"""Unified awareness route/claim envelope tests.

Validates:
1. Private default route with no broadcast intent
2. Public speech requires all gates
3. Private risk flags block all public outcomes
4. Blocked apertures produce refusal
5. Archive-only apertures produce no_claim
6. Compact prompt block derivation
7. Autonomous narration can be private while public remains blocked
8. Public speech cannot have blockers or private risk
"""

from __future__ import annotations

import pytest

from shared.self_grounding_envelope import (
    AllowedOutcome,
    ApertureSnapshot,
    AudioSafetySnapshot,
    AudioSafetyState,
    EgressSnapshot,
    EnvelopeInputs,
    LivestreamEgressState,
    ProgrammeAuthorizationState,
    ProgrammeSnapshot,
    RoleSnapshot,
    RouteDecision,
    SelfPresenceEnvelopeProjection,
    build_envelope_projection,
    render_compact_prompt_block,
)
from shared.self_presence import (
    AuthorityCeiling,
    ExposureMode,
    PublicPrivateMode,
)

# ---- Fixtures ----


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


def _archive_aperture() -> ApertureSnapshot:
    return ApertureSnapshot(
        aperture_id="aperture:archive-window",
        kind="archive_window",
        exposure_mode=ExposureMode.ARCHIVE_ONLY,
        public_private_mode=PublicPrivateMode.ARCHIVE,
        requires_programme_authorization=False,
        requires_audio_safety=False,
        requires_egress_witness=True,
    )


def _fresh_programme() -> ProgrammeSnapshot:
    return ProgrammeSnapshot(
        programme_id="prog:test-001",
        authorization_state=ProgrammeAuthorizationState.FRESH,
        authorized_at="2026-04-30T16:00:00Z",
        expires_at="2026-04-30T17:00:00Z",
    )


def _safe_audio() -> AudioSafetySnapshot:
    return AudioSafetySnapshot(
        state=AudioSafetyState.SAFE,
        evidence_refs=("audio-health:broadcast-safe",),
    )


def _witnessed_egress() -> EgressSnapshot:
    return EgressSnapshot(
        state=LivestreamEgressState.WITNESSED,
        evidence_refs=("egress:obs-streaming",),
    )


# ---- Tests ----


def test_private_default_route() -> None:
    """Private aperture always routes to private."""

    inputs = EnvelopeInputs(
        role=_private_role(),
        aperture=_private_aperture(),
    )
    proj = build_envelope_projection(inputs)

    assert proj.route_decision is RouteDecision.PRIVATE
    assert AllowedOutcome.PRIVATE_ANSWER in proj.allowed_outcomes
    assert AllowedOutcome.PUBLIC_SPEECH_ALLOWED not in proj.allowed_outcomes


def test_public_speech_all_gates_pass() -> None:
    """Public speech requires all gates: programme + audio + egress."""

    inputs = EnvelopeInputs(
        role=_public_role(),
        aperture=_public_aperture(),
        programme=_fresh_programme(),
        audio_safety=_safe_audio(),
        egress=_witnessed_egress(),
    )
    proj = build_envelope_projection(inputs)

    assert proj.route_decision is RouteDecision.BROADCAST
    assert proj.programme_id == "prog:test-001"
    assert AllowedOutcome.PUBLIC_SPEECH_ALLOWED in proj.allowed_outcomes
    assert AllowedOutcome.PRIVATE_ANSWER in proj.allowed_outcomes
    assert not proj.blockers


def test_missing_programme_blocks_public() -> None:
    """Missing programme authorization blocks public speech."""

    inputs = EnvelopeInputs(
        role=_public_role(),
        aperture=_public_aperture(),
        audio_safety=_safe_audio(),
        egress=_witnessed_egress(),
    )
    proj = build_envelope_projection(inputs)

    assert proj.route_decision is RouteDecision.PRIVATE
    assert AllowedOutcome.PUBLIC_SPEECH_ALLOWED not in proj.allowed_outcomes
    assert "programme_authorization_missing" in proj.blockers


