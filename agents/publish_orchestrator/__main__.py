"""systemd entry-point for the publish orchestrator daemon."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from prometheus_client import start_http_server

from agents.publish_orchestrator.orchestrator import (
    DEFAULT_TICK_S,
    METRICS_PORT_DEFAULT,
    Orchestrator,
)

log = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agents.publish_orchestrator",
        description="Watch ~/hapax-state/publish/inbox/ for approved artifacts; "
        "dispatch to all configured surfaces in parallel.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="process pending artifacts then exit (default: daemon loop)",
    )
    parser.add_argument(
        "--tick-s",
        type=float,
        default=DEFAULT_TICK_S,
        help=f"daemon-loop wakeup cadence in seconds (default: {DEFAULT_TICK_S})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("HAPAX_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parse_args(argv)

    orch = Orchestrator(tick_s=args.tick_s)

    if args.once:
        handled = orch.run_once()
        log.info("processed %d artifact(s)", handled)
        return 0

    metrics_port = int(
        os.environ.get("HAPAX_PUBLISH_ORCHESTRATOR_METRICS_PORT", METRICS_PORT_DEFAULT)
    )
    start_http_server(metrics_port, addr="127.0.0.1")
    orch.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
