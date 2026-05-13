"""Unit tests for the M8 stem-archive recorder.

Covers the chronicle emitter (agents/m8_stem_emitter.py) — rotation
detection, retention thresholds, and event payload shape. The bash
recorder script and the systemd units are smoke-tested for shape +
content; the actual PipeWire/sox pipeline is operator-physical.

cc-task: m8-stem-archive-recorder
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest import mock

import pytest

from agents import m8_stem_emitter


@pytest.fixture
def stem_dir(tmp_path: Path) -> Path:
    d = tmp_path / "m8-stems"
    d.mkdir()
    return d


@pytest.fixture
def cursor_path(tmp_path: Path) -> Path:
    return tmp_path / "cursor.txt"


def _make_flac_file(stem_dir: Path, name: str, size: int, mtime_offset_s: float) -> Path:
    """Create a fake .flac file with controlled mtime offset (negative = older)."""
    path = stem_dir / name
    path.write_bytes(b"\x00" * size)
    now = time.time()
    os.utime(path, (now + mtime_offset_s, now + mtime_offset_s))
    return path


def test_no_files_emits_zero(stem_dir: Path, cursor_path: Path):
    count = m8_stem_emitter.emit_for_completed_files(stem_dir=stem_dir, cursor_path=cursor_path)
    assert count == 0


def test_recently_written_file_skipped(stem_dir: Path, cursor_path: Path):
    """A FLAC file modified within the last 60s is treated as still being written."""
    _make_flac_file(stem_dir, "2026-05-02.flac", size=1024, mtime_offset_s=-10)

    count = m8_stem_emitter.emit_for_completed_files(stem_dir=stem_dir, cursor_path=cursor_path)
    assert count == 0


def test_completed_file_emits_one_event(stem_dir: Path, cursor_path: Path):
    _make_flac_file(stem_dir, "2026-05-01.flac", size=120_000_000, mtime_offset_s=-3600)

    with mock.patch("agents.m8_stem_emitter.record") as mock_record:
        count = m8_stem_emitter.emit_for_completed_files(stem_dir=stem_dir, cursor_path=cursor_path)

    assert count == 1
    assert mock_record.call_count == 1
    event = mock_record.call_args[0][0]
    assert event.event_type == "m8.stem.day_rolled"
    assert event.source == "m8_stem_recorder"
    assert event.payload["filename"] == "2026-05-01.flac"
    assert event.payload["size_bytes"] == 120_000_000
    # Day-roll events ride above the chronicle-ticker salience threshold
    # so the operator's broadcast surfaces archive-completion without
    # ``m8_stem_recorder`` joining the source allow-list.
    assert event.payload["salience"] >= 0.7
    assert event.payload["salience"] == 0.95


def test_already_emitted_file_skipped_via_cursor(stem_dir: Path, cursor_path: Path):
    _make_flac_file(stem_dir, "2026-05-01.flac", size=1024, mtime_offset_s=-3600)
    cursor_path.write_text("2026-05-01.flac\n")

    with mock.patch("agents.m8_stem_emitter.record") as mock_record:
        count = m8_stem_emitter.emit_for_completed_files(stem_dir=stem_dir, cursor_path=cursor_path)

    assert count == 0
    mock_record.assert_not_called()


def test_cursor_persists_across_runs(stem_dir: Path, cursor_path: Path):
    _make_flac_file(stem_dir, "2026-05-01.flac", size=1024, mtime_offset_s=-3600)

    with mock.patch("agents.m8_stem_emitter.record"):
        m8_stem_emitter.emit_for_completed_files(stem_dir=stem_dir, cursor_path=cursor_path)

    assert cursor_path.exists()
    assert "2026-05-01.flac" in cursor_path.read_text()


def test_multiple_completed_files_emit_separate_events(stem_dir: Path, cursor_path: Path):
    for day in ("2026-04-29", "2026-04-30", "2026-05-01"):
        _make_flac_file(stem_dir, f"{day}.flac", size=1024, mtime_offset_s=-3600)

    with mock.patch("agents.m8_stem_emitter.record") as mock_record:
        count = m8_stem_emitter.emit_for_completed_files(stem_dir=stem_dir, cursor_path=cursor_path)

    assert count == 3
    assert mock_record.call_count == 3
    filenames = {call.args[0].payload["filename"] for call in mock_record.call_args_list}
    assert filenames == {"2026-04-29.flac", "2026-04-30.flac", "2026-05-01.flac"}


def test_missing_stem_dir_returns_zero(tmp_path: Path):
    missing = tmp_path / "no-such-dir"
    cursor = tmp_path / "cursor.txt"
    count = m8_stem_emitter.emit_for_completed_files(stem_dir=missing, cursor_path=cursor)
    assert count == 0


def test_chronicle_record_failure_does_not_advance_cursor(stem_dir: Path, cursor_path: Path):
    _make_flac_file(stem_dir, "2026-05-01.flac", size=1024, mtime_offset_s=-3600)

    with mock.patch("agents.m8_stem_emitter.record", side_effect=OSError("disk full")):
        count = m8_stem_emitter.emit_for_completed_files(stem_dir=stem_dir, cursor_path=cursor_path)

    assert count == 0
    assert not cursor_path.exists()


def test_recorder_script_invokes_parec_and_sox():
    """Smoke-test the shape of the bash recorder script."""
    repo_root = Path(__file__).resolve().parent.parent
    script = repo_root / "scripts" / "m8-stem-recorder.sh"
    assert script.exists(), "recorder script missing"
    assert script.stat().st_mode & 0o111, "recorder script not executable"

    body = script.read_text()
    assert "parec" in body
    assert "sox" in body
    assert "alsa_input.usb-Dirtywave_M8" in body
    assert "44100" in body
    assert "/var/lib/hapax/m8-stems" in body or "HAPAX_M8_STEM_DIR" in body


def test_systemd_units_present_and_well_formed():
    repo_root = Path(__file__).resolve().parent.parent
    recorder = repo_root / "systemd" / "units" / "hapax-m8-stem-recorder.service"
    retention_svc = repo_root / "systemd" / "units" / "hapax-m8-stem-retention.service"
    retention_timer = repo_root / "systemd" / "units" / "hapax-m8-stem-retention.timer"

    assert recorder.exists()
    assert retention_svc.exists()
    assert retention_timer.exists()

    rec_body = recorder.read_text()
    assert "[Service]" in rec_body
    assert "ExecStart=" in rec_body
    assert "PartOf=hapax.target" in rec_body

    timer_body = retention_timer.read_text()
    assert "[Timer]" in timer_body
    assert "OnCalendar=daily" in timer_body
    assert "Persistent=true" in timer_body

    retention_body = retention_svc.read_text()
    assert "Environment=HAPAX_M8_STEM_DIR=/var/lib/hapax/m8-stems" in retention_body
    assert "${HAPAX_M8_STEM_DIR:-" not in retention_body
