#!/usr/bin/env -S uv run python
"""Generate a private SS2 autonomous-speech cycle report.

The report samples autonomous narrative chronicle emissions, joins private
operator-quality ratings when available, and computes the SS2 rubric gates.
It is a local research artifact only; it does not create public claims.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.chronicle import CHRONICLE_FILE  # noqa: E402
from shared.operator_quality_feedback import quality_feedback_path  # noqa: E402
from shared.ss2_cycle_report import (  # noqa: E402
    DEFAULT_SAMPLE_SIZE,
    build_ss2_cycle_report,
    render_ss2_cycle_report_markdown,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cycle-id",
        default="ytb-SS2-cycle",
        help="Cycle identifier to stamp into the private report.",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="Window start as ISO-8601 or unix seconds.",
    )
    parser.add_argument(
        "--until",
        default=None,
        help="Window end as ISO-8601 or unix seconds. Defaults to now UTC.",
    )
    parser.add_argument(
        "--hours",
        type=float,
        default=None,
        help="Alternative to --since: report the last N hours ending at --until/now.",
    )
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    parser.add_argument("--seed", default=None, help="Deterministic sampling seed override.")
    parser.add_argument("--chronicle-path", type=Path, default=CHRONICLE_FILE)
    parser.add_argument(
        "--ratings-path",
        type=Path,
        default=None,
        help="Ratings JSONL path. Defaults to HAPAX_OPERATOR_QUALITY_FEEDBACK_PATH or the canonical private sink.",
    )
    parser.add_argument("--programme-id", default=None)
    parser.add_argument("--condition-id", default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format. Markdown is operator-readable; JSON is machine-readable.",
    )
    parser.add_argument(
        "--no-text",
        action="store_true",
        help="Omit raw narrative text from sampled emission rows.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write report to a file instead of stdout.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        until = _parse_time(args.until) if args.until else datetime.now(UTC)
        since = _resolve_since(args.since, until=until, hours=args.hours)
        report = build_ss2_cycle_report(
            cycle_id=args.cycle_id,
            window_start=since,
            window_end=until,
            sample_size=args.sample_size,
            sample_seed=args.seed,
            chronicle_path=args.chronicle_path,
            ratings_path=args.ratings_path or quality_feedback_path(),
            include_text=not args.no_text,
            programme_id=args.programme_id,
            condition_id=args.condition_id,
            run_id=args.run_id,
        )
    except (OSError, ValidationError, ValueError) as exc:
        print(f"ss2-cycle-report: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        rendered = report.model_dump_json(indent=2) + "\n"
    else:
        rendered = render_ss2_cycle_report_markdown(report)

    if args.output is None:
        print(rendered, end="")
        return 0

    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    except OSError as exc:
        print(f"ss2-cycle-report: failed to write {args.output}: {exc}", file=sys.stderr)
        return 1
    print(f"ok path={args.output} verdict={report.verdict}")
    return 0


def _resolve_since(raw_since: str | None, *, until: datetime, hours: float | None) -> datetime:
    if hours is not None:
        if hours <= 0:
            raise ValueError("--hours must be positive")
        return until - timedelta(hours=hours)
    if raw_since is None:
        raise ValueError("--since is required unless --hours is supplied")
    return _parse_time(raw_since)


def _parse_time(raw: str) -> datetime:
    value = raw.strip()
    if not value:
        raise ValueError("timestamp cannot be empty")
    try:
        return datetime.fromtimestamp(float(value), UTC)
    except ValueError:
        pass
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamps must include timezone information")
    return parsed.astimezone(UTC)


if __name__ == "__main__":
    raise SystemExit(main())
