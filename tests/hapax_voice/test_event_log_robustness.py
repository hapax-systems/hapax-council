"""Robustness / failure-mode tests for EventLog."""

import datetime
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.hapax_voice.event_log import EventLog


def test_emit_survives_write_permission_error(tmp_path):
    """PermissionError on file open is caught — emit does not crash."""
    elog = EventLog(base_dir=tmp_path)
    with patch("builtins.open", side_effect=PermissionError("denied")):
        elog.emit("should_not_crash", key="val")  # must not raise


def test_emit_survives_disk_full(tmp_path):
    """OSError during write() is caught — emit does not crash."""
    elog = EventLog(base_dir=tmp_path)
    # First emit succeeds and opens the file
    elog.emit("setup")
    # Now make write raise on the next call
    elog._file.write = MagicMock(side_effect=OSError("No space left on device"))
    elog.emit("should_not_crash", key="val")  # must not raise


def test_emit_with_newlines_in_field(tmp_path):
    """Newlines inside field values are escaped — output is a single JSON line."""
    elog = EventLog(base_dir=tmp_path)
    elog.emit("multiline", text="line1\nline2\nline3")

    files = list(tmp_path.glob("events-*.jsonl"))
    raw_lines = files[0].read_text().strip().split("\n")
    assert len(raw_lines) == 1, "Event with embedded newlines must be a single line"
    event = json.loads(raw_lines[0])
    assert event["text"] == "line1\nline2\nline3"


def test_emit_with_non_serializable_field(tmp_path):
    """Non-serializable values (set, custom object) handled via default=str."""
    elog = EventLog(base_dir=tmp_path)
    elog.emit("exotic", tags={1, 2, 3}, path=Path("/tmp"))

    files = list(tmp_path.glob("events-*.jsonl"))
    event = json.loads(files[0].read_text().strip())
    assert event["type"] == "exotic"
    # set and Path are stringified
    assert isinstance(event["tags"], str)
    assert isinstance(event["path"], str)


def test_date_rollover(tmp_path):
    """When date changes between emits, a new file is opened."""
    day1 = datetime.date(2026, 1, 15)
    day2 = datetime.date(2026, 1, 16)

    elog = EventLog(base_dir=tmp_path)

    with patch("agents.hapax_voice.event_log.datetime") as mock_dt:
        mock_dt.date.today.return_value = day1
        mock_dt.date.fromisoformat = datetime.date.fromisoformat
        mock_dt.timedelta = datetime.timedelta
        elog.emit("day1_event")

        mock_dt.date.today.return_value = day2
        elog.emit("day2_event")

    assert (tmp_path / "events-2026-01-15.jsonl").exists()
    assert (tmp_path / "events-2026-01-16.jsonl").exists()

    e1 = json.loads((tmp_path / "events-2026-01-15.jsonl").read_text().strip())
    assert e1["type"] == "day1_event"
    e2 = json.loads((tmp_path / "events-2026-01-16.jsonl").read_text().strip())
    assert e2["type"] == "day2_event"

    elog.close()


def test_cleanup_with_malformed_filename(tmp_path):
    """Files with unparseable date stems are skipped, not crashed on."""
    (tmp_path / "events-notadate.jsonl").write_text("{}\n")
    (tmp_path / "events-2020-01-01.jsonl").write_text("{}\n")  # old, should be removed

    elog = EventLog(base_dir=tmp_path, retention_days=7)
    elog.cleanup()

    # Malformed file survives
    assert (tmp_path / "events-notadate.jsonl").exists()
    # Old file removed
    assert not (tmp_path / "events-2020-01-01.jsonl").exists()


def test_cleanup_with_zero_retention(tmp_path):
    """retention_days=0: cutoff = today, today < today is False → file kept."""
    today = datetime.date.today()
    path = tmp_path / f"events-{today.isoformat()}.jsonl"
    path.write_text("{}\n")

    elog = EventLog(base_dir=tmp_path, retention_days=0)
    elog.cleanup()

    assert path.exists(), "Today's file should NOT be deleted with retention_days=0"


def test_close_idempotent(tmp_path):
    """Calling close() twice does not crash."""
    elog = EventLog(base_dir=tmp_path)
    elog.emit("setup")
    elog.close()
    elog.close()  # must not raise


def test_close_sets_file_none(tmp_path):
    """After close(), internal file handle is None."""
    elog = EventLog(base_dir=tmp_path)
    elog.emit("setup")
    assert elog._file is not None
    elog.close()
    assert elog._file is None


def test_base_dir_created_on_first_emit(tmp_path):
    """base_dir that doesn't exist is created on first emit."""
    new_dir = tmp_path / "deep" / "nested" / "logs"
    assert not new_dir.exists()

    elog = EventLog(base_dir=new_dir)
    elog.emit("first")

    assert new_dir.exists()
    assert len(list(new_dir.glob("events-*.jsonl"))) == 1
    elog.close()


def test_emit_after_close_reopens(tmp_path):
    """emit() after close() transparently reopens the file."""
    elog = EventLog(base_dir=tmp_path)
    elog.emit("before_close", n=1)
    elog.close()
    assert elog._file is None

    # Reset _current_date so _get_file will reopen
    elog._current_date = ""
    elog.emit("after_close", n=2)

    files = list(tmp_path.glob("events-*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[1])["type"] == "after_close"
    elog.close()
