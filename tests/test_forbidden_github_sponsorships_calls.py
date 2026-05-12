"""Pin GitHub Sponsors activation to repo metadata and GraphQL profile setup.

The active Sponsors surface is receive-only org funding metadata plus no-perk
GitHub Sponsors tiers. Agents and scripts still must not toggle repository
settings with ``has_sponsorships=true``; profile/tier setup belongs in the
Sponsors GraphQL/dashboard flow and ``.github/FUNDING.yml``.

Mirrors the existing forbidden-imports + pinItem CI-guard patterns.
"""

from __future__ import annotations

import re
from pathlib import Path

# Forbidden: any line that asserts has_sponsorships=true or
# has_sponsorships: true. Keep the regex narrow to avoid false-positive
# substring matches on legitimate has_sponsorships=false / .has_sponsorships
# read calls.
_ENABLE_REGEXES: tuple[re.Pattern, ...] = (
    re.compile(r"has_sponsorships\s*=\s*true", re.IGNORECASE),
    re.compile(r'has_sponsorships["\']?\s*:\s*true', re.IGNORECASE),
    re.compile(r"-F\s+has_sponsorships=true"),
)

_SCAN_ROOTS = ("agents", "scripts")
_PERMITTED_FILES = {
    "tests/test_forbidden_github_sponsorships_calls.py",
    "docs/refusal-briefs/sponsorships-multi-user-pattern.md",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_no_sponsorships_enable_calls_in_agents_or_scripts():
    """Scan agents/ + scripts/ for has_sponsorships=true call sites."""
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
            for line_no, line in enumerate(text.splitlines(), start=1):
                for regex in _ENABLE_REGEXES:
                    if regex.search(line):
                        offenders.append(f"{rel}:{line_no}: {line.strip()[:100]}")
                        break

    assert not offenders, (
        "Forbidden GitHub has_sponsorships=true call sites detected:\n  "
        + "\n  ".join(offenders)
        + "\n\nUse GitHub Sponsors profile/tier GraphQL setup and "
        ".github/FUNDING.yml; do not add repo Settings enable mutations."
    )


def test_disable_script_sets_false_only():
    """Verify scripts/disable-sponsorships.sh only sets has_sponsorships=false."""
    script = _repo_root() / "scripts" / "disable-sponsorships.sh"
    if not script.is_file():
        return  # script not yet shipped — not a hard fail
    text = script.read_text(encoding="utf-8")
    # Must mention has_sponsorships=false (the disable mutation it performs)
    assert "has_sponsorships=false" in text, (
        "disable-sponsorships.sh must reference has_sponsorships=false"
    )
    # Must NOT contain any has_sponsorships=true mutation
    for regex in _ENABLE_REGEXES:
        assert not regex.search(text), (
            f"disable-sponsorships.sh contains forbidden enable mutation: {regex.pattern!r}"
        )
