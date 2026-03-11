"""Cross-component integration tests for hapax-voice subsystems.

These tests verify that multiple subsystems work together correctly.
All external services are mocked, but the internal wiring between
components is real.
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_voice.context_gate import ContextGate
from agents.hapax_voice.event_log import EventLog
from agents.hapax_voice.notification_queue import NotificationQueue, VoiceNotification
from agents.hapax_voice.presence import PresenceDetector
from agents.hapax_voice.screen_models import (
    GearObservation,
    Issue,
    WorkspaceAnalysis,
)
from agents.hapax_voice.session import SessionManager
from agents.hapax_voice.workspace_monitor import WorkspaceMonitor


def _make_analysis(**kwargs) -> WorkspaceAnalysis:
    """Build a WorkspaceAnalysis with sensible defaults."""
    defaults = dict(
        app="terminal",
        context="editing code",
        summary="Operator is writing Python in the terminal.",
        issues=[],
        suggestions=[],
        keywords=["python", "terminal"],
        operator_present=True,
        operator_activity="typing",
        operator_attention="screen",
        gear_state=[],
        workspace_change=False,
    )
    defaults.update(kwargs)
    return WorkspaceAnalysis(**defaults)


def _read_events(tmp_path) -> list[dict]:
    """Read all events from JSONL files in tmp_path."""
    events = []
    for p in sorted(tmp_path.glob("events-*.jsonl")):
        for line in p.read_text().splitlines():
            if line.strip():
                events.append(json.loads(line))
    return events


def _events_of_type(tmp_path, event_type: str) -> list[dict]:
    """Filter events by type."""
    return [e for e in _read_events(tmp_path) if e["type"] == event_type]


# ---------------------------------------------------------------------------
# Test 1: Full analysis pipeline with events
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_full_analysis_pipeline_with_events(tmp_path):
    """Wire WorkspaceMonitor with real EventLog, mock analyzer + capturer.

    Verify EventLog receives analysis_complete event and analysis is cached.
    """
    event_log = EventLog(base_dir=tmp_path, enabled=True)
    analysis = _make_analysis(
        gear_state=[GearObservation(device="SP-404", powered=True, display_content="A01", notes="")]
    )

    monitor = WorkspaceMonitor(enabled=True)
    monitor.set_event_log(event_log)

    # Mock screen capturer to return a fake base64 image
    mock_capturer = MagicMock()
    mock_capturer.capture.return_value = "fake_base64_screenshot"
    monitor._screen_capturer = mock_capturer

    # Mock analyzer to return our analysis
    mock_analyzer = AsyncMock()
    mock_analyzer.analyze.return_value = analysis
    monitor._analyzer = mock_analyzer

    await monitor._capture_and_analyze()
    event_log.close()

    # Analysis should be cached
    assert monitor.latest_analysis is not None
    assert monitor.latest_analysis.app == "terminal"
    assert monitor.is_analysis_stale is False

    # EventLog should have analysis_complete event
    events = _events_of_type(tmp_path, "analysis_complete")
    assert len(events) == 1
    assert events[0]["app"] == "terminal"
    assert events[0]["operator_present"] is True
    assert events[0]["gear_count"] == 1
    assert "latency_ms" in events[0]
    assert events[0]["images_sent"] == 1  # screen only, no webcams


# ---------------------------------------------------------------------------
# Test 2: Analysis failure emits failed event
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_analysis_failure_emits_failed_event(tmp_path):
    """Mock analyzer returns None. Verify analysis_failed event and no cache."""
    event_log = EventLog(base_dir=tmp_path, enabled=True)

    monitor = WorkspaceMonitor(enabled=True)
    monitor.set_event_log(event_log)

    mock_capturer = MagicMock()
    mock_capturer.capture.return_value = "fake_base64"
    monitor._screen_capturer = mock_capturer

    mock_analyzer = AsyncMock()
    mock_analyzer.analyze.return_value = None
    monitor._analyzer = mock_analyzer

    await monitor._capture_and_analyze()
    event_log.close()

    assert monitor.latest_analysis is None

    events = _events_of_type(tmp_path, "analysis_failed")
    assert len(events) == 1
    assert "error" in events[0]
    assert events[0]["latency_ms"] >= 0


# ---------------------------------------------------------------------------
# Test 3: Proactive routing chain
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_proactive_routing_chain(tmp_path):
    """Analysis with high-confidence error routes to NotificationQueue.

    Verify notification is dequeue-able and EventLog records events.
    """
    event_log = EventLog(base_dir=tmp_path, enabled=True)
    queue = NotificationQueue()
    queue.set_event_log(event_log)

    analysis = _make_analysis(
        issues=[Issue(severity="error", description="Docker container crashed", confidence=0.95)]
    )

    monitor = WorkspaceMonitor(enabled=True, proactive_min_confidence=0.8)
    monitor.set_event_log(event_log)
    monitor.set_notification_queue(queue)

    mock_capturer = MagicMock()
    mock_capturer.capture.return_value = "fake_base64"
    monitor._screen_capturer = mock_capturer

    mock_analyzer = AsyncMock()
    mock_analyzer.analyze.return_value = analysis
    monitor._analyzer = mock_analyzer

    await monitor._capture_and_analyze()
    event_log.close()

    # Notification should be in queue
    assert queue.pending_count == 1
    notification = queue.next()
    assert notification is not None
    assert notification.title == "Workspace Alert"
    assert "Docker container crashed" in notification.message

    # EventLog should have both analysis_complete and notification_lifecycle
    analysis_events = _events_of_type(tmp_path, "analysis_complete")
    assert len(analysis_events) == 1

    notif_events = _events_of_type(tmp_path, "notification_lifecycle")
    assert len(notif_events) == 1
    assert notif_events[0]["action"] == "queued"
    assert notif_events[0]["source"] == "workspace"


# ---------------------------------------------------------------------------
# Test 4: Gate blocks during session
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_gate_blocks_during_session(tmp_path):
    """Open session then check gate. Should block with 'Session active'."""
    event_log = EventLog(base_dir=tmp_path, enabled=True)
    session = SessionManager(silence_timeout_s=30)
    gate = ContextGate(session=session, ambient_classification=False)
    gate.set_event_log(event_log)

    session.open(trigger="test")
    result = gate.check()
    event_log.close()

    assert result.eligible is False
    assert "Session active" in result.reason

    events = _events_of_type(tmp_path, "gate_decision")
    assert len(events) == 1
    assert events[0]["eligible"] is False
    assert "Session active" in events[0]["reason"]


# ---------------------------------------------------------------------------
# Test 5: Gate allows when idle and quiet
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_gate_allows_when_idle_and_quiet(tmp_path):
    """Session idle, low volume, no MIDI, ambient disabled. Gate allows."""
    event_log = EventLog(base_dir=tmp_path, enabled=True)
    session = SessionManager(silence_timeout_s=30)
    gate = ContextGate(session=session, ambient_classification=False)
    gate.set_event_log(event_log)

    # Mock wpctl to return low volume
    mock_wpctl_result = MagicMock()
    mock_wpctl_result.stdout = "Volume: 0.30"

    # Mock aconnect to return empty (no active MIDI connections)
    mock_aconnect_result = MagicMock()
    mock_aconnect_result.stdout = "client 0: 'System' [type=kernel]\n"

    with patch("agents.hapax_voice.context_gate.subprocess.run") as mock_run:

        def route_subprocess(cmd, **kwargs):
            if cmd[0] == "wpctl":
                return mock_wpctl_result
            elif cmd[0] == "aconnect":
                return mock_aconnect_result
            return MagicMock(stdout="")

        mock_run.side_effect = route_subprocess
        result = gate.check()

    event_log.close()

    assert result.eligible is True

    events = _events_of_type(tmp_path, "gate_decision")
    assert len(events) == 1
    assert events[0]["eligible"] is True


# ---------------------------------------------------------------------------
# Test 6: Presence fusion drives score
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_presence_fusion_drives_gate_context():
    """Record VAD + face events and verify presence score is definitely_present."""
    presence = PresenceDetector(window_minutes=5, vad_threshold=0.4)

    # Record 5 VAD events above threshold
    for _ in range(5):
        presence.record_vad_event(0.8)

    # Record face detection
    presence.record_face_event(detected=True, count=1)

    assert presence.score == "definitely_present"
    assert presence.face_detected is True
    assert presence.event_count == 5


# ---------------------------------------------------------------------------
# Test 7: Session lifecycle with events
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_session_lifecycle_with_events(tmp_path):
    """Manually emit session_lifecycle events as __main__.py does.

    SessionManager itself doesn't emit events, so we replicate the
    daemon's pattern to verify the event structure.
    """
    event_log = EventLog(base_dir=tmp_path, enabled=True)
    session = SessionManager(silence_timeout_s=30)

    # Open session (mimic daemon pattern)
    session.open(trigger="hotkey")
    event_log.set_session_id(session.session_id)
    event_log.emit("session_lifecycle", action="opened", trigger="hotkey")

    # Mark activity
    session.mark_activity()

    # Small delay for measurable duration
    time.sleep(0.01)

    # Close session (mimic daemon pattern)
    duration = time.monotonic() - session._opened_at
    event_log.emit(
        "session_lifecycle", action="closed", reason="test", duration_s=round(duration, 1)
    )
    event_log.set_session_id(None)
    session.close(reason="test")

    event_log.close()

    events = _events_of_type(tmp_path, "session_lifecycle")
    assert len(events) == 2

    opened = events[0]
    assert opened["action"] == "opened"
    assert opened["trigger"] == "hotkey"
    assert opened["session_id"] is not None

    closed = events[1]
    assert closed["action"] == "closed"
    assert closed["reason"] == "test"
    assert "duration_s" in closed


# ---------------------------------------------------------------------------
# Test 8: Notification lifecycle with events
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_notification_lifecycle_with_events(tmp_path):
    """Enqueue notification, verify queued event. Expire another, verify expired event."""
    event_log = EventLog(base_dir=tmp_path, enabled=True)
    queue = NotificationQueue(ttls={"urgent": 1800, "normal": 1, "low": 0})
    queue.set_event_log(event_log)

    # Enqueue a notification
    queue.enqueue(
        VoiceNotification(
            title="Test Alert",
            message="Something happened",
            priority="normal",
            source="test",
        )
    )

    # Dequeue it (should succeed)
    notification = queue.next()
    assert notification is not None
    assert notification.title == "Test Alert"

    # Enqueue another with very short TTL that will expire
    # Set created_at to the past so it expires immediately on prune
    expired_notif = VoiceNotification(
        title="Expired Alert",
        message="This will expire",
        priority="normal",
        source="test",
        created_at=time.monotonic() - 100,  # 100 seconds ago, TTL is 1
    )
    queue.enqueue(expired_notif)
    # Trigger prune by accessing pending_count
    _ = queue.pending_count

    event_log.close()

    events = _events_of_type(tmp_path, "notification_lifecycle")
    # Should have: queued (first), queued (second), expired (second)
    assert len(events) == 3

    queued_events = [e for e in events if e["action"] == "queued"]
    assert len(queued_events) == 2

    expired_events = [e for e in events if e["action"] == "expired"]
    assert len(expired_events) == 1
    assert expired_events[0]["title"] == "Expired Alert"


# ---------------------------------------------------------------------------
# Test 9: RAG augmentation failure is non-fatal
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_workspace_monitor_rag_augmentation_failure(tmp_path):
    """Mock Qdrant import to fail. Analysis should still complete."""
    event_log = EventLog(base_dir=tmp_path, enabled=True)
    analysis = _make_analysis()

    monitor = WorkspaceMonitor(enabled=True)
    monitor.set_event_log(event_log)

    mock_capturer = MagicMock()
    mock_capturer.capture.return_value = "fake_base64"
    monitor._screen_capturer = mock_capturer

    mock_analyzer = AsyncMock()
    mock_analyzer.analyze.return_value = analysis
    monitor._analyzer = mock_analyzer

    # Set a previous analysis with keywords so _query_rag is attempted
    monitor._latest_analysis = _make_analysis(keywords=["docker", "error"])

    with patch("agents.hapax_voice.workspace_monitor.WorkspaceMonitor._query_rag") as mock_rag:
        mock_rag.return_value = None  # Simulates failure fallback
        await monitor._capture_and_analyze()

    event_log.close()

    # Analysis should still succeed
    assert monitor.latest_analysis is not None
    assert monitor.latest_analysis.app == "terminal"

    events = _events_of_type(tmp_path, "analysis_complete")
    assert len(events) == 1


# ---------------------------------------------------------------------------
# Test 10: End-to-end analysis to notification
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_end_to_end_analysis_to_notification(tmp_path):
    """Full chain: capture -> analyze -> route issue -> notification available.

    Verify the entire chain with EventLog recording all events.
    """
    event_log = EventLog(base_dir=tmp_path, enabled=True)

    # Real components wired together
    queue = NotificationQueue()
    queue.set_event_log(event_log)

    analysis = _make_analysis(
        issues=[Issue(severity="error", description="GPU VRAM at 23.5GB", confidence=0.92)],
        gear_state=[
            GearObservation(
                device="Digitakt II", powered=True, display_content="Pattern A01", notes=""
            ),
            GearObservation(device="SP-404MKII", powered=True, display_content="PAD", notes=""),
        ],
    )

    monitor = WorkspaceMonitor(enabled=True, proactive_min_confidence=0.8)
    monitor.set_event_log(event_log)
    monitor.set_notification_queue(queue)

    mock_capturer = MagicMock()
    mock_capturer.capture.return_value = "fake_base64_screen"
    monitor._screen_capturer = mock_capturer

    mock_analyzer = AsyncMock()
    mock_analyzer.analyze.return_value = analysis
    monitor._analyzer = mock_analyzer

    # Run the pipeline
    await monitor._capture_and_analyze()
    event_log.close()

    # Notification should be available
    assert queue.pending_count == 1
    notification = queue.next()
    assert notification is not None
    assert "GPU VRAM" in notification.message
    assert notification.priority == "normal"
    assert notification.source == "workspace"

    # Verify full event trail
    all_events = _read_events(tmp_path)
    event_types = [e["type"] for e in all_events]

    assert "analysis_complete" in event_types
    assert "notification_lifecycle" in event_types

    # Verify analysis_complete details
    ac = _events_of_type(tmp_path, "analysis_complete")[0]
    assert ac["gear_count"] == 2
    assert ac["operator_present"] is True

    # Verify notification details
    nl = _events_of_type(tmp_path, "notification_lifecycle")[0]
    assert nl["action"] == "queued"
    assert nl["title"] == "Workspace Alert"


# --- Audio pipeline integration ---


def _make_audio_frame(n_samples: int = 480) -> bytes:
    """Create a fake PCM frame (480 int16 samples = 960 bytes)."""
    import struct

    return struct.pack(f"<{n_samples}h", *([100] * n_samples))


class TestAudioPipelineIntegration:
    """End-to-end audio pipeline: input → distribution → wake word → session."""

    @pytest.mark.asyncio
    async def test_audio_to_wake_word_to_session(self):
        """Audio frame triggers wake word which opens a session."""
        from agents.hapax_voice.__main__ import VoiceDaemon

        daemon = object.__new__(VoiceDaemon)
        daemon._running = True
        daemon.event_log = MagicMock()
        daemon.presence = MagicMock()
        daemon.presence.process_audio_frame.return_value = 0.5  # open VAD gate
        daemon._gemini_session = None
        daemon.session = MagicMock()
        daemon.session.is_active = False
        daemon.session.session_id = "test123"

        session_opened = False

        def process_and_trigger(audio_np):
            nonlocal session_opened
            if not session_opened:
                session_opened = True
                daemon.session.open(trigger="wake_word")
                daemon._running = False

        daemon.wake_word = MagicMock()
        daemon.wake_word.frame_length = 1280
        daemon.wake_word.process_audio = process_and_trigger

        frame = _make_audio_frame()
        audio_input = AsyncMock()
        call_count = 0
        # Need enough frames to fill the wake word buffer (1280 samples = 2560 bytes).
        # Each frame is 480 samples = 960 bytes, so we need ceil(2560/960) = 3 frames.
        _frames_needed = 3

        async def get_frame_side_effect(timeout=1.0):
            nonlocal call_count
            call_count += 1
            if call_count <= _frames_needed:
                return frame
            return None

        audio_input.get_frame = get_frame_side_effect
        daemon._audio_input = audio_input

        await daemon._audio_loop()

        assert session_opened
        daemon.session.open.assert_called_once_with(trigger="wake_word")
        assert daemon.presence.process_audio_frame.call_count >= 1
