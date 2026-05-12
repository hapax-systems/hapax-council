"""Scrim WCS claim-posture projection.

The scrim can express WCS posture, but it cannot create truth, rights, safety,
public status, live control, or monetization status. This module keeps that
boundary explicit for downstream director/compositor adapters.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from shared.livestream_role_state import LivestreamRoleState, PublicMode
from shared.world_surface_health import (
    AuthorityCeiling,
    FreshnessState,
    HealthStatus,
    PrivacyState,
    RightsState,
    SurfaceFamily,
    WitnessPolicy,
    WorldSurfaceHealthRecord,
    load_world_surface_health_fixtures,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIM_STATE_ENVELOPE_FIXTURES = REPO_ROOT / "config" / "scrim-state-envelope-fixtures.json"
SCRIM_WCS_CLAIM_POSTURE_FIXTURES = REPO_ROOT / "config" / "scrim-wcs-claim-posture-fixtures.json"

REQUIRED_FIXTURE_FAMILIES = frozenset(
    {
        "fresh_public_safe",
        "stale",
        "missing_witness",
        "private_only",
        "blocked_media",
        "audio_blocked",
        "refusal",
        "correction",
        "conversion_ready",
        "conversion_held",
    }
)

REQUIRED_BLOCKER_FAMILIES = frozenset(
    {
        "rights",
        "privacy_consent",
        "monetization",
        "egress",
        "audio",
        "public_event",
    }
)


class ScrimWCSClaimPostureError(ValueError):
    """Raised when scrim/WCS claim posture data cannot be loaded safely."""


type ScrimPublicPrivateModeValue = Literal[
    "private", "dry_run", "public_live", "public_archive", "public_monetizable"
]
type ScrimEvidenceStatus = Literal[
    "fresh", "stale", "missing", "unknown", "blocked", "private_only", "dry_run"
]
type ScrimHealthState = Literal[
    "healthy",
    "degraded",
    "blocked",
    "unsafe",
    "stale",
    "missing",
    "unknown",
    "private_only",
    "dry_run",
    "quiet_off_air",
    "candidate",
]
type ScrimClaimPosture = Literal[
    "fresh",
    "uncertain",
    "blocked",
    "private_only",
    "dry_run",
    "refusal",
    "correction",
    "conversion_ready",
    "conversion_held",
]
type ScrimFallbackMode = Literal[
    "none",
    "minimum_density",
    "neutral_hold",
    "suppress_public_cue",
    "dry_run_badge",
    "operator_reason",
    "panic_clear_operator_only",
]
type BoundedScrimPosture = Literal[
    "local_clarity",
    "hold",
    "dry_run",
    "suppress_public_cue",
    "neutralize_blocked_media",
    "operator_reason",
    "refusal_artifact",
    "correction_boundary",
    "conversion_cue",
    "conversion_held",
]
type VisibilityTreatment = Literal[
    "bounded_local_clarity",
    "neutral_hold",
    "dry_run_badge",
    "public_cue_suppressed",
    "neutralized_metadata_first",
    "operator_reason_visible",
    "refusal_artifact_visible",
    "correction_boundary_visible",
    "conversion_cue_visible",
    "conversion_held_visible",
]
type ConversionCue = Literal["none", "ready", "held"]
type BlockerFamily = Literal[
    "evidence",
    "freshness",
    "health",
    "missing_witness",
    "rights",
    "privacy_consent",
    "monetization",
    "egress",
    "audio",
    "public_event",
]
type MediaVisibility = Literal[
    "not_applicable",
    "active",
    "neutralized_metadata_first",
    "suppressed_public_cue",
]


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ScrimStateEnvelopeRef(BaseModel):
    """Fields consumed from the upstream ScrimStateEnvelope.

    The upstream envelope has additional visual fields owned by the scrim state
    contract. This adapter deliberately reads only the posture/gating subset.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    schema_version: Literal[1]
    state_id: str
    public_private_mode: ScrimPublicPrivateModeValue
    evidence_status: ScrimEvidenceStatus
    health_state: ScrimHealthState
    claim_posture: ScrimClaimPosture
    blocked_reasons: tuple[str, ...] = Field(default_factory=tuple)
    source_refs: tuple[str, ...] = Field(default_factory=tuple)
    director_move_refs: tuple[str, ...] = Field(default_factory=tuple)
    boundary_event_refs: tuple[str, ...] = Field(default_factory=tuple)
    wcs_snapshot_ref: str
    health_ref: str
    fallback_mode: ScrimFallbackMode
    public_claim_allowed: bool
    public_claim_basis_refs: tuple[str, ...] = Field(default_factory=tuple)


