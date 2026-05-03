"""Bayesian presence engine — probabilistic operator presence via signal fusion.

Replaces rule-based PresenceDetector.score with a Bayesian posterior that
fuses all available perception signals. Uses temporal hysteresis to prevent
oscillation between PRESENT/AWAY states.

Registered as a PerceptionBackend; provides `presence_probability` (float)
and `presence_state` (str: PRESENT/UNCERTAIN/AWAY).

Phase 1 (2026-04-25) — internals refactored to delegate posterior fusion +
hysteresis to the generic ``shared.claim.ClaimEngine[bool]`` shipped in
Phase 0 FULL (#1350). The public PerceptionBackend API + state-name
vocabulary (PRESENT/UNCERTAIN/AWAY) is preserved bit-identically; the
delegation maps to ClaimEngine's ASSERTED/UNCERTAIN/RETRACTED at the
state-translation boundary. ``DEFAULT_SIGNAL_WEIGHTS`` tuples are
auto-converted to ``LRDerivation`` records on construction.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any

from agents.hapax_daimonion.perception import PerceptionTier
from agents.hapax_daimonion.primitives import Behavior
from shared.bayesian_impingement_emitter import emit_state_transition_impingement
from shared.claim import ClaimEngine, ClaimState, LRDerivation, TemporalProfile

log = logging.getLogger(__name__)

# Calibrated from first live run (2026-03-17):
# - operator_face P(no_face|present) was 0.05, far too low — operator frequently
#   not visible (turned away, under desk, out of frame). Raised to 0.10.
# - vad_speech P(speech|present) lowered — silent work is common, mic often off.
# Phase 1 — translate ClaimEngine's generic state vocabulary to the
# PresenceEngine-canonical names that the rest of the system reads.
_ENGINE_STATE_TO_PRESENCE_STATE: dict[ClaimState, str] = {
    "ASSERTED": "PRESENT",
    "UNCERTAIN": "UNCERTAIN",
    "RETRACTED": "AWAY",
}


DEFAULT_SIGNAL_WEIGHTS: dict[str, tuple[float, float]] = {
    "operator_face": (0.90, 0.10),
    "keyboard_active": (0.85, 0.05),
    "vad_speech": (0.85, 0.03),  # Raised from (0.60, 0.15): Blue Yeti speech = strong presence
    "speaker_is_operator": (0.95, 0.02),
    "watch_hr": (0.80, 0.30),
    "watch_connected": (0.70, 0.40),
    "desktop_active": (0.75, 0.10),
    "midi_active": (0.90, 0.02),
    "bt_phone_connected": (0.70, 0.30),  # Linux BLE unreliable; downweighted from (0.95, 0.05)
    "phone_kde_connected": (0.80, 0.25),  # KDE Connect WiFi reachable = likely in house
    "room_occupancy": (0.85, 0.20),  # person detected on any camera = strong presence signal
    "ir_person_detected": (0.90, 0.10),  # lighting-invariant IR detection from Pi NoIR
    "ir_hand_active": (
        0.85,
        0.10,
    ),  # IR hand detection on desk — works even when person detection broken
    "desk_active": (
        0.90,
        0.05,
    ),  # Contact mic desk vibration — typing/tapping/drumming on Cortado MKIII
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

        # Phase 1: delegate posterior + state to generic ClaimEngine[bool].
        # PresenceEngine's _read_signals already converts positive-only
        # signals to None, so the engine sees bidirectional True/False/None
        # observations — ClaimEngine processes False values via the
        # full LR formula (positive_only=False on every record).
        lr_records: dict[str, LRDerivation] = {
            name: LRDerivation(
                signal_name=name,
                claim_name="operator_present",
                source_category="expert_elicitation_shelf",
                p_true_given_h1=p_present,
                p_true_given_h0=p_absent,
                positive_only=False,
                estimation_reference="DEFAULT_SIGNAL_WEIGHTS calibrated 2026-03-17 first live run",
            )
            for name, (p_present, p_absent) in self._signal_weights.items()
        }
        self._engine: ClaimEngine[bool] = ClaimEngine(
            name="operator_present",
            prior=prior,
            temporal_profile=TemporalProfile(
                enter_threshold=enter_threshold,
                exit_threshold=exit_threshold,
                k_enter=enter_ticks,
                k_exit=exit_ticks,
                k_uncertain=4,  # Pre-Phase-1 PresenceEngine constant
            ),
            signal_weights=lr_records,
        )

        # Compatibility shadow state — preserved for diagnostics access.
        # The authoritative state lives in self._engine; these mirror the
        # last-seen values for any caller still reading them directly.
        self._last_posterior: float = prior
        self._state: str = "UNCERTAIN"

        # Retained for backward-compatible field access in tests.
        self._ticks_in_candidate_state: int = 0
        self._candidate_state: str | None = None

        # Decay rate is now owned by ClaimEngine; preserved for caller
        # introspection if any test reads it.
        self._decay_rate: float = 0.02  # per tick

        # Behaviors we provide
        self._b_probability: Behavior[float] = Behavior(prior)
        self._b_state: Behavior[str] = Behavior("UNCERTAIN")

        # Diagnostics ring buffer
        self._history: deque[dict[str, object]] = deque(maxlen=100)
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
            # Audit 3 fix #1: broadcast the transition on the impingement
            # bus so the cosine-similarity recruiter sees a richly-narrated
            # "operator-presence transitioned" event with the actual
            # measured posterior + delta + active signal fingerprint. This
            # is what drives diverse capability recruitment instead of
            # collapsing the posterior to a scalar at the JSON boundary.
            try:
                emit_state_transition_impingement(
                    source="presence_engine",
                    claim_name="operator-presence",
                    from_state=old_state,
                    to_state=self._state,
                    posterior=posterior,
                    prev_posterior=self._last_posterior,
                    active_signals={k: v for k, v in signal_observations.items() if v is not None},
                )
            except Exception:
                log.debug("presence impingement emit failed", exc_info=True)
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

        # Diagnostic: log active signals every 30 ticks (~75s)
        self._diag_counter = getattr(self, "_diag_counter", 0) + 1
        if self._diag_counter >= 30:
            self._diag_counter = 0
            active = {k: v for k, v in signal_observations.items() if v is not None}
            log.info(
                "PRESENCE diag: posterior=%.4f state=%s signals=%s",
                posterior,
                self._state,
                active,
            )

        behaviors["presence_probability"] = self._b_probability
        behaviors["presence_state"] = self._b_state

    # -- Internal --

    def _read_signals(self, behaviors: dict[str, Behavior]) -> dict[str, bool | None]:
        """Map perception behaviors to binary signal observations."""
        obs: dict[str, bool | None] = {}

        # Operator face visible (from presence detector via fused detection)
        # Positive-only signal: face detection is evidence FOR presence, but
        # absence of face is NOT evidence AGAINST (operator looks at screen,
        # is turned away, camera angle wrong, model undertrained).
        op_visible = behaviors.get("operator_visible")
        face_detected = behaviors.get("face_detected")
        if op_visible is not None and op_visible.value:
            obs["operator_face"] = True
        elif face_detected is not None and face_detected.value:
            obs["operator_face"] = None  # face seen but not matched — neutral
        else:
            obs["operator_face"] = None  # no face = neutral, not negative

        # Keyboard/mouse active — from raw evdev (physical devices only).
        # Bypasses logind polluted by virtual input devices (RustDesk UInput,
        # mouce-library-fake-mouse). Falls back to logind if evdev unavailable.
        b_real = behaviors.get("real_keyboard_active")
        b_real_idle = behaviors.get("real_idle_seconds")
        if b_real is not None:
            if b_real.value:
                obs["keyboard_active"] = True
            else:
                idle_s = float(b_real_idle.value) if b_real_idle is not None else 9999.0
                if idle_s > 300:
                    obs["keyboard_active"] = False
                else:
                    obs["keyboard_active"] = None
        else:
            b_active = behaviors.get("input_active")
            obs["keyboard_active"] = b_active.value if b_active is not None else None

        # VAD speech: positive-only. Detected speech = evidence FOR presence.
        # Silence = neutral (operator typing, reading, thinking).
        b = behaviors.get("vad_confidence")
        if b is not None and isinstance(b.value, (int, float)) and b.value > 0.5:
            obs["vad_speech"] = True
        else:
            obs["vad_speech"] = None

        # Speaker identified as operator
        b = behaviors.get("speaker_is_operator")
        obs["speaker_is_operator"] = b.value if b is not None else None

        # Watch heart rate — bidirectional with staleness decay.
        b_hr = behaviors.get("heart_rate_bpm")
        b_stale = behaviors.get("watch_hr_stale_seconds")
        hr_stale = (
            float(b_stale.value) if b_stale is not None and b_stale.value is not None else 9999.0
        )
        if b_hr is not None and isinstance(b_hr.value, (int, float)) and b_hr.value > 0:
            if hr_stale < 30:
                obs["watch_hr"] = True
            elif hr_stale < 120:
                obs["watch_hr"] = None
            else:
                obs["watch_hr"] = False  # out of BLE range
        else:
            obs["watch_hr"] = None

        # Watch connected: positive-only. Connected = evidence FOR presence.
        # Disconnected = neutral (watch charging, Bluetooth off, battery dead).
        b = behaviors.get("watch_connected")
        if b is not None and b.value:
            obs["watch_connected"] = True
        else:
            obs["watch_connected"] = None

        # Desktop activity: positive-only. Focus change = evidence FOR presence.
        # Sustained focus on one window = neutral (deep work, not absence).
        b = behaviors.get("desktop_active")
        if b is not None and b.value:
            obs["desktop_active"] = True
        else:
            obs["desktop_active"] = None

        # Bluetooth phone presence: positive-only. Active BT connection = evidence
        # FOR presence (requires proximity). Paired-but-not-connected = neutral
        # (paired list is permanent regardless of distance). Future: BLE RSSI
        # proximity with distance calibration for in-office vs hallway thresholds.
        b = behaviors.get("bt_watch_connected")
        if b is not None and b.value:
            # Check if actually connected (not just in paired list)
            # The bt_presence backend sets True when MAC seen in recent scan
            obs["bt_phone_connected"] = True
        else:
            obs["bt_phone_connected"] = None

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

        # IR hand activity: positive-only, gated on motion.
        # The NIR hand thresholding produces false positives on static objects
        # (cables, equipment with right reflectivity). Real hands produce motion;
        # static false positives don't. Gate: hand detected AND motion > 0.05.
        b_hand = behaviors.get("ir_hand_activity")
        b_motion = behaviors.get("ir_motion_delta")
        motion = (
            float(b_motion.value) if b_motion is not None and b_motion.value is not None else 0.0
        )
        hand_active = (
            b_hand is not None
            and isinstance(b_hand.value, str)
            and b_hand.value not in ("none", "idle", "")
        )
        if hand_active and motion > 0.05:
            obs["ir_hand_active"] = True
        else:
            obs["ir_hand_active"] = None

        # Contact mic desk activity: positive-only. Typing/tapping/drumming on Cortado
        # MKIII = strong presence. Idle/unknown = neutral.
        b = behaviors.get("desk_activity")
        if b is not None and isinstance(b.value, str) and b.value not in ("idle", "unknown", ""):
            obs["desk_active"] = True
        else:
            obs["desk_active"] = None

        return obs

    def _compute_posterior(self, observations: dict[str, bool | None]) -> float:
        """Compute posterior + advance state via ClaimEngine.tick.

        Phase 1 delegation: ClaimEngine performs the same log-odds fusion
        + drift-toward-prior decay + sigmoid this method used to do
        inline. Returns the engine's resulting posterior. Side-effect:
        the engine's hysteresis state machine ticks once.
        """
        self._engine.tick(observations)
        return self._engine.posterior

    def _update_state_machine(self, posterior: float) -> None:
        """Synchronize the legacy state-name shadow from the engine.

        Phase 1 delegation: ClaimEngine.tick() (called from
        ``_compute_posterior``) already advanced its hysteresis state
        machine using the same dwell-counter logic this method used to
        own. Translate the engine's ASSERTED/UNCERTAIN/RETRACTED
        vocabulary back to PresenceEngine's PRESENT/UNCERTAIN/AWAY for
        public-API compatibility.
        """
        self._state = _ENGINE_STATE_TO_PRESENCE_STATE[self._engine.state]

    def _required_ticks_for_transition(self, from_state: str, to_state: str) -> int:
        """How many sustained ticks needed to transition between states.

        Retained as a helper for backward-compatible introspection in tests
        that import this method directly. The runtime hysteresis logic is
        now in ``shared.claim.ClaimEngine._required_ticks_for_transition``;
        the two implementations stay in lock-step (Phase 1 regression pin).
        """
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
    def history(self) -> list[dict[str, object]]:
        return list(self._history)
