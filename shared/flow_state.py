"""shared/flow_state.py — Flow state machine for studio production sessions.

States: idle → warming-up → active → flow → winding-down → idle

Transitions are driven by composite scoring from multiple signals:
  - WatchBackend HR/HRV (physiological engagement)
  - HSEmotion valence/arousal (emotional state)
  - Audio energy / CLAP activity (production activity)
  - Session duration (time in current state)

5-minute hysteresis prevents rapid state oscillation.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum

log = logging.getLogger(__name__)

# Hysteresis: minimum time before state can change
HYSTERESIS_SECONDS = 300.0  # 5 minutes

# Score thresholds for state transitions
WARMING_THRESHOLD = 0.2
ACTIVE_THRESHOLD = 0.4
FLOW_THRESHOLD = 0.7
WINDING_THRESHOLD = 0.3


class FlowState(Enum):
    """Studio session flow states."""

    IDLE = "idle"
    WARMING_UP = "warming-up"
    ACTIVE = "active"
    FLOW = "flow"
    WINDING_DOWN = "winding-down"


@dataclass
class FlowSignals:
    """Input signals for flow state computation."""

    # From WatchBackend
    heart_rate_bpm: int = 0
    hrv_rmssd_ms: float = 0.0
    physiological_load: float = 0.0

    # From HSEmotion (via StudioIngestionBackend)
    emotion_valence: float = 0.0
    emotion_arousal: float = 0.0

    # From StudioIngestionBackend
    production_activity: str = "idle"
    audio_energy_rms: float = 0.0
    flow_state_score: float = 0.0

    # Session timing
    session_duration_minutes: float = 0.0


@dataclass
class FlowTransition:
    """Record of a state transition."""

    from_state: FlowState
    to_state: FlowState
    timestamp: float
    composite_score: float
    reason: str


class FlowStateMachine:
    """Manages flow state transitions with hysteresis.

    The machine consumes FlowSignals and produces state transitions.
    Hysteresis prevents oscillation: a state must be held for
    HYSTERESIS_SECONDS before a transition is allowed.
    """

    def __init__(self, hysteresis_s: float = HYSTERESIS_SECONDS) -> None:
        self._state = FlowState.IDLE
        self._hysteresis_s = hysteresis_s
        self._last_transition: float = 0.0
        self._history: list[FlowTransition] = []

    @property
    def state(self) -> FlowState:
        return self._state

    @property
    def history(self) -> list[FlowTransition]:
        return list(self._history)

    @property
    def time_in_state(self) -> float:
        """Seconds since last transition."""
        if self._last_transition == 0.0:
            return 0.0
        return time.monotonic() - self._last_transition

    def compute_composite_score(self, signals: FlowSignals) -> float:
        """Compute a composite flow score from all input signals.

        Returns a float in [0.0, 1.0].
        """
        score = 0.0

        # Production activity is the strongest signal
        if signals.production_activity == "production":
            score += 0.35
        elif signals.production_activity == "conversation":
            score += 0.10

        # CLAP-derived flow score
        score += 0.20 * signals.flow_state_score

        # Audio energy (above noise floor)
        if signals.audio_energy_rms > 0.01:
            score += 0.10

        # Physiological engagement (elevated HR, low HRV = focused)
        if signals.heart_rate_bpm > 75:
            score += 0.10
        if signals.physiological_load > 0.3:
            score += 0.05

        # Emotional state (positive valence + high arousal = engaged)
        if signals.emotion_valence > 0.2:
            score += 0.05
        if signals.emotion_arousal > 0.3:
            score += 0.05

        # Session momentum (longer sessions build flow)
        if signals.session_duration_minutes > 15:
            score += 0.05
        if signals.session_duration_minutes > 45:
            score += 0.05

        return min(1.0, score)

    def update(self, signals: FlowSignals) -> FlowState:
        """Update the flow state based on current signals.

        Returns the (possibly new) state. Respects hysteresis.
        """
        now = time.monotonic()
        score = self.compute_composite_score(signals)

        # Check hysteresis
        if self._last_transition > 0 and (now - self._last_transition) < self._hysteresis_s:
            return self._state

        new_state = self._compute_target_state(score)

        if new_state != self._state:
            transition = FlowTransition(
                from_state=self._state,
                to_state=new_state,
                timestamp=now,
                composite_score=score,
                reason=self._transition_reason(score, new_state),
            )
            self._history.append(transition)
            log.info(
                "Flow: %s → %s (score=%.2f, reason=%s)",
                self._state.value,
                new_state.value,
                score,
                transition.reason,
            )
            self._state = new_state
            self._last_transition = now

        return self._state

    def _compute_target_state(self, score: float) -> FlowState:
        """Determine target state from score, respecting valid transitions."""
        if score >= FLOW_THRESHOLD:
            # Can only enter flow from active
            if self._state in (FlowState.ACTIVE, FlowState.FLOW):
                return FlowState.FLOW
            return FlowState.ACTIVE
        elif score >= ACTIVE_THRESHOLD:
            if self._state == FlowState.FLOW:
                return FlowState.WINDING_DOWN
            return FlowState.ACTIVE
        elif score >= WARMING_THRESHOLD:
            if self._state in (FlowState.ACTIVE, FlowState.FLOW):
                return FlowState.WINDING_DOWN
            return FlowState.WARMING_UP
        else:
            if self._state in (FlowState.ACTIVE, FlowState.FLOW):
                return FlowState.WINDING_DOWN
            return FlowState.IDLE

    def _transition_reason(self, score: float, target: FlowState) -> str:
        if target == FlowState.FLOW:
            return f"high_engagement(score={score:.2f})"
        elif target == FlowState.ACTIVE:
            return f"production_detected(score={score:.2f})"
        elif target == FlowState.WARMING_UP:
            return f"activity_starting(score={score:.2f})"
        elif target == FlowState.WINDING_DOWN:
            return f"engagement_declining(score={score:.2f})"
        else:
            return f"idle(score={score:.2f})"

    def reset(self) -> None:
        """Reset to idle state."""
        self._state = FlowState.IDLE
        self._last_transition = 0.0
        self._history.clear()
