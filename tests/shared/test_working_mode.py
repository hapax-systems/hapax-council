"""Tests for shared.working_mode.

62-LOC working-mode reader/writer (RESEARCH / RND / FORTRESS).
Untested before this commit. Tests monkeypatch ``WORKING_MODE_FILE``
so the operator's real ~/.cache/hapax/working-mode is never read or
mutated.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shared import working_mode
from shared.working_mode import (
    WorkingMode,
    get_working_mode,
    is_fortress,
    is_research,
    is_rnd,
    set_working_mode,
)


@pytest.fixture
def fake_mode_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "working-mode"
    monkeypatch.setattr(working_mode, "WORKING_MODE_FILE", path)
    return path


# ── Enum membership pin ────────────────────────────────────────────


class TestEnumMembership:
    def test_three_modes_pinned(self) -> None:
        assert {m.name for m in WorkingMode} == {"RESEARCH", "RND", "FORTRESS"}

    def test_wire_values_pinned(self) -> None:
        assert WorkingMode.RESEARCH.value == "research"
        assert WorkingMode.RND.value == "rnd"
        assert WorkingMode.FORTRESS.value == "fortress"


# ── get_working_mode ───────────────────────────────────────────────


class TestGetWorkingMode:
    def test_missing_file_defaults_to_rnd(self, fake_mode_file: Path) -> None:
        assert not fake_mode_file.exists()
        assert get_working_mode() == WorkingMode.RND

    def test_reads_research(self, fake_mode_file: Path) -> None:
        fake_mode_file.write_text("research")
        assert get_working_mode() == WorkingMode.RESEARCH

    def test_reads_fortress(self, fake_mode_file: Path) -> None:
        fake_mode_file.write_text("fortress")
        assert get_working_mode() == WorkingMode.FORTRESS

    def test_invalid_value_defaults_to_rnd(self, fake_mode_file: Path) -> None:
        fake_mode_file.write_text("party")
        assert get_working_mode() == WorkingMode.RND

    def test_whitespace_stripped(self, fake_mode_file: Path) -> None:
        fake_mode_file.write_text("  research\n")
        assert get_working_mode() == WorkingMode.RESEARCH


# ── set_working_mode ───────────────────────────────────────────────


class TestSetWorkingMode:
    def test_writes_mode_value(self, fake_mode_file: Path) -> None:
        set_working_mode(WorkingMode.RESEARCH)
        assert fake_mode_file.read_text() == "research"

    def test_creates_parent_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        nested = tmp_path / "deep" / "nested" / "working-mode"
        monkeypatch.setattr(working_mode, "WORKING_MODE_FILE", nested)
        set_working_mode(WorkingMode.FORTRESS)
        assert nested.exists()
        assert nested.read_text() == "fortress"

    def test_overwrites_existing(self, fake_mode_file: Path) -> None:
        fake_mode_file.write_text("research")
        set_working_mode(WorkingMode.RND)
        assert fake_mode_file.read_text() == "rnd"


# ── Predicate helpers ──────────────────────────────────────────────


class TestPredicates:
    def test_is_research(self, fake_mode_file: Path) -> None:
        fake_mode_file.write_text("research")
        assert is_research()
        assert not is_rnd()
        assert not is_fortress()

    def test_is_rnd(self, fake_mode_file: Path) -> None:
        fake_mode_file.write_text("rnd")
        assert is_rnd()
        assert not is_research()
        assert not is_fortress()

    def test_is_fortress(self, fake_mode_file: Path) -> None:
        fake_mode_file.write_text("fortress")
        assert is_fortress()
        assert not is_research()
        assert not is_rnd()

    def test_predicates_default_to_rnd(self, fake_mode_file: Path) -> None:
        """No file → RND default → only is_rnd() returns True."""
        assert not fake_mode_file.exists()
        assert is_rnd()
        assert not is_research()
        assert not is_fortress()
