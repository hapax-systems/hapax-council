"""CLI entry-point for the auto-clip Shorts pipeline.

Usage::

    uv run python -m agents.auto_clip --dry-run
    uv run python -m agents.auto_clip --dry-run --minutes 10
    uv run python -m agents.auto_clip --run --minutes 30
    uv run python -m agents.auto_clip --catalog --year 2026 --month 5
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agents.auto_clip.segment_detection import (
    LlmSegmentDetector,
    RollingContext,
    chat_snapshots_to_dicts,
    read_recent_impingements,
)
from shared.transcript_parser import format_as_text, parse_transcript


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m agents.auto_clip",
        description="Auto-clip Shorts pipeline.",
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Print candidates as JSON.")
    mode.add_argument("--run", action="store_true", help="Run full pipeline.")
    mode.add_argument("--catalog", action="store_true", help="Generate monthly catalog.")

    p.add_argument("--minutes", type=float, default=10.0)
    p.add_argument("--transcript", type=Path, default=None)
    p.add_argument(
        "--impingements",
        type=Path,
        default=Path("/dev/shm/hapax-dmn/impingements.jsonl"),
    )
    p.add_argument("--chat", type=Path, default=None)
    p.add_argument("--model", default="balanced")
    p.add_argument("--year", type=int, default=None)
    p.add_argument("--month", type=int, default=None)
    p.add_argument("--output-dir", type=Path, default=None)
    return p.parse_args(argv)


def _load_chat(path: Path | None) -> list[dict]:
    if path is None:
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    snapshots: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            snapshots.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return chat_snapshots_to_dicts(snapshots)


def _load_transcript(path: Path | None) -> str:
    if path is None:
        return ""
    return format_as_text(parse_transcript(path))


def _cmd_detect(args: argparse.Namespace) -> int:
    now = datetime.now(UTC)
    window = timedelta(minutes=args.minutes)
    context = RollingContext(
        window_start=now - window,
        window_end=now,
        transcript_text=_load_transcript(args.transcript),
        impingements=read_recent_impingements(path=args.impingements, window=window, now=now),
        chat_messages=_load_chat(args.chat),
    )

    detector = LlmSegmentDetector(model_alias=args.model)
    candidates = detector.detect(context)

    payload = {
        "window_start": context.window_start.isoformat(),
        "window_end": context.window_end.isoformat(),
        "window_seconds": context.window_seconds,
        "candidate_count": len(candidates),
        "candidates": [c.model_dump(mode="json") for c in candidates],
    }
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from agents.auto_clip.pipeline import run_pipeline

    results = run_pipeline(
        minutes=args.minutes,
        model_alias=args.model,
        dry_run=False,
        output_dir=args.output_dir,
    )
    print(json.dumps({"clips_processed": len(results)}, indent=2))
    return 0


def _cmd_catalog(args: argparse.Namespace) -> int:
    from agents.auto_clip.clip_catalog import write_catalog

    now = datetime.now(UTC)
    year = args.year or now.year
    month = args.month or now.month
    path = write_catalog(year, month)
    if path:
        print(f"Catalog written: {path}")
    else:
        print(f"No clips found for {year:04d}-{month:02d}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.catalog:
        return _cmd_catalog(args)
    if args.run:
        return _cmd_run(args)
    return _cmd_detect(args)


if __name__ == "__main__":
    raise SystemExit(main())
