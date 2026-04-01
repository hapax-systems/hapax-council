"""Loop gain controller -- continuous conversational intensity.

Replaces the binary session model (open/close) with a continuous
scalar 0.0 (ambient) to 1.0 (fully engaged). Gain emerges from
perception signals and modulates all conversational behavior.

Follows the same asymmetric hysteresis as all S1 components:
3 consecutive failures -> degrade, 5 consecutive successes -> recover.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from agents.hapax_daimonion.cpal.types import ConversationalRegion, GainUpdate

_DECAY_TAU = 15.0  # exponential decay time constant (seconds)
_DEGRADE_THRESHOLD = 3  # consecutive failures before gain reduction
_RECOVER_THRESHOLD = 5  # consecutive successes before gain boost
_DEGRADE_AMOUNT = 0.1  # gain reduction on degrade
_RECOVER_AMOUNT = 0.05  # gain boost on recover
_NEAR_ZERO = 0.005  # below this, clamp to 0.0
_HISTORY_MAXLEN = 50

_STIMMUNG_CEILINGS: dict[str, float] = {
    "nominal": 1.0,
    "cautious": 0.7,
    "degraded": 0.5,
    "critical": 0.3,
}


@dataclass
class LoopGainController:
    """Manages continuous conversational intensity."""

    _gain: float = 0.0
    _ceiling: float = 1.0
    _consecutive_failures: int = 0
    _consecutive_successes: int = 0
    _recent_updates: deque[GainUpdate] = field(
        default_factory=lambda: deque(maxlen=_HISTORY_MAXLEN)
    )

    @property
    def gain(self) -> float:
        return self._gain

    @property
    def region(self) -> ConversationalRegion:
        return ConversationalRegion.from_gain(self._gain)

    @property
    def recent_updates(self) -> list[GainUpdate]:
        return list(self._recent_updates)

    def apply(self, update: GainUpdate) -> None:
        """Apply a gain adjustment (driver or damper)."""
        self._gain = max(0.0, min(self._ceiling, self._gain + update.delta))
        self._recent_updates.append(update)

    def decay(self, dt: float) -> None:
        """Apply exponential silence decay over dt seconds."""
        self._gain *= math.exp(-dt / _DECAY_TAU)
        if self._gain < _NEAR_ZERO:
            self._gain = 0.0
        self._gain = min(self._gain, self._ceiling)

    def set_stimmung_ceiling(self, stance: str) -> None:
        """Set gain ceiling from stimmung stance. Enforced immediately."""
        self._ceiling = _STIMMUNG_CEILINGS.get(stance, 1.0)
        if self._gain > self._ceiling:
            self._gain = self._ceiling

    def record_grounding_outcome(self, *, success: bool) -> None:
        """Record a grounding success or failure for hysteresis."""
        if success:
            self._consecutive_failures = 0
            self._consecutive_successes += 1
            if self._consecutive_successes >= _RECOVER_THRESHOLD:
                self._gain = min(self._ceiling, self._gain + _RECOVER_AMOUNT)
                self._consecutive_successes = 0
        else:
            self._consecutive_successes = 0
            self._consecutive_failures += 1
            if self._consecutive_failures >= _DEGRADE_THRESHOLD:
                self._gain = max(0.0, self._gain - _DEGRADE_AMOUNT)
                self._consecutive_failures = 0
