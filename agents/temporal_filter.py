"""Temporal stability filter — hysteresis to prevent flickering classifications.

N-of-M confirmation filter: requires N consistent classifications in an
M-sample window before changing the displayed value. Applied to categorical
fields: gaze_direction, emotion, posture, action, mobility.

Pure-logic module: no I/O, no threading. The aggregator instantiates one
filter per field and calls it every tick.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class TemporalFilter:
    """N-of-M hysteresis filter for a single categorical classification field.

    Requires `confirm_n` consistent values in a `window_m` sample window
    before switching the output. Until confirmed, the previous stable
    value is returned.
    """

    confirm_n: int = 3
    window_m: int = 5
    _history: deque[str | None] = field(default_factory=lambda: deque(maxlen=5))
    _stable_value: str | None = None

    def __post_init__(self) -> None:
        # Ensure maxlen matches window_m
        self._history = deque(maxlen=self.window_m)

    def update(self, value: str | None) -> str | None:
        """Push a new observation, return the stable (filtered) value.

        Returns the new value only after it has been seen confirm_n times
        in the last window_m observations. Otherwise returns the previous
        stable value.
        """
        self._history.append(value)

        if value is not None:
            count = sum(1 for v in self._history if v == value)
            if count >= self.confirm_n:
                self._stable_value = value

        return self._stable_value

    def reset(self) -> None:
        """Clear history and stable value."""
        self._history.clear()
        self._stable_value = None

    @property
    def current(self) -> str | None:
        """Return the current stable value without updating."""
        return self._stable_value


@dataclass
class ClassificationFilter:
    """Composite filter for all categorical classification fields.

    One TemporalFilter per field, all sharing the same N-of-M parameters.
    """

    confirm_n: int = 3
    window_m: int = 5
    _filters: dict[str, TemporalFilter] = field(default_factory=dict)

    _FIELDS: tuple[str, ...] = (
        "gaze_direction",
        "emotion",
        "posture",
        "gesture",
        "action",
        "mobility",
    )

    def __post_init__(self) -> None:
        for name in self._FIELDS:
            self._filters[name] = TemporalFilter(
                confirm_n=self.confirm_n,
                window_m=self.window_m,
            )

    def filter(self, **values: str | None) -> dict[str, str | None]:
        """Filter a set of classification values.

        Accepts keyword arguments matching field names. Returns a dict
        of filtered (stable) values for all fields.
        """
        result: dict[str, str | None] = {}
        for name in self._FIELDS:
            raw = values.get(name)
            result[name] = self._filters[name].update(raw)
        return result

    def reset(self) -> None:
        """Clear all filter state."""
        for f in self._filters.values():
            f.reset()
