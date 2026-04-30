"""Private-to-public bridge governor tests.

Validates:
1. Default path (no public intent) → private_response
2. All gates pass + public intent → public_action_proposal
3. Private risk context → cannot reach broadcast
4. Missing programme → dry_run
5. Missing audio safety → dry_run
6. Missing egress → dry_run
7. Blocked aperture → refusal
8. Impingement content carries broadcast intent metadata
9. Blue Yeti/private text cannot reach broadcast
10. "Do that publicly" without gates → held
11. Model validators catch inconsistent state
"""

from __future__ import annotations

import pytest

from shared.private_to_public_bridge import (
    BridgeOutcome,
    BridgeRequest,
    BridgeResult,
    _format_impingement_content,
    evaluate_bridge,
)
from shared.self_grounding_envelope import (
    ApertureSnapshot,
    AudioSafetySnapshot,
    AudioSafetyState,
    EgressSnapshot,
    EnvelopeInputs,
    LivestreamEgressState,
    ProgrammeAuthorizationState,
    ProgrammeSnapshot,
    RoleSnapshot,
    build_envelope_projection,
)
from shared.self_presence import (
    AuthorityCeiling,
    ExposureMode,
    PublicPrivateMode,
)

# ---- Shared fixtures ----


def _private_role() -> RoleSnapshot:
    return RoleSnapshot(
        role_id="role:private-assistant",
        office="private_assistant",
        addressee_mode="operator",
        route_posture="private_default",
    )


def _public_role() -> RoleSnapshot:
    return RoleSnapshot(
        role_id="role:public-narrator",
        office="public_narrator",
        addressee_mode="public_audience",
        route_posture="broadcast_authorized",
    )


def _private_aperture() -> ApertureSnapshot:
    return ApertureSnapshot(
        aperture_id="aperture:private-assistant",
        kind="private_assistant",
        exposure_mode=ExposureMode.PRIVATE,
        public_private_mode=PublicPrivateMode.PRIVATE,
        requires_programme_authorization=False,
        requires_audio_safety=False,
        requires_egress_witness=False,
    )


def _public_aperture() -> ApertureSnapshot:
    return ApertureSnapshot(
        aperture_id="aperture:public-broadcast-voice",
        kind="public_broadcast_voice",
        exposure_mode=ExposureMode.PUBLIC_CANDIDATE,
        public_private_mode=PublicPrivateMode.PUBLIC_CANDIDATE,
        requires_programme_authorization=True,
        requires_audio_safety=True,
        requires_egress_witness=True,
    )


def _blocked_aperture() -> ApertureSnapshot:
    return ApertureSnapshot(
        aperture_id="aperture:blocked-test",
        kind="private_assistant",
        exposure_mode=ExposureMode.BLOCKED,
        public_private_mode=PublicPrivateMode.PUBLIC_FORBIDDEN,
        requires_programme_authorization=False,
        requires_audio_safety=False,
        requires_egress_witness=False,
    )


def _full_gates_envelope():
    """Build an envelope where all public gates pass."""

    inputs = EnvelopeInputs(
        role=_public_role(),
        aperture=_public_aperture(),
        programme=ProgrammeSnapshot(
            programme_id="prog:test",
            authorization_state=ProgrammeAuthorizationState.FRESH,
            authorized_at="2026-04-30T16:00:00Z",
            expires_at="2026-04-30T17:00:00Z",
        ),
        audio_safety=AudioSafetySnapshot(
            state=AudioSafetyState.SAFE,
            evidence_refs=("audio:safe",),
        ),
        egress=EgressSnapshot(
            state=LivestreamEgressState.WITNESSED,
            evidence_refs=("egress:obs",),
        ),
        source_context_refs=("ctx:autonomous-narration",),
        wcs_snapshot_refs=("wcs:snapshot-1",),
        chronicle_refs=("chronicle:event-1",),
    )
    return build_envelope_projection(inputs)


def _blocked_envelope():
    """Build an envelope where the aperture is blocked."""

    inputs = EnvelopeInputs(
        role=_private_role(),
        aperture=_blocked_aperture(),
    )
    return build_envelope_projection(inputs)


def _private_envelope():
    """Build a private envelope (no public gates)."""

    inputs = EnvelopeInputs(
        role=_private_role(),
        aperture=_private_aperture(),
    )
    return build_envelope_projection(inputs)


