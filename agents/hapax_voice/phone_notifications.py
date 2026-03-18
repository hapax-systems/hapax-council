"""Phone notification router — classify, queue, and summarize.

Classifies phone notifications into IMMEDIATE / BATCHED / SUPPRESSED
based on app name, sender, operator state, and time of day.
Queues notifications during focus mode for batch delivery.

Used by PhoneAwarenessBackend and voice pipeline proactive delivery.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum

log = logging.getLogger(__name__)

_DEVICE_ID = "aecd697f91434f7797836db631b36e3b"


class Priority(Enum):
    IMMEDIATE = "immediate"  # phone calls, security alerts
    BATCHED = "batched"  # texts, emails, calendar
    SUPPRESSED = "suppressed"  # social, games, ads


# App classification (lowercase app name → priority)
_APP_PRIORITY: dict[str, Priority] = {
    "phone": Priority.IMMEDIATE,
    "dialer": Priority.IMMEDIATE,
    "messages": Priority.BATCHED,
    "gmail": Priority.BATCHED,
    "calendar": Priority.BATCHED,
    "slack": Priority.BATCHED,
    "signal": Priority.BATCHED,
    "whatsapp": Priority.BATCHED,
    "instagram": Priority.SUPPRESSED,
    "twitter": Priority.SUPPRESSED,
    "tiktok": Priority.SUPPRESSED,
    "youtube": Priority.SUPPRESSED,
    "reddit": Priority.SUPPRESSED,
    "facebook": Priority.SUPPRESSED,
}


@dataclass
class PhoneNotification:
    app: str
    title: str
    text: str
    timestamp: float
    priority: Priority
    delivered: bool = False


@dataclass
class NotificationRouter:
    """Classifies and queues phone notifications."""

    _queue: list[PhoneNotification] = field(default_factory=list)
    _focus_mode: bool = False
    _focus_started: float = 0.0
    _last_poll: float = 0.0
    _known_ids: set[str] = field(default_factory=set)

    def classify(self, app: str, title: str = "", text: str = "") -> Priority:
        """Classify a notification by app name."""
        app_lower = app.lower()
        for key, priority in _APP_PRIORITY.items():
            if key in app_lower:
                return priority
        return Priority.BATCHED  # unknown apps default to batched

    def push(self, app: str, title: str, text: str) -> PhoneNotification:
        """Push a new notification and classify it."""
        notif = PhoneNotification(
            app=app,
            title=title,
            text=text[:100],
            timestamp=time.time(),
            priority=self.classify(app, title, text),
        )
        self._queue.append(notif)
        # Trim old notifications (keep last 50)
        if len(self._queue) > 50:
            self._queue = self._queue[-50:]
        return notif

    @property
    def focus_mode(self) -> bool:
        return self._focus_mode

    def activate_focus(self) -> None:
        """Activate focus mode — hold all non-immediate notifications."""
        self._focus_mode = True
        self._focus_started = time.time()
        log.info("Focus mode activated")

    def deactivate_focus(self) -> str:
        """Deactivate focus mode and return summary of held notifications."""
        self._focus_mode = False
        duration = time.time() - self._focus_started
        held = [n for n in self._queue if n.timestamp >= self._focus_started and not n.delivered]
        summary = self._summarize(held, duration)
        # Mark as delivered
        for n in held:
            n.delivered = True
        log.info("Focus mode deactivated (%.0fs, %d held)", duration, len(held))
        return summary

    def pending_immediate(self) -> list[PhoneNotification]:
        """Get undelivered IMMEDIATE notifications."""
        return [n for n in self._queue if n.priority == Priority.IMMEDIATE and not n.delivered]

    def pending_batched(self) -> list[PhoneNotification]:
        """Get undelivered BATCHED notifications (for natural-pause delivery)."""
        if self._focus_mode:
            return []  # hold during focus
        return [n for n in self._queue if n.priority == Priority.BATCHED and not n.delivered]

    def mark_delivered(self, notifs: list[PhoneNotification]) -> None:
        for n in notifs:
            n.delivered = True

    def _summarize(self, notifications: list[PhoneNotification], duration: float) -> str:
        """Generate natural language summary of held notifications."""
        if not notifications:
            return f"You were in focus mode for {int(duration / 60)} minutes. No notifications."

        by_app: dict[str, int] = {}
        for n in notifications:
            by_app[n.app] = by_app.get(n.app, 0) + 1

        parts = []
        for app, count in sorted(by_app.items(), key=lambda x: -x[1]):
            if count == 1:
                parts.append(f"1 from {app}")
            else:
                parts.append(f"{count} from {app}")

        summary = (
            f"You were in focus mode for {int(duration / 60)} minutes. "
            f"{len(notifications)} notifications: {', '.join(parts)}."
        )
        return summary

    @property
    def stats(self) -> dict:
        return {
            "focus_mode": self._focus_mode,
            "total_queued": len(self._queue),
            "pending_immediate": len(self.pending_immediate()),
            "pending_batched": len(self.pending_batched()),
        }
