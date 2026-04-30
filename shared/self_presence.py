"""Self-presence ontology fixtures for Hapax Unified.

This module is a contract surface, not a runtime router. It names the minimal
self-grounding vocabulary and validates fixture envelopes so downstream prompt,
route, WCS, chronicle, and public-event work can consume one fail-closed model
without treating selected, commanded, rendered, inferred, or prompt-written
state as witnessed success.
"""

from __future__ import annotations

import json
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

REPO_ROOT = Path(__file__).resolve().parents[1]
SELF_PRESENCE_FIXTURES = REPO_ROOT / "config" / "self-presence-envelope-fixtures.json"

REQUIRED_ONTOLOGY_TERMS = frozenset(
    {
        "Aperture",
        "RoleState",
        "SelfPresenceEnvelope",
        "ClaimBinding",
        "ApertureEvent",
        "ContinuityObligation",
    }
)

REQUIRED_MAPPING_TARGETS = frozenset({"wcs", "temporal", "chronicle", "role", "impingement"})

REQUIRED_FIXTURE_CASES = frozenset(
    {
        "private_answer",
        "public_speech_candidate",
        "livestream_referent",
        "archive_only_referent",
        "synthetic_only_provenance",
        "blocked_route",
    }
)

PROMPT_ONLY_NON_WITNESS_STATES = frozenset(
    {
        "selection",
        "command_dispatch",
        "prompt_text",
        "render_state",
        "inference",
        "log_write",
    }
)

ROLES_ARE_OFFICES_STATEMENT = (
    "Roles are offices/lenses that define answerability and authority; "
    "they are not masks, personas, activities, or fictional selves."
)


class SelfPresenceError(ValueError):
    """Raised when a self-presence fixture tries to overclaim authority."""


class ApertureKind(StrEnum):
    PRIVATE_ASSISTANT = "private_assistant"
    PUBLIC_BROADCAST_VOICE = "public_broadcast_voice"
    COMPOSED_LIVESTREAM_FRAME = "composed_livestream_frame"
    RAW_STUDIO_CAMERA = "raw_studio_camera"
    ARCHIVE_WINDOW = "archive_window"
    SIDECHAT = "sidechat"
    CAPTION_SURFACE = "caption_surface"
    PUBLIC_EVENT = "public_event"
    WCS_ROW = "wcs_row"


class ExposureMode(StrEnum):
    PRIVATE = "private"
    PUBLIC_CANDIDATE = "public_candidate"
    PUBLIC_LIVE = "public_live"
    ARCHIVE_ONLY = "archive_only"
    SYNTHETIC_ONLY = "synthetic_only"
    BLOCKED = "blocked"


class RoleOffice(StrEnum):
    PRIVATE_ASSISTANT = "private_assistant"
    PUBLIC_NARRATOR = "public_narrator"
    DIRECTOR = "director"
    RESEARCH_VEHICLE = "research_vehicle"
    PUBLICATION_ADAPTER = "publication_adapter"
    GOVERNANCE_REFUSAL = "governance_refusal"


class AddresseeMode(StrEnum):
    OPERATOR = "operator"
    PUBLIC_AUDIENCE = "public_audience"
    SIDECHAT = "sidechat"
    ARCHIVE_READER = "archive_reader"
    SYSTEM = "system"


class AuthorityCeiling(StrEnum):
    NO_CLAIM = "no_claim"
    PRIVATE_ONLY = "private_only"
    DIAGNOSTIC_ONLY = "diagnostic_only"
    LAST_OBSERVED_ONLY = "last_observed_only"
    EVIDENCE_BOUND = "evidence_bound"
    PUBLIC_GATE_REQUIRED = "public_gate_required"


class PublicPrivateMode(StrEnum):
    PRIVATE = "private"
    PUBLIC_CANDIDATE = "public_candidate"
    PUBLIC_SAFE = "public_safe"
    PUBLIC_LIVE = "public_live"
    ARCHIVE = "archive"
    PUBLIC_FORBIDDEN = "public_forbidden"


