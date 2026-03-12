"""Perception primitive types: Stamped, Behavior, Event.

Phase 1 of the perception type system. These types provide typed containers
with freshness watermarks (Behavior) and discrete occurrence signaling (Event)
as extension points for Phase 2 Combinators.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Stamped[T]:
    """Immutable snapshot of a value with its freshness watermark."""

    value: T
    watermark: float


class Behavior[T]:
    """Continuously-available value with monotonic watermark.

    Always has a current value — sample() never fails.
    Watermark must advance monotonically; regression raises ValueError.
    """

    __slots__ = ("_value", "_watermark")

    def __init__(self, initial: T, watermark: float | None = None) -> None:
        self._value: T = initial
        self._watermark: float = watermark if watermark is not None else time.monotonic()

    @property
    def value(self) -> T:
        return self._value

    @property
    def watermark(self) -> float:
        return self._watermark

    def sample(self) -> Stamped[T]:
        """Return current value with its watermark."""
        return Stamped(value=self._value, watermark=self._watermark)

    def update(self, value: T, timestamp: float) -> None:
        """Update value. Raises ValueError if timestamp regresses."""
        if timestamp < self._watermark:
            raise ValueError(f"Watermark regression: {timestamp} < {self._watermark}")
        self._value = value
        self._watermark = timestamp


class Event[T]:
    """Discrete occurrence with pub/sub signaling.

    Subscribers receive (timestamp, value) on emit. No history for late
    subscribers. Exceptions in individual subscribers are caught and logged
    (matches PerceptionEngine pattern).
    """

    __slots__ = ("_subscribers",)

    def __init__(self) -> None:
        self._subscribers: list[Callable[[float, T], None]] = []

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def subscribe(self, callback: Callable[[float, T], None]) -> Callable[[], None]:
        """Register a callback. Returns an unsubscribe function."""
        self._subscribers.append(callback)

        def _unsubscribe() -> None:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

        return _unsubscribe

    def emit(self, timestamp: float, value: T) -> None:
        """Notify all subscribers. Exceptions are caught per-subscriber."""
        for cb in self._subscribers:
            try:
                cb(timestamp, value)
            except Exception:
                log.exception("Event subscriber error")
