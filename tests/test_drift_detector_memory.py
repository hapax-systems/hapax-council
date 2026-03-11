"""Tests for drift_detector project memory enforcement check."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from agents.drift_detector import check_project_memory


def test_flags_repo_missing_claude_md(tmp_path):
    """Repo with no CLAUDE.md should be flagged."""
    repo = tmp_path / "fake-repo"
    repo.mkdir()
    with patch("agents.drift_detector.HAPAX_REPO_DIRS", [repo]):
        items = check_project_memory()
    assert len(items) == 1
    assert items[0].category == "missing_project_memory"
    assert "CLAUDE.md" in items[0].suggestion


def test_flags_repo_missing_memory_section(tmp_path):
    """Repo with CLAUDE.md but no Project Memory section should be flagged."""
    repo = tmp_path / "fake-repo"
    repo.mkdir()
    (repo / "CLAUDE.md").write_text("# Project\n\nSome content.\n")
    with patch("agents.drift_detector.HAPAX_REPO_DIRS", [repo]):
        items = check_project_memory()
    assert len(items) == 1
    assert items[0].category == "missing_project_memory"
    assert "Project Memory" in items[0].suggestion


def test_passes_repo_with_memory_section(tmp_path):
    """Repo with CLAUDE.md containing Project Memory section should pass."""
    repo = tmp_path / "fake-repo"
    repo.mkdir()
    (repo / "CLAUDE.md").write_text("# Project\n\n## Project Memory\n\n- Pattern A\n")
    with patch("agents.drift_detector.HAPAX_REPO_DIRS", [repo]):
        items = check_project_memory()
    assert len(items) == 0


def test_handles_nonexistent_repo(tmp_path):
    """Non-existent repo directory should be silently skipped."""
    fake = tmp_path / "does-not-exist"
    with patch("agents.drift_detector.HAPAX_REPO_DIRS", [fake]):
        items = check_project_memory()
    assert len(items) == 0
