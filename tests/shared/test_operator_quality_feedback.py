from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.operator_quality_feedback import (
    OperatorQualityRatingEvent,
    append_operator_quality_rating,
    append_operator_quality_rating_from_args,
    build_operator_quality_rating,
    iter_operator_quality_ratings,
)


def test_event_shape_pins_private_quality_contract() -> None:
    event = build_operator_quality_rating(
        rating=4,
        rating_axis="listenable",
        source_surface="cli",
        occurred_at=datetime(2026, 5, 1, 0, 30, tzinfo=UTC),
        event_id="oqr-test",
        programme_id="programme-a",
        condition_id="condition-a",
        run_id="run-a",
        emission_ref="chronicle:abc123",
        evidence_refs=("sample:20",),
        note="held attention",
    )

    payload = json.loads(event.model_dump_json())

    assert payload["schema_version"] == 1
    assert payload["event_type"] == "operator_quality_rating"
    assert payload["event_id"] == "oqr-test"
    assert payload["idempotency_key"] == "oqr-test"
    assert payload["rating"] == 4
    assert payload["rating_axis"] == "listenable"
    assert payload["rating_scale"] == "1_5_subjective_quality"
    assert payload["source_surface"] == "cli"
    assert payload["emission_ref"] == "chronicle:abc123"
    assert payload["handoff_refs"] == ["ytb-QM1", "ytb-SS2", "ytb-SS3"]


@pytest.mark.parametrize("rating", [0, 6])
def test_rejects_rating_outside_one_to_five(rating: int) -> None:
    with pytest.raises(ValidationError):
        build_operator_quality_rating(
            rating=rating,
            occurred_at=datetime(2026, 5, 1, tzinfo=UTC),
            event_id="oqr-bad",
        )


def test_append_does_not_truncate_existing_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "ratings.jsonl"
    first = build_operator_quality_rating(
        rating=3,
        occurred_at=datetime(2026, 5, 1, 0, 1, tzinfo=UTC),
        event_id="oqr-first",
    )
    second = build_operator_quality_rating(
        rating=5,
        occurred_at=datetime(2026, 5, 1, 0, 2, tzinfo=UTC),
        event_id="oqr-second",
    )

    append_operator_quality_rating(first, path=path)
    append_operator_quality_rating(second, path=path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event_id"] == "oqr-first"
    assert json.loads(lines[1])["event_id"] == "oqr-second"
    assert [event.event_id for event in iter_operator_quality_ratings(path=path)] == [
        "oqr-first",
        "oqr-second",
    ]


def test_command_args_append_defaults_to_streamdeck_surface(tmp_path: Path) -> None:
    path = tmp_path / "ratings.jsonl"

    event = append_operator_quality_rating_from_args(
        {
            "rating": 4,
            "rating_axis": "overall",
            "event_id": "oqr-command",
            "occurred_at": "2026-05-01T00:03:00Z",
            "evidence_refs": ["control:stream_deck.key.13"],
        },
        path=path,
    )

    assert event.source_surface == "streamdeck"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["event_id"] == "oqr-command"
    assert payload["source_surface"] == "streamdeck"
    assert payload["evidence_refs"] == ["control:stream_deck.key.13"]


def test_model_forbids_public_or_extra_fields() -> None:
    with pytest.raises(ValidationError):
        OperatorQualityRatingEvent.model_validate(
            {
                "schema_version": 1,
                "event_type": "operator_quality_rating",
                "event_id": "oqr-extra",
                "idempotency_key": "oqr-extra",
                "occurred_at": "2026-05-01T00:00:00Z",
                "rating": 4,
                "public_claim_allowed": True,
            }
        )
