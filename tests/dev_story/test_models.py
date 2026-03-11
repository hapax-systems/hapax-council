"""Tests for dev_story data models."""

from __future__ import annotations

from agents.dev_story.models import (
    CodeSurvivalEntry,
    Commit,
    CommitFile,
    Correlation,
    CriticalMoment,
    FileChange,
    HotspotEntry,
    Message,
    Session,
    SessionMetrics,
    SessionTag,
    ToolCall,
)


def test_session_defaults():
    s = Session(
        id="abc-123",
        project_path="/home/user/projects/foo",
        project_name="foo",
        started_at="2026-03-10T10:00:00Z",
    )
    assert s.git_branch is None
    assert s.message_count == 0
    assert s.total_tokens_in == 0
    assert s.total_tokens_out == 0
    assert s.total_cost_estimate == 0.0
    assert s.model_primary is None
    assert s.ended_at is None


def test_message_fields():
    m = Message(
        id="msg-1",
        session_id="abc-123",
        role="assistant",
        timestamp="2026-03-10T10:00:01Z",
        content_text="Hello",
    )
    assert m.parent_id is None
    assert m.model is None
    assert m.tokens_in == 0
    assert m.tokens_out == 0


def test_tool_call_fields():
    tc = ToolCall(
        message_id="msg-1",
        tool_name="Edit",
        sequence_position=0,
    )
    assert tc.arguments_summary is None
    assert tc.duration_ms is None
    assert tc.success is True


def test_file_change_fields():
    fc = FileChange(
        message_id="msg-1",
        file_path="shared/config.py",
        version=2,
        change_type="modified",
        timestamp="2026-03-10T10:00:02Z",
    )
    assert fc.file_path == "shared/config.py"


def test_commit_fields():
    c = Commit(
        hash="abc123def",
        author_date="2026-03-10 10:00:00 -0500",
        message="feat: add something",
    )
    assert c.branch is None
    assert c.files_changed == 0
    assert c.insertions == 0
    assert c.deletions == 0


def test_commit_file_fields():
    cf = CommitFile(
        commit_hash="abc123def",
        file_path="shared/config.py",
        operation="M",
    )
    assert cf.operation == "M"


def test_correlation_confidence_range():
    c = Correlation(
        message_id="msg-1",
        commit_hash="abc123def",
        confidence=0.85,
        method="file_and_timestamp",
    )
    assert 0.0 <= c.confidence <= 1.0


def test_session_metrics_defaults():
    sm = SessionMetrics(session_id="abc-123")
    assert sm.tool_call_count == 0
    assert sm.tool_diversity == 0
    assert sm.edit_count == 0
    assert sm.bash_count == 0
    assert sm.agent_dispatch_count == 0
    assert sm.user_steering_ratio == 0.0
    assert sm.phase_sequence is None


def test_session_tag():
    t = SessionTag(
        session_id="abc-123",
        dimension="work_type",
        value="feature",
        confidence=0.9,
    )
    assert t.dimension == "work_type"


def test_critical_moment():
    cm = CriticalMoment(
        moment_type="churn",
        severity=0.8,
        session_id="abc-123",
        description="Code rewritten within 2 days",
    )
    assert cm.message_id is None
    assert cm.commit_hash is None
    assert cm.evidence is None


def test_hotspot_entry():
    h = HotspotEntry(
        file_path="shared/config.py",
        change_frequency=31,
        session_count=12,
        churn_rate=0.15,
    )
    assert h.change_frequency == 31


def test_code_survival_entry():
    cs = CodeSurvivalEntry(
        file_path="shared/config.py",
        introduced_by_commit="abc123",
        survived_days=5.5,
    )
    assert cs.introduced_by_session is None
    assert cs.replacement_commit is None
