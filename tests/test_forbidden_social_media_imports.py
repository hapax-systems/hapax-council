"""Forbidden-import CI guard for multi-user-platform client libraries.

The "social_media" in the filename is shorthand: this guard covers
all multi-user platform clients where engagement expectations
collide with the single-operator axiom or the full-automation
envelope.

Per cc-tasks:
  - ``leverage-REFUSED-twitter-linkedin-substack-accounts``: Twitter/X,
    LinkedIn, Substack are operator-mediated relationship-management
    surfaces, not daemon-tractable.
  - ``leverage-REFUSED-discord-community``: Discord is multi-user;
    single-operator axiom precludes community moderation. Per
    ``awareness-refused-slack-discord-dm-bots`` precedent, slack and
    discord webhook clients are also refused.
  - ``leverage-REFUSED-wikipedia-auto-edit``: Wikipedia is multi-user;
    ToS forbids unflagged bot editing; flagged-bot path requires
    operator-mediated edit-approval workflow.
  - ``leverage-REFUSED-bot-driven-sc-inflation``: SoundCloud ToS forbids
    bot-driven plays / follows / reposts. Enforced as a path-based
    guard (``FORBIDDEN_PACKAGE_PATHS``) rather than a library-import
    guard because the legitimate ``agents/soundcloud_adapter/`` reads
    SC for bed-music routing (per
    ``project_soundcloud_bed_music_routing``).

All refusals trace to ``feedback_full_automation_or_no_engagement``
(operator constitutional directive 2026-04-25). The guard is a
grep-based test (no AST parsing required) that walks the agents/,
shared/, scripts/, and logos/ trees.

Authorized social fan-out must route through publication-bus publishers
(including Bridgy POSSE and the bus-backed Mastodon/Bluesky public-event
posters). Wikipedia citations to Hapax can arrive organically via third-party
editors who notice arXiv preprint / Zenodo DOI — daemon participation is
unnecessary.

Editing the forbidden list directly is governance-protected — these
strings come out of the operator's constitutional posture and
removing them without an axiom-precedent change is a non-starter.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

FORBIDDEN_IMPORTS: Final[tuple[str, ...]] = (
    # Per cc-task leverage-REFUSED-twitter-linkedin-substack-accounts
    "tweepy",
    "linkedin_api",
    "linkedin-api",
    "substackapi",
    "substack-api",
    # Per cc-task leverage-REFUSED-discord-community + awareness-refused-slack-discord-dm-bots
    "discord",
    "discord_py",
    "discord.py",
    "slack_sdk",
    "slack-sdk",
    # Per cc-task leverage-REFUSED-wikipedia-auto-edit
    "pywikibot",
    "mwclient",
    # NOTE: SoundCloud library imports are NOT in FORBIDDEN_IMPORTS — the
    # legitimate ``agents/soundcloud_adapter/`` reads SC for bed-music
    # routing (per ``project_soundcloud_bed_music_routing``). The
    # leverage-REFUSED-bot-driven-sc-inflation refusal is enforced via
    # FORBIDDEN_PACKAGE_PATHS below (path-based, not import-based) so
    # the legitimate adapter is not false-positive flagged.
)
"""Python clients for refused multi-user-platform surfaces.

The discord/slack additions are per
``leverage-REFUSED-discord-community`` and the
``awareness-refused-slack-discord-dm-bots`` precedent. Multi-user
chat-platform community moderation violates the single-operator axiom;
direct DM bots also violate the consent gate.

The Wikipedia additions are per ``leverage-REFUSED-wikipedia-auto-edit``.
Wikipedia ToS forbids unflagged bot editing; the flagged-bot path
requires per-edit operator decisions, violating full-automation."""

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

FORBIDDEN_PACKAGE_PATHS: Final[tuple[str, ...]] = (
    # Per cc-task leverage-REFUSED-bot-driven-sc-inflation:
    # bot-driven SoundCloud inflation is refused; legitimate
    # bed-music routing via agents/soundcloud_adapter/ is permitted.
    # Path-based check forbids inflation-named packages without
    # blocking the legitimate adapter.
    "agents/soundcloud_inflater",
    "agents/soundcloud_inflator",
    "agents/sc_inflater",
    # Per cc-task leverage-REFUSED-tutorial-videos:
    # tutorial-video production is operator-physical (on-camera or
    # voiced narration). Existing agents/video_capture/ +
    # agents/video_processor/ are livestream infrastructure (per
    # project_livestream_is_research) and remain permitted.
    "agents/tutorial_publisher",
    "agents/tutorial_videos",
    "agents/youtube_tutorials",
    "agents/educational_content",
    # Per cc-task leverage-REFUSED-consulting-methodology-as-service:
    # consulting requires operator-mediated client engagement.
    # Methodology is shipped as PyPI packages (daemon-tractable);
    # consulting itself is not.
    "agents/consulting_dispatcher",
    "agents/consulting",
    "agents/calcom_integration",
    "agents/calendly_integration",
)
"""Refused package directory paths.

Path-based check (vs library-import check) is the appropriate
enforcement when the same library is used for both refused
(inflation) and permitted (bed-music routing) purposes. The check
walks the repo root looking for any directory matching these
prefixes."""


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


def _scan_for_forbidden_package_paths(
    forbidden: tuple[str, ...] = FORBIDDEN_PACKAGE_PATHS,
    *,
    repo_root: Path = REPO_ROOT,
) -> list[Path]:
    """Walk the repo root looking for any forbidden package directory.

    Returns paths to directories that exist under the repo root
    matching any forbidden prefix.
    """
    found: list[Path] = []
    for forbidden_path in forbidden:
        candidate = repo_root / forbidden_path
        if candidate.is_dir():
            found.append(candidate)
    return found


class TestForbiddenPackagePathGuard:
    def test_codebase_has_no_forbidden_package_paths(self) -> None:
        """Refused package paths must not exist in the repo."""
        found = _scan_for_forbidden_package_paths()
        assert found == [], (
            "Forbidden package paths detected:\n"
            + "\n".join(f"  {path}" for path in found)
            + "\n\n"
            "Per leverage-REFUSED-bot-driven-sc-inflation, these "
            "package paths represent refused inflation surfaces."
        )

    def test_scanner_detects_planted_package(self, tmp_path: Path) -> None:
        """Self-test: planted forbidden package is detected."""
        bad_dir = tmp_path / "agents" / "soundcloud_inflater"
        bad_dir.mkdir(parents=True)
        (bad_dir / "__init__.py").touch()
        found = _scan_for_forbidden_package_paths(repo_root=tmp_path)
        assert len(found) == 1


class TestForbiddenSocialMediaImportGuard:
    def test_codebase_has_no_forbidden_imports(self) -> None:
        """Codebase must not import any refused social-media client.

        Refused libs span Twitter/X, LinkedIn, Substack, Discord, and
        Slack — all relationship-management surfaces that violate
        ``feedback_full_automation_or_no_engagement``.
        """
        findings = _scan_for_forbidden_imports()
        assert findings == [], (
            "Forbidden social-media library imports detected:\n"
            + "\n".join(
                f"  {path}:{line_no}: {line.strip()} (lib: {lib})"
                for path, lib, line_no, line in findings
            )
            + "\n\n"
            "Per leverage-REFUSED-* cc-tasks, these surfaces are "
            "constitutionally refused. Use publication-bus-backed fan-out "
            "paths instead."
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
