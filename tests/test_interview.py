"""Tests for the interview system — models, analysis, serialization, profiler integration.

No LLM calls; tests focus on deterministic logic.
"""

import json
from pathlib import Path

import pytest

from agents.profiler import (
    ProfileDimension,
    ProfileFact,
    UserProfile,
    flush_interview_facts,
    load_existing_profile,
)
from cockpit.interview import (
    InterviewPlan,
    InterviewState,
    InterviewTopic,
    ProfileAnalysis,
    RecordedFact,
    RecordedInsight,
    analyze_profile,
    format_interview_summary,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_topic(dimension="work_patterns", topic="test", depth="surface"):
    return InterviewTopic(
        dimension=dimension,
        topic=topic,
        rationale="test rationale",
        question_seed="test question?",
        depth=depth,
    )


def _make_plan(*topics, focus="test focus"):
    return InterviewPlan(topics=list(topics), overall_focus=focus)


def _make_state(**kwargs):
    defaults = dict(
        plan=_make_plan(_make_topic()),
        started_at="2026-03-01T00:00:00Z",
    )
    defaults.update(kwargs)
    return InterviewState(**defaults)


# ── Model tests ──────────────────────────────────────────────────────────────


def test_interview_topic_creation():
    topic = _make_topic(dimension="work_patterns", topic="daily routine")
    assert topic.dimension == "work_patterns"
    assert topic.depth == "surface"


def test_interview_plan_creation():
    plan = _make_plan(
        _make_topic(topic="daily routine"),
        _make_topic(dimension="values", topic="design principles", depth="challenge"),
        focus="Explore work_patterns and values gaps",
    )
    assert len(plan.topics) == 2
    assert plan.overall_focus.startswith("Explore")


def test_recorded_fact_creation():
    fact = RecordedFact(
        dimension="identity",
        key="morning_routine",
        value="Starts day with coffee and briefing review",
        confidence=0.9,
        evidence="Operator stated: 'I always check the briefing first thing'",
    )
    assert fact.confidence == 0.9
    assert fact.dimension == "identity"


def test_recorded_fact_confidence_bounds():
    fact = RecordedFact(
        dimension="work_patterns",
        key="test",
        value="test",
        confidence=0.0,
        evidence="test",
    )
    assert fact.confidence == 0.0

    fact2 = RecordedFact(
        dimension="work_patterns",
        key="test",
        value="test",
        confidence=1.0,
        evidence="test",
    )
    assert fact2.confidence == 1.0


def test_recorded_fact_rejects_invalid_confidence():
    with pytest.raises(Exception):
        RecordedFact(
            dimension="work_patterns",
            key="test",
            value="test",
            confidence=1.5,
            evidence="test",
        )


def test_recorded_insight_creation():
    insight = RecordedInsight(
        category="workflow_gap",
        description="No backup strategy for creative work",
        recommendation="Set up automated backup for SP-404 patterns",
    )
    assert insight.category == "workflow_gap"


def test_recorded_insight_categories():
    valid = ["workflow_gap", "goal_refinement", "practice_critique", "aspiration", "contradiction"]
    for cat in valid:
        insight = RecordedInsight(category=cat, description="test", recommendation="test")
        assert insight.category == cat


def test_interview_state_creation():
    state = _make_state()
    assert state.facts == []
    assert state.insights == []
    assert state.topics_explored == []


def test_interview_state_serialization():
    """InterviewState round-trips through JSON."""
    state = InterviewState(
        plan=_make_plan(
            _make_topic(topic="daily routine"),
            _make_topic(dimension="values", topic="design principles", depth="challenge"),
            focus="Explore work_patterns and values",
        ),
        facts=[
            RecordedFact(
                dimension="work_patterns",
                key="start_time",
                value="7am",
                confidence=0.9,
                evidence="said 7am",
            ),
        ],
        insights=[
            RecordedInsight(
                category="aspiration",
                description="wants more automation",
                recommendation="explore n8n workflows",
            ),
        ],
        topics_explored=["daily routine"],
        started_at="2026-03-01T00:00:00Z",
    )

    data = state.model_dump()
    json_str = json.dumps(data)
    restored = InterviewState.model_validate(json.loads(json_str))

    assert len(restored.plan.topics) == 2
    assert len(restored.facts) == 1
    assert restored.facts[0].key == "start_time"
    assert len(restored.insights) == 1
    assert restored.insights[0].category == "aspiration"
    assert restored.topics_explored == ["daily routine"]


# ── InterviewState property tests ────────────────────────────────────────────


def test_all_topics_explored_false():
    state = _make_state(plan=_make_plan(_make_topic(topic="a"), _make_topic(topic="b")))
    assert state.all_topics_explored is False


def test_all_topics_explored_partial():
    state = _make_state(
        plan=_make_plan(_make_topic(topic="a"), _make_topic(topic="b")),
        topics_explored=["a"],
    )
    assert state.all_topics_explored is False


def test_all_topics_explored_true():
    state = _make_state(
        plan=_make_plan(_make_topic(topic="a"), _make_topic(topic="b")),
        topics_explored=["a", "b"],
    )
    assert state.all_topics_explored is True


def test_all_topics_explored_empty_plan():
    state = _make_state(plan=_make_plan(focus="empty"))
    assert state.all_topics_explored is False


def test_current_topic():
    state = _make_state(
        plan=_make_plan(_make_topic(topic="a"), _make_topic(topic="b")),
    )
    assert state.current_topic is not None
    assert state.current_topic.topic == "a"


def test_current_topic_after_exploring_first():
    state = _make_state(
        plan=_make_plan(_make_topic(topic="a"), _make_topic(topic="b")),
        topics_explored=["a"],
    )
    assert state.current_topic is not None
    assert state.current_topic.topic == "b"


def test_current_topic_all_explored():
    state = _make_state(
        plan=_make_plan(_make_topic(topic="a")),
        topics_explored=["a"],
    )
    assert state.current_topic is None


# ── Analysis tests ───────────────────────────────────────────────────────────


def test_analyze_profile_runs():
    """analyze_profile() runs without error (uses real profile if available)."""
    analysis = analyze_profile()
    assert isinstance(analysis, ProfileAnalysis)
    assert isinstance(analysis.total_facts, int)
    assert isinstance(analysis.dimension_stats, dict)


def test_analyze_profile_with_real_data():
    """If a profile exists, analysis should have meaningful stats."""
    profile = load_existing_profile()
    if profile is None:
        pytest.skip("No profile found — skipping real data test")

    analysis = analyze_profile()
    assert analysis.total_facts > 0
    assert len(analysis.dimension_stats) > 0


def test_profile_analysis_empty():
    """ProfileAnalysis can be constructed with defaults."""
    analysis = ProfileAnalysis()
    assert analysis.total_facts == 0
    assert analysis.sparse_dimensions == []
    assert analysis.missing_dimensions == []
    assert analysis.low_confidence_clusters == []
    assert analysis.goal_gaps == []


# ── Profiler integration tests ───────────────────────────────────────────────


def test_flush_empty():
    """Flushing empty facts/insights returns a message without modifying profile."""
    result = flush_interview_facts([], [])
    assert "No facts or insights" in result


def test_recorded_fact_to_profile_fact():
    """RecordedFact fields map correctly to ProfileFact."""
    rf = RecordedFact(
        dimension="work_patterns",
        key="preferred_editor",
        value="neovim",
        confidence=0.95,
        evidence="stated preference",
    )
    pf = ProfileFact(
        dimension=rf.dimension,
        key=rf.key,
        value=rf.value,
        confidence=rf.confidence,
        source="interview:cockpit",
        evidence=rf.evidence,
    )
    assert pf.dimension == "work_patterns"
    assert pf.source == "interview:cockpit"
    assert pf.key == "preferred_editor"


def test_flush_facts_creates_profile_facts(tmp_path, monkeypatch):
    """flush_interview_facts converts RecordedFacts and merges into profile."""
    profile = UserProfile(
        name="Test",
        summary="Test profile",
        dimensions=[
            ProfileDimension(
                name="work_patterns",
                summary="test",
                facts=[
                    ProfileFact(
                        dimension="work_patterns",
                        key="existing_fact",
                        value="old value",
                        confidence=0.8,
                        source="test",
                        evidence="test",
                    )
                ],
            ),
        ],
        sources_processed=["test"],
        version=1,
        updated_at="2026-01-01",
    )

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "operator-profile.json").write_text(profile.model_dump_json(indent=2))
    monkeypatch.setattr("agents.profiler.PROFILES_DIR", profiles_dir)

    facts = [
        RecordedFact(
            dimension="work_patterns",
            key="new_fact",
            value="new value",
            confidence=0.9,
            evidence="operator said so",
        ),
    ]
    insights = [
        RecordedInsight(
            category="workflow_gap",
            description="missing backup strategy",
            recommendation="add backups",
        ),
    ]

    result = flush_interview_facts(facts, insights)
    assert "1 facts" in result
    assert "1 insights" in result

    updated = json.loads((profiles_dir / "operator-profile.json").read_text())
    assert updated["version"] == 2

    work_dim = next(d for d in updated["dimensions"] if d["name"] == "work_patterns")
    fact_keys = [f["key"] for f in work_dim["facts"]]
    assert "existing_fact" in fact_keys
    assert "new_fact" in fact_keys
    insight_facts = [
        f
        for f in work_dim["facts"]
        if f["source"] == "interview:cockpit" and "insight_" in f["key"]
    ]
    assert len(insight_facts) == 1


