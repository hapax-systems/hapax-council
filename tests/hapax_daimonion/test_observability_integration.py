# tests/hapax_daimonion/test_observability_integration.py
"""Integration test: verify observability events flow end-to-end."""

import json

from agents.hapax_daimonion.context_gate import ContextGate
from agents.hapax_daimonion.event_log import EventLog
from agents.hapax_daimonion.notification_queue import NotificationQueue, VoiceNotification
from agents.hapax_daimonion.presence import PresenceDetector
from agents.hapax_daimonion.session import SessionManager


def test_full_event_flow(tmp_path):
    """Simulate a daemon lifecycle and verify JSONL output."""
    elog = EventLog(base_dir=tmp_path, retention_days=7)
    sm = SessionManager(silence_timeout_s=10)
    pd = PresenceDetector(window_minutes=5, vad_threshold=0.4)
    gate = ContextGate(session=sm, volume_threshold=0.7)
    nq = NotificationQueue()

    pd.set_event_log(elog)
    gate.set_event_log(elog)
    nq.set_event_log(elog)

    # 1. Session opens
    sm.open(trigger="hotkey")
    elog.set_session_id(sm.session_id)
    elog.emit("session_lifecycle", action="opened", trigger="hotkey")

    # 2. VAD events trigger presence transition
    for _ in range(3):
        pd.record_vad_event(0.8)
    _ = pd.score  # triggers transition event

    # 3. Notification enqueued
    nq.enqueue(VoiceNotification(title="Build done", message="OK", priority="normal", source="ci"))

    # 4. Session closes
    elog.emit("session_lifecycle", action="closed", reason="hotkey", duration_s=5.0)
    elog.set_session_id(None)
    sm.close(reason="hotkey")

    # Verify events
    elog.close()
    files = list(tmp_path.glob("events-*.jsonl"))
    assert len(files) == 1

    events = [json.loads(line) for line in files[0].read_text().strip().split("\n")]

    types = [e["type"] for e in events]
    assert "session_lifecycle" in types
    assert "presence_transition" in types
    assert "notification_lifecycle" in types

    # All events have required fields
    for e in events:
        assert "ts" in e
        assert "source_service" in e
        assert e["source_service"] == "hapax-daimonion"
        assert "session_id" in e

    # Session events have the session_id set
    session_events = [e for e in events if e["type"] == "session_lifecycle"]
    opened = [e for e in session_events if e.get("action") == "opened"]
    assert len(opened) == 1
    assert opened[0]["session_id"] is not None
