"""Tests for notification lifecycle events."""

from unittest.mock import MagicMock

from agents.hapax_voice.notification_queue import NotificationQueue, VoiceNotification


def test_notification_emits_queued_event():
    q = NotificationQueue()
    mock_log = MagicMock()
    q.set_event_log(mock_log)

    n = VoiceNotification(title="Test", message="msg", priority="normal", source="test")
    q.enqueue(n)

    mock_log.emit.assert_called_once()
    call = mock_log.emit.call_args
    assert call[0][0] == "notification_lifecycle"
    assert call[1]["action"] == "queued"
    assert call[1]["title"] == "Test"
    assert call[1]["priority"] == "normal"


def test_notification_emits_expired_event():
    q = NotificationQueue(ttls={"urgent": 0, "normal": 1, "low": 0})
    mock_log = MagicMock()
    q.set_event_log(mock_log)

    n = VoiceNotification(title="Old", message="", priority="normal", source="test")
    q._items.append(n)
    n.created_at = n.created_at - 100  # make it old

    mock_log.emit.reset_mock()
    q.prune_expired()

    calls = [c for c in mock_log.emit.call_args_list if c[0][0] == "notification_lifecycle"]
    assert len(calls) == 1
    assert calls[0][1]["action"] == "expired"


def test_notification_no_event_without_log():
    q = NotificationQueue()
    n = VoiceNotification(title="Test", message="", priority="normal", source="test")
    q.enqueue(n)
    q.prune_expired()
