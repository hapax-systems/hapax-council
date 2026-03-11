"""Tests for activity_analyzer — schemas, collectors, formatter.

All I/O is mocked. No real HTTP requests, filesystem access, or subprocess calls.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from agents.activity_analyzer import (
    ActivityReport,
    DriftTrend,
    HealthTrend,
    LangfuseActivity,
    ModelUsage,
    ServiceEvent,
    _manifest_age,
    collect_drift_trend,
    collect_health_trend,
    collect_langfuse,
    format_human,
)

# ── Schema tests ─────────────────────────────────────────────────────────────


def test_model_usage_defaults():
    m = ModelUsage(model_group="claude-haiku")
    assert m.call_count == 0
    assert m.total_cost == 0.0
    assert m.error_count == 0


def test_langfuse_activity_defaults():
    a = LangfuseActivity()
    assert a.total_traces == 0
    assert a.models == []


def test_health_trend_defaults():
    h = HealthTrend()
    assert h.uptime_pct == 0.0
    assert h.recurring_issues == []


def test_drift_trend_defaults():
    d = DriftTrend()
    assert d.reports_count == 0
    assert d.latest_summary == ""


def test_activity_report_json_round_trip():
    report = ActivityReport(
        window_start="2026-02-28T00:00:00",
        window_end="2026-02-28T12:00:00",
        hours=12,
    )
    data = json.loads(report.model_dump_json())
    assert data["hours"] == 12
    assert data["langfuse"]["total_traces"] == 0


# ── Langfuse collector tests ─────────────────────────────────────────────────


def _make_langfuse_traces(n: int) -> dict:
    """Build a mock /traces API response."""
    traces = [{"id": f"t{i}", "name": f"trace-{i}"} for i in range(n)]
    return {"data": traces, "meta": {"totalItems": n}}


def _make_langfuse_observations(models: list[tuple[str, int, int, float]]) -> dict:
    """Build a mock /observations API response.

    Each tuple: (model, input_tokens, output_tokens, cost)
    """
    obs = []
    for model, inp, out, cost in models:
        obs.append(
            {
                "model": model,
                "metadata": {"model_group": model},
                "usage": {"input": inp, "output": out},
                "calculatedTotalCost": cost,
                "latency": 150,
                "level": "DEFAULT",
            }
        )
    return {"data": obs, "meta": {"totalItems": len(obs)}}


@patch("agents.activity_analyzer.LANGFUSE_PK", "")
def test_collect_langfuse_no_credentials():
    since = datetime.now(UTC) - timedelta(hours=1)
    result = collect_langfuse(since)
    assert result.total_traces == 0


@patch("agents.activity_analyzer.LANGFUSE_PK", "pk-test")
@patch("agents.activity_analyzer._langfuse_api")
def test_collect_langfuse_with_traces(mock_api):
    traces_resp = _make_langfuse_traces(3)
    obs_resp = _make_langfuse_observations(
        [
            ("claude-haiku", 100, 50, 0.001),
            ("claude-haiku", 200, 100, 0.002),
            ("qwen-7b", 80, 20, 0.0),
        ]
    )

    def side_effect(path, params=None):
        if "/traces" in path:
            return traces_resp
        if "/observations" in path:
            return obs_resp
        return {}

    mock_api.side_effect = side_effect

    since = datetime.now(UTC) - timedelta(hours=1)
    result = collect_langfuse(since)

    assert result.total_traces == 3
    assert result.total_generations == 3
    assert len(result.models) == 2
    assert result.total_cost == pytest.approx(0.003, abs=1e-6)

    haiku = next(m for m in result.models if m.model_group == "claude-haiku")
    assert haiku.call_count == 2
    assert haiku.total_input_tokens == 300


@patch("agents.activity_analyzer.LANGFUSE_PK", "pk-test")
@patch("agents.activity_analyzer._langfuse_api")
def test_collect_langfuse_with_errors(mock_api):
    traces_resp = _make_langfuse_traces(1)
    obs_resp = {
        "data": [
            {
                "model": "gemini-flash",
                "metadata": {},
                "usage": {},
                "calculatedTotalCost": 0,
                "latency": 0,
                "level": "ERROR",
            }
        ],
        "meta": {"totalItems": 1},
    }

    mock_api.side_effect = lambda path, params=None: traces_resp if "/traces" in path else obs_resp

    since = datetime.now(UTC) - timedelta(hours=1)
    result = collect_langfuse(since)
    assert result.error_count == 1


@patch("agents.activity_analyzer.LANGFUSE_PK", "pk-test")
@patch("agents.activity_analyzer._langfuse_api")
def test_collect_langfuse_empty_response(mock_api):
    mock_api.return_value = {"data": [], "meta": {"totalItems": 0}}

    since = datetime.now(UTC) - timedelta(hours=1)
    result = collect_langfuse(since)
    assert result.total_traces == 0
    assert result.total_generations == 0


@patch("agents.activity_analyzer.LANGFUSE_PK", "pk-test")
@patch("agents.activity_analyzer._langfuse_api")
def test_collect_langfuse_unique_trace_names(mock_api):
    traces = {
        "data": [
            {"id": "t1", "name": "drift-detector"},
            {"id": "t2", "name": "profiler"},
            {"id": "t3", "name": "drift-detector"},
        ],
        "meta": {"totalItems": 3},
    }
    mock_api.side_effect = lambda path, params=None: (
        traces if "/traces" in path else {"data": [], "meta": {"totalItems": 0}}
    )

    since = datetime.now(UTC) - timedelta(hours=1)
    result = collect_langfuse(since)
    assert result.unique_trace_names == ["drift-detector", "profiler"]


# ── Health history collector tests ────────────────────────────────────────────


def test_collect_health_trend_no_file(tmp_path):
    with patch("agents.activity_analyzer.HEALTH_HISTORY", tmp_path / "nope.jsonl"):
        since = datetime.now(UTC) - timedelta(hours=24)
        result = collect_health_trend(since)
        assert result.total_runs == 0


def test_collect_health_trend_with_data(tmp_path):
    history_file = tmp_path / "health-history.jsonl"
    now = datetime.now(UTC)

    entries = [
        {
            "timestamp": (now - timedelta(hours=2)).isoformat(),
            "status": "healthy",
            "healthy": 40,
            "degraded": 0,
            "failed": 0,
            "duration_ms": 2000,
            "failed_checks": [],
        },
        {
            "timestamp": (now - timedelta(hours=1)).isoformat(),
            "status": "degraded",
            "healthy": 38,
            "degraded": 2,
            "failed": 0,
            "duration_ms": 2100,
            "failed_checks": ["docker.n8n", "docker.langfuse"],
        },
        {
            "timestamp": (now - timedelta(minutes=30)).isoformat(),
            "status": "healthy",
            "healthy": 40,
            "degraded": 0,
            "failed": 0,
            "duration_ms": 1900,
            "failed_checks": [],
        },
    ]
    history_file.write_text("\n".join(json.dumps(e) for e in entries))

    with patch("agents.activity_analyzer.HEALTH_HISTORY", history_file):
        since = now - timedelta(hours=3)
        result = collect_health_trend(since)

    assert result.total_runs == 3
    assert result.healthy_runs == 2
    assert result.degraded_runs == 1
    assert result.uptime_pct == pytest.approx(100.0, abs=0.1)  # healthy + degraded = available
    assert any("docker.n8n" in i for i in result.recurring_issues)


def test_collect_health_trend_filters_by_time(tmp_path):
    history_file = tmp_path / "health-history.jsonl"
    now = datetime.now(UTC)

    entries = [
        {
            "timestamp": (now - timedelta(hours=48)).isoformat(),
            "status": "failed",
            "healthy": 30,
            "degraded": 0,
            "failed": 10,
            "duration_ms": 3000,
            "failed_checks": ["x"],
        },
        {
            "timestamp": (now - timedelta(hours=1)).isoformat(),
            "status": "healthy",
            "healthy": 40,
            "degraded": 0,
            "failed": 0,
            "duration_ms": 2000,
            "failed_checks": [],
        },
    ]
    history_file.write_text("\n".join(json.dumps(e) for e in entries))

    with patch("agents.activity_analyzer.HEALTH_HISTORY", history_file):
        since = now - timedelta(hours=24)
        result = collect_health_trend(since)

    # Only the recent entry should be included
    assert result.total_runs == 1
    assert result.healthy_runs == 1
    assert result.failed_runs == 0


# ── Drift history collector tests ─────────────────────────────────────────────


def test_collect_drift_trend_no_files(tmp_path):
    with (
        patch("agents.activity_analyzer.DRIFT_REPORT", tmp_path / "nope.json"),
        patch("agents.activity_analyzer.DRIFT_HISTORY", tmp_path / "nope.jsonl"),
    ):
        since = datetime.now(UTC) - timedelta(hours=24)
        result = collect_drift_trend(since)
        assert result.reports_count == 0
        assert result.latest_drift_count == 0


def test_collect_drift_trend_with_report(tmp_path):
    report_file = tmp_path / "drift-report.json"
    history_file = tmp_path / "drift-history.jsonl"

    report_file.write_text(
        json.dumps(
            {
                "drift_items": [{"severity": "high"}, {"severity": "medium"}],
                "summary": "Two items of drift found",
            }
        )
    )
    history_file.write_text('{"ts":"2026-02-28","count":2}\n{"ts":"2026-02-27","count":3}\n')

    with (
        patch("agents.activity_analyzer.DRIFT_REPORT", report_file),
        patch("agents.activity_analyzer.DRIFT_HISTORY", history_file),
    ):
        since = datetime.now(UTC) - timedelta(hours=24)
        result = collect_drift_trend(since)

    assert result.latest_drift_count == 2
    assert result.reports_count == 2
    assert "Two items" in result.latest_summary


# ── Formatter tests ──────────────────────────────────────────────────────────


def test_format_human_empty_report():
    report = ActivityReport(
        window_start="2026-02-28T00:00:00",
        window_end="2026-02-28T12:00:00",
        hours=12,
    )
    output = format_human(report)
    assert "12h window" in output
    assert "No traces" in output
    assert "No history" in output


def test_format_human_with_langfuse_data():
    report = ActivityReport(
        window_start="2026-02-28T00:00:00",
        window_end="2026-02-28T12:00:00",
        hours=12,
        langfuse=LangfuseActivity(
            total_traces=10,
            total_generations=15,
            total_input_tokens=5000,
            total_output_tokens=2000,
            total_cost=0.05,
            models=[
                ModelUsage(
                    model_group="claude-haiku",
                    call_count=10,
                    total_input_tokens=3000,
                    total_output_tokens=1000,
                    total_cost=0.03,
                    avg_latency_ms=200,
                ),
                ModelUsage(
                    model_group="qwen-7b",
                    call_count=5,
                    total_input_tokens=2000,
                    total_output_tokens=1000,
                    total_cost=0.02,
                    avg_latency_ms=100,
                ),
            ],
        ),
    )
    output = format_human(report)
    assert "15 calls across 10 traces" in output
    assert "5,000 in" in output
    assert "$0.0500" in output
    assert "claude-haiku" in output


def test_format_human_with_health_data():
    report = ActivityReport(
        window_start="2026-02-28T00:00:00",
        window_end="2026-02-28T12:00:00",
        hours=12,
        health=HealthTrend(
            total_runs=10,
            healthy_runs=8,
            degraded_runs=2,
            uptime_pct=80.0,
            avg_duration_ms=2000,
            recurring_issues=["docker.n8n (2x)"],
        ),
    )
    output = format_human(report)
    assert "80.0% uptime" in output
    assert "docker.n8n" in output


def test_format_human_with_service_events():
    report = ActivityReport(
        window_start="2026-02-28T00:00:00",
        window_end="2026-02-28T12:00:00",
        hours=12,
        service_events=[
            ServiceEvent(
                unit="health-monitor.service", event="completed", timestamp="2026-02-28T06:00:00"
            ),
        ],
    )
    output = format_human(report)
    assert "Service Events (1)" in output
    assert "health-monitor" in output


def test_format_human_with_synthesis():
    report = ActivityReport(
        window_start="2026-02-28T00:00:00",
        window_end="2026-02-28T12:00:00",
        hours=12,
        synthesis="System is operating normally with low usage.",
    )
    output = format_human(report)
    assert "Summary: System is operating normally" in output


def test_format_human_with_errors():
    report = ActivityReport(
        window_start="2026-02-28T00:00:00",
        window_end="2026-02-28T12:00:00",
        hours=12,
        langfuse=LangfuseActivity(
            total_traces=5,
            total_generations=5,
            error_count=2,
            models=[ModelUsage(model_group="gemini-flash", call_count=5, error_count=2)],
        ),
    )
    output = format_human(report)
    assert "Errors: 2" in output
    assert "2 errors" in output


# ── _manifest_age tests ──────────────────────────────────────────────────────


class TestManifestAge:
    def test_reads_timestamp_key(self, tmp_path, monkeypatch):
        """Bug fix: manifest.json uses 'timestamp', not 'generated_at'."""
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps({"timestamp": "2026-03-01T12:00:00Z"}))
        monkeypatch.setattr("agents.activity_analyzer.PROFILES_DIR", tmp_path)
        assert _manifest_age() == "2026-03-01T12:00:00Z"

    def test_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("agents.activity_analyzer.PROFILES_DIR", tmp_path)
        assert _manifest_age() == ""

    def test_invalid_json(self, tmp_path, monkeypatch):
        manifest = tmp_path / "manifest.json"
        manifest.write_text("not json")
        monkeypatch.setattr("agents.activity_analyzer.PROFILES_DIR", tmp_path)
        assert _manifest_age() == ""
