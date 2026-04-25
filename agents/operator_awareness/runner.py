"""Awareness state runner — 30s tick that aggregates + atomically writes.

The daemon entry point: every ``tick_s`` seconds, calls
``Aggregator.collect()`` and writes the resulting AwarenessState to
``/dev/shm/hapax-awareness/state.json`` via the atomic writer.

Prometheus metrics:
- ``hapax_awareness_state_writes_total{result}`` — per-tick outcome
- ``hapax_awareness_aggregator_source_failures_total{source}`` —
  per-source failure counter (sources fail individually rather than
  failing the whole tick)

The aggregator already swallows per-source failures; this runner
metric counts ticks where any wired source returned a default-empty
block when its source path existed (e.g. corrupt JSON). For now,
each tick that succeeds at writing increments the writes_total
``ok`` counter; a write failure increments ``error``.
"""

from __future__ import annotations

import logging
import os
import signal as _signal
import threading

from prometheus_client import REGISTRY, CollectorRegistry, Counter

from agents.operator_awareness.aggregator import Aggregator
from agents.operator_awareness.state import (
    DEFAULT_STATE_PATH,
    write_state_atomic,
)

log = logging.getLogger(__name__)

DEFAULT_TICK_S: float = float(os.environ.get("HAPAX_AWARENESS_TICK_S", "30"))


class AwarenessRunner:
    """30s tick orchestrator for the awareness state spine.

    Constructor parameters
    ----------------------
    aggregator:
        Aggregator instance (production wires the default; tests
        inject a mock).
    state_path:
        Output path for the atomic writer. Defaults to
        ``/dev/shm/hapax-awareness/state.json``.
    tick_s:
        Tick cadence in seconds. Floor 5s to keep load bounded if
        misconfigured (production default 30s).
    registry:
        Prometheus registry (tests override with CollectorRegistry).
    """

    def __init__(
        self,
        *,
        aggregator: Aggregator | None = None,
        state_path=DEFAULT_STATE_PATH,
        tick_s: float = DEFAULT_TICK_S,
        registry: CollectorRegistry = REGISTRY,
    ) -> None:
        self._aggregator = aggregator or Aggregator()
        self._state_path = state_path
        self._tick_s = max(5.0, tick_s)
        self._stop_evt = threading.Event()

        self.writes_total = Counter(
            "hapax_awareness_state_writes_total",
            "Awareness state writes attempted, broken down by outcome.",
            ["result"],
            registry=registry,
        )

    def run_once(self) -> str:
        """Build state + write atomically; return the result label."""
        try:
            state = self._aggregator.collect()
        except Exception:  # noqa: BLE001
            log.exception("aggregator.collect() raised; recording failure")
            self.writes_total.labels(result="aggregator_error").inc()
            return "aggregator_error"
        ok = write_state_atomic(state, self._state_path)
        result = "ok" if ok else "error"
        self.writes_total.labels(result=result).inc()
        return result

    def run_forever(self) -> None:
        for sig in (_signal.SIGTERM, _signal.SIGINT):
            try:
                _signal.signal(sig, lambda *_: self._stop_evt.set())
            except ValueError:
                pass

        log.info(
            "awareness runner starting; tick=%.1fs state=%s",
            self._tick_s,
            self._state_path,
        )
        while not self._stop_evt.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001
                log.exception("tick failed; continuing on next cadence")
            self._stop_evt.wait(self._tick_s)

    def stop(self) -> None:
        self._stop_evt.set()


__all__ = ["DEFAULT_TICK_S", "AwarenessRunner"]
