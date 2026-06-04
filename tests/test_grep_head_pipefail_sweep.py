"""Regression for the grep|head SIGPIPE sweep.

Under ``set -euo pipefail``, ``grep ... | head`` can fail when ``head`` exits
after the requested first rows and ``grep`` receives SIGPIPE. The sanctioned
shape is ``grep -mN`` or a non-pipeline parser.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (
    REPO_ROOT / ".github" / "workflows",
    REPO_ROOT / "hooks" / "scripts",
)
UNSAFE_GREP_HEAD = re.compile(r"(?<![\w.-])grep(?:\s|$)[^;\n]*\|[^;\n]*\bhead\b")


def _logical_lines(path: Path) -> list[tuple[int, str]]:
    logical: list[tuple[int, str]] = []
    pending = ""
    pending_start = 0
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw.strip()
        if not pending and (not stripped or stripped.startswith("#")):
            continue
        line = raw.rstrip()
        if pending:
            pending += " " + line.lstrip()
        else:
            pending = line
            pending_start = lineno
        if pending.rstrip().endswith("\\"):
            pending = pending.rstrip()[:-1]
            continue
        logical.append((pending_start, pending))
        pending = ""
    if pending:
        logical.append((pending_start, pending))
    return logical


def test_no_unguarded_grep_head_pipelines_in_ci_or_hooks() -> None:
    offenders: list[str] = []
    for root in SCAN_ROOTS:
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            if root.name == "workflows" and path.suffix not in {".yml", ".yaml"}:
                continue
            if root.name == "scripts" and path.suffix not in {"", ".sh"}:
                continue
            for lineno, line in _logical_lines(path):
                if UNSAFE_GREP_HEAD.search(line):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")

    assert offenders == []
