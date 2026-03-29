"""Tests for hapax_daimonion notification queue."""

from __future__ import annotations

import time

from agents.hapax_daimonion.notification_queue import (
    NotificationQueue,
    VoiceNotification,
)


def test_enqueue_dequeue() -> None:
    q = NotificationQueue()
    n = VoiceNotification(title="Test", message="Hello", priority="normal", source="test")
    q.enqueue(n)
    assert q.pending_count == 1
    result = q.next()
    assert result is not None
    assert result.title == "Test"
    assert q.pending_count == 0


def test_urgent_first() -> None:
    q = NotificationQueue()
    low = VoiceNotification(title="Low", message="low", priority="low", source="test")
    normal = VoiceNotification(title="Normal", message="normal", priority="normal", source="test")
    urgent = VoiceNotification(title="Urgent", message="urgent", priority="urgent", source="test")
    q.enqueue(low)
    q.enqueue(normal)
    q.enqueue(urgent)
    assert q.next().title == "Urgent"
    assert q.next().title == "Normal"
    assert q.next().title == "Low"


def test_ttl_zero_still_available() -> None:
    q = NotificationQueue()
    n = VoiceNotification(title="Low", message="low prio", priority="low", source="test")
    q.enqueue(n)
    # TTL=0 means deliver-or-discard, should still be available immediately
    result = q.next()
    assert result is not None
    assert result.title == "Low"


def test_expired_items_pruned() -> None:
    q = NotificationQueue(ttls={"urgent": 1, "normal": 1, "low": 0})
    n = VoiceNotification(title="Expires", message="bye", priority="urgent", source="test")
    q.enqueue(n)
    time.sleep(1.1)
    result = q.next()
    assert result is None
    assert q.pending_count == 0


def test_requeue() -> None:
    q = NotificationQueue()
    n = VoiceNotification(title="Retry", message="again", priority="normal", source="test")
    q.enqueue(n)
    item = q.next()
    assert q.pending_count == 0
    q.requeue(item)
    assert q.pending_count == 1
    again = q.next()
    assert again.title == "Retry"
