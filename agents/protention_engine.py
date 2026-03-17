"""Protention engine — statistical transition probability model.

Learns activity/flow/physiological transition patterns from accumulated
perception history. Produces predictions about likely next states without
LLM calls — pure statistics from observed patterns.

Three prediction sources:
  1. Activity Markov chain — P(next_activity | current_activity)
  2. Flow state transitions — empirical half-life and transition timing
  3. Circadian patterns — time-of-day baselines for activity/flow/HR

Used by: temporal_bands.py (replaces simple trend-based protention),
         visual_layer_aggregator.py (predictive pre-computation),
         content_scheduler.py (anticipatory content selection).
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

log = logging.getLogger("protention_engine")


# ── Prediction Models ────────────────────────────────────────────────────────


class TransitionPrediction(BaseModel, frozen=True):
    """A predicted state transition."""

    dimension: str  # activity | flow | heart_rate | audio
    predicted_value: str  # the predicted next state/value
    probability: float  # 0.0-1.0
    expected_in_s: float  # seconds until transition expected
    basis: str  # human-readable explanation


class ProtentionSnapshot(BaseModel):
    """Complete set of predictions for the near future."""

    predictions: list[TransitionPrediction] = Field(default_factory=list)
    timestamp: float = 0.0
    observation_count: int = 0  # how many transitions the model has seen

    @property
    def top_predictions(self) -> list[TransitionPrediction]:
        """Top 3 predictions by probability, filtered to p >= 0.3."""
        return sorted(
            [p for p in self.predictions if p.probability >= 0.3],
            key=lambda p: p.probability,
            reverse=True,
        )[:3]


# ── Markov Chain ─────────────────────────────────────────────────────────────


class MarkovChain:
    """First-order Markov chain with count-based transition probabilities.

    Tracks transitions between discrete states. Computes P(next | current)
    with Laplace smoothing to avoid zero probabilities for unseen transitions.
    """

    def __init__(self, smoothing: float = 0.1) -> None:
        self._counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._totals: dict[str, int] = defaultdict(int)
        self._smoothing = smoothing
        self._states: set[str] = set()

    def observe(self, from_state: str, to_state: str) -> None:
        """Record an observed transition."""
        self._counts[from_state][to_state] += 1
        self._totals[from_state] += 1
        self._states.add(from_state)
        self._states.add(to_state)

    def predict(self, current: str) -> list[tuple[str, float]]:
        """Return predicted next states with probabilities, sorted by probability.

        Returns at most 3 predictions. Uses Laplace smoothing.
        """
        if current not in self._counts:
            return []

        transitions = self._counts[current]
        total = self._totals[current]
        n_states = max(1, len(self._states))
        smoothed_total = total + self._smoothing * n_states

        results: list[tuple[str, float]] = []
        for state in self._states:
            count = transitions.get(state, 0)
            prob = (count + self._smoothing) / smoothed_total
            if prob > 0.05:  # skip negligible
                results.append((state, round(prob, 3)))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:3]

    @property
    def total_observations(self) -> int:
        return sum(self._totals.values())

    def to_dict(self) -> dict[str, Any]:
        """Serialize for persistence."""
        return {
            "counts": {k: dict(v) for k, v in self._counts.items()},
            "totals": dict(self._totals),
            "states": sorted(self._states),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], smoothing: float = 0.1) -> MarkovChain:
        """Deserialize from persistence."""
        chain = cls(smoothing=smoothing)
        for from_state, transitions in data.get("counts", {}).items():
            for to_state, count in transitions.items():
                chain._counts[from_state][to_state] = count
                chain._totals[from_state] += count
                chain._states.add(from_state)
                chain._states.add(to_state)
        return chain


# ── Flow Timing Model ────────────────────────────────────────────────────────


class FlowTimingModel:
    """Tracks how long flow states last and predicts transition timing.

    Records flow session durations and computes empirical statistics.
    """

    def __init__(self) -> None:
        self._session_durations: list[float] = []  # seconds
        self._current_session_start: float | None = None
        self._current_state: str = "idle"
        self._max_history = 50

    def observe(self, flow_state: str, now: float | None = None) -> None:
        """Record a flow state observation."""
        if now is None:
            now = time.monotonic()

        if flow_state != self._current_state:
            # State changed — record duration of previous state
            if self._current_session_start is not None and self._current_state == "active":
                duration = now - self._current_session_start
                if duration > 5.0:  # ignore sub-5s blips
                    self._session_durations.append(duration)
                    if len(self._session_durations) > self._max_history:
                        self._session_durations.pop(0)

            self._current_session_start = now
            self._current_state = flow_state

    def predict_remaining(self, current_state: str, elapsed_s: float) -> float | None:
        """Predict seconds remaining in current flow state.

        Returns None if insufficient data. Uses exponential survival model.
        """
        if current_state != "active" or len(self._session_durations) < 3:
            return None

        # Median duration as expected session length
        sorted_durations = sorted(self._session_durations)
        median = sorted_durations[len(sorted_durations) // 2]

        # Survival probability: P(still in flow | already elapsed)
        # Simple exponential: remaining ≈ median - elapsed, floor at 0
        remaining = max(0.0, median - elapsed_s)
        return round(remaining, 0)

    @property
    def median_duration(self) -> float | None:
        """Median flow session duration, or None if insufficient data."""
        if len(self._session_durations) < 3:
            return None
        sorted_d = sorted(self._session_durations)
        return sorted_d[len(sorted_d) // 2]

    def to_dict(self) -> dict[str, Any]:
        return {"session_durations": self._session_durations}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FlowTimingModel:
        model = cls()
        model._session_durations = data.get("session_durations", [])
        return model


# ── Circadian Model ──────────────────────────────────────────────────────────


class CircadianModel:
    """Time-of-day baselines for activity patterns.

    Bins observations into hourly buckets. After enough data, predicts
    the typical activity/flow/HR for any hour of the day.
    """

    def __init__(self) -> None:
        # hour → {activity: count}
        self._activity_by_hour: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._flow_by_hour: dict[int, list[float]] = defaultdict(list)
        self._max_per_hour = 100

    def observe(self, hour: int, activity: str, flow_score: float) -> None:
        """Record an hourly observation."""
        self._activity_by_hour[hour][activity] += 1
        scores = self._flow_by_hour[hour]
        scores.append(flow_score)
        if len(scores) > self._max_per_hour:
            scores.pop(0)

    def typical_activity(self, hour: int) -> str | None:
        """Most common activity at this hour, or None if insufficient data."""
        counts = self._activity_by_hour.get(hour, {})
        if not counts or sum(counts.values()) < 5:
            return None
        return max(counts, key=counts.get)  # type: ignore[arg-type]

    def typical_flow(self, hour: int) -> float | None:
        """Mean flow score at this hour, or None if insufficient data."""
        scores = self._flow_by_hour.get(hour, [])
        if len(scores) < 5:
            return None
        return round(sum(scores) / len(scores), 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "activity_by_hour": {str(k): dict(v) for k, v in self._activity_by_hour.items()},
            "flow_by_hour": {str(k): v for k, v in self._flow_by_hour.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CircadianModel:
        model = cls()
        for hour_str, counts in data.get("activity_by_hour", {}).items():
            hour = int(hour_str)
            for activity, count in counts.items():
                model._activity_by_hour[hour][activity] = count
        for hour_str, scores in data.get("flow_by_hour", {}).items():
            model._flow_by_hour[int(hour_str)] = scores
        return model


# ── Protention Engine ────────────────────────────────────────────────────────

PROTENTION_STATE_PATH = Path.home() / ".cache" / "hapax-voice" / "protention-state.json"


class ProtentionEngine:
    """Statistical protention engine — learns and predicts from perception history.

    Three sub-models:
      - Activity Markov chain: P(next_activity | current_activity)
      - Flow timing: empirical session durations → predict remaining time
      - Circadian baselines: typical patterns by hour of day

    All updates are O(1). Predictions are O(states). No LLM calls.
    Persists learned state to disk for cross-session learning.
    """

    def __init__(self) -> None:
        self._activity_chain = MarkovChain()
        self._flow_timing = FlowTimingModel()
        self._circadian = CircadianModel()
        self._last_activity: str = ""
        self._last_flow_state: str = "idle"
        self._flow_session_start: float = 0.0

    def observe(
        self,
        activity: str,
        flow_score: float,
        hour: int,
        now: float | None = None,
    ) -> None:
        """Feed a perception snapshot to all sub-models.

        Call this every perception tick (~2.5s). O(1) per call.
        """
        if now is None:
            now = time.monotonic()

        # Activity transitions
        if activity and activity != self._last_activity and self._last_activity:
            self._activity_chain.observe(self._last_activity, activity)
        if activity:
            self._last_activity = activity

        # Flow state
        flow_state = "active" if flow_score >= 0.6 else ("warming" if flow_score >= 0.3 else "idle")
        if flow_state != self._last_flow_state:
            if flow_state == "active":
                self._flow_session_start = now
            self._flow_timing.observe(flow_state, now)
            self._last_flow_state = flow_state

        # Circadian
        self._circadian.observe(hour, activity or "idle", flow_score)

    def predict(
        self,
        current_activity: str,
        flow_score: float,
        hour: int,
        now: float | None = None,
    ) -> ProtentionSnapshot:
        """Generate predictions based on current state and learned patterns."""
        if now is None:
            now = time.monotonic()

        predictions: list[TransitionPrediction] = []

        # 1. Activity transitions from Markov chain
        activity_preds = self._activity_chain.predict(current_activity)
        for next_activity, prob in activity_preds:
            if next_activity == current_activity:
                continue  # skip self-transitions (staying)
            predictions.append(
                TransitionPrediction(
                    dimension="activity",
                    predicted_value=next_activity,
                    probability=prob,
                    expected_in_s=120.0,  # default: ~2 min
                    basis=f"after {current_activity}, {next_activity} observed {prob:.0%}",
                )
            )

        # 2. Flow session timing
        flow_state = "active" if flow_score >= 0.6 else ("warming" if flow_score >= 0.3 else "idle")
        if flow_state == "active" and self._flow_session_start > 0:
            elapsed = now - self._flow_session_start
            remaining = self._flow_timing.predict_remaining("active", elapsed)
            if remaining is not None:
                median = self._flow_timing.median_duration
                if remaining < 300:  # less than 5 min remaining
                    predictions.append(
                        TransitionPrediction(
                            dimension="flow",
                            predicted_value="flow_ending",
                            probability=min(0.8, 0.4 + (elapsed / (median or 3600)) * 0.4),
                            expected_in_s=remaining,
                            basis=f"flow session {elapsed / 60:.0f}min "
                            f"(typical: {(median or 0) / 60:.0f}min)",
                        )
                    )
                elif elapsed > 120:
                    # Still in flow, predict continuation
                    predictions.append(
                        TransitionPrediction(
                            dimension="flow",
                            predicted_value="flow_continuing",
                            probability=0.7,
                            expected_in_s=remaining,
                            basis=f"flow session {elapsed / 60:.0f}min, "
                            f"~{remaining / 60:.0f}min remaining",
                        )
                    )

        # 3. Circadian predictions
        typical_activity = self._circadian.typical_activity(hour)
        if typical_activity and typical_activity != current_activity:
            predictions.append(
                TransitionPrediction(
                    dimension="circadian",
                    predicted_value=typical_activity,
                    probability=0.4,  # circadian is suggestive, not deterministic
                    expected_in_s=600.0,  # ~10 min horizon
                    basis=f"at {hour}:00, typically {typical_activity}",
                )
            )

        typical_flow = self._circadian.typical_flow(hour)
        if typical_flow is not None:
            if typical_flow >= 0.5 and flow_score < 0.3:
                predictions.append(
                    TransitionPrediction(
                        dimension="circadian",
                        predicted_value="flow_likely",
                        probability=0.35,
                        expected_in_s=900.0,
                        basis=f"at {hour}:00, flow typically {typical_flow:.1f}",
                    )
                )

        return ProtentionSnapshot(
            predictions=predictions,
            timestamp=now,
            observation_count=self._activity_chain.total_observations,
        )

    def save(self, path: Path | None = None) -> None:
        """Persist learned state to disk."""
        path = path or PROTENTION_STATE_PATH
        data = {
            "activity_chain": self._activity_chain.to_dict(),
            "flow_timing": self._flow_timing.to_dict(),
            "circadian": self._circadian.to_dict(),
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.rename(path)
        except OSError:
            log.debug("Failed to save protention state", exc_info=True)

    def load(self, path: Path | None = None) -> bool:
        """Load previously learned state. Returns True if loaded."""
        path = path or PROTENTION_STATE_PATH
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._activity_chain = MarkovChain.from_dict(data.get("activity_chain", {}))
            self._flow_timing = FlowTimingModel.from_dict(data.get("flow_timing", {}))
            self._circadian = CircadianModel.from_dict(data.get("circadian", {}))
            log.info(
                "Loaded protention state: %d activity transitions",
                self._activity_chain.total_observations,
            )
            return True
        except (OSError, json.JSONDecodeError, KeyError):
            return False
