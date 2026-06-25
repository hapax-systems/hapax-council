"""Shared SDLC dispatch worktree resolution and cc-task guard markers."""

from __future__ import annotations

import os
from pathlib import Path

# Single source of truth for dispatcher/coordinator mapping and guard markers.
# Consumers must import these names rather than re-declare local copies.
COORDINATOR_HEADLESS_DISPATCHABLE_PLATFORMS = frozenset({"claude", "codex", "vibe"})

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
    """Resolve the lane worktree used by governed dispatch preflight and launch."""
    override = os.environ.get("HAPAX_DISPATCH_WORKTREE")
    if override:
        return Path(override).expanduser()
    root = Path(os.environ.get("HAPAX_DISPATCH_PROJECT_ROOT", str(Path.home() / "projects")))
    if platform == "codex":
        if role.startswith("cx-"):
            return root / f"hapax-council--{role}"
        return root / f"hapax-council--cx-{role}"
    if platform == "claude":
        return root / "hapax-council" if role == "alpha" else root / f"hapax-council--{role}"
    if platform == "vibe":
        return root / f"hapax-council--{role}"
    if platform == "antigrav":
        normalized = "antigrav" if role == "antigravity" else role
        return root / f"hapax-council--{normalized}"
    return root / "hapax-council"
