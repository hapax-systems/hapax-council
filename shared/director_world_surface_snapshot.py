"""Director-facing World Capability Surface snapshot fixtures.

This module is a contract surface. It validates the shape that future director
prompt, vocabulary, programme, public-event, and move-normalizer adapters can
consume without letting static prompt hints masquerade as live availability.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from shared.livestream_role_state import (
    LivestreamRoleState,
    SpeechAct,
    SpeechAuthorizationDecision,
    authorize_speech_act,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DIRECTOR_WORLD_SURFACE_SNAPSHOT_FIXTURES = (
    REPO_ROOT / "config" / "director-world-surface-snapshot-fixtures.json"
)

REQUIRED_MOVE_STATUSES = frozenset(
    {
        "mounted",
        "public",
        "private",
        "dry_run",
        "stale",
        "blocked",
        "unavailable",
        "blocked_hardware_no_op",
    }
)

REQUIRED_SURFACE_FAMILIES = frozenset(
    {
        "tool_schema",
        "runtime_service",
        "state_file",
        "device",
        "audio_route",
        "model_provider",
        "publication_endpoint",
        "blocked_decommissioned",
    }
)

DIRECTOR_MOVE_ROW_REQUIRED_FIELDS = (
    "schema_version",
    "move_id",
    "surface_id",
    "status",
    "verb",
    "target_type",
    "target_id",
    "display_name",
    "source_refs",
    "generated_from",
    "intent_families",
    "surface_family",
    "surface_ids",
    "route_refs",
    "evidence_status",
    "freshness",
    "availability",
    "privacy_class",
    "rights_class",
    "monetization_state",
    "grounding_status",
    "claim_authority_ceiling",
    "claim_posture",
    "public_claim_allowed",
    "public_event_policy",
    "evidence_obligations",
    "required_witness_refs",
    "missing_witness_refs",
    "blocked_reasons",
    "blocker_reason",
    "fallback",
    "outcome_policy_ref",
    "director_control_move_template",
)

DIRECTOR_SNAPSHOT_REQUIRED_FIELDS = (
    "schema_version",
    "snapshot_id",
    "generated_at",
    "freshness_ttl_s",
    "mode",
    "programme_ref",
    "condition_ref",
    "egress_state_ref",
    "audio_state_ref",
    "rights_state_ref",
    "privacy_state_ref",
    "capability_refs",
    "substrate_refs",
    "route_refs",
    "lane_refs",
    "claim_refs",
    "public_event_refs",
    "available_moves",
    "blocked_moves",
    "dry_run_moves",
    "private_only_moves",
    "fallback_moves",
    "eligible_programme_formats",
    "opportunity_refs",
    "evidence_obligations",
    "refusal_or_correction_candidates",
    "prompt_summary",
    "audit_refs",
)

PUBLIC_LIVE_REQUIRED_OBLIGATIONS = frozenset(
    {
        "source_ref",
        "freshness",
        "route",
        "witness",
        "grounding_gate",
        "rights",
        "privacy",
        "egress",
        "public_event",
    }
)


class DirectorWorldSurfaceSnapshotError(ValueError):
    """Raised when director WCS snapshot fixtures fail closed."""


class SnapshotMode(StrEnum):
    RESEARCH = "research"
    RND = "rnd"
    FORTRESS = "fortress"


class MoveStatus(StrEnum):
    MOUNTED = "mounted"
    PUBLIC = "public"
    PRIVATE = "private"
    DRY_RUN = "dry_run"
    STALE = "stale"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"
    BLOCKED_HARDWARE_NO_OP = "blocked_hardware_no_op"


class SurfaceFamily(StrEnum):
    TOOL_SCHEMA = "tool_schema"
    RUNTIME_SERVICE = "runtime_service"
    STATE_FILE = "state_file"
    DEVICE = "device"
    AUDIO_ROUTE = "audio_route"
    VIDEO_SURFACE = "video_surface"
    MIDI_SURFACE = "midi_surface"
    DESKTOP_CONTROL = "desktop_control"
    MODEL_PROVIDER = "model_provider"
    SEARCH_PROVIDER = "search_provider"
    PUBLICATION_ENDPOINT = "publication_endpoint"
    PUBLIC_EVENT = "public_event"
    ARCHIVE_PROCESSOR = "archive_processor"
    BLOCKED_DECOMMISSIONED = "blocked_decommissioned"
    STATIC_PROMPT_HINT = "static_prompt_hint"


class GeneratedFrom(StrEnum):
    CAPABILITY_CLASSIFICATION_INVENTORY = "capability_classification_inventory"
    WCS_HEALTH_ENVELOPE = "wcs_health_envelope"
    RUNTIME_WITNESS = "runtime_witness"
    DIRECTOR_VOCABULARY = "director_vocabulary"
    PROGRAMME_CONTEXT = "programme_context"
    PUBLIC_EVENT_GATE = "public_event_gate"
    STATIC_PROMPT_HINT = "static_prompt_hint"
    DECOMMISSION_EVIDENCE = "decommission_evidence"


class EvidenceStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    UNKNOWN = "unknown"
    BLOCKED = "blocked"
    PRIVATE_ONLY = "private_only"
    DRY_RUN = "dry_run"
    NOT_APPLICABLE = "not_applicable"


class FreshnessState(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class PrivacyClass(StrEnum):
    PUBLIC_SAFE = "public_safe"
    PRIVATE_ONLY = "private_only"
    DRY_RUN = "dry_run"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class RightsClass(StrEnum):
    PUBLIC_CLEAR = "public_clear"
    PRIVATE_ONLY = "private_only"
    BLOCKED = "blocked"
    MISSING = "missing"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class MonetizationState(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"


class GroundingStatus(StrEnum):
    GROUNDED = "grounded"
    BLOCKED = "blocked"
    MISSING = "missing"
    PRIVATE_ONLY = "private_only"
    DRY_RUN = "dry_run"
    NOT_APPLICABLE = "not_applicable"


class ClaimAuthorityCeiling(StrEnum):
    NO_CLAIM = "no_claim"
    INTERNAL_ONLY = "internal_only"
    PRIVATE_ONLY = "private_only"
    DRY_RUN = "dry_run"
    EVIDENCE_BOUND = "evidence_bound"
    PUBLIC_GATE_REQUIRED = "public_gate_required"


class PublicEventPolicy(StrEnum):
    PUBLIC_LIVE_ALLOWED = "public_live_allowed"
    PUBLIC_GATE_REQUIRED = "public_gate_required"
    ARCHIVE_ONLY = "archive_only"
    DRY_RUN = "dry_run"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"


class FallbackMode(StrEnum):
    NO_OP = "no_op"
    DRY_RUN = "dry_run"
    HOLD_LAST_SAFE = "hold_last_safe"
    SUPPRESS = "suppress"
    PRIVATE_ONLY = "private_only"
    OPERATOR_REASON = "operator_reason"
    DEGRADED_STATUS = "degraded_status"
    KILL_SWITCH = "kill_switch"
    FALLBACK_TARGET = "fallback_target"


class TargetType(StrEnum):
    AUDIO_ROUTE = "audio_route"
    VIDEO_SURFACE = "video_surface"
    CONTROL_SURFACE = "control_surface"
    PUBLIC_EVENT = "public_event"
    TOOL = "tool"
    MODEL_ROUTE = "model_route"
    HARDWARE_DEVICE = "hardware_device"
    ARCHIVE = "archive"
    STATE_FILE = "state_file"
    SERVICE = "service"
    PROMPT_HINT = "prompt_hint"


class ObligationDimension(StrEnum):
    SOURCE_REF = "source_ref"
    FRESHNESS = "freshness"
    ROUTE = "route"
    WITNESS = "witness"
    GROUNDING_GATE = "grounding_gate"
    RIGHTS = "rights"
    PRIVACY = "privacy"
    EGRESS = "egress"
    PUBLIC_EVENT = "public_event"
    HARDWARE = "hardware"
    OUTCOME = "outcome"


class AvailabilityFlags(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available_to_attempt: bool
    available_to_render: bool
    available_to_observe: bool
    available_to_claim_private: bool
    available_to_claim_public_live: bool
    available_to_archive: bool
    available_to_monetize: bool
    available_to_convert: bool

    def any_available(self) -> bool:
        return any(
            (
                self.available_to_attempt,
                self.available_to_render,
                self.available_to_observe,
                self.available_to_claim_private,
                self.available_to_claim_public_live,
                self.available_to_archive,
                self.available_to_monetize,
                self.available_to_convert,
            )
        )


class Freshness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: FreshnessState
    checked_at: str
    ttl_s: int | None = Field(default=None, ge=0)
    observed_age_s: int | None = Field(default=None, ge=0)
    source_ref: str | None = None

    @model_validator(mode="after")
    def _fresh_sources_need_evidence(self) -> Self:
        if self.state is FreshnessState.FRESH:
            if self.ttl_s is None or self.observed_age_s is None or not self.source_ref:
                raise ValueError("fresh director surface rows require ttl_s, age, and source_ref")
            if self.observed_age_s > self.ttl_s:
                raise ValueError("fresh director surface rows cannot exceed ttl")
        if self.state is FreshnessState.STALE and not self.source_ref:
            raise ValueError("stale director surface rows require a stale source_ref")
        return self


class EvidenceObligation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    obligation_id: str = Field(pattern=r"^obligation\.[a-z0-9_.-]+$")
    dimension: ObligationDimension
    required_for: list[str] = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    satisfied: bool
    missing_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _satisfied_obligations_need_evidence(self) -> Self:
        if self.satisfied and not self.evidence_refs:
            raise ValueError(f"{self.obligation_id} is satisfied without evidence_refs")
        if not self.satisfied and not self.missing_refs:
            raise ValueError(f"{self.obligation_id} is unsatisfied without missing_refs")
        return self


class ClaimPosture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authority_ceiling: ClaimAuthorityCeiling
    public_claim_allowed: bool
    public_live_claim_allowed: bool
    private_claim_allowed: bool
    archive_claim_allowed: bool
    monetization_claim_allowed: bool
    claim_refs: list[str] = Field(default_factory=list)
    blocker_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_claim_posture_order(self) -> Self:
        if self.public_live_claim_allowed:
            if not self.public_claim_allowed:
                raise ValueError("public_live_claim_allowed requires public_claim_allowed")
            if self.authority_ceiling is not ClaimAuthorityCeiling.PUBLIC_GATE_REQUIRED:
                raise ValueError("public live claims require public_gate_required ceiling")
            if not self.claim_refs:
                raise ValueError("public live claims require claim_refs")
        if self.monetization_claim_allowed and not self.public_live_claim_allowed:
            raise ValueError("monetization claims require public live claimability first")
        if self.blocker_reasons and (
            self.public_claim_allowed
            or self.public_live_claim_allowed
            or self.monetization_claim_allowed
        ):
            raise ValueError("claim blocker reasons cannot coexist with public/monetization claims")
        return self


class Fallback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: FallbackMode
    reason_code: str = Field(min_length=1)
    no_op: bool
    operator_visible_reason: str = Field(min_length=1)
    target_surface_id: str | None = None

    @model_validator(mode="after")
    def _fallback_target_requires_target(self) -> Self:
        if self.mode is FallbackMode.FALLBACK_TARGET and not self.target_surface_id:
            raise ValueError("fallback_target rows require target_surface_id")
        if self.no_op and self.mode not in {FallbackMode.NO_OP, FallbackMode.OPERATOR_REASON}:
            raise ValueError("no_op fallback rows must use no_op or operator_reason mode")
        return self


class DirectorControlMoveTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verb: str = Field(min_length=1)
    target: str = Field(min_length=1)
    execution_state: str = Field(min_length=1)
    public_claim_allowed: bool
    emits_capability_outcome_envelope: bool


class DirectorWorldSurfaceMoveRow(BaseModel):
    """One director-consumable world-surface move row."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    move_id: str = Field(pattern=r"^move\.[a-z0-9_.-]+$")
    surface_id: str = Field(min_length=1)
    status: MoveStatus
    verb: str = Field(min_length=1)
    target_type: TargetType
    target_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    source_refs: list[str] = Field(min_length=1)
    generated_from: list[GeneratedFrom] = Field(min_length=1)
    intent_families: list[str] = Field(min_length=1)
    surface_family: SurfaceFamily
    surface_ids: list[str] = Field(min_length=1)
    route_refs: list[str] = Field(default_factory=list)
    evidence_status: EvidenceStatus
    freshness: Freshness
    availability: AvailabilityFlags
    privacy_class: PrivacyClass
    rights_class: RightsClass
    monetization_state: MonetizationState
    grounding_status: GroundingStatus
    claim_authority_ceiling: ClaimAuthorityCeiling
    claim_posture: ClaimPosture
    public_claim_allowed: bool
    public_event_policy: PublicEventPolicy
    evidence_obligations: list[EvidenceObligation] = Field(min_length=1)
    required_witness_refs: list[str] = Field(default_factory=list)
    missing_witness_refs: list[str] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)
    blocker_reason: str | None = None
    fallback: Fallback
    outcome_policy_ref: str = Field(min_length=1)
    director_control_move_template: DirectorControlMoveTemplate

    @model_validator(mode="after")
    def _validate_director_move_fail_closed(self) -> Self:
        if self.surface_id not in self.surface_ids:
            raise ValueError("surface_id must be included in surface_ids")
        if self.claim_authority_ceiling is not self.claim_posture.authority_ceiling:
            raise ValueError("claim_authority_ceiling must mirror claim_posture")
        if self.public_claim_allowed != self.claim_posture.public_claim_allowed:
            raise ValueError("public_claim_allowed must mirror claim_posture")
        if self.availability.available_to_claim_public_live:
            if not self.public_claim_allowed or not self.claim_posture.public_live_claim_allowed:
                raise ValueError("public-live availability requires public claim posture")
        if self.availability.available_to_monetize:
            if (
                self.monetization_state is not MonetizationState.ALLOWED
                or not self.claim_posture.monetization_claim_allowed
            ):
                raise ValueError("monetization availability requires monetization claim posture")
        if self._generated_only_from_static_hint():
            if self.availability.any_available():
                raise ValueError("static prompt hints cannot satisfy availability")
            if self.public_claim_allowed or self.claim_posture.public_live_claim_allowed:
                raise ValueError("static prompt hints cannot satisfy public/live claimability")
            if self.evidence_status is EvidenceStatus.FRESH:
                raise ValueError("static prompt hints cannot be fresh evidence")
        if self.status in {
            MoveStatus.STALE,
            MoveStatus.BLOCKED,
            MoveStatus.UNAVAILABLE,
            MoveStatus.BLOCKED_HARDWARE_NO_OP,
        }:
            if not self.blocked_reasons or not self.blocker_reason:
                raise ValueError(f"{self.status.value} rows require blocker reasons")
            if self.public_claim_allowed:
                raise ValueError(f"{self.status.value} rows cannot allow public claims")
        if self.status is MoveStatus.STALE and self.freshness.state is not FreshnessState.STALE:
            raise ValueError("stale rows require stale freshness")
        if self.status is MoveStatus.DRY_RUN:
            if self.evidence_status is not EvidenceStatus.DRY_RUN:
                raise ValueError("dry_run rows require dry_run evidence_status")
            if self.public_event_policy is not PublicEventPolicy.DRY_RUN:
                raise ValueError("dry_run rows require dry_run public_event_policy")
        if (
            self.status is MoveStatus.PRIVATE
            and self.privacy_class is not PrivacyClass.PRIVATE_ONLY
        ):
            raise ValueError("private rows require private_only privacy_class")
        if self.status is MoveStatus.PUBLIC:
            self._validate_public_live_row()
        if self.status is MoveStatus.BLOCKED_HARDWARE_NO_OP:
            if self.fallback.mode is not FallbackMode.OPERATOR_REASON or not self.fallback.no_op:
                raise ValueError(
                    "blocked hardware rows must remain visible as operator_reason no-op"
                )
            if self.target_type is not TargetType.HARDWARE_DEVICE:
                raise ValueError("blocked hardware rows require hardware_device target_type")
        if self.director_control_move_template.public_claim_allowed != self.public_claim_allowed:
            raise ValueError("DirectorControlMove template must mirror public claim posture")
        if not self.director_control_move_template.emits_capability_outcome_envelope:
            raise ValueError("every director move row must map to a capability outcome envelope")
        return self

    def _generated_only_from_static_hint(self) -> bool:
        return set(self.generated_from) == {GeneratedFrom.STATIC_PROMPT_HINT}

    def _validate_public_live_row(self) -> None:
        if self.freshness.state is not FreshnessState.FRESH:
            raise ValueError("public rows require fresh evidence")
        if self.evidence_status is not EvidenceStatus.FRESH:
            raise ValueError("public rows require fresh evidence_status")
        if not self.required_witness_refs:
            raise ValueError("public rows require witness refs")
        if self.missing_witness_refs or self.blocked_reasons:
            raise ValueError("public rows cannot have missing witnesses or blockers")
        if self.privacy_class is not PrivacyClass.PUBLIC_SAFE:
            raise ValueError("public rows require public_safe privacy")
        if self.rights_class is not RightsClass.PUBLIC_CLEAR:
            raise ValueError("public rows require public_clear rights")
        if self.grounding_status is not GroundingStatus.GROUNDED:
            raise ValueError("public rows require grounded status")
        if self.public_event_policy is not PublicEventPolicy.PUBLIC_LIVE_ALLOWED:
            raise ValueError("public rows require public_live_allowed event policy")
        satisfied_dimensions = {
            obligation.dimension.value
            for obligation in self.evidence_obligations
            if obligation.satisfied
        }
        missing = PUBLIC_LIVE_REQUIRED_OBLIGATIONS - satisfied_dimensions
        if missing:
            raise ValueError("public rows missing obligations: " + ", ".join(sorted(missing)))

    def prompt_projection_payload(self) -> dict[str, Any]:
        """Return compact prompt-safe data without losing source refs."""

        return {
            "move_id": self.move_id,
            "surface_id": self.surface_id,
            "status": self.status.value,
            "verb": self.verb,
            "target": self.target_id,
            "source_refs": list(self.source_refs),
            "blocked_reasons": list(self.blocked_reasons),
            "fallback": self.fallback.mode.value,
            "public_claim_allowed": self.public_claim_allowed,
        }


class PromptSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checked_at: str
    mode: SnapshotMode
    available: list[str] = Field(default_factory=list)
    dry_run: list[str] = Field(default_factory=list)
    blocked: list[str] = Field(default_factory=list)
    private_only: list[str] = Field(default_factory=list)
    prompt_hint_refs: list[str] = Field(default_factory=list)


class DirectorWorldSurfaceSnapshot(BaseModel):
    """Director-facing projection of the World Capability Surface."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    snapshot_id: str = Field(pattern=r"^director-wcs-snapshot-[a-z0-9-]+$")
    generated_at: str
    freshness_ttl_s: int = Field(ge=0)
    mode: SnapshotMode
    programme_ref: str | None = None
    condition_ref: str | None = None
    egress_state_ref: str
    audio_state_ref: str
    rights_state_ref: str
    privacy_state_ref: str
    capability_refs: list[str] = Field(min_length=1)
    substrate_refs: list[str] = Field(min_length=1)
    route_refs: list[str] = Field(default_factory=list)
    lane_refs: list[str] = Field(default_factory=list)
    claim_refs: list[str] = Field(default_factory=list)
    public_event_refs: list[str] = Field(default_factory=list)
    role_state: LivestreamRoleState | None = None
    available_moves: list[DirectorWorldSurfaceMoveRow] = Field(default_factory=list)
    blocked_moves: list[DirectorWorldSurfaceMoveRow] = Field(default_factory=list)
    dry_run_moves: list[DirectorWorldSurfaceMoveRow] = Field(default_factory=list)
    private_only_moves: list[DirectorWorldSurfaceMoveRow] = Field(default_factory=list)
    fallback_moves: list[DirectorWorldSurfaceMoveRow] = Field(default_factory=list)
    eligible_programme_formats: list[str] = Field(default_factory=list)
    opportunity_refs: list[str] = Field(default_factory=list)
    evidence_obligations: list[EvidenceObligation] = Field(min_length=1)
    refusal_or_correction_candidates: list[str] = Field(default_factory=list)
    prompt_summary: PromptSummary
    audit_refs: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_snapshot_move_buckets(self) -> Self:
        rows = self.all_moves()
        if not rows:
            raise ValueError("director snapshot requires at least one move row")
        move_ids = [row.move_id for row in rows]
        duplicates = sorted({move_id for move_id in move_ids if move_ids.count(move_id) > 1})
        if duplicates:
            raise ValueError("duplicate director move ids: " + ", ".join(duplicates))
        for row in self.available_moves:
            if row.status not in {MoveStatus.MOUNTED, MoveStatus.PUBLIC}:
                raise ValueError("available_moves may only contain mounted or public rows")
        for row in self.blocked_moves:
            if row.status not in {
                MoveStatus.BLOCKED,
                MoveStatus.UNAVAILABLE,
                MoveStatus.BLOCKED_HARDWARE_NO_OP,
            }:
                raise ValueError("blocked_moves contains a non-blocked row")
        for row in self.dry_run_moves:
            if row.status is not MoveStatus.DRY_RUN:
                raise ValueError("dry_run_moves contains a non-dry-run row")
        for row in self.private_only_moves:
            if row.status is not MoveStatus.PRIVATE:
                raise ValueError("private_only_moves contains a non-private row")
        for row in self.fallback_moves:
            if row.status is not MoveStatus.STALE:
                raise ValueError("fallback_moves currently pin stale fallback rows")
        prompt_refs = set(self.prompt_summary.prompt_hint_refs)
        static_hint_refs = {
            ref
            for row in rows
            if set(row.generated_from) == {GeneratedFrom.STATIC_PROMPT_HINT}
            for ref in row.source_refs
        }
        if not static_hint_refs.issubset(prompt_refs):
            raise ValueError("static prompt hint rows must be named in prompt_summary")
        return self

    def all_moves(self) -> list[DirectorWorldSurfaceMoveRow]:
        return [
            *self.available_moves,
            *self.blocked_moves,
            *self.dry_run_moves,
            *self.private_only_moves,
            *self.fallback_moves,
        ]

    def public_live_moves(self) -> list[DirectorWorldSurfaceMoveRow]:
        """Return rows that satisfy public/live claimability."""

        return [
            row
            for row in self.all_moves()
            if row.status is MoveStatus.PUBLIC
            and row.public_claim_allowed
            and row.availability.available_to_claim_public_live
        ]

    def authorize_speech_act(
        self,
        speech_act: SpeechAct,
        *,
        role_state: LivestreamRoleState | None = None,
    ) -> SpeechAuthorizationDecision:
        """Authorize a speech act through this director snapshot's WCS route."""

        state = role_state or self.role_state
        if state is None:
            raise DirectorWorldSurfaceSnapshotError(
                "director speech authorization requires a LivestreamRoleState"
            )
        public_live_moves = self.public_live_moves()
        route_ref = speech_act.route_ref
        route_witness_refs: tuple[str, ...] = ()
        if public_live_moves:
            route = public_live_moves[0]
            route_ref = route_ref or route.surface_id
            route_witness_refs = tuple(route.required_witness_refs)
        return authorize_speech_act(
            state,
            speech_act,
            route_ref=route_ref,
            route_witness_refs=route_witness_refs,
            director_snapshot_ref=self.snapshot_id,
            public_event_refs=self.public_event_refs,
        )

    def rows_for_status(self, status: MoveStatus) -> list[DirectorWorldSurfaceMoveRow]:
        return [row for row in self.all_moves() if row.status is status]

    def rows_for_surface_family(self, family: SurfaceFamily) -> list[DirectorWorldSurfaceMoveRow]:
        return [row for row in self.all_moves() if row.surface_family is family]

    def prompt_projection_payloads(self) -> list[dict[str, Any]]:
        """Return prompt-safe rows with source refs intact."""

        return [row.prompt_projection_payload() for row in self.all_moves()]


