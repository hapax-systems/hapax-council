"""Tests for private SS2 cycle sampling/reporting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from shared.chronicle import ChronicleEvent, record
from shared.operator_quality_feedback import (
    append_operator_quality_rating,
    build_operator_quality_rating,
)
from shared.ss2_cycle_report import (
    build_ss2_cycle_report,
    load_autonomous_narrative_events,
    sample_autonomous_narrative_events,
)


def _event(
    event_id: str,
    *,
    ts: float,
    source: str = "self_authored_narrative",
    event_type: str = "narrative.emitted",
    programme_id: str = "prog-1",
    text: str = "Hapax observed a concrete module transition.",
    grounding: object | None = ("vault:daily:2026-05-11",),
    novelty_score: float | None = None,
) -> ChronicleEvent:
    payload: dict[str, object] = {
        "narrative": text,
        "programme_id": programme_id,
        "speech_event_id": f"speech-{event_id}",
        "salience": 0.6,
    }
    if grounding is not None:
        payload["grounding_provenance"] = grounding
    if novelty_score is not None:
        payload["novelty_score"] = novelty_score
    return ChronicleEvent(
        ts=ts,
        trace_id="1" * 32,
        span_id="2" * 16,
        parent_span_id=None,
        source=source,
        event_type=event_type,
        payload=payload,
        event_id=event_id,
    )


def _write_events(path: Path, events: list[ChronicleEvent]) -> None:
    for event in events:
        record(event, path=path)


def _append_rating(
    path: Path,
    *,
    rating: int,
    axis: str,
    occurred_at: datetime,
    emission_ref: str | None = None,
    programme_id: str | None = None,
) -> None:
    append_operator_quality_rating(
        build_operator_quality_rating(
            rating=rating,
            rating_axis=axis,
            occurred_at=occurred_at,
            emission_ref=emission_ref,
            programme_id=programme_id,
        ),
        path=path,
    )


def test_load_autonomous_narrative_events_filters_non_ss2_events(tmp_path: Path) -> None:
    chronicle = tmp_path / "events.jsonl"
    _write_events(
        chronicle,
        [
            _event("wanted", ts=100.0),
            _event("wrong-source", ts=101.0, source="sensor.audio"),
            _event("wrong-type", ts=102.0, event_type="other.event"),
        ],
    )

    events = load_autonomous_narrative_events(since=0.0, until=200.0, path=chronicle)

    assert [event.event_id for event in events] == ["wanted"]


def test_sample_autonomous_narrative_events_is_seeded_and_chronological() -> None:
    events = tuple(_event(f"ev-{i}", ts=float(i)) for i in range(10))

    first = sample_autonomous_narrative_events(events, sample_size=4, seed="cycle-1")
    second = sample_autonomous_narrative_events(events, sample_size=4, seed="cycle-1")
    other = sample_autonomous_narrative_events(events, sample_size=4, seed="cycle-2")

    assert [event.event_id for event in first] == [event.event_id for event in second]
    assert [event.event_id for event in first] != [event.event_id for event in other]
    assert [event.ts for event in first] == sorted(event.ts for event in first)


def test_cycle_report_joins_direct_and_window_ratings(tmp_path: Path) -> None:
    chronicle = tmp_path / "events.jsonl"
    ratings = tmp_path / "ratings.jsonl"
    start = datetime.fromtimestamp(100.0, UTC)
    end = datetime.fromtimestamp(200.0, UTC)
    _write_events(
        chronicle,
        [
            _event("ev-1", ts=120.0, novelty_score=0.6),
            _event("ev-2", ts=130.0, novelty_score=0.8),
        ],
    )
    for axis in (
        "substantive",
        "grounded",
        "stimmung_coherence",
        "programme_respecting",
        "listenable",
    ):
        _append_rating(
            ratings,
            rating=4,
            axis=axis,
            occurred_at=end + timedelta(minutes=30),
            emission_ref="chronicle:ev-1",
        )
        _append_rating(
            ratings,
            rating=5,
            axis=axis,
            occurred_at=start + timedelta(seconds=30),
            programme_id="prog-1",
        )

    report = build_ss2_cycle_report(
        cycle_id="cycle-1",
        window_start=start,
        window_end=end,
        sample_size=2,
        sample_seed="fixed",
        chronicle_path=chronicle,
        ratings_path=ratings,
        programme_id="prog-1",
        now=end,
    )

    assert report.verdict == "hold"
    assert report.direct_rating_count == 5
    assert report.window_rating_count == 5
    assert report.rubric_mean_1_5 == 4.5
    assert report.grounding_coverage == 1.0
    assert report.novelty_score_mean == 0.7
    by_id = {sample.event_id: sample for sample in report.samples}
    assert by_id["ev-1"].direct_rating_count == 5
    assert by_id["ev-1"].mean_rating_by_axis["grounded"] == 4.0


def test_cycle_report_treats_missing_grounding_as_false(tmp_path: Path) -> None:
    chronicle = tmp_path / "events.jsonl"
    start = datetime.fromtimestamp(100.0, UTC)
    end = datetime.fromtimestamp(200.0, UTC)
    _write_events(
        chronicle,
        [
            _event("grounded", ts=120.0, grounding=["source:ok"]),
            _event("ungrounded", ts=130.0, grounding=None),
        ],
    )

    report = build_ss2_cycle_report(
        cycle_id="cycle-grounding",
        window_start=start,
        window_end=end,
        sample_size=2,
        chronicle_path=chronicle,
        ratings_path=tmp_path / "missing-ratings.jsonl",
        now=end,
    )

    assert report.verdict == "insufficient"
    assert report.grounded_event_count == 1
    assert report.groundable_event_count == 2
    assert report.grounding_coverage == 0.5
    assert not report.grounding_gate_passed


def test_cycle_report_can_omit_raw_narrative_text(tmp_path: Path) -> None:
    chronicle = tmp_path / "events.jsonl"
    start = datetime.fromtimestamp(100.0, UTC)
    end = datetime.fromtimestamp(200.0, UTC)
    _write_events(chronicle, [_event("ev-1", ts=120.0)])

    report = build_ss2_cycle_report(
        cycle_id="cycle-private",
        window_start=start,
        window_end=end,
        sample_size=1,
        chronicle_path=chronicle,
        ratings_path=tmp_path / "missing-ratings.jsonl",
        include_text=False,
        now=end,
    )

    assert report.samples[0].narrative_text is None
    assert report.privacy_label == "private"
    assert "no_public_authorization" in report.negative_constraints
