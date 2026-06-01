"""Dynamic sprint-subtree resolution for the sprint tracker (OQ-9 feeders repair).

The sprint subtree path was hardcoded to ``20-projects/hapax-research/sprint``; a
PARA reorganisation would silently strand the tracker. ``_resolve_sprint_dir`` makes
the location dynamic: env override, then the default, then a vault search, then a
graceful fallback.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import agents.sprint_tracker as st


def test_env_override_wins(tmp_path: Path) -> None:
    target = tmp_path / "custom" / "sprint"
    with patch.dict(os.environ, {"HAPAX_SPRINT_DIR": str(target)}):
        assert st._resolve_sprint_dir(tmp_path) == target


def test_default_used_when_measures_present(tmp_path: Path) -> None:
    default = tmp_path / "20-projects" / "hapax-research" / "sprint"
    (default / "measures").mkdir(parents=True)
    with patch.dict(os.environ, {}, clear=True):
        assert st._resolve_sprint_dir(tmp_path) == default


def test_moved_subtree_found_by_search(tmp_path: Path) -> None:
    moved = tmp_path / "20-projects" / "new-research-home" / "sprint"
    measures = moved / "measures"
    measures.mkdir(parents=True)
    (measures / "1.1.md").write_text("---\nid: '1.1'\ntype: measure\n---\n", encoding="utf-8")
    with patch.dict(os.environ, {}, clear=True):
        assert st._resolve_sprint_dir(tmp_path) == moved


def test_search_skips_templates_and_prefers_populated(tmp_path: Path) -> None:
    # A template measures/ dir — must be skipped even though it has a note.
    tpl = tmp_path / "50-templates" / "measures"
    tpl.mkdir(parents=True)
    (tpl / "tpl.md").write_text("x", encoding="utf-8")
    # The live subtree, more populated.
    live = tmp_path / "20-projects" / "research" / "sprint" / "measures"
    live.mkdir(parents=True)
    (live / "a.md").write_text("x", encoding="utf-8")
    (live / "b.md").write_text("x", encoding="utf-8")
    with patch.dict(os.environ, {}, clear=True):
        assert st._resolve_sprint_dir(tmp_path) == live.parent


def test_fallback_to_default_when_nothing_found(tmp_path: Path) -> None:
    with patch.dict(os.environ, {}, clear=True):
        assert (
            st._resolve_sprint_dir(tmp_path)
            == tmp_path / "20-projects" / "hapax-research" / "sprint"
        )
