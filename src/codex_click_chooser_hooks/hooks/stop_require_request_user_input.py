#!/usr/bin/env python3

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

JUDGE_URL = os.environ.get("CODEX_RUI_JUDGE_URL", "http://127.0.0.1:10531/v1/responses")
JUDGE_MODEL = os.environ.get("CODEX_RUI_JUDGE_MODEL", "gpt-5.4-mini")
JUDGE_TIMEOUT_SECONDS = float(os.environ.get("CODEX_RUI_JUDGE_TIMEOUT_SECONDS", "8"))
STOP_SELECTION_TERMS = (
    "종료",
    "마무리",
    "finish",
    "stop",
    "enough",
    "그만",
    "충분",
    "괜찮",
)
RECENT_TURNS_LIMIT = 6
RECENT_CHOOSERS_LIMIT = 6
MAX_CONTEXT_TEXT_CHARS = 240

SYSTEM_PROMPT = """You are a Codex stop-hook judge.

Decide whether the assistant should end normally, or instead ask the user a
short single-select `request_user_input` question offering 2-3 natural next
actions.

Your main goal is to reduce user friction. Use `should_request=true` when a
short chooser would likely save the user from having to type an obvious follow-
up, make the next action easier to trigger, or reduce an otherwise likely extra
turn. This often applies after result summaries, diagnosis outcomes,
comparisons, design proposals, status checks, completion reports, or other
closeout messages where the next user response would otherwise be a short go-
ahead such as "continue", "do that", or "let's proceed".

Do not require a chooser for every turn. Simple factual answers, very small
verification replies, or cases where the user already clearly specified the
next action will often end normally.

Explanatory, diagnostic, comparative, or summary-style assistant messages can
still warrant a chooser. Use `should_request=true` when the explanation
naturally leads to one or more concrete follow-up actions that would likely
reduce user typing, even if the message does not explicitly present a menu or
branching list.

Do not require explicit next-step phrases. If a reasonable user would likely
reply with a short go-ahead such as "continue", "do that", "make it concrete",
"go one level deeper", or "apply this", a chooser is often appropriate.

If the assistant message is only a narrow factual confirmation or a tiny
verification answer with no meaningful follow-up action, prefer
`should_request=false`.

Do not treat explanatory completeness by itself as a reason to avoid a chooser.
A well-explained answer may still benefit from a chooser if the next action is
obvious and clickable.

In borderline cases, prefer the option that would make the interaction more
useful and lower-friction for the user. Do not rely on rigid heuristics; judge
from the actual conversational context.

Use the recent session context, not just the last assistant message. Pay
special attention to recent `request_user_input` questions, the options that
were already shown, and the user's selections or free-form answers.

If the same or substantially similar chooser was already shown recently and the
conversation did not materially advance to a new state, prefer
`should_request=false`. Avoid repeating the same chooser across nearby turns,
and avoid re-asking it within the same continued turn after the user already
answered it.

If the user answered a chooser with a free-form instruction, complaint, or
course correction, treat that as real intent to act on rather than as a reason
to ask the same chooser again.

When generating options, prefer context-progressing actions that directly
continue the explanation just given. The chooser should feel like a natural
continuation of the explanation, not a detached or reset-style menu.

If the user already selected a high-level lane recently, do not offer that same
lane again. Move one level deeper and propose the next concrete actions within
that lane.

It is acceptable if there is only one strongly recommended next action, as long
as presenting it as a clickable option would still reduce typing and make the
interaction easier. In that case, include that recommended action plus one or
two natural alternatives such as asking for more detail or stopping here.

Options must fit a single-select UI. They do NOT need to be pairwise exclusive
in semantics. If natural, one option may combine actions, such as doing both A
and B.

Write the header, question, labels, and descriptions in the same language as
the assistant final message unless there is a very strong reason not to.
"""

JUDGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "should_request": {"type": "boolean"},
        "header": {"type": "string"},
        "question": {"type": "string"},
        "options": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "label": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["label", "description"],
            },
        },
    },
    "required": ["should_request", "header", "question", "options"],
}


def parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    text = text.strip()
    if not text:
        return None
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    return value


