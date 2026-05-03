"""Audio pipeline health monitoring suite — shared primitives.

This package provides the reusable building blocks for all audio-health
monitors (M0–M5):

- ``classifier``: 5-class PCM classification (silent/tone/music_voice/noise/clipping).
- ``probes``: parecord-based monitor-port capture + measurement.
- ``transitions``: Hysteresis state machine for sustained-state alerting.

Originally extracted from ``agents.audio_signal_assertion`` (the H1
signal-flow assertion daemon). That package re-exports from here so
existing imports continue to work.

Monitors in the suite:
- M0: Package extraction + meta-monitor (this task).
- M1: Signal classification per stage (extends H1).
- M2: LUFS-S rolling integrated loudness.
- M3: Crest factor + ZCR + spectral flatness.
- M4: Inter-stage correlation.
- M5: PipeWire topology + module presence.
"""

from agents.audio_health.classifier import (
    BAD_STEADY_STATES,
    Classification,
    ClassifierConfig,
    ProbeMeasurement,
    classify,
    measure_pcm,
)
from agents.audio_health.probes import (
    DEFAULT_DURATION_S,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_STAGES,
    OBS_BOUND_STAGE,
    ProbeConfig,
    ProbeError,
    ProbeResult,
    capture_and_measure,
    discover_broadcast_stages,
)
from agents.audio_health.transitions import (
    DEFAULT_CLIPPING_SUSTAIN_S,
    DEFAULT_NOISE_SUSTAIN_S,
    DEFAULT_RECOVERY_SUSTAIN_S,
    DEFAULT_SILENCE_SUSTAIN_S,
    StageObservation,
    StageState,
    TransitionDetector,
    TransitionEvent,
)

__all__ = [
    "BAD_STEADY_STATES",
    "Classification",
    "ClassifierConfig",
    "DEFAULT_CLIPPING_SUSTAIN_S",
    "DEFAULT_DURATION_S",
    "DEFAULT_NOISE_SUSTAIN_S",
    "DEFAULT_RECOVERY_SUSTAIN_S",
    "DEFAULT_SAMPLE_RATE",
    "DEFAULT_SILENCE_SUSTAIN_S",
    "DEFAULT_STAGES",
    "OBS_BOUND_STAGE",
    "ProbeConfig",
    "ProbeError",
    "ProbeMeasurement",
    "ProbeResult",
    "StageObservation",
    "StageState",
    "TransitionDetector",
    "TransitionEvent",
    "capture_and_measure",
    "classify",
    "discover_broadcast_stages",
    "measure_pcm",
]
