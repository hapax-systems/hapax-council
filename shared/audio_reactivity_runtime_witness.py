"""Fixture and dry-run runtime witness for audio reactivity calibration.

The harness joins five things that should travel together before a visual
surface claims audio reactivity: source-role audio evidence, egress posture,
visual response witness, anti-visualizer score, and durable trace export.

It is deliberately fixture-first. The optional runtime probe only records the
shape of current ``/dev/shm`` JSON surfaces; it does not certify live audio or
change hardware routes.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from shared.audio_source_evidence import ActivityBasis, AudioSourceRole, FreshnessState

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIO_REACTIVITY_RUNTIME_WITNESS_FIXTURES = (
    REPO_ROOT / "config" / "audio-reactivity-runtime-witness-fixtures.json"
)
DEFAULT_UNIFIED_REACTIVITY_PATH = Path("/dev/shm/hapax-compositor/unified-reactivity.json")
DEFAULT_AUDIO_SOURCE_LEDGER_PATH = Path("/dev/shm/hapax-compositor/audio-source-ledger.json")
DEFAULT_BROADCAST_HEALTH_PATH = Path("/dev/shm/hapax-broadcast/audio-safe-for-broadcast.json")
DEFAULT_ANTI_VISUALIZER_THRESHOLD = 0.45

REQUIRED_RUNTIME_WITNESS_FIXTURE_CASES = frozenset(
    {
        "false_activity_process_liveness",
        "stale_activity_music_marker",
        "wrong_source_youtube_react_audio",
        "audible_programme_visual_source_silent",
        "silent_broadcast_egress",
        "legitimate_high_reactivity_music",
        "visualizer_register_blocked",
    }
)

FAIL_CLOSED_POLICY = {
    "process_liveness_certifies_audio_source": False,
    "route_existence_certifies_visual_source": False,
    "public_egress_certifies_visual_source": False,
    "visual_response_without_frame_witness": False,
    "anti_visualizer_threshold_bypass": False,
    "runtime_shape_probe_certifies_live_audio": False,
}


class AudioReactivityRuntimeWitnessError(ValueError):
    """Raised when runtime witness fixtures or traces are invalid."""


class AudioReactivityStimulusKind(StrEnum):
    SILENCE = "silence"
    MUSIC = "music"
    YOUTUBE_REACT_AUDIO = "youtube_react_audio"
    TTS = "tts"
    OPERATOR_VOICE = "operator_voice"
    CONTACT_DESK = "contact_desk"
    M8_S4 = "m8_s4"
    BROADCAST_EGRESS = "broadcast_egress"
    MIXED_SOURCE = "mixed_source"


class AudioReactivityWitnessState(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


class AudioReactivityFailureClass(StrEnum):
    FALSE_PROCESS_ACTIVITY = "false_process_activity"
    STALE_AUDIO_EVIDENCE = "stale_audio_evidence"
    WRONG_SOURCE_ROLE = "wrong_source_role"
    VISUAL_SOURCE_SILENT = "visual_source_silent"
    BROADCAST_EGRESS_SILENT = "broadcast_egress_silent"
    VISUAL_RESPONSE_MISSING = "visual_response_missing"
    VISUALIZER_REGISTER_EXCEEDED = "visualizer_register_exceeded"
    LEDGER_EVIDENCE_MISSING = "ledger_evidence_missing"


class RuntimeAudioLedgerRowFixture(BaseModel):
    """Fixture projection of one expected audio source ledger row."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str
    role: AudioSourceRole
    active: bool = False
    freshness: FreshnessState = FreshnessState.MISSING
    activity_basis: ActivityBasis = ActivityBasis.MISSING
    rms: float = Field(default=0.0, ge=0.0, le=1.0)
    public_audible: bool = False
    visual_modulation_permitted: bool = False
    process_live: bool = False
    evidence_refs: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_active_source_evidence(self) -> Self:
        if self.active and self.freshness is not FreshnessState.FRESH:
            raise ValueError(f"{self.source_id} active row requires fresh evidence")
        if self.active and self.activity_basis is ActivityBasis.PROCESS_ACTIVITY:
            raise ValueError(f"{self.source_id} process activity cannot mark active")
        if self.active and self.rms <= 0.0 and self.activity_basis is ActivityBasis.MEASURED_SIGNAL:
            raise ValueError(f"{self.source_id} measured active row requires non-zero rms")
        return self


