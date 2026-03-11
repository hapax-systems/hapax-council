"""Integration tests for cycle mode affecting agent thresholds."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from shared.cycle_mode import CycleMode


def test_probe_cooldown_prod(tmp_path):
    mode_file = tmp_path / "cycle-mode"
    mode_file.write_text("prod\n")
    with patch("shared.cycle_mode.MODE_FILE", mode_file):
        from cockpit.micro_probes import _probe_cooldown
        assert _probe_cooldown() == 600


def test_probe_cooldown_dev(tmp_path):
    mode_file = tmp_path / "cycle-mode"
    mode_file.write_text("dev\n")
    with patch("shared.cycle_mode.MODE_FILE", mode_file):
        from cockpit.micro_probes import _probe_cooldown
        assert _probe_cooldown() == 1800


def test_probe_idle_threshold_prod(tmp_path):
    mode_file = tmp_path / "cycle-mode"
    mode_file.write_text("prod\n")
    with patch("shared.cycle_mode.MODE_FILE", mode_file):
        from cockpit.micro_probes import _probe_idle_threshold
        assert _probe_idle_threshold() == 300


def test_probe_idle_threshold_dev(tmp_path):
    mode_file = tmp_path / "cycle-mode"
    mode_file.write_text("dev\n")
    with patch("shared.cycle_mode.MODE_FILE", mode_file):
        from cockpit.micro_probes import _probe_idle_threshold
        assert _probe_idle_threshold() == 900


def test_cache_fast_interval_prod(tmp_path):
    mode_file = tmp_path / "cycle-mode"
    mode_file.write_text("prod\n")
    with patch("shared.cycle_mode.MODE_FILE", mode_file):
        from cockpit.api.cache import _fast_interval, _slow_interval
        assert _fast_interval() == 30
        assert _slow_interval() == 300


def test_cache_intervals_dev(tmp_path):
    mode_file = tmp_path / "cycle-mode"
    mode_file.write_text("dev\n")
    with patch("shared.cycle_mode.MODE_FILE", mode_file):
        from cockpit.api.cache import _fast_interval, _slow_interval
        assert _fast_interval() == 15
        assert _slow_interval() == 120