class TemporalBand(StrEnum):
    RETENTION = "retention"
    IMPRESSION = "impression"
    PROTENTION = "protention"
    SURPRISE = "surprise"


class EventKind(StrEnum):
    PRIVATE_UTTERANCE = "private_utterance"
    PUBLIC_SPEECH = "public_speech"
    PUBLIC_SURFACE_REFERENT = "public_surface_referent"
    TOOL_RECEIPT = "tool_receipt"
    COMPOSITOR_ACTION = "compositor_action"
    PUBLIC_EVENT = "public_event"
    REFUSAL = "refusal"


class EventSuccessState(StrEnum):
    WITNESSED = "witnessed"
    REFUTED = "refuted"
    EXPIRED = "expired"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class AllowedOutcome(StrEnum):
    PRIVATE_ANSWER = "private_answer"
    PUBLIC_SPEECH_ALLOWED = "public_speech_allowed"
    PUBLIC_ACTION_PROPOSAL = "public_action_proposal"
    DRY_RUN = "dry_run"
    HELD = "held"
    REFUSAL = "refusal"
    CORRECTION = "correction"
    NO_CLAIM = "no_claim"
    UNKNOWN = "unknown"


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class OntologyTermMapping(FrozenModel):
    term: str
    definition: str = Field(min_length=1)
    maps_to: dict[str, tuple[str, ...]]

    @model_validator(mode="after")
    def _requires_existing_vocab_targets(self) -> Self:
        missing = REQUIRED_MAPPING_TARGETS - set(self.maps_to)
        if missing:
            raise ValueError(
                f"ontology term {self.term} missing mapping targets: {sorted(missing)}"
            )
        for target, refs in self.maps_to.items():
            if target in REQUIRED_MAPPING_TARGETS and not refs:
                raise ValueError(f"ontology term {self.term} has empty {target} mapping")
        return self


class RoleState(FrozenModel):
    role_id: str = Field(pattern=r"^role:[a-z0-9_.:-]+$")
    office: RoleOffice
    addressee_mode: AddresseeMode
    answerability_refs: tuple[str, ...] = Field(min_length=1)
    authority_scope: tuple[AuthorityCeiling, ...] = Field(min_length=1)
    route_posture: str = Field(min_length=1)
    roles_are_offices_not_masks: Literal[True] = True


class Aperture(FrozenModel):
    aperture_id: str = Field(pattern=r"^aperture:[a-z0-9_.:-]+$")
    kind: ApertureKind
    exposure_mode: ExposureMode
    public_private_mode: PublicPrivateMode
    evidence_classes: tuple[str, ...] = Field(default_factory=tuple)
    surface_refs: tuple[str, ...] = Field(default_factory=tuple)
    claim_authority_ceiling: AuthorityCeiling

    @model_validator(mode="after")
    def _public_live_requires_evidence(self) -> Self:
        if self.exposure_mode is ExposureMode.PUBLIC_LIVE:
            if self.claim_authority_ceiling is not AuthorityCeiling.PUBLIC_GATE_REQUIRED:
                raise ValueError("public_live apertures require public_gate_required authority")
            if not self.evidence_classes or not self.surface_refs:
                raise ValueError("public_live apertures require evidence_classes and surface_refs")
        return self


class ClaimBinding(FrozenModel):
    claim_id: str = Field(pattern=r"^claim:[a-z0-9_.:-]+$")
    representation_ref: str = Field(min_length=1)
    evidence_envelope_refs: tuple[str, ...] = Field(default_factory=tuple)
    authority_ceiling: AuthorityCeiling
    public_private_mode: PublicPrivateMode
    temporal_band: TemporalBand
    witness_refs: tuple[str, ...] = Field(default_factory=tuple)
    support_states: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _prompt_only_states_are_not_evidence(self) -> Self:
        prompt_only = PROMPT_ONLY_NON_WITNESS_STATES & set(self.support_states)
        if prompt_only and self.authority_ceiling not in {
            AuthorityCeiling.NO_CLAIM,
            AuthorityCeiling.DIAGNOSTIC_ONLY,
        }:
            raise ValueError(
                "prompt-only support states cannot carry evidence-bearing authority: "
                f"{sorted(prompt_only)}"
            )
        if self.public_private_mode is PublicPrivateMode.PUBLIC_LIVE:
            if not self.evidence_envelope_refs or not self.witness_refs:
                raise ValueError("public-live claims require evidence envelopes and witness refs")
            if self.authority_ceiling is not AuthorityCeiling.PUBLIC_GATE_REQUIRED:
                raise ValueError("public-live claims require public_gate_required authority")
        return self


