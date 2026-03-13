"""SuppressionField — smooth-ramping suppression primitive wrapping Behavior[float].

Provides temporal smoothing (attack/release) for cross-role suppression signals.
The underlying Behavior[float] participates in Combinator sampling like any other
Behavior. Governance reads the suppression level and adjusts thresholds via
the additive effective_threshold formula.
"""

from __future__ import annotations

from agents.hapax_voice.primitives import Behavior


class SuppressionField:
    """Smooth-ramping suppression signal with attack/release envelope.

    Wraps a Behavior[float] in [0, 1]. Call set_target() to change the desired
    suppression level, then tick() on each perception cycle to advance the ramp.
    The underlying Behavior is updated with monotonic watermarks.
    """

    __slots__ = ("_behavior", "_attack_s", "_release_s", "_target", "_last_tick_time")

    def __init__(
        self,
        attack_s: float = 0.3,
        release_s: float = 1.0,
        initial: float = 0.0,
        watermark: float = 0.0,
    ) -> None:
        if attack_s <= 0:
            raise ValueError(f"attack_s must be positive, got {attack_s}")
        if release_s <= 0:
            raise ValueError(f"release_s must be positive, got {release_s}")
        self._behavior: Behavior[float] = Behavior(max(0.0, min(1.0, initial)), watermark=watermark)
        self._attack_s = attack_s
        self._release_s = release_s
        self._target: float = max(0.0, min(1.0, initial))
        self._last_tick_time: float | None = None

    @property
    def behavior(self) -> Behavior[float]:
        """Expose underlying Behavior for Combinator sampling."""
        return self._behavior

    @property
    def target(self) -> float:
        return self._target

    @property
    def value(self) -> float:
        return self._behavior.value

    def set_target(self, level: float, now: float) -> None:
        """Set the desired suppression level, clamped to [0, 1]."""
        self._target = max(0.0, min(1.0, level))
        # If this is the first interaction, establish timing reference
        if self._last_tick_time is None:
            self._last_tick_time = now

    def tick(self, now: float) -> float:
        """Advance the ramp toward target. Returns current suppression level.

        First tick establishes the timing reference without moving the value.
        Subsequent ticks apply linear ramp with attack_s (rising) or release_s (falling).
        """
        if self._last_tick_time is None:
            self._last_tick_time = now
            return self._behavior.value

        dt = now - self._last_tick_time
        if dt <= 0:
            return self._behavior.value

        self._last_tick_time = now
        current = self._behavior.value

        if current < self._target:
            # Rising — use attack rate
            rate = 1.0 / self._attack_s
            new_value = min(current + rate * dt, self._target)
        elif current > self._target:
            # Falling — use release rate
            rate = 1.0 / self._release_s
            new_value = max(current - rate * dt, self._target)
        else:
            new_value = current

        self._behavior.update(new_value, now)
        return new_value


def effective_threshold(base: float, suppression: float) -> float:
    """Compute effective threshold with additive suppression.

    threshold_eff = base + suppression * (1.0 - base)

    At suppression=0, threshold is unchanged.
    At suppression=1, threshold is 1.0 (impossible to reach → fully suppressed).
    """
    return base + suppression * (1.0 - base)
