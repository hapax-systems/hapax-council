"""Entry point for ``uv run python -m agents.operator_awareness``."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from prometheus_client import start_http_server

from agents.operator_awareness.runner import DEFAULT_TICK_S, AwarenessRunner

METRICS_PORT: int = int(os.environ.get("HAPAX_AWARENESS_METRICS_PORT", "9513"))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agents.operator_awareness",
        description="Awareness state spine: 30s tick aggregator + atomic writer.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="run a single tick then exit (default: daemon loop)",
    )
    parser.add_argument(
        "--tick-s",
        type=float,
        default=DEFAULT_TICK_S,
        help="tick cadence in seconds (default: 30)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("HAPAX_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parse_args(argv)
    runner = AwarenessRunner(tick_s=args.tick_s)

    if args.once:
        result = runner.run_once()
        logging.info("tick result: %s", result)
        return 0

    start_http_server(METRICS_PORT, addr="127.0.0.1")
    runner.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
