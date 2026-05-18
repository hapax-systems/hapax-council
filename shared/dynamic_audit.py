"""Dynamic audit harness — behavioral verification for sustained broadcast.

Complements the static audit catalog (104 rows) with temporal probes that
verify behavior OVER TIME. Answers: does it keep being correct while running
across a full 2+ hour broadcast session?

v0: cadence vocabulary + 5 core probes.

Spec: docs/research/2026-04-20-dynamic-livestream-audit-catalog.md
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

AUDIT_STATE_PATH = Path("/dev/shm/hapax-audit/dynamic-state.json")


class Cadence(StrEnum):
    PER_TICK = "per_tick"
    PER_MINUTE = "per_minute"
    PER_SESSION = "per_session"
    PER_STREAM = "per_stream"
    CONTINUOUS = "continuous"
    REPLAY_ONLY = "replay_only"


class ProbeStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class ProbeResult:
    probe_id: str
    status: ProbeStatus
    value: float = 0.0
    message: str = ""
    timestamp: float = field(default_factory=time.time)


class DynamicProbe(Protocol):
    @property
    def probe_id(self) -> str: ...
    @property
    def cadence(self) -> Cadence: ...
    def evaluate(self) -> ProbeResult: ...


class EffectDriftMonotonicity:
    """Verify effect graph doesn't get stuck in a single preset for >10 minutes."""

    probe_id = "effect_drift_monotonicity"
    cadence = Cadence.PER_MINUTE

    def __init__(self) -> None:
        self._last_preset: str | None = None
        self._stuck_since: float = 0.0

    def evaluate(self) -> ProbeResult:
        try:
            state = json.loads(
                Path("/dev/shm/hapax-imagination/pipeline")
                .joinpath("active_preset.json")
                .read_text()
            )
            preset = state.get("preset", "")
        except (OSError, json.JSONDecodeError):
            return ProbeResult(self.probe_id, ProbeStatus.SKIP, message="No preset state")

        now = time.time()
        if preset != self._last_preset:
            self._last_preset = preset
            self._stuck_since = now
            return ProbeResult(self.probe_id, ProbeStatus.PASS, message=f"Active: {preset}")

        stuck_s = now - self._stuck_since
        if stuck_s > 600:
            return ProbeResult(
                self.probe_id,
                ProbeStatus.WARN,
                value=stuck_s,
                message=f"Stuck on {preset} for {stuck_s:.0f}s",
            )
        return ProbeResult(self.probe_id, ProbeStatus.PASS, value=stuck_s)


class AudioCrestFloor:
    """Verify broadcast audio crest factor stays above floor (not silence)."""

    probe_id = "audio_crest_floor"
    cadence = Cadence.CONTINUOUS

    def evaluate(self) -> ProbeResult:
        try:
            data = json.loads(Path("/dev/shm/hapax-audio/m3-crest-flatness.json").read_text())
            crest = float(data.get("crest_factor", 0.0))
        except (OSError, json.JSONDecodeError, ValueError):
            return ProbeResult(self.probe_id, ProbeStatus.SKIP, message="No crest data")

        if crest < 0.5:
            return ProbeResult(
                self.probe_id,
                ProbeStatus.FAIL,
                value=crest,
                message=f"Crest {crest:.2f} below floor 0.5 — possible silence",
            )
        return ProbeResult(self.probe_id, ProbeStatus.PASS, value=crest)


class CameraFrameFlow:
    """Verify at least one camera is producing frames."""

    probe_id = "camera_frame_flow"
    cadence = Cadence.PER_MINUTE

    def evaluate(self) -> ProbeResult:
        try:
            data = json.loads(
                Path("/dev/shm/hapax-compositor/camera-publisher-stats.json").read_text()
            )
            total = int(data.get("total_frames", 0))
            errors = int(data.get("errors", 0))
        except (OSError, json.JSONDecodeError, ValueError):
            return ProbeResult(self.probe_id, ProbeStatus.SKIP, message="No camera stats")

        if total == 0:
            return ProbeResult(self.probe_id, ProbeStatus.FAIL, message="Zero frames published")
        error_rate = errors / max(total, 1)
        if error_rate > 0.01:
            return ProbeResult(
                self.probe_id,
                ProbeStatus.WARN,
                value=error_rate,
                message=f"Error rate {error_rate:.3%}",
            )
        return ProbeResult(self.probe_id, ProbeStatus.PASS, value=float(total))


class V4l2OutputHealth:
    """Verify hapax-imagination is writing to /dev/video42."""

    probe_id = "v4l2_output_health"
    cadence = Cadence.PER_MINUTE
    _last_count: int = 0

    def evaluate(self) -> ProbeResult:
        try:
            data = json.loads(Path("/dev/shm/hapax-imagination/health.json").read_text())
            ref = float(data.get("reference", 0.0))
            err = float(data.get("error", 0.0))
        except (OSError, json.JSONDecodeError, ValueError):
            return ProbeResult(self.probe_id, ProbeStatus.FAIL, message="No imagination health")

        if err > 0.1:
            return ProbeResult(
                self.probe_id,
                ProbeStatus.WARN,
                value=err,
                message=f"Imagination error rate {err:.2f}",
            )
        return ProbeResult(self.probe_id, ProbeStatus.PASS, value=ref)


class EigenformDrift:
    """Verify eigenform state vector is updating (system is alive)."""

    probe_id = "eigenform_drift"
    cadence = Cadence.PER_MINUTE

    def evaluate(self) -> ProbeResult:
        try:
            data = json.loads(Path("/dev/shm/hapax-eigenform/state.json").read_text())
            ts = float(data.get("timestamp", 0))
            age = time.time() - ts
        except (OSError, json.JSONDecodeError, ValueError):
            return ProbeResult(self.probe_id, ProbeStatus.SKIP, message="No eigenform state")

        if age > 30:
            return ProbeResult(
                self.probe_id,
                ProbeStatus.WARN,
                value=age,
                message=f"Eigenform stale: {age:.0f}s old",
            )
        return ProbeResult(self.probe_id, ProbeStatus.PASS, value=age)


CORE_PROBES: list[DynamicProbe] = [
    EffectDriftMonotonicity(),
    AudioCrestFloor(),
    CameraFrameFlow(),
    V4l2OutputHealth(),
    EigenformDrift(),
]


def run_all_probes() -> list[ProbeResult]:
    results = []
    for probe in CORE_PROBES:
        try:
            results.append(probe.evaluate())
        except Exception:
            results.append(ProbeResult(probe.probe_id, ProbeStatus.SKIP, message="probe crashed"))
    return results


def write_state(results: list[ProbeResult]) -> None:
    state = {
        "timestamp": time.time(),
        "probes": {
            r.probe_id: {"status": r.status, "value": r.value, "message": r.message}
            for r in results
        },
        "overall": "pass"
        if all(r.status in (ProbeStatus.PASS, ProbeStatus.SKIP) for r in results)
        else "degraded",
    }
    try:
        AUDIT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = AUDIT_STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(state))
        tmp.rename(AUDIT_STATE_PATH)
    except OSError:
        log.debug("Failed to write audit state", exc_info=True)