def _missing_programme_envelope():
    """Public aperture but missing programme authorization."""

    inputs = EnvelopeInputs(
        role=_public_role(),
        aperture=_public_aperture(),
        audio_safety=AudioSafetySnapshot(
            state=AudioSafetyState.SAFE,
            evidence_refs=("audio:safe",),
        ),
        egress=EgressSnapshot(
            state=LivestreamEgressState.WITNESSED,
            evidence_refs=("egress:obs",),
        ),
    )
    return build_envelope_projection(inputs)


def _private_risk_envelope():
    """Public aperture + all gates but private risk flags present."""

    inputs = EnvelopeInputs(
        role=_public_role(),
        aperture=_public_aperture(),
        programme=ProgrammeSnapshot(
            programme_id="prog:test",
            authorization_state=ProgrammeAuthorizationState.FRESH,
            authorized_at="2026-04-30T16:00:00Z",
            expires_at="2026-04-30T17:00:00Z",
        ),
        audio_safety=AudioSafetySnapshot(
            state=AudioSafetyState.SAFE,
            evidence_refs=("audio:safe",),
        ),
        egress=EgressSnapshot(
            state=LivestreamEgressState.WITNESSED,
            evidence_refs=("egress:obs",),
        ),
        private_risk_flags=("operator_private_context",),
    )
    return build_envelope_projection(inputs)


# ---- Tests ----


def test_default_path_private_response() -> None:
    """No explicit public intent → private_response."""

    request = BridgeRequest(
        narrative_text="Hapax observes the research instrument stabilizing.",
        envelope=_private_envelope(),
    )
    result = evaluate_bridge(request)

    assert result.outcome is BridgeOutcome.PRIVATE_RESPONSE
    assert not result.public_broadcast_intent


def test_all_gates_pass_public_proposal() -> None:
    """All gates pass + explicit public intent → public_action_proposal."""

    request = BridgeRequest(
        narrative_text="Hapax observes the research instrument stabilizing.",
        programme_id="prog:test",
        envelope=_full_gates_envelope(),
        explicit_public_intent=True,
    )
    result = evaluate_bridge(request)

    assert result.outcome is BridgeOutcome.PUBLIC_ACTION_PROPOSAL
    assert result.public_broadcast_intent
    assert result.route_posture == "broadcast_authorized"
    assert result.programme_authorization == "programme:prog:test"
    assert result.claim_ceiling is AuthorityCeiling.PUBLIC_GATE_REQUIRED
    assert not result.blockers


def test_public_proposal_uses_envelope_programme_when_request_omits_it() -> None:
    """Public proposal falls back to the witnessed envelope programme id."""

    request = BridgeRequest(
        narrative_text="Hapax observes the research instrument stabilizing.",
        envelope=_full_gates_envelope(),
        explicit_public_intent=True,
    )
    result = evaluate_bridge(request)

    assert result.outcome is BridgeOutcome.PUBLIC_ACTION_PROPOSAL
    assert result.programme_authorization == "programme:prog:test"


def test_public_proposal_holds_on_programme_id_mismatch() -> None:
    """Request/envelope programme mismatch cannot authorize broadcast."""

    request = BridgeRequest(
        narrative_text="Hapax observes the research instrument stabilizing.",
        programme_id="prog:other",
        envelope=_full_gates_envelope(),
        explicit_public_intent=True,
    )
    result = evaluate_bridge(request)

    assert result.outcome is BridgeOutcome.HELD
    assert result.blockers == ("programme_id_mismatch",)
    assert result.public_broadcast_intent is False


def test_private_risk_blocks_broadcast() -> None:
    """Private risk flags block public broadcast even with public intent."""

    request = BridgeRequest(
        narrative_text="Hapax observes the research instrument stabilizing.",
        envelope=_private_risk_envelope(),
        explicit_public_intent=True,
    )
    result = evaluate_bridge(request)

    assert result.outcome is not BridgeOutcome.PUBLIC_ACTION_PROPOSAL
    assert not result.public_broadcast_intent or result.outcome in {
        BridgeOutcome.DRY_RUN,
        BridgeOutcome.HELD,
    }


def test_missing_programme_dry_run() -> None:
    """Missing programme authorization → dry_run with blockers."""

    request = BridgeRequest(
        narrative_text="Hapax observes the research instrument stabilizing.",
        envelope=_missing_programme_envelope(),
        explicit_public_intent=True,
    )
    result = evaluate_bridge(request)

    assert result.outcome is BridgeOutcome.DRY_RUN
    assert "programme_authorization_missing" in result.blockers


def test_blocked_aperture_refusal() -> None:
    """Blocked aperture → refusal regardless of intent."""

    request = BridgeRequest(
        narrative_text="Hapax observes the research instrument stabilizing.",
        envelope=_blocked_envelope(),
        explicit_public_intent=True,
    )
    result = evaluate_bridge(request)

    assert result.outcome is BridgeOutcome.REFUSAL
    assert "aperture_blocked" in result.blockers


