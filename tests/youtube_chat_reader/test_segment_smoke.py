"""End-to-end smoke for chat-ingestion segment observability.

Drives the real :class:`ChatReader` (with a mocked YouTube API client)
through fixture chat items, wraps the cycle in
:func:`record_chat_reactivity_segment`, and asserts the segments.jsonl
log carries matching ``STARTED`` + ``HAPPENED`` events with the
expected ``quality.chat_reactivity`` rating.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from prometheus_client import CollectorRegistry

from agents.youtube_chat_reader.reader import ChatReader
from agents.youtube_chat_reader.segment_smoke import (
    ChatReactivityAssessment,
    assess_chat_reactivity,
    record_chat_reactivity_segment,
)
from shared.segment_observability import QualityRating, SegmentLifecycle


def _broadcast_response(*, broadcast_id: str = "BC1", live_chat_id: str = "LC1") -> dict:
    return {
        "items": [
            {
                "id": broadcast_id,
                "snippet": {"liveChatId": live_chat_id, "title": "smoke"},
                "status": {"lifeCycleStatus": "live"},
            }
        ]
    }


def _chat_response(items: list[dict], *, polling_ms: int = 2000) -> dict:
    return {
        "items": items,
        "nextPageToken": "tok-next",
        "pollingIntervalMillis": polling_ms,
    }


def _msg(text: str, *, item_id: str | None = None, author: str = "UC-smoke") -> dict:
    item_id = item_id or f"m-{abs(hash(text)) % 1_000_000}"
    return {
        "id": item_id,
        "snippet": {"displayMessage": text, "publishedAt": "2026-05-04T05:30:00Z"},
        "authorDetails": {"channelId": author},
    }


@pytest.fixture
def fake_client() -> MagicMock:
    client = MagicMock()
    client.enabled = True
    client.yt = MagicMock()
    return client


@pytest.fixture
def reader_factory(tmp_path: Path):
    def _factory(client: MagicMock) -> ChatReader:
        return ChatReader(
            client=client,
            impingement_path=tmp_path / "impingements.jsonl",
            chat_state_path=tmp_path / "recent.jsonl",
            registry=CollectorRegistry(),
        )

    return _factory


def _segments(log_path: Path) -> list[dict]:
    """Read every segment event from the smoke log."""
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]


# ── Pure assessor ─────────────────────────────────────────────────────


def test_assess_poor_when_no_emissions(tmp_path: Path) -> None:
    bus = tmp_path / "bus.jsonl"
    bus.write_text("")
    result = assess_chat_reactivity(bus_path=bus, expected_inputs=5)
    assert result.rating is QualityRating.POOR
    assert result.impingements_emitted == 0


def test_assess_poor_when_no_inputs_no_emissions(tmp_path: Path) -> None:
    bus = tmp_path / "bus.jsonl"
    bus.write_text("")
    result = assess_chat_reactivity(bus_path=bus, expected_inputs=0)
    assert result.rating is QualityRating.POOR
    assert "did not run" in result.notes


def test_assess_acceptable_when_emit_ratio_partial(tmp_path: Path) -> None:
    bus = tmp_path / "bus.jsonl"
    record = {
        "source": "youtube_chat",
        "content": {"text": "hello", "author_token": "abcdef012345"},
    }
    bus.write_text(json.dumps(record) + "\n")
    result = assess_chat_reactivity(bus_path=bus, expected_inputs=5)
    assert result.rating is QualityRating.ACCEPTABLE


def test_assess_excellent_when_clean_full_flow(tmp_path: Path) -> None:
    bus = tmp_path / "bus.jsonl"
    bus.write_text(
        "\n".join(
            json.dumps(
                {
                    "source": "youtube_chat",
                    "content": {
                        "text": f"clean message {i}",
                        "author_token": "abcdef012345",
                    },
                }
            )
            for i in range(10)
        )
        + "\n"
    )
    result = assess_chat_reactivity(bus_path=bus, expected_inputs=10)
    assert result.rating is QualityRating.EXCELLENT


def test_assess_good_when_full_flow_but_one_malformed(tmp_path: Path) -> None:
    bus = tmp_path / "bus.jsonl"
    rows = [
        {
            "source": "youtube_chat",
            "content": {"text": f"clean {i}", "author_token": "abcdef012345"},
        }
        for i in range(9)
    ]
    rows.append(
        {
            "source": "youtube_chat",
            "content": {
                # URL slipped through — well-formed check fails.
                "text": "click https://evil.example.com/x now",
                "author_token": "abcdef012345",
            },
        }
    )
    bus.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    result = assess_chat_reactivity(bus_path=bus, expected_inputs=10)
    assert result.rating is QualityRating.GOOD
    assert result.well_formed == 9


def test_assess_ignores_non_chat_records(tmp_path: Path) -> None:
    bus = tmp_path / "bus.jsonl"
    rows = [
        {"source": "relay.inflection", "content": {}},
        {"source": "youtube_telemetry", "content": {}},
        {"source": "youtube_chat", "content": {"text": "hi", "author_token": "abcdef012345"}},
    ]
    bus.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    result = assess_chat_reactivity(bus_path=bus, expected_inputs=1)
    assert result.impingements_emitted == 1
    assert result.rating is QualityRating.EXCELLENT


def test_assess_skips_malformed_lines(tmp_path: Path) -> None:
    bus = tmp_path / "bus.jsonl"
    bus.write_text(
        "{not json\n"
        + json.dumps(
            {
                "source": "youtube_chat",
                "content": {"text": "ok", "author_token": "abcdef012345"},
            }
        )
        + "\n"
    )
    result = assess_chat_reactivity(bus_path=bus, expected_inputs=1)
    assert result.impingements_emitted == 1
    assert isinstance(result, ChatReactivityAssessment)


# ── Recorder helper integrated with the real reader ───────────────────


def test_recorder_emits_started_and_happened(
    fake_client: MagicMock, reader_factory, tmp_path: Path
) -> None:
    """Smoke: drive a clean batch through the reader inside the recorder."""
    fake_client.execute.side_effect = [
        _broadcast_response(),
        _chat_response([_msg(f"clean {i}", item_id=f"m{i}") for i in range(5)]),
    ]
    reader = reader_factory(fake_client)
    bus = reader._impingement_path  # noqa: SLF001 — direct access for the smoke
    seg_log = tmp_path / "segments.jsonl"

    with record_chat_reactivity_segment(
        bus_path=bus,
        expected_inputs=5,
        topic_seed="smoke-clean",
        log_path=seg_log,
    ) as event:
        reader.tick_once(now=1000.0)
        reader.tick_once(now=1000.0)
        assert event.programme_role == "chat_ingestion"
        assert event.topic_seed == "smoke-clean"

    events = _segments(seg_log)
    assert len(events) == 2
    started, happened = events
    assert started["lifecycle"] == SegmentLifecycle.STARTED.value
    assert happened["lifecycle"] == SegmentLifecycle.HAPPENED.value
    assert started["segment_id"] == happened["segment_id"]
    assert happened["quality"]["chat_reactivity"] == QualityRating.EXCELLENT.value
    assert "emit_ratio=1.00" in happened["quality"]["notes"]


def test_recorder_records_didnt_happen_on_exception(
    fake_client: MagicMock, reader_factory, tmp_path: Path
) -> None:
    """An exception inside the block must surface as DIDNT_HAPPEN."""
    fake_client.execute.side_effect = [_broadcast_response()]
    reader = reader_factory(fake_client)
    bus = reader._impingement_path  # noqa: SLF001
    seg_log = tmp_path / "segments.jsonl"

    with pytest.raises(RuntimeError, match="boom"):
        with record_chat_reactivity_segment(
            bus_path=bus,
            expected_inputs=1,
            log_path=seg_log,
        ):
            reader.tick_once(now=1000.0)
            raise RuntimeError("boom — driver crashed")

    events = _segments(seg_log)
    assert len(events) == 2
    assert events[1]["lifecycle"] == SegmentLifecycle.DIDNT_HAPPEN.value
    # No quality assessment should have been written.
    assert events[1]["quality"]["chat_reactivity"] == QualityRating.UNMEASURED.value


def test_recorder_marks_poor_when_idle_broadcast(
    fake_client: MagicMock, reader_factory, tmp_path: Path
) -> None:
    """No active broadcast → no impingements → POOR rating but HAPPENED."""
    fake_client.execute.return_value = {"items": []}
    reader = reader_factory(fake_client)
    bus = reader._impingement_path  # noqa: SLF001
    seg_log = tmp_path / "segments.jsonl"

    with record_chat_reactivity_segment(
        bus_path=bus,
        expected_inputs=3,
        log_path=seg_log,
    ):
        reader.tick_once(now=1000.0)

    events = _segments(seg_log)
    assert events[1]["lifecycle"] == SegmentLifecycle.HAPPENED.value
    assert events[1]["quality"]["chat_reactivity"] == QualityRating.POOR.value


def test_recorder_handles_mixed_batch_sanitisation(
    fake_client: MagicMock, reader_factory, tmp_path: Path
) -> None:
    """One URL message + one blank message: blank drops, URL gets stripped to [link]."""
    items = [
        _msg("clean message", item_id="ok-1"),
        _msg("check https://evil.example.com now", item_id="url-1"),
        _msg("   ", item_id="blank-1"),  # dropped by sanitiser
        _msg("another clean", item_id="ok-2"),
    ]
    fake_client.execute.side_effect = [
        _broadcast_response(),
        _chat_response(items),
    ]
    reader = reader_factory(fake_client)
    bus = reader._impingement_path  # noqa: SLF001
    seg_log = tmp_path / "segments.jsonl"

    # Caller passes 3 expected inputs because the blank one is correctly dropped.
    with record_chat_reactivity_segment(
        bus_path=bus,
        expected_inputs=3,
        log_path=seg_log,
    ):
        reader.tick_once(now=1000.0)
        reader.tick_once(now=1000.0)

    events = _segments(seg_log)
    happened = events[-1]
    assert happened["lifecycle"] == SegmentLifecycle.HAPPENED.value
    # URL was sanitised → all 3 emissions are well-formed → EXCELLENT.
    assert happened["quality"]["chat_reactivity"] == QualityRating.EXCELLENT.value


def test_recorder_preserves_caller_notes(
    fake_client: MagicMock, reader_factory, tmp_path: Path
) -> None:
    """If the caller writes notes inside the block, they must survive."""
    fake_client.execute.side_effect = [
        _broadcast_response(),
        _chat_response([_msg("hi")]),
    ]
    reader = reader_factory(fake_client)
    bus = reader._impingement_path  # noqa: SLF001
    seg_log = tmp_path / "segments.jsonl"

    with record_chat_reactivity_segment(
        bus_path=bus,
        expected_inputs=1,
        log_path=seg_log,
    ) as event:
        event.quality.notes = "fixture run; no live broadcast"
        reader.tick_once(now=1000.0)
        reader.tick_once(now=1000.0)

    events = _segments(seg_log)
    happened = events[-1]
    notes = happened["quality"]["notes"]
    assert "fixture run; no live broadcast" in notes
    assert "emit_ratio=1.00" in notes  # appended after the |
