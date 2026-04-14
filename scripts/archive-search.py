#!/usr/bin/env python3
"""LRR Phase 2 item 6 — archive search CLI.

Scans the stream archive's per-segment sidecar JSON files and returns
segments matching a query. Subcommands::

    archive-search.py by-condition <condition_id>
    archive-search.py by-reaction <reaction_id>
    archive-search.py by-timerange <start_iso> <end_iso>
    archive-search.py extract <segment_id> <output_dir>

Emits machine-readable JSON by default. Pass ``--format=table`` for
human-friendly output. Respects ``HAPAX_ARCHIVE_ROOT`` if set.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from shared.stream_archive import SegmentSidecar, archive_root


def _iter_sidecars(root: Path) -> list[Path]:
    """Return all sidecar JSON paths under <root>/hls/ and <root>/audio/."""
    paths: list[Path] = []
    for kind in ("hls", "audio"):
        subdir = root / kind
        if not subdir.exists():
            continue
        paths.extend(sorted(subdir.rglob("*.json")))
    return paths


def _load_all(root: Path) -> list[SegmentSidecar]:
    out: list[SegmentSidecar] = []
    for path in _iter_sidecars(root):
        try:
            out.append(SegmentSidecar.from_path(path))
        except (ValueError, json.JSONDecodeError, OSError):
            continue
    return out


def _parse_iso(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _emit_json(results: list[SegmentSidecar]) -> None:
    payload = [
        {
            "segment_id": s.segment_id,
            "segment_path": s.segment_path,
            "condition_id": s.condition_id,
            "segment_start_ts": s.segment_start_ts,
            "segment_end_ts": s.segment_end_ts,
            "duration_seconds": s.duration_seconds,
            "reaction_count": len(s.reaction_ids),
            "archive_kind": s.archive_kind,
        }
        for s in results
    ]
    print(json.dumps(payload, indent=2))


def _emit_table(results: list[SegmentSidecar]) -> None:
    if not results:
        print("(no results)")
        return
    print(f"{'SEGMENT':<32}{'CONDITION':<40}{'DURATION':<12}{'KIND':<12}START")
    for s in results:
        print(
            f"{s.segment_id:<32}"
            f"{(s.condition_id or '—'):<40}"
            f"{s.duration_seconds:<12.3f}"
            f"{s.archive_kind:<12}"
            f"{s.segment_start_ts}"
        )


def _emit(results: list[SegmentSidecar], fmt: str) -> None:
    if fmt == "table":
        _emit_table(results)
    else:
        _emit_json(results)


def cmd_by_condition(args: argparse.Namespace) -> int:
    root = Path(args.archive_root) if args.archive_root else archive_root()
    all_sidecars = _load_all(root)
    matches = [s for s in all_sidecars if s.condition_id == args.condition_id]
    _emit(matches, args.format)
    return 0


def cmd_by_reaction(args: argparse.Namespace) -> int:
    root = Path(args.archive_root) if args.archive_root else archive_root()
    all_sidecars = _load_all(root)
    matches = [s for s in all_sidecars if args.reaction_id in s.reaction_ids]
    _emit(matches, args.format)
    return 0


def cmd_by_timerange(args: argparse.Namespace) -> int:
    root = Path(args.archive_root) if args.archive_root else archive_root()
    start = _parse_iso(args.start)
    end = _parse_iso(args.end)
    if end < start:
        print("ERROR: end precedes start", file=sys.stderr)
        return 2
    all_sidecars = _load_all(root)
    matches: list[SegmentSidecar] = []
    for s in all_sidecars:
        seg_start = _parse_iso(s.segment_start_ts)
        seg_end = _parse_iso(s.segment_end_ts)
        if seg_end >= start and seg_start <= end:
            matches.append(s)
    _emit(matches, args.format)
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    root = Path(args.archive_root) if args.archive_root else archive_root()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for sidecar_path in _iter_sidecars(root):
        try:
            sidecar = SegmentSidecar.from_path(sidecar_path)
        except (ValueError, json.JSONDecodeError, OSError):
            continue
        if sidecar.segment_id != args.segment_id:
            continue

        segment_path = Path(sidecar.segment_path)
        if not segment_path.exists():
            print(f"ERROR: segment path does not exist: {segment_path}", file=sys.stderr)
            return 1

        dest_segment = output_dir / segment_path.name
        dest_sidecar = output_dir / sidecar_path.name
        shutil.copy2(segment_path, dest_segment)
        shutil.copy2(sidecar_path, dest_sidecar)
        print(json.dumps({"segment": str(dest_segment), "sidecar": str(dest_sidecar)}))
        return 0

    print(f"ERROR: segment_id {args.segment_id!r} not found", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="archive-search.py",
        description="Search the LRR Phase 2 stream archive by condition, reaction, or timerange.",
    )
    p.add_argument(
        "--archive-root",
        type=str,
        default=None,
        help="Override archive root (defaults to $HAPAX_ARCHIVE_ROOT or ~/hapax-state/stream-archive)",
    )
    p.add_argument(
        "--format",
        choices=("json", "table"),
        default="json",
        help="Output format (default: json)",
    )
    sub = p.add_subparsers(dest="action", required=True)

    p_c = sub.add_parser("by-condition", help="Find segments tagged with a condition_id")
    p_c.add_argument("condition_id")
    p_c.set_defaults(func=cmd_by_condition)

    p_r = sub.add_parser("by-reaction", help="Find segments whose reaction_ids contain an ID")
    p_r.add_argument("reaction_id")
    p_r.set_defaults(func=cmd_by_reaction)

    p_t = sub.add_parser("by-timerange", help="Find segments whose window overlaps a time range")
    p_t.add_argument("start", help="ISO8601 UTC start (e.g. 2026-04-14T12:00:00Z)")
    p_t.add_argument("end", help="ISO8601 UTC end (e.g. 2026-04-14T13:00:00Z)")
    p_t.set_defaults(func=cmd_by_timerange)

    p_e = sub.add_parser("extract", help="Copy a segment + sidecar to an output dir")
    p_e.add_argument("segment_id")
    p_e.add_argument("output_dir")
    p_e.set_defaults(func=cmd_extract)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
