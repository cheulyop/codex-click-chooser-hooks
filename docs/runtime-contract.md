# Runtime Contract

`codex-click-chooser-hooks` is a public package for Codex hook workflows.

This document captures the minimal contract for the judge backend and the
install-time template rendering flow.

## Judge Backend

The `Stop` hook sends the current turn closeout to a small judge model and
decides whether to end normally or show a `request_user_input` chooser.

Defaults:

- endpoint: `http://127.0.0.1:10531/v1/responses`
- model: `gpt-5.4-mini`
- timeout: `8` seconds

Implementation:

- `src/codex_click_chooser_hooks/hooks/stop_require_request_user_input.py`

The judge backend must:

- provide an OpenAI-compatible `responses` endpoint
- support JSON structured output
- respond within the hook timeout window

## Environment Variables

### `CODEX_RUI_JUDGE_URL`

- meaning: endpoint called by the stop hook
- default: `http://127.0.0.1:10531/v1/responses`
- use when: your local proxy port or gateway address differs

```bash
export CODEX_RUI_JUDGE_URL=http://127.0.0.1:10531/v1/responses
```

### `CODEX_RUI_JUDGE_MODEL`

- meaning: model slug used for chooser judgment
- default: `gpt-5.4-mini`
- use when: you want to tune cost, latency, or decision behavior

```bash
export CODEX_RUI_JUDGE_MODEL=gpt-5.4-mini
```

### `CODEX_RUI_JUDGE_TIMEOUT_SECONDS`

- meaning: time to wait for the judge response
- default: `8`
- use when: the endpoint is slower or the timeout is too aggressive

```bash
export CODEX_RUI_JUDGE_TIMEOUT_SECONDS=8
```

## Install-Time Rendering

The template file `src/codex_click_chooser_hooks/templates/hooks.json`
contains `{{python}}` and `{{repo_root}}` placeholders.

The installer renders the template and then merges the resulting commands into
the user's `hooks.json`.

- `{{python}}`: Python interpreter path used at `install` time
- `{{repo_root}}`: repo root path where the package is installed

The template stays generic; only rendered commands are written into user
config.

## Current Non-Goals

This package does not currently cover:

- background service installation
- platform-specific deployment guides
- hosted judge infrastructure provisioning

## Recommended Verification

```bash
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli doctor --json
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli doctor --live-judge --json
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli self-test --json
PYTHONPATH=src python3 -m codex_click_chooser_hooks.cli install --dry-run --json
```

`doctor --live-judge` performs a structured probe using the same endpoint and
model configuration as the real hook.

- endpoint unreachable or structured output failure: `fail`
- endpoint reachable but no chooser recommendation for the sample closeout: `warn`
- endpoint reachable and chooser recommendation returned as expected: `pass`
