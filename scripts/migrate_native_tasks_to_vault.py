"""Migrate native CC TaskTool records to the Obsidian vault SSOT.

Phase 2 of D-30 (CC-task Obsidian SSOT). Reads native task JSON files
from ``~/.claude/tasks/<list-uuid>/<id>.json``, generates one cc-task
markdown note per task in the operator's vault, and places it in
``active/`` or ``closed/`` based on status.

Native task shape (one file per task):
  {
    "id": "20",
    "subject": "...",
    "description": "...",
    "activeForm": "...",
    "status": "completed" | "pending" | "in_progress" | "cancelled",
    "blocks": ["21"],
    "blockedBy": []
  }

Status mapping:
  pending     → offered    (active/)
  in_progress → claimed    (active/)
  completed   → done       (closed/)
  cancelled   → withdrawn  (closed/)

ID namespacing: native IDs collide across lists ("20" exists in many).
This script prefixes each ID with the first 4 chars of its list-UUID:
``ef7b-020``. Globally unique without losing recognizability.

Idempotent: skips notes that already exist in the vault. Re-run is safe.

Usage:
    uv run python scripts/migrate_native_tasks_to_vault.py --dry-run
    uv run python scripts/migrate_native_tasks_to_vault.py --apply
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.sdlc_filesystem_transaction import (  # noqa: E402
    FilesystemTransactionError,
    create_task_note_transactionally,
    task_note_transaction_context,
)

log = logging.getLogger(__name__)

DEFAULT_NATIVE_TASKS_ROOT: Path = Path.home() / ".claude" / "tasks"
DEFAULT_VAULT_ROOT: Path = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"

# Native task status → vault status
_STATUS_MAP: dict[str, str] = {
    "pending": "offered",
    "in_progress": "claimed",
    "completed": "done",
    "cancelled": "withdrawn",
}

# Vault status → folder
_FOLDER_MAP: dict[str, str] = {
    "offered": "active",
    "claimed": "active",
    "in_progress": "active",
    "pr_open": "active",
    "blocked": "active",
    "done": "closed",
    "superseded": "closed",
    "withdrawn": "closed",
}

_SLUG_MAX_LEN: int = 50


@dataclass(frozen=True)
class NativeTask:
    """One record from a native ~/.claude/tasks/<list>/<id>.json file."""

    list_id: str  # e.g. "ef7bbda9-4b93-494f-b8e7-7037c7279a85"
    raw_id: str  # native id, e.g. "20"
    subject: str
    description: str
    status: str  # native status
    blocks: list[str]
    blocked_by: list[str]
    file_mtime: float  # filesystem mtime as proxy for created/updated

    @property
    def composite_id(self) -> str:
        """Globally-unique vault ID: ``<list-prefix>-<padded-raw-id>``."""
        prefix = self.list_id[:4]
        # raw_id may be a string or int-like; pad to 3 digits within a list.
        try:
            n = int(self.raw_id)
            return f"{prefix}-{n:03d}"
        except ValueError:
            # Non-numeric ID — keep verbatim, length-bound.
            return f"{prefix}-{self.raw_id[:8]}"

    @property
    def vault_status(self) -> str:
        return _STATUS_MAP.get(self.status, "withdrawn")  # unknown → withdrawn

    @property
    def folder(self) -> str:
        return _FOLDER_MAP[self.vault_status]


def slugify(text: str, max_len: int = _SLUG_MAX_LEN) -> str:
    """Lowercase, replace non-alphanum with hyphen, collapse, truncate."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len].rstrip("-")


