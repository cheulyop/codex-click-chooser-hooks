# codex-click-chooser-hooks

**English** | [한국어](README.ko.md) | [日本語](README.ja.md) | [简体中文](README.zh-CN.md)

Translations may lag behind the English version.

Codex hooks that help a turn end the right way: finish normally, continue
automatically, or ask one clear follow-up question.

## What It Does

This package installs two Codex hooks:

- a `SessionStart` hook that loads a short closeout policy into the Codex
  session on startup and resume
- a `Stop` hook that decides whether a closeout should end normally, auto-continue in the same turn, or show a short follow-up chooser

The judge model picks the `end` / `auto_continue` / `ask_user` mode by looking
at the recent conversation context. When `ask_user` is needed, Codex generates
the actual chooser question and options from the live session context.

The hook entries from this package are merged additively into
`~/.codex/hooks.json`, and `uninstall` removes only the entries added by this
package.

## How It Works

1. `SessionStart` runs on startup and resume and writes a short policy into
   `hookSpecificOutput.additionalContext` for the Codex session.
   - it tells Codex to prefer automatic same-turn follow-through when one
     clear next step exists
   - it tells Codex to use `request_user_input` only when the user really
     needs to choose among materially different next paths
2. `Stop` runs when a turn is about to end.
3. The `Stop` hook rebuilds recent turn history from the transcript. Here, a
   `turn` is one reconstructed conversation unit keyed by `turn_id`. Internally,
   each turn keeps one ordered `entries` stream instead of separate raw
   `user_messages`, `assistant_messages`, `requests`, and `timeline` fields.
4. For the current turn, it derives a compact summary instead of shipping the
   whole transcript:
   - recent turn window: up to `6` turns
   - chooser history window: up to `6` recent choosers
   - current-turn message-sequence window: up to `12` derived message entries,
     reconstructed from the ordered `entries` stream
   - current-turn counts such as assistant message count and chooser count
5. The hook sends that compact prompt to a judge model.
6. The judge returns one of three structured modes:
   - `end`: let the assistant finish normally
   - `auto_continue`: keep going in the same turn without asking the user
   - `ask_user`: stop and let Codex ask one real follow-up chooser
7. The main Codex session carries out that result:
   - `end`: the turn closes normally
   - `auto_continue`: Codex receives a continue instruction and keeps moving
   - `ask_user`: Codex generates the actual `request_user_input` question and
     options from the live session context
8. The hook appends a `stop_hook_judgment` debug event to the transcript so
   you can inspect what happened later with `observe`.

The judge model only decides the mode and returns a short rationale plus an
optional `continue_instruction`. It does not generate the chooser itself.

## Judge Endpoint

The judge side requires:

- an OpenAI-compatible `responses` endpoint
- structured JSON output that matches the hook schema
- a response that arrives within the hook timeout window
- support for returning `mode`, `continue_instruction`, and `rationale`

Default judge settings:

- endpoint: `http://127.0.0.1:10531/v1/responses`
- model: `gpt-5.4`
- reasoning effort: `medium`
- timeout: `30` seconds

You can change those with:

- `CODEX_RUI_JUDGE_URL`
- `CODEX_RUI_JUDGE_MODEL`
- `CODEX_RUI_JUDGE_REASONING_EFFORT`
- `CODEX_RUI_JUDGE_TIMEOUT_SECONDS`

For the full runtime contract, see [docs/runtime-contract.md](docs/runtime-contract.md).

## What The Judge Sees

The stop hook does not send the raw transcript wholesale. It sends a compact
text prompt that reflects the current lane of work.

Current-turn summarization works like this:

1. rebuild recent turns from the transcript as ordered `entries`
2. derive the current turn's message sequence view and chooser history from those
   entries
3. compute coarse turn-shape counters such as assistant message count and
   chooser count
4. keep the derived message sequence from the latest user message onward as the main
   current-turn block
5. attach recent chooser history separately so the judge can see what was
   already offered and selected

The raw turn shape now looks like this:

```python
turn = {
  "turn_id": "t2",
  "entries": [
    {"kind": "message", "role": "user", "text": "U1"},
    {"kind": "message", "role": "assistant", "text": "A1"},
    {"kind": "request_user_input", "call_id": "c1", "...": "..."},
    {"kind": "request_user_input_output", "call_id": "c1", "answers": ["A"]},
    {"kind": "message", "role": "user", "text": "U2"},
    {"kind": "message", "role": "assistant", "text": "A2"},
  ],
}
```

There is no raw `timeline` field anymore. From that ordered stream, the hook
derives the judge-facing `last_user_message`, `recent_choosers`,
`timeline_since_last_user`, and count fields.

The judge prompt still uses the block name
`<current_turn_timeline_since_last_user>`, but that block is now a derived view
from `entries`, not a raw stored field.

The current shape is:

