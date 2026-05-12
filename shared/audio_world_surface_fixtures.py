"""Typed loader for audio World Capability Surface contract fixtures.

These fixtures describe semantic audio surfaces and expected route-result
shapes. They are not live routing code and must not be treated as runtime
evidence that audio is fresh, audible, public-safe, private, or no-leak.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIO_WORLD_SURFACE_FIXTURES = REPO_ROOT / "config" / "audio-world-surface-fixtures.json"

REQUIRED_AUDIO_SURFACE_IDS = frozenset(
    {
        "audio.broadcast_voice",
        "audio.private_assistant_monitor",
        "audio.private_notification_monitor",
        "audio.programme_audio",
        "audio.stt_captions",
        "audio.l12_capture",
        "audio.s4_private_monitor",
        "audio.broadcast_egress",
        "audio.broadcast_health",
        "audio.no_private_leak",
    }
)

REQUIRED_AUDIO_HEALTH_STATES = frozenset(
    {
        "safe",
        "quiet_off_air",
        "degraded",
        "unsafe",
        "broken",
        "blocked_absent",
        "stale",
        "unknown",
    }
)

ROUTE_RESULT_REQUIRED_FIELDS = (
    "semantic_destination",
    "concrete_target_binding",
    "privacy_posture",
    "fallback_policy",
    "witness_class",
    "freshness",
    "failure_reason",
)


class AudioWorldSurfaceFixturesError(ValueError):
    """Raised when audio WCS fixtures cannot be loaded safely."""


class AudioHealthState(StrEnum):
    SAFE = "safe"
    QUIET_OFF_AIR = "quiet_off_air"
    DEGRADED = "degraded"
    UNSAFE = "unsafe"
    BROKEN = "broken"
    BLOCKED_ABSENT = "blocked_absent"
    STALE = "stale"
    UNKNOWN = "unknown"


class AudioWitnessClassId(StrEnum):
    PUBLIC = "public_audio_witness"
    PRIVATE = "private_audio_witness"
    NO_LEAK = "no_leak_audio_witness"
    ROUTE_BINDING = "route_binding_witness"
    FRESHNESS = "freshness_witness"
    HEALTH = "health_witness"


class AudioPrivacyPosture(StrEnum):
    PUBLIC_CANDIDATE = "public_candidate"
    PRIVATE_ONLY = "private_only"
    NO_LEAK = "no_leak"
    INTERNAL_HEALTH = "internal_health"
    ARCHIVE_ONLY = "archive_only"
    DRY_RUN = "dry_run"


class FreshnessState(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"
    BLOCKED_ABSENT = "blocked_absent"


class ConcreteTargetBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binding_id: str
    media_role: str | None
    target_ref: str
    route_id: str
    substrate_ref: str
    concrete_interface: str
    raw_high_level_target_assumption: Literal[False] = False
    implementation_truth_source_refs: list[str] = Field(min_length=1)


class AudioFallbackPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str
    reason_code: str
    prohibited_fallback_refs: list[str] = Field(default_factory=list)
    operator_visible_reason: str


class AudioFreshness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: FreshnessState
    ttl_s: int | None = Field(default=None, ge=0)
    checked_at: str | None = None
    evidence_ref: str | None = None


class AudioRouteResultFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    semantic_destination: str
    concrete_target_binding: ConcreteTargetBinding
    privacy_posture: AudioPrivacyPosture
    fallback_policy: AudioFallbackPolicy
    witness_class: AudioWitnessClassId
    freshness: AudioFreshness
    failure_reason: str


class AudioWitnessClass(BaseModel):
    model_config = ConfigDict(extra="forbid")

    witness_class: AudioWitnessClassId
    privacy_scope: Literal["public", "private", "no_leak", "route", "freshness", "health"]
    required_evidence_classes: list[str] = Field(min_length=1)
    raw_target_assumptions_allowed: Literal[False] = False
    description: str


class AudioSurfaceFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    surface_id: str
    label: str
    world_capability_ref: str
    semantic_destination: str
    surface_role: str
    grounding_status: str
    health_state: AudioHealthState
    route_result: AudioRouteResultFixture
    public_claim_allowed: Literal[False] = False
    blocked_reasons: list[str] = Field(min_length=1)
    notes: str

    @model_validator(mode="after")
    def _route_destination_matches_row(self) -> Self:
        if self.route_result.semantic_destination != self.semantic_destination:
            raise ValueError(
                f"{self.surface_id} route_result semantic destination does not match row"
            )
        return self


class AudioHealthStateFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: AudioHealthState
    public_live_allowed: Literal[False] = False
    public_claim_allowed_without_runtime_witness: Literal[False] = False
    meaning: str
    failure_reason: str


class AudioWorldSurfaceFixtureSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    fixture_set_id: str
    schema_ref: str
    generated_from: list[str] = Field(min_length=1)
    declared_at: str
    producer: str
    health_states: list[AudioHealthState] = Field(min_length=1)
    witness_classes: list[AudioWitnessClass] = Field(min_length=1)
    route_result_required_fields: list[str] = Field(min_length=1)
    audio_surface_rows: list[AudioSurfaceFixture] = Field(min_length=1)
    health_state_fixtures: list[AudioHealthStateFixture] = Field(min_length=1)
    fail_closed_policy: dict[str, bool]

    @model_validator(mode="after")
    def _validate_contract_coverage(self) -> Self:
        surface_ids = {row.surface_id for row in self.audio_surface_rows}
        missing_surfaces = REQUIRED_AUDIO_SURFACE_IDS - surface_ids
        if missing_surfaces:
            raise ValueError(
                "missing required audio WCS fixture rows: " + ", ".join(sorted(missing_surfaces))
            )

        health_states = {state.value for state in self.health_states}
        missing_health = REQUIRED_AUDIO_HEALTH_STATES - health_states
        if missing_health:
            raise ValueError(
                "missing required audio WCS health states: " + ", ".join(sorted(missing_health))
            )

        fixture_health_states = {fixture.state.value for fixture in self.health_state_fixtures}
        missing_fixture_health = REQUIRED_AUDIO_HEALTH_STATES - fixture_health_states
        if missing_fixture_health:
            raise ValueError(
                "missing required audio WCS health fixtures: "
                + ", ".join(sorted(missing_fixture_health))
            )

        route_fields = set(self.route_result_required_fields)
        missing_route_fields = set(ROUTE_RESULT_REQUIRED_FIELDS) - route_fields
        if missing_route_fields:
            raise ValueError(
                "route result shape missing fields: " + ", ".join(sorted(missing_route_fields))
            )

        witness_ids = [witness.witness_class for witness in self.witness_classes]
        if len(witness_ids) != len(set(witness_ids)):
            raise ValueError("duplicate audio witness class ids")
        required_witnesses = {
            AudioWitnessClassId.PUBLIC,
            AudioWitnessClassId.PRIVATE,
            AudioWitnessClassId.NO_LEAK,
        }
        if not required_witnesses <= set(witness_ids):
            raise ValueError("public, private, and no-leak witness classes are required")

        for row in self.audio_surface_rows:
            if row.route_result.concrete_target_binding.raw_high_level_target_assumption:
                raise ValueError("raw high-level target assumptions cannot be implementation truth")
        return self

    def rows_by_surface_id(self) -> dict[str, AudioSurfaceFixture]:
        """Return fixture rows keyed by WCS surface id."""

        return {row.surface_id: row for row in self.audio_surface_rows}

    def require_surface(self, surface_id: str) -> AudioSurfaceFixture:
        """Return a fixture row or raise a fail-closed lookup error."""

        row = self.rows_by_surface_id().get(surface_id)
        if row is None:
            raise KeyError(f"unknown audio WCS fixture surface: {surface_id}")
        return row

    def rows_for_witness(self, witness_class: AudioWitnessClassId) -> list[AudioSurfaceFixture]:
        """Return rows that require a given witness class."""

        return [
            row
            for row in self.audio_surface_rows
            if row.route_result.witness_class is witness_class
        ]


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AudioWorldSurfaceFixturesError(f"{path} did not contain a JSON object")
    return payload


def load_audio_world_surface_fixtures(
    path: Path = AUDIO_WORLD_SURFACE_FIXTURES,
) -> AudioWorldSurfaceFixtureSet:
    """Load audio WCS fixture contracts, failing closed on malformed data."""

    try:
        return AudioWorldSurfaceFixtureSet.model_validate(_load_json_object(path))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise AudioWorldSurfaceFixturesError(
            f"invalid audio WCS fixtures at {path}: {exc}"
        ) from exc


__all__ = [
    "AUDIO_WORLD_SURFACE_FIXTURES",
    "AudioHealthState",
    "AudioPrivacyPosture",
    "AudioWitnessClassId",
    "AudioWorldSurfaceFixturesError",
    "AudioWorldSurfaceFixtureSet",
    "REQUIRED_AUDIO_HEALTH_STATES",
    "REQUIRED_AUDIO_SURFACE_IDS",
    "ROUTE_RESULT_REQUIRED_FIELDS",
    "load_audio_world_surface_fixtures",
]