def test_flush_insights_unique_keys(tmp_path, monkeypatch):
    """Multiple insights of the same category get unique keys."""
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    monkeypatch.setattr("agents.profiler.PROFILES_DIR", profiles_dir)

    insights = [
        RecordedInsight(
            category="workflow_gap",
            description="missing backup strategy",
            recommendation="add backups",
        ),
        RecordedInsight(
            category="workflow_gap",
            description="no CI/CD pipeline",
            recommendation="set up GitHub Actions",
        ),
    ]

    result = flush_interview_facts([], insights)
    assert "2 insights" in result

    updated = json.loads((profiles_dir / "operator-profile.json").read_text())
    work_dim = next(d for d in updated["dimensions"] if d["name"] == "work_patterns")
    insight_keys = [f["key"] for f in work_dim["facts"] if "insight_" in f["key"]]
    # Both insights should be present (unique keys via description hash)
    assert len(insight_keys) == 2
    assert insight_keys[0] != insight_keys[1]


# ── Summary formatting tests ─────────────────────────────────────────────────


def test_format_interview_summary_empty():
    state = _make_state(plan=_make_plan(focus="test"))
    summary = format_interview_summary(state)
    assert "0/0 topics" in summary
    assert "Facts recorded: 0" in summary


def test_format_interview_summary_with_data():
    state = InterviewState(
        plan=_make_plan(
            _make_topic(topic="t1"),
            _make_topic(dimension="values", topic="t2", depth="deep"),
        ),
        facts=[
            RecordedFact(
                dimension="work_patterns", key="k1", value="v1", confidence=0.9, evidence="e"
            ),
            RecordedFact(dimension="values", key="k2", value="v2", confidence=0.8, evidence="e"),
        ],
        insights=[
            RecordedInsight(category="aspiration", description="wants X", recommendation="try Y"),
        ],
        topics_explored=["t1"],
        started_at="2026-03-01T00:00:00Z",
    )

    summary = format_interview_summary(state)
    assert "1/2 topics" in summary
    assert "Facts recorded: 2" in summary
    assert "Insights recorded: 1" in summary
    assert "work_patterns: 1" in summary
    assert "values: 1" in summary
    assert "aspiration" in summary