```text
Recent session context follows.

<recent_session_context>
<turn id="...">
<last_user_message>
...
</last_user_message>
</turn>
</recent_session_context>

<current_turn_state>
- user_message_count: ...
- assistant_message_count: ...
- request_user_input_count: ...
- assistant_messages_since_last_user: ...
</current_turn_state>

<current_turn_timeline_since_last_user>
- user|assistant: ...
</current_turn_timeline_since_last_user>

<recent_chooser_summary>
- question: ...
  options: ...
  user_answer: ...
</recent_chooser_summary>

<assistant_final_message>
...
</assistant_final_message>
```

In practice, that means the judge sees:

- recent turn-by-turn user prompts
- how much assistant work already happened in the current turn
- the current turn timeline since the latest user message
- the most recent chooser history and user selections
- the final assistant message that is about to end the turn

This prompt is intentionally narrower than earlier revisions. The current
implementation already removed several duplicated projections such as:

- top-level duplicate `last_user_message`
- `current_turn_user_messages`
- `current_turn_assistant_history_before_final`
- `current_turn_recent_timeline`
- turn-local `request_user_input_history`

## What The Judge Returns

The judge responds with structured JSON matching this schema:

```json
{
  "mode": "end | auto_continue | ask_user",
  "continue_instruction": "string",
  "rationale": "string"
}
```

Expected behavior by mode:

- `end`: `continue_instruction` is usually empty
- `auto_continue`: `continue_instruction` must be non-empty
- `ask_user`: `continue_instruction` may be empty because Codex will generate
  the chooser itself

Example outputs:

```json
{
  "mode": "end",
  "continue_instruction": "",
  "rationale": "The reply already closes the current lane and does not tee up a meaningful next step."
}
```

```json
{
  "mode": "auto_continue",
  "continue_instruction": "Update the stop-hook schema to use mode=end|auto_continue|ask_user, then split the branch handling for ask_user and auto_continue.",
  "rationale": "The user already chose the implementation lane and one next action is clearly dominant."
}
```

```json
{
  "mode": "ask_user",
  "continue_instruction": "",
  "rationale": "Two materially different next paths are open and the user should pick between them."
}
```

## What The User Experiences

At the UI level, the behavior feels like this:

- if the turn is truly done, Codex just ends normally
- if one next action is obvious, Codex keeps going without making you click
- if a real decision is needed, Codex shows one chooser and continues in the
  same turn after you select it

Typical examples:

- Tiny factual confirmation:
  - user asks: `Does the hook template still point at the packaged script?`
  - assistant ends with: `Confirmed. The hook template still points at the packaged stop-hook script.`
  - expected mode: `end`
- Clear follow-through:
  - assistant ends with: `The patch is in. The next step is to run the verification command.`
  - expected mode: `auto_continue`
  - expected output shape:

    ```json
    {
      "mode": "auto_continue",
      "continue_instruction": "Run the verification command next.",
      "rationale": "One dominant follow-through step is already clear."
    }
    ```
- Real branch choice:
  - assistant ends with: `We can either inspect more mode_end cases or tighten the prompt wording.`
  - expected mode: `ask_user`
  - Codex then writes the actual chooser in the same turn

## Stop-Hook Branch Handling

After the judge returns, the stop hook turns that result into one of two block
instructions or lets the turn end:

- `build_auto_continue_block_reason(...)` tells Codex not to ask another
  question and to continue immediately with the supplied instruction
- `build_ask_user_block_reason(...)` tells Codex to call
  `request_user_input` and generate the chooser from session context
- `end` does not produce a follow-up block reason; the turn simply closes

There is also one safety layer after the judge:

- if the raw judge response says `end`, but the assistant message itself
  clearly surfaces multiple follow-up choices, the hook can promote that to
  `ask_user`
- if the raw judge response says `end`, but the assistant message clearly names
  one next step, the hook can promote that to `auto_continue`

That safeguard is meant to catch obviously premature `end` decisions.

Here, "clearly" is not decided by another LLM call. The current implementation
uses lightweight message-pattern checks over the final assistant message.
Examples include phrases like:

- follow-up choice patterns: `we can either`, `options like`, `or we can`,
  `아니면`, `또는`
- next-step patterns: `the next step is to ...`, `the obvious next step is to ...`,
  `다음 단계는 ...`, `다음으로는 ...`

This is intentionally a narrow heuristic backstop. It is useful when the judge
returns an obviously premature `end`, but it is not a full semantic parser.

## Observability And Debugging

Every stop-hook decision appends a transcript debug event with fields such as:

- `status`
- `mode`
- `rationale`
- `continue_instruction`
- `judgment_override`
- `judge_failure_reason`
- `current_turn_context`

