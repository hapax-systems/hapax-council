#!/usr/bin/env python3
"""LRR Phase 1 — research registry CLI.

Manages the append-only research registry at
``~/hapax-state/research-registry/``. Every condition under the LRR epic
gets a directory + a ``condition.yaml`` definition. The CLI is the
single mutation surface so concurrent invocations don't corrupt the
registry (atomic writes + flock).

Subcommands:
    research-registry.py init                        create the registry dir + first condition
    research-registry.py current                     print active condition_id
    research-registry.py list                        list all conditions (open + closed)
    research-registry.py open <slug>                 open a new condition
    research-registry.py close <id>                  mark a condition closed
    research-registry.py show <id>                   print full condition.yaml
    research-registry.py set-collection-halt <id> <ts>
                                                     set collection_halt_at on
                                                     an open condition (LRR
                                                     Phase 4 item 7)

Epic spec: docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md § Phase 1
Phase 1 spec: docs/superpowers/specs/2026-04-14-lrr-phase-1-research-registry-design.md
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print(
        "research-registry: PyYAML is required. Install via `uv sync` or `pip install pyyaml`.",
        file=sys.stderr,
    )
    sys.exit(2)


REGISTRY_DIR = Path.home() / "hapax-state" / "research-registry"
CURRENT_FILE = REGISTRY_DIR / "current.txt"
LOCK_FILE = REGISTRY_DIR / ".registry.lock"

# LRR Phase 1 item 3: research-marker SHM injection. Written by init/open/close
# subcommands; read by the studio compositor's director_loop on every reaction
# so each reaction is tagged with the active condition_id. JSON shape is stable
# (compositor-side reader hard-codes the field name).
RESEARCH_MARKER_SHM_PATH = Path("/dev/shm/hapax-compositor/research-marker.json")

# Audit log: every condition transition gets a frame-accurate timestamp +
# before/after pair. Tracks the full history of which condition was active
# at any point in time (for retroactive analysis).
MARKER_CHANGES_LOG = REGISTRY_DIR / "research_marker_changes.jsonl"

# Schema for the per-condition YAML. Subset checked at write time; full
# schema is pinned by tests/test_research_registry.py.
_REQUIRED_FIELDS = (
    "condition_id",
    "claim_id",
    "opened_at",
    "closed_at",
    "substrate",
    "frozen_files",
    "directives_manifest",
    "parent_condition_id",
    "sibling_condition_ids",
    "collection_started_at",
    "collection_halt_at",
    "osf_project_id",
    "pre_registration",
    "notes",
)


def _atomic_write(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically via tmp+rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content)
    os.replace(tmp_path, path)


def _registry_lock(timeout_s: float = 5.0):
    """Acquire an exclusive flock on the registry. Context manager."""
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    lock_fh = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
    except OSError as e:
        lock_fh.close()
        raise RuntimeError(f"failed to acquire registry lock: {e}") from e
    return lock_fh


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _condition_dir(condition_id: str) -> Path:
    return REGISTRY_DIR / condition_id


def _condition_file(condition_id: str) -> Path:
    return _condition_dir(condition_id) / "condition.yaml"


def _read_current() -> str | None:
    if not CURRENT_FILE.exists():
        return None
    return CURRENT_FILE.read_text().strip() or None


def _read_condition(condition_id: str) -> dict[str, Any] | None:
    f = _condition_file(condition_id)
    if not f.exists():
        return None
    return yaml.safe_load(f.read_text()) or None


def _write_condition(condition_id: str, data: dict[str, Any]) -> None:
    _atomic_write(_condition_file(condition_id), yaml.safe_dump(data, sort_keys=False))


def _set_current(condition_id: str) -> None:
    _atomic_write(CURRENT_FILE, condition_id + "\n")


def _clear_current_if_matches(condition_id: str) -> bool:
    """Atomically clear CURRENT_FILE iff it still points at ``condition_id``.

    Phase 1 audit finding H1 — ``cmd_close`` did not clear ``current.txt``
    when closing the active condition, so downstream callers that read the
    pointer file (``archive-purge.py``, ``check-frozen-files.py``) continued
    to see the closed condition as active. The fix clears the pointer only
    when it still matches the just-closed condition — so a concurrent
    ``open`` that advances the pointer to a new condition between close and
    clear is not clobbered.

    Returns True iff the file was cleared by this call.
    """
    if not CURRENT_FILE.exists():
        return False
    before = CURRENT_FILE.read_text().strip()
    if before != condition_id:
        return False
    _atomic_write(CURRENT_FILE, "")
    return True


def _write_marker(condition_id: str | None) -> None:
    """LRR Phase 1 item 3: write the research marker for the compositor to read.

    The marker file at /dev/shm/hapax-compositor/research-marker.json carries
    the active condition_id. The compositor's director_loop reads this file
    on every reaction tick (cached 5 s) and tags JSONL + Qdrant writes with
    the condition_id so every reaction lands in a coherent experimental
    context.

    Atomic write via tmp+rename — director_loop never sees a partial document.
    Failures are swallowed with a stderr warning so a missing /dev/shm path
    in dev/test environments doesn't break the registry CLI itself.
    """
    payload = {
        "condition_id": condition_id,
        "written_at": _now_iso(),
    }
    try:
        RESEARCH_MARKER_SHM_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = RESEARCH_MARKER_SHM_PATH.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(payload) + "\n")
        os.replace(tmp_path, RESEARCH_MARKER_SHM_PATH)
    except OSError as exc:
        print(
            f"research-registry: warning: failed to write research marker at "
            f"{RESEARCH_MARKER_SHM_PATH}: {exc}",
            file=sys.stderr,
        )


def _append_marker_change(before: str | None, after: str | None) -> None:
    """LRR Phase 1 item 3: append a condition transition to the audit log.

    Captures every open/close transition so retroactive analysis can ask
    'which condition was active when reaction N happened?' without depending
    on the live SHM marker (which may have been overwritten or lost on
    process restart).
    """
    record = {
        "ts": _now_iso(),
        "before": before,
        "after": after,
    }
    try:
        MARKER_CHANGES_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(MARKER_CHANGES_LOG, "a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(
            f"research-registry: warning: failed to append marker change log "
            f"at {MARKER_CHANGES_LOG}: {exc}",
            file=sys.stderr,
        )


def _list_condition_ids() -> list[str]:
    if not REGISTRY_DIR.exists():
        return []
    out = [p.name for p in REGISTRY_DIR.iterdir() if p.is_dir() and (p / "condition.yaml").exists()]
    out.sort()
    return out


def _next_sequential(slug: str) -> int:
    """Return the next sequential number for a slug (e.g. cond-<slug>-NNN)."""
    prefix = f"cond-{slug}-"
    existing_nums: list[int] = []
    for cid in _list_condition_ids():
        if cid.startswith(prefix):
            tail = cid[len(prefix) :]
            try:
                existing_nums.append(int(tail))
            except ValueError:
                continue
    return (max(existing_nums) + 1) if existing_nums else 1


def _new_condition_skeleton(condition_id: str, slug: str) -> dict[str, Any]:
    return {
        "condition_id": condition_id,
        "claim_id": f"claim-{slug}",
        "opened_at": _now_iso(),
        "closed_at": None,
        "substrate": {
            "model": None,
            "backend": None,
            "route": None,
        },
        "frozen_files": [],
        "directives_manifest": [],
        "parent_condition_id": None,
        "sibling_condition_ids": [],
        "collection_started_at": None,
        "collection_halt_at": None,
        "osf_project_id": None,
        "pre_registration": {
            "filed": False,
            "url": None,
            "filed_at": None,
        },
        "notes": (
            f"Condition {condition_id} opened by research-registry CLI at "
            f"{_now_iso()}. Substrate fields, frozen_files, and directives_manifest "
            "must be populated by the operator before any data is collected under "
            "this condition."
        ),
    }


# ----- subcommands -----


def cmd_init(_args: argparse.Namespace) -> int:
    if REGISTRY_DIR.exists() and any(REGISTRY_DIR.iterdir()):
        print(
            f"research-registry: {REGISTRY_DIR} already exists and is non-empty; refusing to init.",
            file=sys.stderr,
        )
        return 1
    lock = _registry_lock()
    try:
        REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        condition_id = "cond-phase-a-baseline-qwen-001"
        skeleton = _new_condition_skeleton(condition_id, "phase-a-baseline-qwen")
        skeleton["substrate"] = {
            "model": "Qwen3.5-9B-exl3-5.00bpw",
            "backend": "tabbyapi",
            "route": "local-fast|coding|reasoning",
        }
        _write_condition(condition_id, skeleton)
        _set_current(condition_id)
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()
    # LRR Phase 1 item 3: publish the SHM marker so director_loop starts
    # tagging reactions immediately, plus log the transition (None → init).
    _write_marker(condition_id)
    _append_marker_change(before=None, after=condition_id)
    print(f"research-registry: initialized at {REGISTRY_DIR} with condition {condition_id}")
    return 0


def cmd_current(_args: argparse.Namespace) -> int:
    current = _read_current()
    if current is None:
        print("null")
        return 0
    print(current)
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    ids = _list_condition_ids()
    if not ids:
        print("(no conditions)")
        return 0
    current = _read_current()
    for cid in ids:
        marker = " *" if cid == current else "  "
        condition = _read_condition(cid) or {}
        closed_at = condition.get("closed_at")
        status = "closed" if closed_at else "open"
        print(f"{marker} {cid}  [{status}]")
    return 0


def cmd_open(args: argparse.Namespace) -> int:
    slug = args.slug
    if not slug or not slug.replace("-", "").isalnum():
        print(
            f"research-registry: invalid slug {slug!r} (must be alphanumeric + hyphens)",
            file=sys.stderr,
        )
        return 1
    lock = _registry_lock()
    previous_current = _read_current()
    try:
        n = _next_sequential(slug)
        condition_id = f"cond-{slug}-{n:03d}"
        if _condition_file(condition_id).exists():
            print(
                f"research-registry: {condition_id} already exists; refusing to overwrite",
                file=sys.stderr,
            )
            return 1
        skeleton = _new_condition_skeleton(condition_id, slug)
        _write_condition(condition_id, skeleton)
        _set_current(condition_id)
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()
    # LRR Phase 1 item 3: publish the SHM marker + audit log the transition.
    _write_marker(condition_id)
    _append_marker_change(before=previous_current, after=condition_id)
    print(f"research-registry: opened {condition_id} (now current)")
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    condition_id = args.condition_id
    lock = _registry_lock()
    previous_current = _read_current()
    closed_now = False
    try:
        condition = _read_condition(condition_id)
        if condition is None:
            print(f"research-registry: condition {condition_id!r} not found", file=sys.stderr)
            return 1
        if condition.get("closed_at"):
            print(f"research-registry: {condition_id} already closed at {condition['closed_at']}")
            return 0
        condition["closed_at"] = _now_iso()
        if condition.get("collection_halt_at") is None:
            condition["collection_halt_at"] = condition["closed_at"]
        _write_condition(condition_id, condition)
        closed_now = True
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()
    # LRR Phase 1 item 3: if we just closed the active condition, the SHM
    # marker should reflect "no active condition" (None). Future PRs may add
    # an explicit `succeed` semantic where the next condition is named at
    # close time. Today close means "the current condition is sealed for
    # analysis" and the marker drops to None until an explicit open.
    if closed_now and previous_current == condition_id:
        _write_marker(None)
        _append_marker_change(before=condition_id, after=None)
        # H1 fix: also clear the persistent pointer file so downstream
        # callers (archive-purge, check-frozen-files) stop seeing the
        # closed condition as "current." Uses the match-and-clear helper
        # so a concurrent open that advanced the pointer is not clobbered.
        _clear_current_if_matches(condition_id)
    print(f"research-registry: closed {condition_id}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    condition = _read_condition(args.condition_id)
    if condition is None:
        print(f"research-registry: condition {args.condition_id!r} not found", file=sys.stderr)
        return 1
    print(yaml.safe_dump(condition, sort_keys=False, default_flow_style=False), end="")
    return 0


def cmd_set_collection_halt(args: argparse.Namespace) -> int:
    """LRR Phase 4 item 7: set ``collection_halt_at`` on an open condition.

    Phase 4 closes the live data-collection window for Condition A without
    closing the condition itself (conditions never close per P-3). This
    subcommand writes the marker so downstream consumers can distinguish
    'condition is live but sealed for analysis' from 'condition is still
    accepting data.'

    Accepts an ISO-8601 UTC timestamp (e.g. ``2026-04-15T12:00:00Z``) or
    the literal ``now`` for the current wall clock. Refuses to overwrite
    a non-null ``collection_halt_at`` unless ``--force`` is given — the
    marker is supposed to be set once per condition.
    """
    condition_id = args.condition_id
    lock = _registry_lock()
    try:
        condition = _read_condition(condition_id)
        if condition is None:
            print(f"research-registry: condition {condition_id!r} not found", file=sys.stderr)
            return 1
        existing = condition.get("collection_halt_at")
        if existing and not args.force:
            print(
                f"research-registry: {condition_id} already has "
                f"collection_halt_at={existing}; pass --force to overwrite",
                file=sys.stderr,
            )
            return 1
        ts = args.timestamp
        if ts == "now":
            ts = _now_iso()
        else:
            try:
                parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError as exc:
                print(
                    f"research-registry: invalid timestamp {ts!r} "
                    f"(expected ISO-8601 or 'now'): {exc}",
                    file=sys.stderr,
                )
                return 1
            if parsed.tzinfo is None:
                print(
                    f"research-registry: timestamp {ts!r} has no timezone; "
                    f"use a UTC suffix like 'Z' or '+00:00'",
                    file=sys.stderr,
                )
                return 1
            ts = parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
        condition["collection_halt_at"] = ts
        _write_condition(condition_id, condition)
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()
    print(f"research-registry: set collection_halt_at={ts} on {condition_id}")
    return 0


def cmd_tag_reactions(args: argparse.Namespace) -> int:
    """LRR Phase 1 item 9: backfill stream-reactions Qdrant points.

    Scrolls the entire `stream-reactions` collection in batches of
    BATCH_SIZE points, finds points whose payload lacks `condition_id`
    (or whose condition_id is null/empty), and sets it to the given
    condition_id. Designed to be safe to re-run — points that already
    have the condition_id are skipped, not re-written.

    Default BATCH_SIZE = 100 per Bundle 2 §4 chunked-update guidance.

    Verification is built in: after the backfill, the function prints
    a count of points now tagged with the given condition_id and a
    count of points still untagged. The operator should compare the
    "tagged" count against the expected ~2178 and the "untagged" count
    against 0.
    """
    condition_id = args.condition_id
    if not _read_condition(condition_id):
        print(
            f"research-registry: condition {condition_id!r} not found in registry; "
            f"refusing to tag reactions with an unknown condition",
            file=sys.stderr,
        )
        return 1
    if args.dry_run:
        print(
            f"research-registry: DRY RUN — would tag stream-reactions points "
            f"with condition_id={condition_id} (no writes performed)"
        )
        return 0
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import (
            FieldCondition,
            Filter,
            IsNullCondition,
            MatchValue,
            PayloadField,
        )
    except ImportError:
        print("research-registry: qdrant-client not installed", file=sys.stderr)
        return 2
    client = QdrantClient(url="http://localhost:6333")
    collection = "stream-reactions"
    batch_size = args.batch_size or 100
    total_scanned = 0
    total_updated = 0
    next_offset: Any = None
    while True:
        try:
            points, next_offset = client.scroll(
                collection_name=collection,
                limit=batch_size,
                offset=next_offset,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as exc:
            print(f"research-registry: qdrant scroll failed: {exc}", file=sys.stderr)
            return 3
        if not points:
            break
        ids_to_update = [p.id for p in points if not (p.payload or {}).get("condition_id")]
        total_scanned += len(points)
        if ids_to_update:
            try:
                client.set_payload(
                    collection_name=collection,
                    payload={"condition_id": condition_id},
                    points=ids_to_update,
                )
                total_updated += len(ids_to_update)
                print(
                    f"research-registry: tagged batch of {len(ids_to_update)} "
                    f"(running total: {total_updated} updated / {total_scanned} scanned)"
                )
            except Exception as exc:
                print(f"research-registry: qdrant set_payload failed: {exc}", file=sys.stderr)
                return 4
        if next_offset is None:
            break
    # Verification: count points now carrying the target condition_id
    # plus a cross-check that every non-target point is accounted for.
    #
    # H2 fix (Phase 1 audit): ``IsNullCondition`` only catches points where
    # the key exists and has a literal null value. Qdrant distinguishes
    # three payload states — field absent, field present with null, field
    # present with a non-null value. Points in the "field absent" state
    # would slip past the IsNullCondition filter and be silently excluded
    # from Phase 4 BEST analysis even though the CLI reported
    # ``still_untagged=0``. Cross-check by deriving ``still_untagged`` from
    # the total-collection count minus ``tagged_count``; if the two
    # numbers disagree, the IsNullCondition path is hiding untagged points
    # and the verification must escalate a warning.
    try:
        tagged_count = client.count(
            collection_name=collection,
            count_filter=Filter(
                must=[FieldCondition(key="condition_id", match=MatchValue(value=condition_id))]
            ),
            exact=True,
        ).count
        null_count = client.count(
            collection_name=collection,
            count_filter=Filter(
                must=[
                    IsNullCondition(is_null=PayloadField(key="condition_id")),
                ]
            ),
            exact=True,
        ).count
        total_count = client.count(collection_name=collection, exact=True).count
    except Exception as exc:
        print(f"research-registry: verification count failed: {exc}", file=sys.stderr)
        print(
            f"research-registry: backfill complete. "
            f"scanned={total_scanned} updated={total_updated} "
            f"now_tagged_with_{condition_id}=? still_untagged=?"
        )
        return 0

    derived_untagged = total_count - tagged_count
    still_untagged = derived_untagged  # canonical source of truth
    print(
        f"research-registry: backfill complete. "
        f"scanned={total_scanned} updated={total_updated} "
        f"now_tagged_with_{condition_id}={tagged_count} "
        f"still_untagged={still_untagged} "
        f"(derived=total-tagged; is_null_reported={null_count}; total={total_count})"
    )
    if derived_untagged != null_count:
        print(
            f"research-registry: WARNING — derived_untagged ({derived_untagged}) does not "
            f"match IsNullCondition count ({null_count}); some points likely lack the "
            f"condition_id key entirely (field absent, not null). Re-run tag-reactions "
            f"to guarantee every point is covered.",
            file=sys.stderr,
        )
        return 5
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="research-registry", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create the registry dir + first condition")
    sub.add_parser("current", help="print active condition_id")
    sub.add_parser("list", help="list all conditions")
    open_parser = sub.add_parser("open", help="open a new condition")
    open_parser.add_argument("slug", help="short name for the condition (alphanumeric + hyphens)")
    close_parser = sub.add_parser("close", help="close a condition")
    close_parser.add_argument("condition_id", help="condition_id to close")
    show_parser = sub.add_parser("show", help="show a condition's full YAML")
    show_parser.add_argument("condition_id", help="condition_id to show")
    tag_parser = sub.add_parser(
        "tag-reactions",
        help="backfill stream-reactions Qdrant points with a condition_id (chunked)",
    )
    tag_parser.add_argument("condition_id", help="condition_id to backfill onto untagged points")
    tag_parser.add_argument(
        "--dry-run", action="store_true", help="print what would happen without writing"
    )
    tag_parser.add_argument(
        "--batch-size", type=int, default=100, help="points per scroll/update batch (default 100)"
    )
    halt_parser = sub.add_parser(
        "set-collection-halt",
        help="set collection_halt_at on an open condition (LRR Phase 4 item 7)",
    )
    halt_parser.add_argument("condition_id", help="condition_id to mark")
    halt_parser.add_argument(
        "timestamp",
        help="ISO-8601 UTC timestamp (e.g. 2026-04-15T12:00:00Z) or 'now'",
    )
    halt_parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing non-null collection_halt_at",
    )
    args = parser.parse_args()
    return {
        "init": cmd_init,
        "current": cmd_current,
        "list": cmd_list,
        "open": cmd_open,
        "close": cmd_close,
        "show": cmd_show,
        "tag-reactions": cmd_tag_reactions,
        "set-collection-halt": cmd_set_collection_halt,
    }[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
