"""Tests for logos.data.goals — goal collection and staleness."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

import shared.operator
from logos.data.goals import (
    _activity_hours,
    _is_stale,
    collect_goals,
)


@pytest.fixture(autouse=True)
def _clear_operator_cache():
    """Clear operator.json cache before each test."""
    shared.operator._operator_cache = None
    yield
    shared.operator._operator_cache = None


# ── _activity_hours tests ──────────────────────────────────────────────────


def test_activity_hours_none_returns_none():
    assert _activity_hours(None) is None


def test_activity_hours_empty_returns_none():
    assert _activity_hours("") is None


def test_activity_hours_recent():
    recent = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
    h = _activity_hours(recent)
    assert h is not None
    assert 2.5 < h < 3.5


def test_activity_hours_z_suffix():
    ts = (datetime.now(UTC) - timedelta(hours=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    h = _activity_hours(ts)
    assert h is not None
    assert 9.5 < h < 10.5


def test_activity_hours_invalid():
    assert _activity_hours("not-a-date") is None


# ── _is_stale tests ────────────────────────────────────────────────────────


def test_active_goal_no_activity_is_stale():
    assert _is_stale("active", None) is True


def test_planned_goal_no_activity_not_stale():
    assert _is_stale("planned", None) is False


def test_active_goal_recent_not_stale():
    # 1 day old — well within 7-day threshold
    assert _is_stale("active", 24.0) is False


def test_active_goal_old_is_stale():
    # 10 days — past 7-day threshold
    assert _is_stale("active", 10 * 24.0) is True


def test_ongoing_goal_recent_not_stale():
    # 10 days — within 30-day threshold
    assert _is_stale("ongoing", 10 * 24.0) is False


def test_ongoing_goal_old_is_stale():
    # 35 days — past 30-day threshold
    assert _is_stale("ongoing", 35 * 24.0) is True


# ── collect_goals tests ────────────────────────────────────────────────────


def _make_operator_data(primary=None, secondary=None):
    return {
        "goals": {
            "primary": primary or [],
            "secondary": secondary or [],
        },
    }


@patch("shared.operator._load_operator")
def test_collect_goals_basic(mock_load):
    recent = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    mock_load.return_value = _make_operator_data(
        primary=[
            {
                "id": "test-goal",
                "name": "Test Goal",
                "status": "active",
                "progress": "Making progress",
                "last_activity_at": recent,
            }
        ],
    )
    snap = collect_goals()
    assert len(snap.goals) == 1
    assert snap.goals[0].name == "Test Goal"
    assert snap.goals[0].category == "primary"
    assert snap.goals[0].stale is False
    assert snap.active_count == 1
    assert snap.stale_count == 0


@patch("shared.operator._load_operator")
def test_collect_goals_stale_primary(mock_load):
    old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    mock_load.return_value = _make_operator_data(
        primary=[
            {
                "id": "stale-goal",
                "name": "Stale Goal",
                "status": "active",
                "last_activity_at": old,
            }
        ],
    )
    snap = collect_goals()
    assert snap.stale_count == 1
    assert snap.primary_stale == ["Stale Goal"]
    assert snap.goals[0].stale is True


@patch("shared.operator._load_operator")
def test_collect_goals_null_activity(mock_load):
    mock_load.return_value = _make_operator_data(
        secondary=[
            {
                "id": "no-activity",
                "name": "No Activity",
                "status": "active",
                "last_activity_at": None,
            }
        ],
    )
    snap = collect_goals()
    assert snap.goals[0].stale is True
    assert snap.goals[0].last_activity_h is None


@patch("shared.operator._load_operator")
def test_collect_goals_empty(mock_load):
    mock_load.return_value = {"goals": {}}
    snap = collect_goals()
    assert snap.goals == []
    assert snap.active_count == 0


@patch("shared.operator._load_operator")
def test_collect_goals_mixed_categories(mock_load):
    recent = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    mock_load.return_value = _make_operator_data(
        primary=[
            {
                "id": "p1",
                "name": "Primary 1",
                "status": "active",
                "last_activity_at": recent,
            }
        ],
        secondary=[
            {
                "id": "s1",
                "name": "Secondary 1",
                "status": "planned",
                "last_activity_at": None,
            }
        ],
    )
    snap = collect_goals()
    assert len(snap.goals) == 2
    categories = [g.category for g in snap.goals]
    assert "primary" in categories
    assert "secondary" in categories


@patch("shared.operator._load_operator")
def test_collect_goals_exception_returns_empty(mock_load):
    mock_load.side_effect = RuntimeError("broken")
    snap = collect_goals()
    assert snap.goals == []
    assert snap.active_count == 0


@patch("shared.operator._load_operator")
def test_collect_goals_planned_not_stale(mock_load):
    mock_load.return_value = _make_operator_data(
        primary=[
            {
                "id": "planned",
                "name": "Planned Goal",
                "status": "planned",
                "last_activity_at": None,
            }
        ],
    )
    snap = collect_goals()
    assert snap.goals[0].stale is False
    assert snap.stale_count == 0
