"""Bayesian presence engine — probabilistic operator presence via signal fusion.

Replaces rule-based PresenceDetector.score with a Bayesian posterior that
fuses all available perception signals. Uses temporal hysteresis to prevent
oscillation between PRESENT/AWAY states.

Registered as a PerceptionBackend; provides `presence_probability` (float)
and `presence_state` (str: PRESENT/UNCERTAIN/AWAY).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from collections import deque
from pathlib import Path
from typing import Any

from agents.hapax_daimonion.perception import PerceptionTier
from agents.hapax_daimonion.primitives import Behavior

log = logging.getLogger(__name__)

# State enum used by the `hapax_presence_state` Prometheus gauge.
# AWAY < UNCERTAIN < PRESENT so the ordering is monotone in presence evidence.
PRESENCE_STATE_ENUM: dict[str, int] = {"AWAY": 0, "UNCERTAIN": 1, "PRESENT": 2}

# Atomic tmp+rename write target consumed by `/api/predictions/metrics`.
PRESENCE_METRICS_FILE = Path("/dev/shm/hapax-daimonion/presence-metrics.json")

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
        self._history: deque[dict[str, object]] = deque(maxlen=100)
        self._event_log: Any | None = None

        # Prometheus observability — cumulative True-observation counts per
        # signal. Incremented every tick when a signal fires positive; exposed
        # via `metrics_snapshot()` and the on-disk file consumed by the
        # `/api/predictions/metrics` route. Seeded to 0 for every signal in
        # `DEFAULT_SIGNAL_WEIGHTS` so the Prometheus series exist before the
        # first fire — rate() over an always-zero series returns 0 instead of
        # stale-label gaps, which matters when the signal has been silent for
        # the full scrape window.
        self._signal_fire_counts: dict[str, int] = dict.fromkeys(self._signal_weights, 0)
        self._metrics_file_failures: int = 0

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

        # Tally cumulative fires for Prometheus counters. Only True fires
        # count — None observations are "no evidence" and False fires are
        # absence evidence, neither should inflate the positive-fire counter.
        for signal_name, observed in signal_observations.items():
            if observed is True:
                self._signal_fire_counts[signal_name] = (
                    self._signal_fire_counts.get(signal_name, 0) + 1
                )

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

        # Publish the Prometheus snapshot. The file is the scrape source for
        # `/api/predictions/metrics`; consumers read it atomically via
        # read_text() so a tmp+rename write is required.
        self._write_metrics_snapshot()

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
        """Compute Bayesian posterior from likelihood ratios (log-domain)."""
        import math

        prior = self._last_posterior
        prior = prior + (self._prior - prior) * self._decay_rate
        prior = max(0.001, min(0.999, prior))
        log_odds = math.log(prior / (1.0 - prior))

        for signal_name, (p_present, p_absent) in self._signal_weights.items():
            observed = observations.get(signal_name)
            if observed is None:
                continue
            if observed:
                lr = p_present / max(p_absent, 1e-12)
            else:
                lr = (1.0 - p_present) / max(1.0 - p_absent, 1e-12)
            log_odds += math.log(max(lr, 1e-12))

        try:
            posterior = 1.0 / (1.0 + math.exp(-log_odds))
        except OverflowError:
            posterior = 0.0 if log_odds < 0 else 1.0
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
    def history(self) -> list[dict[str, object]]:
        return list(self._history)

    # -- Prometheus observability --

    def metrics_snapshot(self) -> dict[str, Any]:
        """Return a Prometheus-friendly snapshot of the current state.

        Consumed by the `/api/predictions/metrics` endpoint (via the shm
        file) and by tests. Fields:

        - ``signal_fire_counts``: cumulative True-observation counts per
          signal since process start. Restart-safe under Prometheus
          counter-reset semantics.
        - ``posterior``: current Bayesian posterior (0.0..1.0).
        - ``state``: current hysteresis state string.
        - ``state_enum``: integer enum for the gauge (0=AWAY,
          1=UNCERTAIN, 2=PRESENT).
        - ``ts``: wall-clock seconds for freshness gating.
        """
        return {
            "signal_fire_counts": dict(self._signal_fire_counts),
            "posterior": self._last_posterior,
            "state": self._state,
            "state_enum": PRESENCE_STATE_ENUM.get(self._state, PRESENCE_STATE_ENUM["UNCERTAIN"]),
            "ts": time.time(),
        }

    def _write_metrics_snapshot(self, path: Path | None = None) -> None:
        """Atomically write the metrics snapshot to disk.

        Logged at warning for the first few failures, then silent — the
        metrics file is advisory and must never stall the perception tick.
        """
        target = path if path is not None else PRESENCE_METRICS_FILE
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(self.metrics_snapshot())
            # tmp+rename keeps readers from observing a torn write.
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=str(target.parent),
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                tmp.write(payload)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_name = tmp.name
            os.replace(tmp_name, target)
            self._metrics_file_failures = 0
        except OSError:
            self._metrics_file_failures += 1
            if self._metrics_file_failures <= 3:
                log.warning(
                    "PresenceEngine metrics snapshot write failed (%d)",
                    self._metrics_file_failures,
                    exc_info=True,
                )
