"""Proactive gate — conditions for system-initiated speech.

Determines whether the system should speak unprompted based on
imagination fragment salience, operator activity, VAD state,
conversation gap, TPN state, and cooldown timing.
"""

from __future__ import annotations

import time

from agents.imagination import ImaginationFragment

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SALIENCE_THRESHOLD = 0.8
GAP_THRESHOLD_S = 30.0
DEFAULT_COOLDOWN_S = 120.0
ABSENT_ACTIVITIES = {"idle", "away", "unknown"}


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


class ProactiveGate:
    """Gate that decides whether the system should speak proactively."""

    def __init__(self, cooldown_s: float = DEFAULT_COOLDOWN_S) -> None:
        self._cooldown_s = cooldown_s
        self._last_proactive: float = 0.0

    def should_speak(self, fragment: ImaginationFragment, state: dict) -> bool:
        """Return True only when ALL gate conditions pass."""
        if fragment.salience < SALIENCE_THRESHOLD:
            return False
        if state["perception_activity"] in ABSENT_ACTIVITIES:
            return False
        if state["vad_active"]:
            return False
        if time.monotonic() - state["last_utterance_time"] < GAP_THRESHOLD_S:
            return False
        if state["tpn_active"]:
            return False
        return time.monotonic() - self._last_proactive >= self._cooldown_s

    def record_utterance(self) -> None:
        """Record that the system just spoke proactively."""
        self._last_proactive = time.monotonic()

    def on_operator_speech(self) -> None:
        """Clear cooldown when the operator speaks (conversation started)."""
        self._last_proactive = 0.0
