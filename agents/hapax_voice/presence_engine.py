"""Bayesian presence engine — probabilistic operator presence via signal fusion.

Replaces rule-based PresenceDetector.score with a Bayesian posterior that
fuses all available perception signals. Uses temporal hysteresis to prevent
oscillation between PRESENT/AWAY states.

Registered as a PerceptionBackend; provides `presence_probability` (float)
and `presence_state` (str: PRESENT/UNCERTAIN/AWAY).
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any

from agents.hapax_voice.perception import PerceptionTier
from agents.hapax_voice.primitives import Behavior

log = logging.getLogger(__name__)

# Calibrated from first live run (2026-03-17):
# - operator_face P(no_face|present) was 0.05, far too low — operator frequently
#   not visible (turned away, under desk, out of frame). Raised to 0.10.
# - vad_speech P(speech|present) lowered — silent work is common, mic often off.
DEFAULT_SIGNAL_WEIGHTS: dict[str, tuple[float, float]] = {
    "operator_face": (0.90, 0.10),
    "keyboard_active": (0.85, 0.05),
    "vad_speech": (0.60, 0.15),
    "speaker_is_operator": (0.95, 0.02),
    "watch_hr": (0.80, 0.30),
    "watch_connected": (0.70, 0.40),
    "desktop_active": (0.75, 0.10),
    "midi_active": (0.90, 0.02),
    "bt_phone_connected": (0.95, 0.05),  # BT paired phone in range = very strong presence
    "phone_kde_connected": (0.80, 0.25),  # KDE Connect WiFi reachable = likely in house
    "room_occupancy": (0.85, 0.20),  # person detected on any camera = strong presence signal
    "ir_person_detected": (0.90, 0.10),  # lighting-invariant IR detection from Pi NoIR
}


class PresenceEngine:
    """Bayesian presence fusion engine with hysteresis state machine.

    Consumes Behaviors from other perception backends and produces a
    posterior probability of operator presence plus a discrete state.

    States:
        PRESENT:   posterior >= enter_threshold sustained for enter_ticks
        UNCERTAIN: posterior between exit_threshold and enter_threshold
        AWAY:      posterior < exit_threshold sustained for exit_ticks
    """

    def __init__(
        self,
        prior: float = 0.5,
        enter_threshold: float = 0.7,
        exit_threshold: float = 0.3,
        enter_ticks: int = 2,
        exit_ticks: int = 24,
        signal_weights: dict[str, tuple[float, float]] | None = None,
    ) -> None:
        self._prior = prior
        self._enter_threshold = enter_threshold
        self._exit_threshold = exit_threshold
        self._enter_ticks = enter_ticks
        self._exit_ticks = exit_ticks
        self._signal_weights = signal_weights or DEFAULT_SIGNAL_WEIGHTS

        # State
        self._last_posterior: float = prior
        self._state: str = "UNCERTAIN"
        self._ticks_in_candidate_state: int = 0
        self._candidate_state: str | None = None

        # Decay: posterior drifts toward prior when no signals update
        self._decay_rate: float = 0.02  # per tick

        # Behaviors we provide
        self._b_probability: Behavior[float] = Behavior(prior)
        self._b_state: Behavior[str] = Behavior("UNCERTAIN")

        # Diagnostics ring buffer
        self._history: deque[dict[str, Any]] = deque(maxlen=100)
        self._event_log: Any | None = None

    def set_event_log(self, event_log: Any) -> None:
        self._event_log = event_log

    # -- PerceptionBackend protocol --

    @property
    def name(self) -> str:
        return "presence_engine"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"presence_probability", "presence_state"})

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.FAST

    def available(self) -> bool:
        return True

    def start(self) -> None:
        log.info(
            "Bayesian presence engine started (prior=%.2f, enter=%.2f, exit=%.2f)",
            self._prior,
            self._enter_threshold,
            self._exit_threshold,
        )

    def stop(self) -> None:
        log.info("Bayesian presence engine stopped")

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        """Read signals from behaviors dict and update posterior + state."""
        now = time.monotonic()

        # Read signals from other backends' behaviors
        signal_observations = self._read_signals(behaviors)

        # Compute posterior via likelihood ratios
        posterior = self._compute_posterior(signal_observations)

        # Update state machine with hysteresis
        old_state = self._state
        self._update_state_machine(posterior)

        # Store diagnostics
        tick_record = {
            "t": now,
            "posterior": posterior,
            "state": self._state,
            "signals": signal_observations,
        }
        self._history.append(tick_record)

        if self._state != old_state:
            log.info(
                "PRESENCE state %s → %s (posterior=%.3f)",
                old_state,
                self._state,
                posterior,
            )
            if self._event_log is not None:
                self._event_log.emit(
                    "presence_bayesian_transition",
                    **{
                        "from": old_state,
                        "to": self._state,
                        "posterior": round(posterior, 4),
                        "signals": {k: v for k, v in signal_observations.items() if v is not None},
                    },
                )
        else:
            log.debug(
                "PRESENCE tick: state=%s posterior=%.3f signals=%s",
                self._state,
                posterior,
                {k: v for k, v in signal_observations.items() if v is not None},
            )

        self._last_posterior = posterior
        self._b_probability.update(posterior, now)
        self._b_state.update(self._state, now)

        behaviors["presence_probability"] = self._b_probability
        behaviors["presence_state"] = self._b_state

    # -- Internal --

    def _read_signals(self, behaviors: dict[str, Behavior]) -> dict[str, bool | None]:
        """Map perception behaviors to binary signal observations."""
        obs: dict[str, bool | None] = {}

        # Operator face visible (from presence detector via fused detection)
        # Three states: True (operator matched), False (no face at all), None (face detected
        # but not matched — ambiguous, could be stale embedding or bad angle)
        op_visible = behaviors.get("operator_visible")
        face_detected = behaviors.get("face_detected")
        if op_visible is not None and op_visible.value:
            obs["operator_face"] = True
        elif face_detected is not None and face_detected.value:
            obs["operator_face"] = None  # face seen but not matched — neutral
        elif face_detected is not None and not face_detected.value:
            obs["operator_face"] = False  # no face at all
        else:
            obs["operator_face"] = None

        # Keyboard/mouse active
        b = behaviors.get("input_active")
        obs["keyboard_active"] = b.value if b is not None else None

        # VAD speech (convert float confidence to bool)
        b = behaviors.get("vad_confidence")
        if b is not None:
            obs["vad_speech"] = b.value > 0.5 if isinstance(b.value, (int, float)) else None
        else:
            obs["vad_speech"] = None

        # Speaker identified as operator
        b = behaviors.get("speaker_is_operator")
        obs["speaker_is_operator"] = b.value if b is not None else None

        # Watch heart rate > 0 (0 bpm = not connected, treat as missing)
        b = behaviors.get("heart_rate_bpm")
        if b is not None and isinstance(b.value, (int, float)) and b.value > 0:
            obs["watch_hr"] = True
        else:
            obs["watch_hr"] = None  # no data = neutral, not negative

        # Watch connected
        b = behaviors.get("watch_connected")
        obs["watch_connected"] = b.value if b is not None else None

        # Desktop activity (window focus changed recently)
        b = behaviors.get("desktop_active")
        obs["desktop_active"] = b.value if b is not None else None

        # Bluetooth phone presence (paired, connected = in room)
        b = behaviors.get("bt_watch_connected")
        obs["bt_phone_connected"] = b.value if b is not None else None

        # KDE Connect phone reachable (WiFi)
        b = behaviors.get("phone_kde_connected")
        obs["phone_kde_connected"] = b.value if b is not None else None

        # MIDI active
        b = behaviors.get("midi_playing")
        obs["midi_active"] = b.value if b is not None else None

        # Room occupancy from multi-camera person detection
        b = behaviors.get("room_occupancy")
        if b is not None and isinstance(b.value, (int, float)) and b.value >= 1:
            obs["room_occupancy"] = True
        else:
            obs["room_occupancy"] = None  # no data = neutral

        # IR person detected (from Pi NoIR edge cameras)
        b = behaviors.get("ir_person_detected")
        obs["ir_person_detected"] = b.value if b is not None else None

        return obs

    def _compute_posterior(self, observations: dict[str, bool | None]) -> float:
        """Compute Bayesian posterior from likelihood ratios."""
        # Start with odds form of prior (decayed toward 0.5)
        prior = self._last_posterior
        # Decay toward base prior
        prior = prior + (self._prior - prior) * self._decay_rate
        # Clamp to avoid log(0)
        prior = max(0.001, min(0.999, prior))

        # Convert to odds
        odds = prior / (1.0 - prior)

        for signal_name, (p_present, p_absent) in self._signal_weights.items():
            observed = observations.get(signal_name)
            if observed is None:
                continue  # Missing sensor → neutral

            if observed:
                # Signal is True: likelihood ratio = P(signal|present) / P(signal|absent)
                lr = p_present / p_absent
            else:
                # Signal is False: likelihood ratio = P(¬signal|present) / P(¬signal|absent)
                lr = (1.0 - p_present) / (1.0 - p_absent)

            odds *= lr

        # Convert odds back to probability
        posterior = odds / (odds + 1.0)
        return max(0.0, min(1.0, posterior))

    def _update_state_machine(self, posterior: float) -> None:
        """Update hysteresis state machine based on posterior."""
        # Determine what state the posterior is pointing toward
        if posterior >= self._enter_threshold:
            target = "PRESENT"
        elif posterior < self._exit_threshold:
            target = "AWAY"
        else:
            target = "UNCERTAIN"

        # Count ticks toward transition
        if target != self._state:
            if target == self._candidate_state:
                self._ticks_in_candidate_state += 1
            else:
                self._candidate_state = target
                self._ticks_in_candidate_state = 1

            # Check if sustained long enough to transition
            required_ticks = self._required_ticks_for_transition(self._state, target)
            if self._ticks_in_candidate_state >= required_ticks:
                self._state = target
                self._candidate_state = None
                self._ticks_in_candidate_state = 0
        else:
            # Already in target state — reset candidate tracking
            self._candidate_state = None
            self._ticks_in_candidate_state = 0

    def _required_ticks_for_transition(self, from_state: str, to_state: str) -> int:
        """How many sustained ticks needed to transition between states."""
        if from_state == "PRESENT" and to_state in ("UNCERTAIN", "AWAY"):
            return self._exit_ticks  # 60s to leave PRESENT
        if to_state == "PRESENT":
            return self._enter_ticks  # 5s to enter PRESENT
        # UNCERTAIN transitions
        return 4  # 10s for UNCERTAIN transitions

    # -- Public accessors for diagnostics --

    @property
    def state(self) -> str:
        return self._state

    @property
    def posterior(self) -> float:
        return self._last_posterior

    @property
    def history(self) -> list[dict[str, Any]]:
        return list(self._history)
