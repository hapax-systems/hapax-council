#!/usr/bin/env python3
"""LRR Phase 2 item 6 + item 7 — archive search CLI.

Scans the stream archive's per-segment sidecar JSON files and returns
segments matching a query. Subcommands::

    archive-search.py by-condition <condition_id>
    archive-search.py by-reaction <reaction_id>
    archive-search.py by-timerange <start_iso> <end_iso>
    archive-search.py extract <segment_id> <output_dir>
    archive-search.py stats
    archive-search.py verify
    archive-search.py note <segment_id>

Emits machine-readable JSON by default. Pass ``--format=table`` for
human-friendly output. Respects ``HAPAX_ARCHIVE_ROOT`` if set.

Item 7 ``note`` subcommand writes an Obsidian vault note from the
per-segment sidecar (gated on ``HAPAX_VAULT_PATH``). See
``shared/vault_note_renderer.py`` for the renderer.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from shared.stream_archive import SegmentSidecar, archive_root
from shared.vault_note_renderer import (
    note_path_for,
    render_note_body,
    vault_path_from_env,
)


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


def cmd_stats(args: argparse.Namespace) -> int:
    """Aggregate summary of the archive.

    Emits counts by `condition_id` + `archive_kind`, total duration,
    total reaction count, and oldest/newest segment timestamps. Useful
    for operator dashboards and Phase 4 data-integrity checks.
    """
    root = Path(args.archive_root) if args.archive_root else archive_root()
    all_sidecars = _load_all(root)

    by_condition: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    total_duration = 0.0
    total_reactions = 0
    oldest: str | None = None
    newest: str | None = None

    for s in all_sidecars:
        cid = s.condition_id or "(untagged)"
        by_condition[cid] = by_condition.get(cid, 0) + 1
        by_kind[s.archive_kind] = by_kind.get(s.archive_kind, 0) + 1
        total_duration += s.duration_seconds
        total_reactions += len(s.reaction_ids)
        if oldest is None or s.segment_start_ts < oldest:
            oldest = s.segment_start_ts
        if newest is None or s.segment_start_ts > newest:
            newest = s.segment_start_ts

    payload = {
        "total_segments": len(all_sidecars),
        "by_condition": by_condition,
        "by_archive_kind": by_kind,
        "total_duration_seconds": round(total_duration, 3),
        "total_reaction_count": total_reactions,
        "oldest_segment_start_ts": oldest,
        "newest_segment_start_ts": newest,
        "archive_root": str(root),
    }
    if args.format == "table":
        print(f"archive root: {root}")
        print(f"total segments: {payload['total_segments']}")
        print(f"total duration: {payload['total_duration_seconds']:.2f}s")
        print(f"total reactions: {payload['total_reaction_count']}")
        print(f"oldest: {oldest or '—'}")
        print(f"newest: {newest or '—'}")
        print("\nby condition_id:")
        for cid, count in sorted(by_condition.items(), key=lambda kv: -kv[1]):
            print(f"  {cid:<48} {count}")
        print("\nby archive_kind:")
        for kind, count in sorted(by_kind.items()):
            print(f"  {kind:<48} {count}")
    else:
        print(json.dumps(payload, indent=2))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Walk every sidecar + flag integrity issues.

    Checks: (1) sidecar file is parseable + valid schema, (2) segment
    file referenced by `segment_path` exists on disk, (3)
    `segment_end_ts >= segment_start_ts`. Reports issues as a JSON
    list (or table). Exit 0 on clean, 1 if any issues.
    """
    root = Path(args.archive_root) if args.archive_root else archive_root()
    issues: list[dict[str, str]] = []
    sidecar_paths = _iter_sidecars(root)
    total = 0

    for sidecar_path in sidecar_paths:
        total += 1
        try:
            sidecar = SegmentSidecar.from_path(sidecar_path)
        except (ValueError, json.JSONDecodeError, OSError) as exc:
            issues.append(
                {
                    "sidecar_path": str(sidecar_path),
                    "issue": f"parse_error: {exc}",
                }
            )
            continue

        segment_path = Path(sidecar.segment_path)
        if not segment_path.exists():
            issues.append(
                {
                    "sidecar_path": str(sidecar_path),
                    "segment_id": sidecar.segment_id,
                    "issue": f"segment_missing: {segment_path}",
                }
            )

        try:
            start = _parse_iso(sidecar.segment_start_ts)
            end = _parse_iso(sidecar.segment_end_ts)
            if end < start:
                issues.append(
                    {
                        "sidecar_path": str(sidecar_path),
                        "segment_id": sidecar.segment_id,
                        "issue": f"end_before_start: {sidecar.segment_end_ts} < {sidecar.segment_start_ts}",
                    }
                )
        except ValueError as exc:
            issues.append(
                {
                    "sidecar_path": str(sidecar_path),
                    "segment_id": sidecar.segment_id,
                    "issue": f"invalid_timestamp: {exc}",
                }
            )

    summary = {
        "total_sidecars_checked": total,
        "issues_found": len(issues),
        "issues": issues,
    }
    if args.format == "table":
        print(f"total sidecars checked: {total}")
        print(f"issues found: {len(issues)}")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print(json.dumps(summary, indent=2))
    return 0 if not issues else 1


def cmd_note(args: argparse.Namespace) -> int:
    """LRR Phase 2 item 7 — vault note creation for a segment.

    Looks up the sidecar by ``segment_id``, then writes a templated
    Obsidian vault note under ``30-areas/legomena-live/archive/YYYY-MM/``.
    Gated on ``HAPAX_VAULT_PATH``: if unset, the command reports the
    renderer is disabled and exits 2. Does not overwrite existing
    notes — operator commentary is preserved across invocations.
    """
    vault_root = vault_path_from_env()
    if vault_root is None:
        print(
            "archive-search: HAPAX_VAULT_PATH not set; vault note renderer disabled",
            file=sys.stderr,
        )
        return 2
    if not vault_root.exists():
        print(
            f"archive-search: HAPAX_VAULT_PATH={vault_root} does not exist",
            file=sys.stderr,
        )
        return 2

    root = Path(args.archive_root) if args.archive_root else archive_root()
    for sidecar_path in _iter_sidecars(root):
        try:
            sidecar = SegmentSidecar.from_path(sidecar_path)
        except (ValueError, json.JSONDecodeError, OSError):
            continue
        if sidecar.segment_id != args.segment_id:
            continue

        note_path = note_path_for(sidecar, vault_root)
        if note_path.exists() and not args.force:
            print(
                json.dumps(
                    {
                        "note_path": str(note_path),
                        "status": "exists",
                        "message": "pass --force to overwrite",
                    }
                )
            )
            return 0

        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(render_note_body(sidecar), encoding="utf-8")
        print(
            json.dumps(
                {
                    "note_path": str(note_path),
                    "segment_id": sidecar.segment_id,
                    "status": "written",
                }
            )
        )
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

    p_s = sub.add_parser("stats", help="Aggregate summary of the archive")
    p_s.set_defaults(func=cmd_stats)

    p_v = sub.add_parser("verify", help="Walk every sidecar + flag integrity issues")
    p_v.set_defaults(func=cmd_verify)

    p_n = sub.add_parser(
        "note",
        help="Write an Obsidian vault note for a segment (LRR Phase 2 item 7)",
    )
    p_n.add_argument("segment_id")
    p_n.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing vault note (default: preserve operator commentary)",
    )
    p_n.set_defaults(func=cmd_note)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
