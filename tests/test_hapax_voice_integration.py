"""Integration tests for VoiceDaemon — verifies subsystem wiring."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest


def test_daemon_subsystem_init():
    """VoiceDaemon initialises all subsystems from default config."""
    from agents.hapax_voice.__main__ import VoiceDaemon

    daemon = VoiceDaemon()
    assert daemon.session is not None
    assert daemon.presence is not None
    assert daemon.gate is not None
    assert daemon.notifications is not None
    assert daemon.hotkey is not None
    assert daemon.wake_word is not None
    assert daemon.tts is not None


@pytest.mark.asyncio
async def test_daemon_starts_and_stops():
    """Daemon main loop starts, runs briefly, then stops cleanly."""
    from agents.hapax_voice.__main__ import VoiceDaemon

    daemon = VoiceDaemon()

    async def stop_after_delay():
        await asyncio.sleep(0.5)
        daemon.stop()

    with (
        patch.object(daemon.hotkey, "start", new_callable=AsyncMock),
        patch.object(daemon.hotkey, "stop", new_callable=AsyncMock),
    ):
        task = asyncio.create_task(stop_after_delay())
        await daemon.run()
        await task

    assert daemon.session.state == "idle"


@pytest.mark.asyncio
async def test_daemon_hotkey_toggle():
    """Hotkey 'toggle' command opens and closes sessions."""
    from agents.hapax_voice.__main__ import VoiceDaemon

    daemon = VoiceDaemon()
    await daemon._handle_hotkey("toggle")
    assert daemon.session.is_active
    await daemon._handle_hotkey("toggle")
    assert not daemon.session.is_active


@pytest.mark.asyncio
async def test_daemon_hotkey_open_close():
    """Hotkey 'open' and 'close' commands work explicitly."""
    from agents.hapax_voice.__main__ import VoiceDaemon

    daemon = VoiceDaemon()
    await daemon._handle_hotkey("open")
    assert daemon.session.is_active
    await daemon._handle_hotkey("close")
    assert not daemon.session.is_active


@pytest.mark.asyncio
async def test_daemon_hotkey_status_no_crash():
    """Hotkey 'status' command runs without error."""
    from agents.hapax_voice.__main__ import VoiceDaemon

    daemon = VoiceDaemon()
    # Should not raise
    await daemon._handle_hotkey("status")


def test_daemon_session_timeout():
    """Session auto-closes after silence timeout expires."""
    from agents.hapax_voice.__main__ import VoiceDaemon

    daemon = VoiceDaemon()
    daemon.session.silence_timeout_s = 1
    daemon.session.open(trigger="test")
    assert daemon.session.is_active
    time.sleep(1.1)
    if daemon.session.is_timed_out:
        daemon.session.close(reason="silence_timeout")
    assert not daemon.session.is_active


@pytest.mark.asyncio
async def test_daemon_loop_handles_timeout():
    """Daemon main loop detects silence timeout and closes session."""
    from agents.hapax_voice.__main__ import VoiceDaemon

    daemon = VoiceDaemon()
    daemon.session.silence_timeout_s = 1
    daemon.session.open(trigger="test")

    async def stop_after_timeout():
        await asyncio.sleep(1.5)
        daemon.stop()

    with (
        patch.object(daemon.hotkey, "start", new_callable=AsyncMock),
        patch.object(daemon.hotkey, "stop", new_callable=AsyncMock),
    ):
        task = asyncio.create_task(stop_after_timeout())
        await daemon.run()
        await task

    # The loop should have detected the timeout and closed the session
    assert not daemon.session.is_active
    assert daemon.session.state == "idle"


def test_gate_blocks_during_active_session():
    """Context gate blocks interrupts when session is active."""
    from agents.hapax_voice.__main__ import VoiceDaemon

    daemon = VoiceDaemon()
    daemon.session.open(trigger="test")
    with (
        patch.object(daemon.gate, "_get_sink_volume", return_value=0.3),
        patch.object(daemon.gate, "_check_studio", return_value=(True, "")),
    ):
        result = daemon.gate.check()
    assert not result.eligible
    assert "Session active" in result.reason


def test_gate_allows_when_idle():
    """Context gate permits interrupts when session is idle and conditions met."""
    from agents.hapax_voice.__main__ import VoiceDaemon

    daemon = VoiceDaemon()
    with (
        patch.object(daemon.gate, "_get_sink_volume", return_value=0.3),
        patch.object(daemon.gate, "_check_studio", return_value=(True, "")),
        patch.object(daemon.gate, "_check_ambient", return_value=(True, "")),
    ):
        result = daemon.gate.check()
    assert result.eligible


def test_notification_queue_wired():
    """Notification queue is wired with config TTLs."""
    from agents.hapax_voice.__main__ import VoiceDaemon
    from agents.hapax_voice.notification_queue import VoiceNotification

    daemon = VoiceDaemon()
    n = VoiceNotification(title="Test", message="Hello", priority="normal", source="test")
    daemon.notifications.enqueue(n)
    assert daemon.notifications.pending_count == 1
    item = daemon.notifications.next()
    assert item is not None
    assert item.title == "Test"


def test_wake_word_opens_session():
    """Wake word callback opens a session when idle."""
    from agents.hapax_voice.__main__ import VoiceDaemon

    daemon = VoiceDaemon()
    assert not daemon.session.is_active
    daemon._on_wake_word()
    assert daemon.session.is_active
    assert daemon.session.trigger == "wake_word"


def test_wake_word_noop_when_active():
    """Wake word callback does nothing when session already active."""
    from agents.hapax_voice.__main__ import VoiceDaemon

    daemon = VoiceDaemon()
    daemon.session.open(trigger="hotkey")
    daemon._on_wake_word()
    assert daemon.session.trigger == "hotkey"  # unchanged


@pytest.mark.asyncio
async def test_ntfy_callback_enqueues():
    """ntfy callback enqueues notifications."""
    from agents.hapax_voice.__main__ import VoiceDaemon
    from agents.hapax_voice.notification_queue import VoiceNotification

    daemon = VoiceDaemon()
    n = VoiceNotification(title="Alert", message="disk full", priority="urgent", source="ntfy")
    await daemon._ntfy_callback(n)
    assert daemon.notifications.pending_count == 1
    item = daemon.notifications.next()
    assert item.title == "Alert"


@pytest.mark.asyncio
async def test_daemon_starts_background_tasks():
    """Daemon starts ntfy and proactive delivery as background tasks."""
    from agents.hapax_voice.__main__ import VoiceDaemon

    daemon = VoiceDaemon()

    async def stop_quickly():
        await asyncio.sleep(0.3)
        daemon.stop()

    with (
        patch.object(daemon.hotkey, "start", new_callable=AsyncMock),
        patch.object(daemon.hotkey, "stop", new_callable=AsyncMock),
        patch("agents.hapax_voice.__main__.subscribe_ntfy", new_callable=AsyncMock),
    ):
        task = asyncio.create_task(stop_quickly())
        await daemon.run()
        await task

    # Background tasks should have been cancelled during shutdown
    assert len(daemon._background_tasks) == 0
