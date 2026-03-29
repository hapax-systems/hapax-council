"""Unified signal bus for perception → modulation flow.

Perception backends publish normalized float signals. All capabilities
(voice, visual, modulation) consume via snapshot(). No callbacks —
consumers poll on their own tick cadence.

Phase 4 of capability parity (queue #020).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class SignalModulationBinding:
    """Binds a signal to a target parameter with scaling and smoothing.

    Used by both daimonion (voice.word_limit) and Reverie (bloom.alpha).
    Named SignalModulationBinding to avoid collision with
    agents.effect_graph.types.ModulationBinding (different schema).
    """

    target: str  # "bloom.alpha" or "voice.word_limit"
    signal: str  # signal name from SignalBus
    scale: float = 1.0
    offset: float = 0.0
    smoothing: float = 0.85  # exponential smoothing alpha


class SignalBus:
    """Thread-safe signal bus for perception → modulation flow."""

    def __init__(self) -> None:
        self._signals: dict[str, float] = {}
        self._lock = threading.Lock()

    def publish(self, name: str, value: float) -> None:
        """Publish a signal value. Thread-safe."""
        with self._lock:
            self._signals[name] = value

    def publish_many(self, signals: dict[str, float]) -> None:
        """Publish multiple signals atomically."""
        with self._lock:
            self._signals.update(signals)

    def get(self, name: str, default: float = 0.0) -> float:
        """Get a single signal value. Thread-safe."""
        with self._lock:
            return self._signals.get(name, default)

    def snapshot(self) -> dict[str, float]:
        """Return a copy of all current signal values. Thread-safe."""
        with self._lock:
            return dict(self._signals)

    def clear(self) -> None:
        """Clear all signals."""
        with self._lock:
            self._signals.clear()

    def apply_bindings(
        self,
        bindings: list[SignalModulationBinding],
        current: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """Apply modulation bindings to current values.

        Returns dict of {target: modulated_value}. If current is provided,
        applies exponential smoothing against current values.
        """
        signals = self.snapshot()
        result: dict[str, float] = {}
        for b in bindings:
            raw = signals.get(b.signal, 0.0)
            target_value = raw * b.scale + b.offset
            if current is not None and b.target in current:
                # Exponential smoothing
                prev = current[b.target]
                target_value = b.smoothing * prev + (1.0 - b.smoothing) * target_value
            result[b.target] = target_value
        return result
