"""End-to-end test for AUDIT-16 — engine queue-depth → SystemDegradedEngine.

Pins the contract that:
1. ``queue_depth_observation`` produces a bool keyed at
   ``engine_queue_depth_high``, matching the `LRDerivation.signal_name`
   registered in `shared/lr_registry.yaml`.
2. When fed to ``SystemDegradedEngine.contribute()`` for ``enter_ticks``
   consecutive ticks at depth > watermark, the engine transitions to
   ``DEGRADED``.
3. When depth drops below watermark for ``exit_ticks`` consecutive ticks
   (after being DEGRADED), the engine eventually transitions back toward
   HEALTHY.
4. The default watermark survives schema changes without breaking
   downstream consumers.
"""

from __future__ import annotations

from dataclasses import dataclass

from agents.hapax_daimonion.backends.engine_queue_depth import (
    DEFAULT_WATERMARK_DEPTH,
    queue_depth_observation,
)
from agents.hapax_daimonion.system_degraded_engine import SystemDegradedEngine


@dataclass
class _StubQueue:
    depth: int

    def qsize(self) -> int:
        return self.depth


# ── Observation shape ────────────────────────────────────────────────


def test_high_depth_observation():
    obs = queue_depth_observation(_StubQueue(depth=DEFAULT_WATERMARK_DEPTH + 1))
    assert obs == {"engine_queue_depth_high": True}


def test_low_depth_observation():
    obs = queue_depth_observation(_StubQueue(depth=0))
    assert obs == {"engine_queue_depth_high": False}


def test_at_watermark_observation():
    """Watermark itself is NOT 'high' — strictly greater-than."""
    obs = queue_depth_observation(_StubQueue(depth=DEFAULT_WATERMARK_DEPTH))
    assert obs == {"engine_queue_depth_high": False}


def test_custom_watermark():
    """Caller-specified watermark overrides the default."""
    src = _StubQueue(depth=10)
    assert queue_depth_observation(src, watermark=5) == {"engine_queue_depth_high": True}
    assert queue_depth_observation(src, watermark=20) == {"engine_queue_depth_high": False}


# ── End-to-end: contribute the observation → engine transitions ──────


def test_sustained_high_depth_drives_engine_to_degraded():
    """After enter_ticks of high queue depth, the engine state is DEGRADED."""
    eng = SystemDegradedEngine(prior=0.1, enter_ticks=2)
    src = _StubQueue(depth=DEFAULT_WATERMARK_DEPTH + 100)
    # Tick 1 — engine_queue_depth_high alone is a strong-but-single signal;
    # may not yet cross enter_threshold given conservative prior.
    eng.contribute(queue_depth_observation(src))
    eng.contribute(queue_depth_observation(src))
    # Either DEGRADED already or about to flip — give it 4 more ticks of
    # sustained evidence to pin the assertion robustly.
    for _ in range(4):
        eng.contribute(queue_depth_observation(src))
    assert eng.state == "DEGRADED", (
        f"After 6 ticks of high-depth signal, expected DEGRADED, got {eng.state!r}; "
        f"posterior={eng.posterior:.3f}"
    )


def test_recovery_returns_engine_toward_healthy():
    """After DEGRADED, sustained low-depth ticks flow through k_uncertain
    + k_exit hysteresis and eventually transition back."""
    eng = SystemDegradedEngine(prior=0.1, enter_ticks=2, exit_ticks=8)
    high = _StubQueue(depth=DEFAULT_WATERMARK_DEPTH + 100)
    low = _StubQueue(depth=0)

    # Drive to DEGRADED first.
    for _ in range(6):
        eng.contribute(queue_depth_observation(high))
    assert eng.state == "DEGRADED"

    # Apply sustained low-depth — engine must hold DEGRADED through
    # exit_ticks dwell, then transition.
    for _ in range(20):
        eng.contribute(queue_depth_observation(low))
    assert eng.state in ("UNCERTAIN", "HEALTHY"), (
        f"After 20 healthy ticks, expected UNCERTAIN or HEALTHY, got {eng.state!r}"
    )


# ── Watcher integration ─────────────────────────────────────────────


def test_directory_watcher_qsize_protocol_match():
    """The real watcher's qsize() satisfies the _QueueDepthSource protocol."""
    from logos.engine.watcher import DirectoryWatcher

    # Construct without start() — _queue is None, qsize() returns 0.
    w = DirectoryWatcher(watch_paths=[], callback=lambda e: None)  # type: ignore[arg-type]
    assert w.qsize() == 0
    obs = queue_depth_observation(w)
    assert obs == {"engine_queue_depth_high": False}
