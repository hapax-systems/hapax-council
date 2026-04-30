"""Programme boundary events to bounded scrim gestures.

This contract makes refusal, correction, uncertainty, and blocked programme
boundaries visually legible without letting a scrim gesture validate a claim or
imply that public fanout happened.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from functools import cache
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIM_REFUSAL_CORRECTION_BOUNDARY_GESTURES_FIXTURES = (
    REPO_ROOT / "config" / "scrim-refusal-correction-boundary-gestures-fixtures.json"
)

REQUIRED_BOUNDARY_POSTURES = frozenset(
    {
        "refusal",
        "correction",
        "uncertainty",
        "stale_source",
        "rights_blocked",
        "privacy_blocked",
        "monetization_held",
        "public_event_held",
    }
)
FAIL_CLOSED_POLICY = {
    "scrim_grants_truth": False,
    "scrim_grants_rights": False,
    "scrim_grants_safety": False,
    "scrim_grants_public_status": False,
    "scrim_grants_monetization_status": False,
    "scrim_implies_public_fanout": False,
    "aesthetic_emphasis_validates_blocked_claim": False,
    "private_blocked_details_can_be_foregrounded": False,
}

PUBLIC_ARTIFACT_MODES = frozenset({"public_live", "public_archive", "public_monetizable"})
BLOCKED_POSTURES = frozenset(
    {
        "stale_source",
        "rights_blocked",
        "privacy_blocked",
        "monetization_held",
        "public_event_held",
    }
)
PRIVATE_UNSAFE_POSTURES = frozenset({"privacy_blocked", "rights_blocked"})

type BoundaryType = Literal[
    "programme.started",
    "claim.made",
    "uncertainty.marked",
    "refusal.issued",
    "correction.made",
    "artifact.candidate",
    "programme.ended",
]
type PublicPrivateMode = Literal[
    "private",
    "dry_run",
    "public_live",
    "public_archive",
    "public_monetizable",
]
type GateState = Literal[
    "pass", "fail", "dry_run", "private_only", "refusal", "correction_required"
]
type ClaimKind = Literal[
    "observation",
    "classification",
    "ranking",
    "comparison",
    "explanation",
    "refusal",
    "correction",
    "metadata",
]
type AuthorityCeiling = Literal["evidence_bound", "speculative", "internal_only"]
type ConfidenceLabel = Literal["none", "low", "medium", "medium_high", "high"]
type FallbackAction = Literal[
    "hold",
    "dry_run",
    "private_only",
    "archive_only",
    "chapter_only",
    "operator_review",
    "deny",
]
type UnavailableReason = Literal[
    "private_mode",
    "dry_run_mode",
    "missing_grounding_gate",
    "grounding_gate_failed",
    "unsupported_claim",
    "source_stale",
    "rights_blocked",
    "privacy_blocked",
    "egress_blocked",
    "audio_blocked",
    "archive_missing",
    "monetization_blocked",
    "operator_review_required",
    "research_vehicle_public_event_missing",
]
type BoundaryPosture = Literal[
    "refusal",
    "correction",
    "uncertainty",
    "stale_source",
    "rights_blocked",
    "privacy_blocked",
    "monetization_held",
    "public_event_held",
]
type BoundaryVisualTreatment = Literal[
    "foreground_public_safe_artifact",
    "suppress_private_detail",
    "hold_last_safe",
    "neutralize_blocked_claim",
    "boundary_breath_pulse",
    "local_clarity_shift",
]
type BoundaryArtifactVisibility = Literal[
    "foreground_public_safe",
    "suppressed_private",
    "metadata_only",
    "operator_only",
    "none",
]
type ScrimStateGestureType = Literal[
    "soften",
    "thicken",
    "thin",
    "shimmer",
    "ripple",
    "clear_window",
    "mark_boundary",
    "conversion_glow",
    "refusal_dim",
    "correction_glint",
    "neutral_hold",
]
type ScrimFallbackBehavior = Literal[
    "no_op",
    "neutral_hold",
    "minimum_density",
    "suppress_public_cue",
    "dry_run_badge",
]
type BoundaryAuditOutcome = Literal["accepted", "suppressed", "held", "fallback", "dry_run"]


class ScrimBoundaryGestureError(ValueError):
    """Raised when scrim boundary gesture fixtures fail closed."""


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class BoundaryNoExpertGate(FrozenModel):
    gate_ref: str | None = None
    gate_state: GateState
    claim_allowed: bool
    public_claim_allowed: bool
    infractions: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _blocked_gate_cannot_claim_public(self) -> Self:
        if self.gate_state != "pass" and self.public_claim_allowed:
            raise ValueError("non-pass boundary gate cannot allow public claims")
        return self


class BoundaryClaimShape(FrozenModel):
    claim_kind: ClaimKind
    authority_ceiling: AuthorityCeiling
    confidence_label: ConfidenceLabel
    uncertainty: str = Field(min_length=1)
    scope_limit: str = Field(min_length=1)


class BoundaryPublicEventMapping(FrozenModel):
    internal_only: bool
    fallback_action: FallbackAction
    unavailable_reasons: tuple[UnavailableReason, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _internal_only_cannot_have_public_fallback(self) -> Self:
        if self.internal_only and self.fallback_action in {"archive_only", "chapter_only"}:
            raise ValueError("internal-only boundary mappings cannot choose public fallbacks")
        return self


class ProgrammeBoundaryEventGestureRef(FrozenModel):
    """Compact ProgrammeBoundaryEvent subset consumed by the scrim adapter."""

    schema_version: Literal[1] = 1
    boundary_id: str = Field(pattern=r"^[a-z][a-z0-9_:-]*$")
    emitted_at: str = Field(min_length=1)
    programme_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    format_id: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    boundary_type: BoundaryType
    public_private_mode: PublicPrivateMode
    summary: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    no_expert_system_gate: BoundaryNoExpertGate
    claim_shape: BoundaryClaimShape
    public_event_mapping: BoundaryPublicEventMapping
    dry_run_unavailable_reasons: tuple[UnavailableReason, ...] = Field(default_factory=tuple)
    duplicate_key: str = Field(min_length=1)

    @model_validator(mode="after")
    def _public_boundary_claims_require_evidence(self) -> Self:
        if self.no_expert_system_gate.public_claim_allowed and not self.evidence_refs:
            raise ValueError("public boundary claims require evidence_refs")
        if self.public_private_mode in {"private", "dry_run"}:
            if self.no_expert_system_gate.public_claim_allowed:
                raise ValueError("private/dry-run boundaries cannot allow public claims")
        return self


class BoundaryGesturePublicClaimPolicy(FrozenModel):
    inherited_boundary_public_claim_allowed: bool
    scrim_public_claim_allowed: Literal[False] = False
    basis_refs: tuple[str, ...] = Field(default_factory=tuple)
    scrim_grants_truth: Literal[False] = False
    scrim_grants_rights: Literal[False] = False
    scrim_grants_safety: Literal[False] = False
    scrim_grants_public_status: Literal[False] = False
    scrim_grants_monetization_status: Literal[False] = False
    scope_expansion_allowed: Literal[False] = False


class BoundaryGestureCaps(FrozenModel):
    ttl_s: int = Field(ge=1, le=30)
    density_delta: float = Field(ge=-0.25, le=0.25)
    refraction_delta: float = Field(ge=-0.18, le=0.18)
    focus_strength: float = Field(ge=0.0, le=0.55)
    breath_pulse_count: int = Field(default=0, ge=0, le=3)
    boundary_pulse_count: int = Field(default=0, ge=0, le=3)
    local_clarity_delta: float = Field(default=0.0, ge=0.0, le=0.35)

    @model_validator(mode="after")
    def _bounded_boundary_pulses(self) -> Self:
        if self.breath_pulse_count and self.ttl_s > 18:
            raise ValueError("boundary breath pulses must stay brief")
        if self.boundary_pulse_count and self.ttl_s > 18:
            raise ValueError("boundary pulses must stay brief")
        return self


class BoundaryGestureRefs(FrozenModel):
    run_store_refs: tuple[str, ...] = Field(min_length=1)
    audit_refs: tuple[str, ...] = Field(min_length=1)
    health_refs: tuple[str, ...] = Field(min_length=1)
    boundary_event_refs: tuple[str, ...] = Field(min_length=1)
    wcs_source_refs: tuple[str, ...] = Field(min_length=1)


class ScrimBoundaryGestureRecord(FrozenModel):
    schema_version: Literal[1] = 1
    gesture_id: str = Field(pattern=r"^scrim_boundary_gesture:[a-z0-9_.:-]+$")
    created_at: str = Field(min_length=1)
    boundary_event_ref: str = Field(min_length=1)
    programme_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    boundary_type: BoundaryType
    posture: BoundaryPosture
    visual_treatment: BoundaryVisualTreatment
    scrim_state_gesture_type: ScrimStateGestureType
    fallback_behavior: ScrimFallbackBehavior
    ttl_s: int = Field(ge=1, le=30)
    intensity: float = Field(ge=0.0, le=1.0)
    target_region_refs: tuple[str, ...] = Field(default_factory=tuple)
    artifact_visibility: BoundaryArtifactVisibility
    public_safe_artifact: bool
    programme_output_success: bool
    public_fanout_implied: Literal[False] = False
    claim_validation_by_aesthetic: Literal[False] = False
    public_claim_policy: BoundaryGesturePublicClaimPolicy
    caps: BoundaryGestureCaps
    refs: BoundaryGestureRefs
    source_refs: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    blocked_reasons: tuple[str, ...] = Field(default_factory=tuple)
    suppressed_detail_refs: tuple[str, ...] = Field(default_factory=tuple)
    reason_code: str = Field(min_length=1)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_no_laundered_boundary_claim(self) -> Self:
        if self.ttl_s != self.caps.ttl_s:
            raise ValueError("gesture ttl_s must mirror caps.ttl_s")
        if self.public_claim_policy.scrim_public_claim_allowed:
            raise ValueError("scrim boundary gestures cannot allow public claims")
        if self.posture in BLOCKED_POSTURES:
            if not self.blocked_reasons:
                raise ValueError(f"{self.posture} gestures require blocked_reasons")
            if self.visual_treatment == "foreground_public_safe_artifact":
                raise ValueError("blocked boundary claims cannot be foregrounded")
            if self.artifact_visibility == "foreground_public_safe":
                raise ValueError("blocked boundary artifacts cannot be public-foregrounded")
            if self.intensity > 0.3:
                raise ValueError("blocked boundary gestures cannot be visually intensified")
            if self.programme_output_success:
                raise ValueError("blocked boundary gestures are not programme successes")
        if self.posture in PRIVATE_UNSAFE_POSTURES:
            if not self.suppressed_detail_refs:
                raise ValueError("private/unsafe blocked boundaries must suppress detail refs")
            if self.artifact_visibility not in {"suppressed_private", "metadata_only"}:
                raise ValueError("private/unsafe blocked boundaries must suppress details")
        if self.public_safe_artifact:
            if self.posture not in {"refusal", "correction"}:
                raise ValueError("only refusal/correction artifacts can be public-safe artifacts")
            if self.artifact_visibility != "foreground_public_safe":
                raise ValueError("public-safe artifacts must use foreground_public_safe visibility")
            if not self.programme_output_success:
                raise ValueError("public-safe refusal/correction artifact is programme output")
        if self.programme_output_success and not self.public_safe_artifact:
            raise ValueError("programme output success requires a public-safe artifact")
        return self

    def scrim_state_gesture(self) -> dict[str, Any]:
        """Return the ScrimStateEnvelope-compatible gesture projection."""

        return {
            "gesture_id": self.gesture_id.replace("scrim_boundary_gesture:", "scrim_gesture:"),
            "gesture_type": self.scrim_state_gesture_type,
            "created_at": self.created_at,
            "ttl_s": self.ttl_s,
            "intensity": self.intensity,
            "target_region_refs": list(self.target_region_refs),
            "source_move_refs": list(
                _dedupe((*self.refs.boundary_event_refs, *self.refs.audit_refs))
            ),
            "fallback_behavior": self.fallback_behavior,
        }


class ScrimBoundaryGestureAuditRecord(FrozenModel):
    schema_version: Literal[1] = 1
    audit_id: str = Field(pattern=r"^scrim_boundary_gesture_audit:[a-z0-9_.:-]+$")
    created_at: str = Field(min_length=1)
    gesture_id: str = Field(min_length=1)
    boundary_event_ref: str = Field(min_length=1)
    outcome: BoundaryAuditOutcome
    posture: BoundaryPosture
    reason_code: str = Field(min_length=1)
    run_store_refs: tuple[str, ...] = Field(min_length=1)
    health_refs: tuple[str, ...] = Field(min_length=1)
    public_claim_allowed: Literal[False] = False
    operator_visible: bool


class BoundaryGestureExpected(FrozenModel):
    posture: BoundaryPosture
    visual_treatment: BoundaryVisualTreatment
    scrim_state_gesture_type: ScrimStateGestureType
    artifact_visibility: BoundaryArtifactVisibility
    programme_output_success: bool
    public_safe_artifact: bool
    reason_code: str


class ScrimBoundaryGestureInput(FrozenModel):
    fixture_id: str = Field(min_length=1)
    family: BoundaryPosture
    boundary_event: ProgrammeBoundaryEventGestureRef
    wcs_source_refs: tuple[str, ...] = Field(min_length=1)
    source_refs: tuple[str, ...] = Field(min_length=1)
    run_store_ref: str = Field(min_length=1)
    audit_log_ref: str = Field(min_length=1)
    health_ref: str = Field(min_length=1)
    target_region_refs: tuple[str, ...] = Field(default_factory=tuple)
    requested_intensity: float = Field(default=0.35, ge=0.0, le=1.0)
    expected: BoundaryGestureExpected | None = None

    @model_validator(mode="after")
    def _family_must_match_projection(self) -> Self:
        posture = derive_boundary_posture(self.boundary_event)
        if self.family != posture:
            raise ValueError(f"fixture family {self.family} does not match derived {posture}")
        return self


class ScrimBoundaryGestureProjection(FrozenModel):
    schema_version: Literal[1] = 1
    projection_id: str = Field(min_length=1)
    fixture_id: str = Field(min_length=1)
    gesture: ScrimBoundaryGestureRecord
    audit_record: ScrimBoundaryGestureAuditRecord

    @model_validator(mode="after")
    def _refs_stay_consistent(self) -> Self:
        if self.gesture.gesture_id != self.audit_record.gesture_id:
            raise ValueError("gesture and audit record ids must match")
        if self.gesture.posture != self.audit_record.posture:
            raise ValueError("gesture and audit record posture must match")
        return self


class ScrimBoundaryGestureFixtureSet(FrozenModel):
    schema_version: Literal[1]
    fixture_set_id: str = Field(min_length=1)
    schema_ref: Literal["schemas/scrim-refusal-correction-boundary-gestures.schema.json"]
    generated_from: tuple[str, ...] = Field(min_length=1)
    declared_at: str = Field(min_length=1)
    producer: str = Field(min_length=1)
    boundary_postures: tuple[BoundaryPosture, ...] = Field(min_length=1)
    fail_closed_policy: dict[str, bool]
    fixtures: tuple[ScrimBoundaryGestureInput, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_fixture_set(self) -> Self:
        if set(self.boundary_postures) != REQUIRED_BOUNDARY_POSTURES:
            raise ValueError("boundary_postures do not cover every required posture")
        observed_postures = {fixture.family for fixture in self.fixtures}
        if observed_postures != REQUIRED_BOUNDARY_POSTURES:
            raise ValueError("fixtures do not cover every required boundary posture")
        if self.fail_closed_policy != FAIL_CLOSED_POLICY:
            raise ValueError("fail_closed_policy must pin every no-grant gate false")
        projections = tuple(
            project_scrim_boundary_gesture_input(fixture) for fixture in self.fixtures
        )
        for projection in projections:
            if projection.gesture.posture != projection.audit_record.posture:
                raise ValueError("fixture projection posture mismatch")
        return self

    def projections(self) -> tuple[ScrimBoundaryGestureProjection, ...]:
        """Project all fixture rows into bounded scrim boundary gestures."""

        return tuple(project_scrim_boundary_gesture_input(fixture) for fixture in self.fixtures)


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ScrimBoundaryGestureError(f"{path} did not contain a JSON object")
    return payload


@cache
def load_scrim_boundary_gesture_fixtures(
    path: Path = SCRIM_REFUSAL_CORRECTION_BOUNDARY_GESTURES_FIXTURES,
) -> ScrimBoundaryGestureFixtureSet:
    """Load and validate scrim refusal/correction boundary gesture fixtures."""

    try:
        return ScrimBoundaryGestureFixtureSet.model_validate(_load_json_object(path))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise ScrimBoundaryGestureError(
            f"invalid scrim boundary gesture fixtures at {path}: {exc}"
        ) from exc


def project_scrim_boundary_gesture_input(
    inputs: ScrimBoundaryGestureInput,
) -> ScrimBoundaryGestureProjection:
    """Project one ProgrammeBoundaryEvent into a bounded scrim gesture."""

    boundary = inputs.boundary_event
    posture = derive_boundary_posture(boundary)
    visual_treatment = _visual_treatment(posture)
    artifact_visibility = _artifact_visibility(posture, boundary)
    public_safe_artifact = _is_public_safe_artifact(posture, boundary)
    programme_output_success = public_safe_artifact
    reason_code = _reason_code(posture, boundary)
    caps = _caps_for_posture(posture, public_safe_artifact)
    intensity = _bounded_intensity(inputs.requested_intensity, posture, public_safe_artifact)
    blocked_reasons = _blocked_reasons(posture, boundary)
    refs = BoundaryGestureRefs(
        run_store_refs=(inputs.run_store_ref,),
        audit_refs=(inputs.audit_log_ref,),
        health_refs=(inputs.health_ref,),
        boundary_event_refs=(boundary.boundary_id,),
        wcs_source_refs=inputs.wcs_source_refs,
    )
    gesture = ScrimBoundaryGestureRecord(
        gesture_id=f"scrim_boundary_gesture:{inputs.fixture_id}",
        created_at=boundary.emitted_at,
        boundary_event_ref=boundary.boundary_id,
        programme_id=boundary.programme_id,
        run_id=boundary.run_id,
        boundary_type=boundary.boundary_type,
        posture=posture,
        visual_treatment=visual_treatment,
        scrim_state_gesture_type=_scrim_gesture_type(posture, public_safe_artifact),
        fallback_behavior=_fallback_behavior(posture),
        ttl_s=caps.ttl_s,
        intensity=intensity,
        target_region_refs=inputs.target_region_refs,
        artifact_visibility=artifact_visibility,
        public_safe_artifact=public_safe_artifact,
        programme_output_success=programme_output_success,
        public_claim_policy=BoundaryGesturePublicClaimPolicy(
            inherited_boundary_public_claim_allowed=(
                boundary.no_expert_system_gate.public_claim_allowed
            ),
            basis_refs=_dedupe(
                (*boundary.evidence_refs, boundary.no_expert_system_gate.gate_ref or "")
            ),
        ),
        caps=caps,
        refs=refs,
        source_refs=_dedupe((*inputs.source_refs, boundary.boundary_id)),
        evidence_refs=boundary.evidence_refs,
        blocked_reasons=blocked_reasons,
        suppressed_detail_refs=_suppressed_detail_refs(posture, boundary),
        reason_code=reason_code,
        reason=_reason_text(posture),
    )
    audit = ScrimBoundaryGestureAuditRecord(
        audit_id=f"scrim_boundary_gesture_audit:{inputs.fixture_id}",
        created_at=boundary.emitted_at,
        gesture_id=gesture.gesture_id,
        boundary_event_ref=boundary.boundary_id,
        outcome=_audit_outcome(posture, boundary, public_safe_artifact),
        posture=posture,
        reason_code=reason_code,
        run_store_refs=refs.run_store_refs,
        health_refs=refs.health_refs,
        operator_visible=posture in BLOCKED_POSTURES or boundary.public_private_mode == "private",
    )
    projection = ScrimBoundaryGestureProjection(
        projection_id=f"scrim_boundary_gesture_projection:{inputs.fixture_id}",
        fixture_id=inputs.fixture_id,
        gesture=gesture,
        audit_record=audit,
    )
    if inputs.expected is not None:
        _assert_expected_projection(inputs, projection)
    return projection


def derive_boundary_posture(boundary: ProgrammeBoundaryEventGestureRef) -> BoundaryPosture:
    """Classify a ProgrammeBoundaryEvent into the bounded posture vocabulary."""

    reasons = _all_unavailable_reasons(boundary)
    if "privacy_blocked" in reasons or boundary.public_private_mode == "private":
        return "privacy_blocked"
    if "rights_blocked" in reasons:
        return "rights_blocked"
    if "source_stale" in reasons:
        return "stale_source"
    if "monetization_blocked" in reasons:
        return "monetization_held"
    if "research_vehicle_public_event_missing" in reasons or (
        boundary.public_event_mapping.fallback_action == "operator_review"
        and boundary.public_private_mode in PUBLIC_ARTIFACT_MODES
    ):
        return "public_event_held"
    if (
        boundary.boundary_type == "refusal.issued"
        or boundary.no_expert_system_gate.gate_state == "refusal"
        or boundary.claim_shape.claim_kind == "refusal"
    ):
        return "refusal"
    if (
        boundary.boundary_type == "correction.made"
        or boundary.no_expert_system_gate.gate_state == "correction_required"
        or boundary.claim_shape.claim_kind == "correction"
    ):
        return "correction"
    return "uncertainty"


def _assert_expected_projection(
    inputs: ScrimBoundaryGestureInput, projection: ScrimBoundaryGestureProjection
) -> None:
    expected = inputs.expected
    if expected is None:
        return
    gesture = projection.gesture
    mismatches: list[str] = []
    if gesture.posture != expected.posture:
        mismatches.append(f"posture:{gesture.posture}!={expected.posture}")
    if gesture.visual_treatment != expected.visual_treatment:
        mismatches.append(
            f"visual_treatment:{gesture.visual_treatment}!={expected.visual_treatment}"
        )
    if gesture.scrim_state_gesture_type != expected.scrim_state_gesture_type:
        mismatches.append(
            "scrim_state_gesture_type:"
            f"{gesture.scrim_state_gesture_type}!={expected.scrim_state_gesture_type}"
        )
    if gesture.artifact_visibility != expected.artifact_visibility:
        mismatches.append(
            f"artifact_visibility:{gesture.artifact_visibility}!={expected.artifact_visibility}"
        )
    if gesture.programme_output_success != expected.programme_output_success:
        mismatches.append("programme_output_success mismatch")
    if gesture.public_safe_artifact != expected.public_safe_artifact:
        mismatches.append("public_safe_artifact mismatch")
    if gesture.reason_code != expected.reason_code:
        mismatches.append(f"reason_code:{gesture.reason_code}!={expected.reason_code}")
    if mismatches:
        raise ValueError(
            f"{inputs.fixture_id} expected projection mismatch: {', '.join(mismatches)}"
        )


def _all_unavailable_reasons(boundary: ProgrammeBoundaryEventGestureRef) -> tuple[str, ...]:
    return _dedupe(
        (
            *boundary.public_event_mapping.unavailable_reasons,
            *boundary.dry_run_unavailable_reasons,
            *boundary.no_expert_system_gate.infractions,
        )
    )


def _is_public_safe_artifact(
    posture: BoundaryPosture, boundary: ProgrammeBoundaryEventGestureRef
) -> bool:
    return (
        posture in {"refusal", "correction"}
        and boundary.public_private_mode in PUBLIC_ARTIFACT_MODES
        and not boundary.public_event_mapping.internal_only
        and bool(boundary.evidence_refs)
        and not _all_unavailable_reasons(boundary)
    )


def _visual_treatment(posture: BoundaryPosture) -> BoundaryVisualTreatment:
    if posture in {"refusal", "correction"}:
        return "foreground_public_safe_artifact"
    if posture == "privacy_blocked":
        return "suppress_private_detail"
    if posture in {"rights_blocked", "monetization_held"}:
        return "neutralize_blocked_claim"
    if posture == "public_event_held":
        return "boundary_breath_pulse"
    if posture == "stale_source":
        return "hold_last_safe"
    return "local_clarity_shift"


def _artifact_visibility(
    posture: BoundaryPosture, boundary: ProgrammeBoundaryEventGestureRef
) -> BoundaryArtifactVisibility:
    if _is_public_safe_artifact(posture, boundary):
        return "foreground_public_safe"
    if posture == "privacy_blocked":
        return "suppressed_private"
    if posture == "rights_blocked":
        return "metadata_only"
    if posture in {"monetization_held", "public_event_held", "stale_source"}:
        return "operator_only"
    return "none"


def _scrim_gesture_type(
    posture: BoundaryPosture, public_safe_artifact: bool
) -> ScrimStateGestureType:
    if posture == "refusal" and public_safe_artifact:
        return "refusal_dim"
    if posture == "correction" and public_safe_artifact:
        return "correction_glint"
    if posture == "public_event_held":
        return "mark_boundary"
    if posture == "uncertainty":
        return "shimmer"
    return "neutral_hold"


def _fallback_behavior(posture: BoundaryPosture) -> ScrimFallbackBehavior:
    if posture == "privacy_blocked":
        return "suppress_public_cue"
    if posture in {"stale_source", "public_event_held"}:
        return "neutral_hold"
    if posture in {"rights_blocked", "monetization_held"}:
        return "minimum_density"
    return "neutral_hold"


def _caps_for_posture(posture: BoundaryPosture, public_safe_artifact: bool) -> BoundaryGestureCaps:
    if public_safe_artifact:
        return BoundaryGestureCaps(
            ttl_s=14,
            density_delta=0.08,
            refraction_delta=0.04,
            focus_strength=0.45,
            breath_pulse_count=1,
            boundary_pulse_count=1,
            local_clarity_delta=0.25,
        )
    if posture == "public_event_held":
        return BoundaryGestureCaps(
            ttl_s=12,
            density_delta=0.04,
            refraction_delta=0.0,
            focus_strength=0.2,
            breath_pulse_count=2,
            boundary_pulse_count=2,
            local_clarity_delta=0.1,
        )
    if posture == "uncertainty":
        return BoundaryGestureCaps(
            ttl_s=10,
            density_delta=0.0,
            refraction_delta=0.06,
            focus_strength=0.28,
            local_clarity_delta=0.18,
        )
    return BoundaryGestureCaps(
        ttl_s=10, density_delta=0.0, refraction_delta=0.0, focus_strength=0.15
    )


def _bounded_intensity(
    requested_intensity: float, posture: BoundaryPosture, public_safe_artifact: bool
) -> float:
    if public_safe_artifact:
        return round(min(requested_intensity, 0.55), 3)
    if posture in BLOCKED_POSTURES:
        return round(min(requested_intensity, 0.28), 3)
    return round(min(requested_intensity, 0.38), 3)


def _blocked_reasons(
    posture: BoundaryPosture, boundary: ProgrammeBoundaryEventGestureRef
) -> tuple[str, ...]:
    reasons = _all_unavailable_reasons(boundary)
    if posture == "stale_source":
        return _dedupe((*reasons, "source_stale"))
    if posture == "rights_blocked":
        return _dedupe((*reasons, "rights_blocked"))
    if posture == "privacy_blocked":
        return _dedupe((*reasons, "privacy_blocked"))
    if posture == "monetization_held":
        return _dedupe((*reasons, "monetization_blocked"))
    if posture == "public_event_held":
        return _dedupe((*reasons, "research_vehicle_public_event_missing"))
    return ()


def _suppressed_detail_refs(
    posture: BoundaryPosture, boundary: ProgrammeBoundaryEventGestureRef
) -> tuple[str, ...]:
    if posture == "privacy_blocked":
        return _dedupe((f"{boundary.boundary_id}:private-detail", *boundary.evidence_refs))
    if posture == "rights_blocked":
        return _dedupe((f"{boundary.boundary_id}:unsafe-media-detail",))
    return ()


def _reason_code(posture: BoundaryPosture, boundary: ProgrammeBoundaryEventGestureRef) -> str:
    if posture == "refusal":
        return (
            "public_safe_refusal_artifact"
            if _is_public_safe_artifact(posture, boundary)
            else "refusal_boundary_held"
        )
    if posture == "correction":
        return (
            "public_safe_correction_artifact"
            if _is_public_safe_artifact(posture, boundary)
            else "correction_boundary_held"
        )
    return posture


def _reason_text(posture: BoundaryPosture) -> str:
    return {
        "refusal": "Public-safe refusal artifact can be visually successful without truth authority.",
        "correction": "Public-safe correction artifact can be foregrounded without expanding scope.",
        "uncertainty": "Uncertainty is expressed as bounded local clarity, not confidence inflation.",
        "stale_source": "Stale source boundary holds last safe posture.",
        "rights_blocked": "Rights-blocked media remains metadata-first and non-prominent.",
        "privacy_blocked": "Private or unsafe blocked details are suppressed from public view.",
        "monetization_held": "Monetization-held state remains a non-public claim boundary.",
        "public_event_held": "Public-event-held boundary pulses locally without implying fanout.",
    }[posture]


def _audit_outcome(
    posture: BoundaryPosture,
    boundary: ProgrammeBoundaryEventGestureRef,
    public_safe_artifact: bool,
) -> BoundaryAuditOutcome:
    if public_safe_artifact:
        return "accepted"
    if boundary.public_private_mode == "dry_run":
        return "dry_run"
    if posture == "privacy_blocked":
        return "suppressed"
    if posture in {"stale_source", "monetization_held", "public_event_held"}:
        return "held"
    return "fallback"


__all__ = [
    "FAIL_CLOSED_POLICY",
    "REQUIRED_BOUNDARY_POSTURES",
    "SCRIM_REFUSAL_CORRECTION_BOUNDARY_GESTURES_FIXTURES",
    "BoundaryGestureCaps",
    "BoundaryGestureExpected",
    "BoundaryGesturePublicClaimPolicy",
    "BoundaryGestureRefs",
    "BoundaryNoExpertGate",
    "BoundaryClaimShape",
    "BoundaryPublicEventMapping",
    "ProgrammeBoundaryEventGestureRef",
    "ScrimBoundaryGestureAuditRecord",
    "ScrimBoundaryGestureError",
    "ScrimBoundaryGestureFixtureSet",
    "ScrimBoundaryGestureInput",
    "ScrimBoundaryGestureProjection",
    "ScrimBoundaryGestureRecord",
    "derive_boundary_posture",
    "load_scrim_boundary_gesture_fixtures",
    "project_scrim_boundary_gesture_input",
]
