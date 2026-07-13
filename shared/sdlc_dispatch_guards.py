"""Shared SDLC dispatch worktree resolution and executable cc-task guards."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Single source of truth for dispatcher/coordinator mapping and guard protocols.
# Consumers must import these names rather than re-declare local copies.
COORDINATOR_HEADLESS_DISPATCHABLE_PLATFORMS = ("claude", "codex", "vibe")

CLAIM_DISPATCH_PROTOCOL_VERSION = "hapax-claim-dispatch-v1"
CLOSE_DISPATCH_PROTOCOL_VERSION = "hapax-close-dispatch-v1"

# Compatibility only while every consumer migrates to ``check_worktree_claim_guard``.
# Text markers are not valid claim-tool evidence.
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


def check_worktree_claim_guard(worktree: Path) -> tuple[bool, str]:
    """Execute the exact worktree-local cc-claim protocol probe."""
    resolved_worktree = worktree.expanduser().resolve()
    script = resolved_worktree / "scripts" / "cc-claim"
    if not script.is_file():
        return False, f"missing cc-claim at {script}"
    if not os.access(script, os.X_OK):
        return False, f"cc-claim is not executable at {script}"

    try:
        result = subprocess.run(
            [str(script), "--dispatch-protocol-version"],
            cwd=resolved_worktree,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return False, f"cc-claim dispatch protocol probe timed out at {script}"
    except OSError as exc:
        return False, f"cc-claim dispatch protocol probe failed at {script}: {exc}"

    expected = f"{CLAIM_DISPATCH_PROTOCOL_VERSION}\n"
    if result.returncode != 0:
        return False, (
            f"cc-claim dispatch protocol probe failed at {script} (exit {result.returncode})"
        )
    if result.stdout != expected:
        return False, (
            f"stale cc-claim in {resolved_worktree}: expected dispatch protocol "
            f"{CLAIM_DISPATCH_PROTOCOL_VERSION!r}"
        )
    return True, f"worktree cc-claim dispatch protocol {CLAIM_DISPATCH_PROTOCOL_VERSION} present"


def check_worktree_close_guard(worktree: Path) -> tuple[bool, str]:
    """Execute the exact worktree-local cc-close protocol probe."""

    resolved_worktree = worktree.expanduser().resolve()
    script = resolved_worktree / "scripts" / "cc-close"
    if not script.is_file():
        return False, f"missing cc-close at {script}"
    if not os.access(script, os.X_OK):
        return False, f"cc-close is not executable at {script}"

    try:
        result = subprocess.run(
            [str(script), "--dispatch-protocol-version"],
            cwd=resolved_worktree,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return False, f"cc-close dispatch protocol probe timed out at {script}"
    except OSError as exc:
        return False, f"cc-close dispatch protocol probe failed at {script}: {exc}"

    expected = f"{CLOSE_DISPATCH_PROTOCOL_VERSION}\n"
    if result.returncode != 0:
        return (
            False,
            f"cc-close dispatch protocol probe failed at {script} (exit {result.returncode})",
        )
    if result.stdout != expected:
        return False, (
            f"stale cc-close in {resolved_worktree}: expected dispatch protocol "
            f"{CLOSE_DISPATCH_PROTOCOL_VERSION!r}"
        )
    return True, f"worktree cc-close dispatch protocol {CLOSE_DISPATCH_PROTOCOL_VERSION} present"


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
