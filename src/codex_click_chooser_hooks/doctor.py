from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any


def summarize_status(check: dict[str, Any]) -> str:
    status = check.get("status")
    if status in {"pass", "warn", "fail"}:
        return status
    return "fail"


def package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def run_live_judge_probe() -> dict[str, Any]:
    try:
        stop_hook = import_module(
            "codex_click_chooser_hooks.hooks.stop_require_request_user_input"
        )
    except Exception as exc:
        return {
            "status": "fail",
            "error": f"failed to import stop hook module: {exc}",
        }

    probe_message = (
        "That covers the explanation.\n\n"
        "If helpful, we can continue with one of two obvious next steps.\n"
        "We can add a concrete example or refine the chooser decision rules."
    )
    try:
        judgment = stop_hook.judge_should_request(
            probe_message,
            None,
            [],
            [],
        )
    except Exception as exc:
        return {
            "status": "fail",
            "url": stop_hook.JUDGE_URL,
            "model": stop_hook.JUDGE_MODEL,
            "timeout_seconds": stop_hook.JUDGE_TIMEOUT_SECONDS,
            "error": f"judge probe raised an exception: {exc}",
        }

    if not isinstance(judgment, dict):
        return {
            "status": "fail",
            "url": stop_hook.JUDGE_URL,
            "model": stop_hook.JUDGE_MODEL,
            "timeout_seconds": stop_hook.JUDGE_TIMEOUT_SECONDS,
            "error": "judge returned no structured response",
        }

    options = stop_hook.normalize_options(judgment.get("options"))
    should_request = judgment.get("should_request")
    if (
        not isinstance(should_request, bool)
        or not isinstance(judgment.get("header"), str)
        or not isinstance(judgment.get("question"), str)
        or len(options) < 2
    ):
        return {
            "status": "fail",
            "url": stop_hook.JUDGE_URL,
            "model": stop_hook.JUDGE_MODEL,
            "timeout_seconds": stop_hook.JUDGE_TIMEOUT_SECONDS,
            "error": "judge response did not satisfy the expected schema shape",
            "raw_judgment": judgment,
        }

    status = "pass" if should_request else "warn"
    result = {
        "status": status,
        "url": stop_hook.JUDGE_URL,
        "model": stop_hook.JUDGE_MODEL,
        "timeout_seconds": stop_hook.JUDGE_TIMEOUT_SECONDS,
        "should_request": should_request,
        "option_count": len(options),
        "header": judgment.get("header", "").strip(),
        "question": judgment.get("question", "").strip(),
    }
    if not should_request:
        result["note"] = (
            "judge endpoint is reachable, but the sample explanatory closeout did "
            "not produce a chooser recommendation"
        )
    return result


def run_doctor(live_judge: bool = False) -> dict:
    root = package_root()
    checks = {
        "package_root_exists": {"status": "pass" if root.exists() else "fail"},
        "license_file": {
            "status": "pass" if (root / "LICENSE").exists() else "fail"
        },
        "stop_hook_script": {
            "status": "pass"
            if (root / "src/codex_click_chooser_hooks/hooks/stop_require_request_user_input.py").exists()
            else "fail"
        },
        "sessionstart_hook_script": {
            "status": "pass"
            if (root / "src/codex_click_chooser_hooks/hooks/session_start_request_user_input_policy.py").exists()
            else "fail"
        },
        "install_module": {
            "status": "pass"
            if (root / "src/codex_click_chooser_hooks/install.py").exists()
            else "fail"
        },
        "uninstall_module": {
            "status": "pass"
            if (root / "src/codex_click_chooser_hooks/uninstall.py").exists()
            else "fail"
        },
        "merge_module": {
            "status": "pass"
            if (root / "src/codex_click_chooser_hooks/merge.py").exists()
            else "fail"
        },
        "hooks_template": {
            "status": "pass"
            if (root / "src/codex_click_chooser_hooks/templates/hooks.json").exists()
            else "fail"
        },
        "selftest_fixture": {
            "status": "pass"
            if (root / "tests/fixtures/explanatory_closure_recent_lane.jsonl").exists()
            else "fail"
        },
    }
    if live_judge:
        checks["live_judge"] = run_live_judge_probe()
    ok = all(summarize_status(item) != "fail" for item in checks.values())
    return {
        "ok": ok,
        "repo_root": str(root),
        "live_judge_requested": live_judge,
        "checks": checks,
    }
