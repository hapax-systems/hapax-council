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
