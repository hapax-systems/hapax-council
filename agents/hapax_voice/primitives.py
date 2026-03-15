"""Perception primitive types: Stamped, Behavior, Event.

Phase 1 of the perception type system. These types provide typed containers
with freshness watermarks (Behavior) and discrete occurrence signaling (Event)
as extension points for Phase 2 Combinators.

Consent threading (DD-22):
- L0 (Stamped): No change. Pure value snapshots carry no consent semantics.
- L1 (Behavior): Optional consent_label tracks information flow governance.
  Labels float upward on update via join (no implicit declassification, DD-4).
  None means "untracked" (gradual adoption, DD-16); bottom means "explicitly public."
- L1 (Event): No change. Consent attaches to data flowing through events
  at the FusedContext level (L2+).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from shared.governance.consent_label import ConsentLabel

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

    Optional consent_label (DD-22) tracks information flow governance:
    - None: consent not tracked for this behavior (gradual adoption, DD-16)
    - ConsentLabel.bottom(): explicitly public / unrestricted
    - ConsentLabel({policies}): governed by specific consent policies
    Labels only float upward via join on update (DD-4: no implicit declassification).
    """

    __slots__ = ("_value", "_watermark", "_consent_label")

    def __init__(
        self,
        initial: T,
        watermark: float | None = None,
        consent_label: ConsentLabel | None = None,
    ) -> None:
        self._value: T = initial
        self._watermark: float = watermark if watermark is not None else time.monotonic()
        self._consent_label: ConsentLabel | None = consent_label

    @property
    def value(self) -> T:
        return self._value

    @property
    def watermark(self) -> float:
        return self._watermark

    @property
    def consent_label(self) -> ConsentLabel | None:
        """Current consent label, or None if consent is untracked."""
        return self._consent_label

    def sample(self) -> Stamped[T]:
        """Return current value with its watermark."""
        return Stamped(value=self._value, watermark=self._watermark)

    def update(self, value: T, timestamp: float, consent_label: ConsentLabel | None = None) -> None:
        """Update value. Raises ValueError if timestamp regresses.

        If consent_label is provided, it is joined with the existing label
        (labels float upward only). If the existing label is None and a
        label is provided, the behavior transitions from untracked to tracked.
        """
        if timestamp < self._watermark:
            raise ValueError(f"Watermark regression: {timestamp} < {self._watermark}")
        self._value = value
        self._watermark = timestamp
        if consent_label is not None:
            if self._consent_label is not None:
                self._consent_label = self._consent_label.join(consent_label)
            else:
                self._consent_label = consent_label


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
