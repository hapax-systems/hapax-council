"""Tests for shared/vault_writer.py — Obsidian vault egress.

Uses tmp_path for filesystem isolation. No real vault access.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from shared.vault_writer import (
    write_to_vault,
    write_briefing_to_vault,
    write_digest_to_vault,
    write_nudges_to_vault,
    write_goals_to_vault,
    write_bridge_prompt_to_vault,
    create_decision_starter,
    SYSTEM_DIR,
    BRIEFINGS_DIR,
    DIGESTS_DIR,
)


@pytest.fixture
def fake_vault(tmp_path: Path):
    """Patch VAULT_PATH to a temporary directory."""
    with patch("shared.vault_writer.VAULT_PATH", tmp_path), \
         patch("shared.vault_writer.SYSTEM_DIR", tmp_path / "system"), \
         patch("shared.vault_writer.BRIEFINGS_DIR", tmp_path / "system" / "briefings"), \
         patch("shared.vault_writer.DIGESTS_DIR", tmp_path / "system" / "digests"):
        yield tmp_path


# ── write_to_vault ───────────────────────────────────────────────────────────

class TestWriteToVault:
    def test_basic_write(self, fake_vault: Path):
        path = write_to_vault("system", "test.md", "Hello world")
        assert path.exists()
        content = path.read_text()
        assert "Hello world" in content

    def test_creates_directories(self, fake_vault: Path):
        path = write_to_vault("system/deep/nested", "doc.md", "content")
        assert path.exists()
        assert (fake_vault / "system" / "deep" / "nested").is_dir()

    def test_with_frontmatter(self, fake_vault: Path):
        path = write_to_vault(
            "system", "fm.md", "Body",
            frontmatter={"type": "test", "version": 1},
        )
        content = path.read_text()
        assert content.startswith("---\n")
        assert "type: test" in content
        assert "---" in content
        assert "Body" in content

    def test_overwrites_existing(self, fake_vault: Path):
        write_to_vault("system", "over.md", "First")
        write_to_vault("system", "over.md", "Second")
        content = (fake_vault / "system" / "over.md").read_text()
        assert "Second" in content
        assert "First" not in content


# ── write_briefing_to_vault ──────────────────────────────────────────────────

class TestWriteBriefingToVault:
    def test_writes_dated_file(self, fake_vault: Path):
        path = write_briefing_to_vault("# Briefing\nAll good.")
        # Should be named with today's date
        assert path.name.endswith(".md")
        assert len(path.name) == len("2026-03-01.md")
        assert "system/briefings" in str(path.parent)
        content = path.read_text()
        assert "# Briefing" in content
        assert "type: briefing" in content


# ── write_digest_to_vault ───────────────────────────────────────────────────

class TestWriteDigestToVault:
    def test_writes_dated_file(self, fake_vault: Path):
        path = write_digest_to_vault("# Content Digest\n5 new documents.")
        assert path.name.endswith(".md")
        assert "digest" in path.name
        assert "system/digests" in str(path.parent)
        content = path.read_text()
        assert "# Content Digest" in content
        assert "type: digest" in content

    def test_content_preserved(self, fake_vault: Path):
        md = "# Digest\n\n## Notable Items\n- Paper A\n- Paper B"
        path = write_digest_to_vault(md)
        content = path.read_text()
        assert "Paper A" in content
        assert "Paper B" in content


# ── write_nudges_to_vault ────────────────────────────────────────────────────

class TestWriteNudgesToVault:
    def test_empty_nudges(self, fake_vault: Path):
        path = write_nudges_to_vault([])
        content = path.read_text()
        assert "No active nudges" in content

    def test_with_nudges(self, fake_vault: Path):
        nudges = [
            {"priority": 10, "source": "health", "message": "3 checks degraded", "action": "Run --verbose"},
            {"priority": 50, "source": "goals", "message": "Goal stale", "action": ""},
        ]
        path = write_nudges_to_vault(nudges)
        content = path.read_text()
        assert "- [ ]" in content  # Tasks-compatible checkbox
        assert "3 checks degraded" in content
        assert "Goal stale" in content
        assert path.name == "nudges.md"

    def test_nudges_sorted_by_priority(self, fake_vault: Path):
        nudges = [
            {"priority": 30, "source": "goals", "message": "Low priority"},
            {"priority": 80, "source": "health", "message": "High priority"},
        ]
        path = write_nudges_to_vault(nudges)
        content = path.read_text()
        # Higher priority_score = more urgent, sorted first (descending)
        assert content.index("High priority") < content.index("Low priority")


# ── write_goals_to_vault ─────────────────────────────────────────────────────

class TestWriteGoalsToVault:
    def test_basic_goals(self, fake_vault: Path):
        goals = [
            {"name": "Learn Rust", "status": "active", "description": "Systems programming"},
            {"name": "Build MIDI tools", "status": "ongoing", "description": "MPC automation"},
        ]
        path = write_goals_to_vault(goals)
        content = path.read_text()
        assert "## Learn Rust" in content
        assert "**Status:** active" in content
        assert "Systems programming" in content
        assert path.name == "goals.md"

    def test_empty_goals(self, fake_vault: Path):
        path = write_goals_to_vault([])
        content = path.read_text()
        assert "# Operator Goals" in content


# ── write_bridge_prompt_to_vault ────────────────────────────────────────────

class TestWriteBridgePromptToVault:
    def test_writes_prompt(self, fake_vault: Path):
        path = write_bridge_prompt_to_vault("1on1-prep-prompt", "# Prompt\n[PERSON] context")
        assert path.exists()
        assert path.name == "1on1-prep-prompt.md"
        content = path.read_text()
        assert "type: bridge-prompt" in content
        assert "[PERSON]" in content
        assert "32-bridge/prompts" in str(path.parent)

    def test_directory_created(self, fake_vault: Path):
        write_bridge_prompt_to_vault("test", "content")
        assert (fake_vault / "32-bridge" / "prompts").is_dir()


# ── Starter doc writers ────────────────────────────────────────────────────

class TestDecisionStarter:
    def test_creates_decision_doc(self, fake_vault: Path):
        path = create_decision_starter("Use PostgreSQL for data storage", "2026-03-03-meeting")
        assert path is not None
        assert path.exists()
        content = path.read_text()
        assert "type: decision" in content
        assert "PostgreSQL" in content
        assert "[[2026-03-03-meeting]]" in content
        assert "## Rationale" in content  # blank for operator

    def test_slug_generation(self, fake_vault: Path):
        path = create_decision_starter("Adopt Python 3.12", "meeting-ref")
        assert "adopt-python" in path.name


# ── F-4.2: Atomic write_to_vault ──────────────────────────────────────────

class TestAtomicWrite:
    """Verify write_to_vault uses atomic write (no temp files left)."""

    @pytest.fixture(autouse=True)
    def fake_vault(self, tmp_path: Path):
        with patch("shared.vault_writer.VAULT_PATH", tmp_path):
            yield tmp_path

    def test_write_to_vault_atomic(self, fake_vault: Path):
        from shared.vault_writer import write_to_vault
        path = write_to_vault("30-system", "test.md", "Hello world")
        assert path is not None
        assert path.read_text() == "Hello world"
        # No leftover temp files
        temps = list((fake_vault / "30-system").glob("*.md"))
        assert len(temps) == 1