def load_native_tasks(root: Path = DEFAULT_NATIVE_TASKS_ROOT) -> list[NativeTask]:
    """Walk ``root`` and load every task JSON file."""
    if not root.exists():
        log.warning("native task root %s does not exist", root)
        return []
    tasks: list[NativeTask] = []
    for list_dir in sorted(root.iterdir()):
        if not list_dir.is_dir():
            continue
        for json_path in sorted(list_dir.glob("*.json")):
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                log.warning("skipping unreadable %s: %s", json_path, exc)
                continue
            try:
                tasks.append(
                    NativeTask(
                        list_id=list_dir.name,
                        raw_id=str(data.get("id", json_path.stem)),
                        subject=str(data.get("subject", "(no subject)")),
                        description=str(data.get("description", "")),
                        status=str(data.get("status", "pending")),
                        blocks=list(data.get("blocks", []) or []),
                        blocked_by=list(data.get("blockedBy", []) or []),
                        file_mtime=json_path.stat().st_mtime,
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("skipping malformed task %s: %s", json_path, exc)
    return tasks


def render_task_note(task: NativeTask) -> str:
    """Render a native task as a vault cc-task markdown note."""
    timestamp = datetime.fromtimestamp(task.file_mtime, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    completed_at = timestamp if task.vault_status in ("done", "withdrawn") else "null"
    blocks_yaml = json.dumps(task.blocks) if task.blocks else "[]"
    blocked_by_yaml = json.dumps(task.blocked_by) if task.blocked_by else "[]"
    title_safe = task.subject.replace('"', "'")
    return f"""---
type: cc-task
task_id: {task.composite_id}
native_list: {task.list_id}
native_id: {task.raw_id}
title: "{title_safe}"
status: {task.vault_status}
assigned_to: unassigned
priority: normal
wsjf: 0.0
depends_on: {blocked_by_yaml}
blocks: {blocks_yaml}
branch: null
pr: null
created_at: {timestamp}
claimed_at: null
completed_at: {completed_at}
updated_at: {timestamp}
parent_plan: null
parent_spec: null
tags: [migrated-from-native]
---

# {task.subject}

## Intent

{task.description if task.description else "(migrated from native CC TaskTool — no description)"}

## Acceptance criteria

- [ ] (legacy task — acceptance criteria not captured by native TaskTool)

## Session log

- {timestamp} migrated from native CC TaskTool list `{task.list_id}` (native id `{task.raw_id}`, status `{task.status}`)
"""


def vault_note_path(vault_root: Path, task: NativeTask) -> Path:
    """Compute the vault file path for a task note."""
    slug = slugify(task.subject) or "no-subject"
    filename = f"{task.composite_id}-{slug}.md"
    return vault_root / task.folder / filename


def migrate(
    *,
    native_root: Path = DEFAULT_NATIVE_TASKS_ROOT,
    vault_root: Path = DEFAULT_VAULT_ROOT,
    apply: bool = False,
) -> dict[str, Any]:
    """Migrate native tasks to the vault. Returns counts."""
    tasks = load_native_tasks(native_root)
    counts = {"loaded": len(tasks), "written": 0, "skipped_existing": 0, "errors": 0}
    for task in tasks:
        out_path = vault_note_path(vault_root, task)
        if out_path.exists():
            counts["skipped_existing"] += 1
            log.debug("skip existing %s", out_path.name)
            continue
        body = render_task_note(task)
        if not apply:
            log.info("[dry-run] would write %s", out_path.relative_to(vault_root))
            counts["written"] += 1
            continue
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            guards = tuple(
                vault_root / state / out_path.name
                for state in ("active", "closed", "refused")
                if state != task.folder
            )
            for guard in guards:
                guard.parent.mkdir(parents=True, exist_ok=True)
            resolved_vault, cache_dir = task_note_transaction_context(
                out_path,
                vault_root=vault_root,
            )
            create_task_note_transactionally(
                out_path,
                content=body.encode("utf-8"),
                mode=0o644,
                cache_dir=cache_dir,
                vault_root=resolved_vault,
                absent_guard_paths=guards,
            )
            counts["written"] += 1
        except (OSError, FilesystemTransactionError) as exc:
            log.warning("failed to write %s: %s", out_path, exc)
            counts["errors"] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--apply", action="store_true", help="actually write files")
    parser.add_argument("--dry-run", action="store_true", help="(default) preview only")
    parser.add_argument("--native-root", type=Path, default=DEFAULT_NATIVE_TASKS_ROOT)
    parser.add_argument("--vault-root", type=Path, default=DEFAULT_VAULT_ROOT)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    if args.apply and args.dry_run:
        parser.error("--apply and --dry-run are mutually exclusive")
    counts = migrate(
        native_root=args.native_root,
        vault_root=args.vault_root,
        apply=args.apply,
    )
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(
        f"\n[{mode}] loaded={counts['loaded']} "
        f"written={counts['written']} "
        f"skipped_existing={counts['skipped_existing']} "
        f"errors={counts['errors']}"
    )
    return 0 if counts["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