# ── ChatSession tests ────────────────────────────────────────────────────────


def test_chat_session_saves_interview_state(tmp_path):
    """ChatSession serializes interview state alongside message history."""
    from cockpit.chat_agent import ChatSession

    session = ChatSession(project_dir=tmp_path)
    session.mode = "interview"
    session.interview_state = _make_state()

    save_path = tmp_path / "session.json"
    session.save(save_path)

    data = json.loads(save_path.read_text())
    assert data["mode"] == "interview"
    assert data["interview_state"]["plan"]["overall_focus"] == "test focus"
    assert len(data["interview_state"]["plan"]["topics"]) == 1


def test_chat_session_loads_interview_state(tmp_path):
    """ChatSession restores interview state from JSON."""
    from cockpit.chat_agent import ChatSession

    session = ChatSession(project_dir=tmp_path)
    session.mode = "interview"
    session.interview_state = InterviewState(
        plan=_make_plan(
            _make_topic(topic="test topic", depth="deep"),
            focus="testing persistence",
        ),
        facts=[
            RecordedFact(
                dimension="work_patterns",
                key="test_key",
                value="test_value",
                confidence=0.85,
                evidence="test evidence",
            ),
        ],
        started_at="2026-03-01T00:00:00Z",
    )

    save_path = tmp_path / "session.json"
    session.save(save_path)

    loaded = ChatSession.load(save_path, tmp_path)
    assert loaded.mode == "interview"
    assert loaded.interview_state is not None
    assert loaded.interview_state.plan.overall_focus == "testing persistence"
    assert len(loaded.interview_state.facts) == 1
    assert loaded.interview_state.facts[0].key == "test_key"


