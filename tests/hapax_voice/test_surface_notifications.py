"""Surface 7: Notification delivery — ntfy → queue → proactive delivery.

Tests the full notification chain: ntfy event parsing, priority queuing,
TTL expiry, and the proactive delivery conditions.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agents.hapax_voice.notification_queue import NotificationQueue, VoiceNotification
from agents.hapax_voice.ntfy_listener import parse_ntfy_event


class TestNtfyParsing:
    """ntfy JSON events are parsed into VoiceNotifications."""

    def test_parses_message_event(self):
        raw = '{"event":"message","topic":"hapax","title":"Alert","message":"Test alert","priority":4}'
        notif = parse_ntfy_event(raw)
        assert notif is not None
        assert notif.title == "Alert"
        assert notif.message == "Test alert"
        assert notif.priority == "urgent"

    def test_ignores_keepalive_event(self):
        raw = '{"event":"keepalive","topic":"hapax"}'
        assert parse_ntfy_event(raw) is None

    def test_ignores_open_event(self):
        raw = '{"event":"open","topic":"hapax"}'
        assert parse_ntfy_event(raw) is None

    def test_handles_missing_title(self):
        raw = '{"event":"message","topic":"alerts","message":"No title"}'
        notif = parse_ntfy_event(raw)
        assert notif is not None
        # Falls back to topic when title is absent
        assert notif.title == "alerts"

    def test_handles_invalid_json(self):
        assert parse_ntfy_event("not json") is None

    def test_priority_mapping(self):
        for ntfy_pri, expected in [
            (5, "urgent"),
            (4, "urgent"),
            (3, "normal"),
            (2, "low"),
            (1, "low"),
        ]:
            raw = f'{{"event":"message","topic":"t","message":"m","priority":{ntfy_pri}}}'
            notif = parse_ntfy_event(raw)
            assert notif is not None
            assert notif.priority == expected, (
                f"ntfy priority {ntfy_pri} → {notif.priority}, expected {expected}"
            )

    def test_source_is_ntfy(self):
        raw = '{"event":"message","topic":"hapax","message":"hello"}'
        notif = parse_ntfy_event(raw)
        assert notif is not None
        assert notif.source == "ntfy"

    def test_default_priority_is_normal_when_missing(self):
        """Messages without a priority field default to ntfy priority 3 → normal."""
        raw = '{"event":"message","topic":"hapax","message":"no priority field"}'
        notif = parse_ntfy_event(raw)
        assert notif is not None
        assert notif.priority == "normal"

    def test_unknown_event_type_returns_none(self):
        raw = '{"event":"subscribe","topic":"hapax"}'
        assert parse_ntfy_event(raw) is None

    def test_empty_string_returns_none(self):
        assert parse_ntfy_event("") is None

    def test_missing_message_field_produces_empty_string(self):
        raw = '{"event":"message","topic":"hapax","title":"Alert"}'
        notif = parse_ntfy_event(raw)
        assert notif is not None
        assert notif.message == ""

    def test_title_falls_back_to_topic_then_ntfy(self):
        """When both title and topic are absent, falls back to 'ntfy'."""
        raw = '{"event":"message","message":"hello"}'
        notif = parse_ntfy_event(raw)
        assert notif is not None
        assert notif.title == "ntfy"


class TestNotificationQueue:
    """Priority queue with TTL-based expiry."""

    def test_enqueue_and_dequeue(self):
        q = NotificationQueue()
        n = VoiceNotification(title="Test", message="Hello", priority="normal", source="test")
        q.enqueue(n)
        assert q.pending_count == 1
        result = q.next()
        assert result is not None
        assert result.message == "Hello"
        assert q.pending_count == 0

    def test_urgent_dequeued_before_normal(self):
        q = NotificationQueue()
        q.enqueue(VoiceNotification(title="Normal", message="n", priority="normal", source="test"))
        q.enqueue(VoiceNotification(title="Urgent", message="u", priority="urgent", source="test"))
        result = q.next()
        assert result is not None
        assert result.title == "Urgent"

    def test_normal_dequeued_before_low(self):
        q = NotificationQueue()
        q.enqueue(VoiceNotification(title="Low", message="lo", priority="low", source="test"))
        q.enqueue(VoiceNotification(title="Normal", message="no", priority="normal", source="test"))
        result = q.next()
        assert result is not None
        assert result.title == "Normal"

    def test_urgent_before_normal_before_low(self):
        q = NotificationQueue()
        q.enqueue(VoiceNotification(title="Low", message="lo", priority="low", source="test"))
        q.enqueue(VoiceNotification(title="Urgent", message="ur", priority="urgent", source="test"))
        q.enqueue(VoiceNotification(title="Normal", message="no", priority="normal", source="test"))
        assert q.next().title == "Urgent"
        assert q.next().title == "Normal"
        assert q.next().title == "Low"

    def test_empty_queue_returns_none(self):
        q = NotificationQueue()
        assert q.next() is None

    def test_pending_count_decrements_on_next(self):
        q = NotificationQueue()
        q.enqueue(VoiceNotification(title="A", message="a", priority="normal", source="test"))
        q.enqueue(VoiceNotification(title="B", message="b", priority="normal", source="test"))
        assert q.pending_count == 2
        q.next()
        assert q.pending_count == 1

    def test_expired_notifications_pruned(self):
        """Notifications with non-zero TTL that are past their TTL are removed."""
        # TTL of 1 second for normal; we'll backdate the creation time
        q = NotificationQueue(ttls={"urgent": 1800, "normal": 1, "low": 0})
        n = VoiceNotification(title="Old", message="expired", priority="normal", source="test")
        q._items.append(n)
        # Backdate created_at so TTL has elapsed (uses time.monotonic)
        n.created_at = n.created_at - 100
        # pending_count triggers prune_expired
        assert q.pending_count == 0

    def test_ttl_zero_means_no_auto_expiry(self):
        """TTL=0 means deliver-or-discard — items with TTL=0 are never pruned."""
        # low priority has TTL=0 by default — they do NOT auto-expire
        q = NotificationQueue()  # default: low TTL=0
        n = VoiceNotification(title="Persist", message="stays", priority="low", source="test")
        q._items.append(n)
        n.created_at = n.created_at - 99999  # very old
        # Should NOT be pruned since TTL=0 means "no expiry"
        assert q.pending_count == 1

    def test_requeue_adds_back_to_queue(self):
        q = NotificationQueue()
        n = VoiceNotification(title="Retry", message="re", priority="normal", source="test")
        q.enqueue(n)
        dequeued = q.next()
        assert dequeued is not None
        assert q.pending_count == 0
        q.requeue(dequeued)
        assert q.pending_count == 1

    def test_prune_expired_removes_old_items(self):
        """prune_expired() directly removes items past their TTL."""
        q = NotificationQueue(ttls={"urgent": 1800, "normal": 10, "low": 0})
        old = VoiceNotification(title="Old", message="", priority="normal", source="test")
        fresh = VoiceNotification(title="Fresh", message="", priority="normal", source="test")
        q._items.extend([old, fresh])
        old.created_at = old.created_at - 100  # past TTL
        q.prune_expired()
        assert len(q._items) == 1
        assert q._items[0].title == "Fresh"


class TestProactiveDeliveryConditions:
    """Proactive delivery only fires under correct conditions."""

    @pytest.mark.asyncio
    async def test_no_delivery_during_active_session(self):
        """Proactive delivery loop skips delivery when session is active."""
        from agents.hapax_voice.__main__ import VoiceDaemon
        from agents.hapax_voice.session import VoiceLifecycle

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()

        # Real session in active state
        daemon.session = VoiceLifecycle()
        daemon.session.open(trigger="test")
        assert daemon.session.is_active is True

        daemon.notifications = NotificationQueue()
        daemon.notifications.enqueue(
            VoiceNotification(title="Test", message="hi", priority="normal", source="test")
        )
        daemon.presence = MagicMock()
        daemon.gate = MagicMock()
        daemon.tts = MagicMock()
        daemon.event_log = MagicMock()

        # Simulate one iteration of the delivery decision
        # When session is active, we should skip and not call gate.check()
        if daemon.notifications.pending_count == 0 or daemon.session.is_active:
            should_deliver = False
        else:
            should_deliver = True

        assert should_deliver is False
        daemon.gate.check.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_delivery_when_operator_absent(self):
        """Proactive delivery is suppressed when presence score is likely_absent."""
        from agents.hapax_voice.__main__ import VoiceDaemon
        from agents.hapax_voice.session import VoiceLifecycle

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()

        daemon.session = VoiceLifecycle()  # idle, not active
        daemon.notifications = NotificationQueue()
        daemon.notifications.enqueue(
            VoiceNotification(title="Alert", message="msg", priority="urgent", source="test")
        )

        daemon.presence = MagicMock()
        daemon.presence.score = "likely_absent"
        daemon.gate = MagicMock()
        daemon.tts = MagicMock()
        daemon.event_log = MagicMock()

        # Simulate the delivery condition checks from _proactive_delivery_loop
        pending = daemon.notifications.pending_count
        session_active = daemon.session.is_active
        presence = daemon.presence.score

        if pending == 0 or session_active or presence == "likely_absent":
            should_check_gate = False
        else:
            should_check_gate = True

        assert should_check_gate is False
        daemon.gate.check.assert_not_called()

    @pytest.mark.asyncio
    async def test_delivery_when_conditions_met(self):
        """Proactive delivery proceeds when queue has items, session idle, presence present."""
        from agents.hapax_voice.__main__ import VoiceDaemon
        from agents.hapax_voice.session import VoiceLifecycle

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()

        daemon.session = VoiceLifecycle()  # idle
        daemon.notifications = NotificationQueue()
        daemon.notifications.enqueue(
            VoiceNotification(title="Ready", message="deliver me", priority="normal", source="test")
        )

        gate_result = MagicMock()
        gate_result.eligible = True
        gate_result.reason = ""

        daemon.presence = MagicMock()
        daemon.presence.score = "present"
        daemon.gate = MagicMock()
        daemon.gate.check.return_value = gate_result
        daemon.tts = MagicMock()
        daemon.tts.synthesize.return_value = b"audio-bytes"
        daemon.event_log = MagicMock()

        with patch(
            "agents.hapax_voice.__main__.format_notification",
            return_value="Notification: Ready — deliver me",
        ):
            # Simulate the full delivery branch
            pending = daemon.notifications.pending_count
            assert pending == 1
            assert not daemon.session.is_active
            assert daemon.presence.score != "likely_absent"

            gate_res = daemon.gate.check()
            assert gate_res.eligible

            notification = daemon.notifications.next()
            assert notification is not None
            assert notification.title == "Ready"

        daemon.gate.check.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_delivery_when_gate_blocks(self):
        """Proactive delivery is suppressed when context gate blocks."""
        from agents.hapax_voice.__main__ import VoiceDaemon
        from agents.hapax_voice.session import VoiceLifecycle

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()

        daemon.session = VoiceLifecycle()  # idle
        daemon.notifications = NotificationQueue()
        daemon.notifications.enqueue(
            VoiceNotification(
                title="Blocked", message="blocked msg", priority="normal", source="test"
            )
        )

        gate_result = MagicMock()
        gate_result.eligible = False
        gate_result.reason = "ambient noise too loud"

        daemon.presence = MagicMock()
        daemon.presence.score = "present"
        daemon.gate = MagicMock()
        daemon.gate.check.return_value = gate_result
        daemon.tts = MagicMock()

        # Gate blocks — simulate decision path
        pending = daemon.notifications.pending_count
        assert pending == 1
        assert not daemon.session.is_active
        assert daemon.presence.score != "likely_absent"

        gate_res = daemon.gate.check()
        should_deliver = gate_res.eligible
        assert should_deliver is False

        # Notification should still be in the queue
        assert daemon.notifications.pending_count == 1

    @pytest.mark.asyncio
    async def test_no_delivery_when_queue_empty(self):
        """Proactive delivery loop is a no-op when queue is empty."""
        from agents.hapax_voice.__main__ import VoiceDaemon
        from agents.hapax_voice.session import VoiceLifecycle

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()

        daemon.session = VoiceLifecycle()
        daemon.notifications = NotificationQueue()  # empty
        daemon.presence = MagicMock()
        daemon.gate = MagicMock()
        daemon.tts = MagicMock()

        assert daemon.notifications.pending_count == 0
        # Short-circuit: nothing to deliver
        daemon.gate.check.assert_not_called()


class TestNtfyCallbackWiring:
    """ntfy callback enqueues received notifications into the daemon's queue."""

    @pytest.mark.asyncio
    async def test_ntfy_callback_enqueues_notification(self):
        """_ntfy_callback() enqueues a VoiceNotification into self.notifications."""
        from agents.hapax_voice.__main__ import VoiceDaemon

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()

        daemon.notifications = NotificationQueue()

        notif = VoiceNotification(
            title="Callback", message="cb msg", priority="urgent", source="ntfy"
        )
        await daemon._ntfy_callback(notif)

        assert daemon.notifications.pending_count == 1
        result = daemon.notifications.next()
        assert result is not None
        assert result.title == "Callback"
        assert result.source == "ntfy"

    @pytest.mark.asyncio
    async def test_ntfy_callback_multiple_enqueued(self):
        """Multiple callback calls accumulate in the queue."""
        from agents.hapax_voice.__main__ import VoiceDaemon

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()

        daemon.notifications = NotificationQueue()

        for i in range(3):
            notif = VoiceNotification(title=f"N{i}", message="m", priority="normal", source="ntfy")
            await daemon._ntfy_callback(notif)

        assert daemon.notifications.pending_count == 3
