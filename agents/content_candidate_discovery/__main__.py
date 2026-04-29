"""Runnable content candidate discovery producer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agents.content_candidate_discovery.runner import run_once


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Emit Hapax content opportunity candidates")
    parser.add_argument("--once", action="store_true", help="Run one discovery pass")
    parser.add_argument("--policy", type=Path, default=None)
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--audit", type=Path, default=None)
    parser.add_argument("--health", type=Path, default=None)
    parser.add_argument("--print-json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    health = run_once(
        policy_path=args.policy,
        input_path=args.input,
        output_path=args.output,
        audit_path=args.audit,
        health_path=args.health,
    )
    if args.print_json:
        print(json.dumps(health, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
