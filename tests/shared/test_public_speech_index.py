"""Tests for the public speech event witness index.

Covers: public spoken, private spoken, failed playback, no egress,
stale witness, blocked programme auth, deictic resolver fixture.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from shared.public_speech_index import (
    PublicSpeechEventRecord,
    PublicSpeechIndexError,
    append_public_speech_event,
    compute_utterance_hash,
    lookup_speech_event,
    read_public_speech_events,
    recent_public_speech,
)


def _record(**overrides: Any) -> PublicSpeechEventRecord:
    defaults: dict[str, Any] = {
        "speech_event_id": "se-001",
        "impulse_id": "imp-1",
        "triad_ids": ["tr-1"],
        "utterance_hash": compute_utterance_hash("hello world"),
        "route_decision": {"destination": "livestream"},
        "tts_result": {"status": "completed"},
        "playback_result": {"status": "completed"},
        "audio_safety_refs": ["safety-1"],
        "egress_refs": ["egress-1"],
        "wcs_snapshot_refs": ["wcs-1"],
        "chronicle_refs": ["chr-1"],
        "temporal_span_refs": ["ts-1"],
        "scope": "public_broadcast",
        "created_at": "2026-05-20T12:00:00Z",
    }
    defaults.update(overrides)
    return PublicSpeechEventRecord(**defaults)


class TestComputeUtteranceHash:
    def test_sha256_length(self) -> None:
        assert len(compute_utterance_hash("test")) == 64

    def test_deterministic(self) -> None:
        assert compute_utterance_hash("same") == compute_utterance_hash("same")

    def test_different_input_different_hash(self) -> None:
        assert compute_utterance_hash("a") != compute_utterance_hash("b")


class TestPublicSpeechEventRecord:
    def test_valid_public_broadcast(self) -> None:
        r = _record()
        assert r.scope == "public_broadcast"
        assert r.egress_refs == ["egress-1"]

    def test_private_only_scope_no_egress_ok(self) -> None:
        r = _record(scope="private_only", egress_refs=[])
        assert r.scope == "private_only"

    def test_blocked_scope_no_egress_ok(self) -> None:
        r = _record(scope="blocked", egress_refs=[])
        assert r.scope == "blocked"

    def test_failed_scope_no_egress_ok(self) -> None:
        r = _record(scope="failed", egress_refs=[])
        assert r.scope == "failed"

    def test_frozen(self) -> None:
        r = _record()
        with pytest.raises(Exception):
            r.scope = "private_only"  # type: ignore[misc]


class TestPublicBroadcastWithoutEgress:
    def test_rejects_public_broadcast_no_egress(self) -> None:
        with pytest.raises((ValidationError, PublicSpeechIndexError)):
            _record(scope="public_broadcast", egress_refs=[])

    def test_rejects_public_broadcast_empty_egress_list(self) -> None:
        with pytest.raises((ValidationError, PublicSpeechIndexError)):
            _record(scope="public_broadcast", egress_refs=[])


class TestPrivateCannotBePublic:
    def test_rejects_private_route_with_public_scope(self) -> None:
        with pytest.raises((ValidationError, PublicSpeechIndexError)):
            _record(
                scope="public_broadcast",
                route_decision={"route": "private"},
                egress_refs=["egress-1"],
            )

    def test_rejects_private_destination_with_public_scope(self) -> None:
        with pytest.raises((ValidationError, PublicSpeechIndexError)):
            _record(
                scope="public_broadcast",
                route_decision={"destination": "private"},
                egress_refs=["egress-1"],
            )

    def test_allows_private_route_with_private_scope(self) -> None:
        r = _record(
            scope="private_only",
            route_decision={"route": "private"},
            egress_refs=[],
        )
        assert r.scope == "private_only"


class TestFailedPlayback:
    def test_failed_playback_recorded_as_failed(self) -> None:
        r = _record(
            scope="failed",
            playback_result={"status": "failed", "error": "device unavailable"},
            egress_refs=[],
        )
        assert r.scope == "failed"
        assert r.playback_result["status"] == "failed"

    def test_null_tts_with_failed_scope(self) -> None:
        r = _record(scope="failed", tts_result=None, playback_result=None, egress_refs=[])
        assert r.tts_result is None


class TestBlockedProgrammeAuth:
    def test_blocked_scope(self) -> None:
        r = _record(
            scope="blocked",
            route_decision={"blocked_reason": "programme_auth_expired"},
            egress_refs=[],
        )
        assert r.scope == "blocked"


class TestAppendAndRead:
    def test_append_creates_file(self, tmp_path: Path) -> None:
        index = tmp_path / "events.jsonl"
        r = _record()
        append_public_speech_event(r, path=index)
        assert index.exists()

    def test_append_is_additive(self, tmp_path: Path) -> None:
        index = tmp_path / "events.jsonl"
        r1 = _record(speech_event_id="se-001")
        r2 = _record(speech_event_id="se-002")
        append_public_speech_event(r1, path=index)
        append_public_speech_event(r2, path=index)
        lines = index.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_read_empty_file(self, tmp_path: Path) -> None:
        index = tmp_path / "events.jsonl"
        assert read_public_speech_events(index) == []

    def test_read_nonexistent_file(self, tmp_path: Path) -> None:
        index = tmp_path / "nonexistent.jsonl"
        assert read_public_speech_events(index) == []

    def test_read_returns_records(self, tmp_path: Path) -> None:
        index = tmp_path / "events.jsonl"
        r = _record()
        append_public_speech_event(r, path=index)
        records = read_public_speech_events(index)
        assert len(records) == 1
        assert records[0].speech_event_id == "se-001"

    def test_read_filtered_by_scope(self, tmp_path: Path) -> None:
        index = tmp_path / "events.jsonl"
        r_public = _record(speech_event_id="se-pub")
        r_private = _record(speech_event_id="se-priv", scope="private_only", egress_refs=[])
        append_public_speech_event(r_public, path=index)
        append_public_speech_event(r_private, path=index)
        public = read_public_speech_events(index, scope="public_broadcast")
        assert len(public) == 1
        assert public[0].speech_event_id == "se-pub"

    def test_roundtrip_json_integrity(self, tmp_path: Path) -> None:
        index = tmp_path / "events.jsonl"
        r = _record()
        append_public_speech_event(r, path=index)
        line = index.read_text().strip()
        parsed = json.loads(line)
        assert parsed["speech_event_id"] == "se-001"
        assert parsed["scope"] == "public_broadcast"

    def test_append_keeps_bounded_recent_rows(self, tmp_path: Path) -> None:
        index = tmp_path / "events.jsonl"
        for idx in range(3):
            append_public_speech_event(
                _record(speech_event_id=f"se-{idx}"),
                path=index,
                max_events=2,
            )

        records = read_public_speech_events(index)

        assert [record.speech_event_id for record in records] == ["se-1", "se-2"]


class TestLookup:
    def test_lookup_existing(self, tmp_path: Path) -> None:
        index = tmp_path / "events.jsonl"
        r = _record(speech_event_id="se-target")
        append_public_speech_event(r, path=index)
        result = lookup_speech_event("se-target", path=index)
        assert result is not None
        assert result.speech_event_id == "se-target"

    def test_lookup_missing(self, tmp_path: Path) -> None:
        index = tmp_path / "events.jsonl"
        r = _record()
        append_public_speech_event(r, path=index)
        assert lookup_speech_event("se-nonexistent", path=index) is None

    def test_lookup_empty_index(self, tmp_path: Path) -> None:
        index = tmp_path / "events.jsonl"
        assert lookup_speech_event("se-any", path=index) is None


class TestRecentPublicSpeech:
    def test_returns_only_public(self, tmp_path: Path) -> None:
        index = tmp_path / "events.jsonl"
        for i in range(3):
            append_public_speech_event(_record(speech_event_id=f"se-pub-{i}"), path=index)
        append_public_speech_event(
            _record(speech_event_id="se-priv", scope="private_only", egress_refs=[]),
            path=index,
        )
        recent = recent_public_speech(n=10, path=index)
        assert len(recent) == 3
        assert all(r.scope == "public_broadcast" for r in recent)

    def test_limits_to_n(self, tmp_path: Path) -> None:
        index = tmp_path / "events.jsonl"
        for i in range(10):
            append_public_speech_event(_record(speech_event_id=f"se-{i}"), path=index)
        recent = recent_public_speech(n=3, path=index)
        assert len(recent) == 3
        assert recent[-1].speech_event_id == "se-9"


class TestDeicticResolverFixture:
    def test_two_recent_events_resolvable(self, tmp_path: Path) -> None:
        index = tmp_path / "events.jsonl"
        first = _record(
            speech_event_id="se-first",
            utterance_hash=compute_utterance_hash("The system is now live."),
            created_at="2026-05-20T12:00:00Z",
        )
        second = _record(
            speech_event_id="se-second",
            utterance_hash=compute_utterance_hash("Here is the update."),
            created_at="2026-05-20T12:05:00Z",
        )
        append_public_speech_event(first, path=index)
        append_public_speech_event(second, path=index)

        recent = recent_public_speech(n=2, path=index)
        assert len(recent) == 2
        assert recent[0].speech_event_id == "se-first"
        assert recent[1].speech_event_id == "se-second"

        found = lookup_speech_event("se-second", path=index)
        assert found is not None
        assert found.utterance_hash == compute_utterance_hash("Here is the update.")