class ApertureEvent(FrozenModel):
    event_id: str = Field(pattern=r"^aperture-event:[a-z0-9_.:-]+$")
    aperture_id: str = Field(pattern=r"^aperture:[a-z0-9_.:-]+$")
    event_kind: EventKind
    temporal_span_ref: str | None = Field(default=None, pattern=r"^span:[a-z0-9_.:-]+$")
    witness_refs: tuple[str, ...] = Field(default_factory=tuple)
    success_state: EventSuccessState
    support_states: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _success_requires_witness(self) -> Self:
        if self.success_state is EventSuccessState.WITNESSED and not self.witness_refs:
            raise ValueError("witnessed aperture events require witness refs")
        if PROMPT_ONLY_NON_WITNESS_STATES & set(self.support_states):
            if self.success_state is EventSuccessState.WITNESSED:
                raise ValueError("prompt-only states cannot be witnessed aperture success")
        return self


class ContinuityObligation(FrozenModel):
    obligation_id: str = Field(pattern=r"^continuity:[a-z0-9_.:-]+$")
    obligation_kind: str = Field(min_length=1)
    source_event_ref: str = Field(pattern=r"^aperture-event:[a-z0-9_.:-]+$")
    status: Literal["open", "resolved", "expired", "blocked"]
    visibility: PublicPrivateMode
    resolution_policy: str = Field(min_length=1)


