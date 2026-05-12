"""Project audio health evidence into World Capability Surface health rows.

The broadcast audio health producer owns the aggregate
``audio_safe_for_broadcast`` decision. This adapter keeps that aggregate
decision from becoming a broader claim than the evidence supports: public voice
requires a surface-specific marker witness, private routes stay private-only or
blocked-absent, and unsafe/stale/unknown aggregate audio fails closed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shared.audio_world_surface_fixtures import (
    AudioHealthState,
    AudioSurfaceFixture,
    AudioWorldSurfaceFixtureSet,
    load_audio_world_surface_fixtures,
)
from shared.broadcast_audio_health import (
    DEFAULT_STATE_PATH,
    BroadcastAudioHealth,
    BroadcastAudioStatus,
    read_broadcast_audio_health_state,
)
from shared.world_surface_health import (
    REQUIRED_CLAIM_BLOCKER_CASES,
    REQUIRED_CLAIMABLE_DIMENSIONS,
    AuthorityCeiling,
    EnvelopeStatus,
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
    WorldSurfaceHealthEnvelope,
    WorldSurfaceHealthRecord,
)

OWNER = "world-surface-health-audio-adapter"

PUBLIC_BROADCAST_SURFACE_ID = "audio.broadcast_voice"
BROADCAST_HEALTH_SURFACE_ID = "audio.broadcast_health"
NO_LEAK_SURFACE_ID = "audio.no_private_leak"
L12_CAPTURE_SURFACE_ID = "audio.l12_capture"
BROADCAST_EGRESS_SURFACE_ID = "audio.broadcast_egress"
PROGRAMME_AUDIO_SURFACE_ID = "audio.programme_audio"
STT_CAPTIONS_SURFACE_ID = "audio.stt_captions"

PRIVATE_AUDIO_SURFACE_IDS = frozenset(
    {
        "audio.private_assistant_monitor",
        "audio.private_notification_monitor",
        "audio.s4_private_monitor",
    }
)

PUBLIC_AUDIO_SURFACE_IDS = frozenset(
    {
        PUBLIC_BROADCAST_SURFACE_ID,
        PROGRAMME_AUDIO_SURFACE_ID,
        L12_CAPTURE_SURFACE_ID,
        BROADCAST_EGRESS_SURFACE_ID,
        BROADCAST_HEALTH_SURFACE_ID,
        NO_LEAK_SURFACE_ID,
    }
)

PUBLIC_BROADCAST_READY_REQUIRED_SURFACE_IDS = frozenset(
    {
        PUBLIC_BROADCAST_SURFACE_ID,
        BROADCAST_HEALTH_SURFACE_ID,
        NO_LEAK_SURFACE_ID,
        L12_CAPTURE_SURFACE_ID,
        BROADCAST_EGRESS_SURFACE_ID,
    }
)

PUBLIC_BROADCAST_MEDIA_ROLE = "Broadcast"
PUBLIC_BROADCAST_TARGETS = frozenset(
    {
        "hapax-livestream",
        "hapax-livestream-tap",
        "hapax-voice-fx-capture",
        "hapax-broadcast-normalized",
        "hapax-obs-broadcast-remap",
    }
)

DEFAULT_AUDIO_WCS_TTL_S = 30


class AudioWorldSurfaceHealthError(ValueError):
    """Raised when audio WCS health projection cannot be built safely."""


class AudioSurfaceObservation(BaseModel):
    """Optional runtime witness for one audio surface.

    Tests and future marker probes can pass this shape without mutating live
    audio. Observations never override fail-closed aggregate broadcast safety.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    health_state: AudioHealthState
    checked_at: str | None = None
    ttl_s: int = Field(default=DEFAULT_AUDIO_WCS_TTL_S, ge=0)
    observed_age_s: int | None = Field(default=0, ge=0)
    source_refs: tuple[str, ...] = Field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    witness_refs: tuple[str, ...] = Field(default_factory=tuple)
    route_refs: tuple[str, ...] = Field(default_factory=tuple)
    blocking_reasons: tuple[str, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    private_only: bool = False
    note: str | None = None


@dataclass(frozen=True)
class _AudioProjection:
    surface_id: str
    health_state: AudioHealthState
    checked_at: str
    ttl_s: int
    observed_age_s: int | None
    source_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    witness_refs: tuple[str, ...]
    route_refs: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    confidence: float
    fixture_case: FixtureCase
    witness_policy: WitnessPolicy
    private_only: bool = False
    claimable_public_broadcast: bool = False


def load_audio_world_surface_health(
    path: Path = DEFAULT_STATE_PATH,
    *,
    now: float | None = None,
    max_age_s: float = 30.0,
    observations: Mapping[str, AudioSurfaceObservation | Mapping[str, Any]] | None = None,
    fixtures: AudioWorldSurfaceFixtureSet | None = None,
) -> WorldSurfaceHealthEnvelope:
    """Read ``audio_safe_for_broadcast`` and project it into WCS health rows."""

    return project_audio_world_surface_health(
        read_broadcast_audio_health_state(path, now=now, max_age_s=max_age_s),
        observations=observations,
        fixtures=fixtures,
    )


def project_audio_world_surface_health(
    audio_safe_for_broadcast: BroadcastAudioHealth,
    *,
    observations: Mapping[str, AudioSurfaceObservation | Mapping[str, Any]] | None = None,
    fixtures: AudioWorldSurfaceFixtureSet | None = None,
) -> WorldSurfaceHealthEnvelope:
    """Build one WCS health envelope for the audio reference surfaces."""

    fixture_set = fixtures or load_audio_world_surface_fixtures()
    observed = _coerce_observations(observations or {}, fixture_set)
    records = [
        _record_for_surface(row, audio_safe_for_broadcast, observed.get(row.surface_id))
        for row in fixture_set.audio_surface_rows
    ]
    public_live_allowed = _public_broadcast_ready(records)

    return WorldSurfaceHealthEnvelope(
        envelope_id=f"world-surface-health:audio:{audio_safe_for_broadcast.checked_at}",
        checked_at=audio_safe_for_broadcast.checked_at,
        overall_status=_overall_status(records),
        records=records,
        summary=_summary(records),
        public_live_allowed=public_live_allowed,
        public_archive_allowed=public_live_allowed,
        public_monetization_allowed=False,
        blocked_surface_count=sum(record.status is HealthStatus.BLOCKED for record in records),
        unsafe_surface_count=sum(record.status is HealthStatus.UNSAFE for record in records),
        stale_surface_count=sum(record.status is HealthStatus.STALE for record in records),
        unknown_surface_count=sum(record.status is HealthStatus.UNKNOWN for record in records),
        false_grounding_risk_count=_false_grounding_risk_count(records),
        next_required_actions=_next_required_actions(records),
        metrics_refs=("metrics:audio_safe_for_broadcast",),
    )


def _coerce_observations(
    observations: Mapping[str, AudioSurfaceObservation | Mapping[str, Any]],
    fixtures: AudioWorldSurfaceFixtureSet,
) -> dict[str, AudioSurfaceObservation]:
    rows = fixtures.rows_by_surface_id()
    coerced: dict[str, AudioSurfaceObservation] = {}
    for raw_surface_id, raw_observation in observations.items():
        surface_id = raw_surface_id[:-7] if raw_surface_id.endswith(".health") else raw_surface_id
        if surface_id not in rows:
            raise AudioWorldSurfaceHealthError(f"unknown audio WCS surface: {raw_surface_id}")
        try:
            coerced[surface_id] = AudioSurfaceObservation.model_validate(raw_observation)
        except ValidationError as exc:
            raise AudioWorldSurfaceHealthError(
                f"invalid audio WCS observation for {raw_surface_id}: {exc}"
            ) from exc
    return coerced


def _record_for_surface(
    row: AudioSurfaceFixture,
    audio_health: BroadcastAudioHealth,
    observation: AudioSurfaceObservation | None,
) -> WorldSurfaceHealthRecord:
    projection = _projection_for_surface(row, audio_health, observation)
    claimable = projection.claimable_public_broadcast
    health_status = _health_status_for_projection(projection)
    fallback_mode = _fallback_mode_for(row)
    health_id = _health_surface_id(row.surface_id)

    return WorldSurfaceHealthRecord(
        surface_id=health_id,
        surface_family=SurfaceFamily.AUDIO,
        checked_at=projection.checked_at,
        status=health_status,
        health_dimensions=_dimensions_for(row, projection, health_status, claimable),
        source_refs=_dedupe(
            (
                f"source:{row.surface_id}",
                "source:audio_safe_for_broadcast",
                *projection.source_refs,
            )
        ),
        producer_refs=_producer_refs(row),
        consumer_refs=(
            "consumer:world-surface-health",
            "consumer:public-broadcast-readiness",
        ),
        route_refs=_dedupe(
            (row.route_result.concrete_target_binding.route_id, *projection.route_refs)
        ),
        substrate_refs=(row.route_result.concrete_target_binding.substrate_ref,),
        capability_refs=(f"wcs:{row.world_capability_ref}",),
        evidence_envelope_refs=projection.evidence_refs,
        outcome_envelope_refs=_outcome_refs(row, projection),
        witness_refs=projection.witness_refs,
        grounding_gate_refs=(
            ("gate:audio.world-surface-health:public-broadcast-ready",) if claimable else ()
        ),
        public_event_refs=(("public-event:studio.broadcast.session",) if claimable else ()),
        freshness=_freshness_for(projection, health_status),
        confidence=projection.confidence,
        authority_ceiling=(
            AuthorityCeiling.PUBLIC_GATE_REQUIRED
            if claimable
            else _authority_ceiling_for(row, projection)
        ),
        privacy_state=_privacy_state_for(row, projection, health_status),
        rights_state=_rights_state_for(row, projection, claimable),
        public_private_posture=_posture_for(row, projection, health_status, claimable),
        public_claim_allowed=claimable,
        private_only=projection.private_only,
        dry_run_allowed=projection.health_state is AudioHealthState.QUIET_OFF_AIR,
        monetization_allowed=False,
        blocking_reasons=_blocking_reasons_for(row, projection, health_status, claimable),
        warnings=list(projection.warnings),
        fallback={
            "mode": fallback_mode,
            "reason_code": row.route_result.fallback_policy.reason_code,
            "operator_visible_reason": row.route_result.fallback_policy.operator_visible_reason,
            "safe_state": _fallback_safe_state_for(row, projection),
        },
        kill_switch_state={
            "state": KillSwitchStatus.CLEAR if claimable else KillSwitchStatus.NOT_APPLICABLE,
            "evidence_refs": (("kill-switch:audio.public-broadcast:clear",) if claimable else ()),
        },
        owner=OWNER,
        next_probe_due_at=_next_probe_due_at(projection.checked_at, projection.ttl_s),
        claimable_health=claimable,
        claimability={
            "public_live": claimable,
            "action": claimable,
            "grounded": claimable,
            "monetization": False,
        },
        witness_policy=projection.witness_policy,
        fixture_case=projection.fixture_case,
    )


def _projection_for_surface(
    row: AudioSurfaceFixture,
    audio_health: BroadcastAudioHealth,
    observation: AudioSurfaceObservation | None,
) -> _AudioProjection:
    if observation is not None:
        observed = _projection_from_observation(row, audio_health, observation)
        if row.surface_id == PUBLIC_BROADCAST_SURFACE_ID:
            return _gate_broadcast_voice_with_aggregate(row, audio_health, observed)
        return observed

    if row.surface_id == PUBLIC_BROADCAST_SURFACE_ID:
        return _broadcast_voice_projection(row, audio_health)
    if row.surface_id == BROADCAST_HEALTH_SURFACE_ID:
        return _aggregate_health_projection(row, audio_health)
    if row.surface_id == NO_LEAK_SURFACE_ID:
        return _no_leak_projection(row, audio_health)
    if row.surface_id == L12_CAPTURE_SURFACE_ID:
        return _l12_capture_projection(row, audio_health)
    if row.surface_id == BROADCAST_EGRESS_SURFACE_ID:
        return _egress_projection(row, audio_health)
    if row.surface_id == PROGRAMME_AUDIO_SURFACE_ID:
        return _programme_audio_projection(row, audio_health)
    return _fixture_projection(row, audio_health)


def _projection_from_observation(
    row: AudioSurfaceFixture,
    audio_health: BroadcastAudioHealth,
    observation: AudioSurfaceObservation,
) -> _AudioProjection:
    state = observation.health_state
    checked_at = observation.checked_at or audio_health.checked_at
    evidence_refs = _dedupe(
        (
            "evidence:audio_safe_for_broadcast",
            f"evidence:{row.surface_id}:observation",
            *observation.evidence_refs,
        )
    )
    witness_refs = _dedupe(observation.witness_refs)
    private_only = observation.private_only or row.surface_id in PRIVATE_AUDIO_SURFACE_IDS
    return _AudioProjection(
        surface_id=row.surface_id,
        health_state=state,
        checked_at=checked_at,
        ttl_s=observation.ttl_s,
        observed_age_s=observation.observed_age_s,
        source_refs=_dedupe(observation.source_refs),
        evidence_refs=evidence_refs,
        witness_refs=witness_refs,
        route_refs=_dedupe(observation.route_refs),
        blocking_reasons=_reasons_for_state(row, state, observation.blocking_reasons),
        warnings=observation.warnings,
        confidence=observation.confidence,
        fixture_case=_fixture_case_for(row, state, bool(witness_refs), command_only=False),
        witness_policy=_witness_policy_for(state, bool(witness_refs), command_only=False),
        private_only=private_only and state is AudioHealthState.SAFE,
        claimable_public_broadcast=False,
    )


def _gate_broadcast_voice_with_aggregate(
    row: AudioSurfaceFixture,
    audio_health: BroadcastAudioHealth,
    observed: _AudioProjection,
) -> _AudioProjection:
    if observed.health_state is not AudioHealthState.SAFE:
        return observed
    if not audio_health.safe or audio_health.status is not BroadcastAudioStatus.SAFE:
        state = _aggregate_audio_state(audio_health)
        return _replace_projection(
            observed,
            health_state=state,
            blocking_reasons=_dedupe(
                (
                    *observed.blocking_reasons,
                    "audio_safe_for_broadcast_not_safe",
                    *_reason_codes(audio_health),
                )
            ),
            fixture_case=_fixture_case_for(row, state, False, command_only=False),
            witness_policy=_witness_policy_for(state, False, command_only=False),
            claimable_public_broadcast=False,
            private_only=False,
            confidence=min(observed.confidence, 0.35),
        )
    if not _voice_marker_is_public_audible(audio_health):
        return _broadcast_voice_projection(row, audio_health)
    return _replace_projection(
        observed,
        fixture_case=FixtureCase.HEALTHY_WITNESSED,
        witness_policy=WitnessPolicy.WITNESSED,
        private_only=False,
        claimable_public_broadcast=True,
        confidence=max(observed.confidence, 0.9),
    )


def _broadcast_voice_projection(
    row: AudioSurfaceFixture,
    audio_health: BroadcastAudioHealth,
) -> _AudioProjection:
    aggregate_state = _aggregate_audio_state(audio_health)
    voice = _evidence_dict(audio_health, "voice_output_witness")
    command_only = _broadcast_voice_commanded_without_marker(voice)

    if aggregate_state not in {AudioHealthState.SAFE, AudioHealthState.DEGRADED}:
        return _base_projection(
            row,
            audio_health,
            health_state=aggregate_state,
            evidence_refs=("evidence:audio_safe_for_broadcast",),
            witness_refs=(),
            blocking_reasons=("audio_safe_for_broadcast_not_safe", *_reason_codes(audio_health)),
            fixture_case=_fixture_case_for(row, aggregate_state, False, command_only=False),
            witness_policy=_witness_policy_for(aggregate_state, False, command_only=False),
            confidence=0.25,
        )

    if (
        _voice_marker_is_public_audible(audio_health)
        and audio_health.status is BroadcastAudioStatus.SAFE
    ):
        return _base_projection(
            row,
            audio_health,
            health_state=AudioHealthState.SAFE,
            evidence_refs=(
                "evidence:audio_safe_for_broadcast",
                "evidence:voice_output_witness",
                "evidence:broadcast_egress_marker",
            ),
            witness_refs=(
                "witness:audio.broadcast_voice:playback",
                "witness:audio.broadcast_voice:egress-marker",
            ),
            blocking_reasons=(),
            fixture_case=FixtureCase.HEALTHY_WITNESSED,
            witness_policy=WitnessPolicy.WITNESSED,
            confidence=0.93,
            claimable_public_broadcast=True,
        )

    if _voice_witness_is_stale_or_broken(voice):
        state = (
            AudioHealthState.STALE if voice.get("status") == "stale" else AudioHealthState.BROKEN
        )
        return _base_projection(
            row,
            audio_health,
            health_state=state,
            evidence_refs=("evidence:voice_output_witness",),
            witness_refs=(),
            blocking_reasons=(f"voice_output_witness_{voice.get('status')}",),
            fixture_case=_fixture_case_for(row, state, False, command_only=False),
            witness_policy=_witness_policy_for(state, False, command_only=False),
            confidence=0.2,
        )

    if command_only:
        return _base_projection(
            row,
            audio_health,
            health_state=AudioHealthState.UNKNOWN,
            evidence_refs=("evidence:voice_output_witness", "evidence:broadcast_forward"),
            witness_refs=(),
            blocking_reasons=("commanded_tts_without_public_egress_marker",),
            fixture_case=FixtureCase.COMMANDED_ONLY,
            witness_policy=WitnessPolicy.COMMANDED_ONLY,
            confidence=0.2,
        )

    return _base_projection(
        row,
        audio_health,
        health_state=AudioHealthState.QUIET_OFF_AIR,
        evidence_refs=("evidence:audio_safe_for_broadcast", "evidence:voice_output_witness"),
        witness_refs=(),
        blocking_reasons=("broadcast_voice_marker_missing",),
        fixture_case=FixtureCase.QUIET_OFF_AIR,
        witness_policy=WitnessPolicy.ABSENT,
        confidence=0.55,
    )


def _aggregate_health_projection(
    row: AudioSurfaceFixture,
    audio_health: BroadcastAudioHealth,
) -> _AudioProjection:
    state = _aggregate_audio_state(audio_health)
    return _base_projection(
        row,
        audio_health,
        health_state=state,
        evidence_refs=("evidence:audio_safe_for_broadcast",),
        witness_refs=(
            ("witness:audio_safe_for_broadcast:fresh",) if state is AudioHealthState.SAFE else ()
        ),
        blocking_reasons=_reason_codes(audio_health),
        fixture_case=_fixture_case_for(row, state, audio_health.safe, command_only=False),
        witness_policy=_witness_policy_for(state, audio_health.safe, command_only=False),
        confidence=0.9 if audio_health.safe else 0.35,
    )


def _no_leak_projection(
    row: AudioSurfaceFixture,
    audio_health: BroadcastAudioHealth,
) -> _AudioProjection:
    private_routes = _evidence_dict(audio_health, "private_routes")
    if "private_route_leak_guard_failed" in _reason_codes(audio_health):
        state = AudioHealthState.UNSAFE
        blocking = ("private_route_leak_guard_failed",)
        witnessed = True
        confidence = 0.2
    elif _evidence_passed(private_routes):
        state = AudioHealthState.SAFE
        blocking = ()
        witnessed = True
        confidence = 0.88
    else:
        state = _aggregate_audio_state(audio_health)
        blocking = ("no_leak_witness_missing", *_reason_codes(audio_health))
        witnessed = False
        confidence = 0.25
    return _base_projection(
        row,
        audio_health,
        health_state=state,
        evidence_refs=("evidence:audio_safe_for_broadcast.private_routes",),
        witness_refs=(("witness:audio.no_private_leak:leak-guard",) if witnessed else ()),
        blocking_reasons=blocking,
        fixture_case=_fixture_case_for(row, state, witnessed, command_only=False),
        witness_policy=_witness_policy_for(state, witnessed, command_only=False),
        confidence=confidence,
    )


def _l12_capture_projection(
    row: AudioSurfaceFixture,
    audio_health: BroadcastAudioHealth,
) -> _AudioProjection:
    l12 = _evidence_dict(audio_health, "l12_forward_invariant")
    if "broadcast_forward_invariant_failed" in _reason_codes(audio_health):
        state = AudioHealthState.UNSAFE
        blocking = ("broadcast_forward_invariant_failed",)
        witnessed = True
        confidence = 0.25
    elif _evidence_passed(l12):
        state = AudioHealthState.SAFE
        blocking = ()
        witnessed = True
        confidence = 0.82
    else:
        state = _aggregate_audio_state(audio_health)
        blocking = ("l12_forward_invariant_unwitnessed", *_reason_codes(audio_health))
        witnessed = False
        confidence = 0.25
    return _base_projection(
        row,
        audio_health,
        health_state=state,
        evidence_refs=("evidence:audio_safe_for_broadcast.l12_forward_invariant",),
        witness_refs=(("witness:audio.l12_capture:forward-invariant",) if witnessed else ()),
        blocking_reasons=blocking,
        fixture_case=_fixture_case_for(row, state, witnessed, command_only=False),
        witness_policy=_witness_policy_for(state, witnessed, command_only=False),
        confidence=confidence,
    )


def _egress_projection(
    row: AudioSurfaceFixture,
    audio_health: BroadcastAudioHealth,
) -> _AudioProjection:
    egress = _evidence_dict(audio_health, "egress_binding")
    loudness = _evidence_dict(audio_health, "loudness")
    if not bool(egress.get("bound")):
        return _base_projection(
            row,
            audio_health,
            health_state=AudioHealthState.BLOCKED_ABSENT,
            evidence_refs=("evidence:audio_safe_for_broadcast.egress_binding",),
            witness_refs=(),
            blocking_reasons=(
                "egress_binding_missing",
                *_matching_reason_codes(audio_health, "egress"),
            ),
            fixture_case=FixtureCase.BLOCKED_WITH_REASON,
            witness_policy=WitnessPolicy.ABSENT,
            confidence=0.25,
        )
    if loudness and (
        loudness.get("within_target_band") is False
        or loudness.get("true_peak_within_ceiling") is False
    ):
        return _base_projection(
            row,
            audio_health,
            health_state=AudioHealthState.DEGRADED,
            evidence_refs=(
                "evidence:audio_safe_for_broadcast.egress_binding",
                "evidence:audio_safe_for_broadcast.loudness",
            ),
            witness_refs=("witness:audio.broadcast_egress:binding",),
            blocking_reasons=("broadcast_loudness_or_peak_out_of_band",),
            fixture_case=FixtureCase.DEGRADED_WITNESSED,
            witness_policy=WitnessPolicy.WITNESSED,
            confidence=0.6,
        )
    return _base_projection(
        row,
        audio_health,
        health_state=AudioHealthState.SAFE,
        evidence_refs=(
            "evidence:audio_safe_for_broadcast.egress_binding",
            "evidence:audio_safe_for_broadcast.loudness",
        ),
        witness_refs=("witness:audio.broadcast_egress:binding",),
        blocking_reasons=(),
        fixture_case=FixtureCase.HEALTHY_WITNESSED,
        witness_policy=WitnessPolicy.WITNESSED,
        confidence=0.84,
    )


def _programme_audio_projection(
    row: AudioSurfaceFixture,
    audio_health: BroadcastAudioHealth,
) -> _AudioProjection:
    aggregate_state = _aggregate_audio_state(audio_health)
    if aggregate_state not in {AudioHealthState.SAFE, AudioHealthState.DEGRADED}:
        state = aggregate_state
        blocking = ("audio_safe_for_broadcast_not_safe", *_reason_codes(audio_health))
        fixture_case = _fixture_case_for(row, state, False, command_only=False)
        witness_policy = _witness_policy_for(state, False, command_only=False)
        confidence = 0.25
    else:
        state = AudioHealthState.DEGRADED
        blocking = ("programme_source_rights_unwitnessed",)
        fixture_case = FixtureCase.DEGRADED_WITNESSED
        witness_policy = WitnessPolicy.WITNESSED
        confidence = 0.55
    return _base_projection(
        row,
        audio_health,
        health_state=state,
        evidence_refs=("evidence:audio_safe_for_broadcast", "evidence:programme_audio_policy"),
        witness_refs=(
            ("witness:audio.programme_audio:route",)
            if aggregate_state is AudioHealthState.SAFE
            else ()
        ),
        blocking_reasons=blocking,
        fixture_case=fixture_case,
        witness_policy=witness_policy,
        confidence=confidence,
    )


def _fixture_projection(
    row: AudioSurfaceFixture,
    audio_health: BroadcastAudioHealth,
) -> _AudioProjection:
    if (
        row.surface_id in PRIVATE_AUDIO_SURFACE_IDS
        and "private_route_leak_guard_failed" in _reason_codes(audio_health)
    ):
        state = AudioHealthState.UNSAFE
        blocking = ("private_route_leak_guard_failed",)
    else:
        state = row.health_state
        blocking = tuple(row.blocked_reasons)
    return _base_projection(
        row,
        audio_health,
        health_state=state,
        evidence_refs=(f"fixture:{row.surface_id}", "evidence:audio_safe_for_broadcast"),
        witness_refs=(),
        blocking_reasons=blocking,
        fixture_case=_fixture_case_for(row, state, False, command_only=False),
        witness_policy=_witness_policy_for(state, False, command_only=False),
        confidence=0.3,
    )


def _base_projection(
    row: AudioSurfaceFixture,
    audio_health: BroadcastAudioHealth,
    *,
    health_state: AudioHealthState,
    evidence_refs: tuple[str, ...],
    witness_refs: tuple[str, ...],
    blocking_reasons: tuple[str, ...],
    fixture_case: FixtureCase,
    witness_policy: WitnessPolicy,
    confidence: float,
    claimable_public_broadcast: bool = False,
) -> _AudioProjection:
    return _AudioProjection(
        surface_id=row.surface_id,
        health_state=health_state,
        checked_at=audio_health.checked_at,
        ttl_s=DEFAULT_AUDIO_WCS_TTL_S,
        observed_age_s=round(audio_health.freshness_s),
        source_refs=(),
        evidence_refs=_dedupe(evidence_refs or (f"evidence:{row.surface_id}:audio-health",)),
        witness_refs=_dedupe(witness_refs),
        route_refs=(),
        blocking_reasons=_dedupe(blocking_reasons),
        warnings=tuple(reason.code for reason in audio_health.warnings),
        confidence=confidence,
        fixture_case=fixture_case,
        witness_policy=witness_policy,
        private_only=False,
        claimable_public_broadcast=claimable_public_broadcast,
    )


def _replace_projection(projection: _AudioProjection, **updates: object) -> _AudioProjection:
    values = {
        "surface_id": projection.surface_id,
        "health_state": projection.health_state,
        "checked_at": projection.checked_at,
        "ttl_s": projection.ttl_s,
        "observed_age_s": projection.observed_age_s,
        "source_refs": projection.source_refs,
        "evidence_refs": projection.evidence_refs,
        "witness_refs": projection.witness_refs,
        "route_refs": projection.route_refs,
        "blocking_reasons": projection.blocking_reasons,
        "warnings": projection.warnings,
        "confidence": projection.confidence,
        "fixture_case": projection.fixture_case,
        "witness_policy": projection.witness_policy,
        "private_only": projection.private_only,
        "claimable_public_broadcast": projection.claimable_public_broadcast,
    }
    values.update(updates)
    return _AudioProjection(**values)


def _health_status_for_projection(projection: _AudioProjection) -> HealthStatus:
    if projection.health_state is AudioHealthState.SAFE:
        return HealthStatus.PRIVATE_ONLY if projection.private_only else HealthStatus.HEALTHY
    if projection.health_state is AudioHealthState.QUIET_OFF_AIR:
        return HealthStatus.QUIET_OFF_AIR
    if projection.health_state is AudioHealthState.DEGRADED:
        return HealthStatus.DEGRADED
    if projection.health_state is AudioHealthState.UNSAFE:
        return HealthStatus.UNSAFE
    if projection.health_state is AudioHealthState.BROKEN:
        return HealthStatus.MISSING
    if projection.health_state is AudioHealthState.BLOCKED_ABSENT:
        return HealthStatus.BLOCKED
    if projection.health_state is AudioHealthState.STALE:
        return HealthStatus.STALE
    return HealthStatus.UNKNOWN


def _dimensions_for(
    row: AudioSurfaceFixture,
    projection: _AudioProjection,
    health_status: HealthStatus,
    claimable: bool,
) -> list[dict[str, object]]:
    return [
        _dimension(
            dimension,
            _dimension_state(row, projection, health_status, claimable, dimension),
            _dimension_evidence_refs(row, projection, claimable, dimension),
        )
        for dimension in (
            HealthDimensionId.SOURCE_FRESHNESS,
            HealthDimensionId.PRODUCER_EXISTS,
            HealthDimensionId.CONSUMER_EXISTS,
            HealthDimensionId.ROUTE_BINDING,
            HealthDimensionId.EXECUTION_WITNESS,
            HealthDimensionId.WORLD_WITNESS,
            HealthDimensionId.RENDERABILITY,
            HealthDimensionId.NO_LEAK,
            HealthDimensionId.EGRESS_PUBLIC,
            HealthDimensionId.PUBLIC_EVENT_POLICY,
            HealthDimensionId.RIGHTS_PROVENANCE,
            HealthDimensionId.PRIVACY_CONSENT,
            HealthDimensionId.GROUNDING_GATE,
            HealthDimensionId.CLAIM_AUTHORITY,
            HealthDimensionId.MONETIZATION_READINESS,
            HealthDimensionId.FALLBACK_KNOWN,
            HealthDimensionId.KILL_SWITCH,
        )
    ]


def _dimension(
    dimension: HealthDimensionId,
    state: HealthDimensionState,
    evidence_refs: tuple[str, ...],
) -> dict[str, object]:
    required = dimension.value in REQUIRED_CLAIMABLE_DIMENSIONS
    return {
        "dimension": dimension,
        "state": state,
        "required_for_claimable": required,
        "evidence_refs": list(evidence_refs),
        "note": _dimension_note(dimension, state),
    }


def _dimension_state(
    row: AudioSurfaceFixture,
    projection: _AudioProjection,
    health_status: HealthStatus,
    claimable: bool,
    dimension: HealthDimensionId,
) -> HealthDimensionState:
    if claimable:
        return HealthDimensionState.PASS
    if dimension is HealthDimensionId.SOURCE_FRESHNESS:
        if health_status is HealthStatus.STALE:
            return HealthDimensionState.STALE
        if health_status is HealthStatus.MISSING:
            return HealthDimensionState.MISSING
        if health_status is HealthStatus.UNKNOWN:
            return HealthDimensionState.UNKNOWN
        return HealthDimensionState.PASS
    if dimension in {HealthDimensionId.FALLBACK_KNOWN, HealthDimensionId.KILL_SWITCH}:
        return HealthDimensionState.PASS
    if dimension is HealthDimensionId.PRODUCER_EXISTS:
        return (
            HealthDimensionState.MISSING
            if health_status is HealthStatus.MISSING
            else HealthDimensionState.PASS
        )
    if dimension is HealthDimensionId.CONSUMER_EXISTS:
        return (
            HealthDimensionState.UNKNOWN
            if health_status is HealthStatus.UNKNOWN
            else HealthDimensionState.PASS
        )
    if dimension is HealthDimensionId.ROUTE_BINDING:
        if projection.health_state is AudioHealthState.BLOCKED_ABSENT:
            return HealthDimensionState.BLOCKED
        if health_status in {HealthStatus.MISSING, HealthStatus.UNKNOWN, HealthStatus.STALE}:
            return _nonpass_dimension_state(health_status)
        return HealthDimensionState.PASS
    if dimension in {HealthDimensionId.EXECUTION_WITNESS, HealthDimensionId.WORLD_WITNESS}:
        if projection.witness_refs:
            return HealthDimensionState.PASS
        return _nonpass_dimension_state(health_status)
    if dimension is HealthDimensionId.NO_LEAK:
        if row.surface_id == NO_LEAK_SURFACE_ID and health_status is HealthStatus.UNSAFE:
            return HealthDimensionState.FAIL
        if "private_route_leak_guard_failed" in projection.blocking_reasons:
            return HealthDimensionState.FAIL
        return (
            HealthDimensionState.PASS
            if row.surface_id in PUBLIC_AUDIO_SURFACE_IDS
            else HealthDimensionState.NOT_APPLICABLE
        )
    if dimension is HealthDimensionId.EGRESS_PUBLIC:
        if row.surface_id in PRIVATE_AUDIO_SURFACE_IDS:
            return HealthDimensionState.NOT_APPLICABLE
        if projection.health_state is AudioHealthState.BLOCKED_ABSENT:
            return HealthDimensionState.BLOCKED
        if health_status in {HealthStatus.MISSING, HealthStatus.UNKNOWN, HealthStatus.STALE}:
            return _nonpass_dimension_state(health_status)
        return (
            HealthDimensionState.PASS
            if row.surface_id in PUBLIC_AUDIO_SURFACE_IDS
            else HealthDimensionState.UNKNOWN
        )
    if dimension in {
        HealthDimensionId.PUBLIC_EVENT_POLICY,
        HealthDimensionId.GROUNDING_GATE,
        HealthDimensionId.CLAIM_AUTHORITY,
    }:
        return (
            HealthDimensionState.NOT_APPLICABLE
            if row.surface_id in PRIVATE_AUDIO_SURFACE_IDS
            else HealthDimensionState.UNKNOWN
        )
    if dimension is HealthDimensionId.RIGHTS_PROVENANCE:
        return (
            HealthDimensionState.UNKNOWN
            if row.surface_id == PROGRAMME_AUDIO_SURFACE_ID
            else HealthDimensionState.NOT_APPLICABLE
        )
    if dimension is HealthDimensionId.PRIVACY_CONSENT:
        if health_status is HealthStatus.UNSAFE:
            return HealthDimensionState.FAIL
        if health_status is HealthStatus.UNKNOWN:
            return HealthDimensionState.UNKNOWN
        return HealthDimensionState.PASS
    if dimension is HealthDimensionId.RENDERABILITY:
        return HealthDimensionState.NOT_APPLICABLE
    if dimension is HealthDimensionId.MONETIZATION_READINESS:
        return HealthDimensionState.NOT_APPLICABLE
    return HealthDimensionState.UNKNOWN


def _dimension_evidence_refs(
    row: AudioSurfaceFixture,
    projection: _AudioProjection,
    claimable: bool,
    dimension: HealthDimensionId,
) -> tuple[str, ...]:
    if claimable:
        refs = {
            HealthDimensionId.SOURCE_FRESHNESS: ("evidence:audio_safe_for_broadcast",),
            HealthDimensionId.PRODUCER_EXISTS: ("producer:agents.broadcast_audio_health",),
            HealthDimensionId.CONSUMER_EXISTS: ("consumer:public-broadcast-readiness",),
            HealthDimensionId.ROUTE_BINDING: ("evidence:broadcast_forward",),
            HealthDimensionId.EXECUTION_WITNESS: ("witness:audio.broadcast_voice:playback",),
            HealthDimensionId.WORLD_WITNESS: ("witness:audio.broadcast_voice:egress-marker",),
            HealthDimensionId.NO_LEAK: ("witness:audio.no_private_leak:leak-guard",),
            HealthDimensionId.EGRESS_PUBLIC: ("evidence:audio_safe_for_broadcast.egress_binding",),
            HealthDimensionId.PUBLIC_EVENT_POLICY: ("public-event:studio.broadcast.session",),
            HealthDimensionId.RIGHTS_PROVENANCE: ("rights:operator-voice:public-clear",),
            HealthDimensionId.PRIVACY_CONSENT: ("privacy:operator-public-safe",),
            HealthDimensionId.GROUNDING_GATE: (
                "gate:audio.world-surface-health:public-broadcast-ready",
            ),
            HealthDimensionId.CLAIM_AUTHORITY: ("authority:audio.public-gate-required",),
            HealthDimensionId.FALLBACK_KNOWN: (
                f"fallback:{row.route_result.fallback_policy.reason_code}",
            ),
            HealthDimensionId.KILL_SWITCH: ("kill-switch:audio.public-broadcast:clear",),
        }
        return refs.get(dimension, projection.evidence_refs)
    if dimension is HealthDimensionId.FALLBACK_KNOWN:
        return (f"fallback:{row.route_result.fallback_policy.reason_code}",)
    if dimension is HealthDimensionId.KILL_SWITCH:
        return ("kill-switch:audio:declared",)
    if dimension in {
        HealthDimensionId.EXECUTION_WITNESS,
        HealthDimensionId.WORLD_WITNESS,
    }:
        return projection.witness_refs
    return projection.evidence_refs


def _dimension_note(dimension: HealthDimensionId, state: HealthDimensionState) -> str:
    return f"{dimension.value} is {state.value} for the audio world-surface projection."


def _nonpass_dimension_state(status: HealthStatus) -> HealthDimensionState:
    if status is HealthStatus.STALE:
        return HealthDimensionState.STALE
    if status is HealthStatus.MISSING:
        return HealthDimensionState.MISSING
    if status is HealthStatus.UNKNOWN:
        return HealthDimensionState.UNKNOWN
    if status is HealthStatus.BLOCKED:
        return HealthDimensionState.BLOCKED
    if status is HealthStatus.UNSAFE:
        return HealthDimensionState.FAIL
    return HealthDimensionState.UNKNOWN


def _freshness_for(projection: _AudioProjection, health_status: HealthStatus) -> dict[str, object]:
    if health_status is HealthStatus.STALE:
        state = FreshnessState.STALE
    elif health_status is HealthStatus.MISSING:
        state = FreshnessState.MISSING
    elif health_status is HealthStatus.UNKNOWN:
        state = FreshnessState.UNKNOWN
    else:
        state = FreshnessState.FRESH
    payload: dict[str, object] = {"state": state, "checked_at": projection.checked_at}
    if state is FreshnessState.FRESH:
        payload.update(
            {
                "ttl_s": projection.ttl_s,
                "observed_age_s": min(projection.observed_age_s or 0, projection.ttl_s),
                "source_ref": projection.source_refs[0]
                if projection.source_refs
                else "source:audio_safe_for_broadcast",
            }
        )
    return payload


def _producer_refs(row: AudioSurfaceFixture) -> tuple[str, ...]:
    if row.surface_id == BROADCAST_HEALTH_SURFACE_ID:
        return ("producer:agents.broadcast_audio_health",)
    return ("producer:audio-world-surface-health-adapter",)


def _outcome_refs(row: AudioSurfaceFixture, projection: _AudioProjection) -> tuple[str, ...]:
    if projection.claimable_public_broadcast:
        return ("outcome:audio.broadcast_voice:public-egress-marker",)
    if row.surface_id in PRIVATE_AUDIO_SURFACE_IDS and projection.private_only:
        return (f"outcome:{row.surface_id}:private-monitor",)
    return ()


def _authority_ceiling_for(
    row: AudioSurfaceFixture,
    projection: _AudioProjection,
) -> AuthorityCeiling:
    if row.surface_id in PRIVATE_AUDIO_SURFACE_IDS:
        return AuthorityCeiling.INTERNAL_ONLY
    if projection.witness_refs:
        return AuthorityCeiling.EVIDENCE_BOUND
    if projection.fixture_case is FixtureCase.COMMANDED_ONLY:
        return AuthorityCeiling.NO_CLAIM
    return AuthorityCeiling.SPECULATIVE


def _privacy_state_for(
    row: AudioSurfaceFixture,
    projection: _AudioProjection,
    health_status: HealthStatus,
) -> PrivacyState:
    if projection.private_only or row.surface_id in PRIVATE_AUDIO_SURFACE_IDS:
        return PrivacyState.PRIVATE_ONLY
    if health_status is HealthStatus.UNSAFE:
        return PrivacyState.BLOCKED
    if health_status is HealthStatus.UNKNOWN:
        return PrivacyState.UNKNOWN
    return (
        PrivacyState.PUBLIC_SAFE
        if row.surface_id in PUBLIC_AUDIO_SURFACE_IDS
        else PrivacyState.UNKNOWN
    )


def _rights_state_for(
    row: AudioSurfaceFixture,
    projection: _AudioProjection,
    claimable: bool,
) -> RightsState:
    if claimable:
        return RightsState.PUBLIC_CLEAR
    if row.surface_id == PROGRAMME_AUDIO_SURFACE_ID:
        return RightsState.UNKNOWN
    if row.surface_id in PRIVATE_AUDIO_SURFACE_IDS:
        return RightsState.PRIVATE_ONLY
    if projection.health_state is AudioHealthState.UNKNOWN:
        return RightsState.UNKNOWN
    return RightsState.NOT_APPLICABLE


def _posture_for(
    row: AudioSurfaceFixture,
    projection: _AudioProjection,
    health_status: HealthStatus,
    claimable: bool,
) -> PublicPrivatePosture:
    if claimable:
        return PublicPrivatePosture.PUBLIC_LIVE
    if projection.private_only or row.surface_id in PRIVATE_AUDIO_SURFACE_IDS:
        return (
            PublicPrivatePosture.PRIVATE_ONLY
            if projection.private_only
            else PublicPrivatePosture.BLOCKED
        )
    if projection.health_state is AudioHealthState.QUIET_OFF_AIR:
        return PublicPrivatePosture.DISABLED
    if health_status in {HealthStatus.BLOCKED, HealthStatus.MISSING, HealthStatus.UNSAFE}:
        return PublicPrivatePosture.BLOCKED
    return PublicPrivatePosture.DRY_RUN


def _blocking_reasons_for(
    row: AudioSurfaceFixture,
    projection: _AudioProjection,
    health_status: HealthStatus,
    claimable: bool,
) -> list[str]:
    if claimable:
        return []
    reasons = list(projection.blocking_reasons)
    if health_status is HealthStatus.PRIVATE_ONLY:
        reasons.append("private_only_not_public")
    if health_status is HealthStatus.HEALTHY and row.surface_id not in {
        NO_LEAK_SURFACE_ID,
        L12_CAPTURE_SURFACE_ID,
        BROADCAST_EGRESS_SURFACE_ID,
        BROADCAST_HEALTH_SURFACE_ID,
    }:
        reasons.append("not_public_claim_authority")
    if health_status is not HealthStatus.HEALTHY and not reasons:
        reasons.append(f"audio_health_state:{projection.health_state.value}")
    return list(_dedupe(reasons))


def _fallback_mode_for(row: AudioSurfaceFixture) -> FallbackMode:
    mode = row.route_result.fallback_policy.mode
    if mode in {"blocked_absent_silence", "unsafe_block", "stale_block"}:
        return FallbackMode.SUPPRESS
    if mode == "block_public_speech":
        return FallbackMode.BLOCK_PUBLIC_CLAIM
    if mode == "private_only":
        return FallbackMode.PRIVATE_ONLY
    if mode == "dry_run":
        return FallbackMode.DRY_RUN_BADGE
    return FallbackMode.NO_OP_EXPLAIN


def _fallback_safe_state_for(row: AudioSurfaceFixture, projection: _AudioProjection) -> str:
    if projection.private_only:
        return "private_only"
    if row.surface_id in PRIVATE_AUDIO_SURFACE_IDS:
        return "silent_no_fallback"
    if projection.health_state is AudioHealthState.QUIET_OFF_AIR:
        return "quiet_off_air"
    return "block_public_audio"


def _aggregate_audio_state(audio_health: BroadcastAudioHealth) -> AudioHealthState:
    codes = _reason_codes(audio_health)
    if audio_health.safe:
        return (
            AudioHealthState.DEGRADED
            if audio_health.status is BroadcastAudioStatus.DEGRADED
            else AudioHealthState.SAFE
        )
    if any("stale" in code for code in codes):
        return AudioHealthState.STALE
    if any(
        token in code
        for code in codes
        for token in ("malformed", "unreadable", "schema", "service_failed", "descriptor_missing")
    ):
        return AudioHealthState.BROKEN
    if audio_health.status is BroadcastAudioStatus.UNKNOWN:
        return AudioHealthState.UNKNOWN
    return AudioHealthState.UNSAFE


def _fixture_case_for(
    row: AudioSurfaceFixture,
    state: AudioHealthState,
    witnessed: bool,
    *,
    command_only: bool,
) -> FixtureCase:
    if command_only:
        return FixtureCase.COMMANDED_ONLY
    if row.surface_id in PRIVATE_AUDIO_SURFACE_IDS and state is AudioHealthState.SAFE:
        return FixtureCase.PRIVATE_ONLY
    if state is AudioHealthState.SAFE and witnessed:
        return FixtureCase.HEALTHY_WITNESSED
    if state is AudioHealthState.DEGRADED:
        return FixtureCase.DEGRADED_WITNESSED if witnessed else FixtureCase.UNKNOWN
    if state is AudioHealthState.UNSAFE:
        return FixtureCase.UNSAFE_NO_LEAK
    if state is AudioHealthState.STALE:
        return FixtureCase.STALE
    if state is AudioHealthState.BROKEN:
        return FixtureCase.MISSING
    if state is AudioHealthState.BLOCKED_ABSENT:
        return FixtureCase.BLOCKED_WITH_REASON
    if state is AudioHealthState.QUIET_OFF_AIR:
        return FixtureCase.QUIET_OFF_AIR
    return FixtureCase.UNKNOWN


def _witness_policy_for(
    state: AudioHealthState,
    witnessed: bool,
    *,
    command_only: bool,
) -> WitnessPolicy:
    if command_only:
        return WitnessPolicy.COMMANDED_ONLY
    if witnessed:
        return WitnessPolicy.WITNESSED
    if state in {
        AudioHealthState.UNKNOWN,
        AudioHealthState.STALE,
        AudioHealthState.BROKEN,
        AudioHealthState.BLOCKED_ABSENT,
        AudioHealthState.QUIET_OFF_AIR,
    }:
        return WitnessPolicy.ABSENT
    return WitnessPolicy.FIXTURE_ONLY


def _reasons_for_state(
    row: AudioSurfaceFixture,
    state: AudioHealthState,
    explicit_reasons: tuple[str, ...],
) -> tuple[str, ...]:
    if explicit_reasons:
        return _dedupe(explicit_reasons)
    if state is AudioHealthState.SAFE:
        return ()
    return tuple(row.blocked_reasons)


def _reason_codes(audio_health: BroadcastAudioHealth) -> tuple[str, ...]:
    return tuple(reason.code for reason in audio_health.blocking_reasons)


def _matching_reason_codes(audio_health: BroadcastAudioHealth, token: str) -> tuple[str, ...]:
    return tuple(code for code in _reason_codes(audio_health) if token in code)


def _evidence_dict(audio_health: BroadcastAudioHealth, key: str) -> dict[str, Any]:
    value = audio_health.evidence.get(key, {})
    return value if isinstance(value, dict) else {}


def _evidence_passed(evidence: Mapping[str, Any]) -> bool:
    status = evidence.get("status")
    return status == "pass" or evidence.get("verification") == "pass"


def _voice_marker_is_public_audible(audio_health: BroadcastAudioHealth) -> bool:
    voice = _evidence_dict(audio_health, "voice_output_witness")
    return (
        voice.get("media_role") == PUBLIC_BROADCAST_MEDIA_ROLE
        and voice.get("target") in PUBLIC_BROADCAST_TARGETS
        and bool(voice.get("route_present"))
        and bool(voice.get("playback_present"))
        and voice.get("egress_audible") is True
    )


def _voice_witness_is_stale_or_broken(voice: Mapping[str, Any]) -> bool:
    return voice.get("status") in {"stale", "malformed", "unreadable"}


def _broadcast_voice_commanded_without_marker(voice: Mapping[str, Any]) -> bool:
    return bool(voice.get("planned_utterance")) and not (
        bool(voice.get("playback_present")) and voice.get("egress_audible") is True
    )


def _public_broadcast_ready(records: list[WorldSurfaceHealthRecord]) -> bool:
    by_surface = {record.surface_id.removesuffix(".health"): record for record in records}
    required = [
        by_surface[surface_id] for surface_id in sorted(PUBLIC_BROADCAST_READY_REQUIRED_SURFACE_IDS)
    ]
    return (
        all(record.status is HealthStatus.HEALTHY for record in required)
        and by_surface[PUBLIC_BROADCAST_SURFACE_ID].satisfies_claimable_health()
    )


def _overall_status(records: list[WorldSurfaceHealthRecord]) -> EnvelopeStatus:
    statuses = [record.status for record in records]
    if HealthStatus.UNSAFE in statuses:
        return EnvelopeStatus.UNSAFE
    if any(status in statuses for status in {HealthStatus.BLOCKED, HealthStatus.MISSING}):
        return EnvelopeStatus.BLOCKED
    if any(status in statuses for status in {HealthStatus.UNKNOWN, HealthStatus.CANDIDATE}):
        return EnvelopeStatus.UNKNOWN
    if any(
        status in statuses
        for status in {
            HealthStatus.DEGRADED,
            HealthStatus.STALE,
            HealthStatus.PRIVATE_ONLY,
            HealthStatus.DRY_RUN,
            HealthStatus.QUIET_OFF_AIR,
        }
    ):
        return EnvelopeStatus.DEGRADED
    return EnvelopeStatus.HEALTHY


def _summary(records: list[WorldSurfaceHealthRecord]) -> dict[str, object]:
    statuses = [record.status for record in records]
    families = [record.surface_family for record in records]
    return {
        "total_records": len(records),
        "by_status": {status.value: statuses.count(status) for status in sorted(set(statuses))},
        "by_surface_family": {
            family.value: families.count(family) for family in sorted(set(families))
        },
        "claimable_health_count": sum(record.satisfies_claimable_health() for record in records),
        "public_claim_allowed_count": sum(record.public_claim_allowed for record in records),
    }


def _false_grounding_risk_count(records: list[WorldSurfaceHealthRecord]) -> int:
    risky_witness_policies = {
        WitnessPolicy.INFERRED,
        WitnessPolicy.SELECTED_ONLY,
        WitnessPolicy.COMMANDED_ONLY,
    }
    return sum(
        record.fixture_case.value in REQUIRED_CLAIM_BLOCKER_CASES
        or record.witness_policy in risky_witness_policies
        for record in records
    )


def _next_required_actions(records: list[WorldSurfaceHealthRecord]) -> list[str]:
    if any(record.satisfies_claimable_health() for record in records):
        return ["Continue scheduled audio surface probes before TTL expiry."]
    reasons = [
        f"{record.surface_id}:{reason}"
        for record in records
        for reason in record.blocking_reasons[:2]
    ]
    return reasons[:6] or ["Collect fresh audio world-surface witnesses."]


def _health_surface_id(surface_id: str) -> str:
    return f"{surface_id}.health"


def _next_probe_due_at(checked_at: str, ttl_s: int) -> str:
    try:
        base = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
    except ValueError:
        base = datetime.now(tz=UTC)
    return (base + timedelta(seconds=ttl_s)).isoformat().replace("+00:00", "Z")


def _dedupe(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


__all__ = [
    "BROADCAST_HEALTH_SURFACE_ID",
    "NO_LEAK_SURFACE_ID",
    "PUBLIC_BROADCAST_READY_REQUIRED_SURFACE_IDS",
    "PUBLIC_BROADCAST_SURFACE_ID",
    "AudioSurfaceObservation",
    "AudioWorldSurfaceHealthError",
    "load_audio_world_surface_health",
    "project_audio_world_surface_health",
]
