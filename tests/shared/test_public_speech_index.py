"""Tests for the public speech index."""

import json
from pathlib import Path

from shared.public_speech_index import (
    PublicSpeechEventRecord,
    append_public_speech_event,
    compute_utterance_hash,
)


def test_compute_utterance_hash():
    text = "hello world"
    # Should not raise
    h = compute_utterance_hash(text)
    assert isinstance(h, str)
    assert len(h) == 64  # SHA-256


def test_public_speech_record_validation():
    record = PublicSpeechEventRecord(
        speech_event_id="se-12345",
        impulse_id=None,
        triad_ids=["tr-1", "tr-2"],
        utterance_hash=compute_utterance_hash("hello world"),
        route_decision={"destination": "livestream"},
        tts_result={"status": "completed"},
        playback_result={"status": "completed"},
        audio_safety_refs=[],
        egress_refs=["ref-1"],
        wcs_snapshot_refs=[],
        chronicle_refs=[],
        temporal_span_refs=[],
        scope="public_broadcast",
        created_at="2026-05-04T12:00:00Z",
    )
    assert record.speech_event_id == "se-12345"
    assert record.scope == "public_broadcast"
    assert record.egress_refs == ["ref-1"]


def test_append_public_speech_event(tmp_path: Path):
    index_path = tmp_path / "public-speech-events.jsonl"

    record = PublicSpeechEventRecord(
        speech_event_id="se-12345",
        impulse_id="imp-1",
        triad_ids=[],
        utterance_hash="dummy-hash",
        route_decision={},
        tts_result=None,
        playback_result=None,
        audio_safety_refs=[],
        egress_refs=[],
        wcs_snapshot_refs=[],
        chronicle_refs=[],
        temporal_span_refs=[],
        scope="public_broadcast",
        created_at="2026-05-04T12:00:00Z",
    )

    append_public_speech_event(record, path=index_path)
    append_public_speech_event(record, path=index_path)

    lines = index_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2

    parsed = json.loads(lines[0])
    assert parsed["speech_event_id"] == "se-12345"
    assert parsed["scope"] == "public_broadcast"
