"""Broadcast audio health producer — periodic egress audibility probe.

Wraps :mod:`shared.audio_marker_probe_fft` (delta's PR #2049) into a
periodic daemon that injects a sub-audible marker into each named
PipeWire sink, captures from the corresponding monitor source, and
emits JSONL evidence per configured route. Operator gets a
machine-checkable answer to "is Hapax actually being heard right now"
on broadcast vs private audio paths.

cc-task: ``broadcast-audio-health-producer`` (depends on the now-
merged audio-marker-probe-fft).
"""

from __future__ import annotations

from .producer import (
    DEFAULT_STATE_DIR,
    BroadcastAudioHealthProducer,
    ProbeOutcome,
    ProbeResult,
    RouteSpec,
)

__all__ = [
    "DEFAULT_STATE_DIR",
    "BroadcastAudioHealthProducer",
    "ProbeOutcome",
    "ProbeResult",
    "RouteSpec",
]