def test_unsafe_audio_blocks_public() -> None:
    """Unsafe audio blocks public speech."""

    inputs = EnvelopeInputs(
        role=_public_role(),
        aperture=_public_aperture(),
        programme=_fresh_programme(),
        audio_safety=AudioSafetySnapshot(state=AudioSafetyState.UNSAFE),
        egress=_witnessed_egress(),
    )
    proj = build_envelope_projection(inputs)

    assert proj.route_decision is RouteDecision.PRIVATE
    assert AllowedOutcome.PUBLIC_SPEECH_ALLOWED not in proj.allowed_outcomes
    assert "audio_safety_unsafe" in proj.blockers


def test_missing_egress_blocks_public() -> None:
    """Missing egress witness blocks public speech."""

    inputs = EnvelopeInputs(
        role=_public_role(),
        aperture=_public_aperture(),
        programme=_fresh_programme(),
        audio_safety=_safe_audio(),
    )
    proj = build_envelope_projection(inputs)

    assert proj.route_decision is RouteDecision.PRIVATE
    assert AllowedOutcome.PUBLIC_SPEECH_ALLOWED not in proj.allowed_outcomes
    assert "egress_not_applicable" in proj.blockers


def test_private_risk_blocks_everything_public() -> None:
    """Private risk flags block all public outcomes even with all gates."""

    inputs = EnvelopeInputs(
        role=_public_role(),
        aperture=_public_aperture(),
        programme=_fresh_programme(),
        audio_safety=_safe_audio(),
        egress=_witnessed_egress(),
        private_risk_flags=("operator_private_context",),
    )
    proj = build_envelope_projection(inputs)

    assert proj.route_decision is RouteDecision.PRIVATE
    assert AllowedOutcome.PUBLIC_SPEECH_ALLOWED not in proj.allowed_outcomes
    assert "private_risk_context" in proj.blockers
    assert proj.public_claim_ceiling is AuthorityCeiling.NO_CLAIM


def test_blocked_aperture_produces_refusal() -> None:
    """Blocked apertures produce a refusal outcome."""

    inputs = EnvelopeInputs(
        role=_private_role(),
        aperture=_blocked_aperture(),
    )
    proj = build_envelope_projection(inputs)

    assert proj.route_decision is RouteDecision.BLOCKED
    assert AllowedOutcome.REFUSAL in proj.allowed_outcomes
    assert AllowedOutcome.PRIVATE_ANSWER not in proj.allowed_outcomes


def test_archive_aperture_no_claim() -> None:
    """Archive-only apertures produce no_claim and archive route."""

    inputs = EnvelopeInputs(
        role=_private_role(),
        aperture=_archive_aperture(),
    )
    proj = build_envelope_projection(inputs)

    assert proj.route_decision is RouteDecision.ARCHIVE_ONLY
    assert AllowedOutcome.NO_CLAIM in proj.allowed_outcomes
    assert proj.public_claim_ceiling is AuthorityCeiling.LAST_OBSERVED_ONLY


def test_public_blocked_gives_dry_run() -> None:
    """Public aperture with blockers gives dry_run outcome."""

    inputs = EnvelopeInputs(
        role=_public_role(),
        aperture=_public_aperture(),
        # No programme, audio, or egress → blocked
    )
    proj = build_envelope_projection(inputs)

    assert proj.route_decision is RouteDecision.PRIVATE
    assert AllowedOutcome.DRY_RUN in proj.allowed_outcomes
    assert AllowedOutcome.PUBLIC_SPEECH_ALLOWED not in proj.allowed_outcomes


def test_autonomous_narration_private_while_public_blocked() -> None:
    """Autonomous narration routes privately when public broadcast is blocked.

    This is the acceptance test for the documented gap: autonomous narration
    emits to private because broadcast intent is absent.
    """

    # Simulate autonomous narration context: private role, but targeting
    # broadcast aperture without programme authorization
    inputs = EnvelopeInputs(
        role=RoleSnapshot(
            role_id="role:autonomous-narrator",
            office="public_narrator",
            addressee_mode="public_audience",
            route_posture="private_default",
        ),
        aperture=_public_aperture(),
        # No programme, no audio, no egress
    )
    proj = build_envelope_projection(inputs)

    assert proj.route_decision is RouteDecision.PRIVATE
    assert AllowedOutcome.PRIVATE_ANSWER in proj.allowed_outcomes
    assert AllowedOutcome.PUBLIC_SPEECH_ALLOWED not in proj.allowed_outcomes
    assert len(proj.blockers) >= 1


