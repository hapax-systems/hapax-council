"""Tests for shared.chronicle — ChronicleEvent model, writer, reader, retention."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from shared.chronicle import (
    RETENTION_S,
    ChronicleEvent,
    current_otel_ids,
    query,
    record,
    trim,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_event(
    *,
    ts: float | None = None,
    source: str = "test_source",
    event_type: str = "test.event",
    trace_id: str = "a" * 32,
    span_id: str = "b" * 16,
    parent_span_id: str | None = None,
    payload: dict | None = None,
) -> ChronicleEvent:
    return ChronicleEvent(
        ts=ts if ts is not None else time.time(),
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        source=source,
        event_type=event_type,
        payload=payload or {},
    )


# ── Task 1: ChronicleEvent model ──────────────────────────────────────────────


def test_chronicle_event_frozen():
    ev = _make_event()
    with pytest.raises(Exception):
        ev.source = "other"  # type: ignore[misc]


def test_to_json_produces_valid_json():
    ev = _make_event(payload={"key": "value"})
    raw = ev.to_json()
    d = json.loads(raw)
    assert d["source"] == "test_source"
    assert d["event_type"] == "test.event"
    assert d["payload"] == {"key": "value"}


def test_from_json_roundtrip():
    ev = _make_event(parent_span_id="c" * 16, payload={"x": 42})
    reconstructed = ChronicleEvent.from_json(ev.to_json())
    assert reconstructed.ts == ev.ts
    assert reconstructed.trace_id == ev.trace_id
    assert reconstructed.span_id == ev.span_id
    assert reconstructed.parent_span_id == ev.parent_span_id
    assert reconstructed.source == ev.source
    assert reconstructed.event_type == ev.event_type
    assert reconstructed.payload == ev.payload


def test_from_json_null_parent_span_id():
    ev = _make_event(parent_span_id=None)
    reconstructed = ChronicleEvent.from_json(ev.to_json())
    assert reconstructed.parent_span_id is None


def test_from_json_missing_payload_defaults_to_empty_dict():
    raw = json.dumps(
        {
            "ts": 1.0,
            "trace_id": "a" * 32,
            "span_id": "b" * 16,
            "parent_span_id": None,
            "source": "s",
            "event_type": "e",
        }
    )
    ev = ChronicleEvent.from_json(raw)
    assert ev.payload == {}


def test_payload_default_factory():
    ev1 = _make_event()
    ev2 = _make_event()
    # Ensure default dicts are not shared across instances.
    assert ev1.payload is not ev2.payload


# ── Task 2: OTel extraction ───────────────────────────────────────────────────


def test_current_otel_ids_no_active_span():
    trace_id, span_id = current_otel_ids()
    assert trace_id == "0" * 32
    assert span_id == "0" * 16


def test_current_otel_ids_returns_strings():
    trace_id, span_id = current_otel_ids()
    assert isinstance(trace_id, str)
    assert isinstance(span_id, str)


# ── Task 2: Writer ────────────────────────────────────────────────────────────


def test_record_creates_file(tmp_path: Path):
    p = tmp_path / "sub" / "events.jsonl"
    ev = _make_event()
    record(ev, path=p)
    assert p.exists()


def test_record_creates_parent_dirs(tmp_path: Path):
    p = tmp_path / "a" / "b" / "c" / "events.jsonl"
    record(_make_event(), path=p)
    assert p.exists()


def test_record_appends_multiple_events(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    ev1 = _make_event(source="alpha")
    ev2 = _make_event(source="beta")
    ev3 = _make_event(source="gamma")
    record(ev1, path=p)
    record(ev2, path=p)
    record(ev3, path=p)
    lines = p.read_text().strip().split("\n")
    assert len(lines) == 3
    sources = [json.loads(ln)["source"] for ln in lines]
    assert sources == ["alpha", "beta", "gamma"]


def test_record_each_line_is_valid_json(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    for i in range(5):
        record(_make_event(payload={"i": i}), path=p)
    for line in p.read_text().strip().split("\n"):
        json.loads(line)  # Must not raise.


# ── Task 3: Reader ────────────────────────────────────────────────────────────


def test_query_missing_file_returns_empty(tmp_path: Path):
    result = query(since=0.0, path=tmp_path / "nonexistent.jsonl")
    assert result == []


def test_query_empty_file_returns_empty(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    p.write_text("")
    result = query(since=0.0, path=p)
    assert result == []


def test_query_returns_events_in_range(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    now = time.time()
    old = _make_event(ts=now - 100)
    recent = _make_event(ts=now - 10)
    future = _make_event(ts=now + 100)
    for ev in (old, recent, future):
        record(ev, path=p)
    result = query(since=now - 50, until=now + 50, path=p)
    tss = {ev.ts for ev in result}
    assert recent.ts in tss
    assert old.ts not in tss
    assert future.ts not in tss


def test_query_returns_newest_first(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    now = time.time()
    for offset in (30, 20, 10):
        record(_make_event(ts=now - offset), path=p)
    result = query(since=0.0, path=p)
    assert len(result) == 3
    assert result[0].ts > result[1].ts > result[2].ts


def test_query_filter_by_source(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    record(_make_event(source="alpha"), path=p)
    record(_make_event(source="beta"), path=p)
    result = query(since=0.0, source="alpha", path=p)
    assert all(ev.source == "alpha" for ev in result)
    assert len(result) == 1


def test_query_filter_by_event_type(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    record(_make_event(event_type="voice.start"), path=p)
    record(_make_event(event_type="voice.end"), path=p)
    result = query(since=0.0, event_type="voice.start", path=p)
    assert len(result) == 1
    assert result[0].event_type == "voice.start"


def test_query_filter_by_trace_id(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    tid1 = "1" * 32
    tid2 = "2" * 32
    record(_make_event(trace_id=tid1), path=p)
    record(_make_event(trace_id=tid2), path=p)
    result = query(since=0.0, trace_id=tid1, path=p)
    assert len(result) == 1
    assert result[0].trace_id == tid1


def test_query_limit_enforced(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    now = time.time()
    for i in range(20):
        record(_make_event(ts=now - i), path=p)
    result = query(since=0.0, limit=5, path=p)
    assert len(result) == 5


def test_query_combined_filters(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    now = time.time()
    tid = "f" * 32
    record(_make_event(ts=now - 5, source="s1", event_type="e1", trace_id=tid), path=p)
    record(_make_event(ts=now - 5, source="s2", event_type="e1", trace_id=tid), path=p)
    record(_make_event(ts=now - 5, source="s1", event_type="e2", trace_id=tid), path=p)
    result = query(since=now - 10, source="s1", event_type="e1", trace_id=tid, path=p)
    assert len(result) == 1
    assert result[0].source == "s1"


def test_query_no_filters_returns_all(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    for _ in range(10):
        record(_make_event(), path=p)
    result = query(since=0.0, path=p)
    assert len(result) == 10


def test_query_skips_malformed_lines(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    record(_make_event(), path=p)
    with p.open("a") as fh:
        fh.write("not-valid-json\n")
    record(_make_event(), path=p)
    result = query(since=0.0, path=p)
    assert len(result) == 2  # Malformed line silently skipped.


# ── Task 4: Retention ─────────────────────────────────────────────────────────


def test_trim_missing_file_is_noop(tmp_path: Path):
    p = tmp_path / "no_such_file.jsonl"
    trim(retention_s=3600, path=p)  # Must not raise.
    assert not p.exists()


def test_trim_removes_old_events(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    now = time.time()
    old = _make_event(ts=now - 7200)  # 2 h ago — outside 1 h retention
    fresh = _make_event(ts=now - 30)  # 30 s ago — within 1 h retention
    record(old, path=p)
    record(fresh, path=p)
    trim(retention_s=3600, path=p)
    remaining = query(since=0.0, path=p)
    tss = {ev.ts for ev in remaining}
    assert fresh.ts in tss
    assert old.ts not in tss


def test_trim_keeps_all_fresh_events(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    now = time.time()
    for offset in (10, 20, 30):
        record(_make_event(ts=now - offset), path=p)
    trim(retention_s=3600, path=p)
    remaining = query(since=0.0, path=p)
    assert len(remaining) == 3


def test_trim_removes_all_stale_events(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    now = time.time()
    for offset in (7200, 10800, 14400):
        record(_make_event(ts=now - offset), path=p)
    trim(retention_s=3600, path=p)
    remaining = query(since=0.0, path=p)
    assert remaining == []


def test_trim_atomic_rewrite(tmp_path: Path):
    """After trim, no .tmp file should remain."""
    p = tmp_path / "events.jsonl"
    record(_make_event(), path=p)
    trim(retention_s=3600, path=p)
    assert not p.with_suffix(".tmp").exists()


def test_trim_default_retention_constant():
    assert RETENTION_S == 12 * 3600


# ── Full roundtrip ────────────────────────────────────────────────────────────


def test_full_roundtrip_record_query_trim(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    now = time.time()
    stale = _make_event(ts=now - 43201, source="old", event_type="stale")  # > 12 h
    fresh1 = _make_event(ts=now - 60, source="new", event_type="fresh", trace_id="d" * 32)
    fresh2 = _make_event(ts=now - 30, source="new", event_type="fresh", trace_id="d" * 32)

    for ev in (stale, fresh1, fresh2):
        record(ev, path=p)

    # Verify all 3 events are readable before trim.
    all_events = query(since=0.0, path=p)
    assert len(all_events) == 3

    # Trim with 12-hour retention.
    trim(retention_s=RETENTION_S, path=p)

    remaining = query(since=0.0, path=p)
    assert len(remaining) == 2
    assert all(ev.source == "new" for ev in remaining)

    # Filter by trace_id.
    by_trace = query(since=0.0, trace_id="d" * 32, path=p)
    assert len(by_trace) == 2

    # newest-first ordering preserved.
    assert by_trace[0].ts > by_trace[1].ts


# ── Evidence envelope (cc-task chronicle-event-evidence-envelope-migration) ──


class TestEvidenceEnvelopeDefaults:
    """The evidence envelope is opt-in; legacy callers must keep working."""

    def test_legacy_constructor_assigns_event_id(self) -> None:
        ev = _make_event()
        # event_id auto-assigned via UUID4 (32-hex string).
        assert len(ev.event_id) == 32
        assert all(c in "0123456789abcdef" for c in ev.event_id)

    def test_legacy_defaults_for_envelope_fields(self) -> None:
        ev = _make_event()
        assert ev.valid_time is None
        assert ev.transaction_time is None
        assert ev.aperture_ref == ""
        assert ev.public_scope == "private"
        assert ev.speech_event_ref == ""
        assert ev.impulse_ref == ""
        assert ev.triad_ref == ""
        assert ev.evidence_class == ""
        assert ev.evidence_refs == ()
        assert ev.temporal_span_ref == ""

    def test_effective_times_default_to_ts(self) -> None:
        ev = _make_event(ts=1234.0)
        assert ev.effective_valid_time == 1234.0
        assert ev.effective_transaction_time == 1234.0

    def test_effective_times_use_explicit_values_when_set(self) -> None:
        ev = ChronicleEvent(
            ts=1234.0,
            trace_id="a" * 32,
            span_id="b" * 16,
            parent_span_id=None,
            source="src",
            event_type="t",
            valid_time=1000.0,
            transaction_time=1500.0,
        )
        assert ev.effective_valid_time == 1000.0
        assert ev.effective_transaction_time == 1500.0

    def test_unique_event_ids_across_legacy_constructions(self) -> None:
        a = _make_event()
        b = _make_event()
        assert a.event_id != b.event_id


class TestHasFullProvenance:
    """Authority downgrade hinges on the trace/span zero-fill predicate."""

    def test_zero_trace_and_span_returns_false(self) -> None:
        ev = ChronicleEvent(
            ts=1234.0,
            trace_id="0" * 32,
            span_id="0" * 16,
            parent_span_id=None,
            source="src",
            event_type="t",
        )
        assert ev.has_full_provenance is False

    def test_real_trace_and_span_returns_true(self) -> None:
        ev = _make_event()
        assert ev.has_full_provenance is True

    def test_zero_trace_only_returns_false(self) -> None:
        ev = ChronicleEvent(
            ts=1234.0,
            trace_id="0" * 32,
            span_id="b" * 16,
            parent_span_id=None,
            source="src",
            event_type="t",
        )
        assert ev.has_full_provenance is False

    def test_zero_span_only_returns_false(self) -> None:
        ev = ChronicleEvent(
            ts=1234.0,
            trace_id="a" * 32,
            span_id="0" * 16,
            parent_span_id=None,
            source="src",
            event_type="t",
        )
        assert ev.has_full_provenance is False


class TestSerializationRoundTrip:
    """Pre-migration JSONL must read back correctly; new fields round-trip."""

    def test_pre_migration_jsonl_reads_with_defaults(self) -> None:
        # Hand-crafted legacy line — none of the new fields present.
        legacy = json.dumps(
            {
                "ts": 1234.0,
                "trace_id": "a" * 32,
                "span_id": "b" * 16,
                "parent_span_id": None,
                "source": "legacy_src",
                "event_type": "legacy.event",
                "payload": {"k": "v"},
            }
        )
        ev = ChronicleEvent.from_json(legacy)
        assert ev.ts == 1234.0
        assert ev.source == "legacy_src"
        assert ev.payload == {"k": "v"}
        # Synthetic event_id derived from trace_id/span_id/ts via UUID5.
        assert len(ev.event_id) == 32
        # Re-reading the same legacy line yields the same event_id
        # (deterministic UUID5 namespace fallback).
        ev2 = ChronicleEvent.from_json(legacy)
        assert ev.event_id == ev2.event_id
        # All envelope fields fall back to dataclass defaults.
        assert ev.aperture_ref == ""
        assert ev.public_scope == "private"
        assert ev.evidence_refs == ()

    def test_envelope_fields_round_trip(self) -> None:
        original = ChronicleEvent(
            ts=1234.0,
            trace_id="a" * 32,
            span_id="b" * 16,
            parent_span_id="c" * 16,
            source="src",
            event_type="t",
            payload={"k": "v"},
            event_id="custom-event-id",
            valid_time=1000.0,
            transaction_time=1500.0,
            aperture_ref="aperture.broadcast.live",
            public_scope="public",
            speech_event_ref="speech-1",
            impulse_ref="impulse-2",
            triad_ref="triad-3",
            evidence_class="sensor",
            evidence_refs=("ref-1", "ref-2"),
            temporal_span_ref="span-7",
        )
        round_tripped = ChronicleEvent.from_json(original.to_json())
        assert round_tripped == original

    def test_to_json_omits_empty_envelope_fields(self) -> None:
        # Legacy events shouldn't bloat the JSONL with empty optional
        # fields. Only `event_id` and `public_scope` are unconditionally
        # emitted (the contract for downstream consumers that want a
        # universally-present handle and scope).
        ev = _make_event()
        decoded = json.loads(ev.to_json())
        assert "event_id" in decoded
        assert "public_scope" in decoded  # default "private" always emitted
        assert "aperture_ref" not in decoded
        assert "speech_event_ref" not in decoded
        assert "evidence_refs" not in decoded
        assert "temporal_span_ref" not in decoded

    def test_to_json_emits_envelope_fields_when_set(self) -> None:
        ev = ChronicleEvent(
            ts=1234.0,
            trace_id="a" * 32,
            span_id="b" * 16,
            parent_span_id=None,
            source="src",
            event_type="t",
            aperture_ref="aperture.broadcast.live",
            evidence_class="sensor",
            evidence_refs=("ref-1",),
        )
        decoded = json.loads(ev.to_json())
        assert decoded["aperture_ref"] == "aperture.broadcast.live"
        assert decoded["evidence_class"] == "sensor"
        assert decoded["evidence_refs"] == ["ref-1"]


class TestEnvelopeQueryFilters:
    """The new query filters must be honored."""

    def _seed(self, p: Path) -> None:
        # Three events with distinct envelope fields.
        ts = time.time()
        record(
            ChronicleEvent(
                ts=ts - 30,
                trace_id="a" * 32,
                span_id="b" * 16,
                parent_span_id=None,
                source="src",
                event_type="t",
                aperture_ref="aperture.broadcast.live",
                public_scope="public",
                evidence_class="sensor",
                speech_event_ref="speech-A",
                temporal_span_ref="span-1",
            ),
            path=p,
        )
        record(
            ChronicleEvent(
                ts=ts - 20,
                trace_id="a" * 32,
                span_id="b" * 16,
                parent_span_id=None,
                source="src",
                event_type="t",
                aperture_ref="aperture.private.console",
                public_scope="private",
                evidence_class="route",
                temporal_span_ref="span-2",
            ),
            path=p,
        )
        record(
            ChronicleEvent(
                ts=ts - 10,
                trace_id="a" * 32,
                span_id="b" * 16,
                parent_span_id=None,
                source="src",
                event_type="t",
                aperture_ref="aperture.broadcast.live",
                public_scope="diagnostic",
                evidence_class="sensor",
            ),
            path=p,
        )

    def test_filter_by_aperture_ref(self, tmp_path: Path) -> None:
        p = tmp_path / "chronicle.jsonl"
        self._seed(p)
        results = query(since=0.0, aperture_ref="aperture.broadcast.live", path=p)
        assert len(results) == 2

    def test_filter_by_public_scope(self, tmp_path: Path) -> None:
        p = tmp_path / "chronicle.jsonl"
        self._seed(p)
        public = query(since=0.0, public_scope="public", path=p)
        private = query(since=0.0, public_scope="private", path=p)
        diagnostic = query(since=0.0, public_scope="diagnostic", path=p)
        assert len(public) == 1
        assert len(private) == 1
        assert len(diagnostic) == 1

    def test_filter_by_speech_event_ref(self, tmp_path: Path) -> None:
        p = tmp_path / "chronicle.jsonl"
        self._seed(p)
        results = query(since=0.0, speech_event_ref="speech-A", path=p)
        assert len(results) == 1
        assert results[0].speech_event_ref == "speech-A"

    def test_filter_by_evidence_class(self, tmp_path: Path) -> None:
        p = tmp_path / "chronicle.jsonl"
        self._seed(p)
        results = query(since=0.0, evidence_class="sensor", path=p)
        assert len(results) == 2

    def test_filter_by_temporal_span_ref(self, tmp_path: Path) -> None:
        p = tmp_path / "chronicle.jsonl"
        self._seed(p)
        results = query(since=0.0, temporal_span_ref="span-1", path=p)
        assert len(results) == 1

    def test_envelope_filter_combines_with_legacy_filters(self, tmp_path: Path) -> None:
        p = tmp_path / "chronicle.jsonl"
        self._seed(p)
        # public + sensor narrows to one event.
        results = query(
            since=0.0,
            public_scope="public",
            evidence_class="sensor",
            path=p,
        )
        assert len(results) == 1
        assert results[0].public_scope == "public"
        assert results[0].evidence_class == "sensor"


class TestLegacyJsonlMixedFile:
    """Pre-migration + post-migration lines coexist in the same file."""

    def test_legacy_and_new_round_trip_in_same_file(self, tmp_path: Path) -> None:
        p = tmp_path / "chronicle.jsonl"
        # Legacy line written by hand.
        legacy_payload = {
            "ts": time.time() - 100,
            "trace_id": "a" * 32,
            "span_id": "b" * 16,
            "parent_span_id": None,
            "source": "legacy",
            "event_type": "t",
            "payload": {},
        }
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(legacy_payload) + "\n", encoding="utf-8")
        # New line via the writer.
        record(
            ChronicleEvent(
                ts=time.time(),
                trace_id="a" * 32,
                span_id="b" * 16,
                parent_span_id=None,
                source="modern",
                event_type="t",
                public_scope="public",
                aperture_ref="aperture.live",
            ),
            path=p,
        )
        results = query(since=0.0, path=p)
        assert len(results) == 2
        # Filter by aperture; legacy event has empty aperture_ref so
        # only the modern event surfaces.
        modern_only = query(since=0.0, aperture_ref="aperture.live", path=p)
        assert len(modern_only) == 1
        assert modern_only[0].source == "modern"
