# codex-click-chooser-hooks

A public package for Codex hook workflows that turn natural closeout messages
into recent-session-aware `request_user_input` choosers.

## What It Does

This package installs two managed Codex hooks:

- a `SessionStart` hook that loads chooser policy on startup and resume
- a `Stop` hook that decides whether a closeout should end normally or show a short follow-up chooser

The managed hooks are merged additively into `~/.codex/hooks.json`, and the
`uninstall` command removes only the handlers owned by this package.

## What It Includes

- packaged `Stop` and `SessionStart` hook scripts
- additive `install` and `uninstall` commands for `hooks.json`
- `doctor` checks for local package health
- `doctor --live-judge` for a real structured probe against the configured judge endpoint
- a deterministic self-test runner for chooser regressions
- a runtime contract for endpoint and environment configuration

## Current Capabilities

- recent-session-aware chooser logic for Codex `Stop` hooks
- startup policy loading through a paired `SessionStart` hook
- template rendering for interpreter and repo-root aware hook commands
- synthetic regression coverage for explanatory-closeout behavior
- install-time and runtime verification commands for local environments

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
   ├─ explanatory_closure_should_request.json
   └─ fixtures/
      └─ explanatory_closure_recent_lane.jsonl
```

## Quick Start

```bash
cd /path/to/codex-click-chooser-hooks
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli install --dry-run --json
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli doctor --json
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli doctor --live-judge --json
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli self-test --json
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
- injects the current repo root into the managed hook commands
- merges the managed handlers into `~/.codex/hooks.json`
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

Run the deterministic regression case:

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli self-test --json
```

## Uninstall

Preview the removal:

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli uninstall --dry-run --json
```

Remove the managed handlers:

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli uninstall --json
```

`uninstall` removes only the handlers marked as managed by this package and
leaves unrelated hook configuration intact.

## CLI Commands

- `install`: render the hook template and merge the managed handlers into `hooks.json`
- `uninstall`: remove only the managed handlers while leaving unrelated hook config intact
- `doctor`: run static package and file checks
- `doctor --live-judge`: probe the configured judge endpoint with a structured request
- `self-test`: run the deterministic synthetic regression case

## Runtime Configuration

- judge backend and env vars: `docs/runtime-contract.md`

## Managed Hook Entries

The managed template adds one handler under each of these events:

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
