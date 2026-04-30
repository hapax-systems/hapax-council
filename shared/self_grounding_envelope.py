"""Unified awareness route and claim envelope builder.

This module provides ``build_envelope_projection()`` — a pure function that
projects runtime state into a ``SelfPresenceEnvelopeProjection``.  The
projection carries the route decision, claim ceilings, blocker list, and
allowed outcomes that downstream consumers (prompt, emit, bridge governor)
inspect before answering, speaking, acting, or claiming.

The projection is a contract surface, not a runtime router. It does not
perform I/O.  Callers supply runtime snapshots as ``EnvelopeInputs``.

The ``render_compact_prompt_block()`` function produces a small, structured
text block for LLM prompt injection, replacing ad-hoc seed construction in
``compose.py``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.self_presence import (
    AuthorityCeiling,
    ExposureMode,
    PublicPrivateMode,
)

# ---- Enums ----


class RouteDecision(StrEnum):
    """Route decision for a given turn."""

    PRIVATE = "private"
    BROADCAST = "broadcast"
    HELD = "held"
    BLOCKED = "blocked"
    ARCHIVE_ONLY = "archive_only"


class ProgrammeAuthorizationState(StrEnum):
    """Whether programme authorization is present and fresh."""

    FRESH = "fresh"
    MISSING = "missing"
    EXPIRED = "expired"
    NOT_REQUIRED = "not_required"


class AudioSafetyState(StrEnum):
    """Audio safety gate state."""

    SAFE = "safe"
    UNSAFE = "unsafe"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class LivestreamEgressState(StrEnum):
    """Whether egress to livestream is witnessed."""

    WITNESSED = "witnessed"
    NOT_WITNESSED = "not_witnessed"
    NOT_APPLICABLE = "not_applicable"


class AllowedOutcome(StrEnum):
    """What the system can do from this aperture right now."""

    PRIVATE_ANSWER = "private_answer"
    PUBLIC_SPEECH_ALLOWED = "public_speech_allowed"
    PUBLIC_ACTION_PROPOSAL = "public_action_proposal"
    DRY_RUN = "dry_run"
    HELD = "held"
    REFUSAL = "refusal"
    CORRECTION = "correction"
    NO_CLAIM = "no_claim"
    UNKNOWN = "unknown"


# ---- Input types ----


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RoleSnapshot(FrozenModel):
    """Snapshot of the active role state."""

    role_id: str = Field(pattern=r"^role:[a-z0-9_.:-]+$")
    office: str = Field(min_length=1)
    addressee_mode: str = Field(min_length=1)
    route_posture: str = Field(min_length=1)


class ApertureSnapshot(FrozenModel):
    """Snapshot of the target aperture from the registry."""

    aperture_id: str = Field(pattern=r"^aperture:[a-z0-9_.:-]+$")
    kind: str = Field(min_length=1)
    exposure_mode: ExposureMode
    public_private_mode: PublicPrivateMode
    requires_programme_authorization: bool
    requires_audio_safety: bool
    requires_egress_witness: bool


class ProgrammeSnapshot(FrozenModel):
    """Snapshot of the programme authorization state."""

    programme_id: str | None = None
    authorization_state: ProgrammeAuthorizationState = ProgrammeAuthorizationState.MISSING
    authorized_at: str | None = None
    expires_at: str | None = None


class AudioSafetySnapshot(FrozenModel):
    """Snapshot of broadcast audio safety."""

    state: AudioSafetyState = AudioSafetyState.UNKNOWN
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)


class EgressSnapshot(FrozenModel):
    """Snapshot of livestream egress state."""

    state: LivestreamEgressState = LivestreamEgressState.NOT_APPLICABLE
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)


class EnvelopeInputs(FrozenModel):
    """All runtime inputs for building a SelfPresenceEnvelopeProjection.

    Callers construct this from their I/O reads, then pass it to
    ``build_envelope_projection()`` as a pure function call.
    """

    role: RoleSnapshot
    aperture: ApertureSnapshot
    programme: ProgrammeSnapshot = Field(default_factory=lambda: ProgrammeSnapshot())
    audio_safety: AudioSafetySnapshot = Field(default_factory=lambda: AudioSafetySnapshot())
    egress: EgressSnapshot = Field(default_factory=lambda: EgressSnapshot())
    source_context_refs: tuple[str, ...] = Field(default_factory=tuple)
    private_risk_flags: tuple[str, ...] = Field(default_factory=tuple)
    wcs_snapshot_refs: tuple[str, ...] = Field(default_factory=tuple)
    temporal_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    chronicle_refs: tuple[str, ...] = Field(default_factory=tuple)
    triad_refs: tuple[str, ...] = Field(default_factory=tuple)
    claim_ceiling_override: AuthorityCeiling | None = None


# ---- Output type ----


class SelfPresenceEnvelopeProjection(FrozenModel):
    """Envelope projection: the canonical per-turn answer to
    "what can Hapax know, say, do, and claim from this aperture right now?"

    This is consumed by prompt builders, emit functions, and the bridge
    governor.
    """

    schema_version: Literal[1] = 1

    # Role and aperture
    role: RoleSnapshot
    aperture: ApertureSnapshot

    # Route decision
    route_decision: RouteDecision
    programme_id: str | None = None
    programme_authorization: ProgrammeAuthorizationState
    programme_authorized_at: str | None = None
    programme_expires_at: str | None = None
    audio_safety: AudioSafetyState
    livestream_egress_state: LivestreamEgressState

    # Evidence refs
    source_context_refs: tuple[str, ...] = Field(default_factory=tuple)
    private_risk_flags: tuple[str, ...] = Field(default_factory=tuple)
    wcs_snapshot_refs: tuple[str, ...] = Field(default_factory=tuple)
    temporal_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    chronicle_refs: tuple[str, ...] = Field(default_factory=tuple)
    triad_refs: tuple[str, ...] = Field(default_factory=tuple)

    # Ceilings
    consent_privacy_ceiling: AuthorityCeiling
    rights_provenance_ceiling: AuthorityCeiling
    public_claim_ceiling: AuthorityCeiling

    # Blockers and outcomes
    blockers: tuple[str, ...] = Field(default_factory=tuple)
    allowed_outcomes: tuple[AllowedOutcome, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _fail_closed_public_speech(self) -> Self:
        if AllowedOutcome.PUBLIC_SPEECH_ALLOWED in self.allowed_outcomes:
            if self.route_decision is not RouteDecision.BROADCAST:
                raise ValueError("public_speech_allowed requires broadcast route")
            if self.programme_authorization is not ProgrammeAuthorizationState.FRESH:
                raise ValueError("public_speech_allowed requires fresh programme authorization")
            if not self.programme_id:
                raise ValueError("public_speech_allowed requires programme_id")
            if not self.programme_authorized_at:
                raise ValueError("public_speech_allowed requires programme authorization timestamp")
            if self.audio_safety is not AudioSafetyState.SAFE:
                raise ValueError("public_speech_allowed requires safe audio")
            if self.livestream_egress_state is not LivestreamEgressState.WITNESSED:
                raise ValueError("public_speech_allowed requires witnessed egress")
            if self.public_claim_ceiling is not AuthorityCeiling.PUBLIC_GATE_REQUIRED:
                raise ValueError("public_speech_allowed requires public_gate_required ceiling")
            if self.blockers:
                raise ValueError("public_speech_allowed cannot have blockers")
            if self.private_risk_flags:
                raise ValueError("public_speech_allowed cannot have private risk flags")
        return self


# ---- Builder ----


def _compute_blockers(inputs: EnvelopeInputs) -> tuple[str, ...]:
    """Determine the list of blockers preventing public speech."""

    blockers: list[str] = []

    if inputs.private_risk_flags:
        blockers.append("private_risk_context")

    if inputs.aperture.exposure_mode in {ExposureMode.PRIVATE, ExposureMode.SYNTHETIC_ONLY}:
        blockers.append("aperture_is_private")

    if inputs.aperture.exposure_mode is ExposureMode.BLOCKED:
        blockers.append("aperture_is_blocked")

    if inputs.aperture.requires_programme_authorization:
        if inputs.programme.authorization_state is not ProgrammeAuthorizationState.FRESH:
            blockers.append(f"programme_authorization_{inputs.programme.authorization_state.value}")
        elif not inputs.programme.programme_id:
            blockers.append("programme_authorization_programme_id_missing")
        elif not inputs.programme.authorized_at:
            blockers.append("programme_authorization_timestamp_missing")

    if inputs.aperture.requires_audio_safety:
        if inputs.audio_safety.state is not AudioSafetyState.SAFE:
            blockers.append(f"audio_safety_{inputs.audio_safety.state.value}")

    if inputs.aperture.requires_egress_witness:
        if inputs.egress.state is not LivestreamEgressState.WITNESSED:
            blockers.append(f"egress_{inputs.egress.state.value}")

    return tuple(blockers)


def _compute_route_decision(inputs: EnvelopeInputs, blockers: tuple[str, ...]) -> RouteDecision:
    """Determine the route decision from inputs and blockers."""

    if inputs.aperture.exposure_mode is ExposureMode.BLOCKED:
        return RouteDecision.BLOCKED

    if inputs.aperture.exposure_mode is ExposureMode.ARCHIVE_ONLY:
        return RouteDecision.ARCHIVE_ONLY

    if inputs.aperture.exposure_mode in {ExposureMode.PRIVATE, ExposureMode.SYNTHETIC_ONLY}:
        return RouteDecision.PRIVATE

    # Public candidate/live: check blockers
    if blockers:
        return RouteDecision.PRIVATE  # fail-closed

    return RouteDecision.BROADCAST


def _compute_allowed_outcomes(
    inputs: EnvelopeInputs,
    route: RouteDecision,
    blockers: tuple[str, ...],
) -> tuple[AllowedOutcome, ...]:
    """Determine what the system can do from this aperture right now."""

    outcomes: list[AllowedOutcome] = []

    # Private answer is always available when not blocked
    if route is not RouteDecision.BLOCKED:
        outcomes.append(AllowedOutcome.PRIVATE_ANSWER)

    # Public speech: only when route is broadcast and no blockers
    if route is RouteDecision.BROADCAST and not blockers:
        outcomes.append(AllowedOutcome.PUBLIC_SPEECH_ALLOWED)
        outcomes.append(AllowedOutcome.PUBLIC_ACTION_PROPOSAL)
    elif route is RouteDecision.PRIVATE and inputs.aperture.exposure_mode in {
        ExposureMode.PUBLIC_CANDIDATE,
        ExposureMode.PUBLIC_LIVE,
    }:
        # Public aperture but blocked: dry-run or held
        outcomes.append(AllowedOutcome.DRY_RUN)

    if route is RouteDecision.BLOCKED:
        outcomes.append(AllowedOutcome.REFUSAL)

    if route is RouteDecision.ARCHIVE_ONLY:
        outcomes.append(AllowedOutcome.NO_CLAIM)

    if not outcomes:
        outcomes.append(AllowedOutcome.UNKNOWN)

    return tuple(outcomes)


def _compute_public_claim_ceiling(inputs: EnvelopeInputs) -> AuthorityCeiling:
    """Determine the public claim ceiling from inputs."""

    if inputs.claim_ceiling_override is not None:
        return inputs.claim_ceiling_override

    if inputs.private_risk_flags:
        return AuthorityCeiling.NO_CLAIM

    if inputs.aperture.exposure_mode in {ExposureMode.PRIVATE, ExposureMode.SYNTHETIC_ONLY}:
        return AuthorityCeiling.NO_CLAIM

    if inputs.aperture.exposure_mode is ExposureMode.ARCHIVE_ONLY:
        return AuthorityCeiling.LAST_OBSERVED_ONLY

    return AuthorityCeiling.PUBLIC_GATE_REQUIRED


def build_envelope_projection(inputs: EnvelopeInputs) -> SelfPresenceEnvelopeProjection:
    """Build a SelfPresenceEnvelopeProjection from runtime inputs.

    This is a pure function: no I/O, no side effects, deterministic.
    """

    blockers = _compute_blockers(inputs)
    route = _compute_route_decision(inputs, blockers)
    outcomes = _compute_allowed_outcomes(inputs, route, blockers)
    public_claim_ceiling = _compute_public_claim_ceiling(inputs)

    return SelfPresenceEnvelopeProjection(
        role=inputs.role,
        aperture=inputs.aperture,
        route_decision=route,
        programme_id=inputs.programme.programme_id,
        programme_authorization=inputs.programme.authorization_state,
        programme_authorized_at=inputs.programme.authorized_at,
        programme_expires_at=inputs.programme.expires_at,
        audio_safety=inputs.audio_safety.state,
        livestream_egress_state=inputs.egress.state,
        source_context_refs=inputs.source_context_refs,
        private_risk_flags=inputs.private_risk_flags,
        wcs_snapshot_refs=inputs.wcs_snapshot_refs,
        temporal_evidence_refs=inputs.temporal_evidence_refs,
        chronicle_refs=inputs.chronicle_refs,
        triad_refs=inputs.triad_refs,
        consent_privacy_ceiling=AuthorityCeiling.PRIVATE_ONLY
        if inputs.private_risk_flags
        else AuthorityCeiling.EVIDENCE_BOUND,
        rights_provenance_ceiling=AuthorityCeiling.PRIVATE_ONLY
        if inputs.private_risk_flags
        else AuthorityCeiling.EVIDENCE_BOUND,
        public_claim_ceiling=public_claim_ceiling,
        blockers=blockers,
        allowed_outcomes=outcomes,
    )


# ---- Compact prompt block ----


def render_compact_prompt_block(projection: SelfPresenceEnvelopeProjection) -> str:
    """Render a compact prompt block from the envelope projection.

    This replaces the ad-hoc seed construction in compose.py with a
    structured, envelope-derived prompt section.
    """

    lines: list[str] = []

    lines.append("[Self-Grounding State]")
    lines.append(f"Role: {projection.role.office} ({projection.role.addressee_mode})")
    lines.append(
        f"Aperture: {projection.aperture.kind} ({projection.aperture.exposure_mode.value})"
    )
    lines.append(f"Route: {projection.route_decision.value}")

    if projection.programme_authorization is not ProgrammeAuthorizationState.NOT_REQUIRED:
        lines.append(f"Programme auth: {projection.programme_authorization.value}")

    if projection.audio_safety is not AudioSafetyState.NOT_APPLICABLE:
        lines.append(f"Audio safety: {projection.audio_safety.value}")

    if projection.blockers:
        lines.append(f"Blockers: {', '.join(projection.blockers)}")

    outcomes_str = ", ".join(o.value for o in projection.allowed_outcomes)
    lines.append(f"Allowed: {outcomes_str}")

    lines.append(f"Claim ceiling: {projection.public_claim_ceiling.value}")

    return "\n".join(lines)


__all__ = [
    "AllowedOutcome",
    "ApertureSnapshot",
    "AudioSafetySnapshot",
    "AudioSafetyState",
    "EgressSnapshot",
    "EnvelopeInputs",
    "LivestreamEgressState",
    "ProgrammeAuthorizationState",
    "ProgrammeSnapshot",
    "RoleSnapshot",
    "RouteDecision",
    "SelfPresenceEnvelopeProjection",
    "build_envelope_projection",
    "render_compact_prompt_block",
]
