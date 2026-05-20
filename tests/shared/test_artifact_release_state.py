"""Tests for the artifact release state machine."""

from __future__ import annotations

import pytest

from shared.artifact_release_state import (
    TERMINAL_STATES,
    VALID_TRANSITIONS,
    ArtifactReleaseRecord,
    InvalidTransitionError,
    ReleaseMetrics,
    ReleaseState,
    SourceRef,
)


def _candidate() -> ArtifactReleaseRecord:
    return ArtifactReleaseRecord(
        artifact_id="art-001",
        public_event_refs=[SourceRef(ref_type="public_event", ref_id="evt-1")],
        run_refs=[SourceRef(ref_type="run", ref_id="run-1")],
        rights_class="operator_owned",
        privacy_class="public_safe",
    )


class TestStateTransitions:
    def test_candidate_to_public_safe(self):
        r = _candidate()
        t = r.transition(ReleaseState.PUBLIC_SAFE, reason="rights cleared")
        assert r.state == ReleaseState.PUBLIC_SAFE
        assert t.from_state == ReleaseState.CANDIDATE
        assert t.to_state == ReleaseState.PUBLIC_SAFE

    def test_full_release_path(self):
        r = _candidate()
        r.transition(ReleaseState.PUBLIC_SAFE, reason="rights cleared")
        r.transition(ReleaseState.RELEASED, reason="operator approved")
        assert r.state == ReleaseState.RELEASED
        assert len(r.transitions) == 2

    def test_release_to_sold(self):
        r = _candidate()
        r.transition(ReleaseState.PUBLIC_SAFE, reason="cleared")
        r.transition(ReleaseState.RELEASED, reason="approved")
        r.transition(ReleaseState.SOLD, reason="stripe payment received")
        assert r.state == ReleaseState.SOLD
        assert r.is_terminal

    def test_invalid_transition_raises(self):
        r = _candidate()
        with pytest.raises(InvalidTransitionError):
            r.transition(ReleaseState.RELEASED, reason="skip steps")

    def test_candidate_to_refused(self):
        r = _candidate()
        t = r.transition(
            ReleaseState.REFUSED,
            reason="no provenance",
            refusal_reason="missing_provenance",
        )
        assert r.state == ReleaseState.REFUSED
        assert t.refusal_reason == "missing_provenance"
        assert r.is_terminal

    def test_refusal_requires_reason(self):
        r = _candidate()
        with pytest.raises(InvalidTransitionError, match="refusal_reason"):
            r.transition(ReleaseState.REFUSED, reason="bad")

    def test_release_requires_public_event_refs(self):
        r = ArtifactReleaseRecord(artifact_id="art-002")
        r.transition(ReleaseState.PUBLIC_SAFE, reason="cleared")
        with pytest.raises(InvalidTransitionError, match="public_event_refs"):
            r.transition(ReleaseState.RELEASED, reason="approved")

    def test_withdrawn_is_terminal(self):
        r = _candidate()
        r.transition(ReleaseState.HELD, reason="under review")
        r.transition(ReleaseState.WITHDRAWN, reason="operator withdrew")
        assert r.is_terminal
        with pytest.raises(InvalidTransitionError):
            r.transition(ReleaseState.CANDIDATE, reason="reopen")


class TestRefusalStates:
    @pytest.mark.parametrize(
        "refusal_reason",
        [
            "missing_provenance",
            "private_data",
            "rights_risk",
            "overclaiming",
            "manual_labor_obligation",
            "consent_missing",
            "monetization_unready",
        ],
    )
    def test_all_refusal_reasons_accepted(self, refusal_reason):
        r = _candidate()
        r.transition(
            ReleaseState.REFUSED,
            reason=f"refused: {refusal_reason}",
            refusal_reason=refusal_reason,
        )
        assert r.state == ReleaseState.REFUSED

    def test_blocked_reasons_tracked(self):
        r = _candidate()
        r.transition(ReleaseState.BLOCKED, reason="rights unclear")
        assert r.blocked_reasons == ["rights unclear"]


class TestTransitionGraph:
    def test_all_states_have_transitions(self):
        for state in ReleaseState:
            assert state in VALID_TRANSITIONS

    def test_terminal_states_defined(self):
        assert ReleaseState.RELEASED in TERMINAL_STATES
        assert ReleaseState.REFUSED in TERMINAL_STATES
        assert ReleaseState.WITHDRAWN in TERMINAL_STATES
        assert ReleaseState.CANDIDATE not in TERMINAL_STATES

    def test_withdrawn_has_no_outgoing(self):
        assert len(VALID_TRANSITIONS[ReleaseState.WITHDRAWN]) == 0

    def test_refused_has_no_outgoing(self):
        assert len(VALID_TRANSITIONS[ReleaseState.REFUSED]) == 0


class TestMetrics:
    def test_metrics_from_records(self):
        records = [_candidate() for _ in range(5)]
        records[0].transition(ReleaseState.PUBLIC_SAFE, reason="cleared")
        records[0].transition(ReleaseState.RELEASED, reason="approved")
        records[1].transition(
            ReleaseState.REFUSED,
            reason="no provenance",
            refusal_reason="missing_provenance",
        )
        records[2].transition(
            ReleaseState.REFUSED,
            reason="private",
            refusal_reason="private_data",
        )

        m = ReleaseMetrics.from_records(records)
        assert m.total == 5
        assert m.by_state["released"] == 1
        assert m.by_state["refused"] == 2
        assert m.by_state["candidate"] == 2
        assert m.by_refusal_reason["missing_provenance"] == 1
        assert m.by_refusal_reason["private_data"] == 1
        assert m.conversion_funnel["public_safe->released"] == 1

    def test_empty_metrics(self):
        m = ReleaseMetrics.from_records([])
        assert m.total == 0
        assert m.by_state == {}


class TestEvidenceTracking:
    def test_transition_records_evidence(self):
        r = _candidate()
        t = r.transition(
            ReleaseState.PUBLIC_SAFE,
            reason="cleared",
            evidence_refs=["rights:check-001", "privacy:screen-002"],
        )
        assert len(t.evidence_refs) == 2
        assert "rights:check-001" in t.evidence_refs

    def test_transition_timestamps_present(self):
        r = _candidate()
        t = r.transition(ReleaseState.HELD, reason="review")
        assert t.transitioned_at
        assert "T" in t.transitioned_at
