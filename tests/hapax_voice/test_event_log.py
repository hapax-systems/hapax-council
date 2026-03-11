"""Tests for the EventLog JSONL writer."""
import datetime
import json
from pathlib import Path

from agents.hapax_voice.event_log import EventLog


def test_emit_writes_jsonl(tmp_path):
    elog = EventLog(base_dir=tmp_path, retention_days=7)
    elog.emit("test_event", foo="bar", count=42)

    files = list(tmp_path.glob("events-*.jsonl"))
    assert len(files) == 1

    lines = files[0].read_text().strip().split("\n")
    assert len(lines) == 1

    event = json.loads(lines[0])
    assert event["type"] == "test_event"
    assert event["foo"] == "bar"
    assert event["count"] == 42
    assert event["source_service"] == "hapax-voice"
    assert "ts" in event
    assert "session_id" in event


def test_emit_includes_session_id(tmp_path):
    elog = EventLog(base_dir=tmp_path)
    elog.set_session_id("abc123")
    elog.emit("test_event")

    files = list(tmp_path.glob("events-*.jsonl"))
    event = json.loads(files[0].read_text().strip())
    assert event["session_id"] == "abc123"


def test_emit_session_id_none_when_unset(tmp_path):
    elog = EventLog(base_dir=tmp_path)
    elog.emit("test_event")

    files = list(tmp_path.glob("events-*.jsonl"))
    event = json.loads(files[0].read_text().strip())
    assert event["session_id"] is None


def test_emit_multiple_events(tmp_path):
    elog = EventLog(base_dir=tmp_path)
    elog.emit("event_a", x=1)
    elog.emit("event_b", x=2)
    elog.emit("event_c", x=3)

    files = list(tmp_path.glob("events-*.jsonl"))
    lines = files[0].read_text().strip().split("\n")
    assert len(lines) == 3
    types = [json.loads(l)["type"] for l in lines]
    assert types == ["event_a", "event_b", "event_c"]


def test_cleanup_old_files(tmp_path):
    for i in range(5):
        day = datetime.date.today() - datetime.timedelta(days=i + 20)
        (tmp_path / f"events-{day.isoformat()}.jsonl").write_text("{}\n")

    elog = EventLog(base_dir=tmp_path, retention_days=7)
    elog.cleanup()

    remaining = list(tmp_path.glob("events-*.jsonl"))
    assert len(remaining) == 0


def test_cleanup_keeps_recent_files(tmp_path):
    today = datetime.date.today()
    (tmp_path / f"events-{today.isoformat()}.jsonl").write_text("{}\n")
    yesterday = today - datetime.timedelta(days=1)
    (tmp_path / f"events-{yesterday.isoformat()}.jsonl").write_text("{}\n")
    old = today - datetime.timedelta(days=30)
    (tmp_path / f"events-{old.isoformat()}.jsonl").write_text("{}\n")

    elog = EventLog(base_dir=tmp_path, retention_days=7)
    elog.cleanup()

    remaining = sorted(p.name for p in tmp_path.glob("events-*.jsonl"))
    assert len(remaining) == 2


def test_disabled_event_log(tmp_path):
    elog = EventLog(base_dir=tmp_path, enabled=False)
    elog.emit("test_event", foo="bar")

    files = list(tmp_path.glob("events-*.jsonl"))
    assert len(files) == 0
