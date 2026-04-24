"""Tests for the cuepoint consumer + inline JSONL tailer.

No live API hit — the YouTubeApiClient is replaced with a fake that
records the requests made to :func:`emit_cuepoint`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agents.live_cuepoints.consumer import (
    CuepointConsumer,
    _is_chapter_worthy,
    _JsonlTailer,
    iter_events,
)


class _FakeClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, secs: float) -> None:
        self.now += secs


class _FakeClient:
    def __init__(self) -> None:
        self.enabled = True
        self.calls: list[dict[str, Any]] = []
        self.next_response: Any = {"kind": "youtube#liveBroadcast"}

    def execute(self, request: Any, *, endpoint: str, quota_cost_hint: int | None = None) -> Any:
        self.calls.append(
            {
                "endpoint": endpoint,
                "quota_cost_hint": quota_cost_hint,
            }
        )
        return self.next_response


class _FakeYtService:
    def liveBroadcasts(self) -> Any:  # noqa: N802
        class _LB:
            def cuepoint(self, **kwargs: Any) -> Any:
                return kwargs

        return _LB()


@pytest.fixture()
def fake_client(monkeypatch):
    client = _FakeClient()
    client.yt = _FakeYtService()  # type: ignore[attr-defined]
    return client


@pytest.fixture()
def event_file(tmp_path):
    return tmp_path / "events.jsonl"


@pytest.fixture()
def cursor_file(tmp_path):
    return tmp_path / "cursor.txt"


def _write_event(path: Path, event: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")


def _rotation(broadcast_id: str) -> dict[str, Any]:
    return {
        "event_type": "broadcast_rotated",
        "incoming_broadcast_id": broadcast_id,
        "outgoing_broadcast_id": "old-xyz",
    }


# --- JsonlTailer ---------------------------------------------------------


def test_tailer_first_run_seeks_to_end(event_file, cursor_file):
    _write_event(event_file, _rotation("a"))
    _write_event(event_file, _rotation("b"))
    tailer = _JsonlTailer(event_file, cursor_file)
    assert tailer.read_new() == [], "first run must skip existing lines"
    assert cursor_file.read_text().strip() == "2"


def test_tailer_subsequent_reads_get_new_lines(event_file, cursor_file):
    _write_event(event_file, _rotation("a"))
    tailer = _JsonlTailer(event_file, cursor_file)
    tailer.read_new()  # seek to end
    _write_event(event_file, _rotation("b"))
    _write_event(event_file, _rotation("c"))
    events = tailer.read_new()
    assert [e.get("incoming_broadcast_id") for e in events] == ["b", "c"]


def test_tailer_cursor_persists_across_instances(event_file, cursor_file):
    _write_event(event_file, _rotation("a"))
    t1 = _JsonlTailer(event_file, cursor_file)
    t1.read_new()
    _write_event(event_file, _rotation("b"))
    t2 = _JsonlTailer(event_file, cursor_file)
    events = t2.read_new()
    assert [e.get("incoming_broadcast_id") for e in events] == ["b"]


def test_tailer_tolerates_malformed_lines(event_file, cursor_file):
    event_file.write_text("not valid json\n")
    tailer = _JsonlTailer(event_file, cursor_file)
    tailer.read_new()  # seek to end
    with event_file.open("a") as fh:
        fh.write("still malformed\n")
        fh.write(json.dumps(_rotation("z")) + "\n")
    events = tailer.read_new()
    assert len(events) == 1
    assert events[0].get("incoming_broadcast_id") == "z"


def test_tailer_handles_missing_file(tmp_path, cursor_file):
    tailer = _JsonlTailer(tmp_path / "does-not-exist.jsonl", cursor_file)
    assert tailer.read_new() == []


def test_tailer_shrinkage_resets_cursor(event_file, cursor_file):
    for bid in ("a", "b", "c"):
        _write_event(event_file, _rotation(bid))
    tailer = _JsonlTailer(event_file, cursor_file)
    tailer.read_new()  # seek to 3
    # Rotate the file (simulate truncation).
    event_file.write_text("")
    assert tailer.read_new() == []
    assert cursor_file.read_text().strip() == "0"


# --- CuepointConsumer ----------------------------------------------------


def test_consumer_emits_on_rotation(event_file, cursor_file, fake_client):
    clock = _FakeClock()
    consumer = CuepointConsumer(
        fake_client,
        event_path=event_file,
        cursor_path=cursor_file,
        time_fn=clock,
    )
    _write_event(event_file, _rotation("broadcast-new-1"))
    emitted = consumer.poll_once()
    assert emitted == 1
    assert len(fake_client.calls) == 1
    assert fake_client.calls[0]["endpoint"] == "liveBroadcasts.cuepoint"


def test_consumer_debounces_rapid_rotations(event_file, cursor_file, fake_client):
    clock = _FakeClock()
    consumer = CuepointConsumer(
        fake_client,
        event_path=event_file,
        cursor_path=cursor_file,
        debounce_s=90,
        time_fn=clock,
    )
    _write_event(event_file, _rotation("broadcast-1"))
    assert consumer.poll_once() == 1
    clock.advance(30)  # within debounce
    _write_event(event_file, _rotation("broadcast-2"))
    assert consumer.poll_once() == 0
    assert len(fake_client.calls) == 1  # only the first
    clock.advance(120)  # past debounce
    _write_event(event_file, _rotation("broadcast-3"))
    assert consumer.poll_once() == 1
    assert len(fake_client.calls) == 2


def test_consumer_rate_caps(event_file, cursor_file, fake_client):
    clock = _FakeClock()
    consumer = CuepointConsumer(
        fake_client,
        event_path=event_file,
        cursor_path=cursor_file,
        debounce_s=0,
        max_per_hour=2,
        time_fn=clock,
    )
    for i in range(5):
        _write_event(event_file, _rotation(f"b-{i}"))
        clock.advance(60)
    consumer.poll_once()
    # Only 2 of the 5 should succeed inside a 1-hour window.
    assert len(fake_client.calls) == 2


def test_consumer_ignores_non_rotation_events(event_file, cursor_file, fake_client):
    clock = _FakeClock()
    consumer = CuepointConsumer(
        fake_client,
        event_path=event_file,
        cursor_path=cursor_file,
        time_fn=clock,
    )
    _write_event(event_file, {"event_type": "some_other_event", "data": 1})
    _write_event(event_file, _rotation("only-this-one"))
    emitted = consumer.poll_once()
    assert emitted == 1
    assert len(fake_client.calls) == 1


def test_consumer_missing_broadcast_id_skips(event_file, cursor_file, fake_client):
    clock = _FakeClock()
    consumer = CuepointConsumer(
        fake_client,
        event_path=event_file,
        cursor_path=cursor_file,
        time_fn=clock,
    )
    _write_event(
        event_file,
        {"event_type": "broadcast_rotated", "outgoing_broadcast_id": "x"},
    )
    assert consumer.poll_once() == 0
    assert fake_client.calls == []


def test_consumer_api_silent_skip(event_file, cursor_file, fake_client):
    clock = _FakeClock()
    fake_client.next_response = None  # quota silent-skip
    consumer = CuepointConsumer(
        fake_client,
        event_path=event_file,
        cursor_path=cursor_file,
        time_fn=clock,
    )
    _write_event(event_file, _rotation("will-skip"))
    emitted = consumer.poll_once()
    assert emitted == 0
    # Debounce ts should NOT advance on a skipped emit (so next real event can try).
    assert consumer._last_emit_ts == 0.0


# --- helpers -------------------------------------------------------------


def test_is_chapter_worthy():
    assert _is_chapter_worthy({"event_type": "broadcast_rotated"})
    assert not _is_chapter_worthy({"event_type": "something_else"})
    assert not _is_chapter_worthy({})


def test_iter_events_yields_parseable(event_file):
    _write_event(event_file, _rotation("a"))
    event_file.open("a").write("malformed\n")
    _write_event(event_file, _rotation("b"))
    out = list(iter_events(event_file))
    ids = [e.get("incoming_broadcast_id") for e in out]
    assert ids == ["a", "b"]


def test_iter_events_missing_file_returns_empty(tmp_path):
    assert list(iter_events(tmp_path / "nope.jsonl")) == []
