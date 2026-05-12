#!/usr/bin/env python3
"""Emit scheduler readiness unblock reconcile handoff."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from shared.scheduler_readiness_reconciler import (
    DEFAULT_CC_TASK_ROOT,
    SCHEDULER_RECONCILE_TASK_ID,
    build_scheduler_readiness_reconcile,
    load_cc_task_records,
    render_handoff_markdown,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile scheduler readiness blockers")
    parser.add_argument("--task-root", type=Path, default=DEFAULT_CC_TASK_ROOT)
    parser.add_argument(
        "--assume-current-done",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Treat this reconcile task as done for downstream handoff output.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of markdown")
    args = parser.parse_args(argv)

    assumed = (SCHEDULER_RECONCILE_TASK_ID,) if args.assume_current_done else ()
    report = build_scheduler_readiness_reconcile(
        load_cc_task_records(args.task_root),
        assume_done_task_ids=assumed,
    )
    if args.json:
        print(report.to_json(), end="")
    else:
        print(render_handoff_markdown(report), end="")
    return 0


def _cli_entrypoint(argv: list[str] | None = None) -> int:
    try:
        return main(argv)
    except Exception as exc:
        print(f"DIDNT_HAPPEN: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 13


if __name__ == "__main__":
    sys.exit(_cli_entrypoint())
