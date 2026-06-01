"""CI guard: no authority-case-ledger.jsonl may be git-tracked (NEW-4).

Coordination reform (CASE-SDLC-REFORM-001): the per-worktree authority-case
ledger is removed from git in favor of the single daemon-owned coord event log
outside every worktree. This guard fails if any copy is re-tracked — e.g. a stray
``git add -A`` on a branch where .gitignore has not yet propagated.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_no_tracked_authority_case_ledger() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "*authority-case-ledger.jsonl"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert tracked == [], f"authority-case-ledger.jsonl must not be git-tracked: {tracked}"