class ProgrammeEgressFixture(BaseModel):
    """Fixture observation of public programme/egress posture."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    programme_path_active: bool = False
    egress_audible: bool = False
    egress_source_id: str = "broadcast-egress"
    loudness_lufs_i: float | None = None
    observed_at: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class VisualResponseFixture(BaseModel):
    """Fixture observation of visual response and anti-visualizer score."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    visual_response_id: str
    response_present: bool = False
    frame_witness_ref: str | None = None
    lane_witness_ref: str | None = None
    variance_ledger_ref: str | None = None
    observed_at: str | None = None
    modulation_range: tuple[float, float] = Field(default=(0.0, 0.0))
    anti_visualizer_score: float = Field(ge=0.0, le=1.0)
    anti_visualizer_threshold: float = Field(
        default=DEFAULT_ANTI_VISUALIZER_THRESHOLD,
        ge=0.0,
        le=1.0,
    )
    visualizer_register: bool = False

    @model_validator(mode="after")
    def _validate_response_witnesses(self) -> Self:
        if self.response_present and not self.frame_witness_ref:
            raise ValueError("response_present requires frame_witness_ref")
        if self.response_present and not self.lane_witness_ref:
            raise ValueError("response_present requires lane_witness_ref")
        if self.response_present and not self.variance_ledger_ref:
            raise ValueError("response_present requires variance_ledger_ref")
        if (
            self.visualizer_register
            and self.anti_visualizer_score <= self.anti_visualizer_threshold
        ):
            raise ValueError("visualizer_register requires score above threshold")
        return self


class AudioReactivityRuntimeWitnessFixture(BaseModel):
    """One audio-to-visual witness fixture scenario."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    fixture_case: str
    witness_id: str
    stimulus_kind: AudioReactivityStimulusKind
    expected_source_role: AudioSourceRole
    expected_visual_source_id: str
    requires_public_egress: bool = True
    requires_visual_response: bool = True
    source_refs: list[str] = Field(min_length=1)
    ledger_rows: list[RuntimeAudioLedgerRowFixture] = Field(min_length=1)
    programme_egress: ProgrammeEgressFixture
    visual_response: VisualResponseFixture
    expected_state: AudioReactivityWitnessState
    expected_failure_class: AudioReactivityFailureClass | None = None

    @model_validator(mode="after")
    def _validate_expected_state(self) -> Self:
        if (
            self.expected_state is AudioReactivityWitnessState.PASSED
            and self.expected_failure_class
        ):
            raise ValueError("passed fixture cannot declare expected_failure_class")
        if self.expected_state is not AudioReactivityWitnessState.PASSED:
            if self.expected_failure_class is None:
                raise ValueError("non-passing fixture requires expected_failure_class")
        return self

    def expected_row(self) -> RuntimeAudioLedgerRowFixture | None:
        for row in self.ledger_rows:
            if (
                row.source_id == self.expected_visual_source_id
                and row.role is self.expected_source_role
            ):
                return row
        return None


class AudioReactivityRuntimeWitnessResult(BaseModel):
    """Evaluated witness result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    witness_id: str
    fixture_case: str
    stimulus_kind: AudioReactivityStimulusKind
    state: AudioReactivityWitnessState
    failure_class: AudioReactivityFailureClass | None = None
    checked_at: str
    expected_source_role: AudioSourceRole
    expected_visual_source_id: str
    selected_source_ids: list[str] = Field(default_factory=list)
    active_source_ids: list[str] = Field(default_factory=list)
    active_roles: list[AudioSourceRole] = Field(default_factory=list)
    source_role_verified: bool = False
    programme_path_active: bool = False
    egress_audible: bool = False
    visual_response_id: str
    visual_response_present: bool = False
    anti_visualizer_score: float = Field(ge=0.0, le=1.0)
    anti_visualizer_threshold: float = Field(ge=0.0, le=1.0)
    anti_visualizer_passed: bool = False
    public_claim_allowed: bool = False
    source_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    witness_refs: list[str] = Field(default_factory=list)
    wcs_refs: list[str] = Field(default_factory=list)
    variance_ledger_refs: list[str] = Field(default_factory=list)
    durable_trace_ref: str
    blocked_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    certifies_fixture_or_dry_run_only: Literal[True] = True


