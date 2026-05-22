"""Tests for the daily semantic trace archiver."""

from __future__ import annotations

import json
import time
from pathlib import Path

import zstandard

from agents.semantic_trace_archiver import archive_day
from shared.chronicle import ChronicleEvent, record


def test_archive_extracts_only_semantic_events(tmp_path: Path):
    chronicle_path = tmp_path / "events.jsonl"
    archive_dir = tmp_path / "archive"
    now = time.time()

    record(
        ChronicleEvent(
            ts=now - 100,
            trace_id="a" * 32,
            span_id="b" * 16,
            parent_span_id=None,
            source="hapax_daimonion",
            event_type="semantics.interpretation_decided",
            payload={"interpretation": {"input_summary": "test"}},
            evidence_class="semantic_interpretation",
        ),
        path=chronicle_path,
    )
    record(
        ChronicleEvent(
            ts=now - 50,
            trace_id="a" * 32,
            span_id="c" * 16,
            parent_span_id=None,
            source="reverie",
            event_type="semantics.transformation_logged",
            payload={"transformation": {"source_node": "stimmung"}},
            evidence_class="semantic_interpretation",
        ),
        path=chronicle_path,
    )
    record(
        ChronicleEvent(
            ts=now - 30,
            trace_id="a" * 32,
            span_id="d" * 16,
            parent_span_id=None,
            source="test",
            event_type="voice.turn_start",
            payload={},
            evidence_class="sensor",
        ),
        path=chronicle_path,
    )

    out = archive_day(
        chronicle_path=chronicle_path,
        archive_dir=archive_dir,
        since=now - 200,
        until=now,
    )
    assert out.exists()
    assert out.suffix == ".zst"

    data = zstandard.ZstdDecompressor().decompress(out.read_bytes())
    lines = [json.loads(line) for line in data.decode().strip().splitlines()]
    assert len(lines) == 2
    assert all(line["evidence_class"] == "semantic_interpretation" for line in lines)


def test_archive_empty_chronicle(tmp_path: Path):
    chronicle_path = tmp_path / "events.jsonl"
    chronicle_path.write_text("")
    archive_dir = tmp_path / "archive"
    now = time.time()

    out = archive_day(
        chronicle_path=chronicle_path,
        archive_dir=archive_dir,
        since=now - 200,
        until=now,
    )
    assert out.exists()
    data = zstandard.ZstdDecompressor().decompress(out.read_bytes())
    assert data.decode().strip() == ""
