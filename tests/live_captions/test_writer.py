"""Tests for ``agents.live_captions.writer``."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from agents.live_captions.writer import CaptionWriter


def _read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# ── Basic emit ─────────────────────────────────────────────────────


class TestEmit:
    def test_appends_one_line_per_emit(self, tmp_path):
        out = tmp_path / "live.jsonl"
        writer = CaptionWriter(captions_path=out)
        writer.emit(ts=1.0, text="hello", duration_ms=500)
        writer.emit(ts=2.0, text="world", duration_ms=600)
        records = _read_lines(out)
        assert [r["text"] for r in records] == ["hello", "world"]
        assert [r["duration_ms"] for r in records] == [500, 600]

    def test_creates_parent_dir(self, tmp_path):
        out = tmp_path / "deep" / "nested" / "live.jsonl"
        writer = CaptionWriter(captions_path=out)
        writer.emit(ts=1.0, text="hi")
        assert out.exists()

    def test_speaker_field_optional(self, tmp_path):
        out = tmp_path / "live.jsonl"
        writer = CaptionWriter(captions_path=out)
        writer.emit(ts=1.0, text="with", speaker="oudepode")
        writer.emit(ts=2.0, text="without")
        records = _read_lines(out)
        assert records[0]["speaker"] == "oudepode"
        assert "speaker" not in records[1]

    def test_empty_text_dropped(self, tmp_path):
        out = tmp_path / "live.jsonl"
        writer = CaptionWriter(captions_path=out)
        writer.emit(ts=1.0, text="")
        writer.emit(ts=2.0, text="kept")
        records = _read_lines(out)
        assert [r["text"] for r in records] == ["kept"]

    def test_unicode_preserved(self, tmp_path):
        """STT may produce non-ASCII glyphs (Hapax / Oudepode)."""
        out = tmp_path / "live.jsonl"
        writer = CaptionWriter(captions_path=out)
        writer.emit(ts=1.0, text="Oudepode says café")
        records = _read_lines(out)
        assert records[0]["text"] == "Oudepode says café"


# ── Round-trip with reader ──────────────────────────────────────────


class TestRoundTrip:
    def test_reader_consumes_writer_output(self, tmp_path):
        from agents.live_captions.reader import CaptionReader

        out = tmp_path / "live.jsonl"
        # Reader created BEFORE first write so its bootstrap cursor
        # starts at 0 (matches production: reader is the long-lived
        # GStreamer attachment, writer is per-utterance from STT).
        reader = CaptionReader(captions_path=out)
        writer = CaptionWriter(captions_path=out)
        writer.emit(ts=10.0, text="alpha", duration_ms=400, speaker="oudepode")
        writer.emit(ts=11.0, text="beta", duration_ms=500)
        events = list(reader.read_pending())
        assert [e.text for e in events] == ["alpha", "beta"]
        assert events[0].speaker == "oudepode"
        assert events[1].speaker is None
        assert events[0].duration_ms == 400


# ── Concurrency ────────────────────────────────────────────────────


class TestConcurrency:
    def test_concurrent_emits_serialise(self, tmp_path):
        """Two threads emitting simultaneously produce well-formed lines."""
        out = tmp_path / "live.jsonl"
        writer = CaptionWriter(captions_path=out)

        def burst(start: int) -> None:
            for i in range(50):
                writer.emit(ts=float(start * 100 + i), text=f"msg-{start}-{i}")

        threads = [threading.Thread(target=burst, args=(s,)) for s in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All 200 lines well-formed; total count matches.
        records = _read_lines(out)
        assert len(records) == 200
        # Per-line atomicity: every record parses + carries the right
        # shape (no partial writes interleaving).
        for r in records:
            assert "ts" in r
            assert "text" in r
            assert r["text"].startswith("msg-")
