"""Private-to-public bridge governor.

This module is the ONLY path from private narration to public broadcast.
There is no default/fallback broadcast. The bridge governor takes a private
narration candidate and the SelfPresenceEnvelopeProjection, then produces
one of:

- ``private_response`` — narration stays private (default)
- ``public_action_proposal`` — narration re-enters impingement recruitment
  with explicit public metadata
- ``dry_run`` — narration would qualify for public but is held for logging
- ``held`` — narration is gated pending resolution
- ``refusal`` — narration is blocked by safety/privacy/rights
- ``rvpe_candidate`` — Research Vehicle Public Event candidate

No raw private content reaches public apertures unless explicitly
transformed, authorized, and witnessed.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.self_grounding_envelope import (
    AllowedOutcome,
    RouteDecision,
    SelfPresenceEnvelopeProjection,
)
from shared.self_presence import AuthorityCeiling


class BridgeOutcome(StrEnum):
    """What the bridge governor decides for a narration candidate."""

    PRIVATE_RESPONSE = "private_response"
    PUBLIC_ACTION_PROPOSAL = "public_action_proposal"
    DRY_RUN = "dry_run"
    HELD = "held"
    REFUSAL = "refusal"
    RVPE_CANDIDATE = "rvpe_candidate"


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class BridgeRequest(FrozenModel):
    """A narration candidate requesting bridge evaluation.

    The bridge request carries the composed narrative text, the envelope
    projection at the time of composition, and optional metadata.
    """

    schema_version: Literal[1] = 1
    narrative_text: str = Field(min_length=1)
    programme_id: str | None = None
    speech_event_id: str | None = None
    impulse_id: str | None = None
    triad_ids: tuple[str, ...] = Field(default_factory=tuple)
    operator_referent: str | None = None
    envelope: SelfPresenceEnvelopeProjection
    requested_aperture_id: str | None = None
    visibility_scope: str = "private"
    explicit_public_intent: bool = False


class BridgeResult(FrozenModel):
    """Result of the bridge governor's evaluation."""

    schema_version: Literal[1] = 1
    outcome: BridgeOutcome
    narrative_text: str = Field(min_length=1)
    blockers: tuple[str, ...] = Field(default_factory=tuple)
    aperture_id: str | None = None
    programme_authorization: str | None = None
    public_broadcast_intent: bool = False
    route_posture: str = "private_default"
    claim_ceiling: AuthorityCeiling = AuthorityCeiling.NO_CLAIM
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _no_public_without_authorization(self) -> Self:
        if self.outcome is BridgeOutcome.PUBLIC_ACTION_PROPOSAL:
            if not self.public_broadcast_intent:
                raise ValueError("public_action_proposal requires public_broadcast_intent=True")
            if not self.programme_authorization:
                raise ValueError("public_action_proposal requires programme_authorization")
            if self.route_posture != "broadcast_authorized":
                raise ValueError(
                    "public_action_proposal requires route_posture=broadcast_authorized"
                )
            if self.claim_ceiling not in {
                AuthorityCeiling.PUBLIC_GATE_REQUIRED,
                AuthorityCeiling.EVIDENCE_BOUND,
            }:
                raise ValueError("public_action_proposal requires public claim ceiling")
            if self.blockers:
                raise ValueError("public_action_proposal cannot have blockers")
        if self.outcome is BridgeOutcome.PRIVATE_RESPONSE:
            if self.public_broadcast_intent:
                raise ValueError("private_response cannot have public_broadcast_intent")
        return self


def _format_impingement_content(request: BridgeRequest, result: BridgeResult) -> dict:
    """Format the impingement content with bridge governor metadata.

    This is the content that ``_broadcast_intent_evidence()`` in
    ``destination_channel.py`` will inspect to find explicit broadcast intent.
    """

    content: dict = {
        "narrative": result.narrative_text,
        "programme_id": request.programme_id,
        "operator_referent": request.operator_referent,
        "impulse_id": request.impulse_id,
        "speech_event_id": request.speech_event_id,
        "triad_ids": list(request.triad_ids),
        # Bridge governor metadata — what classify_destination() inspects
        "public_broadcast_intent": result.public_broadcast_intent,
        "destination": "broadcast" if result.public_broadcast_intent else "private",
        "bridge_outcome": result.outcome.value,
        "route_posture": result.route_posture,
        "claim_ceiling": result.claim_ceiling.value,
        "aperture_id": result.aperture_id,
        "programme_authorization": result.programme_authorization,
        "evidence_refs": list(result.evidence_refs),
    }
    return content


def evaluate_bridge(request: BridgeRequest) -> BridgeResult:
    """Evaluate a narration candidate through the bridge governor.

    This is a pure function: no I/O, deterministic.

    Decision logic:

    1. If the envelope says blocked → refusal
    2. If no explicit public intent → private_response
    3. If public intent but envelope blockers → held (or dry_run)
    4. If public intent AND envelope allows public speech → public_action_proposal
    5. Default → private_response
    """

    envelope = request.envelope

    # 1. Blocked apertures
    if envelope.route_decision is RouteDecision.BLOCKED:
        return BridgeResult(
            outcome=BridgeOutcome.REFUSAL,
            narrative_text=request.narrative_text,
            blockers=("aperture_blocked",) + envelope.blockers,
        )

    # 2. No explicit public intent → private (default path)
    if not request.explicit_public_intent:
        return BridgeResult(
            outcome=BridgeOutcome.PRIVATE_RESPONSE,
            narrative_text=request.narrative_text,
        )

    # 3. Public intent but envelope has blockers → dry_run or held
    if envelope.blockers:
        return BridgeResult(
            outcome=BridgeOutcome.DRY_RUN,
            narrative_text=request.narrative_text,
            blockers=envelope.blockers,
        )

    # 4. Public intent AND envelope allows public speech
    if AllowedOutcome.PUBLIC_SPEECH_ALLOWED in envelope.allowed_outcomes:
        programme_auth = (
            f"programme:{envelope.role.role_id}"
            if envelope.programme_authorization.value == "fresh"
            else None
        )
        if programme_auth is None:
            # This shouldn't happen if PUBLIC_SPEECH_ALLOWED is in outcomes,
            # but fail-closed.
            return BridgeResult(
                outcome=BridgeOutcome.HELD,
                narrative_text=request.narrative_text,
                blockers=("programme_authorization_inconsistent",),
            )

        return BridgeResult(
            outcome=BridgeOutcome.PUBLIC_ACTION_PROPOSAL,
            narrative_text=request.narrative_text,
            aperture_id=request.requested_aperture_id or envelope.aperture.aperture_id,
            programme_authorization=programme_auth,
            public_broadcast_intent=True,
            route_posture="broadcast_authorized",
            claim_ceiling=envelope.public_claim_ceiling,
            evidence_refs=(
                envelope.source_context_refs + envelope.wcs_snapshot_refs + envelope.chronicle_refs
            ),
        )

    # 5. Public intent but not allowed (envelope didn't grant it)
    return BridgeResult(
        outcome=BridgeOutcome.HELD,
        narrative_text=request.narrative_text,
        blockers=("public_speech_not_allowed_by_envelope",),
    )


__all__ = [
    "BridgeOutcome",
    "BridgeRequest",
    "BridgeResult",
    "_format_impingement_content",
    "evaluate_bridge",
]
