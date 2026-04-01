"""Reusable exploration tracker bundle for component wiring.

Each component instantiates an ExplorationTrackerBundle, feeds it
per-tick data, and publishes the resulting ExplorationSignal.
"""

from __future__ import annotations

import logging
import time

from shared.exploration import (
    CoherenceTracker,
    ExplorationAction,
    ExplorationSignal,
    HabituationTracker,
    InterestTracker,
    LearningProgressTracker,
    compute_exploration_signal,
    evaluate_control_law,
)
from shared.exploration_writer import publish_exploration_signal

log = logging.getLogger("exploration")


class ExplorationTrackerBundle:
    """Pre-wired bundle of all 4 exploration trackers for a component."""

    def __init__(
        self,
        component: str,
        edges: list[str],
        traces: list[str],
        neighbors: list[str],
        *,
        kappa: float = 1.0,
        t_patience: float = 300.0,
    ) -> None:
        self.component = component
        self.t_patience = t_patience
        self.habituation = HabituationTracker(edges, kappa=kappa)
        self.interest = InterestTracker(traces, t_patience=t_patience)
        self.learning = LearningProgressTracker()
        self.coherence = CoherenceTracker(neighbors)
        self._last_tick = time.monotonic()

    def feed_habituation(self, edge: str, current: float, previous: float, std_dev: float) -> None:
        self.habituation.update(edge, current, previous, std_dev)

    def feed_interest(self, trace: str, current: float, std_dev: float) -> None:
        now = time.monotonic()
        elapsed = now - self._last_tick
        self.interest.tick(trace, current, std_dev, elapsed)

    def feed_error(self, error: float) -> None:
        self.learning.update(error)

    def feed_phases(self, phases: dict[str, float]) -> None:
        now = time.monotonic()
        elapsed = now - self._last_tick
        self.coherence.update_phases(phases)
        self.coherence.tick(elapsed)

    def compute_and_publish(self) -> ExplorationSignal:
        """Compute the ExplorationSignal and publish to /dev/shm."""
        self._last_tick = time.monotonic()
        sig = compute_exploration_signal(
            self.component,
            self.habituation,
            self.interest,
            self.learning,
            self.coherence,
            self.t_patience,
        )
        try:
            publish_exploration_signal(sig)
        except Exception:
            log.debug("Failed to publish exploration signal for %s", self.component)
        return sig

    def evaluate_action(
        self, signal: ExplorationSignal | None = None, sigma_explore: float = 0.10
    ) -> ExplorationAction:
        """Evaluate the 15th control law for this component.

        Call after compute_and_publish(). Returns an ExplorationAction
        that the component should apply to its behavior this tick.
        """
        if signal is None:
            signal = self.compute_and_publish()
        return evaluate_control_law(signal, sigma_explore)
