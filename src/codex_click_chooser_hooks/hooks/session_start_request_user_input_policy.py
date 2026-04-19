#!/usr/bin/env python3

import json


def main() -> int:
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                "If a turn is ending and a short clickable chooser would reduce user "
                "typing or make the next step easier, prefer the `request_user_input` "
                "tool over a prose chooser. This can still apply when one next action is "
                "clearly recommended. Ask one short question with 2-3 natural "
                "single-select options. A combined option such as doing both A and B is "
                "allowed when it fits the context."
            ),
        }
    }
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
