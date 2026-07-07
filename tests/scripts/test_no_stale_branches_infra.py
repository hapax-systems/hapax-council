"""The ENFORCED infra-exclusion regex in no-stale-branches.sh.

The audit tool's classification is covered by test_worktree_cap_audit.py, but the
hook is the side that actually *gates* `git worktree add`, and it uses a different
match syntax (ERE regex vs the audit's bash glob), so the two can silently drift.
This test pins the hook's real `INFRA_WORKTREE_RE` (extracted from the file, never
duplicated) and the path-anchored count pipeline it runs, including the
over-broad case the review-team flagged: a session worktree whose *branch name*
contains an infra-like substring must still be COUNTED.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK = REPO_ROOT / "hooks" / "scripts" / "no-stale-branches.sh"


def _infra_re() -> str:
    text = HOOK.read_text(encoding="utf-8")
    m = re.search(r"INFRA_WORKTREE_RE='([^']+)'", text)
    assert m, "INFRA_WORKTREE_RE literal not found in no-stale-branches.sh"
    return m.group(1)


def _count_sessions(worktree_list: str) -> int:
    """Replicate the hook's enforced count: path field only, minus infra."""
    regex = _infra_re()
    out = subprocess.run(
        ["bash", "-c", f"awk '{{print $1}}' | grep -Evc \"{regex}\""],
        input=worktree_list,
        capture_output=True,
        text=True,
    )
    return int((out.stdout or "0").strip() or "0")


def test_relocated_infra_excluded_session_paths_counted():
    listing = (
        "\n".join(
            [
                "/home/hapax/projects/hapax-council  a [main]",
                "/home/hapax/projects/hapax-council--cx-green  b [codex/cx-green]",
                "/data2/data/cache/hapax/rebuild/worktree  c (detached HEAD)",
                "/data2/data/cache/hapax/scratch/eval-batch  d [cc/eval-batch]",
                "/data2/data/cache/hapax/source-activation/releases/deadbeef  e (detached HEAD)",
                "/store/llm-data/runtime/health-monitor-source  f (detached HEAD)",
            ]
        )
        + "\n"
    )
    # Only the two real session worktrees count; the 4 infra paths are excluded.
    assert _count_sessions(listing) == 2


def test_branch_name_with_infra_substring_is_still_counted():
    # Path-anchoring: a session worktree whose BRANCH contains 'source-activation'
    # must NOT be excluded (the review-team over-broad finding).
    listing = (
        "/home/hapax/projects/hapax-council--cx-foo  a [feature/source-activation-rework]\n"
        "/home/hapax/projects/hapax-council--cx-bar  b [fix/cache/hapax-thing]\n"
    )
    assert _count_sessions(listing) == 2
