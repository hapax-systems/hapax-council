"""Pin the repo-pres-pinned-repos-removal refusal mechanically.

Per ``docs/refusal-briefs/pinned-repos-trending-pattern.md``: pinned
repos on the operator's GitHub profile are a "trying-to-trend"
affordance refused per drop 3 anti-pattern §10 + drop 4 §10.

This test scans the agents/ + scripts/ trees for any call site that
would re-pin a repo via the GitHub GraphQL ``pinItem`` mutation, and
fails CI on any match. The remove-pinned-repos.sh helper is
explicitly excluded from the scan because it ONLY un-pins (the inverse
mutation, ``unpinItem``).

Mirrors the existing forbidden-imports CI-guard pattern for refused
substrate.
"""

from __future__ import annotations

import re
from pathlib import Path

# ``pinItem`` is the mutation that adds a repo to the profile pin list.
# ``unpinItem`` is its inverse (removes one) and is permitted.
_PINNED_REGEX = re.compile(r"\bpinItem\b")
_INVERSE = "unpinItem"

# Directories to scan for forbidden mutations.
_SCAN_ROOTS = ("agents", "scripts")

# Files explicitly permitted to mention "pinItem" — the refusal-brief
# itself documents the forbidden mutation by name.
_PERMITTED_FILES = {
    "tests/test_forbidden_github_pin_calls.py",  # this test
    "docs/refusal-briefs/pinned-repos-trending-pattern.md",  # the brief itself
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_no_github_pin_calls_in_agents_or_scripts():
    """Scan agents/ + scripts/ for `pinItem` GraphQL call sites."""
    root = _repo_root()
    offenders: list[str] = []
    for sub in _SCAN_ROOTS:
        sub_dir = root / sub
        if not sub_dir.is_dir():
            continue
        for path in sub_dir.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".py", ".sh", ".bash", ".yaml", ".yml"}:
                continue
            rel = path.relative_to(root).as_posix()
            if rel in _PERMITTED_FILES:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            # Strip lines that are clearly the inverse mutation; pinItem
            # appears as a substring of unpinItem so we filter first.
            for line in text.splitlines():
                stripped = line.replace(_INVERSE, "")
                if _PINNED_REGEX.search(stripped):
                    offenders.append(f"{rel}:{stripped.strip()[:100]}")

    assert not offenders, (
        "Forbidden GitHub `pinItem` mutation call sites detected:\n  "
        + "\n  ".join(offenders)
        + "\n\nPer docs/refusal-briefs/pinned-repos-trending-pattern.md, "
        "pinned repos are a trying-to-trend affordance refused by the "
        "corporate-boundary axiom + canonical-surface discipline. Use "
        "`unpinItem` (the inverse mutation) only."
    )


def test_remove_script_uses_only_unpin():
    """Verify the remove-pinned-repos.sh helper uses unpinItem exclusively."""
    script = _repo_root() / "scripts" / "remove-pinned-repos.sh"
    if not script.is_file():
        return  # script not yet shipped — not a hard fail
    text = script.read_text(encoding="utf-8")
    # The helper should mention unpinItem (the un-pin mutation it
    # actually performs) — and should NOT contain a bare pinItem outside
    # that compound word.
    assert _INVERSE in text, "remove-pinned-repos.sh must reference unpinItem"
    # Strip the inverse + check no naked pinItem remains
    stripped = text.replace(_INVERSE, "")
    assert not _PINNED_REGEX.search(stripped), (
        "remove-pinned-repos.sh contains a forbidden bare `pinItem` mutation"
    )
