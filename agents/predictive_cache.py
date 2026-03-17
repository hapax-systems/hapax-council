"""Predictive pre-computation cache for visual layer transitions.

Uses protention predictions to pre-compute likely next visual states.
When a predicted transition actually happens, the aggregator can apply
the cached ambient params immediately — reducing perceived latency from
one tick interval to near-zero.

Pure logic, no I/O. The aggregator feeds predictions in and checks for
matches on each tick.
"""

from __future__ import annotations

import time

from pydantic import BaseModel

from agents.protention_engine import ProtentionSnapshot, TransitionPrediction
from agents.visual_layer_state import AmbientParams, DisplayState, DisplayStateMachine

# ── Cached Scenario ──────────────────────────────────────────────────────────


class CachedScenario(BaseModel):
    """A pre-computed visual state for a predicted transition."""

    prediction: TransitionPrediction
    ambient_params: AmbientParams
    display_state_hint: str  # expected display state if this scenario triggers
    created_at: float = 0.0
    ttl_s: float = 30.0  # expire after this many seconds

    @property
    def expired(self) -> bool:
        return (time.monotonic() - self.created_at) > self.ttl_s if self.created_at > 0 else False


# ── Predictive Cache ─────────────────────────────────────────────────────────


class PredictiveCache:
    """Maintains pre-computed visual states for likely near-future transitions.

    Usage:
        1. After compute_and_write(), call precompute() with current protention
        2. On next tick, call match() with current perception to check for hits
        3. If hit, apply cached ambient params before full state computation

    Cache is small (max 3 scenarios) and short-lived (30s TTL).
    """

    def __init__(self) -> None:
        self._scenarios: list[CachedScenario] = []
        self._hits: int = 0
        self._misses: int = 0

    def precompute(
        self,
        protention: ProtentionSnapshot,
        current_flow: float,
        current_audio: float,
        stimmung_stance: str = "nominal",
        now: float | None = None,
    ) -> None:
        """Pre-compute visual states for top protention predictions.

        Only caches predictions with p >= 0.4 (worth pre-computing).
        """
        if now is None:
            now = time.monotonic()

        self._scenarios = []  # replace, don't accumulate

        for pred in protention.top_predictions:
            if pred.probability < 0.4:
                continue

            # Simulate the predicted scenario's ambient params
            scenario_params = self._simulate_ambient(
                pred, current_flow, current_audio, stimmung_stance
            )
            if scenario_params is None:
                continue

            self._scenarios.append(
                CachedScenario(
                    prediction=pred,
                    ambient_params=scenario_params,
                    display_state_hint=self._predict_display_state(pred, current_flow),
                    created_at=now,
                    ttl_s=min(pred.expected_in_s * 1.5, 60.0),  # TTL scales with prediction horizon
                )
            )

    def match(
        self,
        flow_score: float,
        activity: str,
        heart_rate: int = 0,
    ) -> CachedScenario | None:
        """Check if current state matches any cached prediction.

        Returns the best matching scenario, or None.
        Expired scenarios are pruned.
        """
        # Prune expired
        self._scenarios = [s for s in self._scenarios if not s.expired]

        if not self._scenarios:
            return None

        flow_state = "active" if flow_score >= 0.6 else ("warming" if flow_score >= 0.3 else "idle")

        for scenario in self._scenarios:
            pred = scenario.prediction

            if pred.dimension == "flow":
                if pred.predicted_value == "flow_ending" and flow_state != "active":
                    self._hits += 1
                    return scenario
                if pred.predicted_value == "flow_continuing" and flow_state == "active":
                    self._hits += 1
                    return scenario

            elif pred.dimension == "activity" or pred.dimension == "circadian":
                if activity == pred.predicted_value:
                    self._hits += 1
                    return scenario

        self._misses += 1
        return None

    @property
    def hit_rate(self) -> float:
        """Cache hit rate. 0.0 if no lookups yet."""
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    @property
    def cached_count(self) -> int:
        return len(self._scenarios)

    def _simulate_ambient(
        self,
        pred: TransitionPrediction,
        current_flow: float,
        current_audio: float,
        stimmung_stance: str,
    ) -> AmbientParams | None:
        """Compute what ambient params would look like if this prediction comes true."""
        # Simulate the predicted flow/activity state
        if pred.dimension == "flow":
            if pred.predicted_value in ("flow_ending", "flow_breaking"):
                sim_flow = 0.1  # flow ended
                sim_severity = 0.0
            elif pred.predicted_value in ("flow_continuing", "flow_likely"):
                sim_flow = 0.7  # deep flow
                sim_severity = 0.0
            else:
                return None
        elif pred.dimension == "activity":
            # Activity change doesn't directly affect ambient much
            sim_flow = current_flow
            sim_severity = 0.0
        elif pred.dimension == "circadian":
            sim_flow = current_flow
            sim_severity = 0.0
        else:
            return None

        # Use a temporary state machine to compute params
        sm = DisplayStateMachine()
        params = sm._compute_ambient_params(
            max_severity=sim_severity,
            flow_score=sim_flow,
            audio_energy=current_audio,
            stimmung_stance=stimmung_stance,
        )
        return params

    @staticmethod
    def _predict_display_state(pred: TransitionPrediction, current_flow: float) -> str:
        """Predict the likely display state after a transition."""
        if pred.dimension == "flow":
            if pred.predicted_value in ("flow_ending", "flow_breaking"):
                return DisplayState.PERIPHERAL  # signals may appear as flow breaks
            if pred.predicted_value in ("flow_continuing", "flow_likely"):
                return DisplayState.AMBIENT  # deep flow = ambient
        return DisplayState.AMBIENT