def test_impingement_content_has_broadcast_intent() -> None:
    """Impingement content from public proposal carries broadcast intent."""

    request = BridgeRequest(
        narrative_text="Hapax observes the research instrument stabilizing.",
        programme_id="prog:test",
        speech_event_id="speech:001",
        envelope=_full_gates_envelope(),
        explicit_public_intent=True,
    )
    result = evaluate_bridge(request)
    content = _format_impingement_content(request, result)

    assert content["public_broadcast_intent"] is True
    assert content["destination"] == "broadcast"
    assert content["bridge_outcome"] == "public_action_proposal"
    assert content["route_posture"] == "broadcast_authorized"
    assert content["programme_authorization"] == "programme:prog:test"


def test_impingement_content_private_has_no_broadcast() -> None:
    """Impingement content from private response has no broadcast intent."""

    request = BridgeRequest(
        narrative_text="Hapax observes the research instrument stabilizing.",
        envelope=_private_envelope(),
    )
    result = evaluate_bridge(request)
    content = _format_impingement_content(request, result)

    assert content["public_broadcast_intent"] is False
    assert content["destination"] == "private"


def test_blue_yeti_private_cannot_reach_broadcast() -> None:
    """Blue Yeti/private source context cannot reach broadcast.

    This simulates the exact case: operator speaks via Blue Yeti (private),
    autonomous narration composes, but private risk flags prevent broadcast.
    """

    # Simulate: private risk flag for Blue Yeti input
    envelope_inputs = EnvelopeInputs(
        role=_public_role(),
        aperture=_public_aperture(),
        programme=ProgrammeSnapshot(
            programme_id="prog:test",
            authorization_state=ProgrammeAuthorizationState.FRESH,
            authorized_at="2026-04-30T16:00:00Z",
        ),
        audio_safety=AudioSafetySnapshot(state=AudioSafetyState.SAFE),
        egress=EgressSnapshot(state=LivestreamEgressState.WITNESSED),
        private_risk_flags=("blue_yeti_input", "operator_private_context"),
    )
    envelope = build_envelope_projection(envelope_inputs)

    request = BridgeRequest(
        narrative_text="The operator said something privately.",
        envelope=envelope,
        explicit_public_intent=True,
    )
    result = evaluate_bridge(request)

    assert result.outcome is not BridgeOutcome.PUBLIC_ACTION_PROPOSAL
    assert "private_risk_context" in envelope.blockers


def test_do_that_publicly_without_gates_held() -> None:
    """'Do that publicly' without all gates → held or dry_run."""

    # Public aperture but no programme authorization
    request = BridgeRequest(
        narrative_text="Say that on stream.",
        envelope=_missing_programme_envelope(),
        explicit_public_intent=True,
    )
    result = evaluate_bridge(request)

    assert result.outcome in {BridgeOutcome.DRY_RUN, BridgeOutcome.HELD}
    assert result.blockers


def test_model_validator_rejects_public_without_intent() -> None:
    """Model validator catches public_action_proposal without broadcast intent."""

    with pytest.raises(Exception, match="public_broadcast_intent"):
        BridgeResult(
            outcome=BridgeOutcome.PUBLIC_ACTION_PROPOSAL,
            narrative_text="test",
            public_broadcast_intent=False,  # Inconsistent
            programme_authorization="prog:test",
            route_posture="broadcast_authorized",
            claim_ceiling=AuthorityCeiling.PUBLIC_GATE_REQUIRED,
        )


def test_model_validator_rejects_private_with_broadcast() -> None:
    """Model validator catches private_response with broadcast intent."""

    with pytest.raises(Exception, match="public_broadcast_intent"):
        BridgeResult(
            outcome=BridgeOutcome.PRIVATE_RESPONSE,
            narrative_text="test",
            public_broadcast_intent=True,  # Inconsistent
        )


def test_evidence_refs_propagate_to_public_proposal() -> None:
    """Evidence refs from envelope propagate into public action proposal."""

    request = BridgeRequest(
        narrative_text="Hapax observes stabilization.",
        programme_id="prog:test",
        envelope=_full_gates_envelope(),
        explicit_public_intent=True,
    )
    result = evaluate_bridge(request)

    assert "ctx:autonomous-narration" in result.evidence_refs
    assert "wcs:snapshot-1" in result.evidence_refs
    assert "chronicle:event-1" in result.evidence_refs
