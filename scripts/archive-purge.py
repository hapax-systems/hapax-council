#!/usr/bin/env python3
"""LRR Phase 2 item 9 — archive purge CLI.

Auditable deletion of archive data tied to a single ``condition_id``.
Default is **dry-run**: the CLI prints what would be deleted without
touching any file. ``--confirm`` is required for actual deletion.

Refuses to purge the currently-active condition. Every invocation
(dry-run or confirmed) writes an entry to the purge audit log at
``<archive_root>/purge.log``.

Usage::

    archive-purge.py --condition <id>               # dry-run (default)
    archive-purge.py --condition <id> --confirm     # live
    archive-purge.py --condition <id> --confirm --reason "consent revocation"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from shared.stream_archive import (
    SegmentSidecar,
    archive_root,
)

PURGE_LOG_NAME = "purge.log"
DEFAULT_REASON = "operator explicit"
ACTIVE_CONDITION_POINTER = Path.home() / "hapax-state" / "research-registry" / "current.txt"


def _iter_sidecars(root: Path) -> list[Path]:
    paths: list[Path] = []
    for kind in ("hls", "audio"):
        subdir = root / kind
        if not subdir.exists():
            continue
        paths.extend(sorted(subdir.rglob("*.json")))
    return paths


def _load_active_condition(pointer: Path = ACTIVE_CONDITION_POINTER) -> str | None:
    if not pointer.exists():
        return None
    try:
        value = pointer.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _append_audit_log(
    log_path: Path,
    entry: dict[str, object],
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _collect_targets(root: Path, condition_id: str) -> list[tuple[Path, Path, int]]:
    """Find all (sidecar_path, segment_path, size_bytes) for the given condition."""
    results: list[tuple[Path, Path, int]] = []
    for sidecar_path in _iter_sidecars(root):
        try:
            sidecar = SegmentSidecar.from_path(sidecar_path)
        except (ValueError, json.JSONDecodeError, OSError):
            continue
        if sidecar.condition_id != condition_id:
            continue
        segment_path = Path(sidecar.segment_path)
        try:
            size = segment_path.stat().st_size if segment_path.exists() else 0
        except OSError:
            size = 0
        results.append((sidecar_path, segment_path, size))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="archive-purge.py",
        description="Auditable purge of stream archive data for a given condition_id.",
    )
    parser.add_argument("--condition", required=True, help="condition_id to purge")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually delete files (default: dry-run)",
    )
    parser.add_argument(
        "--reason",
        default=DEFAULT_REASON,
        help=f"Purge reason for the audit log (default: {DEFAULT_REASON!r})",
    )
    parser.add_argument(
        "--archive-root",
        type=str,
        default=None,
        help="Override archive root",
    )
    parser.add_argument(
        "--active-condition-pointer",
        type=str,
        default=None,
        help="Override the active-condition pointer file (test harness)",
    )
    args = parser.parse_args(argv)

    root = Path(args.archive_root) if args.archive_root else archive_root()
    pointer = (
        Path(args.active_condition_pointer)
        if args.active_condition_pointer
        else ACTIVE_CONDITION_POINTER
    )

    active = _load_active_condition(pointer)
    if active == args.condition:
        print(
            f"ERROR: refusing to purge active condition {args.condition!r}. "
            f"Close it first via research-registry.py close.",
            file=sys.stderr,
        )
        return 2

    targets = _collect_targets(root, args.condition)

    total_bytes = sum(size for _, _, size in targets)
    mode = "confirmed" if args.confirm else "dry_run"

    print(
        json.dumps(
            {
                "condition_id": args.condition,
                "mode": mode,
                "segments_affected": len(targets),
                "bytes_affected": total_bytes,
                "reason": args.reason,
                "archive_root": str(root),
            },
            indent=2,
        )
    )

    for sidecar_path, segment_path, _ in targets:
        print(f"  {'WOULD DELETE' if not args.confirm else 'DELETING'}: {segment_path}")
        print(f"  {'WOULD DELETE' if not args.confirm else 'DELETING'}: {sidecar_path}")

    if args.confirm:
        errors: list[str] = []
        for sidecar_path, segment_path, _ in targets:
            for p in (segment_path, sidecar_path):
                try:
                    if p.exists():
                        p.unlink()
                except OSError as exc:
                    errors.append(f"{p}: {exc}")
        if errors:
            print(
                json.dumps({"errors": errors}, indent=2),
                file=sys.stderr,
            )

    # Always write an audit entry — even dry-run runs are audited so the
    # purge.log is a complete history of decisions, not just actions.
    _append_audit_log(
        root / PURGE_LOG_NAME,
        {
            "ts": _now_iso(),
            "condition_id": args.condition,
            "mode": mode,
            "operator": "hapax",
            "segments_affected": len(targets),
            "bytes_affected": total_bytes,
            "reason": args.reason,
        },
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
