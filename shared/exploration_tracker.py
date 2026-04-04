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

# Edge descriptions: what each exploration edge means in plain language.
# These flow into the impingement narrative so the affordance pipeline
# can match exploration signals against semantically relevant affordances.
_EDGE_DESCRIPTIONS: dict[str, str] = {
    # affordance_pipeline
    "impingement_source": "the pattern of incoming signals to the recruitment pipeline",
    "candidate_diversity": "the variety of affordances retrieved for each impingement",
    # visual_chain / ReverieMixer
    "salience_input": "the imagination's assessed importance of its current thought",
    "technique_selection": "which visual techniques are being recruited for expression",
    # dmn_pulse
    "observation_quality": "the freshness and availability of perceptual observations",
    "evaluative_trajectory": "the DMN's assessment of whether things are improving or degrading",
    # ir_presence
    "person_detected": "whether a person is physically present in the space",
    "motion_delta": "the level of physical movement detected by infrared cameras",
    # contact_mic
    "desk_energy": "the vibration energy level from the desk contact microphone",
    "desk_activity": "the type of physical desk engagement detected",
    # stimmung
    "stance_changes": "transitions in the system's overall attunement state",
    "dimension_freshness": "how many health dimensions are reporting current data",
    # content_resolver
    "fragment_novelty": "the novelty of incoming imagination fragments",
    "resolution_success": "whether content resolution is succeeding or failing",
    # salience_router
    "concern_overlap": "how well the operator's speech matches established concern areas",
    "activation_level": "the composite activation score for conversational engagement",
    # temporal_bands
    "snapshot_content": "the current activity context in the temporal formatter",
    "surprise_level": "divergence between predicted and actual perceptual state",
    # dmn_imagination
    "observations": "the flow rate of DMN sensory observations",
    "stimmung_stance": "whether the system's attunement state has shifted",
    # input_activity
    "active_state": "whether physical keyboard and mouse input is occurring",
    "idle_duration": "how long since the last physical input event",
    # apperception
    "trigger_novelty": "the rate of self-model cascade triggers",
    "valence_diversity": "the variety of self-model dimensions being observed",
    # voice_state
    "session_active": "whether a voice conversation session is in progress",
    "turn_phase": "the current phase of the conversational turn",
}

# Component descriptions: what each S1 component monitors
_COMPONENT_DESCRIPTIONS: dict[str, str] = {
    "affordance_pipeline": "the recruitment pipeline's selection dynamics",
    "visual_chain": "the visual expression compositor",
    "dmn_pulse": "the default mode network's sensory monitoring",
    "ir_presence": "infrared presence and motion detection",
    "contact_mic": "desk vibration and physical engagement sensing",
    "stimmung": "the system's overall attunement and health state",
    "content_resolver": "content resolution and visual surface generation",
    "salience_router": "conversational salience and concern matching",
    "temporal_bands": "temporal context prediction and surprise detection",
    "dmn_imagination": "the imagination generation loop",
    "input_activity": "physical keyboard and mouse input monitoring",
    "apperception": "the self-model cascade and coherence tracking",
    "voice_state": "voice conversation session state",
}


def _build_exploration_narrative(
    component: str, action: ExplorationAction, signal: ExplorationSignal
) -> str:
    """Build a semantically meaningful narrative for an exploration impingement.

    The narrative is what gets embedded for Qdrant cosine similarity against
    affordance descriptions. It should convey what the component is experiencing
    and why the exploration signal fired.
    """
    comp_desc = _COMPONENT_DESCRIPTIONS.get(component, component)
    edge_desc = _EDGE_DESCRIPTIONS.get(signal.max_novelty_edge or "", signal.max_novelty_edge or "")

    if action.mode == ExplorationMode.DIRECTED:
        return (
            f"{comp_desc} is habituated to routine inputs but drawn to "
            f"a surprising change in {edge_desc}"
        )
    elif action.mode == ExplorationMode.UNDIRECTED:
        return (
            f"{comp_desc} has become monotonous with no novel stimulus — "
            f"all inputs are predictable and interest is evaporating"
        )
    elif action.mode == ExplorationMode.FOCUSED:
        return (
            f"{comp_desc} is engaged but noticing an unexpected shift in "
            f"{edge_desc} that warrants closer attention"
        )
    return f"{comp_desc} exploration signal"


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
            "narrative": _build_exploration_narrative(component, action, signal),
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

    def state_dict(self) -> dict:
        """Serialize tracker state for persistence across restarts."""
        return {
            "component": self.component,
            "habituation": {
                "weights": dict(self.habituation._weights),
                "edge_mean": dict(self.habituation._edge_mean),
                "edge_m2": dict(self.habituation._edge_m2),
                "edge_n": dict(self.habituation._edge_n),
            },
            "interest": {
                "last_value": {k: v for k, v in self.interest._last_value.items()},
                "time_unchanged": dict(self.interest._time_unchanged),
            },
            "learning": {
                "chronic_error": self.learning._chronic_error,
                "prev_chronic": self.learning._prev_chronic,
                "initialized": self.learning._initialized,
            },
            "coherence": {
                "dwell": self.coherence._dwell,
            },
        }

    def load_state_dict(self, state: dict) -> None:
        """Restore tracker state from a persisted state dict."""
        if hab := state.get("habituation"):
            for edge, w in hab.get("weights", {}).items():
                if edge in self.habituation._weights:
                    self.habituation._weights[edge] = w
            for edge, v in hab.get("edge_mean", {}).items():
                if edge in self.habituation._edge_mean:
                    self.habituation._edge_mean[edge] = v
            for edge, v in hab.get("edge_m2", {}).items():
                if edge in self.habituation._edge_m2:
                    self.habituation._edge_m2[edge] = v
            for edge, v in hab.get("edge_n", {}).items():
                if edge in self.habituation._edge_n:
                    self.habituation._edge_n[edge] = v
        if intr := state.get("interest"):
            for trace, v in intr.get("time_unchanged", {}).items():
                if trace in self.interest._time_unchanged:
                    self.interest._time_unchanged[trace] = v
            for trace, v in intr.get("last_value", {}).items():
                if trace in self.interest._last_value:
                    self.interest._last_value[trace] = v
        if lrn := state.get("learning"):
            self.learning._chronic_error = lrn.get("chronic_error", 0.0)
            self.learning._prev_chronic = lrn.get("prev_chronic", 0.0)
            self.learning._initialized = lrn.get("initialized", False)
        if coh := state.get("coherence"):
            self.coherence._dwell = coh.get("dwell", 0.0)

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
