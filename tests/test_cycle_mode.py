"""Tests for shared.cycle_mode — cycle mode reader."""

from __future__ import annotations

from unittest.mock import patch


def test_cycle_mode_enum_has_two_members():
    from shared.cycle_mode import CycleMode

    assert set(CycleMode) == {CycleMode.PROD, CycleMode.DEV}


def test_get_cycle_mode_default_prod(tmp_path):
    """Missing file defaults to prod."""
    from shared.cycle_mode import CycleMode, get_cycle_mode

    with patch("shared.cycle_mode.MODE_FILE", tmp_path / "nonexistent"):
        assert get_cycle_mode() == CycleMode.PROD


def test_get_cycle_mode_reads_dev(tmp_path):
    """File containing 'dev' returns DEV."""
    from shared.cycle_mode import CycleMode, get_cycle_mode

    mode_file = tmp_path / "cycle-mode"
    mode_file.write_text("dev\n")
    with patch("shared.cycle_mode.MODE_FILE", mode_file):
        assert get_cycle_mode() == CycleMode.DEV


def test_get_cycle_mode_reads_prod(tmp_path):
    """File containing 'prod' returns PROD."""
    from shared.cycle_mode import CycleMode, get_cycle_mode

    mode_file = tmp_path / "cycle-mode"
    mode_file.write_text("prod\n")
    with patch("shared.cycle_mode.MODE_FILE", mode_file):
        assert get_cycle_mode() == CycleMode.PROD


def test_get_cycle_mode_invalid_defaults_prod(tmp_path):
    """File containing garbage defaults to prod."""
    from shared.cycle_mode import CycleMode, get_cycle_mode

    mode_file = tmp_path / "cycle-mode"
    mode_file.write_text("turbo\n")
    with patch("shared.cycle_mode.MODE_FILE", mode_file):
        assert get_cycle_mode() == CycleMode.PROD
