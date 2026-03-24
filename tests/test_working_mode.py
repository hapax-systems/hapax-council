"""Tests for shared.working_mode — unified working mode reader."""

from __future__ import annotations

from unittest.mock import patch


def test_working_mode_enum_has_two_members():
    from shared.working_mode import WorkingMode

    assert {WorkingMode.RESEARCH, WorkingMode.RND}.issubset(set(WorkingMode))


def test_get_working_mode_default_rnd(tmp_path):
    """Missing file defaults to rnd."""
    from shared.working_mode import WorkingMode, get_working_mode

    with patch("shared.working_mode.WORKING_MODE_FILE", tmp_path / "nonexistent"):
        assert get_working_mode() == WorkingMode.RND


def test_get_working_mode_reads_research(tmp_path):
    from shared.working_mode import WorkingMode, get_working_mode

    mode_file = tmp_path / "working-mode"
    mode_file.write_text("research\n")
    with patch("shared.working_mode.WORKING_MODE_FILE", mode_file):
        assert get_working_mode() == WorkingMode.RESEARCH


def test_get_working_mode_reads_rnd(tmp_path):
    from shared.working_mode import WorkingMode, get_working_mode

    mode_file = tmp_path / "working-mode"
    mode_file.write_text("rnd\n")
    with patch("shared.working_mode.WORKING_MODE_FILE", mode_file):
        assert get_working_mode() == WorkingMode.RND


def test_get_working_mode_invalid_defaults_rnd(tmp_path):
    from shared.working_mode import WorkingMode, get_working_mode

    mode_file = tmp_path / "working-mode"
    mode_file.write_text("turbo\n")
    with patch("shared.working_mode.WORKING_MODE_FILE", mode_file):
        assert get_working_mode() == WorkingMode.RND


def test_is_research_helper(tmp_path):
    from shared.working_mode import is_research, is_rnd

    mode_file = tmp_path / "working-mode"
    mode_file.write_text("research\n")
    with patch("shared.working_mode.WORKING_MODE_FILE", mode_file):
        assert is_research() is True
        assert is_rnd() is False


def test_is_rnd_helper(tmp_path):
    from shared.working_mode import is_research, is_rnd

    mode_file = tmp_path / "working-mode"
    mode_file.write_text("rnd\n")
    with patch("shared.working_mode.WORKING_MODE_FILE", mode_file):
        assert is_rnd() is True
        assert is_research() is False


def test_set_working_mode(tmp_path):
    from shared.working_mode import WorkingMode, get_working_mode, set_working_mode

    mode_file = tmp_path / "working-mode"
    with patch("shared.working_mode.WORKING_MODE_FILE", mode_file):
        set_working_mode(WorkingMode.RESEARCH)
        assert get_working_mode() == WorkingMode.RESEARCH
        set_working_mode(WorkingMode.RND)
        assert get_working_mode() == WorkingMode.RND


def test_cycle_mode_shim_maps_correctly(tmp_path):
    """The backward-compat shim re-exports working mode as CycleMode."""
    from shared.cycle_mode import CycleMode, get_cycle_mode

    mode_file = tmp_path / "working-mode"
    mode_file.write_text("rnd\n")
    with patch("shared.working_mode.WORKING_MODE_FILE", mode_file):
        result = get_cycle_mode()
        assert result == CycleMode.RND
        assert result.value == "rnd"
