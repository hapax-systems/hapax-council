"""Tests for the audio-health meta-monitor (M0)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from agents.audio_health_meta import (
    MetaMonitorConfig,
    MonitorStatus,
    check_monitor,
    run_tick,
    write_snapshot,
)


def test_check_monitor_file_missing(tmp_path: Path):
    """Missing textfile → up=False."""
    status = check_monitor(tmp_path, "nonexistent.prom", 90.0, 1000.0)
    assert status.up is False
    assert status.exists is False
    assert status.age_s is None


def test_check_monitor_file_fresh(tmp_path: Path):
    """Fresh textfile → up=True."""
    prom = tmp_path / "hapax_audio_signal_health.prom"
    prom.write_text("# some metrics\n")
    now = prom.stat().st_mtime + 10.0  # 10s old, max is 90s
    status = check_monitor(tmp_path, "hapax_audio_signal_health.prom", 90.0, now)
    assert status.up is True
    assert status.exists is True
    assert status.age_s is not None
    assert status.age_s <= 90.0


def test_check_monitor_file_stale(tmp_path: Path):
    """Stale textfile → up=False."""
    prom = tmp_path / "hapax_audio_signal_health.prom"
    prom.write_text("# some metrics\n")
    # Force stale by checking far in the future
    now = prom.stat().st_mtime + 200.0  # 200s old, max is 90s
    status = check_monitor(tmp_path, "hapax_audio_signal_health.prom", 90.0, now)
    assert status.up is False
    assert status.exists is True
    assert status.age_s is not None
    assert status.age_s > 90.0


def test_write_snapshot(tmp_path: Path):
    """write_snapshot produces valid JSON."""
    snapshot_path = tmp_path / "meta.json"
    statuses = [
        MonitorStatus(
            basename="test.prom",
            path=tmp_path / "test.prom",
            exists=True,
            mtime=1000.0,
            age_s=5.0,
            max_age_s=90.0,
            up=True,
        ),
    ]
    write_snapshot(snapshot_path, statuses, 1005.0)
    assert snapshot_path.exists()
    data = json.loads(snapshot_path.read_text())
    assert data["all_up"] is True
    assert len(data["monitors"]) == 1
    assert data["monitors"][0]["basename"] == "test.prom"
    assert data["monitors"][0]["up"] is True


def test_run_tick_all_up(tmp_path: Path):
    """run_tick with a fresh file reports all up."""
    prom = tmp_path / "hapax_audio_signal_health.prom"
    prom.write_text("# metrics\n")

    config = MetaMonitorConfig(
        textfile_dir=tmp_path,
        monitors={"hapax_audio_signal_health.prom": 90.0},
        snapshot_path=tmp_path / "meta.json",
        enable_ntfy=False,
    )

    now = prom.stat().st_mtime + 5.0
    with patch("agents.audio_health_meta.emit_meta_metrics"):
        statuses, up_map = run_tick(config, now=now)

    assert len(statuses) == 1
    assert statuses[0].up is True
    assert up_map["hapax_audio_signal_health.prom"] is True


def test_run_tick_monitor_down_ntfys(tmp_path: Path):
    """run_tick ntfys on transition from up to down."""
    config = MetaMonitorConfig(
        textfile_dir=tmp_path,
        monitors={"missing.prom": 90.0},
        snapshot_path=tmp_path / "meta.json",
        enable_ntfy=True,
    )

    with (
        patch("agents.audio_health_meta.emit_meta_metrics"),
        patch("agents.audio_health_meta._ntfy_monitor_down") as mock_ntfy,
    ):
        # First tick: was_up defaults to True, file missing → ntfy
        statuses, up_map = run_tick(config, now=1000.0)

    assert statuses[0].up is False
    mock_ntfy.assert_called_once()


def test_run_tick_no_double_ntfy(tmp_path: Path):
    """run_tick does NOT re-ntfy if monitor stays down."""
    config = MetaMonitorConfig(
        textfile_dir=tmp_path,
        monitors={"missing.prom": 90.0},
        snapshot_path=tmp_path / "meta.json",
        enable_ntfy=True,
    )

    with (
        patch("agents.audio_health_meta.emit_meta_metrics"),
        patch("agents.audio_health_meta._ntfy_monitor_down") as mock_ntfy,
    ):
        # First tick: transition down → ntfy
        _, up_map = run_tick(config, now=1000.0)
        assert mock_ntfy.call_count == 1

        # Second tick: still down → no ntfy
        _, up_map2 = run_tick(config, now=1060.0, previous_up=up_map)
        assert mock_ntfy.call_count == 1  # unchanged


def test_config_from_env():
    """MetaMonitorConfig.from_env() picks up defaults."""
    config = MetaMonitorConfig.from_env()
    assert config.probe_interval_s == 60.0
    assert "hapax_audio_signal_health.prom" in config.monitors


def test_sd_notify_integration():
    """_try_sd_notify doesn't crash when sdnotify is unavailable."""
    from agents.audio_health_meta import _try_sd_notify

    # Should not raise even if sdnotify is missing
    _try_sd_notify("READY=1")
    _try_sd_notify("WATCHDOG=1")