def extract_input_text(content: Any) -> Optional[str]:
    if not isinstance(content, list):
        return None
    texts: List[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            texts.append(text.strip())
    if not texts:
        return None
    return "\n".join(texts)


def normalize_compare_text(text: Optional[str]) -> str:
    if not isinstance(text, str):
        return ""
    return re.sub(r"\s+", " ", text.strip().lower())


def compact_text(text: Optional[str], max_chars: int = MAX_CONTEXT_TEXT_CHARS) -> str:
    normalized = normalize_compare_text(text)
    if not normalized:
        return ""
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "…"


def is_runtime_control_message(text: Optional[str]) -> bool:
    if not isinstance(text, str):
        return False
    stripped = text.lstrip()
    return stripped.startswith("<turn_aborted>") or stripped.startswith("<hook_prompt")


def read_recent_session_context(
    transcript_path: str, turn_id: str
) -> Dict[str, Any]:
    path = Path(transcript_path)
    if not path.exists():
        return {
            "last_user_message": None,
            "recent_turns": [],
            "recent_choosers": [],
            "current_turn_requests": [],
        }

    turns: List[Dict[str, Any]] = []
    turn_by_id: Dict[str, Dict[str, Any]] = {}
    pending_by_call_id: Dict[str, Dict[str, Any]] = {}
    current_turn: Optional[Dict[str, Any]] = None

    def ensure_turn(current_turn_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not isinstance(current_turn_id, str) or not current_turn_id:
            return None
        existing = turn_by_id.get(current_turn_id)
        if existing is not None:
            return existing
        created = {
            "turn_id": current_turn_id,
            "user_messages": [],
            "assistant_messages": [],
            "requests": [],
        }
        turns.append(created)
        turn_by_id[current_turn_id] = created
        return created

    with path.open() as handle:
        for line in handle:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue

            if item.get("type") == "turn_context":
                current_turn = ensure_turn(item.get("payload", {}).get("turn_id"))
                continue

            if current_turn is None:
                continue

            item_type = item.get("type")
            payload = item.get("payload", {})

            if item_type == "event_msg" and payload.get("type") == "user_message":
                message = payload.get("message")
                if (
                    isinstance(message, str)
                    and message.strip()
                    and not is_runtime_control_message(message)
                ):
                    current_turn["user_messages"].append(message.strip())
                continue

            if item_type != "response_item":
                continue

            if payload.get("type") == "message":
                role = payload.get("role")
                text = extract_input_text(payload.get("content"))
                if text:
                    if role == "user":
                        if not is_runtime_control_message(text):
                            current_turn["user_messages"].append(text)
                    elif role == "assistant":
                        current_turn["assistant_messages"].append(text)
                continue

            if (
                payload.get("type") == "function_call"
                and payload.get("name") == "request_user_input"
            ):
                call_id = payload.get("call_id")
                if not isinstance(call_id, str):
                    continue
                parsed = parse_request_user_input_question(payload.get("arguments", ""))
                if parsed is None:
                    continue
                parsed["call_id"] = call_id
                parsed["turn_id"] = current_turn["turn_id"]
                current_turn["requests"].append(parsed)
                pending_by_call_id[call_id] = parsed
                continue

            if payload.get("type") == "function_call_output":
                call_id = payload.get("call_id")
                if not isinstance(call_id, str):
                    continue
                previous = pending_by_call_id.get(call_id)
                if previous is None:
                    continue
                previous["answers"] = extract_request_user_input_answers(
                    payload.get("output", "")
                )

    target_index = -1
    for index, turn in enumerate(turns):
        if turn.get("turn_id") == turn_id:
            target_index = index
            break
    if target_index == -1:
        return {
            "last_user_message": None,
            "recent_turns": [],
            "recent_choosers": [],
            "current_turn_requests": [],
        }

    recent_turns = turns[max(0, target_index - RECENT_TURNS_LIMIT + 1) : target_index + 1]
    recent_choosers: List[Dict[str, Any]] = []
    for turn in recent_turns:
        for request in turn.get("requests", []):
            recent_choosers.append(request)
    recent_choosers = recent_choosers[-RECENT_CHOOSERS_LIMIT:]

    last_user_message: Optional[str] = None
    current_turn_requests: List[Dict[str, Any]] = []
    if recent_turns:
        current_turn_summary = recent_turns[-1]
        user_messages = current_turn_summary.get("user_messages", [])
        if user_messages:
            last_user_message = user_messages[-1]
        current_turn_requests = list(current_turn_summary.get("requests", []))

    return {
        "last_user_message": last_user_message,
        "recent_turns": recent_turns,
        "recent_choosers": recent_choosers,
        "current_turn_requests": current_turn_requests,
    }


def parse_request_user_input_question(arguments: str) -> Optional[Dict[str, Any]]:
    payload = parse_json_object(arguments)
    if not isinstance(payload, dict):
        return None
    questions = payload.get("questions")
    if not isinstance(questions, list) or not questions:
        return None
    question = questions[0]
    if not isinstance(question, dict):
        return None
    return {
        "header": question.get("header"),
        "question": question.get("question"),
        "options": normalize_options(question.get("options")),
        "answers": [],
    }


def extract_request_user_input_answers(output: str) -> List[str]:
    payload = parse_json_object(output)
    if not isinstance(payload, dict):
        return []
    answers_block = payload.get("answers")
    if not isinstance(answers_block, dict):
        return []
    collected: List[str] = []
    for value in answers_block.values():
        if not isinstance(value, dict):
            continue
        answers = value.get("answers")
        if not isinstance(answers, list):
            continue
        for answer in answers:
            if isinstance(answer, str) and answer.strip():
                collected.append(answer.strip())
    return collected


def chooser_option_labels(chooser: Dict[str, Any]) -> List[str]:
    return [
        compact_text(option.get("label"), 80)
        for option in normalize_options(chooser.get("options"))
        if compact_text(option.get("label"), 80)
    ]


def latest_answer_is_explicit_stop(history: List[Dict[str, Any]]) -> bool:
    if not history:
        return False
    latest_answers = history[-1].get("answers")
    if not isinstance(latest_answers, list):
        return False
    for answer in latest_answers:
        normalized = normalize_compare_text(answer)
        if any(term in normalized for term in STOP_SELECTION_TERMS):
            return True
    return False


def judge_should_request(
    last_assistant_message: str,
    last_user_message: Optional[str],
    recent_turns: List[Dict[str, Any]],
    recent_choosers: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    context_parts = ["Recent session context follows."]
    if recent_turns:
        context_parts.extend(["", "<recent_session_context>"])
        for turn in recent_turns:
            context_parts.append(f'<turn id="{turn.get("turn_id", "")}">')
            user_messages = turn.get("user_messages", [])
            if user_messages:
                context_parts.extend(
                    [
                        "<last_user_message>",
                        compact_text(user_messages[-1]),
                        "</last_user_message>",
                    ]
                )
            requests = turn.get("requests", [])
            if requests:
                context_parts.append("<request_user_input_history>")
                for request in requests[-2:]:
                    question = compact_text(request.get("question"))
                    if question:
                        context_parts.append(f"- question: {question}")
                    option_labels = chooser_option_labels(request)
                    if option_labels:
                        context_parts.append(f"  options: {', '.join(option_labels)}")
                    answers = [
                        compact_text(answer, 120)
                        for answer in request.get("answers", [])
                        if compact_text(answer, 120)
                    ]
                    if answers:
                        context_parts.append(f"  user_answer: {' | '.join(answers)}")
                context_parts.append("</request_user_input_history>")
            context_parts.append("</turn>")
        context_parts.append("</recent_session_context>")
    if isinstance(last_user_message, str) and last_user_message.strip():
        context_parts.extend(
            [
                "",
                "<last_user_message>",
                last_user_message.strip(),
                "</last_user_message>",
            ]
        )
    if recent_choosers:
        context_parts.extend(["", "<recent_chooser_summary>"])
        for chooser in recent_choosers[-3:]:
            question = compact_text(chooser.get("question"))
            if question:
                context_parts.append(f"- question: {question}")
            option_labels = chooser_option_labels(chooser)
            if option_labels:
                context_parts.append(f"  options: {', '.join(option_labels)}")
            answers = [
                compact_text(answer, 120)
                for answer in chooser.get("answers", [])
                if compact_text(answer, 120)
            ]
            if answers:
                context_parts.append(f"  user_answer: {' | '.join(answers)}")
        context_parts.append("</recent_chooser_summary>")
    context_parts.extend(
        [
            "",
            "<assistant_final_message>",
            last_assistant_message,
            "</assistant_final_message>",
            "",
            "Decide whether ending normally is best, or whether a short "
            "`request_user_input` chooser would likely improve the interaction.",
        ]
    )

    body = {
        "model": JUDGE_MODEL,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": SYSTEM_PROMPT}],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "\n".join(context_parts),
                    }
                ],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "request_user_input_decision",
                "schema": JUDGE_SCHEMA,
            }
        },
        "reasoning": {"effort": "none"},
    }
    request = urllib.request.Request(
        JUDGE_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=JUDGE_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None
    output_text = payload.get("output_text")
    if not isinstance(output_text, str):
        output = payload.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    text = block.get("text")
                    if isinstance(text, str):
                        output_text = text
                        break
                if isinstance(output_text, str):
                    break
    if not isinstance(output_text, str):
        return None
    return parse_json_object(output_text)


def normalize_options(raw_options: Any) -> List[Dict[str, str]]:
    normalized = []
    if not isinstance(raw_options, list):
        return normalized
    for item in raw_options[:3]:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        description = item.get("description")
        if isinstance(label, str) and isinstance(description, str) and label.strip():
            normalized.append(
                {"label": label.strip(), "description": description.strip()}
            )
    return normalized


def render_recent_chooser_history(recent_choosers: List[Dict[str, Any]]) -> str:
    if not recent_choosers:
        return ""
    lines = ["Recent chooser history:"]
    for chooser in recent_choosers[-3:]:
        question = compact_text(chooser.get("question"))
        if question:
            lines.append(f"- Question: {question}")
        option_labels = chooser_option_labels(chooser)
        if option_labels:
            lines.append(f"  Options: {', '.join(option_labels)}")
        answers = [
            compact_text(answer, 120)
            for answer in chooser.get("answers", [])
            if compact_text(answer, 120)
        ]
        if answers:
            lines.append(f"  User answer: {' | '.join(answers)}")
    return "\n".join(lines)


def build_block_reason(
    judgment: Dict[str, Any], recent_choosers: List[Dict[str, Any]]
) -> str:
    header = judgment.get("header")
    question = judgment.get("question")
    options = normalize_options(judgment.get("options"))
    recent_history_block = render_recent_chooser_history(recent_choosers)
    anti_repeat_instruction = (
        "Do not ask the same or substantially similar chooser again if the recent "
        "history already offered it. Treat free-form answers as new user intent to "
        "act on, not as a cue to re-ask the same chooser."
    )
    if not isinstance(header, str) or not header.strip():
        header = "Next Step"
    else:
        header = header.strip()[:12]
    if not isinstance(question, str) or not question.strip() or len(options) < 2:
        parts = [
            "Use the `request_user_input` tool now. Do not send another prose answer. "
            "Ask one short question with 2-3 natural next-step options, then wait for "
            "the user's selection.",
        ]
        if recent_history_block:
            parts.extend(["", recent_history_block])
        parts.extend(
            [
                "",
                anti_repeat_instruction,
                "",
                "After the user selects an option, immediately continue in the same turn by "
                "carrying out the selected next action. Treat the selected option as the "
                "user's new instruction. Do not end with an empty or placeholder final "
                "answer. If the selected option asks for more detail, provide that detail "
                "immediately. If the selected option is to stop or finish here, end normally.",
            ]
        )
        return "\n".join(parts)

    option_lines = []
    for index, option in enumerate(options, start=1):
        option_lines.append(
            f"{index}. {option['label']} - {option['description']}"
        )
    rendered_options = "\n".join(option_lines)
    parts = [
        "Use the `request_user_input` tool now. Do not send another prose or bullet-list "
        "answer. Ask the user exactly one short question, using this structure:",
        f"Header: {header}",
        f"Question: {question.strip()}",
        "Options:",
        rendered_options,
        "Then wait for the user's selection.",
    ]
    if recent_history_block:
        parts.extend(["", recent_history_block])
    parts.extend(
        [
            "",
            anti_repeat_instruction,
            "",
            "After the user selects an option, immediately continue in the same turn by "
            "carrying out the selected next action. Treat the selected option as the "
            "user's new instruction. Do not stop right after the `request_user_input` tool "
            "output, and do not end with an empty or placeholder final "
            "answer. If the selected option asks for more detail, provide that detail "
            "immediately. If the selected option is to stop or finish here, end normally.",
        ]
    )
    return "\n".join(parts)


def should_continue(payload: Dict[str, Any]) -> bool:
    message = payload.get("last_assistant_message")
    if not isinstance(message, str) or not message.strip():
        return True
    transcript_path = payload.get("transcript_path")
    turn_id = payload.get("turn_id")
    last_user_message = None
    recent_turns: List[Dict[str, Any]] = []
    recent_choosers: List[Dict[str, Any]] = []
    current_turn_requests: List[Dict[str, Any]] = []
    if isinstance(transcript_path, str) and isinstance(turn_id, str):
        context = read_recent_session_context(transcript_path, turn_id)
        last_user_message = context.get("last_user_message")
        recent_turns = context.get("recent_turns", [])
        recent_choosers = context.get("recent_choosers", [])
        current_turn_requests = context.get("current_turn_requests", [])
    if latest_answer_is_explicit_stop(current_turn_requests):
        return True
    judgment = judge_should_request(
        message,
        last_user_message,
        recent_turns,
        recent_choosers,
    )
    if judgment is None:
        return True
    if judgment.get("should_request") is not True:
        return True
    payload["_judgment"] = judgment
    payload["_recent_choosers"] = recent_choosers
    return False


def main() -> int:
    payload = json.load(sys.stdin)
    if should_continue(payload):
        print(json.dumps({"continue": True}))
        return 0

    print(
        json.dumps(
            {
                "decision": "block",
                "reason": build_block_reason(
                    payload["_judgment"], payload.get("_recent_choosers", [])
                ),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
