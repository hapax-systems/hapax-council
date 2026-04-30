"""Dry-run and fixture harness for audio marker probes.

The harness models marker evidence without touching PipeWire, systemd,
Daimonion, microphones, or speakers. Live execution is represented only as a
fail-closed authorization contract so future live runners cannot bypass the
private-voice hard stop and cx-red/operator authorization gates.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from shared.audio_world_surface_fixtures import AudioHealthState, AudioWitnessClassId
from shared.audio_world_surface_health import AudioSurfaceObservation

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIO_MARKER_PROBE_FIXTURES = REPO_ROOT / "config" / "audio-marker-probe-fixtures.json"

REQUIRED_AUDIO_MARKER_FIXTURE_CASES = frozenset(
    {
        "dry_run_public_plan_only",
        "public_marker_witnessed",
        "private_marker_witnessed_no_leak",
        "no_leak_clean",
        "private_marker_leaked_public_negative",
        "live_execution_blocked_without_authorization",
        "commanded_without_marker",
    }
)

FAIL_CLOSED_POLICY = {
    "dry_run_is_live_truth": False,
    "live_execution_without_authorization": False,
    "private_marker_on_public_path_allowed": False,
    "public_claim_without_no_leak": False,
    "fixtures_unmask_restart_or_unmute_services": False,
    "fixture_result_allows_live_execution": False,
}


class AudioMarkerProbeHarnessError(ValueError):
    """Raised when audio marker probe fixtures or evaluations are unsafe."""


class MarkerProbeKind(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"
    NO_LEAK = "no_leak"


class MarkerProbeMode(StrEnum):
    DRY_RUN = "dry_run"
    FIXTURE = "fixture"
    LIVE = "live"


class MarkerProbeState(StrEnum):
    DRY_RUN_PLANNED = "dry_run_planned"
    WITNESSED = "witnessed"
    BLOCKED = "blocked"
    FAILED = "failed"


class MarkerFailureClass(StrEnum):
    DRY_RUN_NOT_RUNTIME_WITNESS = "dry_run_not_runtime_witness"
    LIVE_EXECUTION_NOT_AUTHORIZED = "live_execution_not_authorized"
    ROUTE_OR_PLAYBACK_MISSING = "route_or_playback_missing"
    PUBLIC_MARKER_MISSING = "public_marker_missing"
    PRIVATE_MARKER_MISSING = "private_marker_missing"
    PRIVATE_MARKER_LEAKED_PUBLIC = "private_marker_leaked_public"
    LEAK_SCAN_MISSING = "leak_scan_missing"
    NO_LEAK_WITNESS_MISSING = "no_leak_witness_missing"


class AudioMarkerProbeAuthorization(BaseModel):
    """Authorization contract for future live marker execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    private_voice_hard_stop_deployed: bool = False
    cx_red_or_operator_authorized: bool = False
    live_audio_probe_authorized: bool = False
    authorization_ref: str | None = None
    checked_at: str | None = None

    def live_execution_allowed(self) -> bool:
        return (
            self.private_voice_hard_stop_deployed
            and self.cx_red_or_operator_authorized
            and self.live_audio_probe_authorized
        )

    def blocking_reasons(self) -> list[str]:
        reasons: list[str] = []
        if not self.private_voice_hard_stop_deployed:
            reasons.append("private_voice_hard_stop_not_deployed")
        if not self.cx_red_or_operator_authorized:
            reasons.append("cx_red_or_operator_authorization_missing")
        if not self.live_audio_probe_authorized:
            reasons.append("live_audio_probe_authorization_missing")
        return reasons


