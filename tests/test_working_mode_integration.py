"""Integration tests for working mode affecting agent thresholds."""

from __future__ import annotations

from unittest.mock import patch


def test_probe_cooldown_rnd(tmp_path):
    mode_file = tmp_path / "working-mode"
    mode_file.write_text("rnd\n")
    with patch("logos._working_mode.WORKING_MODE_FILE", mode_file):
        from logos.micro_probes import _probe_cooldown

        assert _probe_cooldown() == 600


def test_probe_cooldown_research(tmp_path):
    """Research mode suppresses probes."""
    mode_file = tmp_path / "working-mode"
    mode_file.write_text("research\n")
    with patch("logos._working_mode.WORKING_MODE_FILE", mode_file):
        from logos.micro_probes import _probe_cooldown

        assert _probe_cooldown() == 999999


def test_probe_idle_threshold_rnd(tmp_path):
    mode_file = tmp_path / "working-mode"
    mode_file.write_text("rnd\n")
    with patch("logos._working_mode.WORKING_MODE_FILE", mode_file):
        from logos.micro_probes import _probe_idle_threshold

        assert _probe_idle_threshold() == 300


def test_probe_idle_threshold_research(tmp_path):
    """Research mode suppresses probes."""
    mode_file = tmp_path / "working-mode"
    mode_file.write_text("research\n")
    with patch("logos._working_mode.WORKING_MODE_FILE", mode_file):
        from logos.micro_probes import _probe_idle_threshold

        assert _probe_idle_threshold() == 999999


def test_cache_intervals_always_fast(tmp_path):
    """Cache intervals are always at full speed regardless of mode."""
    from logos.api.cache import _fast_interval, _slow_interval

    assert _fast_interval() == 15
    assert _slow_interval() == 120
