"""Regression gate: no PreSonus Studio 24c references in code/config.

Per `feedback_no_24c_ever` (memory, 2026-05-03): the PreSonus Studio
24c interface was retired + unplugged 2026-05-03. The L-12 + Evil Pet
chain replaced it. Operator directive: ZERO mentions in any context —
no "previously 24c", no "post-24c retirement", no historical refs.
Treat as if it never existed.

This test scans the live code/config tree for any 24c references and
fails if any are found, preventing silent re-introduction.

Scope: Python source, shell scripts, YAML configs. Excludes
documentation prose, design-language docs, vault content, and the
test file itself.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Patterns that indicate a 24c reference. Case-insensitive.
FORBIDDEN_PATTERNS: tuple[str, ...] = (
    r"\b24c\b",
    r"\b24-c\b",
    r"PreSonus_Studio_24",
    r"PreSonus Studio 24",
    r"Studio_24c",
)

# Directories to scan. The live code surface, not docs.
SCAN_DIRS: tuple[Path, ...] = (
    REPO_ROOT / "agents",
    REPO_ROOT / "shared",
    REPO_ROOT / "config",
    REPO_ROOT / "scripts",
)

# File extensions in scope.
SCAN_EXTS: frozenset[str] = frozenset({".py", ".sh", ".yaml", ".yml", ".json"})

# Files explicitly excluded.
SCAN_EXCLUDES: frozenset[Path] = frozenset(
    {
        # The test file itself — references the patterns it scans for.
        Path(__file__).resolve(),
    }
)


def _iter_files() -> list[Path]:
    files: list[Path] = []
    for d in SCAN_DIRS:
        if not d.exists():
            continue
        for path in d.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in SCAN_EXTS:
                continue
            if "__pycache__" in path.parts or ".venv" in path.parts:
                continue
            if path.resolve() in SCAN_EXCLUDES:
                continue
            files.append(path)
    return sorted(files)


def test_no_24c_references_in_code_or_config() -> None:
    compiled = [re.compile(p, re.IGNORECASE) for p in FORBIDDEN_PATTERNS]
    violations: list[tuple[Path, int, str, str]] = []
    for path in _iter_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pat in compiled:
                if pat.search(line):
                    violations.append((path, lineno, pat.pattern, line.strip()))
                    break
    if violations:
        lines = ["Forbidden 24c references found:"]
        for path, lineno, pattern, line in violations:
            rel = path.relative_to(REPO_ROOT)
            lines.append(f"  {rel}:{lineno} pattern={pattern!r}: {line[:100]}")
        lines.append("")
        lines.append(
            "Per feedback_no_24c_ever (operator directive 2026-05-03): "
            "the PreSonus Studio 24c is retired. ZERO mentions allowed in "
            "code or config. Remove or rewrite to reference the L-12 "
            "broadcast chain instead. Treat as if 24c never existed."
        )
        import pytest

        pytest.fail("\n".join(lines))
