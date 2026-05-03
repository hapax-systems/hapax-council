"""Signal-flow assertion daemon (H1 hardening).

Continuously asserts audio-graph signal flow at named broadcast stages
via parecord-driven RMS / crest / ZCR probes. Probes the monitor port of
each stage every 30s, classifies the captured PCM as
``silent | tone | music | noise | clipping``, emits Prometheus textfile
gauges, and ntfys on transition into a bad steady state at the
OBS-bound stage.

This package is **READ-ONLY** with respect to the production audio
runtime: it does not load PipeWire modules, does not restart services,
does not modify confs, and does not auto-mute. It is a probe + alerter,
not a circuit-breaker.

Source spec: ``docs/research/2026-05-03-audio-config-hardening-unthought-of-solutions.md``
(§1 H1 ranked first by impact-per-effort).
"""

from agents.audio_signal_assertion.classifier import (
    Classification,
    ClassifierConfig,
    ProbeMeasurement,
    classify,
    measure_pcm,
)
from agents.audio_signal_assertion.probes import (
    ProbeConfig,
    ProbeError,
    ProbeResult,
    capture_and_measure,
    discover_broadcast_stages,
)
from agents.audio_signal_assertion.transitions import (
    StageState,
    TransitionDetector,
    TransitionEvent,
)

__all__ = [
    "Classification",
    "ClassifierConfig",
    "ProbeConfig",
    "ProbeError",
    "ProbeMeasurement",
    "ProbeResult",
    "StageState",
    "TransitionDetector",
    "TransitionEvent",
    "capture_and_measure",
    "classify",
    "discover_broadcast_stages",
    "measure_pcm",
]
