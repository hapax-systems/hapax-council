"""CI guard: no coverage artifact may be git-tracked.

``.coverage`` is a binary SQLite database rewritten by every local ``pytest
--cov`` run. Nothing in the repo reads it, but ``sdlc-implement.yml`` runs
``git add -A`` in two places, so a tracked copy means automation commits
divergent binaries onto unrelated branches and manufactures merge conflicts in
a file no human ever edits. This guard fails if any coverage artifact is
re-tracked — e.g. a stray ``git add -A`` on a branch where .gitignore has not
yet propagated.

Modelled on ``test_no_tracked_authority_ledger.py``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Patterns are git pathspecs, matched against the whole tracked-file list.
COVERAGE_PATHSPECS = (
    ".coverage",
    ".coverage.*",
    "*/.coverage",
    "*/.coverage.*",
    "coverage.xml",
    "*/coverage.xml",
    "coverage.json",
    "*/coverage.json",
    ".coverage_html/*",
    "htmlcov/*",
    "*/htmlcov/*",
)


def test_no_tracked_coverage_artifacts() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "--", *COVERAGE_PATHSPECS],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert tracked == [], f"coverage artifacts must not be git-tracked: {tracked}"


def test_coverage_family_is_gitignored() -> None:
    """The ignore rule is the durable half — the guard above only catches regressions.

    ``--verbose`` is load-bearing. Plain ``git check-ignore`` reports a path as ignored
    no matter which source ignored it, including ``.git/info/exclude`` and the user's
    ``core.excludesFile``. Both are machine-local and invisible to the repo, so without
    the source check this guard keeps passing on the one machine that has a local rule
    while the tracked ``.gitignore`` entry is gone for everyone else.
    """
    probes = (
        ".coverage",
        ".coverage.host.1234.567890",
        "coverage.xml",
        "htmlcov/index.html",
    )
    result = subprocess.run(
        ["git", "check-ignore", "--verbose", "--stdin"],
        cwd=REPO_ROOT,
        input="\n".join(probes),
        capture_output=True,
        text=True,
        check=False,
    )
    # Each matched line is "<source>:<linenum>:<pattern>\t<pathname>".
    covered = set()
    for line in result.stdout.splitlines():
        prefix, _, pathname = line.partition("\t")
        source = prefix.split(":", 2)[0]
        if source == ".gitignore":
            covered.add(pathname)
    missing = [p for p in probes if p not in covered]
    assert not missing, (
        f"the tracked root .gitignore must cover the coverage family; "
        f"not covered by .gitignore: {missing}"
    )
