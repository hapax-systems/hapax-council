"""Tests for density field compute module (DensityFieldCompute class API)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from agents.density_field import (
    ALARM_THRESHOLD,
    DensityFieldCompute,
    DensityTemporalMode,
    read_temporal_mode,
)


def _write_shm(tmp_path: Path, sources: dict) -> Path:
    shm = tmp_path / "hapax-density-field" / "density-field.json"
    shm.parent.mkdir(parents=True, exist_ok=True)
    shm.write_text(json.dumps({"sources": sources}), encoding="utf-8")
    return shm


def test_baseline_on_zero_density(tmp_path: Path) -> None:
    shm = _write_shm(tmp_path, {"a": {"density": 0.0}})
    temporal = tmp_path / "hapax-density-field" / "temporal-mode.json"
    with (
        patch("agents.density_field.DENSITY_FIELD_SHM", shm),
        patch("agents.density_field.TEMPORAL_STATE_PATH", temporal),
    ):
        dfc = DensityFieldCompute()
        mode = dfc.tick()
    assert mode == DensityTemporalMode.BASELINE
    assert dfc.last_density == 0.0


def test_rising_on_moderate_density(tmp_path: Path) -> None:
    shm = _write_shm(tmp_path, {"a": {"density": 0.4}})
    temporal = tmp_path / "hapax-density-field" / "temporal-mode.json"
    with (
        patch("agents.density_field.DENSITY_FIELD_SHM", shm),
        patch("agents.density_field.TEMPORAL_STATE_PATH", temporal),
    ):
        dfc = DensityFieldCompute()
        mode = dfc.tick()
    assert mode == DensityTemporalMode.RISING


def test_sustained_on_high_density(tmp_path: Path) -> None:
    shm = _write_shm(tmp_path, {"a": {"density": 0.6}})
    temporal = tmp_path / "hapax-density-field" / "temporal-mode.json"
    with (
        patch("agents.density_field.DENSITY_FIELD_SHM", shm),
        patch("agents.density_field.TEMPORAL_STATE_PATH", temporal),
    ):
        dfc = DensityFieldCompute()
        mode = dfc.tick()
    assert mode == DensityTemporalMode.SUSTAINED


def test_density_bounded(tmp_path: Path) -> None:
    shm = _write_shm(tmp_path, {"a": {"density": 0.5}, "b": {"density": 0.8}})
    temporal = tmp_path / "hapax-density-field" / "temporal-mode.json"
    with (
        patch("agents.density_field.DENSITY_FIELD_SHM", shm),
        patch("agents.density_field.TEMPORAL_STATE_PATH", temporal),
    ):
        dfc = DensityFieldCompute()
        dfc.tick()
    assert 0.0 <= dfc.last_density <= 1.0


def test_writes_temporal_state(tmp_path: Path) -> None:
    shm = _write_shm(tmp_path, {"a": {"density": 0.4}})
    temporal = tmp_path / "hapax-density-field" / "temporal-mode.json"
    with (
        patch("agents.density_field.DENSITY_FIELD_SHM", shm),
        patch("agents.density_field.TEMPORAL_STATE_PATH", temporal),
    ):
        dfc = DensityFieldCompute()
        dfc.tick()
    assert temporal.exists()
    data = json.loads(temporal.read_text(encoding="utf-8"))
    assert "mode" in data
    assert "aggregate_density" in data


def test_alarm_threshold_exported() -> None:
    assert isinstance(ALARM_THRESHOLD, float)
    assert 0.0 < ALARM_THRESHOLD <= 1.0


def test_read_temporal_mode_defaults_baseline(tmp_path: Path) -> None:
    temporal = tmp_path / "temporal-mode.json"
    with patch("agents.density_field.TEMPORAL_STATE_PATH", temporal):
        assert read_temporal_mode() == DensityTemporalMode.BASELINE


def test_read_temporal_mode_reads_written_state(tmp_path: Path) -> None:
    temporal = tmp_path / "temporal-mode.json"
    temporal.write_text(json.dumps({"mode": "alarm"}), encoding="utf-8")
    with patch("agents.density_field.TEMPORAL_STATE_PATH", temporal):
        assert read_temporal_mode() == DensityTemporalMode.ALARM
