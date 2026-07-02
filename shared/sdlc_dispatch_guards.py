"""Shared SDLC dispatch worktree resolution and cc-task guard markers."""

from __future__ import annotations

import os
from pathlib import Path

# Single source of truth for dispatcher/coordinator mapping and guard markers.
# Consumers must import these names rather than re-declare local copies.
COORDINATOR_HEADLESS_DISPATCHABLE_PLATFORMS = ("claude", "codex", "vibe")

DISPATCH_CLAIM_GUARD_MARKERS = (
    "missing required AuthorityCase/ISAP fields",
    "authority_case",
    "parent_spec",
)

DISPATCH_CLOSE_GUARD_MARKERS = (
    "frontmatter_task_id",
    "closed_duplicate",
    "closed task duplicate has task_id",
)


def dispatch_worktree(role: str, platform: str) -> Path:
    """Resolve a lane worktree for governed dispatch preflight and launch.

    This is mapping only, not coordinator headless eligibility; gate scheduler
    capacity with ``COORDINATOR_HEADLESS_DISPATCHABLE_PLATFORMS``.
    """
    override = os.environ.get("HAPAX_DISPATCH_WORKTREE")
    if override:
        return Path(override).expanduser()
    configured_root = os.environ.get("HAPAX_DISPATCH_PROJECT_ROOT")
    root = Path(configured_root).expanduser() if configured_root else Path.home() / "projects"
    if platform == "codex":
        if role.startswith("cx-"):
            return root / f"hapax-council--{role}"
        return root / f"hapax-council--cx-{role}"
    if platform == "claude":
        return root / "hapax-council" if role == "alpha" else root / f"hapax-council--{role}"
    if platform == "vibe":
        return root / f"hapax-council--{role}"
    if platform in {"agy", "antigrav"}:
        # agy has governed interactive dispatch, so the dispatcher needs a
        # worktree mapping even though coordinator headless dispatch excludes it.
        # The legacy antigrav platform/name is accepted here only so old
        # persisted coordination state maps to the canonical worktree family.
        if role in {"agy", "antigrav", "antigravity"}:
            normalized = "agy"
        elif role.startswith("antigrav-") or role.startswith("antigravity-"):
            normalized = f"agy-{role.split('-', 1)[1]}"
        else:
            normalized = role
        return root / f"hapax-council--{normalized}"
    return root / "hapax-council"
