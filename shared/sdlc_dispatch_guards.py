"""Shared SDLC dispatch worktree resolution and cc-task guard markers."""

from __future__ import annotations

import os
from pathlib import Path

# Single source of truth for dispatcher/coordinator mapping and guard markers.
# Consumers must import these names rather than re-declare local copies.
COORDINATOR_HEADLESS_DISPATCHABLE_PLATFORMS = ("claude", "codex", "vibe")

# A staleness guard must name markers that a CURRENT cc-claim actually contains.
#
# Two aspirational markers were added here ahead of the cc-claim that would carry
# them — `execution_admission_prerequisites_unavailable` and
# `publish_admitted_claim`. Neither appears in main's cc-claim, and
# `publish_admitted_claim` appears in NO cc-claim in any branch. The effect was
# that check_worktree_claim_guard rejected every worktree as "stale", so
# dispatch-into-worktree refused unconditionally — a guard that can never pass is
# a wedge, not a guard.
#
# Markers are therefore the three that a current cc-claim genuinely carries: the
# AuthorityCase/ISAP refusal string plus the two required frontmatter fields it
# validates. Re-add an admission marker only together with the cc-claim that
# contains it, or this refuses everything again.
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
    return root / "hapax-council"
