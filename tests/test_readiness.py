"""Tests for logos.data.readiness — data maturity assessment.

All deterministic, no LLM calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from logos.data.readiness import (
    ReadinessSnapshot,
    _check_interview_facts,
    _check_priorities_validated,
    _compute_level,
    collect_readiness,
)

# ── Helpers ─────────────────────────────────────────────────────────────────


def _mock_analysis(
    missing=None,
    sparse=None,
    dimension_stats=None,
    total_facts=100,
    neurocognitive_gap=False,
    goal_gaps=None,
):
    from logos.interview import ProfileAnalysis

    return ProfileAnalysis(
        missing_dimensions=missing or [],
        sparse_dimensions=sparse or [],
        dimension_stats=dimension_stats or {},
        total_facts=total_facts,
        neurocognitive_gap=neurocognitive_gap,
        goal_gaps=goal_gaps or [],
    )


def _mock_profile(facts_with_sources=None):
    """Create a mock profile with facts that have specific sources."""
    profile = MagicMock()
    dims = []
    if facts_with_sources:
        for dim_name, sources in facts_with_sources.items():
            dim = MagicMock()
            dim.name = dim_name
            dim.facts = []
            for src in sources:
                fact = MagicMock()
                fact.source = src
                dim.facts.append(fact)
            dims.append(dim)
    profile.dimensions = dims
    return profile


# ── Level computation ───────────────────────────────────────────────────────


def test_level_bootstrapping_no_interview():
    snap = ReadinessSnapshot(interview_conducted=False)
    assert _compute_level(snap) == "bootstrapping"


def test_level_bootstrapping_even_with_coverage():
    snap = ReadinessSnapshot(
        interview_conducted=False,
        neurocognitive_mapped=True,
        priorities_known=True,
        missing_dimensions=[],
    )
    assert _compute_level(snap) == "bootstrapping"


def test_level_developing_missing_dims():
    snap = ReadinessSnapshot(
        interview_conducted=True,
        neurocognitive_mapped=True,
        priorities_known=True,
        missing_dimensions=["identity"],
    )
    assert _compute_level(snap) == "developing"


def test_level_developing_neurocognitive_gap():
    snap = ReadinessSnapshot(
        interview_conducted=True,
        neurocognitive_mapped=False,
        priorities_known=True,
        missing_dimensions=[],
    )
    assert _compute_level(snap) == "developing"


def test_level_developing_priorities_unknown():
    snap = ReadinessSnapshot(
        interview_conducted=True,
        neurocognitive_mapped=True,
        priorities_known=False,
        missing_dimensions=[],
    )
    assert _compute_level(snap) == "developing"


def test_level_operational():
    snap = ReadinessSnapshot(
        interview_conducted=True,
        neurocognitive_mapped=True,
        priorities_known=True,
        missing_dimensions=[],
    )
    assert _compute_level(snap) == "operational"


# ── Interview detection ─────────────────────────────────────────────────────


@patch("agents.profiler.load_existing_profile")
def test_interview_facts_detected(mock_profiler_load):
    profile = _mock_profile(
        {
            "identity": ["config:CLAUDE.md", "interview:logos"],
            "workflow": ["config:operator.json", "interview:logos"],
        }
    )
    mock_profiler_load.return_value = profile
    conducted, count = _check_interview_facts()
    assert conducted is True
    assert count == 2


@patch("agents.profiler.load_existing_profile")
def test_no_interview_facts(mock_load):
    profile = _mock_profile(
        {
            "identity": ["config:CLAUDE.md"],
            "workflow": ["config:operator.json"],
        }
    )
    mock_load.return_value = profile
    conducted, count = _check_interview_facts()
    assert conducted is False
    assert count == 0


@patch("agents.profiler.load_existing_profile")
def test_interview_facts_no_profile(mock_load):
    mock_load.return_value = None
    conducted, count = _check_interview_facts()
    assert conducted is False
    assert count == 0


@patch("agents.profiler.load_existing_profile")
def test_interview_facts_exception(mock_load):
    mock_load.side_effect = RuntimeError("boom")
    conducted, count = _check_interview_facts()
    assert conducted is False
    assert count == 0


# ── Priorities validation ───────────────────────────────────────────────────


@patch("shared.operator.get_goals")
def test_priorities_validated_some_goals_covered(mock_goals):
    mock_goals.return_value = [
        {"id": "g1", "name": "Goal 1"},
        {"id": "g2", "name": "Goal 2"},
    ]
    analysis = _mock_analysis(goal_gaps=[{"goal_id": "g2", "goal_name": "Goal 2"}])
    assert _check_priorities_validated(analysis) is True


@patch("shared.operator.get_goals")
def test_priorities_not_validated_all_goals_gaps(mock_goals):
    mock_goals.return_value = [
        {"id": "g1", "name": "Goal 1"},
    ]
    analysis = _mock_analysis(goal_gaps=[{"goal_id": "g1", "goal_name": "Goal 1"}])
    assert _check_priorities_validated(analysis) is False


@patch("shared.operator.get_goals")
def test_priorities_no_goals_defined(mock_goals):
    mock_goals.return_value = []
    analysis = _mock_analysis()
    assert _check_priorities_validated(analysis) is False


# ── collect_readiness integration ───────────────────────────────────────────


@patch("logos.data.readiness._check_priorities_validated")
@patch("logos.data.readiness._check_interview_facts")
@patch("logos.interview.analyze_profile")
def test_collect_bootstrapping(mock_analyze, mock_interview, mock_priorities):
    mock_analyze.return_value = _mock_analysis(
        missing=["identity", "philosophy"],
        dimension_stats={
            "workflow": {"count": 5, "avg_confidence": 0.8},
            "technical_skills": {"count": 10, "avg_confidence": 0.9},
        },
        total_facts=50,
        neurocognitive_gap=True,
    )
    mock_interview.return_value = (False, 0)
    mock_priorities.return_value = False

    snap = collect_readiness()
    assert snap.level == "bootstrapping"
    assert snap.interview_conducted is False
    assert snap.total_facts == 50
    assert len(snap.missing_dimensions) == 2
    assert snap.gaps[0] == "no interview conducted"
    assert snap.top_gap == "no interview conducted"


@patch("logos.data.readiness._check_priorities_validated")
@patch("logos.data.readiness._check_interview_facts")
@patch("logos.interview.analyze_profile")
def test_collect_developing(mock_analyze, mock_interview, mock_priorities):
    mock_analyze.return_value = _mock_analysis(
        missing=["identity"],
        dimension_stats={
            dim: {"count": 10, "avg_confidence": 0.8}
            for dim in ["workflow", "technical_skills", "music_production"]
        },
        total_facts=200,
        neurocognitive_gap=False,
    )
    mock_interview.return_value = (True, 15)
    mock_priorities.return_value = True

    snap = collect_readiness()
    assert snap.level == "developing"
    assert snap.interview_conducted is True
    assert snap.interview_fact_count == 15
    assert "no interview conducted" not in snap.gaps
    assert any("missing" in g for g in snap.gaps)


@patch("logos.data.readiness._check_priorities_validated")
@patch("logos.data.readiness._check_interview_facts")
@patch("logos.interview.analyze_profile")
def test_collect_operational(mock_analyze, mock_interview, mock_priorities):
    mock_analyze.return_value = _mock_analysis(
        missing=[],
        dimension_stats={
            dim: {"count": 10, "avg_confidence": 0.8}
            for dim in [
                "identity",
                "technical_skills",
                "music_production",
                "hardware",
                "software_preferences",
                "communication_style",
                "decision_patterns",
                "philosophy",
                "knowledge_domains",
                "workflow",
                "neurocognitive_profile",
            ]
        },
        total_facts=500,
        neurocognitive_gap=False,
    )
    mock_interview.return_value = (True, 30)
    mock_priorities.return_value = True

    snap = collect_readiness()
    assert snap.level == "operational"
    assert snap.gaps == []
    assert snap.top_gap == ""


@patch("logos.interview.analyze_profile")
def test_collect_readiness_analyze_exception(mock_analyze):
    mock_analyze.side_effect = RuntimeError("profile broken")
    snap = collect_readiness()
    assert snap.level == "bootstrapping"
    assert len(snap.gaps) > 0
    assert snap.top_gap == "no interview conducted"


# ── Gap ordering ────────────────────────────────────────────────────────────


@patch("logos.data.readiness._check_priorities_validated")
@patch("logos.data.readiness._check_interview_facts")
@patch("logos.interview.analyze_profile")
def test_gap_ordering(mock_analyze, mock_interview, mock_priorities):
    """Gaps are ordered by impact: interview > priorities > neurocognitive > missing > sparse."""
    mock_analyze.return_value = _mock_analysis(
        missing=["identity"],
        sparse=[{"dimension": "work_patterns", "fact_count": 2, "avg_confidence": 0.6}],
        dimension_stats={"work_patterns": {"count": 2, "avg_confidence": 0.6}},
        neurocognitive_gap=True,
    )
    mock_interview.return_value = (False, 0)
    mock_priorities.return_value = False

    snap = collect_readiness()
    assert snap.gaps[0] == "no interview conducted"
    assert snap.gaps[1] == "priorities not validated"
    assert snap.gaps[2] == "neurocognitive patterns undiscovered"
    assert "missing" in snap.gaps[3]
    assert "sparse" in snap.gaps[4]


# ── Coverage percentage ─────────────────────────────────────────────────────


@patch("logos.data.readiness._check_priorities_validated")
@patch("logos.data.readiness._check_interview_facts")
@patch("logos.interview.analyze_profile")
def test_coverage_percentage(mock_analyze, mock_interview, mock_priorities):
    mock_analyze.return_value = _mock_analysis(
        missing=["identity", "philosophy"],
        dimension_stats={
            dim: {"count": 5, "avg_confidence": 0.8}
            for dim in ["workflow", "technical_skills", "music_production"]
        },
    )
    mock_interview.return_value = (False, 0)
    mock_priorities.return_value = False

    snap = collect_readiness()
    # 3 populated out of 5 total (3 populated + 2 missing)
    assert snap.populated_dimensions == 3
    assert snap.total_dimensions == 5
    assert snap.profile_coverage_pct == 60.0
