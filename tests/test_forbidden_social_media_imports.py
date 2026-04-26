"""Forbidden-import CI guard for social-media client libraries.

Per cc-task ``leverage-REFUSED-twitter-linkedin-substack-accounts``
(``feedback_full_automation_or_no_engagement``, 2026-04-25): Twitter/X,
LinkedIn, and Substack are operator-mediated relationship-management
surfaces — not daemon-tractable. The constitutional refusal is
enforced via this CI guard: any import of ``tweepy``, ``linkedin-api``,
or ``substackapi`` (and a few related packages) fails the build.

Bridgy POSSE fan-out from omg.lol weblog reaches Mastodon + Bluesky;
that is the only authorized social fan-out path. Any direct social-
media client adoption must go through a constitutional review that
removes the underlying refusal.

The guard is a grep-based test (no AST parsing required) that walks
the agents/, shared/, scripts/, and logos/ trees. Editing the
forbidden list directly is governance-protected — these strings come
out of the operator's constitutional posture and removing them
without an axiom precedent change is a non-starter.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

FORBIDDEN_IMPORTS: Final[tuple[str, ...]] = (
    "tweepy",
    "linkedin_api",
    "linkedin-api",
    "substackapi",
    "substack-api",
)
"""Python clients for refused social-media surfaces. Per cc-task
``leverage-REFUSED-twitter-linkedin-substack-accounts``."""

SCAN_ROOTS: Final[tuple[str, ...]] = (
    "agents",
    "shared",
    "scripts",
    "logos",
)
"""Source-code directories scanned for forbidden imports. Tests and
vendored deps are excluded from the scan because they would generate
false positives on string-matching."""

EXCLUDE_FILE_NAMES: Final[frozenset[str]] = frozenset(
    {
        # The refusal-brief itself names the forbidden libs to document
        # the refusal — exclude it from the scan.
        "leverage-twitter-linkedin-substack.md",
    }
)


_IMPORT_PATTERN_TEMPLATE = r"^\s*(?:from\s+{lib}\s+import|import\s+{lib})\b"


def _scan_for_forbidden_imports(
    forbidden: tuple[str, ...] = FORBIDDEN_IMPORTS,
    *,
    repo_root: Path = REPO_ROOT,
) -> list[tuple[Path, str, int, str]]:
    """Walk the source tree looking for any forbidden import line.

    Returns a list of ``(path, lib, line_no, line)`` tuples, one per
    match. Empty list means the codebase is clean.
    """
    findings: list[tuple[Path, str, int, str]] = []
    for root_name in SCAN_ROOTS:
        root = repo_root / root_name
        if not root.is_dir():
            continue
        for py_file in root.rglob("*.py"):
            if py_file.name in EXCLUDE_FILE_NAMES:
                continue
            try:
                text = py_file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for lib in forbidden:
                # Build the regex per lib — escape package names with hyphens
                # by replacing them with underscores in the pattern (Python
                # imports always use underscore form, but the cc-task lists
                # both spellings to catch package-name variants).
                pattern = _IMPORT_PATTERN_TEMPLATE.format(lib=re.escape(lib.replace("-", "_")))
                for line_no, line in enumerate(text.splitlines(), 1):
                    if re.search(pattern, line):
                        findings.append((py_file, lib, line_no, line))
    return findings


class TestForbiddenSocialMediaImportGuard:
    def test_codebase_has_no_forbidden_imports(self) -> None:
        """Codebase must not import tweepy, linkedin-api, substackapi."""
        findings = _scan_for_forbidden_imports()
        assert findings == [], (
            "Forbidden social-media library imports detected:\n"
            + "\n".join(
                f"  {path}:{line_no}: {line.strip()} (lib: {lib})"
                for path, lib, line_no, line in findings
            )
            + "\n\n"
            "Per leverage-REFUSED-twitter-linkedin-substack-accounts, these "
            "surfaces are constitutionally refused. Use Bridgy POSSE fan-out "
            "from omg.lol weblog instead (reaches Mastodon + Bluesky)."
        )

    def test_scanner_detects_forbidden_import(self, tmp_path: Path) -> None:
        """Self-test: planted import is detected."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        bad_file = agents_dir / "bad_module.py"
        bad_file.write_text("import tweepy\n\nclass X:\n    pass\n")
        findings = _scan_for_forbidden_imports(repo_root=tmp_path)
        assert len(findings) == 1
        assert findings[0][1] == "tweepy"

    def test_scanner_detects_from_import(self, tmp_path: Path) -> None:
        """Self-test: ``from tweepy import X`` is detected."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        bad_file = agents_dir / "bad.py"
        bad_file.write_text("from tweepy import API\n")
        findings = _scan_for_forbidden_imports(repo_root=tmp_path)
        assert len(findings) == 1

    def test_scanner_skips_non_scan_dirs(self, tmp_path: Path) -> None:
        """Self-test: imports in non-source dirs (e.g., a docs/ dir)
        are not flagged."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        bad_file = docs_dir / "ignored.py"
        bad_file.write_text("import tweepy\n")
        findings = _scan_for_forbidden_imports(repo_root=tmp_path)
        assert findings == []

    def test_scanner_excludes_named_files(self, tmp_path: Path) -> None:
        """Self-test: explicitly-excluded files are not flagged."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        excluded_file = agents_dir / "leverage-twitter-linkedin-substack.md"
        # The exclude-by-name only fires on Python files; .md isn't scanned anyway.
        # Add a Python file with the same exclude target name.
        py_excluded = agents_dir / next(iter(EXCLUDE_FILE_NAMES))
        if py_excluded.suffix == ".py":
            py_excluded.write_text("import tweepy\n")
            findings = _scan_for_forbidden_imports(repo_root=tmp_path)
            assert findings == []
        else:
            # Excluded list is currently markdown-only — no Python entries —
            # so this is a smoke test that excluded markdown files don't get
            # scanned (because rglob('*.py') already filters them out).
            excluded_file.write_text("import tweepy\n")
            findings = _scan_for_forbidden_imports(repo_root=tmp_path)
            assert findings == []
