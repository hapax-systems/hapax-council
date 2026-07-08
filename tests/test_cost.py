"""Tests for logos.data.cost — dataclasses and collector.

All I/O is mocked. No real HTTP requests.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from logos.data.cost import (
    CostSnapshot,
    LocalVolumeTrend,
    ModelCost,
    collect_cost,
    collect_local_volume_trend,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_obs_response(items: list[tuple[str, str, float]], total: int | None = None) -> dict:
    """Build a mock /observations response.

    Each tuple: (model, startTime, cost)
    """
    obs = []
    for model, start_time, cost in items:
        obs.append(
            {
                "model": model,
                "startTime": start_time,
                "calculatedTotalCost": cost,
            }
        )
    return {"data": obs, "meta": {"totalItems": total if total is not None else len(obs)}}


# ── Dataclass tests ──────────────────────────────────────────────────────────


def test_cost_snapshot_defaults():
    s = CostSnapshot()
    assert s.available is False
    assert s.today_cost == 0.0
    assert s.period_cost == 0.0
    assert s.daily_average == 0.0
    assert s.top_models == []


def test_model_cost_dataclass():
    m = ModelCost(model="claude-sonnet", cost=1.23)
    assert m.model == "claude-sonnet"
    assert m.cost == 1.23


def test_local_volume_trend_defaults():
    trend = LocalVolumeTrend()
    assert trend.available is False
    assert trend.alert_active is False


def test_collect_local_volume_trend_from_exporter(tmp_path):
    path = tmp_path / "hapax-local-capacity.json"
    path.write_text(
        json.dumps(
            {
                "timestamp": time.time(),
                "inflight": 8,
                "ceiling": 10,
                "ttft_ratio": 1.4,
            }
        ),
        encoding="utf-8",
    )
    result = collect_local_volume_trend(path=path)
    assert result.available is True
    assert result.pressure == pytest.approx(0.8)
    assert result.inflight == 8
    assert result.ceiling == 10
    assert result.alert_active is True


def test_collect_local_volume_trend_accepts_exporter_aliases(tmp_path):
    path = tmp_path / "hapax-local-capacity.json"
    path.write_text(
        json.dumps(
            {
                "ts": time.time(),
                "active_requests": 3,
                "max_concurrency": 12,
                "ttft_ewma_s": 3.0,
                "ttft_baseline_s": 1.0,
            }
        ),
        encoding="utf-8",
    )
    result = collect_local_volume_trend(path=path)
    assert result.available is True
    assert result.pressure == pytest.approx(1.0)
    assert result.inflight == 3
    assert result.ceiling == 12
    assert result.ttft_ratio == pytest.approx(3.0)
    assert result.alert_active is True


def test_collect_local_volume_trend_skips_invalid_alias_values(tmp_path):
    path = tmp_path / "hapax-local-capacity.json"
    path.write_text(
        json.dumps(
            {
                "timestamp": time.time(),
                "active_requests": "unknown",
                "active": 6,
                "max_concurrency": None,
                "concurrency_ceiling": 10,
            }
        ),
        encoding="utf-8",
    )
    result = collect_local_volume_trend(path=path)
    assert result.available is True
    assert result.pressure == pytest.approx(0.6)
    assert result.inflight == 6
    assert result.ceiling == 10


def test_collect_local_volume_trend_stale_fails_unavailable(tmp_path):
    path = tmp_path / "hapax-local-capacity.json"
    path.write_text(json.dumps({"timestamp": time.time() - 300, "inflight": 8, "ceiling": 10}))
    result = collect_local_volume_trend(path=path, max_age_s=120)
    assert result.available is False
    assert result.age_s > 120


# ── Collector tests ──────────────────────────────────────────────────────────


@patch("logos.data.cost.LANGFUSE_PK", "")
@patch("logos.data.cost.collect_local_volume_trend")
def test_collect_cost_no_credentials(mock_local):
    mock_local.return_value = LocalVolumeTrend(pressure=0.5, available=True)
    result = collect_cost()
    assert result.available is False
    assert result.local_capacity is not None
    assert result.local_capacity.available is True


@patch("logos.data.cost.LANGFUSE_PK", "pk-test")
@patch("logos.data.cost.langfuse_get")
def test_collect_cost_api_failure(mock_get):
    mock_get.return_value = {}
    result = collect_cost()
    assert result.available is False


@patch("logos.data.cost.LANGFUSE_PK", "pk-test")
@patch("logos.data.cost.langfuse_get")
def test_collect_cost_empty_window(mock_get):
    mock_get.return_value = {"data": [], "meta": {"totalItems": 0}}
    result = collect_cost()
    assert result.available is True
    assert result.today_cost == 0.0
    assert result.period_cost == 0.0
    assert result.daily_average == 0.0
    assert result.top_models == []


@patch("logos.data.cost.LANGFUSE_PK", "pk-test")
@patch("logos.data.cost.langfuse_get")
def test_collect_cost_single_day(mock_get):
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    mock_get.return_value = _make_obs_response(
        [
            ("claude-sonnet", f"{today}T10:00:00Z", 0.50),
            ("claude-sonnet", f"{today}T11:00:00Z", 0.30),
        ]
    )
    result = collect_cost()
    assert result.available is True
    assert result.today_cost == pytest.approx(0.80, abs=1e-6)
    assert result.period_cost == pytest.approx(0.80, abs=1e-6)
    assert result.daily_average == pytest.approx(0.80, abs=1e-6)


@patch("logos.data.cost.LANGFUSE_PK", "pk-test")
@patch("logos.data.cost.langfuse_get")
def test_collect_cost_multi_day(mock_get):
    now = datetime.now(UTC)
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    two_days_ago = (now - timedelta(days=2)).strftime("%Y-%m-%d")

    mock_get.return_value = _make_obs_response(
        [
            ("claude-sonnet", f"{today}T10:00:00Z", 1.00),
            ("claude-haiku", f"{yesterday}T10:00:00Z", 0.50),
            ("claude-sonnet", f"{two_days_ago}T10:00:00Z", 0.50),
        ]
    )
    result = collect_cost()
    assert result.available is True
    assert result.today_cost == pytest.approx(1.00, abs=1e-6)
    assert result.period_cost == pytest.approx(2.00, abs=1e-6)
    # 3 active days: 2.00 / 3 = 0.6667
    assert result.daily_average == pytest.approx(2.0 / 3, abs=1e-4)


@patch("logos.data.cost.LANGFUSE_PK", "pk-test")
@patch("logos.data.cost.langfuse_get")
def test_collect_cost_model_grouping(mock_get):
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    mock_get.return_value = _make_obs_response(
        [
            ("claude-sonnet", f"{today}T10:00:00Z", 0.80),
            ("claude-haiku", f"{today}T11:00:00Z", 0.10),
            ("claude-sonnet", f"{today}T12:00:00Z", 0.50),
        ]
    )
    result = collect_cost()
    assert len(result.top_models) == 2
    # Sorted descending by cost
    assert result.top_models[0].model == "claude-sonnet"
    assert result.top_models[0].cost == pytest.approx(1.30, abs=1e-6)
    assert result.top_models[1].model == "claude-haiku"
    assert result.top_models[1].cost == pytest.approx(0.10, abs=1e-6)


@patch("logos.data.cost.LANGFUSE_PK", "pk-test")
@patch("logos.data.cost.langfuse_get")
def test_collect_cost_skips_zero_cost(mock_get):
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    mock_get.return_value = _make_obs_response(
        [
            ("claude-sonnet", f"{today}T10:00:00Z", 0.50),
            ("qwen-7b", f"{today}T10:00:00Z", 0.0),
        ]
    )
    result = collect_cost()
    assert len(result.top_models) == 1
    assert result.top_models[0].model == "claude-sonnet"
    assert result.period_cost == pytest.approx(0.50, abs=1e-6)


@patch("logos.data.cost.LANGFUSE_PK", "pk-test")
@patch("logos.data.cost.langfuse_get")
def test_collect_cost_missing_start_time(mock_get):
    """Obs without startTime counted in total/model but not daily bucket."""
    mock_get.return_value = {
        "data": [
            {"model": "claude-sonnet", "startTime": "", "calculatedTotalCost": 0.40},
            {"model": "claude-sonnet", "calculatedTotalCost": 0.30},
        ],
        "meta": {"totalItems": 2},
    }
    result = collect_cost()
    assert result.period_cost == pytest.approx(0.70, abs=1e-6)
    assert result.today_cost == 0.0  # No daily bucket populated
    assert result.daily_average == 0.0  # No daily buckets at all
    assert result.top_models[0].cost == pytest.approx(0.70, abs=1e-6)


@patch("logos.data.cost.LANGFUSE_PK", "pk-test")
@patch("logos.data.cost.langfuse_get")
def test_collect_cost_pagination(mock_get):
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    page1 = _make_obs_response(
        [("claude-sonnet", f"{today}T10:00:00Z", 0.50)],
        total=101,  # Forces pagination (page*100 < total)
    )
    page2 = _make_obs_response(
        [("claude-haiku", f"{today}T11:00:00Z", 0.20)],
        total=101,
    )

    call_count = 0

    def side_effect(path, params, *, timeout=15):
        nonlocal call_count
        call_count += 1
        if params.get("page") == 1:
            return page1
        return page2

    mock_get.side_effect = side_effect
    result = collect_cost()
    assert result.available is True
    assert result.period_cost == pytest.approx(0.70, abs=1e-6)
    assert call_count == 2


@patch("logos.data.cost.LANGFUSE_PK", "pk-test")
@patch("logos.data.cost.langfuse_get")
def test_collect_cost_partial_failure(mock_get):
    """First page succeeds, second fails — partial data preserved."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    page1 = _make_obs_response(
        [("claude-sonnet", f"{today}T10:00:00Z", 0.50)],
        total=200,  # Indicates more pages
    )

    def side_effect(path, params, *, timeout=15):
        if params.get("page") == 1:
            return page1
        return {}  # Second page fails

    mock_get.side_effect = side_effect
    result = collect_cost()
    assert result.available is True
    assert result.period_cost == pytest.approx(0.50, abs=1e-6)
    assert result.today_cost == pytest.approx(0.50, abs=1e-6)
