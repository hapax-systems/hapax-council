"""Tests for shared.gem_frame_log.

The log is the bridge between the gem_producer emission path and the
variance scorer. Tests pin: schema-stable JSONL writes, defensive
posture (broken filesystem cannot break emission), env-driven path
override, time-window filtering, and the flatten helper that feeds
the variance scorer.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shared.gem_frame_log import (
    flatten_frame_texts,
    log_gem_frame,
    read_recent_gem_frames,
)


@pytest.fixture()
def log_path(tmp_path: Path) -> Path:
    """Test-isolated log path; HAPAX_GEM_FRAMES_LOG would also work
    but we pass log_path explicitly for tighter test scoping."""
    return tmp_path / "gem-frames.jsonl"


# --- log_gem_frame ----------------------------------------------------------


class TestLogGemFrame:
    def test_writes_one_line_per_call(self, log_path: Path):
        log_gem_frame(
            impingement_id="imp-1",
            impingement_source="endogenous.narrative_drive",
            frame_texts=["Hapax narration A", "Hapax narration B"],
            programme_role="work_block",
            log_path=log_path,
        )
        lines = log_path.read_text().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["impingement_id"] == "imp-1"
        assert record["impingement_source"] == "endogenous.narrative_drive"
        assert record["frame_texts"] == ["Hapax narration A", "Hapax narration B"]
        assert record["programme_role"] == "work_block"
        assert "timestamp" in record

    def test_filters_blank_and_non_string_frames(self, log_path: Path):
        log_gem_frame(
            impingement_id="imp-2",
            impingement_source="src",
            frame_texts=["valid", "  ", "", "another"],
            log_path=log_path,
        )
        record = json.loads(log_path.read_text().strip())
        assert record["frame_texts"] == ["valid", "another"]

    def test_skips_when_all_frames_blank(self, log_path: Path):
        log_gem_frame(
            impingement_id="imp-3",
            impingement_source="src",
            frame_texts=["", "  ", "\t"],
            log_path=log_path,
        )
        # No log file at all because there was nothing renderable to log.
        assert not log_path.exists()

    def test_appends_across_calls(self, log_path: Path):
        log_gem_frame(
            impingement_id="a",
            impingement_source="s",
            frame_texts=["one"],
            log_path=log_path,
        )
        log_gem_frame(
            impingement_id="b",
            impingement_source="s",
            frame_texts=["two"],
            log_path=log_path,
        )
        lines = log_path.read_text().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["impingement_id"] == "a"
        assert json.loads(lines[1])["impingement_id"] == "b"

    def test_creates_parent_directory(self, tmp_path: Path):
        nested = tmp_path / "deep" / "nested" / "dir" / "gem-frames.jsonl"
        log_gem_frame(
            impingement_id="x",
            impingement_source="s",
            frame_texts=["text"],
            log_path=nested,
        )
        assert nested.exists()

    def test_env_var_default_path(self, tmp_path: Path, monkeypatch):
        target = tmp_path / "via-env.jsonl"
        monkeypatch.setenv("HAPAX_GEM_FRAMES_LOG", str(target))
        log_gem_frame(
            impingement_id="env",
            impingement_source="s",
            frame_texts=["text"],
        )
        assert target.exists()

    def test_failed_write_does_not_raise(self, monkeypatch):
        """A broken filesystem must not break the emission path."""

        def _broken_open(*args, **kwargs):
            raise OSError("disk on fire")

        # Force the open() call inside the writer to fail.
        from pathlib import Path as _PathClass

        monkeypatch.setattr(_PathClass, "open", _broken_open)

        # Should NOT raise.
        log_gem_frame(
            impingement_id="x",
            impingement_source="s",
            frame_texts=["text"],
            log_path=_PathClass("/tmp/nonexistent.jsonl"),
        )


# --- read_recent_gem_frames -------------------------------------------------


class TestReadRecentGemFrames:
    def test_missing_file_returns_empty(self, log_path: Path):
        assert read_recent_gem_frames(log_path=log_path) == []

    def test_filters_by_window(self, log_path: Path):
        now = datetime.now(UTC)
        old = (now - timedelta(seconds=2000)).isoformat()
        recent = (now - timedelta(seconds=30)).isoformat()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps({"timestamp": old, "frame_texts": ["old"]}) + "\n")
            fh.write(json.dumps({"timestamp": recent, "frame_texts": ["recent"]}) + "\n")

        records = read_recent_gem_frames(window_s=600, log_path=log_path, now=now)
        assert len(records) == 1
        assert records[0]["frame_texts"] == ["recent"]

    def test_skips_malformed_lines(self, log_path: Path):
        now = datetime.now(UTC)
        valid = json.dumps({"timestamp": now.isoformat(), "frame_texts": ["ok"]})
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as fh:
            fh.write("not json\n")
            fh.write(valid + "\n")
            fh.write(json.dumps({"timestamp": "not-a-timestamp"}) + "\n")
            fh.write("\n")
            fh.write("{partial json")

        records = read_recent_gem_frames(window_s=3600, log_path=log_path, now=now)
        assert len(records) == 1


# --- flatten_frame_texts ----------------------------------------------------


class TestFlattenFrameTexts:
    def test_flattens_records_into_texts(self):
        records = [
            {"frame_texts": ["A", "B"]},
            {"frame_texts": ["C"]},
            {"frame_texts": ["D", "E", "F"]},
        ]
        assert flatten_frame_texts(records) == ["A", "B", "C", "D", "E", "F"]

    def test_strips_blank_and_non_string(self):
        records = [
            {"frame_texts": ["A", "  ", "", None, "B"]},
            {"no_frames_key": True},
        ]
        # Non-string and blank entries drop; the no_frames_key record
        # contributes nothing because frame_texts defaults to ().
        assert flatten_frame_texts(records) == ["A", "B"]

    def test_preserves_order(self):
        records = [
            {"frame_texts": ["one", "two"]},
            {"frame_texts": ["three"]},
        ]
        assert flatten_frame_texts(records) == ["one", "two", "three"]
