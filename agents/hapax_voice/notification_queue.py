"""Priority notification queue with TTL expiry."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

_PRIORITY_ORDER = {"urgent": 0, "normal": 1, "low": 2}

_DEFAULT_TTLS = {"urgent": 1800, "normal": 14400, "low": 0}


@dataclass
class VoiceNotification:
    """A notification to be delivered via voice."""

    title: str
    message: str
    priority: str  # "urgent", "normal", or "low"
    source: str
    created_at: float = field(default_factory=time.monotonic)


class NotificationQueue:
    """Priority queue for voice notifications with TTL expiry.

    Notifications are sorted by priority (urgent > normal > low).
    Each priority level has a TTL; expired items are pruned on access.
    TTL=0 for low means deliver-or-discard (available immediately,
    never auto-expires — it simply won't persist if not delivered).
    """

    def __init__(self, ttls: dict[str, int] | None = None) -> None:
        self._ttls = ttls if ttls is not None else dict(_DEFAULT_TTLS)
        self._items: list[VoiceNotification] = []
        self._event_log = None

    def set_event_log(self, event_log) -> None:
        """Attach an EventLog instance for lifecycle event emission."""
        self._event_log = event_log

    @property
    def pending_count(self) -> int:
        """Number of pending notifications."""
        self.prune_expired()
        return len(self._items)

    def enqueue(self, notification: VoiceNotification) -> None:
        """Add a notification and sort by priority."""
        self._items.append(notification)
        self._items.sort(key=lambda n: _PRIORITY_ORDER.get(n.priority, 1))
        log.debug(
            "Enqueued notification: %s (priority=%s, source=%s)",
            notification.title,
            notification.priority,
            notification.source,
        )
        if self._event_log is not None:
            self._event_log.emit(
                "notification_lifecycle",
                action="queued",
                title=notification.title,
                priority=notification.priority,
                source=notification.source,
            )

    def next(self) -> VoiceNotification | None:
        """Prune expired items and return the highest-priority notification."""
        self.prune_expired()
        if not self._items:
            return None
        return self._items.pop(0)

    def requeue(self, notification: VoiceNotification) -> None:
        """Re-add a notification (e.g., after failed delivery)."""
        self.enqueue(notification)

    def prune_expired(self) -> None:
        """Remove notifications that have exceeded their TTL.

        TTL=0 means the item does not auto-expire.
        """
        now = time.monotonic()
        kept: list[VoiceNotification] = []
        for item in self._items:
            ttl = self._ttls.get(item.priority, 0)
            if ttl == 0:
                # TTL=0 means deliver-or-discard, no auto-expiry
                kept.append(item)
            elif (now - item.created_at) <= ttl:
                kept.append(item)
            else:
                log.debug("Pruned expired notification: %s", item.title)
                if self._event_log is not None:
                    self._event_log.emit(
                        "notification_lifecycle",
                        action="expired",
                        title=item.title,
                        priority=item.priority,
                    )
        self._items = kept