class AudioReactivityRuntimeWitnessFixtureSet(BaseModel):
    """Fixture packet for the runtime witness harness."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    fixture_set_id: str
    schema_ref: str
    generated_from: list[str] = Field(min_length=1)
    declared_at: str
    producer: str
    required_fixture_cases: list[str] = Field(min_length=1)
    stimulus_kinds: list[AudioReactivityStimulusKind] = Field(min_length=1)
    states: list[AudioReactivityWitnessState] = Field(min_length=1)
    fixtures: list[AudioReactivityRuntimeWitnessFixture] = Field(min_length=1)
    fail_closed_policy: dict[str, bool]

    @model_validator(mode="after")
    def _validate_contract_coverage(self) -> Self:
        if set(self.required_fixture_cases) != REQUIRED_RUNTIME_WITNESS_FIXTURE_CASES:
            raise ValueError("required_fixture_cases must match the runtime witness contract")

        fixture_cases = {fixture.fixture_case for fixture in self.fixtures}
        missing_cases = REQUIRED_RUNTIME_WITNESS_FIXTURE_CASES - fixture_cases
        if missing_cases:
            raise ValueError(
                "missing runtime witness fixture cases: " + ", ".join(sorted(missing_cases))
            )

        witness_ids = [fixture.witness_id for fixture in self.fixtures]
        duplicates = sorted(
            {witness_id for witness_id in witness_ids if witness_ids.count(witness_id) > 1}
        )
        if duplicates:
            raise ValueError("duplicate runtime witness ids: " + ", ".join(duplicates))

        if set(kind.value for kind in self.stimulus_kinds) != {
            kind.value for kind in AudioReactivityStimulusKind
        }:
            raise ValueError("stimulus_kinds must cover every audio reactivity stimulus kind")

        covered_stimuli = {fixture.stimulus_kind for fixture in self.fixtures}
        missing_stimuli = set(AudioReactivityStimulusKind) - covered_stimuli
        if missing_stimuli:
            raise ValueError(
                "missing runtime witness stimulus kinds: "
                + ", ".join(sorted(kind.value for kind in missing_stimuli))
            )

        if set(state.value for state in self.states) != {
            state.value for state in AudioReactivityWitnessState
        }:
            raise ValueError("states must cover passed, failed, and blocked")
        if self.fail_closed_policy != FAIL_CLOSED_POLICY:
            raise ValueError("fail_closed_policy must pin runtime witness gates closed")
        return self

    def fixtures_by_case(self) -> dict[str, AudioReactivityRuntimeWitnessFixture]:
        return {fixture.fixture_case: fixture for fixture in self.fixtures}

    def require_case(self, fixture_case: str) -> AudioReactivityRuntimeWitnessFixture:
        fixture = self.fixtures_by_case().get(fixture_case)
        if fixture is None:
            raise KeyError(f"unknown audio reactivity runtime witness fixture case: {fixture_case}")
        return fixture


class RuntimeShapeProbe(BaseModel):
    """Shape-only probe over current runtime JSON surfaces."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    checked_at: str
    unified_reactivity_path: str
    unified_reactivity_present: bool = False
    unified_per_source_keys: list[str] = Field(default_factory=list)
    unified_active_sources: list[str] = Field(default_factory=list)
    audio_source_ledger_path: str
    audio_source_ledger_present: bool = False
    ledger_source_ids: list[str] = Field(default_factory=list)
    ledger_roles: list[str] = Field(default_factory=list)
    broadcast_health_path: str
    broadcast_health_present: bool = False
    broadcast_safe: bool | None = None
    warnings: list[str] = Field(default_factory=list)
    certifies_shape_only: Literal[True] = True


