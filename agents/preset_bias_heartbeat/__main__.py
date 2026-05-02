"""CLI entry point — ``python -m agents.preset_bias_heartbeat``.

Runs :func:`agents.preset_bias_heartbeat.run_forever` with default
cadence + freshness, configured logging, and a clean SIGTERM exit
path. The systemd unit at ``systemd/units/hapax-preset-bias-heartbeat.service``
calls this entry point.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from typing import NoReturn

from agents._log_setup import configure_logging
from agents.preset_bias_heartbeat.heartbeat import (
    DEFAULT_FRESHNESS_S,
    DEFAULT_TICK_S,
    RECRUITMENT_FILE,
    run_forever,
)

log = logging.getLogger(__name__)


def _install_sigterm_handler() -> None:
    """Exit cleanly on SIGTERM so systemd's stop is graceful."""

    def _handle(signum: int, frame: object) -> NoReturn:
        del frame
        log.info("preset.bias heartbeat: received signal %d, exiting", signum)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "preset.bias heartbeat fallback — backstop chain mutation when LLM recruitment stalls"
        ),
        prog="python -m agents.preset_bias_heartbeat",
    )
    parser.add_argument(
        "--tick-s",
        type=float,
        default=DEFAULT_TICK_S,
        help=f"Seconds between ticks (default: {DEFAULT_TICK_S})",
    )
    parser.add_argument(
        "--freshness-s",
        type=float,
        default=DEFAULT_FRESHNESS_S,
        help=(
            f"Maximum age (seconds) of an LLM-driven preset.bias entry "
            f"before the heartbeat fires (default: {DEFAULT_FRESHNESS_S})"
        ),
    )
    parser.add_argument(
        "--path",
        type=str,
        default=str(RECRUITMENT_FILE),
        help=f"recent-recruitment.json path (default: {RECRUITMENT_FILE})",
    )
    args = parser.parse_args(argv)

    configure_logging(agent="preset-bias-heartbeat")
    _install_sigterm_handler()

    from pathlib import Path

    run_forever(
        tick_s=args.tick_s,
        freshness_s=args.freshness_s,
        path=Path(args.path),
    )


if __name__ == "__main__":
    main()
