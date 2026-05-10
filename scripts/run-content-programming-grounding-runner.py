#!/usr/bin/env python3
"""Run the content-programming grounding runner.

Usage:
    uv run python scripts/run-content-programming-grounding-runner.py --once
    uv run python scripts/run-content-programming-grounding-runner.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agents.content_programming_grounding_runner import (
    DEFAULT_BOUNDARY_EVENT_PATH,
    DEFAULT_CURSOR_PATH,
    DEFAULT_PUBLIC_EVENT_DECISION_PATH,
    DEFAULT_RUN_ENVELOPE_PATH,
    DEFAULT_SCHEDULED_OPPORTUNITY_PATH,
    DEFAULT_TICK_S,
    ContentProgrammingGroundingRunner,
)
from shared.conversion_broker import DEFAULT_PUBLIC_EVENT_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Content-programming grounding runner")
    parser.add_argument(
        "--scheduled-opportunities", type=Path, default=DEFAULT_SCHEDULED_OPPORTUNITY_PATH
    )
    parser.add_argument("--run-envelopes", type=Path, default=DEFAULT_RUN_ENVELOPE_PATH)
    parser.add_argument("--boundary-events", type=Path, default=DEFAULT_BOUNDARY_EVENT_PATH)
    parser.add_argument(
        "--public-event-decisions", type=Path, default=DEFAULT_PUBLIC_EVENT_DECISION_PATH
    )
    parser.add_argument("--public-events", type=Path, default=DEFAULT_PUBLIC_EVENT_PATH)
    parser.add_argument("--cursor", type=Path, default=DEFAULT_CURSOR_PATH)
    parser.add_argument("--tick-s", type=float, default=DEFAULT_TICK_S)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)

    runner = ContentProgrammingGroundingRunner(
        scheduled_opportunity_path=args.scheduled_opportunities,
        run_envelope_path=args.run_envelopes,
        boundary_event_path=args.boundary_events,
        public_event_decision_path=args.public_event_decisions,
        public_event_path=args.public_events,
        cursor_path=args.cursor,
        tick_s=args.tick_s,
    )
    if args.once:
        batch = runner.run_once()
        print(
            f"processed={batch.processed} skipped={batch.skipped_existing} public_events={batch.metrics.public_events_emitted} "
            f"refused_public_events={batch.metrics.public_events_refused}"
        )
        return 0
    runner.run_forever()
    return 0


def _cli_entrypoint(argv: list[str] | None = None) -> int:
    try:
        return main(argv)
    except Exception as exc:
        print(f"DIDNT_HAPPEN: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 13


if __name__ == "__main__":
    sys.exit(_cli_entrypoint())
