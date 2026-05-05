"""Observe-only egress circuit breaker for ``hapax-pipewire-graph``.

P2 samples the OBS-bound monitor at 2 Hz, computes RMS / crest / ZCR,
and records what the future active breaker would have done. It never
engages safe-mute. The implementation keeps the two candidate clipping
predicates separate so the 24 hour shadow window can decide which
predicate survives into P4/P5:

* amplified clipping / bleed: ``crest > 5.0`` and RMS louder than -40 dBFS
* steady drone / format artifact: ``2.5 <= crest <= 5.0``
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from agents.audio_health.probes import ProbeConfig, ProbeResult, capture_and_measure

CLIPPING_CREST_THRESHOLD: Final[float] = 5.0
FORMAT_ARTIFACT_CREST_MIN: Final[float] = 2.5
FORMAT_ARTIFACT_CREST_MAX: Final[float] = 5.0
FORMAT_ARTIFACT_ZCR_MIN: Final[float] = 0.25
CLIPPING_RMS_THRESHOLD_DBFS: Final[float] = -40.0
CLIPPING_SUSTAINED_S: Final[float] = 2.0
SILENCE_RMS_THRESHOLD_DBFS: Final[float] = -60.0
SILENCE_SUSTAINED_S: Final[float] = 5.0
SAMPLE_WINDOW_S: Final[float] = 0.5
HYSTERESIS_RECOVERY_S: Final[float] = 3.0
PRE_EVENT_BUFFER_S: Final[float] = 30.0
PRE_EVENT_BUFFER_SAMPLES: Final[int] = int(PRE_EVENT_BUFFER_S / SAMPLE_WINDOW_S)
RECOVERY_CREST_MAX: Final[float] = 4.0
RECOVERY_RMS_MIN_DBFS: Final[float] = -40.0
RECOVERY_RMS_MAX_DBFS: Final[float] = -10.0
DEFAULT_EGRESS_STAGE: Final[str] = "hapax-obs-broadcast-remap"


def utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp with a stable ``Z`` suffix."""

    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class EgressFailureMode(StrEnum):
    """Breaker state names written to JSONL and metrics."""

    NOMINAL = "nominal"
    CLIPPING_NOISE = "clipping-noise"
    SILENCE = "silence"


@dataclass(frozen=True)
class EgressHealth:
    """One egress sample derived from an OBS-bound monitor capture."""

    rms_dbfs: float
    peak_dbfs: float
    crest_factor: float
    zcr: float
    timestamp_utc: str
    source: str = DEFAULT_EGRESS_STAGE
    sample_window_s: float = SAMPLE_WINDOW_S
    sample_count: int = 0
    error: str | None = None

    @classmethod
    def from_probe_result(
        cls,
        result: ProbeResult,
        *,
        source: str = DEFAULT_EGRESS_STAGE,
        timestamp_utc: str | None = None,
    ) -> EgressHealth:
        measurement = result.measurement
        return cls(
            rms_dbfs=measurement.rms_dbfs,
            peak_dbfs=measurement.peak_dbfs,
            crest_factor=measurement.crest_factor,
            zcr=measurement.zero_crossing_rate,
            timestamp_utc=timestamp_utc or utc_now_iso(),
            source=source,
            sample_window_s=result.duration_s or SAMPLE_WINDOW_S,
            sample_count=measurement.sample_count,
            error=result.error,
        )

    @property
    def amplified_clipping_candidate(self) -> bool:
        return (
            self.crest_factor > CLIPPING_CREST_THRESHOLD
            and self.rms_dbfs > CLIPPING_RMS_THRESHOLD_DBFS
        )

    @property
    def format_artifact_candidate(self) -> bool:
        return FORMAT_ARTIFACT_CREST_MIN <= self.crest_factor <= FORMAT_ARTIFACT_CREST_MAX

    @property
    def silence_candidate(self) -> bool:
        return self.rms_dbfs < SILENCE_RMS_THRESHOLD_DBFS

    @property
    def clipping_candidate(self) -> bool:
        return self.amplified_clipping_candidate or (
            self.format_artifact_candidate
            and self.zcr >= FORMAT_ARTIFACT_ZCR_MIN
            and self.rms_dbfs > CLIPPING_RMS_THRESHOLD_DBFS
        )

    def to_dict(self, *, state: EgressFailureMode | None = None) -> dict[str, object]:
        payload: dict[str, object] = {
            "timestamp_utc": self.timestamp_utc,
            "source": self.source,
            "rms_dbfs": round(self.rms_dbfs, 3),
            "peak_dbfs": round(self.peak_dbfs, 3),
            "crest_factor": round(self.crest_factor, 3),
            "zcr": round(self.zcr, 6),
            "sample_window_s": round(self.sample_window_s, 3),
            "sample_count": int(self.sample_count),
            "amplified_clipping_candidate": self.amplified_clipping_candidate,
            "format_artifact_candidate": self.format_artifact_candidate,
            "clipping_candidate": self.clipping_candidate,
            "silence_candidate": self.silence_candidate,
            "error": self.error,
        }
        if state is not None:
            payload["failure_mode"] = state.value
        return payload


@dataclass(frozen=True)
class ShadowAlert:
    """What the shadow daemon reports on first sustained bad state."""

    mode: EgressFailureMode
    health: EgressHealth
    pre_event_buffer: tuple[EgressHealth, ...]
    message: str = "shadow-mode would have engaged safe-mute"

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "message": self.message,
            "health": self.health.to_dict(state=self.mode),
            "pre_event_buffer": [h.to_dict() for h in self.pre_event_buffer],
        }


