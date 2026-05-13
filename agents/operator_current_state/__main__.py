"""One-shot CLI for the private operator current-state renderer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agents.operator_current_state.collector import (
    OperatorCurrentStatePaths,
    collect_operator_current_state,
)
from agents.operator_current_state.renderer import DEFAULT_PAGE_PATH, write_outputs
from agents.operator_current_state.state import DEFAULT_STATE_PATH, parse_timestamp


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="operator-current-state-render")
    parser.add_argument("--once", action="store_true", help="run a single render")
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--page-path", type=Path, default=DEFAULT_PAGE_PATH)
    parser.add_argument(
        "--planning-feed", type=Path, default=OperatorCurrentStatePaths.planning_feed
    )
    parser.add_argument("--requests-dir", type=Path, default=OperatorCurrentStatePaths.requests_dir)
    parser.add_argument("--cc-tasks-dir", type=Path, default=OperatorCurrentStatePaths.cc_tasks_dir)
    parser.add_argument("--claims-dir", type=Path, default=OperatorCurrentStatePaths.claims_dir)
    parser.add_argument("--relay-dir", type=Path, default=OperatorCurrentStatePaths.relay_dir)
    parser.add_argument(
        "--awareness-state", type=Path, default=OperatorCurrentStatePaths.awareness_state
    )
    parser.add_argument(
        "--operator-now-seed", type=Path, default=OperatorCurrentStatePaths.operator_now_seed
    )
    parser.add_argument(
        "--cc-operator-blocking", type=Path, default=OperatorCurrentStatePaths.cc_operator_blocking
    )
    parser.add_argument(
        "--hn-receipts-dir", type=Path, default=OperatorCurrentStatePaths.hn_receipts_dir
    )
    parser.add_argument("--now", default=None, help="override current time as ISO-8601")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    now = parse_timestamp(args.now) if args.now else None
    paths = OperatorCurrentStatePaths(
        planning_feed=args.planning_feed,
        requests_dir=args.requests_dir,
        cc_tasks_dir=args.cc_tasks_dir,
        claims_dir=args.claims_dir,
        relay_dir=args.relay_dir,
        awareness_state=args.awareness_state,
        operator_now_seed=args.operator_now_seed,
        cc_operator_blocking=args.cc_operator_blocking,
        hn_receipts_dir=args.hn_receipts_dir,
    )
    state = collect_operator_current_state(paths, now=now)
    return 0 if write_outputs(state, state_path=args.state_path, page_path=args.page_path) else 1


if __name__ == "__main__":
    sys.exit(main())