That data feeds the `observe` CLI, which is useful for calibration work:

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli observe --json
```

If the judge endpoint is unavailable or returns malformed structured output,
the hook records `status="judge_unavailable"` with a best-effort
`judge_failure_reason` and falls back to letting the turn end normally.

Because this hook is ultimately driven by an LLM judge, it will not match
every operator's expectation out of the box. This repo intentionally makes the
behavior easy to inspect and customize:

- `observe` lets you review real transcript-level judgments
- transcript debug events preserve rationale, mode, override, and turn-shape
  data
- the judge prompt is local code in
  `src/codex_click_chooser_hooks/hooks/stop_require_request_user_input.py`
- the post-judge override heuristics are also local and editable

The intended workflow is: inspect real outcomes, adjust the prompt or
heuristics, then rerun `self-test`, `doctor`, and `observe`.

## What It Includes

- packaged `Stop` and `SessionStart` hook scripts
- additive `install` and `uninstall` commands for `hooks.json`
- `doctor` checks for local package health
- `doctor --live-judge` for a real structured probe against the configured judge endpoint
- a deterministic self-test runner for follow-up decision regressions
- an `observe` CLI for transcript-level judge calibration and mode/rationale inspection
- a runtime contract for endpoint and environment configuration
- transcript debug events that record the judge mode and short rationale

## Current Capabilities

- context-aware `end` / `auto_continue` / `ask_user` logic for Codex `Stop` hooks
- an `end` override guard when the assistant message itself surfaces a follow-up choice or a clear next step
- startup policy loading through a paired `SessionStart` hook
- template rendering for interpreter and repo-root aware hook commands
- synthetic regression coverage for ask-user, auto-continue, and end behavior
- install-time and runtime verification commands for local environments
- transcript-based observability for mode mix, overrides, and rationale patterns

## Layout

```text
codex-click-chooser-hooks/
├─ README.md
├─ LICENSE
├─ pyproject.toml
├─ docs/
│  └─ runtime-contract.md
├─ src/
│  └─ codex_click_chooser_hooks/
│     ├─ __init__.py
│     ├─ cli.py
│     ├─ doctor.py
│     ├─ install.py
│     ├─ observe.py
│     ├─ uninstall.py
│     ├─ merge.py
│     ├─ runtime_paths.py
│     ├─ selftest.py
│     ├─ hooks/
│     │  ├─ session_start_request_user_input_policy.py
│     │  └─ stop_require_request_user_input.py
│     └─ templates/
│        └─ hooks.json
└─ tests/
   ├─ *.json
   └─ fixtures/
      └─ *.jsonl
```

## Quick Start

```bash
cd /path/to/codex-click-chooser-hooks
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli install --dry-run --json
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli doctor --json
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli doctor --live-judge --json
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli self-test --json
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli observe --json
```

## Install

Preview the changes first:

```bash
cd /path/to/codex-click-chooser-hooks
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli install --dry-run --json
```

Apply the install:

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli install --json
```

What `install` does:

- renders the hook template with the current Python interpreter path
- injects the current repo root into the hook commands added by this package
- merges the hook entries from this package into `~/.codex/hooks.json`
- creates a backup before writing if the file changes

## Verify

Run the static checks:

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli doctor --json
```

Run the live judge probe:

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli doctor --live-judge --json
```

Run the deterministic regression suite:

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli self-test --json
```

Inspect recent stop-hook judgments for this repo:

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli observe --json
```

Focus on one historical session:

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli observe --session-id 019da87f-2a7f-7870-a5aa-84a28745e9db --json
```

Scan all current and archived Codex sessions:

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli observe --all-cwds --include-archived --json
```

Filter calibration output to a date window:

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli observe --all-cwds --date-from 2026-04-20 --date-to 2026-04-20 --json
```

## Uninstall

Preview the removal:

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli uninstall --dry-run --json
```

Remove the hook entries added by this package:

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli uninstall --json
```

`uninstall` removes only the hook entries added by this package and
leaves unrelated hook configuration intact.

## CLI Commands

- `install`: render the hook template and merge the hook entries from this package into `hooks.json`
- `uninstall`: remove only the hook entries from this package while leaving unrelated hook config intact
- `doctor`: run static package and file checks
- `doctor --live-judge`: probe the configured judge endpoint with a structured request
- `self-test`: run the deterministic synthetic regression suite
- `observe`: summarize recorded `stop_hook_judgment` events for calibration work
  - supports repo-scoped or all-cwd scans, archived session inclusion, and date filtering

## Runtime Configuration

- judge backend and env vars: `docs/runtime-contract.md`

## Installed Hook Entries

The package template adds one handler under each of these events:

- `SessionStart` with matcher `startup|resume`
- `Stop`

The commands point at:

- `src/codex_click_chooser_hooks/hooks/session_start_request_user_input_policy.py`
- `src/codex_click_chooser_hooks/hooks/stop_require_request_user_input.py`

## Future Improvements

- harden uninstall coverage for repo moves and renamed interpreters
- expand installer safety checks around existing user config edge cases
- deepen `doctor --live-judge` with richer failure hints if needed
- add more release-ready examples and regression cases
