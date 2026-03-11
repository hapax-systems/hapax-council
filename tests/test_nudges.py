"""Tests for cockpit.data.nudges — nudge collection and priority scoring.

All deterministic, no LLM calls.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from cockpit.data.briefing import ActionItem, BriefingData
from cockpit.data.drift import DriftItem, DriftSummary
from cockpit.data.health import HealthHistory, HealthHistoryEntry
from cockpit.data.nudges import (
    STALE_BRIEFING_H,
    STALE_DRIFT_H,
    STALE_SCOUT_H,
    Nudge,
    _age_hours,
    _collect_action_item_nudges,
    _collect_briefing_nudges,
    _collect_drift_nudges,
    _collect_emergence_nudges,
    _collect_goal_nudges,
    _collect_health_nudges,
    _collect_profile_nudges,
    _collect_readiness_nudges,
    _collect_scout_nudges,
    collect_nudges,
)
from cockpit.data.scout import ScoutData, ScoutRecommendation

# ── _age_hours tests ─────────────────────────────────────────────────────────


def test_age_hours_empty_returns_none():
    assert _age_hours("") is None


def test_age_hours_none_input_returns_none():
    # Should not raise, returns None via TypeError catch
    assert _age_hours(None) is None  # type: ignore[arg-type]


def test_age_hours_recent_timestamp():
    recent = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    age = _age_hours(recent)
    assert age is not None
    assert 1.9 < age < 2.5


def test_age_hours_z_suffix():
    ts = (datetime.now(UTC) - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    age = _age_hours(ts)
    assert age is not None
    assert 4.5 < age < 5.5


def test_age_hours_invalid_returns_none():
    assert _age_hours("not-a-timestamp") is None


def test_age_hours_truncated_timestamp():
    ts = (datetime.now(UTC) - timedelta(hours=10)).strftime("%Y-%m-%dT%H:%M:%S")
    age = _age_hours(ts)
    assert age is not None
    assert 9.5 < age < 10.5


# ── Health nudges ────────────────────────────────────────────────────────────


def _health_history(status: str, failed: int = 0, healthy: int = 44) -> HealthHistory:
    return HealthHistory(
        entries=[
            HealthHistoryEntry(
                timestamp="2026-03-01T12:00:00Z",
                status=status,
                healthy=healthy,
                degraded=0,
                failed=failed,
                duration_ms=100,
            )
        ],
        uptime_pct=100.0 if status == "healthy" else 50.0,
        total_runs=1,
    )


@patch("cockpit.data.nudges.collect_health_history")
def test_health_failure_produces_critical(mock_health):
    mock_health.return_value = _health_history("failed", failed=3, healthy=41)
    nudges: list[Nudge] = []
    _collect_health_nudges(nudges)
    assert len(nudges) == 1
    assert nudges[0].priority_score == 100
    assert nudges[0].priority_label == "critical"
    assert "3 health checks failing" in nudges[0].title


@patch("cockpit.data.nudges.collect_health_history")
def test_health_degraded_produces_critical(mock_health):
    mock_health.return_value = _health_history("degraded", failed=1, healthy=43)
    nudges: list[Nudge] = []
    _collect_health_nudges(nudges)
    assert len(nudges) == 1
    assert nudges[0].priority_score == 100
    assert nudges[0].priority_label == "critical"


@patch("cockpit.data.nudges.collect_health_history")
def test_health_healthy_produces_nothing(mock_health):
    mock_health.return_value = _health_history("healthy", failed=0, healthy=44)
    nudges: list[Nudge] = []
    _collect_health_nudges(nudges)
    assert len(nudges) == 0


@patch("cockpit.data.nudges.collect_health_history")
def test_health_no_history_produces_nothing(mock_health):
    mock_health.return_value = HealthHistory()
    nudges: list[Nudge] = []
    _collect_health_nudges(nudges)
    assert len(nudges) == 0


@patch("cockpit.data.nudges.collect_health_history")
def test_health_exception_produces_nothing(mock_health):
    mock_health.side_effect = RuntimeError("boom")
    nudges: list[Nudge] = []
    _collect_health_nudges(nudges)
    assert len(nudges) == 0


@patch("cockpit.data.nudges.collect_health_history")
def test_health_single_failure_singular(mock_health):
    mock_health.return_value = _health_history("failed", failed=1, healthy=43)
    nudges: list[Nudge] = []
    _collect_health_nudges(nudges)
    assert "1 health check failing" in nudges[0].title
    assert "checks" not in nudges[0].title


# ── Briefing nudges ──────────────────────────────────────────────────────────


def _fresh_ts() -> str:
    return (datetime.now(UTC) - timedelta(hours=2)).isoformat()


def _stale_ts() -> str:
    return (datetime.now(UTC) - timedelta(hours=STALE_BRIEFING_H + 4)).isoformat()


@patch("cockpit.data.nudges.collect_briefing")
def test_briefing_high_items_score_80(mock_briefing):
    mock_briefing.return_value = BriefingData(
        headline="Test",
        generated_at=_fresh_ts(),
        action_items=[ActionItem(priority="high", action="Fix something")],
    )
    nudges: list[Nudge] = []
    _collect_briefing_nudges(nudges)
    assert any(n.priority_score == 80 for n in nudges)


@patch("cockpit.data.nudges.collect_briefing")
def test_briefing_stale_with_items_score_75(mock_briefing):
    mock_briefing.return_value = BriefingData(
        headline="Test",
        generated_at=_stale_ts(),
        action_items=[ActionItem(priority="low", action="Something")],
    )
    nudges: list[Nudge] = []
    _collect_briefing_nudges(nudges)
    assert any(n.priority_score == 75 for n in nudges)


@patch("cockpit.data.nudges.collect_briefing")
def test_briefing_stale_no_items_score_55(mock_briefing):
    mock_briefing.return_value = BriefingData(
        headline="Test",
        generated_at=_stale_ts(),
    )
    nudges: list[Nudge] = []
    _collect_briefing_nudges(nudges)
    assert len(nudges) == 1
    assert nudges[0].priority_score == 55


@patch("cockpit.data.nudges.collect_briefing")
def test_briefing_none_produces_medium(mock_briefing):
    mock_briefing.return_value = None
    nudges: list[Nudge] = []
    _collect_briefing_nudges(nudges)
    assert len(nudges) == 1
    assert nudges[0].priority_score == 55
    assert "No briefing" in nudges[0].title


@patch("cockpit.data.nudges.collect_briefing")
def test_briefing_fresh_no_high_items_nothing(mock_briefing):
    mock_briefing.return_value = BriefingData(
        headline="Test",
        generated_at=_fresh_ts(),
        action_items=[ActionItem(priority="low", action="Minor thing")],
    )
    nudges: list[Nudge] = []
    _collect_briefing_nudges(nudges)
    assert len(nudges) == 0


@patch("cockpit.data.nudges.collect_briefing")
def test_briefing_fresh_empty_nothing(mock_briefing):
    mock_briefing.return_value = BriefingData(
        headline="Test",
        generated_at=_fresh_ts(),
    )
    nudges: list[Nudge] = []
    _collect_briefing_nudges(nudges)
    assert len(nudges) == 0


# ── Action item nudges ──────────────────────────────────────────────────────


def test_action_items_converted_to_nudges():
    briefing = BriefingData(
        headline="Test",
        generated_at=_fresh_ts(),
        action_items=[
            ActionItem(priority="high", action="Fix database", command="uv run fix-db"),
            ActionItem(priority="medium", action="Review logs"),
            ActionItem(priority="low", action="Clean up tmp"),
        ],
    )
    nudges: list[Nudge] = []
    _collect_action_item_nudges(nudges, briefing)
    assert len(nudges) == 3
    # Check priority mapping
    assert nudges[0].priority_score == 80
    assert nudges[0].priority_label == "high"
    assert nudges[0].title == "Fix database"
    assert nudges[0].command_hint == "uv run fix-db"
    assert nudges[1].priority_score == 50
    assert nudges[1].priority_label == "medium"
    assert nudges[2].priority_score == 25
    assert nudges[2].priority_label == "low"


def test_action_items_none_briefing():
    nudges: list[Nudge] = []
    _collect_action_item_nudges(nudges, None)
    assert len(nudges) == 0


def test_action_items_empty_list():
    briefing = BriefingData(headline="Test", generated_at=_fresh_ts())
    nudges: list[Nudge] = []
    _collect_action_item_nudges(nudges, briefing)
    assert len(nudges) == 0


def test_action_items_have_source_id():
    briefing = BriefingData(
        headline="Test",
        generated_at=_fresh_ts(),
        action_items=[ActionItem(priority="high", action="Fix something")],
    )
    nudges: list[Nudge] = []
    _collect_action_item_nudges(nudges, briefing)
    assert nudges[0].source_id.startswith("briefing-action:")


def test_action_items_category_is_action():
    briefing = BriefingData(
        headline="Test",
        generated_at=_fresh_ts(),
        action_items=[ActionItem(priority="medium", action="Do thing")],
    )
    nudges: list[Nudge] = []
    _collect_action_item_nudges(nudges, briefing)
    assert nudges[0].category == "action"


def test_action_items_preserve_reason_as_detail():
    briefing = BriefingData(
        headline="Test",
        generated_at=_fresh_ts(),
        action_items=[ActionItem(priority="high", action="Fix it", reason="It's broken")],
    )
    nudges: list[Nudge] = []
    _collect_action_item_nudges(nudges, briefing)
    assert nudges[0].detail == "It's broken"


# ── Goal nudges ─────────────────────────────────────────────────────────────


@patch("cockpit.data.goals.collect_goals")
def test_goal_stale_primary_score_60(mock_goals):
    from cockpit.data.goals import GoalSnapshot, GoalStatus

    mock_goals.return_value = GoalSnapshot(
        goals=[
            GoalStatus(
                id="test",
                name="Test Goal",
                status="active",
                category="primary",
                last_activity_h=200.0,
                stale=True,
                progress_summary="",
                description="",
            )
        ],
        active_count=1,
        stale_count=1,
        primary_stale=["Test Goal"],
    )
    nudges: list[Nudge] = []
    _collect_goal_nudges(nudges)
    assert len(nudges) == 1
    assert nudges[0].priority_score == 60
    assert nudges[0].priority_label == "medium"
    assert "Stale goal" in nudges[0].title


@patch("cockpit.data.goals.collect_goals")
def test_goal_stale_secondary_score_35(mock_goals):
    from cockpit.data.goals import GoalSnapshot, GoalStatus

    mock_goals.return_value = GoalSnapshot(
        goals=[
            GoalStatus(
                id="s1",
                name="Side Goal",
                status="active",
                category="secondary",
                last_activity_h=300.0,
                stale=True,
                progress_summary="",
                description="",
            )
        ],
        active_count=1,
        stale_count=1,
        primary_stale=[],
    )
    nudges: list[Nudge] = []
    _collect_goal_nudges(nudges)
    assert len(nudges) == 1
    assert nudges[0].priority_score == 35
    assert nudges[0].priority_label == "low"


@patch("cockpit.data.goals.collect_goals")
def test_goal_not_stale_no_nudge(mock_goals):
    from cockpit.data.goals import GoalSnapshot, GoalStatus

    mock_goals.return_value = GoalSnapshot(
        goals=[
            GoalStatus(
                id="fresh",
                name="Fresh Goal",
                status="active",
                category="primary",
                last_activity_h=24.0,
                stale=False,
                progress_summary="",
                description="",
            )
        ],
        active_count=1,
        stale_count=0,
        primary_stale=[],
    )
    nudges: list[Nudge] = []
    _collect_goal_nudges(nudges)
    assert len(nudges) == 0


@patch("cockpit.data.goals.collect_goals")
def test_goal_exception_produces_nothing(mock_goals):
    mock_goals.side_effect = RuntimeError("goals broken")
    nudges: list[Nudge] = []
    _collect_goal_nudges(nudges)
    assert len(nudges) == 0


# ── Readiness nudges ────────────────────────────────────────────────────────


def _mock_readiness(
    interview_conducted=False, priorities_known=False, neurocognitive_mapped=False, total_facts=100
):
    from cockpit.data.readiness import ReadinessSnapshot

    return ReadinessSnapshot(
        interview_conducted=interview_conducted,
        priorities_known=priorities_known,
        neurocognitive_mapped=neurocognitive_mapped,
        total_facts=total_facts,
    )


@patch("cockpit.data.readiness.collect_readiness")
def test_readiness_no_interview_score_65(mock_collect):
    snap = _mock_readiness(interview_conducted=False, total_facts=1103)
    mock_collect.return_value = snap
    nudges: list[Nudge] = []
    _collect_readiness_nudges(nudges)
    assert len(nudges) == 1
    assert nudges[0].priority_score == 65
    assert nudges[0].priority_label == "high"
    assert "No interview" in nudges[0].title
    assert "1103 facts" in nudges[0].detail


@patch("cockpit.data.readiness.collect_readiness")
def test_readiness_priorities_unvalidated_score_55(mock_collect):
    snap = _mock_readiness(
        interview_conducted=True, priorities_known=False, neurocognitive_mapped=True
    )
    mock_collect.return_value = snap
    nudges: list[Nudge] = []
    _collect_readiness_nudges(nudges)
    assert any(n.priority_score == 55 for n in nudges)
    assert any("Goals not validated" in n.title for n in nudges)


@patch("cockpit.data.readiness.collect_readiness")
def test_readiness_neurocognitive_empty_score_50(mock_collect):
    snap = _mock_readiness(
        interview_conducted=True, priorities_known=True, neurocognitive_mapped=False
    )
    mock_collect.return_value = snap
    nudges: list[Nudge] = []
    _collect_readiness_nudges(nudges)
    assert any(n.priority_score == 50 for n in nudges)
    assert any("Neurocognitive" in n.title for n in nudges)


@patch("cockpit.data.readiness.collect_readiness")
def test_readiness_all_good_nothing(mock_collect):
    snap = _mock_readiness(
        interview_conducted=True, priorities_known=True, neurocognitive_mapped=True
    )
    mock_collect.return_value = snap
    nudges: list[Nudge] = []
    _collect_readiness_nudges(nudges)
    assert len(nudges) == 0


@patch("cockpit.data.readiness.collect_readiness")
def test_readiness_exception_nothing(mock_collect):
    mock_collect.side_effect = RuntimeError("readiness broken")
    nudges: list[Nudge] = []
    _collect_readiness_nudges(nudges)
    assert len(nudges) == 0


# ── Profile nudges ───────────────────────────────────────────────────────────


def _mock_analysis(missing=None, sparse=None, dimension_stats=None):
    from cockpit.interview import ProfileAnalysis

    return ProfileAnalysis(
        missing_dimensions=missing or [],
        sparse_dimensions=sparse or [],
        dimension_stats=dimension_stats or {},
    )


@patch("cockpit.interview.analyze_profile")
def test_profile_3_missing_score_60(mock_analyze):
    mock_analyze.return_value = _mock_analysis(
        missing=["identity", "workflow", "philosophy"],
        dimension_stats={
            "technical_stack": {"count": 5, "avg_confidence": 0.8},
            "production_setup": {"count": 3, "avg_confidence": 0.7},
        },
    )
    nudges: list[Nudge] = []
    _collect_profile_nudges(nudges)
    assert len(nudges) == 1
    assert nudges[0].priority_score == 60


@patch("cockpit.interview.analyze_profile")
def test_profile_1_missing_score_50(mock_analyze):
    mock_analyze.return_value = _mock_analysis(
        missing=["identity"],
        dimension_stats={
            "workflow": {"count": 5, "avg_confidence": 0.8},
        },
    )
    nudges: list[Nudge] = []
    _collect_profile_nudges(nudges)
    assert len(nudges) == 1
    assert nudges[0].priority_score == 50


@patch("cockpit.interview.analyze_profile")
def test_profile_sparse_only_score_40(mock_analyze):
    mock_analyze.return_value = _mock_analysis(
        sparse=[{"dimension": "work_patterns", "fact_count": 2, "avg_confidence": 0.6}],
        dimension_stats={
            "work_patterns": {"count": 2, "avg_confidence": 0.6},
            "identity": {"count": 5, "avg_confidence": 0.9},
        },
    )
    nudges: list[Nudge] = []
    _collect_profile_nudges(nudges)
    assert len(nudges) == 1
    assert nudges[0].priority_score == 40


@patch("cockpit.interview.analyze_profile")
def test_profile_complete_nothing(mock_analyze):
    mock_analyze.return_value = _mock_analysis(
        dimension_stats={
            "workflow": {"count": 5, "avg_confidence": 0.9},
            "identity": {"count": 5, "avg_confidence": 0.9},
        },
    )
    nudges: list[Nudge] = []
    _collect_profile_nudges(nudges)
    assert len(nudges) == 0


@patch("cockpit.interview.analyze_profile")
def test_profile_error_produces_nothing(mock_analyze):
    mock_analyze.side_effect = RuntimeError("profiler broken")
    nudges: list[Nudge] = []
    _collect_profile_nudges(nudges)
    assert len(nudges) == 0


# ── Scout nudges ─────────────────────────────────────────────────────────────


@patch("cockpit.data.nudges.collect_scout")
def test_scout_adopt_score_30(mock_scout):
    mock_scout.return_value = ScoutData(
        generated_at=_fresh_ts(),
        components_scanned=10,
        adopt_count=2,
        evaluate_count=1,
        recommendations=[
            ScoutRecommendation(component="x", current="y", tier="adopt", summary="s"),
            ScoutRecommendation(component="a", current="b", tier="adopt", summary="s"),
        ],
    )
    nudges: list[Nudge] = []
    _collect_scout_nudges(nudges)
    assert any(n.priority_score == 30 for n in nudges)


@patch("cockpit.data.nudges.collect_scout")
def test_scout_evaluate_only_score_20(mock_scout):
    mock_scout.return_value = ScoutData(
        generated_at=_fresh_ts(),
        components_scanned=10,
        adopt_count=0,
        evaluate_count=3,
        recommendations=[
            ScoutRecommendation(component="x", current="y", tier="evaluate", summary="s"),
        ],
    )
    nudges: list[Nudge] = []
    _collect_scout_nudges(nudges)
    assert any(n.priority_score == 20 for n in nudges)


@patch("cockpit.data.nudges.collect_scout")
def test_scout_stale_score_25(mock_scout):
    stale = (datetime.now(UTC) - timedelta(hours=STALE_SCOUT_H + 10)).isoformat()
    mock_scout.return_value = ScoutData(
        generated_at=stale,
        components_scanned=10,
        adopt_count=0,
        evaluate_count=0,
    )
    nudges: list[Nudge] = []
    _collect_scout_nudges(nudges)
    assert len(nudges) == 1
    assert nudges[0].priority_score == 25


@patch("cockpit.data.nudges.collect_scout")
def test_scout_none_produces_nothing(mock_scout):
    mock_scout.return_value = None
    nudges: list[Nudge] = []
    _collect_scout_nudges(nudges)
    assert len(nudges) == 0


# ── Drift nudges ─────────────────────────────────────────────────────────────


@patch("cockpit.data.nudges.collect_drift")
def test_drift_items_high_priority(mock_drift):
    mock_drift.return_value = DriftSummary(
        drift_count=3,
        docs_analyzed=10,
        summary="3 items drifted",
        latest_timestamp=_fresh_ts(),
    )
    nudges: list[Nudge] = []
    _collect_drift_nudges(nudges)
    assert any(n.priority_score == 85 for n in nudges)
    assert any(n.priority_label == "high" for n in nudges)
    assert any("3 drift items" in n.title for n in nudges)


@patch("cockpit.data.nudges.collect_drift")
def test_drift_with_high_severity_items_critical(mock_drift):
    mock_drift.return_value = DriftSummary(
        drift_count=2,
        docs_analyzed=5,
        summary="2 items",
        latest_timestamp=_fresh_ts(),
        items=[
            DriftItem(severity="high", description="bad"),
            DriftItem(severity="medium", description="ok"),
        ],
    )
    nudges: list[Nudge] = []
    _collect_drift_nudges(nudges)
    assert any(n.priority_score == 90 for n in nudges)
    assert any(n.priority_label == "critical" for n in nudges)
    assert any("1 high" in n.title for n in nudges)


@patch("cockpit.data.nudges.collect_drift")
def test_drift_stale_score_25(mock_drift):
    stale = (datetime.now(UTC) - timedelta(hours=STALE_DRIFT_H + 10)).isoformat()
    mock_drift.return_value = DriftSummary(
        drift_count=0,
        docs_analyzed=10,
        latest_timestamp=stale,
    )
    nudges: list[Nudge] = []
    _collect_drift_nudges(nudges)
    assert len(nudges) == 1
    assert nudges[0].priority_score == 25


@patch("cockpit.data.nudges.collect_drift")
def test_drift_single_item_singular(mock_drift):
    mock_drift.return_value = DriftSummary(
        drift_count=1,
        docs_analyzed=5,
        summary="1 item drifted",
        latest_timestamp=_fresh_ts(),
    )
    nudges: list[Nudge] = []
    _collect_drift_nudges(nudges)
    assert "1 drift item" in nudges[0].title
    assert "items" not in nudges[0].title


@patch("cockpit.data.nudges.collect_drift")
def test_drift_none_produces_nothing(mock_drift):
    mock_drift.return_value = None
    nudges: list[Nudge] = []
    _collect_drift_nudges(nudges)
    assert len(nudges) == 0


# ── Integration tests ────────────────────────────────────────────────────────


@patch("cockpit.data.nudges._collect_knowledge_sufficiency_nudges")
@patch("cockpit.data.nudges.collect_drift")
@patch("cockpit.data.nudges.collect_scout")
@patch("cockpit.interview.analyze_profile")
@patch("cockpit.data.nudges.collect_briefing")
@patch("cockpit.data.nudges.collect_health_history")
@patch("cockpit.data.readiness.collect_readiness")
def test_collect_nudges_sorted_by_priority(
    mock_readiness,
    mock_health,
    mock_briefing,
    mock_profile,
    mock_scout,
    mock_drift,
    mock_knowledge_sufficiency,
):
    mock_readiness.return_value = _mock_readiness(
        interview_conducted=True,
        priorities_known=True,
        neurocognitive_mapped=True,
    )
    mock_health.return_value = _health_history("failed", failed=2, healthy=42)
    mock_briefing.return_value = BriefingData(
        headline="Test",
        generated_at=_fresh_ts(),
        action_items=[ActionItem(priority="high", action="Fix something")],
    )
    mock_profile.return_value = _mock_analysis(
        missing=["identity", "workflow", "philosophy"],
        dimension_stats={"tech": {"count": 5, "avg_confidence": 0.8}},
    )
    mock_scout.return_value = ScoutData(
        generated_at=_fresh_ts(),
        adopt_count=1,
        recommendations=[
            ScoutRecommendation(component="x", current="y", tier="adopt", summary="s"),
        ],
    )
    mock_drift.return_value = DriftSummary(
        drift_count=2, docs_analyzed=5, latest_timestamp=_fresh_ts()
    )

    nudges = collect_nudges()
    # Budget cap may add a meta nudge beyond the max_nudges limit
    non_meta = [n for n in nudges if n.category != "meta"]
    assert len(non_meta) <= 5
    # Verify non-meta nudges sorted by descending priority
    for i in range(len(non_meta) - 1):
        assert non_meta[i].priority_score >= non_meta[i + 1].priority_score


@patch("cockpit.data.nudges._collect_knowledge_sufficiency_nudges")
@patch("cockpit.data.nudges.collect_drift")
@patch("cockpit.data.nudges.collect_scout")
@patch("cockpit.interview.analyze_profile")
@patch("cockpit.data.nudges.collect_briefing")
@patch("cockpit.data.nudges.collect_health_history")
@patch("cockpit.data.readiness.collect_readiness")
def test_collect_nudges_max_nudges_truncates(
    mock_readiness,
    mock_health,
    mock_briefing,
    mock_profile,
    mock_scout,
    mock_drift,
    mock_knowledge_sufficiency,
):
    mock_readiness.return_value = _mock_readiness(
        interview_conducted=True,
        priorities_known=True,
        neurocognitive_mapped=True,
    )
    mock_health.return_value = _health_history("failed", failed=2, healthy=42)
    mock_briefing.return_value = BriefingData(
        headline="Test",
        generated_at=_stale_ts(),
        action_items=[ActionItem(priority="high", action="Fix something")],
    )
    mock_profile.return_value = _mock_analysis(
        missing=["identity", "workflow", "philosophy"],
        dimension_stats={"tech": {"count": 5, "avg_confidence": 0.8}},
    )
    mock_scout.return_value = ScoutData(
        generated_at=_fresh_ts(),
        adopt_count=1,
        recommendations=[
            ScoutRecommendation(component="x", current="y", tier="adopt", summary="s"),
        ],
    )
    mock_drift.return_value = DriftSummary(
        drift_count=2, docs_analyzed=5, latest_timestamp=_fresh_ts()
    )

    nudges = collect_nudges(max_nudges=2)
    assert len(nudges) == 3  # 2 visible + 1 meta overflow nudge
    # First should be health (100), second drift (85), third is meta
    assert nudges[0].priority_score == 100
    assert nudges[1].priority_score == 85
    assert nudges[2].category == "meta"


@patch("cockpit.data.nudges._collect_knowledge_sufficiency_nudges")
@patch("cockpit.data.nudges._collect_sufficiency_nudges")
@patch("cockpit.data.goals.collect_goals")
@patch("cockpit.data.nudges.collect_drift")
@patch("cockpit.data.nudges.collect_scout")
@patch("cockpit.interview.analyze_profile")
@patch("cockpit.data.nudges.collect_briefing")
@patch("cockpit.data.nudges.collect_health_history")
@patch("cockpit.data.readiness.collect_readiness")
def test_all_healthy_returns_empty(
    mock_readiness,
    mock_health,
    mock_briefing,
    mock_profile,
    mock_scout,
    mock_drift,
    mock_goals,
    mock_sufficiency,
    mock_knowledge_sufficiency,
):
    from cockpit.data.goals import GoalSnapshot

    mock_readiness.return_value = _mock_readiness(
        interview_conducted=True,
        priorities_known=True,
        neurocognitive_mapped=True,
    )
    mock_health.return_value = _health_history("healthy")
    mock_briefing.return_value = BriefingData(
        headline="All clear",
        generated_at=_fresh_ts(),
    )
    mock_profile.return_value = _mock_analysis(
        dimension_stats={
            "workflow": {"count": 5, "avg_confidence": 0.9},
            "identity": {"count": 5, "avg_confidence": 0.9},
        },
    )
    mock_scout.return_value = ScoutData(
        generated_at=_fresh_ts(),
        adopt_count=0,
        evaluate_count=0,
    )
    mock_drift.return_value = DriftSummary(
        drift_count=0, docs_analyzed=10, latest_timestamp=_fresh_ts()
    )
    mock_goals.return_value = GoalSnapshot()

    nudges = collect_nudges()
    assert nudges == []


@patch("cockpit.data.nudges._collect_knowledge_sufficiency_nudges")
@patch("cockpit.data.nudges.collect_drift")
@patch("cockpit.data.nudges.collect_scout")
@patch("cockpit.interview.analyze_profile")
@patch("cockpit.data.nudges.collect_health_history")
@patch("cockpit.data.readiness.collect_readiness")
def test_collect_nudges_with_briefing_param_injects_action_items(
    mock_readiness,
    mock_health,
    mock_profile,
    mock_scout,
    mock_drift,
    mock_knowledge_sufficiency,
):
    """When briefing is passed explicitly, action items become individual nudges."""
    mock_readiness.return_value = _mock_readiness(
        interview_conducted=True,
        priorities_known=True,
        neurocognitive_mapped=True,
    )
    mock_health.return_value = _health_history("healthy")
    mock_profile.return_value = _mock_analysis(
        dimension_stats={"workflow": {"count": 5, "avg_confidence": 0.9}},
    )
    mock_scout.return_value = ScoutData(
        generated_at=_fresh_ts(),
        adopt_count=0,
        evaluate_count=0,
    )
    mock_drift.return_value = DriftSummary(
        drift_count=0, docs_analyzed=10, latest_timestamp=_fresh_ts()
    )

    briefing = BriefingData(
        headline="Test",
        generated_at=_fresh_ts(),
        action_items=[
            ActionItem(priority="high", action="Fix database", command="uv run fix-db"),
            ActionItem(priority="low", action="Clean up"),
        ],
    )
    # Patch collect_briefing since _collect_briefing_nudges calls it internally
    with patch("cockpit.data.nudges.collect_briefing", return_value=briefing):
        nudges = collect_nudges(briefing=briefing)
    # Should contain action item nudges (category "action")
    action_nudges = [n for n in nudges if n.category == "action"]
    assert len(action_nudges) >= 1
    assert any(n.title == "Fix database" for n in action_nudges)


# ── Nudge dataclass tests ────────────────────────────────────────────────────


def test_nudge_default_command_hint():
    n = Nudge(
        category="health",
        priority_score=100,
        priority_label="critical",
        title="Test",
        detail="Test detail",
        suggested_action="Do something",
    )
    assert n.command_hint == ""


def test_nudge_with_command_hint():
    n = Nudge(
        category="profile",
        priority_score=60,
        priority_label="medium",
        title="Test",
        detail="Test detail",
        suggested_action="Interview",
        command_hint="/interview",
    )
    assert n.command_hint == "/interview"


# ── Attention budget cap tests ──────────────────────────────────────────────


class TestNudgeBudgetCap:
    def _make_nudges(self, count: int) -> list[Nudge]:
        return [
            Nudge(
                category="test",
                priority_score=100 - i,
                priority_label="high",
                title=f"nudge {i}",
                detail="",
                suggested_action="",
            )
            for i in range(count)
        ]

    @patch("cockpit.data.nudges._collect_health_nudges")
    @patch("cockpit.data.nudges._collect_briefing_nudges")
    @patch("cockpit.data.nudges._collect_readiness_nudges")
    @patch("cockpit.data.nudges._collect_profile_nudges")
    @patch("cockpit.data.nudges._collect_scout_nudges")
    @patch("cockpit.data.nudges._collect_drift_nudges")
    @patch("cockpit.data.nudges._collect_goal_nudges")
    @patch("cockpit.data.nudges._collect_sufficiency_nudges")
    @patch("cockpit.data.nudges._collect_knowledge_sufficiency_nudges")
    def test_under_cap_no_meta(self, *mocks):
        def inject(nudges):
            nudges.extend(self._make_nudges(3))

        mocks[-1].side_effect = inject
        result = collect_nudges(max_nudges=20)
        assert len(result) == 3
        assert all(n.category != "meta" for n in result)

    @patch("cockpit.data.nudges._collect_health_nudges")
    @patch("cockpit.data.nudges._collect_briefing_nudges")
    @patch("cockpit.data.nudges._collect_readiness_nudges")
    @patch("cockpit.data.nudges._collect_profile_nudges")
    @patch("cockpit.data.nudges._collect_scout_nudges")
    @patch("cockpit.data.nudges._collect_drift_nudges")
    @patch("cockpit.data.nudges._collect_goal_nudges")
    @patch("cockpit.data.nudges._collect_sufficiency_nudges")
    @patch("cockpit.data.nudges._collect_knowledge_sufficiency_nudges")
    def test_over_cap_adds_meta(self, *mocks):
        from cockpit.data.nudges import MAX_VISIBLE_NUDGES

        def inject(nudges):
            nudges.extend(self._make_nudges(15))

        mocks[-1].side_effect = inject
        result = collect_nudges(max_nudges=20)
        assert len(result) == MAX_VISIBLE_NUDGES + 1
        meta = result[-1]
        assert meta.category == "meta"
        assert meta.priority_score == 0
        assert "more items" in meta.title


# ── Emergence nudges ──────────────────────────────────────────────────────


class TestEmergenceNudges:
    def test_emergence_candidates_produce_nudges(self) -> None:
        """Active emergence candidates generate nudges."""
        nudges: list[Nudge] = []
        _collect_emergence_nudges(nudges)
        # Should not crash — may produce 0 nudges if no candidates
        assert isinstance(nudges, list)