class AudioMarkerProbeObservation(BaseModel):
    """Fixture observation of where a marker appeared."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    route_present: bool = False
    playback_present: bool = False
    egress_audible: bool | None = None
    marker_seen_on_public_paths: list[str] = Field(default_factory=list)
    marker_seen_on_private_targets: list[str] = Field(default_factory=list)
    private_marker_seen_on_public_paths: list[str] = Field(default_factory=list)
    leak_scan_completed: bool = False
    observed_at: str | None = None


class AudioMarkerProbeFixture(BaseModel):
    """One dry-run or fixture marker probe scenario."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    fixture_case: str
    probe_id: str
    probe_kind: MarkerProbeKind
    mode: MarkerProbeMode
    surface_id: str
    semantic_destination: str
    marker_id: str
    marker_label: str
    target_ref: str
    route_ref: str
    witness_class: AudioWitnessClassId
    source_refs: list[str] = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    freshness_window_s: int = Field(default=30, ge=0)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    required_for_public_claim: bool = False
    live_execution_requested: bool = False
    observation: AudioMarkerProbeObservation
    expected_state: MarkerProbeState
    expected_health_state: AudioHealthState
    expected_failure_class: MarkerFailureClass | None = None
    expected_public_claim_allowed: bool = False
    expected_private_only: bool = False

    @model_validator(mode="after")
    def _validate_mode_and_witness(self) -> Self:
        expected_witness = {
            MarkerProbeKind.PUBLIC: AudioWitnessClassId.PUBLIC,
            MarkerProbeKind.PRIVATE: AudioWitnessClassId.PRIVATE,
            MarkerProbeKind.NO_LEAK: AudioWitnessClassId.NO_LEAK,
        }[self.probe_kind]
        if self.witness_class is not expected_witness:
            raise ValueError(f"{self.fixture_case} witness_class must be {expected_witness.value}")
        if self.live_execution_requested and self.mode is not MarkerProbeMode.LIVE:
            raise ValueError("live_execution_requested requires mode=live")
        if self.expected_public_claim_allowed and self.probe_kind is not MarkerProbeKind.PUBLIC:
            raise ValueError("only public marker probes may allow public claims")
        if self.expected_private_only and self.probe_kind is MarkerProbeKind.PUBLIC:
            raise ValueError("public marker probes cannot be private_only")
        return self


class AudioMarkerProbeResult(BaseModel):
    """Evaluated marker probe result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    probe_id: str
    fixture_case: str
    probe_kind: MarkerProbeKind
    mode: MarkerProbeMode
    surface_id: str
    semantic_destination: str
    marker_id: str
    target_ref: str
    route_ref: str
    witness_class: AudioWitnessClassId
    state: MarkerProbeState
    health_state: AudioHealthState
    checked_at: str
    observed_at: str | None = None
    freshness_window_s: int
    confidence: float
    source_refs: list[str] = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    witness_refs: list[str] = Field(default_factory=list)
    public_path_refs: list[str] = Field(default_factory=list)
    private_target_refs: list[str] = Field(default_factory=list)
    no_leak_passed: bool = False
    public_claim_allowed: bool = False
    private_only: bool = False
    live_execution_permitted: bool = False
    failure_class: MarkerFailureClass | None = None
    blocked_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    certifies_marker_observation_only: Literal[True] = True


class AudioMarkerProbeFixtureSet(BaseModel):
    """Fixture packet for the marker probe harness."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    fixture_set_id: str
    schema_ref: str
    generated_from: list[str] = Field(min_length=1)
    declared_at: str
    producer: str
    required_fixture_cases: list[str] = Field(min_length=1)
    marker_probe_kinds: list[MarkerProbeKind] = Field(min_length=1)
    modes: list[MarkerProbeMode] = Field(min_length=1)
    states: list[MarkerProbeState] = Field(min_length=1)
    probes: list[AudioMarkerProbeFixture] = Field(min_length=1)
    fail_closed_policy: dict[str, bool]

    @model_validator(mode="after")
    def _validate_contract_coverage(self) -> Self:
        if set(self.required_fixture_cases) != REQUIRED_AUDIO_MARKER_FIXTURE_CASES:
            raise ValueError("required_fixture_cases must match the marker probe contract")
        fixture_cases = {probe.fixture_case for probe in self.probes}
        missing_cases = REQUIRED_AUDIO_MARKER_FIXTURE_CASES - fixture_cases
        if missing_cases:
            raise ValueError(
                "missing marker probe fixture cases: " + ", ".join(sorted(missing_cases))
            )

        probe_ids = [probe.probe_id for probe in self.probes]
        duplicates = sorted({probe_id for probe_id in probe_ids if probe_ids.count(probe_id) > 1})
        if duplicates:
            raise ValueError("duplicate marker probe ids: " + ", ".join(duplicates))

        if set(kind.value for kind in self.marker_probe_kinds) != {
            kind.value for kind in MarkerProbeKind
        }:
            raise ValueError("marker_probe_kinds must cover public, private, and no_leak")
        if set(mode.value for mode in self.modes) != {mode.value for mode in MarkerProbeMode}:
            raise ValueError("modes must cover dry_run, fixture, and live")
        if set(state.value for state in self.states) != {state.value for state in MarkerProbeState}:
            raise ValueError("states must cover all marker probe result states")
        if self.fail_closed_policy != FAIL_CLOSED_POLICY:
            raise ValueError("fail_closed_policy must pin dry-run/live/no-leak gates closed")
        return self

    def probes_by_case(self) -> dict[str, AudioMarkerProbeFixture]:
        return {probe.fixture_case: probe for probe in self.probes}

    def require_case(self, fixture_case: str) -> AudioMarkerProbeFixture:
        probe = self.probes_by_case().get(fixture_case)
        if probe is None:
            raise KeyError(f"unknown audio marker probe fixture case: {fixture_case}")
        return probe


