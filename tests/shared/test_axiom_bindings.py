"""Tests for shared.axiom_bindings — internal helpers + report types.

159-LOC axiom-binding completeness validator. Tests cover the
data-handling heuristics + BindingReport shape; the full
validate_bindings() integration path requires the live AXIOMS_PATH
+ agent-manifest registry and is exercised by integration runs.
"""

from __future__ import annotations

from shared.agent_registry import (
    AgentManifest,
    AxiomBinding,
    ScheduleSpec,
    ScheduleType,
)
from shared.axiom_bindings import (
    BindingGap,
    BindingReport,
    _agent_handles_person_data,
    _agent_handles_work_data,
)


def _manifest(
    *,
    agent_id: str = "test-agent",
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    capabilities: list[str] | None = None,
    bindings: list[AxiomBinding] | None = None,
) -> AgentManifest:
    return AgentManifest(
        id=agent_id,
        name=agent_id,
        category="observability",  # type: ignore[arg-type]
        purpose="test",
        inputs=inputs or [],
        outputs=outputs or [],
        capabilities=capabilities or [],
        schedule=ScheduleSpec(type=ScheduleType.ON_DEMAND),
        axiom_bindings=bindings or [],
    )


# ── _agent_handles_person_data ─────────────────────────────────────


class TestPersonDataHeuristic:
    def test_capability_in_person_set_triggers(self) -> None:
        m = _manifest(capabilities=["voice_processing"])
        assert _agent_handles_person_data(m)

    def test_input_with_person_term_triggers(self) -> None:
        m = _manifest(inputs=["operator-profile"])
        assert _agent_handles_person_data(m)

    def test_input_with_face_term_triggers(self) -> None:
        m = _manifest(inputs=["face-snapshots/*.jpg"])
        assert _agent_handles_person_data(m)

    def test_input_with_voice_term_triggers(self) -> None:
        m = _manifest(inputs=["voice-recording.wav"])
        assert _agent_handles_person_data(m)

    def test_input_with_conversation_term_triggers(self) -> None:
        m = _manifest(inputs=["conversation-history.jsonl"])
        assert _agent_handles_person_data(m)

    def test_no_person_indicators_returns_false(self) -> None:
        m = _manifest(
            inputs=["health-report.json", "metrics.csv"],
            capabilities=["audit_logging"],
        )
        assert not _agent_handles_person_data(m)

    def test_empty_manifest_returns_false(self) -> None:
        assert not _agent_handles_person_data(_manifest())

    def test_case_insensitive_matching(self) -> None:
        m = _manifest(inputs=["Operator-Profile.json"])
        assert _agent_handles_person_data(m)


# ── _agent_handles_work_data ───────────────────────────────────────


class TestWorkDataHeuristic:
    def test_jira_input_triggers(self) -> None:
        m = _manifest(inputs=["jira-tickets.json"])
        assert _agent_handles_work_data(m)

    def test_slack_output_triggers(self) -> None:
        m = _manifest(outputs=["slack-digest.md"])
        assert _agent_handles_work_data(m)

    def test_team_snapshot_input_triggers(self) -> None:
        m = _manifest(inputs=["team-snapshot.json"])
        assert _agent_handles_work_data(m)

    def test_no_work_terms_returns_false(self) -> None:
        m = _manifest(
            inputs=["health-report.json"],
            outputs=["audit-log.jsonl"],
        )
        assert not _agent_handles_work_data(m)

    def test_case_insensitive(self) -> None:
        m = _manifest(inputs=["JIRA-tickets.json"])
        assert _agent_handles_work_data(m)


# ── BindingReport ──────────────────────────────────────────────────


class TestBindingReport:
    def test_empty_report_is_complete(self) -> None:
        report = BindingReport(total_agents=0, agents_with_bindings=0, gaps=())
        assert report.is_complete
        assert report.coverage_ratio == 1.0

    def test_no_gaps_is_complete(self) -> None:
        report = BindingReport(total_agents=5, agents_with_bindings=5, gaps=())
        assert report.is_complete

    def test_gaps_present_not_complete(self) -> None:
        gap = BindingGap(agent_id="x", axiom_id="single_user", reason="missing")
        report = BindingReport(total_agents=5, agents_with_bindings=4, gaps=(gap,))
        assert not report.is_complete

    def test_coverage_ratio_partial(self) -> None:
        report = BindingReport(total_agents=10, agents_with_bindings=7, gaps=())
        assert report.coverage_ratio == 0.7

    def test_coverage_ratio_full(self) -> None:
        report = BindingReport(total_agents=10, agents_with_bindings=10, gaps=())
        assert report.coverage_ratio == 1.0

    def test_coverage_ratio_zero_agents_returns_one(self) -> None:
        """Zero agents = no coverage gaps possible = trivially complete."""
        report = BindingReport(total_agents=0, agents_with_bindings=0, gaps=())
        assert report.coverage_ratio == 1.0


# ── BindingGap dataclass ──────────────────────────────────────────


class TestBindingGap:
    def test_construction_and_fields(self) -> None:
        gap = BindingGap(
            agent_id="profile_sync",
            axiom_id="interpersonal_transparency",
            reason="agent handles person data without binding",
        )
        assert gap.agent_id == "profile_sync"
        assert gap.axiom_id == "interpersonal_transparency"
        assert "person data" in gap.reason

    def test_is_frozen(self) -> None:
        gap = BindingGap(agent_id="x", axiom_id="y", reason="z")
        try:
            gap.agent_id = "mutated"  # type: ignore[misc]
        except Exception:
            return
        raise AssertionError("BindingGap should be frozen")
