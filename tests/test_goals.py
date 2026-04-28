"""Tests for logos.data.goals — goal collection and staleness."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import yaml

from logos.data.goals import (
    _activity_hours,
    _is_stale,
    collect_goals,
)

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


def _write_vault_goal(tmp_path: Path, name: str, **overrides: object) -> Path:
    fm: dict[str, object] = {
        "type": "goal",
        "title": name.replace("-", " ").title(),
        "domain": "research",
        "status": "active",
        "priority": "P1",
        "started_at": "2026-01-15",
        "target_date": "2026-06-30",
        "sprint_measures": [],
        "depends_on": [],
        "tags": ["test"],
    }
    fm.update(overrides)
    content = f"---\n{yaml.dump(fm, default_flow_style=False)}---\n\n# {fm['title']}\n"
    path = tmp_path / f"{name}.md"
    path.write_text(content, encoding="utf-8")
    return path


# ── vault-native collect_goals tests ───────────────────────────────────────


def test_collect_goals_uses_vault_native_snapshot(tmp_path: Path) -> None:
    _write_vault_goal(
        tmp_path,
        "bayesian-validation",
        title="Bayesian Validation",
        priority="P0",
        sprint_measures=["m1"],
    )

    snap = collect_goals(
        vault_base=tmp_path,
        vault_name="Test",
        sprint_measure_statuses={"m1": "completed"},
    )

    assert snap.source == "vault"
    assert snap.source_model == "vault-native"
    assert snap.source_path == str(tmp_path)
    assert snap.total_count == 1
    assert snap.active_count == 1
    assert snap.stale_count == 0
    assert len(snap.goals) == 1
    assert list(snap) == snap.goals

    goal = snap.goals[0]
    assert goal.id == "bayesian-validation"
    assert goal.name == "Bayesian Validation"
    assert goal.title == "Bayesian Validation"
    assert goal.category == "primary"
    assert goal.domain == "research"
    assert goal.priority == "P0"
    assert goal.progress == 1.0
    assert goal.progress_summary == "100% sprint measures complete"
    assert goal.obsidian_uri == "obsidian://open?vault=Test&file=bayesian-validation"


def test_collect_goals_no_active_goals_returns_structured_snapshot(tmp_path: Path) -> None:
    _write_vault_goal(tmp_path, "planned-goal", status="planned")

    snap = collect_goals(vault_base=tmp_path, vault_name="Test")

    assert snap.goals == []
    assert snap.total_count == 1
    assert snap.active_count == 0
    assert snap.stale_count == 0
    assert snap.primary_stale == []
    assert snap.source == "vault"
    assert snap.source_model == "vault-native"
    assert snap.source_path == str(tmp_path)


def test_collect_goals_uses_vault_mtime_for_staleness(tmp_path: Path) -> None:
    path = _write_vault_goal(tmp_path, "old-goal", priority="P0")
    old_time = (datetime.now(UTC) - timedelta(days=30)).timestamp()
    os.utime(path, (old_time, old_time))

    snap = collect_goals(vault_base=tmp_path, vault_name="Test")

    assert snap.stale_count == 1
    assert snap.primary_stale == ["Old Goal"]
    assert snap.goals[0].stale is True
    assert snap.goals[0].last_activity_h is not None


@patch("logos.data.goals.collect_vault_goals")
def test_collect_goals_exception_returns_structured_empty(mock_collect) -> None:
    mock_collect.side_effect = RuntimeError("broken")

    snap = collect_goals()

    assert snap.goals == []
    assert snap.active_count == 0
    assert snap.source == "vault"
    assert snap.source_model == "vault-native"
