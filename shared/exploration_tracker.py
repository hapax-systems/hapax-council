"""Reusable exploration tracker bundle for component wiring.

Each component instantiates an ExplorationTrackerBundle, feeds it
per-tick data, and publishes the resulting ExplorationSignal.

compute_and_publish() now also evaluates the 15th control law and
emits exploration impingements to the cross-daemon JSONL transport.
This means all 13 wired components automatically participate in
the exploration → DMN escalation loop.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from shared.exploration import (
    CoherenceTracker,
    ExplorationAction,
    ExplorationMode,
    ExplorationSignal,
    HabituationTracker,
    InterestTracker,
    LearningProgressTracker,
    compute_exploration_signal,
    evaluate_control_law,
)
from shared.exploration_writer import publish_exploration_signal

log = logging.getLogger("exploration")

_IMPINGEMENTS_FILE = Path("/dev/shm/hapax-dmn/impingements.jsonl")


_EMISSION_COOLDOWN_S = 30.0  # max one impingement per component per 30s
_last_emission: dict[str, float] = {}


def _emit_exploration_impingement(
    component: str, action: ExplorationAction, signal: ExplorationSignal
) -> None:
    """Write exploration impingement to the cross-daemon JSONL transport.

    Rate-limited to one emission per component per 30s to prevent
    flooding the JSONL transport and overwhelming CPAL/DMN consumers.
    """
    if action.mode == ExplorationMode.NONE:
        return

    now = time.time()
    last = _last_emission.get(component, 0.0)
    if now - last < _EMISSION_COOLDOWN_S:
        return
    _last_emission[component] = now

    type_map = {
        ExplorationMode.DIRECTED: "exploration_opp",
        ExplorationMode.UNDIRECTED: "boredom",
        ExplorationMode.FOCUSED: "curiosity",
    }
    imp_type = type_map.get(action.mode, "boredom")
    strength = signal.boredom_index if imp_type == "boredom" else signal.curiosity_index

    imp = {
        "timestamp": time.time(),
        "source": f"exploration.{component}",
        "type": imp_type,
        "strength": round(strength, 4),
        "content": {
            "mode": action.mode,
            "boredom_index": round(signal.boredom_index, 4),
            "curiosity_index": round(signal.curiosity_index, 4),
            "max_novelty_edge": signal.max_novelty_edge,
        },
        "context": {},
    }
    try:
        with _IMPINGEMENTS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(imp) + "\n")
    except OSError:
        pass  # Non-fatal — DMN transport may not exist yet


class ExplorationTrackerBundle:
    """Pre-wired bundle of all 4 exploration trackers for a component.

    compute_and_publish() evaluates the control law and emits impingements
    automatically. Components that need the ExplorationAction for their own
    modulation can read it from self.last_action after compute_and_publish().
    """

    def __init__(
        self,
        component: str,
        edges: list[str],
        traces: list[str],
        neighbors: list[str],
        *,
        kappa: float = 1.0,
        t_patience: float = 300.0,
        sigma_explore: float = 0.10,
    ) -> None:
        self.component = component
        self.t_patience = t_patience
        self.sigma_explore = sigma_explore
        self.habituation = HabituationTracker(edges, kappa=kappa)
        self.interest = InterestTracker(traces, t_patience=t_patience)
        self.learning = LearningProgressTracker()
        self.coherence = CoherenceTracker(neighbors)
        self._last_tick = time.monotonic()
        self.last_action: ExplorationAction = ExplorationAction.no_action()

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
        """Compute ExplorationSignal, evaluate control law, emit impingements."""
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

        # Evaluate control law and emit impingement
        self.last_action = evaluate_control_law(sig, self.sigma_explore)
        if self.last_action.mode != ExplorationMode.NONE:
            _emit_exploration_impingement(self.component, self.last_action, sig)
            log.debug(
                "Exploration [%s]: %s (boredom=%.2f curiosity=%.2f)",
                self.component,
                self.last_action.mode,
                sig.boredom_index,
                sig.curiosity_index,
            )

        return sig

    def evaluate_action(
        self, signal: ExplorationSignal | None = None, sigma_explore: float | None = None
    ) -> ExplorationAction:
        """Evaluate the 15th control law for this component.

        Usually not needed — compute_and_publish() already evaluates.
        Use this for explicit re-evaluation with different sigma.
        """
        if signal is None:
            signal = self.compute_and_publish()
            return self.last_action
        return evaluate_control_law(signal, sigma_explore or self.sigma_explore)