class WCSClaimReference(FrozenModel):
    """Runtime WCS claim posture reference consumed by the scrim gate."""

    wcs_snapshot_ref: str
    capability_refs: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    grounding_gate_refs: tuple[str, ...] = Field(default_factory=tuple)
    public_event_refs: tuple[str, ...] = Field(default_factory=tuple)
    authority_ceiling: AuthorityCeiling
    public_claim_allowed: bool
    rights_state: RightsState
    privacy_state: PrivacyState
    egress_public: bool
    monetization_allowed: bool
    blocked_reasons: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _public_claims_need_public_refs(self) -> Self:
        if self.public_claim_allowed:
            missing: list[str] = []
            if not self.evidence_refs:
                missing.append("evidence_refs")
            if not self.grounding_gate_refs:
                missing.append("grounding_gate_refs")
            if not self.public_event_refs:
                missing.append("public_event_refs")
            if self.rights_state is not RightsState.PUBLIC_CLEAR:
                missing.append(f"rights_state:{self.rights_state.value}")
            if self.privacy_state is not PrivacyState.PUBLIC_SAFE:
                missing.append(f"privacy_state:{self.privacy_state.value}")
            if not self.egress_public:
                missing.append("egress_public:false")
            if missing:
                raise ValueError(
                    "WCS public_claim_allowed requires public evidence refs: " + ", ".join(missing)
                )
        return self


class EvidenceReference(FrozenModel):
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    source_refs: tuple[str, ...] = Field(default_factory=tuple)
    witness_refs: tuple[str, ...] = Field(default_factory=tuple)
    freshness_state: FreshnessState
    confidence: float = Field(ge=0.0, le=1.0)
    observed_age_s: int | None = Field(default=None, ge=0)
    ttl_s: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _fresh_evidence_needs_refs_and_age(self) -> Self:
        if self.freshness_state is FreshnessState.FRESH:
            if not self.evidence_refs or not self.witness_refs:
                raise ValueError("fresh evidence requires evidence_refs and witness_refs")
            if self.ttl_s is None or self.observed_age_s is None:
                raise ValueError("fresh evidence requires ttl_s and observed_age_s")
            if self.observed_age_s > self.ttl_s:
                raise ValueError("fresh evidence observed_age_s cannot exceed ttl_s")
        return self


class ScrimWCSClaimPostureInput(FrozenModel):
    scenario_id: str
    fixture_family: str
    scrim_state: ScrimStateEnvelopeRef
    wcs: WCSClaimReference
    health: WorldSurfaceHealthRecord
    evidence: EvidenceReference
    contains_media_surface: bool = False
    conversion_cue: ConversionCue = "none"
    engagement_pressure: float = Field(default=0.0, ge=0.0, le=1.0)
    trend_pressure: float = Field(default=0.0, ge=0.0, le=1.0)
    revenue_pressure: float = Field(default=0.0, ge=0.0, le=1.0)
    spectacle_intensity_requested: float = Field(default=0.0, ge=0.0, le=1.0)
    livestream_role_state: LivestreamRoleState | None = None

    @model_validator(mode="after")
    def _role_state_must_match_scrim_posture(self) -> Self:
        if self.livestream_role_state is None:
            return self
        expected_mode = _scrim_mode_for_role(self.livestream_role_state.public_mode)
        if self.scrim_state.public_private_mode != expected_mode:
            raise ValueError("scrim public_private_mode must mirror livestream role public_mode")
        if self.conversion_cue == "ready" and not self.livestream_role_state.monetization_ready:
            raise ValueError("conversion-ready scrim posture requires monetization-ready role")
        return self


