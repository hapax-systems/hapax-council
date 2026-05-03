"""CLI entry point — ``python -m agents.parametric_modulation_heartbeat``.

Runs :func:`agents.parametric_modulation_heartbeat.run_forever` with
default cadence + paths, configured logging, and a clean SIGTERM exit
path. The systemd unit at
``systemd/units/hapax-parametric-modulation-heartbeat.service``
calls this entry point.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from pathlib import Path
from typing import NoReturn

from agents._log_setup import configure_logging
from agents.parametric_modulation_heartbeat.heartbeat import (
    DEFAULT_TICK_S,
    RECRUITMENT_FILE,
    UNIFORMS_FILE,
    run_forever,
)

log = logging.getLogger(__name__)


def _install_sigterm_handler() -> None:
    """Exit cleanly on SIGTERM so systemd's stop is graceful."""

    def _handle(signum: int, frame: object) -> NoReturn:
        del frame
        log.info("parametric modulation heartbeat: received signal %d, exiting", signum)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "parametric modulation heartbeat — constrained parameter walker "
            "(supersedes preset-bias heartbeat per operator directive)"
        ),
        prog="python -m agents.parametric_modulation_heartbeat",
    )
    parser.add_argument(
        "--tick-s",
        type=float,
        default=DEFAULT_TICK_S,
        help=f"Seconds between ticks (default: {DEFAULT_TICK_S})",
    )
    parser.add_argument(
        "--uniforms-path",
        type=str,
        default=str(UNIFORMS_FILE),
        help=f"uniforms.json path (default: {UNIFORMS_FILE})",
    )
    parser.add_argument(
        "--recruitment-path",
        type=str,
        default=str(RECRUITMENT_FILE),
        help=f"recent-recruitment.json path (default: {RECRUITMENT_FILE})",
    )
    args = parser.parse_args(argv)

    configure_logging(agent="parametric-modulation-heartbeat")
    _install_sigterm_handler()

    run_forever(
        tick_s=args.tick_s,
        uniforms_path=Path(args.uniforms_path),
        recruitment_path=Path(args.recruitment_path),
    )


if __name__ == "__main__":
    main()
