"""D-30 Phase 5 — relay-yaml → CC-task vault bridge.

Mirrors `~/.cache/hapax/relay/{alpha,beta,delta,epsilon}.yaml`'s
`active_queue_items[]` strings into Obsidian vault cc-task notes so the
operator's canonical SSOT is kept in sync with what each session is
queuing for itself.

Runs as a 5-minute systemd user timer
(`systemd/units/hapax-relay-to-cc-tasks.{service,timer}`). Idempotent:
each queue item gets a deterministic `relay-{md5-prefix}` task_id; re-
running on top of existing notes is a no-op (skip if exists).

Operator hand-edits to a mirrored task's body are preserved — the
bridge never overwrites an existing note. Status changes are mirrored
in one direction only: relay → vault.

Usage:
    uv run python -m agents.relay_to_cc_tasks                # one-shot
    uv run python -m agents.relay_to_cc_tasks --dry-run      # preview
    uv run python -m agents.relay_to_cc_tasks --vault-root P # override
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from shared.sdlc_filesystem_transaction import (
    FilesystemTransactionError,
    create_task_note_transactionally,
    task_note_transaction_context,
)

log = logging.getLogger(__name__)

DEFAULT_RELAY_DIR: Path = Path.home() / ".cache" / "hapax" / "relay"
DEFAULT_VAULT_ROOT: Path = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
KNOWN_ROLES: tuple[str, ...] = ("alpha", "beta", "delta", "epsilon")
_SLUG_MAX_LEN: int = 50


@dataclass(frozen=True)
class RelayQueueItem:
    """One string from a relay yaml's ``active_queue_items[]`` list."""

    role: str  # which session's queue this came from
    title: str

    @property
    def task_id(self) -> str:
        """Deterministic short-hash ID so the same title always maps to the
        same filename (idempotent across reruns)."""
        digest = hashlib.md5(  # noqa: S324 — non-security identifier hash
            self.title.encode("utf-8"), usedforsecurity=False
        ).hexdigest()
        return f"relay-{digest[:8]}"


def _slugify(text: str, max_len: int = _SLUG_MAX_LEN) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:max_len] or "no-title").rstrip("-")


def load_relay_queue_items(
    relay_dir: Path = DEFAULT_RELAY_DIR,
) -> list[RelayQueueItem]:
    """Walk the relay dir for ``{role}.yaml`` files and extract every
    queue item string per role."""
    items: list[RelayQueueItem] = []
    if not relay_dir.exists():
        log.warning("relay dir %s does not exist", relay_dir)
        return items
    for role in KNOWN_ROLES:
        path = relay_dir / f"{role}.yaml"
        if not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            log.warning("skipping malformed %s: %s", path, exc)
            continue
        queue = data.get("active_queue_items", []) or []
        if not isinstance(queue, list):
            log.warning("%s active_queue_items is not a list; skipping", path)
            continue
        for entry in queue:
            if not isinstance(entry, str):
                log.debug("non-string queue entry in %s: %r", path, entry)
                continue
            title = entry.strip()
            if not title:
                continue
            items.append(RelayQueueItem(role=role, title=title))
    return items


def render_task_note(item: RelayQueueItem) -> str:
    """Render a relay queue item as a vault cc-task markdown note."""
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    title_safe = item.title.replace('"', "'")
    return f"""---
type: cc-task
task_id: {item.task_id}
title: "{title_safe}"
status: offered
assigned_to: {item.role}
priority: normal
wsjf: 0.0
depends_on: []
blocks: []
branch: null
pr: null
created_at: {now}
claimed_at: null
completed_at: null
updated_at: {now}
parent_plan: null
parent_spec: null
tags: [from-relay-{item.role}]
---

# {item.title}

## Intent

(Mirrored from {item.role}.yaml `active_queue_items[]`. Operator may
edit this body without losing it on re-runs — the bridge skips
existing notes.)

## Acceptance criteria

- [ ] (operator-author or session-claim to expand)

## Session log

- {now} mirrored from relay yaml ({item.role})
"""


def vault_note_path(vault_root: Path, item: RelayQueueItem) -> Path:
    """Compute the vault file path for a relay queue item."""
    slug = _slugify(item.title)
    return vault_root / "active" / f"{item.task_id}-{slug}.md"


def mirror(
    *,
    relay_dir: Path = DEFAULT_RELAY_DIR,
    vault_root: Path = DEFAULT_VAULT_ROOT,
    apply: bool = True,
) -> dict[str, Any]:
    """Mirror relay queue items into vault notes. Returns counts."""
    items = load_relay_queue_items(relay_dir)
    counts = {"loaded": len(items), "written": 0, "skipped_existing": 0, "errors": 0}
    for item in items:
        out_path = vault_note_path(vault_root, item)
        if out_path.exists():
            counts["skipped_existing"] += 1
            log.debug("skip existing %s", out_path.name)
            continue
        body = render_task_note(item)
        if not apply:
            log.info(
                "[dry-run] would write %s for role=%s",
                out_path.name,
                item.role,
            )
            counts["written"] += 1
            continue
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            guards = tuple(vault_root / state / out_path.name for state in ("closed", "refused"))
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
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--relay-dir", type=Path, default=DEFAULT_RELAY_DIR)
    parser.add_argument("--vault-root", type=Path, default=DEFAULT_VAULT_ROOT)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    counts = mirror(
        relay_dir=args.relay_dir,
        vault_root=args.vault_root,
        apply=not args.dry_run,
    )
    mode = "DRY-RUN" if args.dry_run else "APPLY"
    print(
        f"\n[{mode}] loaded={counts['loaded']} "
        f"written={counts['written']} "
        f"skipped_existing={counts['skipped_existing']} "
        f"errors={counts['errors']}"
    )
    return 0 if counts["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
