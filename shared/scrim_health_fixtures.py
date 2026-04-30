"""Typed scrim health fixtures for OQ-02 invariant contracts.

This is a fixture/contract adapter, not a live compositor health probe. It
turns scrim invariant fixture rows into the two downstream shapes that already
exist in the repo: ``ScrimStateEnvelopeRef`` and ``WorldSurfaceHealthRecord``.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from shared.scrim_wcs_claim_posture import ScrimStateEnvelopeRef
from shared.world_surface_health import (
    AuthorityCeiling,
    FallbackMode,
    FixtureCase,
    FreshnessState,
    HealthDimensionId,
    HealthDimensionState,
    HealthStatus,
    KillSwitchStatus,
    PrivacyState,
    PublicPrivatePosture,
    RightsState,
    SurfaceFamily,
    WitnessPolicy,
    WorldSurfaceHealthRecord,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIM_HEALTH_FIXTURES = REPO_ROOT / "config" / "scrim-health-fixtures.json"

REQUIRED_SCRIM_HEALTH_FIXTURE_FAMILIES = frozenset(
    {
        "anti_recognition_upstream_obscure",
        "scrim_translucency_nominal",
        "anti_visualizer_structural_motion",
        "pixel_sort_dominance_blocked",
        "stale_state",
        "minimum_density_fallback",
        "hothouse_high_texture",
        "listening_quiet",
        "music_reactive_structural",
    }
)
FORBIDDEN_AUDIO_MODULATION_REGISTERS = frozenset(
    {"waveform", "fft", "spectrum_bars", "beat_iconography"}
)

type ScrimHealthFixtureFamily = Literal[
    "anti_recognition_upstream_obscure",
    "scrim_translucency_nominal",
    "anti_visualizer_structural_motion",
    "pixel_sort_dominance_blocked",
    "stale_state",
    "minimum_density_fallback",
    "hothouse_high_texture",
    "listening_quiet",
    "music_reactive_structural",
]
type AudioModulationRegister = Literal[
    "none",
    "structural_texture",
    "structural_motion",
    "waveform",
    "fft",
    "spectrum_bars",
    "beat_iconography",
]
type ScrimProfile = Literal[
    "gauzy_quiet",
    "warm_haze",
    "moire_crackle",
    "clarity_peak",
    "dissolving",
    "ritual_open",
    "rain_streak",
]
type PermeabilityMode = Literal["semipermeable_membrane", "solute_suspension", "ionised_glow"]


class ScrimHealthFixtureError(ValueError):
    """Raised when scrim health fixtures cannot be loaded safely."""


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ScrimHealthNoAuthorityPolicy(FrozenModel):
    """Policy pins that keep scrim health from becoming claim authority."""

    scrim_health_grants_truth: Literal[False]
    scrim_health_grants_rights: Literal[False]
    scrim_health_grants_safety: Literal[False]
    scrim_health_grants_public_status: Literal[False]
    scrim_health_grants_monetization_status: Literal[False]
    scrim_health_counts_as_privacy_protection: Literal[False]
    face_obscure_remains_upstream_privacy_protection: Literal[True]
    audio_reactivity_can_be_structural_only: Literal[True]


class ScrimHealthDimensionRef(FrozenModel):
    dimension: HealthDimensionId
    state: HealthDimensionState
    required_for_claimable: bool
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    note: str


class ScrimHealthFreshnessRef(FrozenModel):
    state: FreshnessState
    ttl_s: int | None = Field(default=None, ge=0)
    observed_age_s: int | None = Field(default=None, ge=0)
    source_ref: str | None = None
    checked_at: str


class ScrimInvariantScores(FrozenModel):
    anti_recognition_passed: bool
    anti_recognition_similarity: float | None = Field(default=None, ge=-1.0, le=1.0)
    face_obscure_upstream_ref: str | None = None
    translucency_score: float = Field(ge=0.0, le=1.0)
    translucency_minimum: float = Field(ge=0.0, le=1.0)
    anti_visualizer_score: float = Field(ge=0.0, le=1.0)
    anti_visualizer_maximum: float = Field(ge=0.0, le=1.0)
    audio_reactive: bool
    audio_modulation_register: AudioModulationRegister
    pixel_sort_dominance: float = Field(ge=0.0, le=1.0)
    pixel_sort_dominance_maximum: float = Field(ge=0.0, le=1.0)
    density: float = Field(ge=0.0, le=1.0)
    minimum_density: float = Field(ge=0.0, le=1.0)
    motion_rate: float = Field(ge=0.0, le=1.0)
    max_motion_rate: float = Field(ge=0.0, le=1.0)
    structural_texture_motion: bool

    @model_validator(mode="after")
    def _validate_register_and_caps(self) -> Self:
        if self.audio_modulation_register in FORBIDDEN_AUDIO_MODULATION_REGISTERS:
            raise ValueError(
                "audio modulation entered forbidden visualizer register: "
                f"{self.audio_modulation_register}"
            )
        if self.audio_reactive and not self.structural_texture_motion:
            raise ValueError("audio-reactive scrim health must be structural texture/motion")
        if self.density < self.minimum_density:
            raise ValueError("scrim density cannot fall below declared minimum density")
        if self.motion_rate > self.max_motion_rate:
            raise ValueError("scrim motion_rate exceeds fixture cap")
        return self

    def clears_primary_bounds(self) -> bool:
        """Return true when B1/B2/B3 and pixel-sort caps all pass."""

        return (
            self.anti_recognition_passed
            and self.translucency_score >= self.translucency_minimum
            and self.anti_visualizer_score <= self.anti_visualizer_maximum
            and self.pixel_sort_dominance <= self.pixel_sort_dominance_maximum
        )


class ScrimHealthWorldSurfaceRef(FrozenModel):
    surface_id: str
    surface_family: SurfaceFamily = SurfaceFamily.VISUAL
    status: HealthStatus
    fixture_case: FixtureCase
    health_dimensions: tuple[ScrimHealthDimensionRef, ...] = Field(min_length=1)
    freshness: ScrimHealthFreshnessRef
    confidence: float = Field(ge=0.0, le=1.0)
    authority_ceiling: AuthorityCeiling = AuthorityCeiling.NO_CLAIM
    privacy_state: PrivacyState
    rights_state: RightsState
    public_private_posture: PublicPrivatePosture
    witness_policy: WitnessPolicy
    blocking_reasons: tuple[str, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    fallback_mode: FallbackMode
    fallback_reason_code: str
    fallback_operator_reason: str
    fallback_safe_state: str
    kill_switch_state: KillSwitchStatus = KillSwitchStatus.NOT_APPLICABLE
    producer_refs: tuple[str, ...] = Field(default=("producer:studio-compositor:scrim",))
    consumer_refs: tuple[str, ...] = Field(
        default=("consumer:scrim-state-envelope", "consumer:world-surface-health")
    )
    route_refs: tuple[str, ...] = Field(default=("route:visual.scrim",))
    substrate_refs: tuple[str, ...] = Field(default=("substrate:nebulous-scrim",))
    capability_refs: tuple[str, ...] = Field(default=("capability:scrim.health",))
    source_refs: tuple[str, ...] = Field(default=("source:oq02-scrim-invariants",))
    evidence_envelope_refs: tuple[str, ...] = Field(default_factory=tuple)
    outcome_envelope_refs: tuple[str, ...] = Field(default_factory=tuple)
    witness_refs: tuple[str, ...] = Field(default_factory=tuple)
    owner: str = "cx-amber"
    next_probe_due_at: str

    @model_validator(mode="after")
    def _validate_no_public_claim_authority(self) -> Self:
        if self.authority_ceiling is not AuthorityCeiling.NO_CLAIM:
            raise ValueError("scrim health fixtures must keep authority_ceiling=no_claim")
        if self.surface_family is not SurfaceFamily.VISUAL:
            raise ValueError("scrim health fixtures must remain visual surface records")
        return self


class ScrimHealthExpectedOutcome(FrozenModel):
    scrim_health_passed: bool
    public_confidence_cue_allowed: bool
    foreground_gestures_required: bool
    foreground_gesture_refs: tuple[str, ...] = Field(default_factory=tuple)
    minimum_density_fallback_required: bool
    scrim_counts_as_privacy_protection: Literal[False]
    face_obscure_upstream_required: bool
    public_claim_allowed: Literal[False]
    monetization_allowed: Literal[False]

    @model_validator(mode="after")
    def _foreground_gestures_are_named_when_required(self) -> Self:
        if self.foreground_gestures_required and not self.foreground_gesture_refs:
            raise ValueError("foreground_gestures_required needs foreground_gesture_refs")
        if self.minimum_density_fallback_required and self.public_confidence_cue_allowed:
            raise ValueError("minimum-density fallback strips public confidence cues")
        return self


class ScrimHealthFixture(FrozenModel):
    family: ScrimHealthFixtureFamily
    description: str
    profile_id: ScrimProfile
    permeability_mode: PermeabilityMode
    texture_family: str
    scrim_state: ScrimStateEnvelopeRef
    world_surface: ScrimHealthWorldSurfaceRef
    invariants: ScrimInvariantScores
    expected: ScrimHealthExpectedOutcome
    consumed_by: tuple[Literal["ScrimStateEnvelope", "WorldSurfaceHealthRecord"], ...]

    @model_validator(mode="after")
    def _validate_fixture_contract(self) -> Self:
        if self.scrim_state.health_ref != self.world_surface.surface_id:
            raise ValueError("scrim_state.health_ref must match world_surface.surface_id")
        if self.scrim_state.public_claim_allowed:
            raise ValueError("scrim health fixtures cannot set scrim public_claim_allowed")
        if "ScrimStateEnvelope" not in self.consumed_by:
            raise ValueError("fixture must declare ScrimStateEnvelope consumption")
        if "WorldSurfaceHealthRecord" not in self.consumed_by:
            raise ValueError("fixture must declare WorldSurfaceHealthRecord consumption")

        if self.expected.face_obscure_upstream_required and not (
            self.invariants.face_obscure_upstream_ref
            and self.invariants.face_obscure_upstream_ref in self.world_surface.source_refs
        ):
            raise ValueError("face-obscure privacy protection must be upstream and referenced")

        if self.expected.scrim_health_passed and not self.invariants.clears_primary_bounds():
            raise ValueError("passing scrim health fixture has failing invariant scores")
        if not self.expected.scrim_health_passed:
            if self.world_surface.status is HealthStatus.HEALTHY:
                raise ValueError("failing scrim health fixture cannot be a healthy WCS record")
            if self.expected.public_confidence_cue_allowed:
                raise ValueError("failing scrim health strips public confidence cues")
            if not self.expected.foreground_gestures_required:
                raise ValueError("failing scrim health must foreground diagnostic gestures")

        if self.invariants.pixel_sort_dominance > self.invariants.pixel_sort_dominance_maximum:
            if not self.expected.minimum_density_fallback_required:
                raise ValueError("pixel-sort dominance requires minimum-density fallback")
            if self.scrim_state.fallback_mode != "minimum_density":
                raise ValueError("pixel-sort dominance fallback must use minimum_density")

        if self.expected.minimum_density_fallback_required:
            if self.scrim_state.fallback_mode != "minimum_density":
                raise ValueError("minimum-density fallback fixture must expose fallback mode")
            if self.invariants.density > self.invariants.minimum_density:
                raise ValueError("minimum-density fallback density must be at the floor")

        if self.world_surface.status is HealthStatus.STALE:
            if self.world_surface.freshness.state is not FreshnessState.STALE:
                raise ValueError("stale scrim health fixture must carry stale freshness")
            if self.scrim_state.fallback_mode not in {"neutral_hold", "minimum_density"}:
                raise ValueError("stale scrim health must fail closed to a bounded fallback")
        return self

    def world_surface_record(self) -> WorldSurfaceHealthRecord:
        """Adapt this compact fixture row into a full WCS health record."""

        private_only = (
            self.world_surface.public_private_posture is PublicPrivatePosture.PRIVATE_ONLY
        )
        dry_run_allowed = self.world_surface.public_private_posture is PublicPrivatePosture.DRY_RUN
        return WorldSurfaceHealthRecord.model_validate(
            {
                "schema_version": 1,
                "surface_id": self.world_surface.surface_id,
                "surface_family": self.world_surface.surface_family,
                "checked_at": self.world_surface.freshness.checked_at,
                "status": self.world_surface.status,
                "health_dimensions": [
                    dimension.model_dump(mode="json")
                    for dimension in self.world_surface.health_dimensions
                ],
                "source_refs": self.world_surface.source_refs,
                "producer_refs": self.world_surface.producer_refs,
                "consumer_refs": self.world_surface.consumer_refs,
                "route_refs": self.world_surface.route_refs,
                "substrate_refs": self.world_surface.substrate_refs,
                "capability_refs": self.world_surface.capability_refs,
                "evidence_envelope_refs": self.world_surface.evidence_envelope_refs,
                "outcome_envelope_refs": self.world_surface.outcome_envelope_refs,
                "witness_refs": self.world_surface.witness_refs,
                "grounding_gate_refs": [],
                "public_event_refs": [],
                "freshness": self.world_surface.freshness.model_dump(mode="json"),
                "confidence": self.world_surface.confidence,
                "authority_ceiling": self.world_surface.authority_ceiling,
                "privacy_state": self.world_surface.privacy_state,
                "rights_state": self.world_surface.rights_state,
                "public_private_posture": self.world_surface.public_private_posture,
                "public_claim_allowed": False,
                "private_only": private_only,
                "dry_run_allowed": dry_run_allowed,
                "monetization_allowed": False,
                "blocking_reasons": self.world_surface.blocking_reasons,
                "warnings": self.world_surface.warnings,
                "fallback": {
                    "mode": self.world_surface.fallback_mode,
                    "reason_code": self.world_surface.fallback_reason_code,
                    "operator_visible_reason": self.world_surface.fallback_operator_reason,
                    "safe_state": self.world_surface.fallback_safe_state,
                },
                "kill_switch_state": {
                    "state": self.world_surface.kill_switch_state,
                    "evidence_refs": [],
                },
                "owner": self.world_surface.owner,
                "next_probe_due_at": self.world_surface.next_probe_due_at,
                "claimable_health": False,
                "claimability": {
                    "public_live": False,
                    "action": False,
                    "grounded": False,
                    "monetization": False,
                },
                "witness_policy": self.world_surface.witness_policy,
                "fixture_case": self.world_surface.fixture_case,
            }
        )


class ScrimHealthFixtureSet(FrozenModel):
    schema_version: Literal[1]
    fixture_set_id: str
    schema_ref: Literal["schemas/scrim-health-fixtures.schema.json"]
    generated_from: tuple[str, ...] = Field(min_length=1)
    declared_at: str
    producer: str
    no_authority_policy: ScrimHealthNoAuthorityPolicy
    families: tuple[ScrimHealthFixtureFamily, ...]
    fixtures: tuple[ScrimHealthFixture, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_set_coverage(self) -> Self:
        if set(self.families) != REQUIRED_SCRIM_HEALTH_FIXTURE_FAMILIES:
            raise ValueError("scrim health fixture families do not match required set")
        fixture_families = {fixture.family for fixture in self.fixtures}
        if fixture_families != REQUIRED_SCRIM_HEALTH_FIXTURE_FAMILIES:
            raise ValueError("scrim health fixtures do not cover required families")
        return self

    def by_family(self) -> dict[ScrimHealthFixtureFamily, ScrimHealthFixture]:
        """Return fixture rows keyed by family."""

        return {fixture.family: fixture for fixture in self.fixtures}

    def world_surface_records(self) -> tuple[WorldSurfaceHealthRecord, ...]:
        """Return every fixture as a validated WCS health record."""

        return tuple(fixture.world_surface_record() for fixture in self.fixtures)

    def scrim_state_refs(self) -> tuple[ScrimStateEnvelopeRef, ...]:
        """Return every fixture's scrim-state compatibility reference."""

        return tuple(fixture.scrim_state for fixture in self.fixtures)


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ScrimHealthFixtureError(f"{path} did not contain a JSON object")
    return payload


@cache
def load_scrim_health_fixtures(
    path: Path = SCRIM_HEALTH_FIXTURES,
) -> ScrimHealthFixtureSet:
    """Load scrim health fixtures, failing closed on malformed data."""

    try:
        return ScrimHealthFixtureSet.model_validate(_load_json_object(path))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise ScrimHealthFixtureError(f"invalid scrim health fixtures at {path}: {exc}") from exc


__all__ = [
    "FORBIDDEN_AUDIO_MODULATION_REGISTERS",
    "REQUIRED_SCRIM_HEALTH_FIXTURE_FAMILIES",
    "SCRIM_HEALTH_FIXTURES",
    "AudioModulationRegister",
    "ScrimHealthFixture",
    "ScrimHealthFixtureError",
    "ScrimHealthFixtureSet",
    "ScrimHealthFixtureFamily",
    "ScrimInvariantScores",
    "load_scrim_health_fixtures",
]
