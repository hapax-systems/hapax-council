"""Engine queue depth → SystemDegradedEngine signal adapter (AUDIT-16).

Phase 6d-i.B partial wire-in: closes the gmail-sync inotify-flood loop
opened by 3499-004 (#1354). The watcher's `_should_skip` filter shipped
in #1354 short-circuits gmail/* events from going through the rule
chain, but a future un-filtered burst (any new RAG subtree without a
skip filter) could re-flood the queue. Phase 6d's `engine_queue_depth_high`
signal makes that observable as a Bayesian posterior over system-degraded
state instead of a hardcoded threshold gate.

This module ships the primitive — a queue-depth observation function
suitable to feed `SystemDegradedEngine.contribute()`. The actual
periodic-tick loop wiring lives in a future Phase 6d-i.B follow-up that
also wires `drift_significant`, `gpu_pressure_high`, and
`director_cadence_missed` into the same engine instance.

Reference doc: `docs/operations/2026-04-25-workstream-realignment-v4-audit-incorporated.md`
§3.4 AUDIT-16 + §5.1 beta queue.
"""

from __future__ import annotations

from typing import Protocol

# Default safe-watermark — consumer queue depth above this counts as
# "high" and contributes positive evidence for system_degraded. Tuned
# empirically: a ~6,000-event gmail-sync burst saturated to ~2,000-3,000
# in the queue at peak before #1354's _should_skip filter shipped. The
# watermark of 500 catches a burst before drain time exceeds tens of
# seconds while staying well below normal-busy queue (typically <50).
DEFAULT_WATERMARK_DEPTH: int = 500


class _QueueDepthSource(Protocol):
    """Anything exposing a ``qsize() -> int`` is acceptable as a source.

    `logos.engine.watcher.DirectoryWatcher` matches this protocol;
    tests use a stub object with the same shape.
    """

    def qsize(self) -> int: ...


def queue_depth_observation(
    source: _QueueDepthSource,
    *,
    watermark: int = DEFAULT_WATERMARK_DEPTH,
) -> dict[str, bool | None]:
    """Build a single-tick observation dict for SystemDegradedEngine.

    Returns ``{"engine_queue_depth_high": True}`` when the source's
    queue depth exceeds the watermark, ``{"engine_queue_depth_high": False}``
    otherwise. The False branch contributes negative evidence per the
    bidirectional `LRDerivation` (`positive_only=False`) registered in
    `shared/lr_registry.yaml::system_degraded_signals.engine_queue_depth_high`.

    Designed for callers like::

        from agents.hapax_daimonion.system_degraded_engine import SystemDegradedEngine
        from agents.hapax_daimonion.backends.engine_queue_depth import queue_depth_observation
        from logos.engine import ReactiveEngine  # exposes .watcher

        engine = SystemDegradedEngine()
        # In a periodic tick:
        engine.contribute(queue_depth_observation(reactive_engine.watcher))
    """
    depth = source.qsize()
    return {"engine_queue_depth_high": depth > watermark}


__all__ = [
    "DEFAULT_WATERMARK_DEPTH",
    "queue_depth_observation",
]
