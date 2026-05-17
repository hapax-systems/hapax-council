"""CLI for the Hapax frontier triage officer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agents.triage_officer.core import (
    DEFAULT_LIMIT,
    DEFAULT_STATE_PATH,
    DEFAULT_TASK_ROOT,
    run_forever,
    run_triage_pass,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Annotate cc-task routing with frontier triage.")
    parser.add_argument("--task-root", type=Path, default=DEFAULT_TASK_ROOT)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument(
        "--model",
        default=None,
        help="LiteLLM route alias; default is HAPAX_TRIAGE_MODEL or balanced",
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--include-missing", action="store_true")
    parser.add_argument("--write", action="store_true", help="Write annotations back to task notes")
    parser.add_argument("--once", action="store_true", help="Run one pass and exit")
    parser.add_argument("--interval-s", type=float, default=900.0)
    args = parser.parse_args()

    if args.once:
        run = run_triage_pass(
            task_root=args.task_root,
            state_path=args.state_path,
            model_name=args.model,
            write=args.write,
            limit=args.limit,
            include_missing=args.include_missing,
        )
        print(json.dumps(run.to_dict(), indent=2, sort_keys=True))
        return 0 if run.failed == 0 else 1

    run_forever(
        task_root=args.task_root,
        state_path=args.state_path,
        model_name=args.model,
        write=args.write,
        limit=args.limit,
        include_missing=args.include_missing,
        interval_s=args.interval_s,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
