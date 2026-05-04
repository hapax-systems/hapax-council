"""Tests for shared.segment_observability.

Covers the canonical SegmentEvent / emit_segment_event / SegmentRecorder
surface that all five operator outcomes (vocal, segmented content,
director moves, chat ingestion, chat response) use to record segment
lifecycle + per-outcome quality.

Each test isolates the jsonl log via tmp_path (or HAPAX_SEGMENTS_LOG env
override) so the operator's real ``~/hapax-state/segments/segments.jsonl``
is never read or mutated.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from shared.segment_observability import (
    QualityRating,
    SegmentEvent,
    SegmentLifecycle,
    SegmentQuality,
    SegmentRecorder,
    emit_segment_event,
)

# ── SegmentEvent schema ────────────────────────────────────────────


class TestSegmentEventSchema:
    def test_round_trip_through_json(self) -> None:
        original = SegmentEvent(programme_role="vocal_only", topic_seed="acid bath")
        original.quality.vocal = QualityRating.GOOD
        original.quality.notes = "TTS latency 230ms"

        as_json = original.model_dump_json()
        restored = SegmentEvent.model_validate_json(as_json)

        assert restored.segment_id == original.segment_id
        assert restored.programme_role == "vocal_only"
        assert restored.topic_seed == "acid bath"
        assert restored.lifecycle is SegmentLifecycle.STARTED
        assert restored.quality.vocal is QualityRating.GOOD
        assert restored.quality.notes == "TTS latency 230ms"
        # Untouched dimensions stay UNMEASURED
        assert restored.quality.programme_authoring is QualityRating.UNMEASURED
        assert restored.quality.director_moves is QualityRating.UNMEASURED

    def test_quality_defaults_unmeasured(self) -> None:
        q = SegmentQuality()
        assert q.vocal is QualityRating.UNMEASURED
        assert q.programme_authoring is QualityRating.UNMEASURED
        assert q.director_moves is QualityRating.UNMEASURED
        assert q.chat_reactivity is QualityRating.UNMEASURED
        assert q.chat_response is QualityRating.UNMEASURED
        assert q.notes is None

    def test_segment_id_unique_per_event(self) -> None:
        a = SegmentEvent(programme_role="r")
        b = SegmentEvent(programme_role="r")
        assert a.segment_id != b.segment_id


# ── emit_segment_event ─────────────────────────────────────────────


class TestEmitSegmentEvent:
    def test_appends_valid_jsonl_line(self, tmp_path: Path) -> None:
        log = tmp_path / "segments.jsonl"
        ev = SegmentEvent(programme_role="director_moves", topic_seed="opening")
        emit_segment_event(ev, log_path=log)

        lines = log.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        loaded = json.loads(lines[0])
        assert loaded["programme_role"] == "director_moves"
        assert loaded["topic_seed"] == "opening"
        assert loaded["lifecycle"] == "started"
        assert loaded["segment_id"] == ev.segment_id

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        log = tmp_path / "deep" / "nested" / "segments.jsonl"
        emit_segment_event(SegmentEvent(programme_role="r"), log_path=log)
        assert log.exists()

    def test_appends_subsequent_calls(self, tmp_path: Path) -> None:
        log = tmp_path / "segments.jsonl"
        emit_segment_event(SegmentEvent(programme_role="a"), log_path=log)
        emit_segment_event(SegmentEvent(programme_role="b"), log_path=log)
        emit_segment_event(SegmentEvent(programme_role="c"), log_path=log)

        lines = log.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3
        roles = [json.loads(line)["programme_role"] for line in lines]
        assert roles == ["a", "b", "c"]

    def test_uses_env_var_when_no_log_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        log = tmp_path / "from-env.jsonl"
        monkeypatch.setenv("HAPAX_SEGMENTS_LOG", str(log))
        emit_segment_event(SegmentEvent(programme_role="env-routed"))

        assert log.exists()
        loaded = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
        assert loaded["programme_role"] == "env-routed"


# ── SegmentRecorder context manager ────────────────────────────────


class TestSegmentRecorderHappyPath:
    def test_emits_started_then_happened(self, tmp_path: Path) -> None:
        log = tmp_path / "segments.jsonl"
        with SegmentRecorder("vocal_only", topic_seed="seed", log_path=log) as ev:
            assert ev.lifecycle is SegmentLifecycle.STARTED
            assert ev.ended_at is None

        lines = log.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        last = json.loads(lines[1])

        assert first["lifecycle"] == "started"
        assert first["ended_at"] is None
        assert last["lifecycle"] == "happened"
        assert last["ended_at"] is not None
        # Same segment_id stitches the pair
        assert first["segment_id"] == last["segment_id"]
        assert first["programme_role"] == "vocal_only" == last["programme_role"]
        assert first["topic_seed"] == "seed" == last["topic_seed"]

    def test_quality_updates_reflected_in_final_event(self, tmp_path: Path) -> None:
        log = tmp_path / "segments.jsonl"
        with SegmentRecorder("vocal_only", log_path=log) as ev:
            ev.quality.vocal = QualityRating.EXCELLENT
            ev.quality.chat_response = QualityRating.ACCEPTABLE
            ev.quality.notes = "TTS clean; chat slow."

        lines = log.read_text(encoding="utf-8").splitlines()
        last = json.loads(lines[1])
        assert last["lifecycle"] == "happened"
        assert last["quality"]["vocal"] == "excellent"
        assert last["quality"]["chat_response"] == "acceptable"
        assert last["quality"]["notes"] == "TTS clean; chat slow."
        # Untouched dimensions stay UNMEASURED in the persisted event
        assert last["quality"]["programme_authoring"] == "unmeasured"
        assert last["quality"]["director_moves"] == "unmeasured"
        assert last["quality"]["chat_reactivity"] == "unmeasured"


class TestSegmentRecorderExceptionPath:
    def test_emits_didnt_happen_and_reraises(self, tmp_path: Path) -> None:
        log = tmp_path / "segments.jsonl"

        class Boom(Exception):
            pass

        with pytest.raises(Boom):
            with SegmentRecorder("director_moves", log_path=log) as ev:
                ev.quality.director_moves = QualityRating.POOR
                raise Boom("director crashed mid-segment")

        lines = log.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        last = json.loads(lines[1])

        assert first["lifecycle"] == "started"
        assert last["lifecycle"] == "didnt_happen"
        assert last["ended_at"] is not None
        assert first["segment_id"] == last["segment_id"]
        # Quality mutations made before the exception are preserved
        assert last["quality"]["director_moves"] == "poor"

    def test_keyboard_interrupt_also_records_didnt_happen(self, tmp_path: Path) -> None:
        log = tmp_path / "segments.jsonl"

        with pytest.raises(KeyboardInterrupt):
            with SegmentRecorder("vocal_only", log_path=log):
                raise KeyboardInterrupt

        lines = log.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        last = json.loads(lines[1])
        assert last["lifecycle"] == "didnt_happen"

    def test_uses_env_var_when_no_log_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        log = tmp_path / "env-routed.jsonl"
        monkeypatch.setenv("HAPAX_SEGMENTS_LOG", str(log))
        with SegmentRecorder("vocal_only") as ev:
            ev.quality.vocal = QualityRating.GOOD

        lines = log.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert json.loads(lines[1])["lifecycle"] == "happened"


# ── Concurrency ────────────────────────────────────────────────────


class TestThreadSafety:
    def test_concurrent_emits_dont_interleave(self, tmp_path: Path) -> None:
        """Lines from N threads each emitting M events must each be a
        complete, parseable JSON object — no torn writes / partial lines.
        """

        log = tmp_path / "segments.jsonl"
        n_threads = 8
        per_thread = 25

        def worker(tid: int) -> None:
            for i in range(per_thread):
                ev = SegmentEvent(
                    programme_role=f"thread-{tid}",
                    topic_seed=f"event-{i}",
                )
                emit_segment_event(ev, log_path=log)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        lines = log.read_text(encoding="utf-8").splitlines()
        assert len(lines) == n_threads * per_thread

        # Every line is a complete JSON document with the expected fields
        seen_per_thread: dict[str, set[str]] = {f"thread-{t}": set() for t in range(n_threads)}
        for line in lines:
            payload = json.loads(line)  # raises on torn write
            assert payload["lifecycle"] == "started"
            role = payload["programme_role"]
            assert role in seen_per_thread
            seen_per_thread[role].add(payload["topic_seed"])

        # Every thread's events all landed
        for tid in range(n_threads):
            assert len(seen_per_thread[f"thread-{tid}"]) == per_thread
