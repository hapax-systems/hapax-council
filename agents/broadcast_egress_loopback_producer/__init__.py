"""Broadcast egress loopback witness producer.

Samples the broadcast egress source (default ``hapax-broadcast-normalized``)
via ``parec`` once per tick, computes RMS dBFS / peak dBFS / silence_ratio
over a sliding window, and writes a fresh
:class:`shared.broadcast_audio_health.EgressLoopbackWitness` JSON
atomically to ``/dev/shm/hapax-broadcast/egress-loopback.json``.

Pairs with PR #2209's ``_evaluate_egress_loopback`` evaluator: that
evaluator reads the witness file with a default 60s freshness threshold
and fails closed when the file is missing/stale/malformed/silent.
Without this producer the witness file never exists and broadcast
audio health stays UNKNOWN forever.

cc-task: ``broadcast-audio-health-producer-loopback-monitor``
related: shared/broadcast_audio_health.py (evaluator)
"""

from __future__ import annotations

from .producer import (
    DEFAULT_BROADCAST_SOURCE,
    DEFAULT_TICK_SECONDS,
    DEFAULT_WINDOW_SECONDS,
    DEFAULT_WITNESS_PATH,
    EgressLoopbackProducer,
    LoopbackSample,
    compute_loopback_metrics,
    write_witness_atomic,
)

__all__ = [
    "DEFAULT_BROADCAST_SOURCE",
    "DEFAULT_TICK_SECONDS",
    "DEFAULT_WINDOW_SECONDS",
    "DEFAULT_WITNESS_PATH",
    "EgressLoopbackProducer",
    "LoopbackSample",
    "compute_loopback_metrics",
    "write_witness_atomic",
]
