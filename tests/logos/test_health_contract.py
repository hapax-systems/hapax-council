"""Contract tests for the logos health endpoint source state."""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from logos.data.health import HealthSnapshot, collect_health_history, collect_live_health


@pytest.mark.asyncio
async def test_collect_live_health_missing_history_is_source_degraded(tmp_path, monkeypatch):
    monkeypatch.setattr("logos.data.health.PROFILES_DIR", tmp_path)

    health = await collect_live_health()

    assert health.overall_status == "degraded"
    assert health.total_checks == 0
    assert health.failed == 0
    assert health.failed_checks == []
    assert health.source_status == "missing"
    assert health.summary == {"healthy": 0, "degraded": 0, "failed": 0, "total": 0}


@pytest.mark.asyncio
async def test_collect_live_health_reads_latest_history_entry(tmp_path, monkeypatch):
    monkeypatch.setattr("logos.data.health.PROFILES_DIR", tmp_path)
    history = tmp_path / "health-history.jsonl"
    history.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-06-11T09:00:00Z",
                        "status": "healthy",
                        "healthy": 12,
                        "degraded": 0,
                        "failed": 0,
                        "duration_ms": 100,
                        "failed_checks": [],
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-06-11T09:15:00Z",
                        "status": "degraded",
                        "healthy": 10,
                        "degraded": 2,
                        "failed": 1,
                        "duration_ms": 250,
                        "failed_checks": ["docker.qdrant"],
                    }
                ),
            ]
        )
        + "\n"
    )

    health = await collect_live_health()

    assert health.overall_status == "degraded"
    assert health.total_checks == 13
    assert health.healthy == 10
    assert health.degraded == 2
    assert health.failed == 1
    assert health.failed_checks == ["docker.qdrant"]
    assert health.source_status == "ok"
    assert health.summary["total"] == 13


@pytest.mark.asyncio
async def test_collect_live_health_invalid_latest_entry_is_source_degraded(tmp_path, monkeypatch):
    monkeypatch.setattr("logos.data.health.PROFILES_DIR", tmp_path)
    (tmp_path / "health-history.jsonl").write_text('{"status": "healthy"}\nnot-json\n')

    health = await collect_live_health()

    assert health.overall_status == "degraded"
    assert health.total_checks == 0
    assert health.failed_checks == []
    assert health.source_status == "invalid"


def test_collect_health_history_missing_path_reports_source_status(tmp_path, monkeypatch):
    monkeypatch.setattr("logos.data.health.PROFILES_DIR", tmp_path)

    history = collect_health_history()

    assert history.entries == []
    assert history.total_runs == 0
    assert history.uptime_pct == 0.0
    assert history.source_status == "missing"


def test_collect_health_history_empty_path_reports_source_status(tmp_path, monkeypatch):
    monkeypatch.setattr("logos.data.health.PROFILES_DIR", tmp_path)
    (tmp_path / "health-history.jsonl").write_text("")

    history = collect_health_history()

    assert history.entries == []
    assert history.total_runs == 0
    assert history.source_status == "empty"


def test_collect_health_history_reads_normal_entries(tmp_path, monkeypatch):
    monkeypatch.setattr("logos.data.health.PROFILES_DIR", tmp_path)
    (tmp_path / "health-history.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-06-11T09:00:00Z",
                        "status": "healthy",
                        "healthy": 12,
                        "degraded": 0,
                        "failed": 0,
                        "duration_ms": 100,
                        "failed_checks": [],
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-06-11T09:15:00Z",
                        "status": "failed",
                        "healthy": 10,
                        "degraded": 0,
                        "failed": 2,
                        "duration_ms": 200,
                        "failed_checks": ["docker.qdrant"],
                    }
                ),
            ]
        )
    )

    history = collect_health_history()

    assert history.total_runs == 2
    assert history.uptime_pct == 50.0
    assert history.source_status == "ok"
    assert history.entries[-1].failed_checks == ["docker.qdrant"]


@pytest.mark.asyncio
async def test_health_endpoint_exposes_snapshot_summary(monkeypatch):
    from logos.api.app import app
    from logos.api.cache import cache

    previous = cache.health
    cache.health = HealthSnapshot(
        overall_status="healthy",
        total_checks=2,
        healthy=2,
        degraded=0,
        failed=0,
        duration_ms=50,
    )
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health")
    finally:
        cache.health = previous

    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"] == {"healthy": 2, "degraded": 0, "failed": 0, "total": 2}
    assert data["source_status"] == "ok"
