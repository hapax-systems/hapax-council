"""CLI entry-point for the LLM-assisted segment-detection layer.

Usage::

    uv run python -m agents.auto_clip --dry-run
    uv run python -m agents.auto_clip --dry-run --minutes 10
    uv run python -m agents.auto_clip --dry-run --transcript /path/to.vtt
    uv run python -m agents.auto_clip --dry-run --impingements /path/to.jsonl
    uv run python -m agents.auto_clip --dry-run --chat /path/to-chat.jsonl

The default sources are the live system paths (``impingements.jsonl``,
no transcript / no chat). ``--dry-run`` is required while the
predecessor pipeline is in flight — there is no cron yet.
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
        description="LLM-assisted segment detection for the auto-clip Shorts pipeline.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        required=True,
        help="Only print proposed candidates as JSON; do not dispatch.",
    )
    p.add_argument(
        "--minutes",
        type=float,
        default=10.0,
        help="Rolling window length in minutes (default 10).",
    )
    p.add_argument(
        "--transcript",
        type=Path,
        default=None,
        help="Path to a transcript file (VTT/SRT/speaker-labeled).",
    )
    p.add_argument(
        "--impingements",
        type=Path,
        default=Path("/dev/shm/hapax-dmn/impingements.jsonl"),
        help="Path to impingements.jsonl (default live path).",
    )
    p.add_argument(
        "--chat",
        type=Path,
        default=None,
        help="Path to chat-snapshot jsonl (default: no chat).",
    )
    p.add_argument(
        "--model",
        default="balanced",
        help="LiteLLM model alias (default 'balanced').",
    )
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


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
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


if __name__ == "__main__":
    raise SystemExit(main())
