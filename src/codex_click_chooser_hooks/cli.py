from __future__ import annotations

import argparse
import json
from pathlib import Path

from .doctor import run_doctor
from .install import run_install
from .selftest import run_selftest
from .uninstall import run_uninstall


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-click-chooser-hooks")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--live-judge", action="store_true")

    install = sub.add_parser("install")
    install.add_argument("--json", action="store_true")
    install.add_argument("--codex-home", type=Path)
    install.add_argument("--python", dest="python_path")
    install.add_argument("--dry-run", action="store_true")

    uninstall = sub.add_parser("uninstall")
    uninstall.add_argument("--json", action="store_true")
    uninstall.add_argument("--codex-home", type=Path)
    uninstall.add_argument("--dry-run", action="store_true")

    selftest = sub.add_parser("self-test")
    selftest.add_argument("--json", action="store_true")
    selftest.add_argument("--case", type=Path)

    layout = sub.add_parser("print-layout")
    layout.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "doctor":
        report = run_doctor(live_judge=args.live_judge)
    elif args.command == "install":
        report = run_install(
            codex_home=args.codex_home,
            python_path=args.python_path,
            dry_run=args.dry_run,
        )
    elif args.command == "uninstall":
        report = run_uninstall(
            codex_home=args.codex_home,
            dry_run=args.dry_run,
        )
    elif args.command == "self-test":
        report = run_selftest(args.case)
    else:
        report = {
            "repo": "codex-click-chooser-hooks",
            "paths": [
                "src/codex_click_chooser_hooks/install.py",
                "src/codex_click_chooser_hooks/uninstall.py",
                "src/codex_click_chooser_hooks/merge.py",
                "src/codex_click_chooser_hooks/runtime_paths.py",
                "src/codex_click_chooser_hooks/hooks",
                "src/codex_click_chooser_hooks/templates",
                "tests/fixtures",
                "docs",
            ],
        }

    if getattr(args, "json", False):
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(report)
    return 0 if report.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
