"""Tests for cockpit.data.cost — dataclasses and collector.

All I/O is mocked. No real HTTP requests.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from cockpit.data.cost import CostSnapshot, ModelCost, collect_cost


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_obs_response(items: list[tuple[str, str, float]], total: int | None = None) -> dict:
    """Build a mock /observations response.

    Each tuple: (model, startTime, cost)
    """
    obs = []
    for model, start_time, cost in items:
        obs.append({
            "model": model,
            "startTime": start_time,
            "calculatedTotalCost": cost,
        })
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


# ── Collector tests ──────────────────────────────────────────────────────────


@patch("cockpit.data.cost.LANGFUSE_PK", "")
def test_collect_cost_no_credentials():
    result = collect_cost()
    assert result.available is False


@patch("cockpit.data.cost.LANGFUSE_PK", "pk-test")
@patch("cockpit.data.cost.langfuse_get")
def test_collect_cost_api_failure(mock_get):
    mock_get.return_value = {}
    result = collect_cost()
    assert result.available is False


@patch("cockpit.data.cost.LANGFUSE_PK", "pk-test")
@patch("cockpit.data.cost.langfuse_get")
def test_collect_cost_empty_window(mock_get):
    mock_get.return_value = {"data": [], "meta": {"totalItems": 0}}
    result = collect_cost()
    assert result.available is True
    assert result.today_cost == 0.0
    assert result.period_cost == 0.0
    assert result.daily_average == 0.0
    assert result.top_models == []


@patch("cockpit.data.cost.LANGFUSE_PK", "pk-test")
@patch("cockpit.data.cost.langfuse_get")
def test_collect_cost_single_day(mock_get):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    mock_get.return_value = _make_obs_response([
        ("claude-sonnet", f"{today}T10:00:00Z", 0.50),
        ("claude-sonnet", f"{today}T11:00:00Z", 0.30),
    ])
    result = collect_cost()
    assert result.available is True
    assert result.today_cost == pytest.approx(0.80, abs=1e-6)
    assert result.period_cost == pytest.approx(0.80, abs=1e-6)
    assert result.daily_average == pytest.approx(0.80, abs=1e-6)


@patch("cockpit.data.cost.LANGFUSE_PK", "pk-test")
@patch("cockpit.data.cost.langfuse_get")
def test_collect_cost_multi_day(mock_get):
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    two_days_ago = (now - timedelta(days=2)).strftime("%Y-%m-%d")

    mock_get.return_value = _make_obs_response([
        ("claude-sonnet", f"{today}T10:00:00Z", 1.00),
        ("claude-haiku", f"{yesterday}T10:00:00Z", 0.50),
        ("claude-sonnet", f"{two_days_ago}T10:00:00Z", 0.50),
    ])
    result = collect_cost()
    assert result.available is True
    assert result.today_cost == pytest.approx(1.00, abs=1e-6)
    assert result.period_cost == pytest.approx(2.00, abs=1e-6)
    # 3 active days: 2.00 / 3 = 0.6667
    assert result.daily_average == pytest.approx(2.0 / 3, abs=1e-4)


@patch("cockpit.data.cost.LANGFUSE_PK", "pk-test")
@patch("cockpit.data.cost.langfuse_get")
def test_collect_cost_model_grouping(mock_get):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    mock_get.return_value = _make_obs_response([
        ("claude-sonnet", f"{today}T10:00:00Z", 0.80),
        ("claude-haiku", f"{today}T11:00:00Z", 0.10),
        ("claude-sonnet", f"{today}T12:00:00Z", 0.50),
    ])
    result = collect_cost()
    assert len(result.top_models) == 2
    # Sorted descending by cost
    assert result.top_models[0].model == "claude-sonnet"
    assert result.top_models[0].cost == pytest.approx(1.30, abs=1e-6)
    assert result.top_models[1].model == "claude-haiku"
    assert result.top_models[1].cost == pytest.approx(0.10, abs=1e-6)


@patch("cockpit.data.cost.LANGFUSE_PK", "pk-test")
@patch("cockpit.data.cost.langfuse_get")
def test_collect_cost_skips_zero_cost(mock_get):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    mock_get.return_value = _make_obs_response([
        ("claude-sonnet", f"{today}T10:00:00Z", 0.50),
        ("qwen-7b", f"{today}T10:00:00Z", 0.0),
    ])
    result = collect_cost()
    assert len(result.top_models) == 1
    assert result.top_models[0].model == "claude-sonnet"
    assert result.period_cost == pytest.approx(0.50, abs=1e-6)


@patch("cockpit.data.cost.LANGFUSE_PK", "pk-test")
@patch("cockpit.data.cost.langfuse_get")
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


@patch("cockpit.data.cost.LANGFUSE_PK", "pk-test")
@patch("cockpit.data.cost.langfuse_get")
def test_collect_cost_pagination(mock_get):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

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


@patch("cockpit.data.cost.LANGFUSE_PK", "pk-test")
@patch("cockpit.data.cost.langfuse_get")
def test_collect_cost_partial_failure(mock_get):
    """First page succeeds, second fails — partial data preserved."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

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
