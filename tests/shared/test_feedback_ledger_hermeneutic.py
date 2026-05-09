"""Tests for hermeneutic delta integration in the feedback ledger."""

from __future__ import annotations

from datetime import UTC, datetime

from shared.content_programme_feedback_ledger import (
    HermeneuticDeltaRecord,
    hermeneutic_delta_records_from_deltas,
)
from shared.hermeneutic_spiral import HermeneuticDelta


def test_hermeneutic_delta_record_is_frozen() -> None:
    record = HermeneuticDeltaRecord(
        delta_id="d1",
        source_ref="vault:zuboff",
        delta_kind="new_consequence",
        consequence_kind="ranking_or_order_changed",
        changed_dimensions=("claim", "ranking"),
        prior_encounter_count=0,
        summary="First encounter",
    )
    assert record.delta_id == "d1"
    assert record.model_config["frozen"] is True


def test_conversion_from_hermeneutic_delta_objects() -> None:
    deltas = [
        HermeneuticDelta(
            delta_id="d1",
            programme_id="prog-1",
            role="tier_list",
            topic="test",
            cycle_timestamp=datetime.now(tz=UTC),
            delta_kind="new_consequence",
            source_ref="vault:zuboff",
            consequence_kind="ranking_or_order_changed",
            changed_dimensions=("claim", "ranking"),
            prior_encounter_ids=(),
            summary="First encounter: vault:zuboff introduced ranking_or_order_changed",
        ),
        HermeneuticDelta(
            delta_id="d2",
            programme_id="prog-1",
            role="tier_list",
            topic="test",
            cycle_timestamp=datetime.now(tz=UTC),
            delta_kind="reinforced_consequence",
            source_ref="vault:nancy",
            consequence_kind="claim_shape_changed",
            changed_dimensions=("claim",),
            prior_encounter_ids=("prior-1", "prior-2"),
            summary="Reinforced: vault:nancy again caused claim_shape_changed",
        ),
    ]

    records = hermeneutic_delta_records_from_deltas(deltas)

    assert len(records) == 2
    assert isinstance(records, tuple)
    assert records[0].delta_id == "d1"
    assert records[0].delta_kind == "new_consequence"
    assert records[0].prior_encounter_count == 0
    assert records[1].delta_id == "d2"
    assert records[1].prior_encounter_count == 2
    assert records[1].changed_dimensions == ("claim",)


def test_empty_deltas_produces_empty_tuple() -> None:
    records = hermeneutic_delta_records_from_deltas([])
    assert records == ()
