#!/usr/bin/env python3
"""LRR Phase 1 — research registry CLI.

Manages the append-only research registry at
``~/hapax-state/research-registry/``. Every condition under the LRR epic
gets a directory + a ``condition.yaml`` definition. The CLI is the
single mutation surface so concurrent invocations don't corrupt the
registry (atomic writes + flock).

Subcommands:
    research-registry.py init             create the registry dir + first condition
    research-registry.py current          print active condition_id
    research-registry.py list             list all conditions (open + closed)
    research-registry.py open <slug>      open a new condition
    research-registry.py close <id>       mark a condition closed
    research-registry.py show <id>        print full condition.yaml

Epic spec: docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md § Phase 1
Phase 1 spec: docs/superpowers/specs/2026-04-14-lrr-phase-1-research-registry-design.md
"""

from __future__ import annotations

import argparse
import fcntl
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
    print(f"research-registry: opened {condition_id} (now current)")
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    condition_id = args.condition_id
    lock = _registry_lock()
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
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()
    print(f"research-registry: closed {condition_id}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    condition = _read_condition(args.condition_id)
    if condition is None:
        print(f"research-registry: condition {args.condition_id!r} not found", file=sys.stderr)
        return 1
    print(yaml.safe_dump(condition, sort_keys=False, default_flow_style=False), end="")
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
    args = parser.parse_args()
    return {
        "init": cmd_init,
        "current": cmd_current,
        "list": cmd_list,
        "open": cmd_open,
        "close": cmd_close,
        "show": cmd_show,
    }[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