class EgressCircuitBreaker:
    """State machine for observe-only egress health.

    ``observe()`` is pure with respect to PipeWire. It updates state,
    returns a :class:`ShadowAlert` on first sustained failure, and
    invokes ``on_shadow_alert`` if provided. Probe capture is factored
    into :meth:`probe_once` so tests can drive the state machine with
    synthetic measurements.
    """

    def __init__(
        self,
        *,
        probe: Callable[[], EgressHealth] | None = None,
        livestream_active: Callable[[], bool] | None = None,
        on_shadow_alert: Callable[[ShadowAlert], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.probe = probe
        self.livestream_active = livestream_active or (lambda: True)
        self.on_shadow_alert = on_shadow_alert
        self.clock = clock or time.monotonic
        self.state = EgressFailureMode.NOMINAL
        self.failure_entered_at: float | None = None
        self.failure_candidate: EgressFailureMode | None = None
        self.recovery_entered_at: float | None = None
        self.history: deque[EgressHealth] = deque(maxlen=PRE_EVENT_BUFFER_SAMPLES)

    def probe_once(self) -> EgressHealth:
        """Capture one egress sample through the configured probe callback."""

        if self.probe is None:
            raise RuntimeError("EgressCircuitBreaker.probe_once requires a probe callback")
        return self.probe()

    def observe(self, health: EgressHealth, *, now_s: float | None = None) -> ShadowAlert | None:
        """Update breaker state with one health sample.

        Probe errors are logged by callers and appended to history, but
        they do not drive SILENCE. This keeps capture glitches from
        producing false-positive shadow alerts.
        """

        now = self.clock() if now_s is None else now_s
        self.history.append(health)
        if health.error:
            self.failure_entered_at = None
            self.failure_candidate = None
            return None

        if self.state == EgressFailureMode.NOMINAL:
            candidate: EgressFailureMode | None = None
            sustain_s = 0.0
            if health.clipping_candidate:
                candidate = EgressFailureMode.CLIPPING_NOISE
                sustain_s = CLIPPING_SUSTAINED_S
            elif health.silence_candidate and self.livestream_active():
                candidate = EgressFailureMode.SILENCE
                sustain_s = SILENCE_SUSTAINED_S

            if candidate is None:
                self.failure_entered_at = None
                self.failure_candidate = None
                return None

            if self.failure_candidate != candidate:
                self.failure_candidate = candidate
                self.failure_entered_at = now
                return None

            if self.failure_entered_at is None:
                self.failure_entered_at = now
                return None

            if now - self.failure_entered_at >= sustain_s:
                return self._enter_failure(candidate, health)
            return None

        if self._is_recovered(health):
            if self.recovery_entered_at is None:
                self.recovery_entered_at = now
            elif now - self.recovery_entered_at >= HYSTERESIS_RECOVERY_S:
                self._exit_failure()
        else:
            self.recovery_entered_at = None
        return None

    def tick(self) -> tuple[EgressHealth, ShadowAlert | None]:
        """Probe once and feed the sample into :meth:`observe`."""

        health = self.probe_once()
        return health, self.observe(health)

    def _enter_failure(
        self,
        mode: EgressFailureMode,
        health: EgressHealth,
    ) -> ShadowAlert:
        self.state = mode
        self.recovery_entered_at = None
        alert = ShadowAlert(mode=mode, health=health, pre_event_buffer=tuple(self.history))
        if self.on_shadow_alert is not None:
            self.on_shadow_alert(alert)
        return alert

    def _exit_failure(self) -> None:
        self.state = EgressFailureMode.NOMINAL
        self.failure_entered_at = None
        self.failure_candidate = None
        self.recovery_entered_at = None

    @staticmethod
    def _is_recovered(health: EgressHealth) -> bool:
        return (
            RECOVERY_RMS_MIN_DBFS <= health.rms_dbfs <= RECOVERY_RMS_MAX_DBFS
            and health.crest_factor < RECOVERY_CREST_MAX
        )


def probe_egress_health(
    *,
    stage: str = DEFAULT_EGRESS_STAGE,
    probe_config: ProbeConfig | None = None,
) -> EgressHealth:
    """Capture and measure the OBS-bound egress monitor.

    The default config matches P2's 2 Hz loop: 0.5 s windows at 48 kHz.
    """

    cfg = probe_config or ProbeConfig(duration_s=SAMPLE_WINDOW_S)
    result = capture_and_measure(stage, config=cfg)
    return EgressHealth.from_probe_result(result, source=stage)


__all__ = [
    "CLIPPING_CREST_THRESHOLD",
    "CLIPPING_RMS_THRESHOLD_DBFS",
    "CLIPPING_SUSTAINED_S",
    "DEFAULT_EGRESS_STAGE",
    "EgressCircuitBreaker",
    "EgressFailureMode",
    "EgressHealth",
    "FORMAT_ARTIFACT_CREST_MAX",
    "FORMAT_ARTIFACT_CREST_MIN",
    "FORMAT_ARTIFACT_ZCR_MIN",
    "HYSTERESIS_RECOVERY_S",
    "PRE_EVENT_BUFFER_S",
    "SAMPLE_WINDOW_S",
    "SILENCE_RMS_THRESHOLD_DBFS",
    "SILENCE_SUSTAINED_S",
    "ShadowAlert",
    "probe_egress_health",
    "utc_now_iso",
]
