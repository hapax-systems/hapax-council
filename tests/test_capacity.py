"""Tests for shared.capacity."""
import json
from datetime import datetime, timedelta, timezone

from shared.capacity import (
    CapacitySnapshot,
    ExhaustionForecast,
    append_capacity_snapshot,
    forecast_exhaustion,
    _linear_regression,
)


def test_snapshot_roundtrip():
    s = CapacitySnapshot(
        timestamp="2026-03-03T12:00:00Z",
        disk_used_gb=200.0, disk_total_gb=500.0, disk_pct=40.0,
    )
    d = s.to_dict()
    s2 = CapacitySnapshot.from_dict(d)
    assert s2.disk_used_gb == 200.0
    assert s2.disk_total_gb == 500.0


def test_linear_regression():
    slope, intercept = _linear_regression([0, 1, 2, 3], [0, 2, 4, 6])
    assert abs(slope - 2.0) < 0.001
    assert abs(intercept) < 0.001


def test_append_and_forecast(tmp_path):
    path = tmp_path / "cap.jsonl"
    now = datetime.now(timezone.utc)
    # Create 6 entries with growing disk
    for i in range(6):
        ts = (now - timedelta(days=5 - i)).isoformat()
        snap = CapacitySnapshot(
            timestamp=ts,
            disk_used_gb=200.0 + i * 10, disk_total_gb=500.0,
            disk_pct=(200.0 + i * 10) / 500 * 100,
        )
        append_capacity_snapshot(snap, path=path)

    forecasts = forecast_exhaustion(path=path, min_points=5)
    assert len(forecasts) >= 1
    disk = [f for f in forecasts if f.resource == "disk"]
    assert len(disk) == 1
    assert disk[0].trend == "growing"
    assert disk[0].days_to_exhaustion is not None


def test_forecast_insufficient_data(tmp_path):
    path = tmp_path / "cap.jsonl"
    # Only 2 entries — below min_points
    for i in range(2):
        snap = CapacitySnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            disk_used_gb=200.0, disk_total_gb=500.0,
        )
        append_capacity_snapshot(snap, path=path)
    assert forecast_exhaustion(path=path, min_points=5) == []
