# shared/axiom_patterns.py
"""Load T0 violation patterns for axiom enforcement scanning.

Patterns are loaded from a data file rather than defined inline to avoid
triggering the axiom-scan.sh PreToolUse hook on the patterns themselves.

Usage:
    from shared.axiom_patterns import load_t0_patterns, scan_file
    patterns = load_t0_patterns()
    violations = scan_file(Path("some_file.py"), patterns)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Pattern data file lives alongside this module
_PATTERNS_FILE = Path(__file__).parent / "axiom_patterns.txt"

# Directories and files to skip during scanning
EXCLUDE_DIRS = frozenset(
    {
        ".venv",
        "venv",
        "node_modules",
        ".git",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "dist",
        "build",
        ".eggs",
        "site-packages",
        ".next",
        ".nuxt",
        "coverage",
        ".coverage",
        "htmlcov",
        "egg-info",
    }
)

# Directory prefixes to exclude (matches .venv311, .venv-test, etc.)
EXCLUDE_DIR_PREFIXES = (".venv", "venv-")

EXCLUDE_FILES = frozenset(
    {
        "axiom-patterns.sh",
        "axiom-scan.sh",
        "axiom-commit-scan.sh",
        "test_axiom_hooks.py",
        "axiom-sweep.sh",
        "axiom_patterns.py",
        "axiom_patterns.txt",
    }
)

SOURCE_EXTS = frozenset({".py", ".ts", ".js", ".sh"})


@dataclass
class PatternMatch:
    file: str
    line: int
    pattern: str
    content: str


def load_t0_patterns() -> list[re.Pattern[str]]:
    """Load compiled T0 violation regex patterns from data file."""
    if not _PATTERNS_FILE.exists():
        return []
    patterns = []
    for line in _PATTERNS_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(re.compile(line))
    return patterns


def scan_file(
    path: Path,
    patterns: list[re.Pattern[str]],
) -> list[PatternMatch]:
    """Scan a single file for T0 pattern violations."""
    if path.name in EXCLUDE_FILES:
        return []
    if path.suffix not in SOURCE_EXTS:
        return []
    try:
        content = path.read_text(errors="replace")
    except OSError:
        return []

    matches = []
    for pat in patterns:
        for m in pat.finditer(content):
            line_num = content[: m.start()].count("\n") + 1
            matches.append(
                PatternMatch(
                    file=str(path),
                    line=line_num,
                    pattern=pat.pattern,
                    content=m.group(0)[:80],
                )
            )
    return matches


def scan_directory(
    root: Path,
    patterns: list[re.Pattern[str]],
) -> list[PatternMatch]:
    """Recursively scan a directory for T0 pattern violations."""
    import os

    all_matches = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [
            d
            for d in dirs
            if d not in EXCLUDE_DIRS
            and not d.startswith(EXCLUDE_DIR_PREFIXES)
            and not d.endswith(".egg-info")
        ]
        for fname in files:
            fpath = Path(dirpath) / fname
            all_matches.extend(scan_file(fpath, patterns))
    return all_matches