class ScrimNoGrantPolicy(FrozenModel):
    scrim_grants_truth: Literal[False] = False
    scrim_grants_rights: Literal[False] = False
    scrim_grants_safety: Literal[False] = False
    scrim_grants_public_status: Literal[False] = False
    scrim_grants_monetization_status: Literal[False] = False
    scrim_grants_live_control: Literal[False] = False
    conversion_cue_is_truth_signal: Literal[False] = False
    engagement_pressure_is_truth_signal: Literal[False] = False
    trend_pressure_is_truth_signal: Literal[False] = False
    revenue_pressure_is_truth_signal: Literal[False] = False
    spectacle_intensity_is_truth_signal: Literal[False] = False


class ScrimWCSClaimPostureProjection(FrozenModel):
    """Bounded visual posture derived from WCS, evidence, and health refs."""

    schema_version: Literal[1] = 1
    projection_id: str
    scenario_id: str
    scrim_state_ref: str
    wcs_snapshot_ref: str
    health_ref: str
    capability_refs: tuple[str, ...]
    source_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    witness_refs: tuple[str, ...]
    posture: BoundedScrimPosture
    visibility_treatment: VisibilityTreatment
    media_visibility: MediaVisibility
    blocker_families: tuple[BlockerFamily, ...]
    blocked_reasons: tuple[str, ...]
    visible_blocker_refs: tuple[str, ...]
    public_claim_allowed: bool
    inherited_public_claim_allowed: bool
    authority_ceiling: AuthorityCeiling
    evidence_freshness: FreshnessState
    health_status: HealthStatus
    visual_confidence: float = Field(ge=0.0, le=1.0)
    max_visual_confidence: float = Field(ge=0.0, le=1.0)
    local_clarity: float = Field(ge=0.0, le=1.0)
    conversion_cue: ConversionCue
    truth_signal_refs: tuple[str, ...]
    non_truth_signal_refs: tuple[str, ...]
    spectacle_intensity: float = Field(ge=0.0, le=1.0)
    blocked_media_neutralized: bool
    no_grant_policy: ScrimNoGrantPolicy = Field(default_factory=ScrimNoGrantPolicy)

    @model_validator(mode="after")
    def _validate_no_claim_expansion(self) -> Self:
        if self.visual_confidence > self.max_visual_confidence:
            raise ValueError("visual confidence cannot exceed authority/freshness ceiling")
        if self.public_claim_allowed and self.blocker_families:
            raise ValueError("blocked scrim posture cannot allow public claims")
        if self.public_claim_allowed and not self.inherited_public_claim_allowed:
            raise ValueError("scrim public claim flag must be inherited from WCS/health")
        if self.posture == "neutralize_blocked_media":
            if not self.blocked_media_neutralized:
                raise ValueError("blocked media posture must mark media as neutralized")
            if self.media_visibility != "neutralized_metadata_first":
                raise ValueError("blocked media must be metadata-first, not hidden spectacle")
            if self.spectacle_intensity > 0.2:
                raise ValueError("blocked media cannot intensify into spectacle")
        forbidden_truth_prefixes = ("engagement:", "trend:", "revenue:", "spectacle:")
        if any(ref.startswith(forbidden_truth_prefixes) for ref in self.truth_signal_refs):
            raise ValueError("engagement/trend/revenue/spectacle cannot be truth signals")
        return self


class ExpectedProjection(FrozenModel):
    posture: BoundedScrimPosture
    visibility_treatment: VisibilityTreatment
    public_claim_allowed: bool
    blocker_families: tuple[BlockerFamily, ...] = Field(default_factory=tuple)
    media_visibility: MediaVisibility = "not_applicable"


class ScrimWCSClaimPostureFixture(FrozenModel):
    fixture_id: str
    family: str
    scrim_fixture_family: str
    health_surface_id: str
    contains_media_surface: bool = False
    conversion_cue: ConversionCue = "none"
    engagement_pressure: float = Field(default=0.0, ge=0.0, le=1.0)
    trend_pressure: float = Field(default=0.0, ge=0.0, le=1.0)
    revenue_pressure: float = Field(default=0.0, ge=0.0, le=1.0)
    spectacle_intensity_requested: float = Field(default=0.0, ge=0.0, le=1.0)
    wcs: WCSClaimReference
    evidence: EvidenceReference
    expected: ExpectedProjection