class DirectorWorldSurfaceSnapshotFixtureSet(BaseModel):
    """Fixture set consumed by schema and loader tests."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_ref: str | None = Field(default=None, alias="$schema")
    schema_version: Literal[1] = 1
    fixture_set_id: str
    declared_at: str
    generated_from: list[str] = Field(min_length=1)
    producer: str
    move_statuses: list[MoveStatus] = Field(min_length=1)
    surface_families: list[SurfaceFamily] = Field(min_length=1)
    director_move_row_required_fields: list[str] = Field(min_length=1)
    director_snapshot_required_fields: list[str] = Field(min_length=1)
    snapshots: list[DirectorWorldSurfaceSnapshot] = Field(min_length=1)
    fail_closed_policy: dict[str, Literal[False]]

    @model_validator(mode="after")
    def _validate_fixture_set_coverage(self) -> Self:
        statuses = {status.value for status in self.move_statuses}
        if statuses != REQUIRED_MOVE_STATUSES:
            raise ValueError("fixture set move_statuses do not match required statuses")
        families = {family.value for family in self.surface_families}
        missing_families = REQUIRED_SURFACE_FAMILIES - families
        if missing_families:
            raise ValueError("fixture set missing surface families: " + ", ".join(missing_families))
        if set(self.director_move_row_required_fields) != set(DIRECTOR_MOVE_ROW_REQUIRED_FIELDS):
            raise ValueError("director move required field list drifted")
        if set(self.director_snapshot_required_fields) != set(DIRECTOR_SNAPSHOT_REQUIRED_FIELDS):
            raise ValueError("director snapshot required field list drifted")
        rows = self.all_moves()
        row_statuses = {row.status.value for row in rows}
        if row_statuses != REQUIRED_MOVE_STATUSES:
            raise ValueError("fixtures do not cover every required move status")
        row_families = {row.surface_family.value for row in rows}
        missing_row_families = REQUIRED_SURFACE_FAMILIES - row_families
        if missing_row_families:
            raise ValueError(
                "fixtures do not cover required surface families: "
                + ", ".join(sorted(missing_row_families))
            )
        if any(value is not False for value in self.fail_closed_policy.values()):
            raise ValueError("fail_closed_policy must remain all false")
        return self

    def all_moves(self) -> list[DirectorWorldSurfaceMoveRow]:
        rows: list[DirectorWorldSurfaceMoveRow] = []
        for snapshot in self.snapshots:
            rows.extend(snapshot.all_moves())
        return rows

    def require_surface(self, surface_id: str) -> DirectorWorldSurfaceMoveRow:
        for row in self.all_moves():
            if row.surface_id == surface_id:
                return row
        raise KeyError(f"unknown director world surface: {surface_id}")

    def rows_for_status(self, status: MoveStatus) -> list[DirectorWorldSurfaceMoveRow]:
        return [row for row in self.all_moves() if row.status is status]

    def rows_for_surface_family(self, family: SurfaceFamily) -> list[DirectorWorldSurfaceMoveRow]:
        return [row for row in self.all_moves() if row.surface_family is family]


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DirectorWorldSurfaceSnapshotError(f"{path} did not contain a JSON object")
    return payload


def load_director_world_surface_snapshot_fixtures(
    path: Path = DIRECTOR_WORLD_SURFACE_SNAPSHOT_FIXTURES,
) -> DirectorWorldSurfaceSnapshotFixtureSet:
    """Load and validate director WCS snapshot fixtures."""

    try:
        payload = _load_json_object(path)
        return DirectorWorldSurfaceSnapshotFixtureSet.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise DirectorWorldSurfaceSnapshotError(
            f"invalid director world surface snapshot fixtures at {path}: {exc}"
        ) from exc


__all__ = [
    "DIRECTOR_MOVE_ROW_REQUIRED_FIELDS",
    "DIRECTOR_SNAPSHOT_REQUIRED_FIELDS",
    "DIRECTOR_WORLD_SURFACE_SNAPSHOT_FIXTURES",
    "PUBLIC_LIVE_REQUIRED_OBLIGATIONS",
    "REQUIRED_MOVE_STATUSES",
    "REQUIRED_SURFACE_FAMILIES",
    "AvailabilityFlags",
    "ClaimAuthorityCeiling",
    "ClaimPosture",
    "DirectorWorldSurfaceMoveRow",
    "DirectorWorldSurfaceSnapshot",
    "DirectorWorldSurfaceSnapshotError",
    "DirectorWorldSurfaceSnapshotFixtureSet",
    "EvidenceObligation",
    "EvidenceStatus",
    "Fallback",
    "FallbackMode",
    "Freshness",
    "FreshnessState",
    "GeneratedFrom",
    "LivestreamRoleState",
    "MoveStatus",
    "SurfaceFamily",
    "load_director_world_surface_snapshot_fixtures",
]