class SelfPresenceEnvelope(FrozenModel):
    schema_version: Literal[1] = 1
    envelope_id: str = Field(pattern=r"^self-presence:[a-z0-9_.:-]+$")
    fixture_case: str
    role_state: RoleState
    apertures: tuple[Aperture, ...] = Field(min_length=1)
    active_environment_refs: tuple[str, ...] = Field(default_factory=tuple)
    source_context_refs: tuple[str, ...] = Field(default_factory=tuple)
    private_risk_flags: tuple[str, ...] = Field(default_factory=tuple)
    route_decision: Literal["private", "broadcast", "held", "blocked", "archive_only"]
    programme_authorization: Literal["fresh", "missing", "expired", "not_required"]
    audio_safety: Literal["safe", "unsafe", "unknown", "not_applicable"]
    livestream_egress_state: Literal["witnessed", "not_witnessed", "not_applicable"]
    wcs_snapshot_refs: tuple[str, ...] = Field(default_factory=tuple)
    temporal_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    multimodal_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    speech_event_refs: tuple[str, ...] = Field(default_factory=tuple)
    chronicle_refs: tuple[str, ...] = Field(default_factory=tuple)
    triad_refs: tuple[str, ...] = Field(default_factory=tuple)
    claim_bindings: tuple[ClaimBinding, ...] = Field(default_factory=tuple)
    aperture_events: tuple[ApertureEvent, ...] = Field(default_factory=tuple)
    continuity_obligations: tuple[ContinuityObligation, ...] = Field(default_factory=tuple)
    recruitment_context_refs: tuple[str, ...] = Field(default_factory=tuple)
    action_receipt_refs: tuple[str, ...] = Field(default_factory=tuple)
    consent_privacy_ceiling: AuthorityCeiling
    rights_provenance_ceiling: AuthorityCeiling
    public_claim_ceiling: AuthorityCeiling
    blockers: tuple[str, ...] = Field(default_factory=tuple)
    allowed_outcomes: tuple[AllowedOutcome, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _fail_closed_public_speech(self) -> Self:
        outcomes = set(self.allowed_outcomes)
        if AllowedOutcome.PUBLIC_SPEECH_ALLOWED in outcomes:
            missing: list[str] = []
            if self.route_decision != "broadcast":
                missing.append("broadcast route")
            if self.programme_authorization != "fresh":
                missing.append("fresh programme authorization")
            if self.audio_safety != "safe":
                missing.append("safe audio")
            if self.livestream_egress_state != "witnessed":
                missing.append("witnessed public egress")
            if self.public_claim_ceiling is not AuthorityCeiling.PUBLIC_GATE_REQUIRED:
                missing.append("public gate authority")
            if not self.speech_event_refs or not self.wcs_snapshot_refs:
                missing.append("speech and WCS witness refs")
            if missing:
                raise ValueError("public speech allowed without " + ", ".join(missing))
        if self.private_risk_flags and AllowedOutcome.PUBLIC_SPEECH_ALLOWED in outcomes:
            raise ValueError("private-risk source context cannot directly allow public speech")
        if self.blockers and any(
            outcome in outcomes
            for outcome in {
                AllowedOutcome.PUBLIC_SPEECH_ALLOWED,
            }
        ):
            raise ValueError("blocked envelopes cannot allow public speech")
        return self


class SelfPresenceFixtureSet(FrozenModel):
    schema_version: Literal[1] = 1
    fixture_set_id: str
    schema_ref: Literal["schemas/self-presence-envelope.schema.json"]
    generated_from: tuple[str, ...] = Field(min_length=1)
    roles_are_offices_statement: str
    prompt_only_non_witness_states: tuple[str, ...] = Field(min_length=1)
    ontology_term_mappings: tuple[OntologyTermMapping, ...] = Field(min_length=1)
    envelopes: tuple[SelfPresenceEnvelope, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _covers_required_contract(self) -> Self:
        terms = {row.term for row in self.ontology_term_mappings}
        missing_terms = REQUIRED_ONTOLOGY_TERMS - terms
        if missing_terms:
            raise ValueError(f"missing ontology term mappings: {sorted(missing_terms)}")
        fixture_cases = {row.fixture_case for row in self.envelopes}
        missing_cases = REQUIRED_FIXTURE_CASES - fixture_cases
        if missing_cases:
            raise ValueError(f"missing self-presence fixture cases: {sorted(missing_cases)}")
        if set(self.prompt_only_non_witness_states) != PROMPT_ONLY_NON_WITNESS_STATES:
            raise ValueError("prompt-only non-witness state list drifted")
        if self.roles_are_offices_statement != ROLES_ARE_OFFICES_STATEMENT:
            raise ValueError("roles-as-offices statement drifted")
        return self


def load_self_presence_fixture_set(path: Path = SELF_PRESENCE_FIXTURES) -> SelfPresenceFixtureSet:
    """Load and validate the self-presence fixture catalog."""

    try:
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return SelfPresenceFixtureSet.model_validate(payload)
    except (OSError, ValidationError, json.JSONDecodeError) as exc:
        raise SelfPresenceError(f"invalid self-presence fixture set {path}: {exc}") from exc


@cache
def fixture_set() -> SelfPresenceFixtureSet:
    """Cached self-presence fixture set for tests and docs gates."""

    return load_self_presence_fixture_set()


__all__ = [
    "AllowedOutcome",
    "Aperture",
    "ApertureEvent",
    "ApertureKind",
    "AuthorityCeiling",
    "ClaimBinding",
    "ContinuityObligation",
    "EventSuccessState",
    "PROMPT_ONLY_NON_WITNESS_STATES",
    "REQUIRED_FIXTURE_CASES",
    "REQUIRED_MAPPING_TARGETS",
    "REQUIRED_ONTOLOGY_TERMS",
    "ROLES_ARE_OFFICES_STATEMENT",
    "RoleState",
    "SELF_PRESENCE_FIXTURES",
    "SelfPresenceEnvelope",
    "SelfPresenceError",
    "SelfPresenceFixtureSet",
    "fixture_set",
    "load_self_presence_fixture_set",
]