def test_chat_session_loads_without_interview_state(tmp_path):
    """ChatSession loads cleanly when no interview state is present (backward compat)."""
    from cockpit.chat_agent import ChatSession

    session = ChatSession(project_dir=tmp_path)
    save_path = tmp_path / "session.json"
    session.save(save_path)

    loaded = ChatSession.load(save_path, tmp_path)
    assert loaded.mode == "chat"
    assert loaded.interview_state is None


def test_clear_resets_interview_state(tmp_path):
    """clear() resets mode and interview state back to chat defaults."""
    from cockpit.chat_agent import ChatSession

    session = ChatSession(project_dir=tmp_path)
    session.mode = "interview"
    session.interview_state = _make_state()
    session.total_tokens = 1000

    session.clear()
    assert session.mode == "chat"
    assert session.interview_state is None
    assert session.total_tokens == 0
    assert session.message_history == []


def test_interview_status_no_interview(tmp_path):
    """interview_status() returns message when no interview active."""
    from cockpit.chat_agent import ChatSession

    session = ChatSession(project_dir=tmp_path)
    assert session.interview_status() == "No active interview."


def test_interview_status_with_progress(tmp_path):
    """interview_status() includes model, topic count, facts, insights."""
    from cockpit.chat_agent import ChatSession

    session = ChatSession(project_dir=tmp_path)
    session.mode = "interview"
    session.interview_state = InterviewState(
        plan=_make_plan(
            _make_topic(topic="a"),
            _make_topic(topic="b"),
            _make_topic(topic="c"),
        ),
        facts=[
            RecordedFact(dimension="w", key="k", value="v", confidence=0.9, evidence="e"),
            RecordedFact(dimension="w", key="k2", value="v2", confidence=0.8, evidence="e"),
        ],
        insights=[
            RecordedInsight(category="aspiration", description="d", recommendation="r"),
        ],
        topics_explored=["a"],
        started_at="2026-03-01T00:00:00Z",
    )

    status = session.interview_status()
    assert "balanced" in status  # default model alias
    assert "1/3 topics" in status
    assert "2 facts" in status
    assert "1 insights" in status


def test_skip_interview_topic(tmp_path):
    """skip_interview_topic() advances to next topic."""
    from cockpit.chat_agent import ChatSession

    session = ChatSession(project_dir=tmp_path)
    session.mode = "interview"
    session.interview_state = InterviewState(
        plan=_make_plan(
            _make_topic(topic="first"),
            _make_topic(topic="second"),
            _make_topic(topic="third"),
        ),
        started_at="2026-03-01T00:00:00Z",
    )

    result = session.skip_interview_topic()
    assert "Skipped 'first'" in result
    assert "second" in result
    assert session.interview_state.topics_explored == ["first"]

    result2 = session.skip_interview_topic()
    assert "Skipped 'second'" in result2
    assert "third" in result2


def test_skip_interview_topic_last():
    """skip_interview_topic() on last topic reports all explored."""
    from cockpit.chat_agent import ChatSession

    session = ChatSession(project_dir=Path("."))
    session.mode = "interview"
    session.interview_state = InterviewState(
        plan=_make_plan(_make_topic(topic="only")),
        started_at="2026-03-01T00:00:00Z",
    )

    result = session.skip_interview_topic()
    assert "All topics explored" in result
    assert session.interview_state.all_topics_explored is True


def test_skip_interview_topic_no_interview(tmp_path):
    """skip_interview_topic() without active interview returns message."""
    from cockpit.chat_agent import ChatSession

    session = ChatSession(project_dir=tmp_path)
    assert "No active interview" in session.skip_interview_topic()


def test_recorded_insight_neurocognitive_category():
    """neurocognitive_pattern is a valid RecordedInsight category."""
    insight = RecordedInsight(
        category="neurocognitive_pattern",
        description="Body doubling enables task initiation",
        recommendation="System should support body-doubling patterns",
    )
    assert insight.category == "neurocognitive_pattern"


def test_profile_analysis_neurocognitive_gap_default():
    """ProfileAnalysis defaults neurocognitive_gap to False."""
    analysis = ProfileAnalysis()
    assert analysis.neurocognitive_gap is False


def test_analyze_profile_includes_neurocognitive_gap():
    """analyze_profile() output includes neurocognitive_gap field."""
    analysis = analyze_profile()
    assert hasattr(analysis, "neurocognitive_gap")
    assert isinstance(analysis.neurocognitive_gap, bool)
