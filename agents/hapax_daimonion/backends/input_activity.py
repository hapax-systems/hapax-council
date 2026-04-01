"""Input activity perception backend — keyboard/mouse via systemd-logind DBus.

Polls org.freedesktop.login1.Session for IdleHint and IdleSinceHintMonotonic.
Zero external dependencies — uses busctl (part of systemd).
Fails open: if logind is unavailable, reports input_active=True.
"""

from __future__ import annotations

import logging
import subprocess
import time

from agents.hapax_daimonion.perception import PerceptionTier
from agents.hapax_daimonion.primitives import Behavior

log = logging.getLogger(__name__)

_SESSION_PATH: str | None = None
_DBUS_AVAILABLE: bool | None = None


def _discover_session_path() -> str:
    """Find the current graphical session object path in logind."""
    result = subprocess.run(
        ["loginctl", "show-user", "--property=Sessions", "--value"],
        capture_output=True,
        text=True,
        timeout=2,
    )
    sessions = result.stdout.strip().split()
    session_id = sessions[0] if sessions else "auto"
    return f"/org/freedesktop/login1/session/{session_id.replace('-', '_')}"


def _busctl_get(session_path: str, prop: str) -> str:
    """Read a single property from the logind session via busctl."""
    result = subprocess.run(
        [
            "busctl",
            "get-property",
            "org.freedesktop.login1",
            session_path,
            "org.freedesktop.login1.Session",
            prop,
        ],
        capture_output=True,
        text=True,
        timeout=2,
    )
    return result.stdout.strip()


def _get_idle_hint() -> tuple[bool, float]:
    """Read IdleHint and idle duration from logind.

    Returns (idle_hint: bool, idle_seconds: float).
    Falls back to (False, 0.0) on any error (fail-open).
    """
    global _SESSION_PATH, _DBUS_AVAILABLE

    if _DBUS_AVAILABLE is False:
        return False, 0.0

    try:
        if _SESSION_PATH is None:
            _SESSION_PATH = _discover_session_path()
            log.debug("logind session path: %s", _SESSION_PATH)

        idle_raw = _busctl_get(_SESSION_PATH, "IdleHint")
        idle_hint = "true" in idle_raw.lower()

        idle_seconds = 0.0
        if idle_hint:
            since_raw = _busctl_get(_SESSION_PATH, "IdleSinceHintMonotonic")
            # busctl output: "t 1234567890" (microseconds, monotonic clock)
            parts = since_raw.split()
            if len(parts) >= 2:
                idle_since_us = int(parts[1])
                if idle_since_us > 0:
                    now_us = int(time.clock_gettime(time.CLOCK_MONOTONIC) * 1_000_000)
                    idle_seconds = max(0.0, (now_us - idle_since_us) / 1_000_000.0)

        _DBUS_AVAILABLE = True
        return idle_hint, idle_seconds

    except Exception:
        if _DBUS_AVAILABLE is None:
            log.info("logind DBus not available — input activity will fail-open")
            _DBUS_AVAILABLE = False
        return False, 0.0


class InputActivityBackend:
    """PerceptionBackend that reads keyboard/mouse activity from systemd-logind.

    Provides:
      - input_active: bool (True if keyboard/mouse activity within threshold)
      - input_idle_seconds: float (seconds since last input)
    """

    def __init__(self, idle_threshold_s: float = 5.0) -> None:
        self._idle_threshold_s = idle_threshold_s
        self._b_input_active: Behavior[bool] = Behavior(True)  # fail-open default
        self._b_idle_seconds: Behavior[float] = Behavior(0.0)
        from shared.exploration_tracker import ExplorationTrackerBundle

        self._exploration = ExplorationTrackerBundle(
            component="input_activity",
            edges=["active_state", "idle_duration"],
            traces=["input_active", "idle_seconds"],
            neighbors=["ir_presence", "contact_mic"],
            kappa=0.020,
            t_patience=180.0,
        )
        self._prev_active: float = 1.0
        self._prev_idle: float = 0.0

    @property
    def name(self) -> str:
        return "input_activity"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"input_active", "input_idle_seconds"})

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.FAST

    def available(self) -> bool:
        return True  # Always available — degrades gracefully

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        now = time.monotonic()
        idle_hint, idle_seconds = _get_idle_hint()

        active = not idle_hint or idle_seconds < self._idle_threshold_s

        self._b_input_active.update(active, now)
        self._b_idle_seconds.update(idle_seconds, now)

        behaviors["input_active"] = self._b_input_active
        behaviors["input_idle_seconds"] = self._b_idle_seconds

        self._exploration.feed_habituation("active_state", float(active), self._prev_active, 0.3)
        self._exploration.feed_habituation("idle_duration", idle_seconds, self._prev_idle, 5.0)
        self._exploration.feed_interest("input_active", float(active), 0.3)
        self._exploration.feed_interest("idle_seconds", idle_seconds, 5.0)
        self._exploration.feed_error(0.0 if active else 0.5)
        self._exploration.compute_and_publish()
        self._prev_active = float(active)
        self._prev_idle = idle_seconds

    def start(self) -> None:
        log.info("InputActivity backend started (threshold=%.1fs)", self._idle_threshold_s)

    def stop(self) -> None:
        log.info("InputActivity backend stopped")
