"""Tests for shared.health_history."""
import json
from datetime import datetime, timedelta, timezone

from shared.health_history import (
    aggregate_hourly,
    aggregate_daily,
    rotate_with_rollup,
    get_recurring_issues,
    get_uptime_trend,
)


def _make_entry(hours_ago: int, status: str = "healthy", failed_checks: list[str] | None = None) -> dict:
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return {
        "timestamp": ts,
        "status": status,
        "healthy": 40 if status == "healthy" else 35,
        "failed": 0 if status == "healthy" else 5,
        "duration_ms": 1200,
        "failed_checks": failed_checks or [],
    }


def test_aggregate_hourly():
    entries = [
        _make_entry(2, "healthy"),
        _make_entry(2, "failed", ["docker.qdrant"]),
        _make_entry(1, "healthy"),
    ]
    rollups = aggregate_hourly(entries)
    assert len(rollups) >= 1
    # At least one rollup should have total_runs > 0
    assert any(r.total_runs > 0 for r in rollups)


def test_aggregate_daily():
    hourly = [
        {"hour": "2026-03-01T10", "total_runs": 4, "healthy_runs": 3,
         "degraded_runs": 0, "failed_runs": 1, "avg_duration_ms": 1000,
         "failed_checks": ["docker.qdrant"]},
        {"hour": "2026-03-01T11", "total_runs": 4, "healthy_runs": 4,
         "degraded_runs": 0, "failed_runs": 0, "avg_duration_ms": 900,
         "failed_checks": []},
    ]
    rollups = aggregate_daily(hourly)
    assert len(rollups) == 1
    assert rollups[0].date == "2026-03-01"
    assert rollups[0].total_runs == 8


def test_rotate_with_rollup(tmp_path):
    raw_path = tmp_path / "raw.jsonl"
    hourly_path = tmp_path / "hourly.jsonl"
    daily_path = tmp_path / "daily.jsonl"

    # Write some raw entries (mix of old and recent)
    entries = [_make_entry(1, "healthy"), _make_entry(200, "failed", ["docker.qdrant"])]
    raw_path.write_text("\n".join(json.dumps(e) for e in entries))

    result = rotate_with_rollup(
        raw_path=raw_path, hourly_path=hourly_path, daily_path=daily_path,
    )
    assert result["raw_kept"] >= 1  # recent entry kept
    assert hourly_path.exists()


def test_get_recurring_issues(tmp_path, monkeypatch):
    monkeypatch.setattr("shared.health_history.PROFILES_DIR", tmp_path)
    raw_path = tmp_path / "health-history.jsonl"
    entries = [_make_entry(i, "failed", ["docker.qdrant"]) for i in range(5)]
    raw_path.write_text("\n".join(json.dumps(e) for e in entries))
    issues = get_recurring_issues(days=7)
    assert len(issues) == 1
    assert issues[0][0] == "docker.qdrant"
    assert issues[0][1] == 5


def test_get_uptime_trend(tmp_path, monkeypatch):
    monkeypatch.setattr("shared.health_history.PROFILES_DIR", tmp_path)
    raw_path = tmp_path / "health-history.jsonl"
    entries = [_make_entry(i, "healthy" if i % 2 == 0 else "failed") for i in range(10)]
    raw_path.write_text("\n".join(json.dumps(e) for e in entries))
    trend = get_uptime_trend(days=7)
    assert len(trend) >= 1
    assert all(isinstance(pct, float) for _, pct in trend)