def load_audio_reactivity_runtime_witness_fixtures(
    path: Path = AUDIO_REACTIVITY_RUNTIME_WITNESS_FIXTURES,
) -> AudioReactivityRuntimeWitnessFixtureSet:
    """Load fixture-backed audio reactivity runtime witness contracts."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return AudioReactivityRuntimeWitnessFixtureSet.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise AudioReactivityRuntimeWitnessError(
            f"invalid audio reactivity runtime witness fixtures at {path}: {exc}"
        ) from exc


def evaluate_runtime_witness(
    fixture: AudioReactivityRuntimeWitnessFixture,
    *,
    checked_at: str | None = None,
) -> AudioReactivityRuntimeWitnessResult:
    """Evaluate one runtime witness fixture without touching live audio."""

    now = checked_at or _utc_now()
    expected = fixture.expected_row()
    active_programme_rows = [
        row
        for row in fixture.ledger_rows
        if row.active and row.role is not AudioSourceRole.BROADCAST_EGRESS
    ]
    source_role_verified = _source_role_verified(expected)
    failure_class, blockers = _failure_for_fixture(
        fixture=fixture,
        expected=expected,
        active_programme_rows=active_programme_rows,
        source_role_verified=source_role_verified,
    )
    state = AudioReactivityWitnessState.PASSED
    if failure_class is not None:
        state = (
            AudioReactivityWitnessState.BLOCKED
            if failure_class
            in {
                AudioReactivityFailureClass.STALE_AUDIO_EVIDENCE,
                AudioReactivityFailureClass.LEDGER_EVIDENCE_MISSING,
            }
            else AudioReactivityWitnessState.FAILED
        )

    visual = fixture.visual_response
    evidence_refs = _dedupe(
        [
            *(ref for row in fixture.ledger_rows for ref in row.evidence_refs),
            *fixture.programme_egress.evidence_refs,
        ]
    )
    witness_refs = _dedupe(
        [
            ref
            for ref in (
                visual.frame_witness_ref,
                visual.lane_witness_ref,
            )
            if ref
        ]
    )
    variance_refs = [visual.variance_ledger_ref] if visual.variance_ledger_ref else []
    active_source_ids = [row.source_id for row in active_programme_rows]
    active_roles = _dedupe_roles([row.role for row in active_programme_rows])
    selected_source_ids = (
        [expected.source_id] if source_role_verified and expected is not None else []
    )

    return AudioReactivityRuntimeWitnessResult(
        witness_id=fixture.witness_id,
        fixture_case=fixture.fixture_case,
        stimulus_kind=fixture.stimulus_kind,
        state=state,
        failure_class=failure_class,
        checked_at=now,
        expected_source_role=fixture.expected_source_role,
        expected_visual_source_id=fixture.expected_visual_source_id,
        selected_source_ids=selected_source_ids,
        active_source_ids=active_source_ids,
        active_roles=active_roles,
        source_role_verified=source_role_verified,
        programme_path_active=fixture.programme_egress.programme_path_active,
        egress_audible=fixture.programme_egress.egress_audible,
        visual_response_id=visual.visual_response_id,
        visual_response_present=visual.response_present,
        anti_visualizer_score=visual.anti_visualizer_score,
        anti_visualizer_threshold=visual.anti_visualizer_threshold,
        anti_visualizer_passed=visual.anti_visualizer_score <= visual.anti_visualizer_threshold
        and not visual.visualizer_register,
        public_claim_allowed=state is AudioReactivityWitnessState.PASSED
        and fixture.requires_public_egress
        and fixture.programme_egress.egress_audible,
        source_refs=_dedupe([*fixture.source_refs, f"fixture:{fixture.fixture_case}"]),
        evidence_refs=evidence_refs,
        witness_refs=witness_refs,
        wcs_refs=[
            f"wcs:audio.{fixture.expected_source_role.value}",
            f"wcs:visual_response.{visual.visual_response_id}",
        ],
        variance_ledger_refs=variance_refs,
        durable_trace_ref=f"trace:audio-reactivity-runtime-witness:{fixture.fixture_case}",
        blocked_reasons=blockers,
        warnings=["runtime_witness_fixture_or_dry_run_only"],
    )


def evaluate_runtime_witness_fixture_set(
    fixtures: AudioReactivityRuntimeWitnessFixtureSet,
    *,
    cases: list[str] | None = None,
    checked_at: str | None = None,
) -> list[AudioReactivityRuntimeWitnessResult]:
    """Evaluate selected fixture cases, or every case when omitted."""

    selected = [fixtures.require_case(case) for case in cases] if cases else fixtures.fixtures
    return [evaluate_runtime_witness(fixture, checked_at=checked_at) for fixture in selected]


def result_to_wcs_record(result: AudioReactivityRuntimeWitnessResult) -> dict[str, Any]:
    """Project a witness result into a compact WCS pass/fail record."""

    return {
        "surface_id": f"audio_reactivity.{result.expected_source_role.value}",
        "status": result.state.value,
        "public_claim_allowed": result.public_claim_allowed,
        "source_role_verified": result.source_role_verified,
        "source_ids": result.selected_source_ids,
        "wcs_refs": result.wcs_refs,
        "evidence_refs": result.evidence_refs,
        "witness_refs": result.witness_refs,
        "blocking_reasons": result.blocked_reasons,
    }


def result_to_variance_ledger_record(
    result: AudioReactivityRuntimeWitnessResult,
) -> dict[str, Any]:
    """Project a witness result into a variance-ledger calibration record."""

    return {
        "visual_response_id": result.visual_response_id,
        "fixture_case": result.fixture_case,
        "state": result.state.value,
        "expected_source_role": result.expected_source_role.value,
        "selected_source_ids": result.selected_source_ids,
        "active_source_ids": result.active_source_ids,
        "anti_visualizer_score": result.anti_visualizer_score,
        "anti_visualizer_threshold": result.anti_visualizer_threshold,
        "anti_visualizer_passed": result.anti_visualizer_passed,
        "variance_ledger_refs": result.variance_ledger_refs,
    }


def write_runtime_witness_trace(
    results: list[AudioReactivityRuntimeWitnessResult],
    *,
    path: Path,
    generated_at: str | None = None,
) -> None:
    """Append durable JSONL trace records for WCS and variance-ledger audit."""

    now = generated_at or _utc_now()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for result in results:
            record = {
                "schema_version": 1,
                "trace_id": f"audio-reactivity-runtime-witness:{result.fixture_case}:{now}",
                "generated_at": now,
                "fixture_case": result.fixture_case,
                "state": result.state.value,
                "failure_class": result.failure_class.value if result.failure_class else None,
                "wcs_record": result_to_wcs_record(result),
                "variance_ledger_record": result_to_variance_ledger_record(result),
                "result": result.model_dump(mode="json"),
            }
            fh.write(json.dumps(record, sort_keys=True) + "\n")


def calibrate_runtime_anti_visualizer_threshold(
    fixtures: AudioReactivityRuntimeWitnessFixtureSet,
    *,
    out_path: Path,
) -> float:
    """Run the anti-visualizer calibration helper over fixture scores."""

    from shared.governance.scrim_invariants.anti_visualizer import (  # noqa: PLC0415
        VisualizerScore,
    )
    from shared.governance.scrim_invariants.anti_visualizer import (
        calibrate as calibrate_anti_visualizer,
    )

    negative_scores: list[VisualizerScore] = []
    positive_scores: list[VisualizerScore] = []
    for fixture in fixtures.fixtures:
        visual = fixture.visual_response
        score = VisualizerScore(
            score=visual.anti_visualizer_score,
            period_agreement=0.0,
            phase_lock=0.0,
            radial_on_beat=0.0,
            spectral_ratio=0.0,
            silence_guard=fixture.stimulus_kind is AudioReactivityStimulusKind.SILENCE,
        )
        if visual.visualizer_register:
            positive_scores.append(score)
        else:
            negative_scores.append(score)
    return calibrate_anti_visualizer(
        negative_fixtures=negative_scores,
        positive_fixtures=positive_scores,
        out_path=out_path,
    )


def read_runtime_shape_probe(
    *,
    checked_at: str | None = None,
    unified_reactivity_path: Path = DEFAULT_UNIFIED_REACTIVITY_PATH,
    audio_source_ledger_path: Path = DEFAULT_AUDIO_SOURCE_LEDGER_PATH,
    broadcast_health_path: Path = DEFAULT_BROADCAST_HEALTH_PATH,
) -> RuntimeShapeProbe:
    """Read current runtime JSON shape without certifying live audio truth."""

    now = checked_at or _utc_now()
    warnings: list[str] = []
    unified = _read_json_shape(unified_reactivity_path, warnings=warnings)
    ledger = _read_json_shape(audio_source_ledger_path, warnings=warnings)
    broadcast = _read_json_shape(broadcast_health_path, warnings=warnings)

    per_source = unified.get("per_source", {}) if isinstance(unified, dict) else {}
    source_rows = ledger.get("source_rows", []) if isinstance(ledger, dict) else []
    return RuntimeShapeProbe(
        checked_at=now,
        unified_reactivity_path=str(unified_reactivity_path),
        unified_reactivity_present=isinstance(unified, dict),
        unified_per_source_keys=sorted(per_source) if isinstance(per_source, dict) else [],
        unified_active_sources=_string_list(unified.get("active_sources", []))
        if isinstance(unified, dict)
        else [],
        audio_source_ledger_path=str(audio_source_ledger_path),
        audio_source_ledger_present=isinstance(ledger, dict),
        ledger_source_ids=[
            str(row.get("source_id"))
            for row in source_rows
            if isinstance(row, dict) and row.get("source_id") is not None
        ],
        ledger_roles=[
            str(row.get("role"))
            for row in source_rows
            if isinstance(row, dict) and row.get("role") is not None
        ],
        broadcast_health_path=str(broadcast_health_path),
        broadcast_health_present=isinstance(broadcast, dict),
        broadcast_safe=bool(broadcast.get("safe")) if isinstance(broadcast, dict) else None,
        warnings=warnings,
    )


def _failure_for_fixture(
    *,
    fixture: AudioReactivityRuntimeWitnessFixture,
    expected: RuntimeAudioLedgerRowFixture | None,
    active_programme_rows: list[RuntimeAudioLedgerRowFixture],
    source_role_verified: bool,
) -> tuple[AudioReactivityFailureClass | None, list[str]]:
    blockers: list[str] = []
    process_liveness_only = expected is not None and (
        expected.process_live or expected.activity_basis is ActivityBasis.PROCESS_ACTIVITY
    )
    if process_liveness_only and not source_role_verified:
        blockers.append("process_liveness_not_audio_evidence")
        return AudioReactivityFailureClass.FALSE_PROCESS_ACTIVITY, blockers

    if expected is not None and expected.freshness is FreshnessState.STALE:
        blockers.append("source_evidence_stale")
        return AudioReactivityFailureClass.STALE_AUDIO_EVIDENCE, blockers

    wrong_source_rows = [
        row for row in active_programme_rows if row.role is not fixture.expected_source_role
    ]
    if wrong_source_rows and not source_role_verified:
        blockers.append("active_audio_source_role_does_not_match_visual_source")
        return AudioReactivityFailureClass.WRONG_SOURCE_ROLE, blockers

    if (
        fixture.programme_egress.programme_path_active
        and fixture.programme_egress.egress_audible
        and not source_role_verified
    ):
        blockers.append("audible_programme_path_but_visual_source_silent")
        return AudioReactivityFailureClass.VISUAL_SOURCE_SILENT, blockers

    if not source_role_verified:
        blockers.append("expected_source_role_evidence_missing")
        return AudioReactivityFailureClass.LEDGER_EVIDENCE_MISSING, blockers

    if expected is not None and not expected.visual_modulation_permitted:
        blockers.append("visual_modulation_not_permitted_by_audio_ledger")
        return AudioReactivityFailureClass.LEDGER_EVIDENCE_MISSING, blockers

    if fixture.requires_public_egress and not fixture.programme_egress.egress_audible:
        blockers.append("broadcast_egress_not_public_audible")
        return AudioReactivityFailureClass.BROADCAST_EGRESS_SILENT, blockers

    visual = fixture.visual_response
    if fixture.requires_visual_response and not visual.response_present:
        blockers.append("visual_response_witness_missing")
        return AudioReactivityFailureClass.VISUAL_RESPONSE_MISSING, blockers

    if (
        visual.anti_visualizer_score > visual.anti_visualizer_threshold
        or visual.visualizer_register
    ):
        blockers.append("anti_visualizer_score_exceeds_threshold")
        return AudioReactivityFailureClass.VISUALIZER_REGISTER_EXCEEDED, blockers

    return None, blockers


def _source_role_verified(row: RuntimeAudioLedgerRowFixture | None) -> bool:
    if row is None:
        return False
    return (
        row.active
        and row.freshness is FreshnessState.FRESH
        and row.activity_basis
        in {
            ActivityBasis.MEASURED_SIGNAL,
            ActivityBasis.EXPLICIT_MARKER,
            ActivityBasis.BROADCAST_HEALTH,
        }
    )


def _read_json_shape(path: Path, *, warnings: list[str]) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        warnings.append(f"missing:{path}")
        return None
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(f"invalid:{path}:{exc}")
        return None
    if not isinstance(payload, dict):
        warnings.append(f"non_mapping:{path}")
        return None
    return payload


def _string_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value) for value in values]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _dedupe_roles(values: list[AudioSourceRole]) -> list[AudioSourceRole]:
    seen: set[AudioSourceRole] = set()
    out: list[AudioSourceRole] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _utc_now() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "AUDIO_REACTIVITY_RUNTIME_WITNESS_FIXTURES",
    "FAIL_CLOSED_POLICY",
    "REQUIRED_RUNTIME_WITNESS_FIXTURE_CASES",
    "AudioReactivityFailureClass",
    "AudioReactivityRuntimeWitnessError",
    "AudioReactivityRuntimeWitnessFixture",
    "AudioReactivityRuntimeWitnessFixtureSet",
    "AudioReactivityRuntimeWitnessResult",
    "AudioReactivityStimulusKind",
    "AudioReactivityWitnessState",
    "RuntimeShapeProbe",
    "calibrate_runtime_anti_visualizer_threshold",
    "evaluate_runtime_witness",
    "evaluate_runtime_witness_fixture_set",
    "load_audio_reactivity_runtime_witness_fixtures",
    "read_runtime_shape_probe",
    "result_to_variance_ledger_record",
    "result_to_wcs_record",
    "write_runtime_witness_trace",
]
