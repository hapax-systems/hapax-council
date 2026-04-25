"""Tests for ``agents.live_captions.reader``."""

from __future__ import annotations

import json
from pathlib import Path

from agents.live_captions.reader import CaptionEvent, CaptionReader


def _write_event(path: Path, *, ts: float, text: str, duration_ms: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"ts": ts, "text": text, "duration_ms": duration_ms})
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


# ── Basic read flow ─────────────────────────────────────────────────


class TestReadPending:
    def test_missing_file_yields_nothing(self, tmp_path):
        reader = CaptionReader(captions_path=tmp_path / "absent.jsonl")
        assert list(reader.read_pending()) == []

    def test_yields_well_formed_events(self, tmp_path):
        captions = tmp_path / "live.jsonl"
        reader = CaptionReader(captions_path=captions)
        _write_event(captions, ts=1.0, text="hello", duration_ms=500)
        _write_event(captions, ts=2.0, text="world", duration_ms=600)
        events = list(reader.read_pending())
        assert [e.text for e in events] == ["hello", "world"]
        assert [e.duration_ms for e in events] == [500, 600]

    def test_advances_cursor_on_success(self, tmp_path):
        captions = tmp_path / "live.jsonl"
        reader = CaptionReader(captions_path=captions)
        _write_event(captions, ts=1.0, text="first")
        list(reader.read_pending())
        _write_event(captions, ts=2.0, text="second")
        events = list(reader.read_pending())
        assert [e.text for e in events] == ["second"]

    def test_skips_malformed_json_line(self, tmp_path):
        captions = tmp_path / "live.jsonl"
        reader = CaptionReader(captions_path=captions)
        captions.parent.mkdir(parents=True, exist_ok=True)
        with captions.open("w", encoding="utf-8") as fh:
            fh.write("not json\n")
            fh.write(json.dumps({"ts": 1.0, "text": "ok"}) + "\n")
        events = list(reader.read_pending())
        assert [e.text for e in events] == ["ok"]

    def test_skips_event_without_required_fields(self, tmp_path):
        captions = tmp_path / "live.jsonl"
        reader = CaptionReader(captions_path=captions)
        captions.parent.mkdir(parents=True, exist_ok=True)
        with captions.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps({"text": "no ts"}) + "\n")
            fh.write(json.dumps({"ts": 1.0}) + "\n")  # no text
            fh.write(json.dumps({"ts": 2.0, "text": ""}) + "\n")  # empty text
            fh.write(json.dumps({"ts": 3.0, "text": "kept"}) + "\n")
        events = list(reader.read_pending())
        assert [e.text for e in events] == ["kept"]

    def test_speaker_field_optional(self, tmp_path):
        captions = tmp_path / "live.jsonl"
        reader = CaptionReader(captions_path=captions)
        captions.parent.mkdir(parents=True, exist_ok=True)
        with captions.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": 1.0, "text": "with", "speaker": "oudepode"}) + "\n")
            fh.write(json.dumps({"ts": 2.0, "text": "without"}) + "\n")
        events = list(reader.read_pending())
        assert events[0].speaker == "oudepode"
        assert events[1].speaker is None


# ── Audio↔video offset estimator ────────────────────────────────────


