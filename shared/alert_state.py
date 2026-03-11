"""Alert deduplication and escalation tracking.

Prevents notification spam by tracking consecutive failures per check and only
notifying on state transitions (OK→FIRING) or escalation thresholds.

Persists state to ~/.cache/health-watchdog/alert-state.json.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path


class AlertPhase(StrEnum):
    OK = "ok"
    FIRING = "firing"
    ACKNOWLEDGED = "acknowledged"


@dataclass
class CheckAlertState:
    """Tracking state for a single check's alert lifecycle."""

    phase: AlertPhase = AlertPhase.OK
    consecutive_failures: int = 0
    last_notified_at: str = ""
    escalation_level: int = 0  # index into ESCALATION_THRESHOLDS
    first_failure_at: str = ""

    def to_dict(self) -> dict:
        return {
            "phase": self.phase.value,
            "consecutive_failures": self.consecutive_failures,
            "last_notified_at": self.last_notified_at,
            "escalation_level": self.escalation_level,
            "first_failure_at": self.first_failure_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> CheckAlertState:
        return cls(
            phase=AlertPhase(d.get("phase", "ok")),
            consecutive_failures=d.get("consecutive_failures", 0),
            last_notified_at=d.get("last_notified_at", ""),
            escalation_level=d.get("escalation_level", 0),
            first_failure_at=d.get("first_failure_at", ""),
        )


# Consecutive failure counts that trigger re-notification (escalation).
ESCALATION_THRESHOLDS = [1, 4, 12]


class AlertStateTracker:
    """Track alert state across health check runs with dedup and escalation."""

    def __init__(self, state_path: Path | None = None):
        from shared.config import HEALTH_STATE_DIR

        self.state_path = state_path or (HEALTH_STATE_DIR / "alert-state.json")
        self._states: dict[str, CheckAlertState] = {}
        self._load()

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text())
            for name, d in data.items():
                self._states[name] = CheckAlertState.from_dict(d)
        except (json.JSONDecodeError, OSError):
            pass

    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {name: s.to_dict() for name, s in self._states.items()}
        # Atomic write
        fd, tmp = tempfile.mkstemp(dir=str(self.state_path.parent), suffix=".json")
        try:
            with open(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self.state_path)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise

    def update(self, check_name: str, is_healthy: bool) -> tuple[bool, str]:
        """Update state for a check. Returns (should_notify, priority).

        priority is one of: "high", "default", "low", or "" (no notification).
        """
        now = datetime.now(UTC).isoformat()
        state = self._states.get(check_name, CheckAlertState())

        if is_healthy:
            if state.phase in (AlertPhase.FIRING, AlertPhase.ACKNOWLEDGED):
                # Recovery — notify once
                state.phase = AlertPhase.OK
                state.consecutive_failures = 0
                state.escalation_level = 0
                state.first_failure_at = ""
                self._states[check_name] = state
                return (True, "low")  # recovery notification
            # Already OK
            state.phase = AlertPhase.OK
            state.consecutive_failures = 0
            self._states[check_name] = state
            return (False, "")

        # Failure path
        state.consecutive_failures += 1
        if not state.first_failure_at:
            state.first_failure_at = now

        if state.phase == AlertPhase.OK:
            # New failure — always notify
            state.phase = AlertPhase.FIRING
            state.escalation_level = 0
            state.last_notified_at = now
            self._states[check_name] = state
            return (True, "high")

        # Already firing — check escalation thresholds
        next_level = state.escalation_level + 1
        if (
            next_level < len(ESCALATION_THRESHOLDS)
            and state.consecutive_failures >= ESCALATION_THRESHOLDS[next_level]
        ):
            state.escalation_level = next_level
            state.last_notified_at = now
            self._states[check_name] = state
            return (True, "high")

        # Still firing but below next escalation threshold — suppress
        self._states[check_name] = state
        return (False, "")

    def acknowledge(self, check_name: str) -> bool:
        """Acknowledge an alert (suppress further escalation until recovery)."""
        state = self._states.get(check_name)
        if state and state.phase == AlertPhase.FIRING:
            state.phase = AlertPhase.ACKNOWLEDGED
            return True
        return False

    def get_state(self, check_name: str) -> CheckAlertState:
        return self._states.get(check_name, CheckAlertState())

    def get_firing(self) -> dict[str, CheckAlertState]:
        """Return all checks currently in FIRING state."""
        return {
            name: state for name, state in self._states.items() if state.phase == AlertPhase.FIRING
        }

    def reset(self) -> None:
        """Clear all tracked state."""
        self._states.clear()
