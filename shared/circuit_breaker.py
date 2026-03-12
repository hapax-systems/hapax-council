"""Circuit breaker for automated fix attempts.

Tracks fix attempts per check within a rolling time window.
Prevents runaway fix loops by limiting attempts.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class CircuitState:
    check_name: str
    attempts: int = 0
    last_attempt: float = 0.0
    window_start: float = 0.0
    successes: int = 0


@dataclass
class CircuitBreaker:
    """Track fix attempts per check. Max N attempts per window."""

    max_attempts: int = 2
    window_seconds: int = 86400  # 24 hours
    state_path: Path = field(default_factory=lambda: Path("profiles/circuit-breaker.json"))
    _states: dict[str, CircuitState] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._load()

    def _load(self) -> None:
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text())
                for key, val in data.items():
                    self._states[key] = CircuitState(**val)
            except (json.JSONDecodeError, TypeError):
                self._states = {}

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({k: asdict(v) for k, v in self._states.items()}, indent=2))
        tmp.rename(self.state_path)

    def _get_state(self, check_name: str) -> CircuitState:
        if check_name not in self._states:
            self._states[check_name] = CircuitState(check_name=check_name)
        state = self._states[check_name]
        # Reset window if expired.
        now = time.time()
        if now - state.window_start > self.window_seconds:
            state.attempts = 0
            state.successes = 0
            state.window_start = now
        return state

    def can_attempt(self, check_name: str) -> bool:
        """Return True if the check has attempts remaining in the current window."""
        state = self._get_state(check_name)
        return state.attempts < self.max_attempts

    def remaining_attempts(self, check_name: str) -> int:
        """Return number of attempts remaining."""
        state = self._get_state(check_name)
        return max(0, self.max_attempts - state.attempts)

    def record_attempt(self, check_name: str, *, success: bool = False) -> None:
        """Record a fix attempt. Resets on success."""
        state = self._get_state(check_name)
        state.attempts += 1
        state.last_attempt = time.time()
        if success:
            state.successes += 1
            # Reset attempts on success — the fix worked.
            state.attempts = 0
        self._save()

    def reset(self, check_name: str) -> None:
        """Manually reset a check's circuit breaker (operator override)."""
        if check_name in self._states:
            del self._states[check_name]
            self._save()

    def is_tripped(self, check_name: str) -> bool:
        """Return True if the circuit breaker has been tripped (max attempts reached)."""
        return not self.can_attempt(check_name)

    def status(self) -> dict[str, dict]:
        """Return all circuit breaker states for monitoring."""
        result = {}
        for key, state in self._states.items():
            result[key] = {
                "attempts": state.attempts,
                "remaining": self.remaining_attempts(key),
                "tripped": self.is_tripped(key),
                "last_attempt": state.last_attempt,
            }
        return result
