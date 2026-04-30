"""Director control move to scrim gesture adapter.

The adapter is a contract surface: it projects audited director moves into
bounded scrim gesture records without granting truth, rights, public status,
live control, or monetization status.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

REPO_ROOT = Path(__file__).resolve().parents[1]
DIRECTOR_SCRIM_GESTURE_ADAPTER_FIXTURES = (
    REPO_ROOT / "config" / "director-scrim-gesture-adapter-fixtures.json"
)

REQUIRED_DIRECTOR_VERBS = frozenset(
    {
        "foreground",
        "background",
        "hold",
        "suppress",
        "transition",
        "crossfade",
        "intensify",
        "stabilize",
        "route_attention",
        "mark_boundary",
    }
)
REQUIRED_AUDIT_OUTCOMES = frozenset(
    {"accepted", "rejected", "fallback", "stale", "private_only", "dry_run"}
)
FAIL_CLOSED_POLICY = {
    "scrim_grants_truth": False,
    "scrim_grants_rights": False,
    "scrim_grants_safety": False,
    "scrim_grants_public_status": False,
    "scrim_grants_live_control": False,
    "scrim_grants_monetization_status": False,
    "scrim_public_claim_scope_expansion_allowed": False,
    "blocked_targets_can_foreground": False,
    "blocked_targets_can_intensify": False,
    "blocked_targets_can_be_made_public": False,
}

BLOCKED_STATUSES = frozenset({"blocked", "unavailable", "blocked_hardware_no_op"})
DEGRADED_STATUSES = frozenset({"stale"})
RISKY_VISIBILITY_VERBS = frozenset({"foreground", "intensify"})

type DirectorVerbValue = Literal[
    "foreground",
    "background",
    "hold",
    "suppress",
    "transition",
    "crossfade",
    "intensify",
    "stabilize",
    "route_attention",
    "mark_boundary",
]
type DirectorTier = Literal["narrative", "structural", "programme", "operator_control", "adapter"]
type TargetType = Literal[
    "substrate",
    "spectacle_lane",
    "ward",
    "camera",
    "re_splay_device",
    "private_control",
    "cuepoint",
    "claim_binding",
    "programme",
    "egress_status",
]
type DirectorFreshnessState = Literal["fresh", "stale", "missing", "unknown", "not_applicable"]
type ExecutionState = Literal[
    "applied", "no_op", "dry_run", "fallback", "blocked", "operator_reason", "unavailable"
]
type FallbackMode = Literal[
    "no_op",
    "dry_run",
    "fallback",
    "operator_reason",
    "hold_last_safe",
    "suppress",
    "private_only",
    "degraded_status",
    "kill_switch",
]
type WCSMoveStatus = Literal[
    "mounted",
    "public",
    "private",
    "dry_run",
    "stale",
    "blocked",
    "unavailable",
    "blocked_hardware_no_op",
]
type WCSEvidenceStatus = Literal[
    "fresh",
    "stale",
    "missing",
    "unknown",
    "blocked",
    "private_only",
    "dry_run",
    "not_applicable",
]
type WCSPublicEventPolicy = Literal[
    "public_live_allowed",
    "public_gate_required",
    "archive_only",
    "dry_run",
    "blocked",
    "not_applicable",
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
type ScrimGestureEffect = Literal[
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
    "scrim.pierce",
]
type ScrimFallbackBehavior = Literal[
    "no_op", "neutral_hold", "minimum_density", "suppress_public_cue", "dry_run_badge"
]
type GestureExecution = Literal[
    "gesture", "no_op", "dry_run", "fallback", "hold_last_safe", "suppress", "operator_reason"
]
type GestureAuditOutcome = Literal[
    "accepted", "rejected", "fallback", "stale", "private_only", "dry_run"
]


class DirectorScrimGestureAdapterError(ValueError):
    """Raised when director-to-scrim gesture fixtures fail closed."""


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DirectorMoveTargetRef(FrozenModel):
    target_type: TargetType
    target_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    source_refs: tuple[str, ...] = Field(min_length=1)


class DirectorMoveFreshnessRef(FrozenModel):
    state: DirectorFreshnessState
    checked_at: str = Field(min_length=1)
    blocking_refs: tuple[str, ...] = Field(default_factory=tuple)


class DirectorMoveFallbackRef(FrozenModel):
    mode: FallbackMode
    reason: str = Field(min_length=1)
    operator_facing: bool


class DirectorMoveAuditEventRef(FrozenModel):
    event_type: str = Field(min_length=1)
    payload_ref: str = Field(min_length=1)
    health_ref: str = Field(min_length=1)


class DirectorControlMoveRef(FrozenModel):
    """Compact audited DirectorControlMove fields consumed by the adapter."""

    schema_version: Literal[1] = 1
    decision_id: str = Field(min_length=1)
    emitted_at: str = Field(min_length=1)
    director_tier: DirectorTier
    condition_id: str = Field(min_length=1)
    programme_id: str | None = None
    verb: DirectorVerbValue
    target: DirectorMoveTargetRef
    wcs_source_refs: tuple[str, ...] = Field(min_length=1)
    freshness: DirectorMoveFreshnessRef
    execution_state: ExecutionState
    fallback: DirectorMoveFallbackRef
    public_claim_allowed: bool
    audit_event: DirectorMoveAuditEventRef
    public_event_ref: str | None = None

    @model_validator(mode="after")
    def _validate_audited_move_ref(self) -> Self:
        if self.audit_event.event_type != f"director.move.{self.verb}":
            raise ValueError("audit_event.event_type must mirror director verb")
        if self.public_claim_allowed and self.freshness.state != "fresh":
            raise ValueError("public director moves require fresh freshness")
        if self.execution_state in {"no_op", "blocked", "operator_reason", "unavailable"}:
            if self.public_claim_allowed:
                raise ValueError("non-applied director move cannot allow public claims")
        return self


class WCSMoveRef(FrozenModel):
    wcs_snapshot_ref: str = Field(min_length=1)
    move_id: str = Field(min_length=1)
    source_refs: tuple[str, ...] = Field(min_length=1)
    status: WCSMoveStatus
    evidence_status: WCSEvidenceStatus
    freshness_state: DirectorFreshnessState
    fallback_mode: FallbackMode
    public_claim_allowed: bool
    public_event_policy: WCSPublicEventPolicy
    blocked_reasons: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_wcs_claim_floor(self) -> Self:
        if self.status in BLOCKED_STATUSES | DEGRADED_STATUSES:
            if self.public_claim_allowed:
                raise ValueError(f"{self.status} WCS moves cannot allow public claims")
            if not self.blocked_reasons:
                raise ValueError(f"{self.status} WCS moves require blocked_reasons")
        if self.public_claim_allowed:
            if self.status != "public" or self.evidence_status != "fresh":
                raise ValueError("public WCS moves require public status and fresh evidence")
            if self.freshness_state != "fresh":
                raise ValueError("public WCS moves require fresh freshness")
        return self


class ScrimGesturePublicClaimPolicy(FrozenModel):
    inherited_public_claim_allowed: bool
    scrim_public_claim_allowed: bool
    basis_refs: tuple[str, ...] = Field(default_factory=tuple)
    scrim_grants_truth: Literal[False] = False
    scrim_grants_rights: Literal[False] = False
    scrim_grants_safety: Literal[False] = False
    scrim_grants_public_status: Literal[False] = False
    scrim_grants_live_control: Literal[False] = False
    scrim_grants_monetization_status: Literal[False] = False
    scope_expansion_allowed: Literal[False] = False

    @model_validator(mode="after")
    def _validate_no_public_claim_expansion(self) -> Self:
        if self.scrim_public_claim_allowed and not self.inherited_public_claim_allowed:
            raise ValueError("scrim public claim flag must be inherited from director/WCS")
        if self.scrim_public_claim_allowed and not self.basis_refs:
            raise ValueError("inherited public claim needs explicit basis refs")
        return self


class ScrimGestureCaps(FrozenModel):
    ttl_s: int = Field(ge=1, le=30)
    density_delta: float = Field(ge=-0.35, le=0.35)
    refraction_delta: float = Field(ge=-0.25, le=0.25)
    focus_strength: float = Field(ge=0.0, le=0.7)
    boundary_pulse_count: int = Field(default=0, ge=0, le=3)
    pierce_requested: bool = False
    pierce_allowed: bool = False
    pierce_ttl_s: int | None = Field(default=None, ge=1, le=5)

    @model_validator(mode="after")
    def _validate_pierce_cap(self) -> Self:
        if self.pierce_allowed:
            if not self.pierce_requested:
                raise ValueError("pierce_allowed requires pierce_requested")
            if self.pierce_ttl_s is None:
                raise ValueError("pierce_allowed requires pierce_ttl_s")
            if self.ttl_s > 8:
                raise ValueError("scrim.pierce must remain rare and brief")
        elif self.pierce_ttl_s is not None:
            raise ValueError("pierce_ttl_s cannot be set when pierce is disallowed")
        return self


class ScrimGestureRecord(FrozenModel):
    schema_version: Literal[1] = 1
    gesture_id: str = Field(pattern=r"^scrim_gesture:[a-z0-9_.:-]+$")
    gesture_type: ScrimStateGestureType
    gesture_effect: ScrimGestureEffect
    created_at: str = Field(min_length=1)
    ttl_s: int = Field(ge=1, le=30)
    intensity: float = Field(ge=0.0, le=1.0)
    execution: GestureExecution
    target_lane_ref: str | None = None
    target_region_refs: tuple[str, ...] = Field(default_factory=tuple)
    source_move_refs: tuple[str, ...] = Field(min_length=1)
    director_decision_id: str = Field(min_length=1)
    director_verb: DirectorVerbValue
    wcs_snapshot_ref: str = Field(min_length=1)
    wcs_source_refs: tuple[str, ...] = Field(min_length=1)
    freshness_state: DirectorFreshnessState
    fallback_mode: FallbackMode
    fallback_behavior: ScrimFallbackBehavior
    public_claim_policy: ScrimGesturePublicClaimPolicy
    caps: ScrimGestureCaps
    reason: str = Field(min_length=1)
    audit_refs: tuple[str, ...] = Field(min_length=1)
    blocked_reasons: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_bounded_scrim_gesture(self) -> Self:
        if self.ttl_s != self.caps.ttl_s:
            raise ValueError("gesture ttl_s must mirror caps.ttl_s")
        if self.gesture_effect == "scrim.pierce":
            if self.gesture_type != "mark_boundary":
                raise ValueError(
                    "scrim.pierce must project as mark_boundary for envelope compatibility"
                )
            if self.director_verb != "mark_boundary":
                raise ValueError("scrim.pierce requires a mark_boundary director move")
            if not self.caps.pierce_allowed:
                raise ValueError("scrim.pierce requires pierce_allowed caps")
        if self.director_verb == "hold" and self.execution != "no_op":
            if not self.target_lane_ref or not self.reason.strip():
                raise ValueError("hold gestures require target_lane_ref and reason")
        if self.execution != "gesture":
            if self.public_claim_policy.scrim_public_claim_allowed:
                raise ValueError("fallback/no-op/dry-run gestures cannot allow public claims")
        if self.director_verb in RISKY_VISIBILITY_VERBS and self.blocked_reasons:
            if self.execution == "gesture":
                raise ValueError("blocked foreground/intensify cannot execute as gestures")
            if self.gesture_type in {"thin", "thicken", "clear_window"}:
                raise ValueError("blocked foreground/intensify cannot use prominence gestures")
        return self

    def scrim_state_gesture(self) -> dict[str, Any]:
        """Return the ScrimStateEnvelope-compatible gesture projection."""

        return {
            "gesture_id": self.gesture_id,
            "gesture_type": self.gesture_type,
            "created_at": self.created_at,
            "ttl_s": self.ttl_s,
            "intensity": self.intensity,
            "target_region_refs": list(self.target_region_refs),
            "source_move_refs": list(self.source_move_refs),
            "fallback_behavior": self.fallback_behavior,
        }


class DirectorScrimGestureAuditRecord(FrozenModel):
    schema_version: Literal[1] = 1
    audit_id: str = Field(pattern=r"^director_scrim_gesture:[a-z0-9_.:-]+$")
    created_at: str = Field(min_length=1)
    director_decision_id: str = Field(min_length=1)
    director_payload_ref: str = Field(min_length=1)
    gesture_id: str = Field(min_length=1)
    verb: DirectorVerbValue
    outcome: GestureAuditOutcome
    execution: GestureExecution
    reason_code: str = Field(min_length=1)
    wcs_snapshot_ref: str = Field(min_length=1)
    source_refs: tuple[str, ...] = Field(min_length=1)
    freshness_state: DirectorFreshnessState
    fallback_mode: FallbackMode
    public_claim_allowed: bool
    operator_visible: bool

    @model_validator(mode="after")
    def _validate_audit_no_claim_expansion(self) -> Self:
        if self.outcome != "accepted" and self.public_claim_allowed:
            raise ValueError("non-accepted scrim gesture audits cannot allow public claims")
        return self


class DirectorScrimGestureExpected(FrozenModel):
    outcome: GestureAuditOutcome
    execution: GestureExecution
    gesture_type: ScrimStateGestureType
    gesture_effect: ScrimGestureEffect
    fallback_behavior: ScrimFallbackBehavior
    public_claim_allowed: bool
    reason_code: str


class DirectorScrimGestureInput(FrozenModel):
    fixture_id: str = Field(min_length=1)
    family: str = Field(min_length=1)
    director_move: DirectorControlMoveRef
    wcs: WCSMoveRef
    scrim_state_ref: str = Field(min_length=1)
    health_ref: str = Field(min_length=1)
    target_lane_ref: str | None = None
    target_region_refs: tuple[str, ...] = Field(default_factory=tuple)
    reason: str | None = None
    request_pierce: bool = False
    requested_intensity: float = Field(default=0.4, ge=0.0, le=1.0)
    expected: DirectorScrimGestureExpected | None = None

    @model_validator(mode="after")
    def _validate_input_refs(self) -> Self:
        if self.director_move.audit_event.health_ref != self.health_ref:
            raise ValueError("director audit health_ref must match gesture input health_ref")
        if not set(self.wcs.source_refs).issubset(set(self.director_move.wcs_source_refs)):
            raise ValueError("director move must cite the WCS source refs consumed by gesture")
        return self


class DirectorScrimGestureProjection(FrozenModel):
    schema_version: Literal[1] = 1
    projection_id: str = Field(min_length=1)
    fixture_id: str = Field(min_length=1)
    scrim_state_ref: str = Field(min_length=1)
    health_ref: str = Field(min_length=1)
    gesture: ScrimGestureRecord
    audit_record: DirectorScrimGestureAuditRecord

    @model_validator(mode="after")
    def _validate_projection_consistency(self) -> Self:
        if self.gesture.gesture_id != self.audit_record.gesture_id:
            raise ValueError("gesture and audit record ids must match")
        if self.gesture.public_claim_policy.scrim_public_claim_allowed != (
            self.audit_record.public_claim_allowed
        ):
            raise ValueError("gesture public claim policy must mirror audit record")
        return self


class DirectorScrimGestureFixtureSet(FrozenModel):
    schema_version: Literal[1]
    fixture_set_id: str
    schema_ref: Literal["schemas/director-scrim-gesture-adapter.schema.json"]
    generated_from: tuple[str, ...] = Field(min_length=1)
    declared_at: str
    producer: str
    director_verbs: tuple[DirectorVerbValue, ...]
    audit_outcomes: tuple[GestureAuditOutcome, ...]
    fail_closed_policy: dict[str, bool]
    fixtures: tuple[DirectorScrimGestureInput, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_fixture_set_contract(self) -> Self:
        declared_verbs = {verb for verb in self.director_verbs}
        if declared_verbs != REQUIRED_DIRECTOR_VERBS:
            raise ValueError("director_verbs do not cover every required verb")
        observed_verbs = {fixture.director_move.verb for fixture in self.fixtures}
        if observed_verbs != REQUIRED_DIRECTOR_VERBS:
            raise ValueError("fixtures do not cover every required director verb")
        if set(self.audit_outcomes) != REQUIRED_AUDIT_OUTCOMES:
            raise ValueError("audit_outcomes do not cover every required outcome")
        projections = tuple(
            project_director_scrim_gesture_input(fixture) for fixture in self.fixtures
        )
        observed_outcomes = {projection.audit_record.outcome for projection in projections}
        if not REQUIRED_AUDIT_OUTCOMES.issubset(observed_outcomes):
            raise ValueError("fixtures do not emit every required audit outcome")
        if self.fail_closed_policy != FAIL_CLOSED_POLICY:
            raise ValueError("fail_closed_policy must pin every no-grant gate false")
        ids = [fixture.fixture_id for fixture in self.fixtures]
        duplicates = sorted({fixture_id for fixture_id in ids if ids.count(fixture_id) > 1})
        if duplicates:
            raise ValueError(
                "duplicate director scrim gesture fixture ids: " + ", ".join(duplicates)
            )
        return self

    def projections(self) -> tuple[DirectorScrimGestureProjection, ...]:
        """Project all fixture rows through the adapter."""

        return tuple(project_director_scrim_gesture_input(fixture) for fixture in self.fixtures)

    def audit_records_by_outcome(
        self,
    ) -> dict[GestureAuditOutcome, tuple[DirectorScrimGestureAuditRecord, ...]]:
        """Return audit records grouped by outcome for downstream fixture tests."""

        grouped: dict[GestureAuditOutcome, list[DirectorScrimGestureAuditRecord]] = {}
        for projection in self.projections():
            grouped.setdefault(projection.audit_record.outcome, []).append(projection.audit_record)
        return {outcome: tuple(records) for outcome, records in grouped.items()}


def _dedupe(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DirectorScrimGestureAdapterError(f"{path} did not contain a JSON object")
    return payload


@cache
def load_director_scrim_gesture_fixtures(
    path: Path = DIRECTOR_SCRIM_GESTURE_ADAPTER_FIXTURES,
) -> DirectorScrimGestureFixtureSet:
    """Load and validate director scrim gesture adapter fixtures."""

    try:
        return DirectorScrimGestureFixtureSet.model_validate(_load_json_object(path))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise DirectorScrimGestureAdapterError(
            f"invalid director scrim gesture adapter fixtures at {path}: {exc}"
        ) from exc


def project_director_scrim_gesture_input(
    inputs: DirectorScrimGestureInput,
) -> DirectorScrimGestureProjection:
    """Project one audited director control move into a bounded scrim gesture."""

    outcome, execution, reason_code = _select_outcome(inputs)
    gesture_type, gesture_effect = _gesture_shape(inputs, outcome, execution)
    fallback_behavior = _fallback_behavior(inputs, outcome, execution)
    public_claim_allowed = _inherited_public_claim_allowed(inputs, outcome, execution)
    caps = _gesture_caps(inputs, gesture_effect, outcome, execution)
    intensity = _bounded_intensity(inputs, outcome, execution, caps)
    source_move_refs = _dedupe(
        (
            inputs.director_move.decision_id,
            inputs.director_move.audit_event.payload_ref,
            inputs.wcs.move_id,
        )
    )
    wcs_source_refs = _dedupe((*inputs.director_move.wcs_source_refs, *inputs.wcs.source_refs))
    blocked_reasons = _blocked_reasons(inputs, reason_code)
    public_policy = ScrimGesturePublicClaimPolicy(
        inherited_public_claim_allowed=public_claim_allowed,
        scrim_public_claim_allowed=public_claim_allowed,
        basis_refs=_public_claim_basis_refs(inputs) if public_claim_allowed else (),
    )
    gesture = ScrimGestureRecord(
        gesture_id=f"scrim_gesture:{inputs.fixture_id}",
        gesture_type=gesture_type,
        gesture_effect=gesture_effect,
        created_at=inputs.director_move.emitted_at,
        ttl_s=caps.ttl_s,
        intensity=intensity,
        execution=execution,
        target_lane_ref=inputs.target_lane_ref,
        target_region_refs=inputs.target_region_refs,
        source_move_refs=source_move_refs,
        director_decision_id=inputs.director_move.decision_id,
        director_verb=inputs.director_move.verb,
        wcs_snapshot_ref=inputs.wcs.wcs_snapshot_ref,
        wcs_source_refs=wcs_source_refs,
        freshness_state=_strictest_freshness(
            inputs.director_move.freshness.state, inputs.wcs.freshness_state
        ),
        fallback_mode=inputs.wcs.fallback_mode,
        fallback_behavior=fallback_behavior,
        public_claim_policy=public_policy,
        caps=caps,
        reason=inputs.reason or reason_code,
        audit_refs=(inputs.director_move.audit_event.payload_ref,),
        blocked_reasons=blocked_reasons,
    )
    audit = DirectorScrimGestureAuditRecord(
        audit_id=f"director_scrim_gesture:{inputs.fixture_id}",
        created_at=inputs.director_move.emitted_at,
        director_decision_id=inputs.director_move.decision_id,
        director_payload_ref=inputs.director_move.audit_event.payload_ref,
        gesture_id=gesture.gesture_id,
        verb=inputs.director_move.verb,
        outcome=outcome,
        execution=execution,
        reason_code=reason_code,
        wcs_snapshot_ref=inputs.wcs.wcs_snapshot_ref,
        source_refs=_dedupe((*source_move_refs, *wcs_source_refs)),
        freshness_state=gesture.freshness_state,
        fallback_mode=inputs.wcs.fallback_mode,
        public_claim_allowed=public_claim_allowed,
        operator_visible=_operator_visible(inputs, outcome, execution),
    )
    projection = DirectorScrimGestureProjection(
        projection_id=f"director_scrim_gesture_projection:{inputs.fixture_id}",
        fixture_id=inputs.fixture_id,
        scrim_state_ref=inputs.scrim_state_ref,
        health_ref=inputs.health_ref,
        gesture=gesture,
        audit_record=audit,
    )
    if inputs.expected is not None:
        _assert_expected_projection(inputs, projection)
    return projection


def _assert_expected_projection(
    inputs: DirectorScrimGestureInput,
    projection: DirectorScrimGestureProjection,
) -> None:
    expected = inputs.expected
    if expected is None:
        return
    actual = projection.audit_record
    gesture = projection.gesture
    mismatches: list[str] = []
    if actual.outcome != expected.outcome:
        mismatches.append(f"outcome:{actual.outcome}!={expected.outcome}")
    if actual.execution != expected.execution:
        mismatches.append(f"execution:{actual.execution}!={expected.execution}")
    if gesture.gesture_type != expected.gesture_type:
        mismatches.append(f"gesture_type:{gesture.gesture_type}!={expected.gesture_type}")
    if gesture.gesture_effect != expected.gesture_effect:
        mismatches.append(f"gesture_effect:{gesture.gesture_effect}!={expected.gesture_effect}")
    if gesture.fallback_behavior != expected.fallback_behavior:
        mismatches.append(
            f"fallback_behavior:{gesture.fallback_behavior}!={expected.fallback_behavior}"
        )
    if gesture.public_claim_policy.scrim_public_claim_allowed != expected.public_claim_allowed:
        mismatches.append("public_claim_allowed mismatch")
    if actual.reason_code != expected.reason_code:
        mismatches.append(f"reason_code:{actual.reason_code}!={expected.reason_code}")
    if mismatches:
        raise ValueError(
            f"{inputs.fixture_id} expected projection mismatch: {', '.join(mismatches)}"
        )


def _select_outcome(
    inputs: DirectorScrimGestureInput,
) -> tuple[GestureAuditOutcome, GestureExecution, str]:
    move = inputs.director_move
    wcs = inputs.wcs

    if move.verb == "hold" and not (inputs.target_lane_ref and inputs.reason):
        return "rejected", "no_op", "hold_requires_target_lane_and_reason"
    if wcs.status in BLOCKED_STATUSES:
        if move.verb in RISKY_VISIBILITY_VERBS:
            return "rejected", "no_op", "blocked_target_cannot_be_prominent"
        if move.verb == "suppress":
            return "fallback", "suppress", "blocked_target_suppressed"
        if wcs.fallback_mode == "operator_reason":
            return "fallback", "operator_reason", "operator_reason_required"
        return "fallback", "hold_last_safe", "blocked_target_hold_last_safe"
    if wcs.status == "private" or wcs.evidence_status == "private_only":
        return "private_only", "dry_run", "private_only_target"
    if wcs.status == "dry_run" or move.execution_state == "dry_run":
        return "dry_run", "dry_run", "dry_run_only"
    if wcs.status in DEGRADED_STATUSES or wcs.freshness_state != "fresh":
        if move.verb == "crossfade":
            return "fallback", "hold_last_safe", "crossfade_stale_side_hold_last_safe"
        return "stale", "hold_last_safe", "stale_evidence_hold_last_safe"
    if wcs.fallback_mode == "degraded_status":
        return "fallback", "hold_last_safe", "degraded_status_hold_last_safe"
    return "accepted", "gesture", "accepted"


def _gesture_shape(
    inputs: DirectorScrimGestureInput,
    outcome: GestureAuditOutcome,
    execution: GestureExecution,
) -> tuple[ScrimStateGestureType, ScrimGestureEffect]:
    verb = inputs.director_move.verb
    if execution == "no_op":
        return "neutral_hold", "neutral_hold"
    if execution == "dry_run" and verb != "mark_boundary":
        return "neutral_hold", "neutral_hold"
    if execution == "suppress":
        return "refusal_dim", "refusal_dim"
    if execution == "hold_last_safe":
        return "neutral_hold", "neutral_hold"
    if execution == "operator_reason":
        return "refusal_dim", "refusal_dim"
    if verb == "foreground":
        return "thin", "thin"
    if verb == "background":
        return "soften", "soften"
    if verb == "hold":
        return "neutral_hold", "neutral_hold"
    if verb == "suppress":
        return "refusal_dim", "refusal_dim"
    if verb == "transition":
        return "ripple", "ripple"
    if verb == "crossfade":
        return "shimmer", "shimmer"
    if verb == "intensify":
        return "thicken", "thicken"
    if verb == "stabilize":
        return "soften", "soften"
    if verb == "route_attention":
        return "clear_window", "clear_window"
    if verb == "mark_boundary":
        if inputs.request_pierce and outcome == "accepted":
            return "mark_boundary", "scrim.pierce"
        return "mark_boundary", "mark_boundary"
    raise AssertionError(f"unhandled director verb: {verb}")


def _fallback_behavior(
    inputs: DirectorScrimGestureInput,
    outcome: GestureAuditOutcome,
    execution: GestureExecution,
) -> ScrimFallbackBehavior:
    if execution == "no_op":
        return "no_op"
    if execution == "dry_run":
        return "dry_run_badge"
    if execution == "suppress" or outcome == "private_only":
        return "suppress_public_cue"
    if execution in {"hold_last_safe", "operator_reason"}:
        if inputs.wcs.fallback_mode == "degraded_status":
            return "minimum_density"
        return "neutral_hold"
    return "neutral_hold"


def _gesture_caps(
    inputs: DirectorScrimGestureInput,
    effect: ScrimGestureEffect,
    outcome: GestureAuditOutcome,
    execution: GestureExecution,
) -> ScrimGestureCaps:
    if execution == "no_op":
        return ScrimGestureCaps(
            ttl_s=5,
            density_delta=0.0,
            refraction_delta=0.0,
            focus_strength=0.0,
            pierce_requested=inputs.request_pierce,
        )
    if execution in {"dry_run", "hold_last_safe", "operator_reason"}:
        return ScrimGestureCaps(
            ttl_s=10,
            density_delta=0.0,
            refraction_delta=0.0,
            focus_strength=0.2,
            pierce_requested=inputs.request_pierce,
        )
    if execution == "suppress":
        return ScrimGestureCaps(
            ttl_s=12,
            density_delta=0.18,
            refraction_delta=-0.04,
            focus_strength=0.3,
            pierce_requested=inputs.request_pierce,
        )
    if effect == "scrim.pierce":
        return ScrimGestureCaps(
            ttl_s=6,
            density_delta=-0.12,
            refraction_delta=0.08,
            focus_strength=0.5,
            boundary_pulse_count=1,
            pierce_requested=True,
            pierce_allowed=outcome == "accepted" and inputs.director_move.verb == "mark_boundary",
            pierce_ttl_s=4,
        )
    verb = inputs.director_move.verb
    if verb == "foreground":
        return ScrimGestureCaps(
            ttl_s=14,
            density_delta=-0.18,
            refraction_delta=0.04,
            focus_strength=0.66,
        )
    if verb == "background":
        return ScrimGestureCaps(
            ttl_s=18,
            density_delta=0.12,
            refraction_delta=-0.03,
            focus_strength=0.22,
        )
    if verb == "hold":
        return ScrimGestureCaps(
            ttl_s=20, density_delta=0.0, refraction_delta=0.0, focus_strength=0.2
        )
    if verb == "transition":
        return ScrimGestureCaps(
            ttl_s=16,
            density_delta=0.08,
            refraction_delta=0.1,
            focus_strength=0.4,
        )
    if verb == "crossfade":
        return ScrimGestureCaps(
            ttl_s=16,
            density_delta=0.04,
            refraction_delta=0.12,
            focus_strength=0.48,
        )
    if verb == "intensify":
        return ScrimGestureCaps(
            ttl_s=12,
            density_delta=0.24,
            refraction_delta=0.12,
            focus_strength=0.6,
        )
    if verb == "stabilize":
        return ScrimGestureCaps(
            ttl_s=20,
            density_delta=-0.08,
            refraction_delta=-0.1,
            focus_strength=0.3,
        )
    if verb == "route_attention":
        return ScrimGestureCaps(
            ttl_s=10,
            density_delta=-0.1,
            refraction_delta=0.05,
            focus_strength=0.58,
        )
    if verb == "mark_boundary":
        return ScrimGestureCaps(
            ttl_s=8,
            density_delta=0.08,
            refraction_delta=0.08,
            focus_strength=0.45,
            boundary_pulse_count=2,
            pierce_requested=inputs.request_pierce,
        )
    return ScrimGestureCaps(ttl_s=10, density_delta=0.0, refraction_delta=0.0, focus_strength=0.2)


def _bounded_intensity(
    inputs: DirectorScrimGestureInput,
    outcome: GestureAuditOutcome,
    execution: GestureExecution,
    caps: ScrimGestureCaps,
) -> float:
    if execution == "no_op":
        return 0.0
    if outcome in {"rejected", "stale", "private_only", "dry_run"}:
        return round(min(inputs.requested_intensity, 0.28), 3)
    if execution in {"fallback", "hold_last_safe", "suppress", "operator_reason"}:
        return round(min(inputs.requested_intensity, 0.35), 3)
    if caps.pierce_allowed:
        return round(min(inputs.requested_intensity, 0.45), 3)
    return round(min(inputs.requested_intensity, 0.7), 3)


def _inherited_public_claim_allowed(
    inputs: DirectorScrimGestureInput,
    outcome: GestureAuditOutcome,
    execution: GestureExecution,
) -> bool:
    return (
        outcome == "accepted"
        and execution == "gesture"
        and inputs.director_move.public_claim_allowed
        and inputs.wcs.public_claim_allowed
        and inputs.director_move.freshness.state == "fresh"
        and inputs.wcs.freshness_state == "fresh"
    )


def _public_claim_basis_refs(inputs: DirectorScrimGestureInput) -> tuple[str, ...]:
    return _dedupe(
        (
            inputs.director_move.decision_id,
            inputs.director_move.audit_event.payload_ref,
            *inputs.wcs.source_refs,
        )
    )


def _strictest_freshness(
    move_state: DirectorFreshnessState, wcs_state: DirectorFreshnessState
) -> DirectorFreshnessState:
    order = {
        "missing": 0,
        "unknown": 1,
        "stale": 2,
        "not_applicable": 3,
        "fresh": 4,
    }
    return min((move_state, wcs_state), key=lambda state: order[state])


def _blocked_reasons(inputs: DirectorScrimGestureInput, reason_code: str) -> tuple[str, ...]:
    reasons = [*inputs.wcs.blocked_reasons, *inputs.director_move.freshness.blocking_refs]
    if reason_code != "accepted":
        reasons.append(reason_code)
    return _dedupe(reasons)


def _operator_visible(
    inputs: DirectorScrimGestureInput,
    outcome: GestureAuditOutcome,
    execution: GestureExecution,
) -> bool:
    return (
        inputs.director_move.fallback.operator_facing
        or execution in {"no_op", "operator_reason", "suppress"}
        or outcome in {"rejected", "fallback", "stale", "private_only", "dry_run"}
    )


__all__ = [
    "DIRECTOR_SCRIM_GESTURE_ADAPTER_FIXTURES",
    "FAIL_CLOSED_POLICY",
    "REQUIRED_AUDIT_OUTCOMES",
    "REQUIRED_DIRECTOR_VERBS",
    "DirectorControlMoveRef",
    "DirectorMoveAuditEventRef",
    "DirectorMoveFallbackRef",
    "DirectorMoveFreshnessRef",
    "DirectorMoveTargetRef",
    "DirectorScrimGestureAdapterError",
    "DirectorScrimGestureAuditRecord",
    "DirectorScrimGestureExpected",
    "DirectorScrimGestureFixtureSet",
    "DirectorScrimGestureInput",
    "DirectorScrimGestureProjection",
    "ScrimGestureCaps",
    "ScrimGesturePublicClaimPolicy",
    "ScrimGestureRecord",
    "WCSMoveRef",
    "load_director_scrim_gesture_fixtures",
    "project_director_scrim_gesture_input",
]
