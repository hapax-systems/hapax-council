"""CLI entry point for the conversion broker daemon."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from prometheus_client import start_http_server

from agents.conversion_broker.runner import (
    DEFAULT_BOUNDARY_EVENT_PATH,
    DEFAULT_CURSOR_PATH,
    DEFAULT_RUN_ENVELOPE_PATH,
    DEFAULT_TICK_S,
    ConversionBrokerRunner,
)
from shared.conversion_broker import DEFAULT_CANDIDATE_PATH, DEFAULT_PUBLIC_EVENT_PATH

METRICS_PORT_DEFAULT = 9513


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value) if value else default


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agents.conversion_broker",
        description="Surface content-programme conversion candidates to publication_bus.",
    )
    parser.add_argument("--once", action="store_true", help="Process current JSONL files once")
    parser.add_argument(
        "--run-envelope-path",
        type=Path,
        default=_env_path("HAPAX_CONTENT_PROGRAMME_RUN_ENVELOPE_PATH", DEFAULT_RUN_ENVELOPE_PATH),
    )
    parser.add_argument(
        "--boundary-event-path",
        type=Path,
        default=_env_path("HAPAX_PROGRAMME_BOUNDARY_EVENT_PATH", DEFAULT_BOUNDARY_EVENT_PATH),
    )
    parser.add_argument(
        "--candidate-path",
        type=Path,
        default=_env_path("HAPAX_CONVERSION_BROKER_CANDIDATE_PATH", DEFAULT_CANDIDATE_PATH),
    )
    parser.add_argument(
        "--public-event-path",
        type=Path,
        default=_env_path("HAPAX_RESEARCH_VEHICLE_PUBLIC_EVENT_PATH", DEFAULT_PUBLIC_EVENT_PATH),
    )
    parser.add_argument(
        "--cursor-path",
        type=Path,
        default=_env_path("HAPAX_CONVERSION_BROKER_CURSOR_PATH", DEFAULT_CURSOR_PATH),
    )
    parser.add_argument(
        "--tick-s",
        type=float,
        default=float(os.environ.get("HAPAX_CONVERSION_BROKER_TICK_S", DEFAULT_TICK_S)),
    )
    parser.add_argument(
        "--metrics-port",
        type=int,
        default=int(os.environ.get("HAPAX_CONVERSION_BROKER_METRICS_PORT", METRICS_PORT_DEFAULT)),
    )
    parser.add_argument("--no-metrics", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("HAPAX_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _build_parser().parse_args(argv)
    if not args.no_metrics:
        start_http_server(args.metrics_port, addr="127.0.0.1")
        logging.getLogger(__name__).info(
            "conversion broker metrics on 127.0.0.1:%d",
            args.metrics_port,
        )
    runner = ConversionBrokerRunner(
        run_envelope_path=args.run_envelope_path,
        boundary_event_path=args.boundary_event_path,
        public_event_path=args.public_event_path,
        candidate_path=args.candidate_path,
        cursor_path=args.cursor_path,
        tick_s=args.tick_s,
    )
    if args.once:
        handled = runner.run_once()
        logging.getLogger(__name__).info("conversion broker handled %d boundaries", handled)
        return 0
    runner.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
