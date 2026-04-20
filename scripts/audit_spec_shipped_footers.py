"""Audit `docs/superpowers/specs/*.md` for missing "Shipped in" footers.

Closes the audit-loop gap surfaced by D-31 unplanned-specs triage
(`docs/research/2026-04-20-d31-unplanned-specs-triage.md` Key Finding):

    > the 2026-04-18 cascade epic shipped 14 of the 15 closed specs in
    > ~36 hours from a single research dossier. The plan-skip pattern
    > is acceptable for stub-sized specs, but specs lack a "shipped
    > in" footer — recommend a hook addition to close that audit loop.

This script walks every spec, looks for a "Shipped in" / "shipped in"
footer pattern, and reports specs that lack one. For each missing-
footer spec, attempts to identify a probable shipping commit by
scanning git log for messages mentioning the spec's lead concept.

Usage:
    uv run python scripts/audit_spec_shipped_footers.py
    uv run python scripts/audit_spec_shipped_footers.py --since 30d
    uv run python scripts/audit_spec_shipped_footers.py --suggest

The `--suggest` flag prints a markdown footer the operator can paste at
the spec's bottom. Does NOT modify specs (operator-author only).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SPECS_DIR = REPO_ROOT / "docs" / "superpowers" / "specs"

# Match "Shipped in <commit-sha>" or "Shipped in PR #N", in any of:
# - inline:  "Shipped in `abc1234`."
# - header:  "## Shipped in\n\n- `abc1234`"
# Tolerates up to 400 chars between "Shipped in" and the ref so a
# multi-line listing under a header still counts.
_SHIPPED_FOOTER_PATTERN = re.compile(
    r"shipped\s+in[\s\S]{0,400}?(?:`?[0-9a-f]{7,40}`?|pr\s*#?\d+)",
    re.I,
)

# Stop-words to drop from spec stem when grepping git log.
_STOP_WORDS = frozenset(
    {"design", "research", "spec", "plan", "and", "the", "for", "of", "to", "a", "an"}
)


@dataclass(frozen=True)
class SpecAuditEntry:
    """One spec's audit result."""

    path: Path
    has_footer: bool
    spec_date: str  # "2026-04-18"
    age_days: int
    candidate_commits: list[str]  # SHA short forms found via grep

    @property
    def spec_stem_words(self) -> list[str]:
        """Words from spec stem suitable for git-log grep."""
        # path.stem like "2026-04-18-camera-naming-classification-design"
        # Drop date prefix + design suffix + stop-words.
        stem = self.path.stem
        # Strip leading YYYY-MM-DD-
        m = re.match(r"^\d{4}-\d{2}-\d{2}-(.+)$", stem)
        if m:
            stem = m.group(1)
        # Strip trailing -design / -spec / -plan
        stem = re.sub(r"-(design|spec|plan)$", "", stem)
        words = [w for w in stem.split("-") if w and w.lower() not in _STOP_WORDS]
        return words


def parse_spec_date(path: Path) -> tuple[str, int]:
    """Extract YYYY-MM-DD from a spec filename. Returns (date, age_days)."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", path.name)
    if not m:
        return ("unknown", -1)
    date_str = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    try:
        spec_dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=UTC)
    except ValueError:
        return (date_str, -1)
    age = (datetime.now(UTC) - spec_dt).days
    return (date_str, age)


def has_shipped_footer(path: Path) -> bool:
    """Does the spec have a 'Shipped in <ref>' footer?"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return _SHIPPED_FOOTER_PATTERN.search(text) is not None


def find_candidate_commits(words: list[str], since_days: int = 60) -> list[str]:
    """Run `git log --grep` for each word; return unique short-SHAs."""
    if not words:
        return []
    since = (datetime.now(UTC) - timedelta(days=since_days)).strftime("%Y-%m-%d")
    candidates: set[str] = set()
    for word in words[:3]:  # cap at first 3 words to bound subprocess cost
        try:
            result = subprocess.run(
                ["git", "log", "--all", f"--since={since}", "--grep", word, "--format=%h %s"],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
                timeout=10,
            )
        except (subprocess.TimeoutExpired, OSError):
            continue
        for line in result.stdout.splitlines()[:5]:  # first 5 hits per word
            sha = line.split(maxsplit=1)[0] if line else ""
            if sha and len(sha) >= 7:
                candidates.add(sha)
    return sorted(candidates)


def audit_specs(
    specs_dir: Path = SPECS_DIR,
    since_days: int = 60,
    pattern: str | None = None,
) -> list[SpecAuditEntry]:
    """Walk specs dir + audit each. Returns list sorted by age descending."""
    if not specs_dir.exists():
        return []
    entries: list[SpecAuditEntry] = []
    for spec_path in sorted(specs_dir.glob("*.md")):
        if pattern and pattern not in spec_path.name:
            continue
        date_str, age = parse_spec_date(spec_path)
        has_footer = has_shipped_footer(spec_path)
        candidates = (
            []
            if has_footer
            else find_candidate_commits(
                SpecAuditEntry(
                    path=spec_path,
                    has_footer=False,
                    spec_date=date_str,
                    age_days=age,
                    candidate_commits=[],
                ).spec_stem_words,
                since_days=since_days,
            )
        )
        entries.append(
            SpecAuditEntry(
                path=spec_path,
                has_footer=has_footer,
                spec_date=date_str,
                age_days=age,
                candidate_commits=candidates,
            )
        )
    return sorted(entries, key=lambda e: -e.age_days)


def render_footer_suggestion(entry: SpecAuditEntry) -> str:
    """Render a markdown footer the operator can paste at the spec's bottom."""
    lines = ["", "---", "", "## Shipped in"]
    if entry.candidate_commits:
        lines.append("")
        lines.append("Candidate commits (operator: cherry-pick the ones that actually shipped):")
        lines.append("")
        for sha in entry.candidate_commits[:5]:
            lines.append(f"- `{sha}`")
    else:
        lines.append("")
        lines.append("(No candidate commits found via title-grep. Operator: fill in manually.)")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--since", default="60d", help="git log lookback window (e.g. 30d)")
    parser.add_argument("--suggest", action="store_true", help="print footer suggestions")
    parser.add_argument("--pattern", help="only audit specs matching this substring")
    parser.add_argument(
        "--missing-only",
        action="store_true",
        help="only print specs without a footer",
    )
    args = parser.parse_args(argv)
    # Parse --since like "30d" → 30
    m = re.match(r"^(\d+)d$", args.since)
    since_days = int(m.group(1)) if m else 60
    entries = audit_specs(SPECS_DIR, since_days=since_days, pattern=args.pattern)
    total = len(entries)
    with_footer = sum(1 for e in entries if e.has_footer)
    missing = total - with_footer
    print(f"Audited {total} spec(s) in {SPECS_DIR}")
    print(f"  with 'Shipped in' footer:    {with_footer}")
    print(f"  without 'Shipped in' footer: {missing}")
    print()
    for entry in entries:
        if args.missing_only and entry.has_footer:
            continue
        marker = "✓" if entry.has_footer else "✗"
        print(f"{marker} {entry.path.name}  (age={entry.age_days}d)")
        if not entry.has_footer:
            if entry.candidate_commits:
                print(f"    candidates: {', '.join(entry.candidate_commits[:5])}")
            else:
                print("    no candidate commits found via title-grep")
            if args.suggest:
                print(render_footer_suggestion(entry))
    return 0 if missing == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
