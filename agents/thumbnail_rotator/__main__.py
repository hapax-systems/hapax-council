"""Entry point for ``uv run python -m agents.thumbnail_rotator``."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from prometheus_client import start_http_server

from agents.thumbnail_rotator.rotator import (
    DEFAULT_TICK_S,
    ThumbnailRotator,
)
from agents.thumbnail_rotator.salience_trigger import SalienceTrigger

METRICS_PORT: int = int(os.environ.get("HAPAX_THUMBNAIL_METRICS_PORT", "9512"))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agents.thumbnail_rotator",
        description="Rotate YouTube thumbnails from compositor snapshots.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="log rotation intent without calling the YouTube API",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="process one rotation then exit (default: daemon loop)",
    )
    parser.add_argument(
        "--tick-s",
        type=float,
        default=DEFAULT_TICK_S,
        help="rotation cadence in seconds (fixed mode only; default: 1800)",
    )
    parser.add_argument(
        "--mode",
        choices=("fixed", "salience"),
        default="salience",
        help=(
            "rotation trigger mode. 'salience' (default): fire on chronicle "
            "high-salience event + 120s chapter stability. 'fixed': fire on "
            "the --tick-s cadence."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("HAPAX_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parse_args(argv)

    rotator = ThumbnailRotator(
        dry_run=args.dry_run,
        tick_s=args.tick_s,
    )

    if args.once:
        result = rotator.run_once()
        logging.info("rotation result: %s", result)
        return 0

    start_http_server(METRICS_PORT, addr="127.0.0.1")
    if args.mode == "salience":
        rotator.run_forever_salience_triggered(SalienceTrigger())
    else:
        rotator.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
