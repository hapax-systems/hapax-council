"""Broadcast audio safety producer.

Builds the canonical ``audio_safe_for_broadcast`` object consumed by
livestream egress, health, monetization, and public/director surfaces.
The resolver is intentionally an evidence aggregator: topology,
route-isolation, TTS forward path, loudness, egress binding, runtime
safety, and service state each remain owned by their existing tools.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shared.audio_loudness import (
    EGRESS_TARGET_LUFS_I,
    EGRESS_TRUE_PEAK_DBTP,
    TRUE_PEAK_TOLERANCE_DBTP,
)
from shared.audio_topology import TopologyDescriptor
from shared.audio_working_mode_couplings import current_audio_constraints
from shared.obs_egress_predicate import (
    EXPECTED_OBS_SOURCE,
    ObsEgressPredicateResult,
    ObsEgressState,
    classify_obs_egress,
    parse_pw_link_output,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_PATH = Path("/dev/shm/hapax-broadcast/audio-safe-for-broadcast.json")
DEFAULT_TOPOLOGY_DESCRIPTOR = REPO_ROOT / "config" / "audio-topology.yaml"
DEFAULT_AUDIO_SAFETY_STATE = Path("/dev/shm/hapax-audio-safety/state.json")
DEFAULT_AUDIO_DUCKER_STATE = Path("/dev/shm/hapax-audio-ducker/state.json")
DEFAULT_VOICE_OUTPUT_WITNESS = Path("/dev/shm/hapax-daimonion/voice-output-witness.json")
DEFAULT_EGRESS_LOOPBACK_WITNESS = Path("/dev/shm/hapax-broadcast/egress-loopback.json")

TOPOLOGY_VERIFY_COMMAND = (
    "scripts/hapax-audio-topology",
    "verify",
    "config/audio-topology.yaml",
)
L12_FORWARD_COMMAND = (
    "scripts/hapax-audio-topology",
    "l12-forward-check",
    "config/audio-topology.yaml",
)
TTS_BROADCAST_COMMAND = (
    "scripts/hapax-audio-topology",
    "tts-broadcast-check",
)
LEAK_GUARD_COMMAND = ("scripts/audio-leak-guard.sh",)
EGRESS_BINDING_COMMAND = ("pw-link", "-l")

REQUIRED_SERVICE_UNITS = (
    "pipewire.service",
    "pipewire-pulse.service",
    "wireplumber.service",
    "hapax-audio-safety.service",
    "hapax-audio-ducker.service",
)

NON_BLOCKING_PIPEWIRE_EGRESS_STATES = (
    ObsEgressState.OBS_BOUND_UNVERIFIED,
    ObsEgressState.PUBLIC_EGRESS_UNKNOWN,
    ObsEgressState.HEALTHY,
)


class BroadcastAudioStatus(StrEnum):
    SAFE = "safe"
    DEGRADED = "degraded"
    UNSAFE = "unsafe"
    UNKNOWN = "unknown"


class ReasonSeverity(StrEnum):
    BLOCKING = "blocking"
    WARNING = "warning"


class AudioHealthReason(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    severity: ReasonSeverity = ReasonSeverity.BLOCKING
    owner: str
    message: str
    evidence_refs: list[str] = Field(default_factory=list)


class BroadcastAudioHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    safe: bool
    status: BroadcastAudioStatus
    checked_at: str
    freshness_s: float
    blocking_reasons: list[AudioHealthReason] = Field(default_factory=list)
    warnings: list[AudioHealthReason] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    owners: dict[str, str] = Field(default_factory=dict)


class EgressLoopbackWitness(BaseModel):
    """Live signal-level snapshot of the broadcast egress sink.

    Written by an out-of-band sampler daemon (e.g. `pw-cat --record --target
    hapax-livestream` → DSP → atomic JSON write). The producer is out of
    scope for this consume-side gate; the producer cc-task is a follow-up.
    """

    model_config = ConfigDict(frozen=True)

    checked_at: str
    rms_dbfs: float
    peak_dbfs: float
    silence_ratio: float = Field(ge=0.0, le=1.0)
    window_seconds: float = Field(gt=0.0)
    target_sink: str = Field(min_length=1)
    error: str | None = None


class BroadcastAudioHealthEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True)

    audio_safe_for_broadcast: BroadcastAudioHealth


@dataclass(frozen=True)
class BroadcastAudioHealthPaths:
    state_path: Path = DEFAULT_STATE_PATH
    topology_descriptor: Path = DEFAULT_TOPOLOGY_DESCRIPTOR
    audio_safety_state: Path = DEFAULT_AUDIO_SAFETY_STATE
    audio_ducker_state: Path = DEFAULT_AUDIO_DUCKER_STATE
    voice_output_witness: Path = DEFAULT_VOICE_OUTPUT_WITNESS
    egress_loopback_witness: Path = DEFAULT_EGRESS_LOOPBACK_WITNESS


@dataclass(frozen=True)
class BroadcastAudioHealthThresholds:
    state_max_age_s: float = 30.0
    audio_safety_state_max_age_s: float = 10.0
    audio_ducker_state_max_age_s: float = 2.0
    voice_output_witness_max_age_s: float = 180.0
    command_timeout_s: float = 15.0
    loudness_timeout_extra_s: float = 8.0
    loudness_duration_s: int = 10
    loopback_max_age_s: float = 60.0
    silence_ratio_max: float = 0.85
    rms_dbfs_floor: float = -55.0
    # The health probe samples only a short live window. Use a 10 s window
    # and a safety band wide enough to avoid failing closed on normal
    # programme/source variance; exact loudness quality belongs to longer-
    # window mix scoring.
    loudness_tolerance_lu: float = 2.0
    # Working-mode override: when fortress sets a tighter true-peak
    # ceiling we honor it directly instead of widening with the
    # nominal +TRUE_PEAK_TOLERANCE_DBTP cushion.
    true_peak_dbtp_override: float | None = None
    # Working-mode override: research mode can short-circuit the
    # 5 s LUFS measurement (no broadcast intent → no signal).
    skip_lufs_egress_check: bool = False

    @property
    def loudness_min_lufs_i(self) -> float:
        return EGRESS_TARGET_LUFS_I - self.loudness_tolerance_lu

    @property
    def loudness_max_lufs_i(self) -> float:
        return EGRESS_TARGET_LUFS_I + self.loudness_tolerance_lu

    @property
    def true_peak_max_dbtp(self) -> float:
        if self.true_peak_dbtp_override is not None:
            return self.true_peak_dbtp_override
        return EGRESS_TRUE_PEAK_DBTP + TRUE_PEAK_TOLERANCE_DBTP


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class ServiceStatus:
    unit: str
    active_state: str
    sub_state: str = ""
    n_restarts: int | None = None
    load_state: str = "loaded"


CommandRunner = Callable[[Sequence[str], float], CommandResult]
ServiceStatusProbe = Callable[[str], ServiceStatus | None]


def resolve_broadcast_audio_health(
    *,
    paths: BroadcastAudioHealthPaths | None = None,
    thresholds: BroadcastAudioHealthThresholds | None = None,
    now: float | None = None,
    command_runner: CommandRunner | None = None,
    service_status_probe: ServiceStatusProbe | None = None,
    constraints: dict[str, object] | None = None,
) -> BroadcastAudioHealth:
    """Resolve live broadcast audio safety from existing authorities.

    ``constraints`` is the working-mode coupling dict from
    :func:`shared.audio_working_mode_couplings.current_audio_constraints`.
    Defaults to a live read so consumers do not have to thread the
    mode through their call sites; tests override it for isolation.
    """

    p = paths or BroadcastAudioHealthPaths()
    base_thresholds = thresholds or BroadcastAudioHealthThresholds()
    active_constraints = constraints if constraints is not None else current_audio_constraints()
    t = _apply_constraints(base_thresholds, active_constraints)
    current = now if now is not None else time.time()
    runner = command_runner or _run_command
    service_probe = service_status_probe or _systemd_service_status

    evidence: dict[str, Any] = {}
    blocking: list[AudioHealthReason] = []
    warnings: list[AudioHealthReason] = []
    if active_constraints:
        evidence["working_mode_constraints"] = dict(active_constraints)

    descriptor_ok = _evaluate_topology_descriptor(
        p.topology_descriptor,
        evidence,
        blocking,
    )
    if descriptor_ok:
        _evaluate_command(
            key="topology",
            command=TOPOLOGY_VERIFY_COMMAND,
            owner="scripts/hapax-audio-topology verify",
            failure_code="topology_unclassified_drift",
            failure_message="live PipeWire graph has unclassified topology drift",
            evidence=evidence,
            blocking=blocking,
            runner=runner,
            timeout_s=t.command_timeout_s,
            success_updates={"descriptor": _repo_relative(p.topology_descriptor)},
        )

    _evaluate_command(
        key="private_routes",
        command=LEAK_GUARD_COMMAND,
        owner="scripts/audio-leak-guard.sh",
        failure_code="private_route_leak_guard_failed",
        failure_message="assistant/private/notification route may reach broadcast",
        evidence=evidence,
        blocking=blocking,
        runner=runner,
        timeout_s=t.command_timeout_s,
    )

    _evaluate_command(
        key="l12_forward_invariant",
        command=L12_FORWARD_COMMAND,
        owner="scripts/hapax-audio-topology l12-forward-check",
        failure_code="broadcast_forward_invariant_failed",
        failure_message="static L-12/broadcast directionality invariant failed",
        evidence=evidence,
        blocking=blocking,
        runner=runner,
        timeout_s=t.command_timeout_s,
    )

    _evaluate_command(
        key="broadcast_forward",
        command=TTS_BROADCAST_COMMAND,
        owner="scripts/hapax-audio-topology tts-broadcast-check",
        failure_code="tts_broadcast_path_failed",
        failure_message="TTS broadcast path does not reach the livestream tap",
        evidence=evidence,
        blocking=blocking,
        runner=runner,
        timeout_s=t.command_timeout_s,
    )

    if t.skip_lufs_egress_check:
        evidence["loudness"] = {
            "stage": "hapax-broadcast-normalized",
            "skipped_by_working_mode": True,
            "reason": "lufs_egress_check_skipped",
        }
    else:
        _evaluate_loudness(
            evidence=evidence,
            blocking=blocking,
            warnings=warnings,
            runner=runner,
            thresholds=t,
        )
    _evaluate_egress_binding(evidence=evidence, blocking=blocking, runner=runner, thresholds=t)
    _evaluate_egress_loopback(
        p.egress_loopback_witness,
        current,
        t,
        evidence=evidence,
        blocking=blocking,
        warnings=warnings,
    )
    _evaluate_health_predicate_drift(evidence=evidence, blocking=blocking)
    _evaluate_voice_output_witness(
        p.voice_output_witness,
        current,
        t,
        evidence=evidence,
        blocking=blocking,
    )
    _evaluate_runtime_safety(
        p.audio_safety_state,
        current,
        t,
        evidence=evidence,
        blocking=blocking,
    )
    _evaluate_audio_ducker_state(
        p.audio_ducker_state,
        current,
        t,
        evidence=evidence,
        blocking=blocking,
    )
    _evaluate_service_freshness(
        evidence=evidence,
        blocking=blocking,
        service_status_probe=service_probe,
    )

    # Demote loudness_out_of_band to warning when ducker is also failing —
    # the ducker failure is the root cause; loudness is a downstream symptom.
    ducker_blocking = any(r.code.startswith("audio_ducker_") for r in blocking)
    if ducker_blocking:
        demoted = [r for r in blocking if r.code == "loudness_out_of_band"]
        if demoted:
            blocking = [r for r in blocking if r.code != "loudness_out_of_band"]
            warnings.extend(demoted)

    safe = not blocking
    status = _status_for(safe=safe, blocking=blocking, warnings=warnings)
    return BroadcastAudioHealth(
        safe=safe,
        status=status,
        checked_at=_iso_from_epoch(current),
        freshness_s=0.0,
        blocking_reasons=blocking,
        warnings=warnings,
        evidence=evidence,
        owners=_owners(),
    )


def read_broadcast_audio_health_state(
    path: Path = DEFAULT_STATE_PATH,
    *,
    now: float | None = None,
    max_age_s: float = 30.0,
) -> BroadcastAudioHealth:
    """Read a published health state, failing closed on missing/stale/bad data."""

    current = now if now is not None else time.time()
    age = _path_age_s(path, current)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _unknown_state(
            code="audio_safe_for_broadcast_missing",
            owner=str(path),
            message="audio_safe_for_broadcast state file is missing",
            freshness_s=age,
            evidence={"state_file": {"path": str(path), "read": "missing", "age_s": age}},
            checked_at=_iso_from_epoch(current),
        )
    except json.JSONDecodeError as exc:
        return _unknown_state(
            code="audio_safe_for_broadcast_malformed",
            owner=str(path),
            message=f"audio_safe_for_broadcast state file is malformed: {exc}",
            freshness_s=age,
            evidence={"state_file": {"path": str(path), "read": "malformed", "age_s": age}},
            checked_at=_iso_from_epoch(current),
        )
    except OSError as exc:
        return _unknown_state(
            code="audio_safe_for_broadcast_unreadable",
            owner=str(path),
            message=f"audio_safe_for_broadcast state file is unreadable: {exc}",
            freshness_s=age,
            evidence={"state_file": {"path": str(path), "read": "error", "age_s": age}},
            checked_at=_iso_from_epoch(current),
        )

    payload = raw.get("audio_safe_for_broadcast") if isinstance(raw, dict) else None
    if payload is None and isinstance(raw, dict):
        payload = raw
    try:
        state = BroadcastAudioHealth.model_validate(payload)
    except ValidationError as exc:
        return _unknown_state(
            code="audio_safe_for_broadcast_schema_invalid",
            owner=str(path),
            message=f"audio_safe_for_broadcast payload failed schema validation: {exc}",
            freshness_s=age,
            evidence={"state_file": {"path": str(path), "read": "schema_invalid", "age_s": age}},
            checked_at=_iso_from_epoch(current),
        )

    freshness_s = round(age, 3) if age is not None else None
    if freshness_s is None or freshness_s > max_age_s:
        stale_reason = AudioHealthReason(
            code="audio_safe_for_broadcast_stale",
            owner=str(path),
            message=(f"audio_safe_for_broadcast state is stale ({freshness_s}s > {max_age_s}s)"),
            evidence_refs=["state_file"],
        )
        evidence = {
            **state.evidence,
            "state_file": {
                "path": str(path),
                "read": "stale",
                "age_s": freshness_s,
                "max_age_s": max_age_s,
            },
        }
        return state.model_copy(
            update={
                "safe": False,
                "status": BroadcastAudioStatus.UNKNOWN,
                "freshness_s": freshness_s or 0.0,
                "blocking_reasons": [*state.blocking_reasons, stale_reason],
                "evidence": evidence,
            }
        )

    return state.model_copy(update={"freshness_s": freshness_s})


def write_broadcast_audio_health_state(
    health: BroadcastAudioHealth,
    path: Path = DEFAULT_STATE_PATH,
) -> None:
    """Atomically publish the health state envelope."""

    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = BroadcastAudioHealthEnvelope(audio_safe_for_broadcast=health)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(
        json.dumps(envelope.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _apply_constraints(
    thresholds: BroadcastAudioHealthThresholds,
    constraints: dict[str, object],
) -> BroadcastAudioHealthThresholds:
    """Override threshold fields from a working-mode constraint dict.

    Only fields explicitly listed by the coupling layer are merged in;
    unknown keys are ignored so the coupling module can grow without
    breaking older threshold dataclasses.
    """
    if not constraints:
        return thresholds
    overrides: dict[str, Any] = {}
    true_peak = constraints.get("broadcast_true_peak_dbtp")
    if isinstance(true_peak, int | float):
        overrides["true_peak_dbtp_override"] = float(true_peak)
    if bool(constraints.get("lufs_egress_check_skipped", False)):
        overrides["skip_lufs_egress_check"] = True
    if not overrides:
        return thresholds
    from dataclasses import replace as _replace

    return _replace(thresholds, **overrides)


def _evaluate_topology_descriptor(
    path: Path,
    evidence: dict[str, Any],
    blocking: list[AudioHealthReason],
) -> bool:
    evidence["topology"] = {
        "descriptor": _repo_relative(path),
        "verification": "unknown",
        "unclassified_drift": None,
        "command": " ".join(TOPOLOGY_VERIFY_COMMAND),
    }
    try:
        TopologyDescriptor.from_yaml(path)
    except FileNotFoundError:
        _block(
            blocking,
            code="topology_descriptor_missing",
            owner=_repo_relative(path),
            message="audio topology descriptor is missing",
            evidence_refs=["topology"],
        )
        evidence["topology"]["verification"] = "fail"
        evidence["topology"]["error"] = "missing"
        return False
    except Exception as exc:
        _block(
            blocking,
            code="topology_descriptor_malformed",
            owner=_repo_relative(path),
            message=f"audio topology descriptor failed to parse: {exc}",
            evidence_refs=["topology"],
        )
        evidence["topology"]["verification"] = "fail"
        evidence["topology"]["error"] = str(exc)
        return False
    return True


def _evaluate_command(
    *,
    key: str,
    command: Sequence[str],
    owner: str,
    failure_code: str,
    failure_message: str,
    evidence: dict[str, Any],
    blocking: list[AudioHealthReason],
    runner: CommandRunner,
    timeout_s: float,
    success_updates: dict[str, Any] | None = None,
) -> CommandResult:
    result = runner(command, timeout_s)
    passed = result.returncode == 0
    record = {
        "status": "pass" if passed else "fail",
        "command": " ".join(command),
        "returncode": result.returncode,
        "stdout": _tail(result.stdout),
        "stderr": _tail(result.stderr),
    }
    if success_updates:
        record.update(success_updates)
    evidence[key] = {**evidence.get(key, {}), **record}
    if not passed:
        _block(
            blocking,
            code=failure_code,
            owner=owner,
            message=failure_message,
            evidence_refs=[key],
        )
        if key == "topology":
            evidence[key]["unclassified_drift"] = result.returncode == 2
    elif key == "topology":
        evidence[key]["verification"] = "pass"
        evidence[key]["unclassified_drift"] = False
    return result


def _evaluate_loudness(
    *,
    evidence: dict[str, Any],
    blocking: list[AudioHealthReason],
    warnings: list[AudioHealthReason],
    runner: CommandRunner,
    thresholds: BroadcastAudioHealthThresholds,
) -> None:
    duration = thresholds.loudness_duration_s
    command = (
        "scripts/audio-measure.sh",
        str(duration),
        "hapax-broadcast-normalized",
    )
    timeout = duration + thresholds.loudness_timeout_extra_s
    result = runner(command, timeout)
    parsed = _parse_loudness_output(result.stdout + "\n" + result.stderr)
    integrated = parsed.get("integrated_lufs_i")
    true_peak = parsed.get("true_peak_dbtp")
    lufs_ok = (
        integrated is not None
        and thresholds.loudness_min_lufs_i <= integrated <= thresholds.loudness_max_lufs_i
    )
    true_peak_ok = true_peak is not None and true_peak <= thresholds.true_peak_max_dbtp
    evidence["loudness"] = {
        "stage": "hapax-broadcast-normalized",
        "integrated_lufs_i": integrated,
        "target_lufs_i": EGRESS_TARGET_LUFS_I,
        "target_min_lufs_i": thresholds.loudness_min_lufs_i,
        "target_max_lufs_i": thresholds.loudness_max_lufs_i,
        "true_peak_dbtp": true_peak,
        "target_true_peak_dbtp": EGRESS_TRUE_PEAK_DBTP,
        "true_peak_max_dbtp": thresholds.true_peak_max_dbtp,
        "within_target_band": lufs_ok,
        "true_peak_within_ceiling": true_peak_ok,
        "measurement_age_s": 0.0 if result.returncode == 0 else None,
        "command": " ".join(command),
        "returncode": result.returncode,
        "stdout": _tail(result.stdout),
        "stderr": _tail(result.stderr),
    }
    _emit_lufs_gauge(integrated, true_peak=true_peak)
    if result.returncode != 0:
        _block(
            blocking,
            code="loudness_measurement_failed",
            owner="scripts/audio-measure.sh",
            message="broadcast loudness measurement command failed",
            evidence_refs=["loudness"],
        )
        return
    if integrated is None or true_peak is None:
        _block(
            blocking,
            code="loudness_measurement_malformed",
            owner="scripts/audio-measure.sh",
            message="broadcast loudness measurement did not include LUFS-I and true peak",
            evidence_refs=["loudness"],
        )
        return
    if not lufs_ok:
        # Distinguish egress silence (no signal present) from genuine
        # miscalibration. Silence (-50 LUFS or below) is the normal state
        # before/between autonomous speech events; blocking on it creates
        # a circular dependency where voice can't flow because the gate
        # requires voice to already be flowing at the right level. Under-target
        # programme loudness is a quality/degradation finding; over-target
        # programme loudness is a safety finding because it can fatigue or
        # clip downstream listeners.
        SILENCE_FLOOR_LUFS = -50.0
        if integrated is not None and integrated < SILENCE_FLOOR_LUFS:
            evidence["loudness"]["egress_silent"] = True
            evidence["loudness"]["silence_floor_lufs"] = SILENCE_FLOOR_LUFS
        elif integrated < thresholds.loudness_min_lufs_i:
            warnings.append(
                AudioHealthReason(
                    code="loudness_under_target",
                    severity=ReasonSeverity.WARNING,
                    owner="shared/audio_loudness.py",
                    message=(
                        f"broadcast loudness {integrated} LUFS-I is below "
                        f"{thresholds.loudness_min_lufs_i} LUFS-I quality floor"
                    ),
                    evidence_refs=["loudness"],
                )
            )
        else:
            _block(
                blocking,
                code="loudness_out_of_band",
                owner="shared/audio_loudness.py",
                message=(
                    f"broadcast loudness {integrated} LUFS-I is outside "
                    f"{thresholds.loudness_min_lufs_i}..{thresholds.loudness_max_lufs_i}"
                ),
                evidence_refs=["loudness"],
            )
    if not true_peak_ok:
        _block(
            blocking,
            code="true_peak_over_ceiling",
            owner="shared/audio_loudness.py",
            message=(
                f"broadcast true peak {true_peak} dBTP exceeds "
                f"{thresholds.true_peak_max_dbtp} dBTP ceiling"
            ),
            evidence_refs=["loudness"],
        )


def _evaluate_egress_binding(
    *,
    evidence: dict[str, Any],
    blocking: list[AudioHealthReason],
    runner: CommandRunner,
    thresholds: BroadcastAudioHealthThresholds,
) -> None:
    result = runner(EGRESS_BINDING_COMMAND, thresholds.command_timeout_s)
    if result.returncode == 0:
        predicate = classify_obs_egress(pipewire=parse_pw_link_output(result.stdout))
    else:
        predicate = classify_obs_egress(
            pipewire=parse_pw_link_output(
                None,
                error=_tail(result.stderr) or f"pw-link exited {result.returncode}",
            )
        )
    observed_source = _observed_obs_source(predicate)
    obs_present = _predicate_observed_bool(predicate, "obs_present")
    bound = predicate.state in NON_BLOCKING_PIPEWIRE_EGRESS_STATES
    evidence["egress_binding"] = {
        "expected_source": EXPECTED_OBS_SOURCE,
        "bound": bound if result.returncode == 0 else False,
        "verified": predicate.safe,
        "state": predicate.state.value,
        "health_impact": predicate.health_impact.value,
        "reason_codes": list(predicate.reason_codes),
        "remediation_allowed": predicate.remediation_allowed,
        "observed_source": observed_source if result.returncode == 0 else None,
        "obs_present": obs_present if result.returncode == 0 else None,
        "predicate_evidence": [record.model_dump(mode="json") for record in predicate.evidence],
        "command": " ".join(EGRESS_BINDING_COMMAND),
        "returncode": result.returncode,
        "stdout": _tail(result.stdout),
        "stderr": _tail(result.stderr),
    }
    if result.returncode != 0:
        _block(
            blocking,
            code="egress_binding_unknown",
            owner="shared/obs_egress_predicate.py + pw-link -l",
            message="egress audio binding could not be inspected",
            evidence_refs=["egress_binding"],
        )
    elif predicate.state not in NON_BLOCKING_PIPEWIRE_EGRESS_STATES:
        _block(
            blocking,
            code="egress_binding_missing",
            owner="shared/obs_egress_predicate.py + pw-link -l",
            message=(
                "public egress state "
                f"{predicate.state.value} is not exactly bound to {EXPECTED_OBS_SOURCE}"
            ),
            evidence_refs=["egress_binding"],
        )


def _evaluate_egress_loopback(
    path: Path,
    now: float,
    thresholds: BroadcastAudioHealthThresholds,
    *,
    evidence: dict[str, Any],
    blocking: list[AudioHealthReason],
    warnings: list[AudioHealthReason],
) -> None:
    data, age_s, error = _read_json_file(path, now)
    record: dict[str, Any] = {
        "egress_loopback_path": str(path),
        "egress_loopback_age_s": age_s,
    }
    if error is not None:
        record["status"] = "unknown"
        record["error"] = error
        evidence["egress_loopback"] = record
        _block(
            blocking,
            code=f"egress_loopback_{error}",
            owner=str(path),
            message=f"egress loopback witness is {error}",
            evidence_refs=["egress_loopback"],
        )
        return
    if age_s is None or age_s > thresholds.loopback_max_age_s:
        record["status"] = "stale"
        evidence["egress_loopback"] = record
        _block(
            blocking,
            code="egress_loopback_stale",
            owner=str(path),
            message=(
                f"egress loopback witness is stale ({age_s}s > {thresholds.loopback_max_age_s}s)"
            ),
            evidence_refs=["egress_loopback"],
        )
        return

    try:
        witness = EgressLoopbackWitness.model_validate(data)
    except ValidationError as exc:
        record["status"] = "malformed"
        record["error"] = str(exc)
        evidence["egress_loopback"] = record
        _block(
            blocking,
            code="egress_loopback_schema_invalid",
            owner=str(path),
            message=f"egress loopback witness failed schema validation: {exc}",
            evidence_refs=["egress_loopback"],
        )
        return

    record.update(
        {
            "status": "live",
            "rms_dbfs": witness.rms_dbfs,
            "peak_dbfs": witness.peak_dbfs,
            "silence_ratio": witness.silence_ratio,
            "window_seconds": witness.window_seconds,
            "target_sink": witness.target_sink,
            "checked_at": witness.checked_at,
            "max_age_s": thresholds.loopback_max_age_s,
        }
    )
    if witness.error:
        record["producer_error"] = witness.error
        record["obs_egress_state"] = ObsEgressState.ANALYZER_INTERNAL_FAILURE.value
    evidence["egress_loopback"] = record

    if witness.error:
        _block(
            blocking,
            code="egress_loopback_producer_failed",
            owner=str(path),
            message=f"egress loopback producer reported error: {witness.error}",
            evidence_refs=["egress_loopback"],
        )
        return

    if witness.silence_ratio > thresholds.silence_ratio_max:
        _block(
            blocking,
            code="egress_loopback_silent",
            owner=str(path),
            message=(
                "egress loopback silence ratio "
                f"{witness.silence_ratio:.2f} > {thresholds.silence_ratio_max:.2f} "
                f"(target_sink={witness.target_sink})"
            ),
            evidence_refs=["egress_loopback"],
        )
        return

    if witness.rms_dbfs < thresholds.rms_dbfs_floor:
        warnings.append(
            AudioHealthReason(
                code="egress_loopback_low_signal",
                severity=ReasonSeverity.WARNING,
                owner=str(path),
                message=(
                    "egress loopback rms below floor "
                    f"({witness.rms_dbfs:.1f} dBFS < {thresholds.rms_dbfs_floor:.1f} dBFS)"
                ),
                evidence_refs=["egress_loopback"],
            )
        )


def _evaluate_health_predicate_drift(
    *,
    evidence: dict[str, Any],
    blocking: list[AudioHealthReason],
) -> None:
    loudness = evidence.get("loudness")
    loopback = evidence.get("egress_loopback")
    if not isinstance(loudness, dict) or not isinstance(loopback, dict):
        return
    if loudness.get("egress_silent") is not True:
        return
    if loopback.get("status") != "live":
        return
    if loopback.get("producer_error"):
        return

    evidence["health_predicate_drift"] = {
        "state": ObsEgressState.HEALTH_PREDICATE_DRIFT.value,
        "loudness_stage": loudness.get("stage"),
        "loudness_integrated_lufs_i": loudness.get("integrated_lufs_i"),
        "loudness_measurement_age_s": loudness.get("measurement_age_s"),
        "egress_loopback_checked_at": loopback.get("checked_at"),
        "egress_loopback_max_age_s": loopback.get("max_age_s"),
        "egress_loopback_rms_dbfs": loopback.get("rms_dbfs"),
        "egress_loopback_silence_ratio": loopback.get("silence_ratio"),
    }
    _block(
        blocking,
        code="health_predicate_drift",
        owner="shared/broadcast_audio_health.py",
        message="loudness and egress loopback evidence disagree about public audio",
        evidence_refs=["loudness", "egress_loopback", "health_predicate_drift"],
    )


def _evaluate_runtime_safety(
    path: Path,
    now: float,
    thresholds: BroadcastAudioHealthThresholds,
    *,
    evidence: dict[str, Any],
    blocking: list[AudioHealthReason],
) -> None:
    data, age_s, error = _read_json_file(path, now)
    record: dict[str, Any] = {
        "audio_safety_state_path": str(path),
        "audio_safety_state_age_s": age_s,
        "vinyl_pet_detector": "unknown",
        "audio_safety_service": "checked_by_service_freshness",
    }
    if error is not None:
        record["status"] = "unknown"
        record["error"] = error
        evidence["runtime_safety"] = record
        _block(
            blocking,
            code=f"runtime_safety_state_{error}",
            owner=str(path),
            message=f"audio runtime safety state is {error}",
            evidence_refs=["runtime_safety"],
        )
        return
    if age_s is None or age_s > thresholds.audio_safety_state_max_age_s:
        record["status"] = "stale"
        evidence["runtime_safety"] = record
        _block(
            blocking,
            code="runtime_safety_state_stale",
            owner=str(path),
            message=(
                "audio runtime safety state is stale "
                f"({age_s}s > {thresholds.audio_safety_state_max_age_s}s)"
            ),
            evidence_refs=["runtime_safety"],
        )
        return

    status = str(data.get("status", "unknown"))
    breach_active = bool(data.get("breach_active", False))
    detector = "breach" if breach_active else status
    record.update(
        {
            "status": status,
            "vinyl_pet_detector": detector,
            "breach_active": breach_active,
            "last_breach_at": data.get("last_breach_at"),
        }
    )
    evidence["runtime_safety"] = record
    if breach_active or status != "clear":
        _block(
            blocking,
            code="runtime_safety_failed",
            owner=str(path),
            message=f"audio runtime safety detector status is {detector}",
            evidence_refs=["runtime_safety"],
        )


def _evaluate_audio_ducker_state(
    path: Path,
    now: float,
    thresholds: BroadcastAudioHealthThresholds,
    *,
    evidence: dict[str, Any],
    blocking: list[AudioHealthReason],
) -> None:
    data, age_s, error = _read_json_file(path, now)
    record: dict[str, Any] = {
        "audio_ducker_state_path": str(path),
        "audio_ducker_state_age_s": age_s,
        "status": "unknown",
    }
    if error is not None:
        record["error"] = error
        evidence["audio_ducker"] = record
        _block(
            blocking,
            code=f"audio_ducker_state_{error}",
            owner=str(path),
            message=f"audio ducker state is {error}",
            evidence_refs=["audio_ducker"],
        )
        return
    if age_s is None or age_s > thresholds.audio_ducker_state_max_age_s:
        record["status"] = "stale"
        evidence["audio_ducker"] = record
        _block(
            blocking,
            code="audio_ducker_state_stale",
            owner=str(path),
            message=(
                "audio ducker state is stale "
                f"({age_s}s > {thresholds.audio_ducker_state_max_age_s}s)"
            ),
            evidence_refs=["audio_ducker"],
        )
        return

    blockers_raw = data.get("blockers", [])
    blockers = [str(item) for item in blockers_raw] if isinstance(blockers_raw, list) else []
    malformed_blockers = (
        [] if isinstance(blockers_raw, list) else ["audio_ducker_blockers_malformed"]
    )
    all_blockers = [*blockers, *malformed_blockers]
    music_duck_state = data.get("music_duck") if isinstance(data.get("music_duck"), dict) else {}
    tts_duck_state = data.get("tts_duck") if isinstance(data.get("tts_duck"), dict) else {}
    commanded_music = _number_or_none(
        data.get("commanded_music_duck_gain") or music_duck_state.get("commanded_gain")
    )
    actual_music = _number_or_none(
        data.get("actual_music_duck_gain") or music_duck_state.get("actual_gain")
    )
    commanded_tts = _number_or_none(
        data.get("commanded_tts_duck_gain") or tts_duck_state.get("commanded_gain")
    )
    actual_tts = _number_or_none(
        data.get("actual_tts_duck_gain") or tts_duck_state.get("actual_gain")
    )
    idle_retired_readback = (
        data.get("trigger_cause") in (None, "none")
        and commanded_music == 1.0
        and commanded_tts == 1.0
    )
    non_blocking_readback_blockers = [
        blocker
        for blocker in all_blockers
        if idle_retired_readback
        and blocker.startswith(("music_readback_error:", "tts_readback_error:"))
        and "not present in PipeWire Props" in blocker
    ]
    effective_blockers = [
        blocker for blocker in all_blockers if blocker not in non_blocking_readback_blockers
    ]
    raw_fail_open = bool(data.get("fail_open", False))
    raw_fail_open_is_readback_only = (
        raw_fail_open
        and idle_retired_readback
        and bool(non_blocking_readback_blockers)
        and not effective_blockers
    )
    fail_open = (raw_fail_open and not raw_fail_open_is_readback_only) or bool(effective_blockers)
    record.update(
        {
            "status": "fail_open" if fail_open else "ok",
            "trigger_cause": data.get("trigger_cause"),
            "fail_open": fail_open,
            "raw_fail_open": raw_fail_open,
            "blockers": all_blockers,
            "non_blocking_readback_blockers": non_blocking_readback_blockers,
            "commanded_music_duck_gain": commanded_music,
            "actual_music_duck_gain": actual_music,
            "commanded_tts_duck_gain": commanded_tts,
            "actual_tts_duck_gain": actual_tts,
            "music_duck": data.get("music_duck")
            if isinstance(data.get("music_duck"), dict)
            else {},
            "tts_duck": data.get("tts_duck") if isinstance(data.get("tts_duck"), dict) else {},
            "rode": data.get("rode") if isinstance(data.get("rode"), dict) else {},
            "tts": data.get("tts") if isinstance(data.get("tts"), dict) else {},
        }
    )
    evidence["audio_ducker"] = record

    if effective_blockers:
        _block(
            blocking,
            code="audio_ducker_fail_open",
            owner=str(path),
            message=(
                f"audio ducker reports fail-open blockers: {', '.join(effective_blockers[:3])}"
            ),
            evidence_refs=["audio_ducker"],
        )
    elif raw_fail_open and not raw_fail_open_is_readback_only:
        _block(
            blocking,
            code="audio_ducker_fail_open",
            owner=str(path),
            message="audio ducker reports fail-open state",
            evidence_refs=["audio_ducker"],
        )

    for label, commanded, actual in (
        ("music", commanded_music, actual_music),
        ("tts", commanded_tts, actual_tts),
    ):
        duck_state = record.get(f"{label}_duck")
        readback_error = (
            duck_state.get("last_readback_error") if isinstance(duck_state, dict) else None
        )
        idle_passthrough = (
            not fail_open
            and commanded == 1.0
            and data.get("trigger_cause") in (None, "none")
            and isinstance(readback_error, str)
            and "not present in PipeWire Props" in readback_error
        )
        if commanded is None or actual is None:
            if idle_passthrough:
                record.setdefault("readback_non_blocking", {})[label] = (
                    "idle passthrough; retired or absent duck node has no active gain command"
                )
                continue
            _block(
                blocking,
                code=f"audio_ducker_{label}_readback_missing",
                owner=str(path),
                message=f"audio ducker {label} commanded/actual gain evidence is missing",
                evidence_refs=["audio_ducker"],
            )
        elif abs(commanded - actual) > 0.025:
            _block(
                blocking,
                code=f"audio_ducker_{label}_readback_mismatch",
                owner=str(path),
                message=(
                    f"audio ducker {label} commanded gain {commanded} "
                    f"does not match actual gain {actual}"
                ),
                evidence_refs=["audio_ducker"],
            )


def _evaluate_voice_output_witness(
    path: Path,
    now: float,
    thresholds: BroadcastAudioHealthThresholds,
    *,
    evidence: dict[str, Any],
    blocking: list[AudioHealthReason],
) -> None:
    data, age_s, error = _read_json_file(path, now)
    record: dict[str, Any] = {
        "witness_path": str(path),
        "age_s": round(age_s, 3) if age_s is not None else None,
        "status": "unknown",
        "route_present": False,
        "playback_present": False,
        "egress_audible": None,
        "silent_failure": False,
    }
    if error is not None:
        record["status"] = error
        evidence["voice_output_witness"] = record
        if error == "missing":
            return
        _block(
            blocking,
            code=f"voice_output_witness_{error}",
            owner=str(path),
            message=f"voice output witness is {error}",
            evidence_refs=["voice_output_witness"],
        )
        return

    if age_s is None or age_s > thresholds.voice_output_witness_max_age_s:
        record["status"] = "stale"
        evidence["voice_output_witness"] = record
        _block(
            blocking,
            code="voice_output_witness_stale",
            owner=str(path),
            message=(
                "voice output witness is stale "
                f"({age_s}s > {thresholds.voice_output_witness_max_age_s}s)"
            ),
            evidence_refs=["voice_output_witness"],
        )
        return

    status = str(data.get("status", "unknown"))
    route = data.get("downstream_route_status") if isinstance(data, dict) else {}
    playback = data.get("last_playback") if isinstance(data, dict) else {}
    last_successful_playback = (
        data.get("last_successful_playback") if isinstance(data, dict) else {}
    )
    last_failed_playback = data.get("last_failed_playback") if isinstance(data, dict) else {}
    last_drop = data.get("last_drop") if isinstance(data, dict) else {}
    egress = data.get("broadcast_egress_activity") if isinstance(data, dict) else {}
    route_present = bool(isinstance(route, dict) and route.get("route_present"))
    playback_present = bool(isinstance(playback, dict) and playback.get("completed")) or bool(
        isinstance(last_successful_playback, dict) and last_successful_playback.get("completed")
    )
    egress_audible = egress.get("egress_audible") if isinstance(egress, dict) else None
    silent_failure = status in {"playback_failed", "drop_recorded", "synthesis_failed"}
    record.update(
        {
            "status": status,
            "updated_at": data.get("updated_at"),
            "route_present": route_present,
            "playback_present": playback_present,
            "egress_audible": egress_audible,
            "silent_failure": silent_failure,
            "blocker_drop_reason": data.get("blocker_drop_reason"),
            "last_drop": last_drop if isinstance(last_drop, dict) else {},
            "last_failed_playback": last_failed_playback
            if isinstance(last_failed_playback, dict)
            else {},
            "last_successful_playback": last_successful_playback
            if isinstance(last_successful_playback, dict)
            else {},
            "target": route.get("target") if isinstance(route, dict) else None,
            "media_role": route.get("media_role") if isinstance(route, dict) else None,
            "planned_utterance": data.get("planned_utterance"),
            "pcm_duration_s": playback.get("pcm_duration_s")
            if isinstance(playback, dict)
            else None,
        }
    )
    evidence["voice_output_witness"] = record
    if silent_failure:
        # Break self-referential circular dependency: if the witness
        # records drops whose blocker_drop_reason is
        # "audio_safe_for_broadcast_false", those drops were caused by
        # THIS gate being closed.  Using them as evidence to keep the
        # gate closed creates an infinite loop.  Only block on
        # genuinely independent failure signals.
        drop_reason = data.get("blocker_drop_reason") if isinstance(data, dict) else None
        _NON_BLOCKING_DROP_REASONS = (
            "audio_safe_for_broadcast_false",
            "broadcast_intent_missing",
        )
        if drop_reason in _NON_BLOCKING_DROP_REASONS:
            record["self_referential_drop"] = True
        else:
            _block(
                blocking,
                code="voice_output_silent_failure",
                owner=str(path),
                message=f"voice output witness reports {status}",
                evidence_refs=["voice_output_witness"],
            )


def _evaluate_service_freshness(
    *,
    evidence: dict[str, Any],
    blocking: list[AudioHealthReason],
    service_status_probe: ServiceStatusProbe,
) -> None:
    services: dict[str, Any] = {}
    for unit in REQUIRED_SERVICE_UNITS:
        status = service_status_probe(unit)
        if status is None:
            services[unit] = {"active_state": "unknown"}
            _block(
                blocking,
                code="service_status_unknown",
                owner=unit,
                message=f"{unit} status could not be inspected",
                evidence_refs=["service_freshness"],
            )
            continue
        services[unit] = {
            "active_state": status.active_state,
            "sub_state": status.sub_state,
            "n_restarts": status.n_restarts,
            "load_state": status.load_state,
        }
        if status.active_state != "active":
            _block(
                blocking,
                code="service_failed",
                owner=unit,
                message=f"{unit} is {status.active_state}/{status.sub_state or 'unknown'}",
                evidence_refs=["service_freshness"],
            )
    evidence["service_freshness"] = {
        "required_units": list(REQUIRED_SERVICE_UNITS),
        "services": services,
    }


def _run_command(command: Sequence[str], timeout_s: float) -> CommandResult:
    try:
        result = subprocess.run(
            list(command),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError as exc:
        return CommandResult(returncode=127, stderr=str(exc))
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            returncode=124,
            stdout=exc.stdout if isinstance(exc.stdout, str) else "",
            stderr=exc.stderr if isinstance(exc.stderr, str) else f"timed out after {timeout_s}s",
        )
    return CommandResult(result.returncode, result.stdout, result.stderr)


def _systemd_service_status(unit: str) -> ServiceStatus | None:
    command = (
        "systemctl",
        "--user",
        "show",
        unit,
        "--property=ActiveState",
        "--property=SubState",
        "--property=NRestarts",
        "--property=LoadState",
        "--no-pager",
    )
    result = _run_command(command, 4.0)
    if result.returncode != 0:
        return None
    fields: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        fields[key] = value
    n_restarts = _int_or_none(fields.get("NRestarts"))
    return ServiceStatus(
        unit=unit,
        active_state=fields.get("ActiveState", "unknown"),
        sub_state=fields.get("SubState", ""),
        n_restarts=n_restarts,
        load_state=fields.get("LoadState", "unknown"),
    )


def _parse_loudness_output(text: str) -> dict[str, float | None]:
    integrated = _labeled_float(text, "I")
    true_peak = _labeled_float(text, "Peak")
    return {
        "integrated_lufs_i": integrated,
        "true_peak_dbtp": true_peak,
    }


def _read_json_file(path: Path, now: float) -> tuple[dict[str, Any], float | None, str | None]:
    age = _path_age_s(path, now)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, age, "missing"
    except json.JSONDecodeError:
        return {}, age, "malformed"
    except OSError:
        return {}, age, "unreadable"
    if not isinstance(raw, dict):
        return {}, age, "malformed"
    return raw, age, None


def _unknown_state(
    *,
    code: str,
    owner: str,
    message: str,
    freshness_s: float | None,
    evidence: dict[str, Any],
    checked_at: str,
) -> BroadcastAudioHealth:
    reason = AudioHealthReason(
        code=code,
        owner=owner,
        message=message,
        evidence_refs=list(evidence.keys()),
    )
    return BroadcastAudioHealth(
        safe=False,
        status=BroadcastAudioStatus.UNKNOWN,
        checked_at=checked_at,
        freshness_s=round(freshness_s, 3) if freshness_s is not None else 0.0,
        blocking_reasons=[reason],
        warnings=[],
        evidence=evidence,
        owners=_owners(),
    )


def _status_for(
    *,
    safe: bool,
    blocking: list[AudioHealthReason],
    warnings: list[AudioHealthReason],
) -> BroadcastAudioStatus:
    if safe:
        return BroadcastAudioStatus.DEGRADED if warnings else BroadcastAudioStatus.SAFE
    unknown_tokens = ("unknown", "missing", "malformed", "stale", "unreadable", "schema")
    if any(any(token in reason.code for token in unknown_tokens) for reason in blocking):
        return BroadcastAudioStatus.UNKNOWN
    return BroadcastAudioStatus.UNSAFE


def _block(
    blocking: list[AudioHealthReason],
    *,
    code: str,
    owner: str,
    message: str,
    evidence_refs: list[str],
) -> None:
    blocking.append(
        AudioHealthReason(
            code=code,
            owner=owner,
            message=message,
            evidence_refs=evidence_refs,
        )
    )


def _observed_obs_source(predicate: ObsEgressPredicateResult) -> str | None:
    if predicate.state in NON_BLOCKING_PIPEWIRE_EGRESS_STATES:
        return EXPECTED_OBS_SOURCE
    for record in predicate.evidence:
        wrong_sources = record.observed.get("wrong_obs_sources")
        if isinstance(wrong_sources, list) and wrong_sources:
            source = wrong_sources[0]
            if isinstance(source, str):
                return _port_node_name(source)
    return None


def _predicate_observed_bool(predicate: ObsEgressPredicateResult, key: str) -> bool | None:
    for record in predicate.evidence:
        value = record.observed.get(key)
        if isinstance(value, bool):
            return value
    return None


def _port_node_name(port: str) -> str:
    return port.split(":", 1)[0]


def _owners() -> dict[str, str]:
    return {
        "loudness_constants": "shared/audio_loudness.py",
        "route_policy": "config/audio-routing.yaml when Phase 6 ships",
        "topology": "config/audio-topology.yaml",
        "leak_guard": "scripts/audio-leak-guard.sh",
        "broadcast_forward": "scripts/hapax-audio-topology tts-broadcast-check",
        "egress_binding": "shared/obs_egress_predicate.py + pw-link -l",
        "voice_output_witness": str(DEFAULT_VOICE_OUTPUT_WITNESS),
        "runtime_safety": "hapax-audio-safety.service",
        "audio_ducker": "hapax-audio-ducker.service",
        "health_consumer": "livestream-health-group",
    }


def _repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _path_age_s(path: Path, now: float) -> float | None:
    try:
        return max(0.0, now - path.stat().st_mtime)
    except OSError:
        return None


def _iso_from_epoch(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).isoformat().replace("+00:00", "Z")


def _labeled_float(text: str, label: str) -> float | None:
    match = re.search(rf"\b{re.escape(label)}:\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))", text)
    if match is None:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _int_or_none(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _number_or_none(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _tail(text: str, *, max_chars: int = 1200) -> str:
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped
    return stripped[-max_chars:]


def _emit_lufs_gauge(integrated: float | None, *, true_peak: float | None = None) -> None:
    """Publish ``hapax_audio_egress_lufs_dbfs{stage="broadcast-master"}``
    to the node_exporter textfile collector. Errors are logged + swallowed
    so a metric-write failure never affects the loudness evaluator's
    own evidence pipeline.

    Cc-task: ``audio-audit-H3-prometheus-recovery-counters``.
    """
    try:
        from shared.recovery_counter_textfile import write_gauge
    except Exception:
        return
    try:
        if integrated is not None:
            write_gauge(
                metric_name="hapax_audio_egress_lufs_dbfs",
                labels={"stage": "broadcast-master"},
                help_text="Integrated loudness (LUFS-I) at the broadcast master stage.",
                value=float(integrated),
                file_basename="hapax_audio_recovery.prom",
            )
        if true_peak is not None:
            write_gauge(
                metric_name="hapax_audio_egress_true_peak_dbtp",
                labels={"stage": "broadcast-master"},
                help_text="True-peak (dBTP) at the broadcast master stage.",
                value=float(true_peak),
                file_basename="hapax_audio_recovery.prom",
            )
    except Exception:
        # Metric publishing must not affect the evidence pipeline.
        return


__all__ = [
    "AudioHealthReason",
    "BroadcastAudioHealth",
    "BroadcastAudioHealthEnvelope",
    "BroadcastAudioHealthPaths",
    "BroadcastAudioHealthThresholds",
    "BroadcastAudioStatus",
    "CommandResult",
    "DEFAULT_VOICE_OUTPUT_WITNESS",
    "ServiceStatus",
    "read_broadcast_audio_health_state",
    "resolve_broadcast_audio_health",
    "write_broadcast_audio_health_state",
]