class TestAvOffsetEstimator:
    def test_no_samples_returns_zero(self, tmp_path):
        reader = CaptionReader(captions_path=tmp_path / "absent.jsonl")
        assert reader.av_offset_s == 0.0

    def test_single_sample_average(self, tmp_path):
        reader = CaptionReader(captions_path=tmp_path / "absent.jsonl")
        reader.observe_av_offset(audio_ts=10.0, video_ts=10.2)
        assert abs(reader.av_offset_s - 0.2) < 1e-9

    def test_multi_sample_average(self, tmp_path):
        reader = CaptionReader(captions_path=tmp_path / "absent.jsonl")
        reader.observe_av_offset(10.0, 10.1)
        reader.observe_av_offset(11.0, 11.3)
        reader.observe_av_offset(12.0, 12.2)
        # Average of 0.1, 0.3, 0.2 → 0.2.
        assert abs(reader.av_offset_s - 0.2) < 1e-9

    def test_window_caps_history(self, tmp_path):
        reader = CaptionReader(captions_path=tmp_path / "absent.jsonl", offset_window=2)
        reader.observe_av_offset(10.0, 10.5)  # 0.5
        reader.observe_av_offset(11.0, 11.1)  # 0.1
        reader.observe_av_offset(12.0, 12.3)  # 0.3 — drops the 0.5 sample
        # Average of 0.1, 0.3 → 0.2.
        assert abs(reader.av_offset_s - 0.2) < 1e-9

    def test_outlier_dropped(self, tmp_path):
        reader = CaptionReader(captions_path=tmp_path / "absent.jsonl", max_drift_s=1.0)
        reader.observe_av_offset(10.0, 10.2)  # 0.2 kept
        reader.observe_av_offset(11.0, 20.0)  # 9.0 spike — dropped
        reader.observe_av_offset(12.0, 12.4)  # 0.4 kept
        # Average of 0.2, 0.4 → 0.3, NOT including the 9.0 outlier.
        assert abs(reader.av_offset_s - 0.3) < 1e-9


# ── Video alignment on read ────────────────────────────────────────


class TestVideoAlignedRead:
    def test_events_shifted_by_current_offset(self, tmp_path):
        captions = tmp_path / "live.jsonl"
        reader = CaptionReader(captions_path=captions)
        reader.observe_av_offset(0.0, 0.25)  # offset = 0.25s
        _write_event(captions, ts=10.0, text="aligned")
        events = list(reader.read_pending())
        assert events[0].ts == 10.25

    def test_offset_change_affects_subsequent_reads(self, tmp_path):
        captions = tmp_path / "live.jsonl"
        reader = CaptionReader(captions_path=captions)
        # First batch at offset 0.
        _write_event(captions, ts=10.0, text="a")
        events1 = list(reader.read_pending())
        assert events1[0].ts == 10.0
        # Now record offset, write another event.
        reader.observe_av_offset(0.0, 0.25)
        _write_event(captions, ts=20.0, text="b")
        events2 = list(reader.read_pending())
        assert events2[0].ts == 20.25


# ── CaptionEvent ────────────────────────────────────────────────────


class TestCaptionEvent:
    def test_video_aligned_returns_new_instance(self):
        ev = CaptionEvent(ts=10.0, text="x", duration_ms=500, speaker="op")
        out = ev.video_aligned(0.3)
        assert out.ts == 10.3
        assert out.text == "x"
        assert out.duration_ms == 500
        assert out.speaker == "op"
        # Frozen dataclass — original unchanged.
        assert ev.ts == 10.0


# ── Cursor persistence ────────────────────────────────────────────


class TestCursorPersistence:
    def test_first_run_seeks_to_end_skipping_backlog(self, tmp_path):
        captions = tmp_path / "live.jsonl"
        cursor = tmp_path / "cursor.txt"
        # Pre-existing backlog — first-run reader must NOT replay these.
        for i in range(3):
            _write_event(captions, ts=float(i), text=f"old {i}")
        reader = CaptionReader(captions_path=captions, cursor_path=cursor)
        assert list(reader.read_pending()) == []

    def test_resumes_from_persisted_cursor(self, tmp_path):
        captions = tmp_path / "live.jsonl"
        cursor = tmp_path / "cursor.txt"
        # First daemon: bootstrap empty file, then process one event.
        reader1 = CaptionReader(captions_path=captions, cursor_path=cursor)
        _write_event(captions, ts=1.0, text="seen")
        events1 = list(reader1.read_pending())
        assert [e.text for e in events1] == ["seen"]
        # Restart: new daemon resumes from saved cursor — no replay.
        reader2 = CaptionReader(captions_path=captions, cursor_path=cursor)
        assert list(reader2.read_pending()) == []
