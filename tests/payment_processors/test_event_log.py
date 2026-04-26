"""Tests for ``agents.payment_processors.event_log``."""

from __future__ import annotations

from datetime import UTC, datetime

from agents.operator_awareness.state import PaymentEvent
from agents.payment_processors.event_log import append_event, tail_events


def _now() -> datetime:
    return datetime.now(UTC)


def _make(rail: str = "lightning", *, ext: str = "abc", sats: int | None = 100) -> PaymentEvent:
    return PaymentEvent(
        timestamp=_now(),
        rail=rail,  # type: ignore[arg-type]
        amount_sats=sats,
        sender_excerpt="hi",
        external_id=ext,
    )


class TestAppendEvent:
    def test_writes_one_line_per_event(self, tmp_path):
        path = tmp_path / "events.jsonl"
        assert append_event(_make(ext="x1"), log_path=path)
        assert append_event(_make(ext="x2"), log_path=path)
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_creates_parent_dir(self, tmp_path):
        path = tmp_path / "deep" / "events.jsonl"
        assert append_event(_make(ext="x1"), log_path=path)
        assert path.exists()


class TestTailEvents:
    def test_missing_file_returns_empty(self, tmp_path):
        assert tail_events(log_path=tmp_path / "absent.jsonl") == []

    def test_returns_events_in_order(self, tmp_path):
        path = tmp_path / "events.jsonl"
        for i in range(3):
            append_event(_make(ext=f"x{i}"), log_path=path)
        events = tail_events(log_path=path)
        assert [e.external_id for e in events] == ["x0", "x1", "x2"]

    def test_skips_malformed_lines(self, tmp_path):
        path = tmp_path / "events.jsonl"
        append_event(_make(ext="x1"), log_path=path)
        with path.open("a", encoding="utf-8") as fh:
            fh.write("garbage line not json\n")
        append_event(_make(ext="x2"), log_path=path)
        events = tail_events(log_path=path)
        assert [e.external_id for e in events] == ["x1", "x2"]

    def test_respects_limit(self, tmp_path):
        path = tmp_path / "events.jsonl"
        for i in range(5):
            append_event(_make(ext=f"x{i}"), log_path=path)
        events = tail_events(log_path=path, limit=2)
        assert [e.external_id for e in events] == ["x3", "x4"]
