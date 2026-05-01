#!/usr/bin/env -S uv run python
"""Append or dry-run one private operator quality rating.

Examples:

    log-operator-quality-rating.py 4 --axis overall --note "held attention"
    log-operator-quality-rating.py 5 --axis listenable --emission-ref chronicle:abc123
    log-operator-quality-rating.py 3 --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.operator_quality_feedback import (  # noqa: E402
    RATING_AXES,
    SOURCE_SURFACES,
    append_operator_quality_rating,
    build_operator_quality_rating,
    quality_feedback_path,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rating", type=int, help="Subjective quality rating, 1..5.")
    parser.add_argument(
        "--axis",
        dest="rating_axis",
        choices=RATING_AXES,
        default="overall",
        help="Rubric axis this rating scores. Defaults to overall.",
    )
    parser.add_argument(
        "--surface",
        dest="source_surface",
        choices=SOURCE_SURFACES,
        default="cli",
        help="Operator input surface. Defaults to cli.",
    )
    parser.add_argument("--programme-id", default=None)
    parser.add_argument("--condition-id", default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--emission-ref", default=None)
    parser.add_argument("--evidence-ref", action="append", default=[])
    parser.add_argument("--note", default=None)
    parser.add_argument("--event-id", default=None)
    parser.add_argument("--idempotency-key", default=None)
    parser.add_argument(
        "--occurred-at", default=None, help="ISO-8601 timestamp; defaults to now UTC."
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Override JSONL sink path. Defaults to HAPAX_OPERATOR_QUALITY_FEEDBACK_PATH or ~/hapax-state/operator-quality-feedback/ratings.jsonl.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the event JSON and do not write the JSONL sink.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        event = build_operator_quality_rating(
            rating=args.rating,
            rating_axis=args.rating_axis,
            source_surface=args.source_surface,
            occurred_at=args.occurred_at,
            event_id=args.event_id,
            idempotency_key=args.idempotency_key,
            programme_id=args.programme_id,
            condition_id=args.condition_id,
            run_id=args.run_id,
            emission_ref=args.emission_ref,
            evidence_refs=tuple(args.evidence_ref),
            note=args.note,
        )
    except (ValidationError, ValueError) as exc:
        print(f"log-operator-quality-rating: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(event.model_dump_json())
        return 0

    target = args.path if args.path is not None else quality_feedback_path()
    try:
        append_operator_quality_rating(event, path=target)
    except OSError as exc:
        print(f"log-operator-quality-rating: failed to append {target}: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"log-operator-quality-rating: {exc}", file=sys.stderr)
        return 2

    print(
        f"ok event_id={event.event_id} rating={event.rating} axis={event.rating_axis} path={target}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