def load_audio_marker_probe_fixtures(
    path: Path = AUDIO_MARKER_PROBE_FIXTURES,
) -> AudioMarkerProbeFixtureSet:
    """Load fixture-backed marker probe contracts."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return AudioMarkerProbeFixtureSet.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise AudioMarkerProbeHarnessError(
            f"invalid audio marker probe fixtures at {path}: {exc}"
        ) from exc


def evaluate_marker_probe(
    fixture: AudioMarkerProbeFixture,
    *,
    authorization: AudioMarkerProbeAuthorization | None = None,
    checked_at: str | None = None,
) -> AudioMarkerProbeResult:
    """Evaluate one marker fixture without touching live audio."""

    now = checked_at or _utc_now()
    auth = authorization or AudioMarkerProbeAuthorization()
    base = _base_result_kwargs(fixture, checked_at=now, authorization=auth)

    if fixture.mode is MarkerProbeMode.DRY_RUN:
        return AudioMarkerProbeResult(
            **base,
            state=MarkerProbeState.DRY_RUN_PLANNED,
            health_state=AudioHealthState.UNKNOWN,
            failure_class=MarkerFailureClass.DRY_RUN_NOT_RUNTIME_WITNESS,
            blocked_reasons=["dry_run_not_runtime_witness", "no_live_audio_action_taken"],
            warnings=["dry_run_plan_only"],
        )

    if fixture.mode is MarkerProbeMode.LIVE and not auth.live_execution_allowed():
        return AudioMarkerProbeResult(
            **base,
            state=MarkerProbeState.BLOCKED,
            health_state=AudioHealthState.BLOCKED_ABSENT,
            failure_class=MarkerFailureClass.LIVE_EXECUTION_NOT_AUTHORIZED,
            blocked_reasons=auth.blocking_reasons(),
        )

    if fixture.probe_kind is MarkerProbeKind.PUBLIC:
        return _evaluate_public_marker(fixture, base)
    if fixture.probe_kind is MarkerProbeKind.PRIVATE:
        return _evaluate_private_marker(fixture, base)
    return _evaluate_no_leak_marker(fixture, base)


def evaluate_marker_fixture_set(
    fixtures: AudioMarkerProbeFixtureSet,
    *,
    cases: list[str] | None = None,
    authorization: AudioMarkerProbeAuthorization | None = None,
    checked_at: str | None = None,
) -> list[AudioMarkerProbeResult]:
    """Evaluate selected fixture cases, or every case when omitted."""

    selected = [fixtures.require_case(case) for case in cases] if cases else fixtures.probes
    return [
        evaluate_marker_probe(probe, authorization=authorization, checked_at=checked_at)
        for probe in selected
    ]


def result_to_audio_surface_observation(
    result: AudioMarkerProbeResult,
) -> AudioSurfaceObservation:
    """Project a marker result into the existing audio WCS observation shape."""

    return AudioSurfaceObservation(
        health_state=result.health_state,
        checked_at=result.checked_at,
        ttl_s=result.freshness_window_s,
        observed_age_s=0 if result.observed_at else None,
        source_refs=tuple(result.source_refs),
        evidence_refs=tuple(result.evidence_refs),
        witness_refs=tuple(result.witness_refs),
        route_refs=(result.route_ref,),
        blocking_reasons=tuple(result.blocked_reasons),
        warnings=tuple(result.warnings),
        confidence=result.confidence,
        private_only=result.private_only,
        note=result.failure_class.value if result.failure_class else None,
    )


def results_to_audio_surface_observations(
    results: list[AudioMarkerProbeResult],
) -> dict[str, AudioSurfaceObservation]:
    """Return WCS health observations keyed by audio surface id."""

    return {result.surface_id: result_to_audio_surface_observation(result) for result in results}


def _base_result_kwargs(
    fixture: AudioMarkerProbeFixture,
    *,
    checked_at: str,
    authorization: AudioMarkerProbeAuthorization,
) -> dict[str, Any]:
    observation = fixture.observation
    return {
        "probe_id": fixture.probe_id,
        "fixture_case": fixture.fixture_case,
        "probe_kind": fixture.probe_kind,
        "mode": fixture.mode,
        "surface_id": fixture.surface_id,
        "semantic_destination": fixture.semantic_destination,
        "marker_id": fixture.marker_id,
        "target_ref": fixture.target_ref,
        "route_ref": fixture.route_ref,
        "witness_class": fixture.witness_class,
        "checked_at": checked_at,
        "observed_at": observation.observed_at,
        "freshness_window_s": fixture.freshness_window_s,
        "confidence": fixture.confidence,
        "source_refs": _dedupe([*fixture.source_refs, f"fixture:{fixture.fixture_case}"]),
        "evidence_refs": _dedupe(fixture.evidence_refs),
        "public_path_refs": _dedupe(
            [
                *observation.marker_seen_on_public_paths,
                *observation.private_marker_seen_on_public_paths,
            ]
        ),
        "private_target_refs": _dedupe(observation.marker_seen_on_private_targets),
        "live_execution_permitted": authorization.live_execution_allowed(),
    }


def _evaluate_public_marker(
    fixture: AudioMarkerProbeFixture,
    base: dict[str, Any],
) -> AudioMarkerProbeResult:
    observation = fixture.observation
    blockers = _route_playback_blockers(observation)
    public_marker_seen = bool(observation.marker_seen_on_public_paths)
    private_leak = bool(observation.private_marker_seen_on_public_paths)
    if not public_marker_seen:
        blockers.append("public_marker_missing")
    if not observation.leak_scan_completed:
        blockers.append("no_leak_witness_missing")
    if private_leak:
        blockers.append("private_marker_leaked_public")

    if blockers:
        failure = (
            MarkerFailureClass.PRIVATE_MARKER_LEAKED_PUBLIC
            if private_leak
            else _first_public_failure(blockers)
        )
        health = AudioHealthState.UNSAFE if private_leak else AudioHealthState.UNKNOWN
        return AudioMarkerProbeResult(
            **base,
            state=MarkerProbeState.FAILED if private_leak else MarkerProbeState.BLOCKED,
            health_state=health,
            failure_class=failure,
            blocked_reasons=_dedupe(blockers),
        )

    return AudioMarkerProbeResult(
        **base,
        state=MarkerProbeState.WITNESSED,
        health_state=AudioHealthState.SAFE,
        witness_refs=[f"witness:{fixture.surface_id}:{fixture.marker_id}:public-egress"],
        no_leak_passed=True,
        public_claim_allowed=fixture.required_for_public_claim,
    )


def _evaluate_private_marker(
    fixture: AudioMarkerProbeFixture,
    base: dict[str, Any],
) -> AudioMarkerProbeResult:
    observation = fixture.observation
    blockers = _route_playback_blockers(observation)
    private_marker_seen = bool(observation.marker_seen_on_private_targets)
    public_leak = bool(observation.marker_seen_on_public_paths)
    if not private_marker_seen:
        blockers.append("private_marker_missing")
    if public_leak:
        blockers.append("private_marker_leaked_public")
    if not observation.leak_scan_completed:
        blockers.append("leak_scan_missing")

    if public_leak:
        return AudioMarkerProbeResult(
            **base,
            state=MarkerProbeState.FAILED,
            health_state=AudioHealthState.UNSAFE,
            failure_class=MarkerFailureClass.PRIVATE_MARKER_LEAKED_PUBLIC,
            blocked_reasons=_dedupe(blockers),
        )
    if blockers:
        return AudioMarkerProbeResult(
            **base,
            state=MarkerProbeState.BLOCKED,
            health_state=AudioHealthState.BLOCKED_ABSENT,
            failure_class=_first_private_failure(blockers),
            blocked_reasons=_dedupe(blockers),
        )

    return AudioMarkerProbeResult(
        **base,
        state=MarkerProbeState.WITNESSED,
        health_state=AudioHealthState.SAFE,
        witness_refs=[f"witness:{fixture.surface_id}:{fixture.marker_id}:private-target"],
        no_leak_passed=True,
        private_only=True,
    )


def _evaluate_no_leak_marker(
    fixture: AudioMarkerProbeFixture,
    base: dict[str, Any],
) -> AudioMarkerProbeResult:
    observation = fixture.observation
    public_hits = [
        *observation.marker_seen_on_public_paths,
        *observation.private_marker_seen_on_public_paths,
    ]
    if public_hits:
        return AudioMarkerProbeResult(
            **base,
            state=MarkerProbeState.FAILED,
            health_state=AudioHealthState.UNSAFE,
            failure_class=MarkerFailureClass.PRIVATE_MARKER_LEAKED_PUBLIC,
            blocked_reasons=["private_marker_leaked_public"],
        )
    if not observation.leak_scan_completed:
        return AudioMarkerProbeResult(
            **base,
            state=MarkerProbeState.BLOCKED,
            health_state=AudioHealthState.UNKNOWN,
            failure_class=MarkerFailureClass.LEAK_SCAN_MISSING,
            blocked_reasons=["leak_scan_missing"],
        )
    return AudioMarkerProbeResult(
        **base,
        state=MarkerProbeState.WITNESSED,
        health_state=AudioHealthState.SAFE,
        witness_refs=[f"witness:{fixture.surface_id}:{fixture.marker_id}:no-leak"],
        no_leak_passed=True,
    )


def _route_playback_blockers(observation: AudioMarkerProbeObservation) -> list[str]:
    blockers: list[str] = []
    if not observation.route_present:
        blockers.append("route_missing")
    if not observation.playback_present:
        blockers.append("playback_missing")
    if observation.egress_audible is False:
        blockers.append("egress_not_audible")
    return blockers


def _first_public_failure(blockers: list[str]) -> MarkerFailureClass:
    if (
        "route_missing" in blockers
        or "playback_missing" in blockers
        or "egress_not_audible" in blockers
    ):
        return MarkerFailureClass.ROUTE_OR_PLAYBACK_MISSING
    if "public_marker_missing" in blockers:
        return MarkerFailureClass.PUBLIC_MARKER_MISSING
    if "no_leak_witness_missing" in blockers:
        return MarkerFailureClass.NO_LEAK_WITNESS_MISSING
    return MarkerFailureClass.PUBLIC_MARKER_MISSING


def _first_private_failure(blockers: list[str]) -> MarkerFailureClass:
    if "route_missing" in blockers or "playback_missing" in blockers:
        return MarkerFailureClass.ROUTE_OR_PLAYBACK_MISSING
    if "private_marker_missing" in blockers:
        return MarkerFailureClass.PRIVATE_MARKER_MISSING
    if "leak_scan_missing" in blockers:
        return MarkerFailureClass.LEAK_SCAN_MISSING
    return MarkerFailureClass.PRIVATE_MARKER_MISSING


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _utc_now() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "AUDIO_MARKER_PROBE_FIXTURES",
    "FAIL_CLOSED_POLICY",
    "REQUIRED_AUDIO_MARKER_FIXTURE_CASES",
    "AudioMarkerProbeAuthorization",
    "AudioMarkerProbeFixture",
    "AudioMarkerProbeFixtureSet",
    "AudioMarkerProbeHarnessError",
    "AudioMarkerProbeObservation",
    "AudioMarkerProbeResult",
    "MarkerFailureClass",
    "MarkerProbeKind",
    "MarkerProbeMode",
    "MarkerProbeState",
    "evaluate_marker_fixture_set",
    "evaluate_marker_probe",
    "load_audio_marker_probe_fixtures",
    "result_to_audio_surface_observation",
    "results_to_audio_surface_observations",
]