class ScrimWCSClaimPostureFixtureSet(FrozenModel):
    schema_version: Literal[1]
    fixture_set_id: str
    schema_ref: Literal["schemas/scrim-wcs-claim-posture.schema.json"]
    generated_from: tuple[str, ...] = Field(min_length=1)
    declared_at: str
    producer: str
    families: tuple[str, ...] = Field(min_length=1)
    fail_closed_policy: dict[str, bool]
    fixtures: tuple[ScrimWCSClaimPostureFixture, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_fixture_contract(self) -> Self:
        if set(self.families) != REQUIRED_FIXTURE_FAMILIES:
            raise ValueError("scrim WCS posture fixture families do not match required set")
        fixture_families = {fixture.family for fixture in self.fixtures}
        if fixture_families != REQUIRED_FIXTURE_FAMILIES:
            raise ValueError("scrim WCS posture fixtures do not cover required families")
        observed_blocker_families = {
            blocker for fixture in self.fixtures for blocker in fixture.expected.blocker_families
        }
        missing_blockers = REQUIRED_BLOCKER_FAMILIES - observed_blocker_families
        if missing_blockers:
            raise ValueError(
                "scrim WCS posture fixtures miss blocker families: "
                + ", ".join(sorted(missing_blockers))
            )
        if self.fail_closed_policy != {
            "scrim_grants_truth": False,
            "scrim_grants_rights": False,
            "scrim_grants_safety": False,
            "scrim_grants_public_status": False,
            "scrim_grants_monetization_status": False,
            "conversion_cue_is_truth_signal": False,
            "engagement_trend_revenue_spectacle_are_truth_signals": False,
            "blocked_media_hidden_under_spectacle": False,
        }:
            raise ValueError("fail_closed_policy must pin every no-grant gate false")
        return self

    def projections(self) -> tuple[ScrimWCSClaimPostureProjection, ...]:
        """Build projections for every fixture."""

        return tuple(
            project_scrim_claim_posture_input(resolve_fixture(fixture)) for fixture in self.fixtures
        )


def _dedupe(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScrimWCSClaimPostureError(f"invalid JSON at {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ScrimWCSClaimPostureError(f"{path} did not contain a JSON object")
    return payload


@cache
def _scrim_envelopes_by_family(
    path: Path = SCRIM_STATE_ENVELOPE_FIXTURES,
) -> dict[str, ScrimStateEnvelopeRef]:
    payload = _load_json_object(path)
    fixtures = payload.get("fixtures")
    if not isinstance(fixtures, list):
        raise ScrimWCSClaimPostureError("scrim state fixtures missing fixtures[]")

    resolved: dict[str, ScrimStateEnvelopeRef] = {}
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise ScrimWCSClaimPostureError("scrim fixture entry was not an object")
        family = fixture.get("family")
        envelope = fixture.get("envelope")
        if not isinstance(family, str) or not isinstance(envelope, dict):
            raise ScrimWCSClaimPostureError("scrim fixture missing family/envelope")
        resolved[family] = ScrimStateEnvelopeRef.model_validate(envelope)
    return resolved


def load_scrim_wcs_claim_posture_fixtures(
    path: Path = SCRIM_WCS_CLAIM_POSTURE_FIXTURES,
) -> ScrimWCSClaimPostureFixtureSet:
    """Load scrim/WCS claim-posture fixtures, failing closed on malformed data."""

    try:
        return ScrimWCSClaimPostureFixtureSet.model_validate(_load_json_object(path))
    except (ValidationError, ValueError) as exc:
        raise ScrimWCSClaimPostureError(
            f"invalid scrim WCS claim posture fixtures at {path}: {exc}"
        ) from exc


def resolve_fixture(fixture: ScrimWCSClaimPostureFixture) -> ScrimWCSClaimPostureInput:
    """Resolve fixture references into the actual ScrimStateEnvelope and health record."""

    scrim_by_family = _scrim_envelopes_by_family()
    try:
        scrim_state = scrim_by_family[fixture.scrim_fixture_family]
    except KeyError as exc:
        raise ScrimWCSClaimPostureError(
            f"unknown scrim fixture family: {fixture.scrim_fixture_family}"
        ) from exc

    health = load_world_surface_health_fixtures().require_surface(fixture.health_surface_id)
    return ScrimWCSClaimPostureInput(
        scenario_id=fixture.fixture_id,
        fixture_family=fixture.family,
        scrim_state=scrim_state,
        wcs=fixture.wcs,
        health=health,
        evidence=fixture.evidence,
        contains_media_surface=fixture.contains_media_surface,
        conversion_cue=fixture.conversion_cue,
        engagement_pressure=fixture.engagement_pressure,
        trend_pressure=fixture.trend_pressure,
        revenue_pressure=fixture.revenue_pressure,
        spectacle_intensity_requested=fixture.spectacle_intensity_requested,
    )


def project_fixture(
    fixture: ScrimWCSClaimPostureFixture,
) -> ScrimWCSClaimPostureProjection:
    """Build one projection from a fixture row."""

    return project_scrim_claim_posture_input(resolve_fixture(fixture))


def project_scrim_claim_posture_input(
    inputs: ScrimWCSClaimPostureInput,
) -> ScrimWCSClaimPostureProjection:
    """Project WCS/evidence/health state into bounded scrim visual posture."""

    blocker_families, blocked_reasons = _derive_blockers(inputs)
    posture = _select_posture(inputs, blocker_families)
    max_visual_confidence = _max_visual_confidence(inputs, blocker_families, posture)
    visual_confidence = round(
        min(inputs.evidence.confidence, inputs.health.confidence, max_visual_confidence), 3
    )

    inherited_public_claim_allowed = _inherited_public_claim_allowed(inputs, blocker_families)
    non_truth_refs = _non_truth_signal_refs(inputs)

    return ScrimWCSClaimPostureProjection(
        projection_id=f"scrim_wcs_claim_posture:{inputs.scenario_id}",
        scenario_id=inputs.scenario_id,
        scrim_state_ref=inputs.scrim_state.state_id,
        wcs_snapshot_ref=inputs.wcs.wcs_snapshot_ref,
        health_ref=inputs.health.surface_id,
        capability_refs=inputs.wcs.capability_refs,
        source_refs=_dedupe((*inputs.scrim_state.source_refs, *inputs.evidence.source_refs)),
        evidence_refs=_dedupe((*inputs.wcs.evidence_refs, *inputs.evidence.evidence_refs)),
        witness_refs=_dedupe((*inputs.health.witness_refs, *inputs.evidence.witness_refs)),
        posture=posture,
        visibility_treatment=_visibility_treatment(posture),
        media_visibility=_media_visibility(inputs, posture),
        blocker_families=blocker_families,
        blocked_reasons=blocked_reasons,
        visible_blocker_refs=_visible_blocker_refs(blocker_families, blocked_reasons),
        public_claim_allowed=inherited_public_claim_allowed,
        inherited_public_claim_allowed=inherited_public_claim_allowed,
        authority_ceiling=_strictest_authority(
            inputs.wcs.authority_ceiling, inputs.health.authority_ceiling
        ),
        evidence_freshness=_strictest_freshness(
            inputs.evidence.freshness_state, inputs.health.freshness.state
        ),
        health_status=inputs.health.status,
        visual_confidence=visual_confidence,
        max_visual_confidence=max_visual_confidence,
        local_clarity=_local_clarity(posture, max_visual_confidence),
        conversion_cue=inputs.conversion_cue,
        truth_signal_refs=_truth_signal_refs(inputs),
        non_truth_signal_refs=non_truth_refs,
        spectacle_intensity=_spectacle_intensity(inputs, blocker_families, posture),
        blocked_media_neutralized=posture == "neutralize_blocked_media",
    )


def _scrim_mode_for_role(public_mode: PublicMode) -> ScrimPublicPrivateModeValue:
    if public_mode is PublicMode.PUBLIC_LIVE:
        return "public_live"
    if public_mode is PublicMode.PUBLIC_ARCHIVE:
        return "public_archive"
    if public_mode is PublicMode.DRY_RUN:
        return "dry_run"
    return "private"


def _derive_blockers(
    inputs: ScrimWCSClaimPostureInput,
) -> tuple[tuple[BlockerFamily, ...], tuple[str, ...]]:
    families: list[BlockerFamily] = []
    reasons: list[str] = []

    def add(family: BlockerFamily, reason: str) -> None:
        families.append(family)
        reasons.append(reason)

    scrim = inputs.scrim_state
    health = inputs.health
    wcs = inputs.wcs
    evidence = inputs.evidence

    reasons.extend(scrim.blocked_reasons)
    reasons.extend(health.blocking_reasons)
    reasons.extend(wcs.blocked_reasons)

    if scrim.evidence_status in {"missing", "unknown", "blocked"} or not evidence.evidence_refs:
        add("evidence", f"evidence_status:{scrim.evidence_status}")
    if (
        evidence.freshness_state is not FreshnessState.FRESH
        or health.freshness.state is not FreshnessState.FRESH
        or scrim.evidence_status == "stale"
    ):
        add("freshness", f"freshness:{evidence.freshness_state.value}")
    if health.status is not HealthStatus.HEALTHY or scrim.health_state != "healthy":
        add("health", f"health:{health.status.value}")
    if health.witness_policy is not WitnessPolicy.WITNESSED or not evidence.witness_refs:
        add("missing_witness", f"witness_policy:{health.witness_policy.value}")
    if wcs.rights_state in {RightsState.BLOCKED, RightsState.MISSING, RightsState.UNKNOWN}:
        add("rights", f"rights_state:{wcs.rights_state.value}")
    if health.rights_state in {RightsState.BLOCKED, RightsState.MISSING, RightsState.UNKNOWN}:
        add("rights", f"health_rights_state:{health.rights_state.value}")
    if wcs.privacy_state in {
        PrivacyState.PRIVATE_ONLY,
        PrivacyState.BLOCKED,
        PrivacyState.UNKNOWN,
    }:
        add("privacy_consent", f"privacy_state:{wcs.privacy_state.value}")
    if health.privacy_state in {
        PrivacyState.PRIVATE_ONLY,
        PrivacyState.BLOCKED,
        PrivacyState.UNKNOWN,
    }:
        add("privacy_consent", f"health_privacy_state:{health.privacy_state.value}")
    if scrim.public_private_mode in {"public_live", "public_archive", "public_monetizable"}:
        if not wcs.egress_public:
            add("egress", "egress_public:false")
        if not wcs.public_event_refs:
            add("public_event", "public_event_refs:missing")
    if health.surface_family is SurfaceFamily.AUDIO and health.status is not HealthStatus.HEALTHY:
        audio_reason_text = " ".join((*health.blocking_reasons, *wcs.blocked_reasons))
        if any(token in audio_reason_text for token in ("audio", "broadcast", "leak", "route")):
            add("audio", f"audio_health:{health.status.value}")
    if inputs.conversion_cue != "none" and not wcs.monetization_allowed:
        add("monetization", "monetization_allowed:false")

    return _dedupe(families), _dedupe(reasons)


def _select_posture(
    inputs: ScrimWCSClaimPostureInput,
    blocker_families: tuple[BlockerFamily, ...],
) -> BoundedScrimPosture:
    scrim = inputs.scrim_state

    if scrim.claim_posture == "refusal":
        return "refusal_artifact"
    if scrim.claim_posture == "correction":
        return "correction_boundary"
    if inputs.contains_media_surface and (
        "rights" in blocker_families
        or "privacy_consent" in blocker_families
        or scrim.claim_posture == "blocked"
    ):
        return "neutralize_blocked_media"
    if inputs.conversion_cue == "held" or scrim.claim_posture == "conversion_held":
        return "conversion_held"
    if inputs.conversion_cue == "ready" or scrim.claim_posture == "conversion_ready":
        return "conversion_cue"
    if scrim.claim_posture == "blocked" and "health" in blocker_families:
        return "operator_reason"
    if scrim.public_private_mode == "private" or scrim.claim_posture == "private_only":
        return "suppress_public_cue"
    if scrim.public_private_mode == "dry_run" or scrim.claim_posture == "dry_run":
        return "dry_run"
    if "freshness" in blocker_families:
        return "hold"
    if "missing_witness" in blocker_families or "evidence" in blocker_families:
        return "dry_run"
    if blocker_families:
        return "operator_reason"
    return "local_clarity"


def _visibility_treatment(posture: BoundedScrimPosture) -> VisibilityTreatment:
    return {
        "local_clarity": "bounded_local_clarity",
        "hold": "neutral_hold",
        "dry_run": "dry_run_badge",
        "suppress_public_cue": "public_cue_suppressed",
        "neutralize_blocked_media": "neutralized_metadata_first",
        "operator_reason": "operator_reason_visible",
        "refusal_artifact": "refusal_artifact_visible",
        "correction_boundary": "correction_boundary_visible",
        "conversion_cue": "conversion_cue_visible",
        "conversion_held": "conversion_held_visible",
    }[posture]


def _media_visibility(
    inputs: ScrimWCSClaimPostureInput, posture: BoundedScrimPosture
) -> MediaVisibility:
    if not inputs.contains_media_surface:
        return "not_applicable"
    if posture == "neutralize_blocked_media":
        return "neutralized_metadata_first"
    if posture == "suppress_public_cue":
        return "suppressed_public_cue"
    return "active"


def _inherited_public_claim_allowed(
    inputs: ScrimWCSClaimPostureInput,
    blocker_families: tuple[BlockerFamily, ...],
) -> bool:
    return (
        not blocker_families
        and inputs.scrim_state.public_claim_allowed
        and inputs.wcs.public_claim_allowed
        and inputs.health.public_claim_allowed
        and inputs.health.satisfies_claimable_health()
        and inputs.evidence.freshness_state is FreshnessState.FRESH
        and bool(inputs.evidence.evidence_refs)
        and bool(inputs.evidence.witness_refs)
    )


def _truth_signal_refs(inputs: ScrimWCSClaimPostureInput) -> tuple[str, ...]:
    return _dedupe(
        (
            *inputs.wcs.evidence_refs,
            *inputs.wcs.grounding_gate_refs,
            *inputs.evidence.evidence_refs,
            *inputs.evidence.witness_refs,
            *inputs.health.witness_refs,
        )
    )


def _non_truth_signal_refs(inputs: ScrimWCSClaimPostureInput) -> tuple[str, ...]:
    refs: list[str] = []
    if inputs.engagement_pressure:
        refs.append(f"engagement:{inputs.engagement_pressure:.2f}")
    if inputs.trend_pressure:
        refs.append(f"trend:{inputs.trend_pressure:.2f}")
    if inputs.revenue_pressure:
        refs.append(f"revenue:{inputs.revenue_pressure:.2f}")
    if inputs.spectacle_intensity_requested:
        refs.append(f"spectacle:{inputs.spectacle_intensity_requested:.2f}")
    if inputs.conversion_cue != "none":
        refs.append(f"conversion:{inputs.conversion_cue}")
    return tuple(refs)


def _visible_blocker_refs(
    blocker_families: tuple[BlockerFamily, ...], blocked_reasons: tuple[str, ...]
) -> tuple[str, ...]:
    if not blocker_families:
        return ()
    if not blocked_reasons:
        return tuple(f"{family}:unspecified" for family in blocker_families)
    return tuple(f"{family}:{reason}" for family in blocker_families for reason in blocked_reasons)


def _strictest_authority(left: AuthorityCeiling, right: AuthorityCeiling) -> AuthorityCeiling:
    order = {
        AuthorityCeiling.NO_CLAIM: 0,
        AuthorityCeiling.INTERNAL_ONLY: 1,
        AuthorityCeiling.SPECULATIVE: 2,
        AuthorityCeiling.EVIDENCE_BOUND: 3,
        AuthorityCeiling.POSTERIOR_BOUND: 4,
        AuthorityCeiling.PUBLIC_GATE_REQUIRED: 5,
    }
    return left if order[left] <= order[right] else right


def _strictest_freshness(left: FreshnessState, right: FreshnessState) -> FreshnessState:
    order = {
        FreshnessState.MISSING: 0,
        FreshnessState.UNKNOWN: 1,
        FreshnessState.STALE: 2,
        FreshnessState.NOT_APPLICABLE: 3,
        FreshnessState.FRESH: 4,
    }
    return left if order[left] <= order[right] else right


def _authority_confidence_cap(authority: AuthorityCeiling) -> float:
    return {
        AuthorityCeiling.NO_CLAIM: 0.0,
        AuthorityCeiling.INTERNAL_ONLY: 0.15,
        AuthorityCeiling.SPECULATIVE: 0.25,
        AuthorityCeiling.EVIDENCE_BOUND: 0.45,
        AuthorityCeiling.POSTERIOR_BOUND: 0.55,
        AuthorityCeiling.PUBLIC_GATE_REQUIRED: 0.65,
    }[authority]


def _freshness_confidence_cap(freshness: FreshnessState) -> float:
    return {
        FreshnessState.FRESH: 1.0,
        FreshnessState.STALE: 0.25,
        FreshnessState.MISSING: 0.0,
        FreshnessState.UNKNOWN: 0.05,
        FreshnessState.NOT_APPLICABLE: 0.2,
    }[freshness]


def _health_confidence_cap(status: HealthStatus) -> float:
    return {
        HealthStatus.HEALTHY: 1.0,
        HealthStatus.DEGRADED: 0.45,
        HealthStatus.BLOCKED: 0.1,
        HealthStatus.UNSAFE: 0.05,
        HealthStatus.STALE: 0.25,
        HealthStatus.MISSING: 0.0,
        HealthStatus.UNKNOWN: 0.05,
        HealthStatus.PRIVATE_ONLY: 0.25,
        HealthStatus.DRY_RUN: 0.3,
        HealthStatus.QUIET_OFF_AIR: 0.2,
        HealthStatus.CANDIDATE: 0.05,
    }[status]


def _mode_confidence_cap(public_private_mode: ScrimPublicPrivateModeValue) -> float:
    if public_private_mode == "private":
        return 0.2
    if public_private_mode == "dry_run":
        return 0.3
    return 1.0


def _max_visual_confidence(
    inputs: ScrimWCSClaimPostureInput,
    blocker_families: tuple[BlockerFamily, ...],
    posture: BoundedScrimPosture,
) -> float:
    strictest_authority = _strictest_authority(
        inputs.wcs.authority_ceiling, inputs.health.authority_ceiling
    )
    strictest_freshness = _strictest_freshness(
        inputs.evidence.freshness_state, inputs.health.freshness.state
    )
    cap = min(
        _authority_confidence_cap(strictest_authority),
        _freshness_confidence_cap(strictest_freshness),
        _health_confidence_cap(inputs.health.status),
        _mode_confidence_cap(inputs.scrim_state.public_private_mode),
    )
    if blocker_families:
        cap = min(cap, 0.35)
    if posture == "neutralize_blocked_media":
        cap = min(cap, 0.1)
    return round(cap, 3)


def _local_clarity(posture: BoundedScrimPosture, max_visual_confidence: float) -> float:
    if posture == "local_clarity":
        return round(min(0.62, max_visual_confidence), 3)
    if posture in {"refusal_artifact", "correction_boundary", "conversion_cue"}:
        return round(min(0.42, max_visual_confidence), 3)
    return round(min(0.2, max_visual_confidence), 3)


def _spectacle_intensity(
    inputs: ScrimWCSClaimPostureInput,
    blocker_families: tuple[BlockerFamily, ...],
    posture: BoundedScrimPosture,
) -> float:
    cap = 0.45
    if blocker_families:
        cap = 0.2
    if posture == "neutralize_blocked_media":
        cap = 0.16
    return round(min(inputs.spectacle_intensity_requested, cap), 3)


__all__ = [
    "REQUIRED_BLOCKER_FAMILIES",
    "REQUIRED_FIXTURE_FAMILIES",
    "SCRIM_STATE_ENVELOPE_FIXTURES",
    "SCRIM_WCS_CLAIM_POSTURE_FIXTURES",
    "EvidenceReference",
    "ExpectedProjection",
    "ScrimNoGrantPolicy",
    "ScrimStateEnvelopeRef",
    "ScrimWCSClaimPostureError",
    "ScrimWCSClaimPostureFixture",
    "ScrimWCSClaimPostureFixtureSet",
    "ScrimWCSClaimPostureInput",
    "ScrimWCSClaimPostureProjection",
    "WCSClaimReference",
    "load_scrim_wcs_claim_posture_fixtures",
    "project_fixture",
    "project_scrim_claim_posture_input",
    "resolve_fixture",
]
