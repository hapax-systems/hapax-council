"""Durable scan: operator-attributed diagnostic text stays off public surfaces.

The 2026-07-09 privacy redaction removed operator-attributed diagnostic
phrasing from docs, code constants, prompts, and profiles. This scan pins the
CLASS: tracked files must not reattribute a diagnosis to the operator.

The exclusion list is EMPTY: the operator-hands axioms edit landed 2026-07-09,
so every tracked surface — including axioms/** — is in scope.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Tight attribution patterns only — generic domain/field-survey discussion of
# ADHD/autism (research corpora, external-product notes) is intentionally out
# of scope; the redaction class is attribution TO THE OPERATOR.
ATTRIBUTION_PATTERNS = (
    re.compile(r"operator\s+(?:has|with)\s+(?:ADHD|autis)", re.IGNORECASE),
    re.compile(r"operator'?s\s+(?:ADHD|autis)", re.IGNORECASE),
    re.compile(r"(?:ADHD|autism)[/\s-]*(?:and\s+autism\s+)?operator", re.IGNORECASE),
)

# Empty since the 2026-07-09 operator-hands axioms edit; add a path here ONLY for a
# guard-protected file with a routed, pending human edit.
PENDING_OPERATOR_EDIT: set[str] = set()

TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".json", ".ts", ".txt", ".j2", ".sh"}


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.splitlines()


def test_no_operator_attributed_diagnostic_text_on_tracked_surfaces() -> None:
    offenders: list[str] = []
    for rel in _tracked_files():
        if rel in PENDING_OPERATOR_EDIT:
            continue
        path = REPO_ROOT / rel
        if path.suffix not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in ATTRIBUTION_PATTERNS:
            match = pattern.search(text)
            if match:
                line_no = text[: match.start()].count("\n") + 1
                offenders.append(f"{rel}:{line_no}: {match.group(0)!r}")
                break
    assert not offenders, (
        "operator-attributed diagnostic text found on tracked surfaces "
        "(redaction class regression):\n" + "\n".join(offenders)
    )
