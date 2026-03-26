"""Uniform modulation — binds node parameters to perceptual signal sources."""

from __future__ import annotations

import logging

from .types import ModulationBinding

log = logging.getLogger(__name__)


class UniformModulator:
    """Drives shader uniforms from perceptual signals."""

    def __init__(self) -> None:
        self._bindings: list[ModulationBinding] = []
        self._smoothed: dict[tuple[str, str], float] = {}

    @property
    def bindings(self) -> list[ModulationBinding]:
        return list(self._bindings)

    def add_binding(self, binding: ModulationBinding) -> None:
        self._bindings = [
            b for b in self._bindings if not (b.node == binding.node and b.param == binding.param)
        ]
        self._bindings.append(binding)

    def remove_binding(self, node: str, param: str) -> None:
        self._bindings = [b for b in self._bindings if not (b.node == node and b.param == param)]
        self._smoothed.pop((node, param), None)

    def replace_all(self, bindings: list[ModulationBinding]) -> None:
        self._bindings = list(bindings)
        self._smoothed.clear()

    def tick(self, signals: dict[str, float]) -> dict[tuple[str, str], float]:
        """Process one frame tick. Returns {(node_id, param_name): value}."""
        updates: dict[tuple[str, str], float] = {}
        for binding in self._bindings:
            raw_signal = signals.get(binding.source)
            if raw_signal is None:
                continue
            target = raw_signal * binding.scale + binding.offset
            key = (binding.node, binding.param)
            prev = self._smoothed.get(key)
            if prev is None or binding.smoothing == 0.0:
                smoothed = target
            else:
                smoothed = binding.smoothing * prev + (1.0 - binding.smoothing) * target
            self._smoothed[key] = smoothed
            updates[key] = smoothed
        return updates