def test_compact_prompt_block_private() -> None:
    """Compact prompt block renders correctly for private route."""

    inputs = EnvelopeInputs(
        role=_private_role(),
        aperture=_private_aperture(),
    )
    proj = build_envelope_projection(inputs)
    block = render_compact_prompt_block(proj)

    assert "[Self-Grounding State]" in block
    assert "Role: private_assistant" in block
    assert "Route: private" in block
    assert "Claim ceiling: no_claim" in block


def test_compact_prompt_block_public() -> None:
    """Compact prompt block renders correctly for broadcast route."""

    inputs = EnvelopeInputs(
        role=_public_role(),
        aperture=_public_aperture(),
        programme=_fresh_programme(),
        audio_safety=_safe_audio(),
        egress=_witnessed_egress(),
    )
    proj = build_envelope_projection(inputs)
    block = render_compact_prompt_block(proj)

    assert "Route: broadcast" in block
    assert "public_speech_allowed" in block
    assert "Programme auth: fresh" in block
    assert "Audio safety: safe" in block
    assert "Blockers" not in block  # No blockers


def test_compact_prompt_block_blocked_shows_blockers() -> None:
    """Compact prompt block shows blockers when present."""

    inputs = EnvelopeInputs(
        role=_public_role(),
        aperture=_public_aperture(),
        # Missing everything → multiple blockers
    )
    proj = build_envelope_projection(inputs)
    block = render_compact_prompt_block(proj)

    assert "Blockers:" in block
    assert "programme_authorization_missing" in block


def test_model_validator_rejects_inconsistent_public_speech() -> None:
    """Pydantic model validator catches inconsistent public speech state."""

    with pytest.raises(Exception, match="public_speech_allowed requires broadcast route"):
        SelfPresenceEnvelopeProjection(
            role=_public_role(),
            aperture=_public_aperture(),
            route_decision=RouteDecision.PRIVATE,  # Inconsistent
            programme_authorization=ProgrammeAuthorizationState.FRESH,
            audio_safety=AudioSafetyState.SAFE,
            livestream_egress_state=LivestreamEgressState.WITNESSED,
            consent_privacy_ceiling=AuthorityCeiling.EVIDENCE_BOUND,
            rights_provenance_ceiling=AuthorityCeiling.EVIDENCE_BOUND,
            public_claim_ceiling=AuthorityCeiling.PUBLIC_GATE_REQUIRED,
            allowed_outcomes=(AllowedOutcome.PUBLIC_SPEECH_ALLOWED,),
        )


def test_model_validator_rejects_public_speech_without_programme_id() -> None:
    """Fresh programme auth without a programme id cannot authorize public speech."""

    with pytest.raises(Exception, match="public_speech_allowed requires programme_id"):
        SelfPresenceEnvelopeProjection(
            role=_public_role(),
            aperture=_public_aperture(),
            route_decision=RouteDecision.BROADCAST,
            programme_authorization=ProgrammeAuthorizationState.FRESH,
            audio_safety=AudioSafetyState.SAFE,
            livestream_egress_state=LivestreamEgressState.WITNESSED,
            consent_privacy_ceiling=AuthorityCeiling.EVIDENCE_BOUND,
            rights_provenance_ceiling=AuthorityCeiling.EVIDENCE_BOUND,
            public_claim_ceiling=AuthorityCeiling.PUBLIC_GATE_REQUIRED,
            allowed_outcomes=(AllowedOutcome.PUBLIC_SPEECH_ALLOWED,),
        )


def test_evidence_refs_propagate() -> None:
    """Evidence refs from inputs propagate into the projection."""

    inputs = EnvelopeInputs(
        role=_private_role(),
        aperture=_private_aperture(),
        source_context_refs=("ctx:test",),
        wcs_snapshot_refs=("wcs:snapshot-1",),
        chronicle_refs=("chronicle:event-1",),
        triad_refs=("triad:obs-1",),
    )
    proj = build_envelope_projection(inputs)

    assert "ctx:test" in proj.source_context_refs
    assert "wcs:snapshot-1" in proj.wcs_snapshot_refs
    assert "chronicle:event-1" in proj.chronicle_refs
    assert "triad:obs-1" in proj.triad_refs
