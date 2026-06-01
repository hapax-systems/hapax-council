"""Objective code-churn computation for the Velocity:Quality Observatory.

CASE-VELOCITY-QUALITY-OBSERVATORY-001 /
ISAP-VELOCITY-QUALITY-OBSERVATORY-PHASE1-INSTRUMENTATION.

Churn is a quality dimension: how much freshly written code is being rewritten.
The observatory ISAP's anti-gaming constraint forbids self-reported metrics — every
number must be derived from immutable git history. This module encapsulates the git
plumbing and a pure parser so the feeder never has to shell out inline (and so the
parsing is unit-testable without a live repository).

The ISAP's full definition ("percentage of lines merged today that were rewritten
within 7 days of their original merge") needs per-line blame attribution, which is a
later observatory phase. Phase-1 ships the objective add/delete churn ratio computed
from ``git log --numstat`` — the standard deletions-over-additions proxy — and labels
it as such rather than overclaiming the blame-based metric.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

_HEX = set("0123456789abcdef")


@dataclass(frozen=True)
class ChurnResult:
    """Aggregate line churn over a git window.

    ``churn_ratio`` is deletions / additions — a value near 0 means new code that
    sticks, a value near (or above) 1 means code being torn out about as fast as it
    is written. It is 0.0 when no lines were added (nothing to churn).
    """

    commits: int
    lines_added: int
    lines_deleted: int

    @property
    def churn_ratio(self) -> float:
        return self.lines_deleted / self.lines_added if self.lines_added else 0.0


def _looks_like_commit_hash(line: str) -> bool:
    """True for a bare ``git log --pretty=format:%H`` hash line."""
    return 7 <= len(line) <= 40 and all(c in _HEX for c in line.lower())


def parse_numstat(log_output: str) -> ChurnResult:
    """Parse ``git log --numstat --pretty=format:%H`` output into a ChurnResult.

    Numstat rows are ``added\\tdeleted\\tpath``; binary files render ``-`` for the
    counts and are skipped. Bare hash lines (from ``%H``) count commits.
    """
    added = deleted = commits = 0
    for raw in log_output.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) == 3:
            a, d, _path = parts
            if a.isdigit():
                added += int(a)
            if d.isdigit():
                deleted += int(d)
        elif len(parts) == 1 and _looks_like_commit_hash(line):
            commits += 1
    return ChurnResult(commits=commits, lines_added=added, lines_deleted=deleted)


def _git(repo: Path, *args: str) -> str:
    """Run a read-only git command in ``repo``, returning stdout ('' on failure)."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout


def compute_churn(repo: Path, *, since: str, until: str | None = None) -> ChurnResult:
    """Compute line churn on ``repo``'s history in the ``[since, until]`` window.

    ``since``/``until`` are passed verbatim to ``git log`` (e.g. ``"2026-05-31
    00:00:00"``). Returns a zeroed ChurnResult if the repo or window yields nothing.
    """
    args = ["log", f"--since={since}"]
    if until:
        args.append(f"--until={until}")
    args += ["--numstat", "--pretty=format:%H"]
    return parse_numstat(_git(repo, *args))
