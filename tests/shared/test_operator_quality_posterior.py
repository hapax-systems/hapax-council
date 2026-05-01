from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.operator_quality_feedback import (
    QUALITY_FEEDBACK_PATH_ENV,
    OperatorQualityRatingEvent,
    append_operator_quality_rating,
    build_operator_quality_rating,
)
from shared.operator_quality_posterior import (
    DEFAULT_HALF_LIFE_DAYS,
    DEFAULT_MIN_SAMPLES,
    GROUPABLE_FIELDS,
    NEGATIVE_CONSTRAINTS,
    ConditionKey,
    OperatorQualityPosteriorReadModel,
    UncertaintyReason,
    aggregate_operator_quality_posterior,
)

NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


def _event(
    *,
    rating: int,
    occurred_at: datetime,
    rating_axis: str = "overall",
    programme_id: str | None = "programme-a",
    condition_id: str | None = "condition-a",
    source_surface: str = "cli",
    run_id: str | None = None,
    emission_ref: str | None = None,
    evidence_refs: tuple[str, ...] = (),
    note: str | None = None,
    event_id: str | None = None,
) -> OperatorQualityRatingEvent:
    return build_operator_quality_rating(
        rating=rating,
        rating_axis=rating_axis,
        source_surface=source_surface,
        occurred_at=occurred_at,
        event_id=event_id,
        programme_id=programme_id,
        condition_id=condition_id,
        run_id=run_id,
        emission_ref=emission_ref,
        evidence_refs=evidence_refs,
        note=note,
    )


def test_empty_input_returns_no_observations_marker() -> None:
    result = aggregate_operator_quality_posterior([], now=NOW)

    assert result.total_events == 0
    assert result.rows == ()
    assert result.contradictions == ()
    assert len(result.insufficient_evidence) == 1
    marker = result.insufficient_evidence[0]
    assert marker.uncertainty_reason is UncertaintyReason.NO_OBSERVATIONS
    assert marker.sample_count == 0
    assert marker.last_seen_at is None
    assert marker.mode_ceiling == "private"


def test_sparse_input_returns_low_support_row() -> None:
    events = [_event(rating=4, occurred_at=NOW - timedelta(days=1))]

    result = aggregate_operator_quality_posterior(events, now=NOW, min_samples=DEFAULT_MIN_SAMPLES)

    assert result.total_events == 1
    assert result.rows == ()
    assert len(result.insufficient_evidence) == 1
    row = result.insufficient_evidence[0]
    assert row.uncertainty_reason is UncertaintyReason.LOW_SUPPORT
    assert row.sample_count == 1
    assert row.last_seen_at == NOW - timedelta(days=1)
    assert row.key.programme_id == "programme-a"
    assert row.key.condition_id == "condition-a"
    assert row.key.rating_axis == "overall"


def test_conflicting_input_lowers_confidence_and_emits_contradiction_row() -> None:
    base = NOW - timedelta(days=2)
    events = [
        _event(rating=5, occurred_at=base, event_id="oqr-h1"),
        _event(rating=5, occurred_at=base + timedelta(hours=1), event_id="oqr-h2"),
        _event(rating=5, occurred_at=base + timedelta(hours=2), event_id="oqr-h3"),
        _event(rating=1, occurred_at=base + timedelta(hours=3), event_id="oqr-l1"),
        _event(rating=1, occurred_at=base + timedelta(hours=4), event_id="oqr-l2"),
    ]

    converging = [_event(rating=5, occurred_at=base + timedelta(hours=h)) for h in range(5)]
    converging_result = aggregate_operator_quality_posterior(converging, now=NOW)
    converging_confidence = converging_result.rows[0].confidence

    result = aggregate_operator_quality_posterior(events, now=NOW)

    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.sample_count == 5
    assert row.support_count == 3
    assert row.correction_count == 2
    assert row.contradiction_rate == pytest.approx(2 / 5)
    assert row.uncertainty_reason is UncertaintyReason.CONFLICTING_EVIDENCE
    assert row.confidence < converging_confidence
    assert 0.0 <= row.aggregate_score <= 1.0
    assert 1.0 <= row.aggregate_score_1_5 <= 5.0

    assert len(result.contradictions) == 1
    contradiction = result.contradictions[0]
    assert contradiction.low_count == 2
    assert contradiction.high_count == 3
    assert contradiction.later_camp == "low"
    assert contradiction.earliest_high_at < contradiction.earliest_low_at


def test_stale_input_flags_stale_evidence() -> None:
    far_past = NOW - timedelta(days=120)
    events = [_event(rating=4, occurred_at=far_past + timedelta(days=i)) for i in range(3)]

    result = aggregate_operator_quality_posterior(
        events,
        now=NOW,
        half_life_days=DEFAULT_HALF_LIFE_DAYS,
        stale_threshold_days=30.0,
    )

    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.uncertainty_reason is UncertaintyReason.STALE_EVIDENCE
    assert row.days_since_last > 30.0
    assert row.effective_sample_size < row.sample_count


def test_high_confidence_input_has_no_uncertainty_reason() -> None:
    events = [
        _event(rating=5, occurred_at=NOW - timedelta(minutes=h), event_id=f"oqr-{h}")
        for h in range(12)
    ]

    result = aggregate_operator_quality_posterior(events, now=NOW)

    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.uncertainty_reason is None
    assert row.aggregate_score > 0.9
    assert row.aggregate_score_1_5 > 4.6
    assert row.confidence > 0.7
    assert row.contradiction_rate == 0.0
    assert row.correction_count == 0
    assert row.support_count == 12
    assert result.contradictions == ()


def test_aggregate_partitions_by_default_group_by() -> None:
    events = [
        _event(
            rating=5,
            occurred_at=NOW - timedelta(hours=h),
            programme_id="programme-a",
            condition_id="condition-a",
        )
        for h in range(3)
    ] + [
        _event(
            rating=2,
            occurred_at=NOW - timedelta(hours=h),
            programme_id="programme-b",
            condition_id="condition-b",
        )
        for h in range(3)
    ]

    result = aggregate_operator_quality_posterior(events, now=NOW)

    assert len(result.rows) == 2
    by_programme = {row.key.programme_id: row for row in result.rows}
    assert by_programme["programme-a"].aggregate_score > by_programme["programme-b"].aggregate_score
    assert result.group_by == GROUPABLE_FIELDS


def test_custom_group_by_collapses_dimensions() -> None:
    events = [
        _event(
            rating=4,
            occurred_at=NOW - timedelta(hours=h),
            programme_id=f"programme-{h % 2}",
            condition_id=f"condition-{h % 3}",
        )
        for h in range(6)
    ]

    result = aggregate_operator_quality_posterior(events, now=NOW, group_by=("rating_axis",))

    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.key.rating_axis == "overall"
    assert row.key.programme_id is None
    assert row.key.condition_id is None
    assert row.sample_count == 6
    assert result.group_by == ("rating_axis",)


def test_distinct_pointers_counted_without_raw_emission_text() -> None:
    events = [
        _event(
            rating=5,
            occurred_at=NOW - timedelta(hours=h),
            run_id=f"run-{h % 2}",
            emission_ref=f"chronicle:abc-{h}",
            evidence_refs=("sample:20",),
            note=f"private note {h}",
        )
        for h in range(4)
    ]

    result = aggregate_operator_quality_posterior(events, now=NOW)

    row = result.rows[0]
    assert row.distinct_run_ids == 2
    assert row.distinct_emission_refs == 4
    assert row.evidence_ref_count == 4

    payload = result.model_dump_json()
    for h in range(4):
        assert f"private note {h}" not in payload
        assert f"chronicle:abc-{h}" not in payload
    assert "sample:20" not in payload


def test_decay_lowers_old_event_weight_relative_to_recent() -> None:
    fresh_events = [_event(rating=5, occurred_at=NOW - timedelta(hours=h)) for h in range(4)]
    decayed_events = [_event(rating=5, occurred_at=NOW - timedelta(days=42 + i)) for i in range(4)]

    fresh_result = aggregate_operator_quality_posterior(
        fresh_events, now=NOW, half_life_days=14.0, stale_threshold_days=365.0
    )
    decayed_result = aggregate_operator_quality_posterior(
        decayed_events, now=NOW, half_life_days=14.0, stale_threshold_days=365.0
    )

    fresh_row = fresh_result.rows[0]
    decayed_row = decayed_result.rows[0]

    assert decayed_row.effective_sample_size < fresh_row.effective_sample_size
    assert decayed_row.effective_sample_size < 1.0
    assert decayed_row.confidence < fresh_row.confidence


def test_correction_after_support_keeps_history_and_widens_uncertainty() -> None:
    base = NOW - timedelta(days=1)
    earlier_5s = [_event(rating=5, occurred_at=base - timedelta(hours=h)) for h in range(5)]
    later_correction = [_event(rating=1, occurred_at=base + timedelta(hours=h)) for h in range(2)]

    only_supports = aggregate_operator_quality_posterior(earlier_5s, now=NOW)
    with_correction = aggregate_operator_quality_posterior(
        list(earlier_5s) + list(later_correction), now=NOW
    )

    assert only_supports.rows[0].confidence > with_correction.rows[0].confidence
    assert with_correction.rows[0].sample_count == 7
    assert with_correction.rows[0].correction_count == 2
    assert len(with_correction.contradictions) == 1
    assert with_correction.contradictions[0].later_camp == "low"


def test_invalid_group_by_field_raises() -> None:
    with pytest.raises(ValueError, match="non-groupable"):
        aggregate_operator_quality_posterior([], group_by=("not_a_field",), now=NOW)


def test_empty_group_by_raises() -> None:
    with pytest.raises(ValueError, match="at least one"):
        aggregate_operator_quality_posterior([], group_by=(), now=NOW)


def test_invalid_numeric_params_raise() -> None:
    with pytest.raises(ValueError, match="half_life_days"):
        aggregate_operator_quality_posterior([], now=NOW, half_life_days=0.0)
    with pytest.raises(ValueError, match="min_samples"):
        aggregate_operator_quality_posterior([], now=NOW, min_samples=0)
    with pytest.raises(ValueError, match="stale_threshold_days"):
        aggregate_operator_quality_posterior([], now=NOW, stale_threshold_days=0.0)
    with pytest.raises(ValueError, match="contradiction_rate_threshold"):
        aggregate_operator_quality_posterior([], now=NOW, contradiction_rate_threshold=1.5)


def test_naive_now_raises() -> None:
    with pytest.raises(ValueError, match="timezone"):
        aggregate_operator_quality_posterior([], now=datetime(2026, 5, 1, 12, 0))


def test_read_model_is_immutable_and_pins_private_ceilings() -> None:
    result = aggregate_operator_quality_posterior([], now=NOW)

    assert result.mode_ceiling == "private"
    assert result.claim_authority == "provisional"
    assert result.privacy_label == "private"
    assert result.negative_constraints == NEGATIVE_CONSTRAINTS
    with pytest.raises(ValidationError):
        result.mode_ceiling = "public_live"  # type: ignore[misc]


def test_posterior_row_rejects_non_private_ceiling() -> None:
    events = [_event(rating=4, occurred_at=NOW - timedelta(hours=h)) for h in range(3)]
    result = aggregate_operator_quality_posterior(events, now=NOW)
    row = result.rows[0]

    assert row.mode_ceiling == "private"
    assert row.claim_authority == "provisional"
    assert row.privacy_label == "private"
    with pytest.raises(ValidationError):
        row.aggregate_score = 0.5  # type: ignore[misc]


def test_aggregate_score_1_5_is_linear_back_projection() -> None:
    events = [_event(rating=3, occurred_at=NOW - timedelta(hours=h)) for h in range(6)]

    result = aggregate_operator_quality_posterior(events, now=NOW)
    row = result.rows[0]

    assert row.aggregate_score_1_5 == pytest.approx(1.0 + 4.0 * row.aggregate_score)
    assert row.aggregate_score_1_5 == pytest.approx(3.0, abs=0.05)


def test_cells_for_programme_filters_rows() -> None:
    events = [
        _event(rating=5, occurred_at=NOW - timedelta(hours=h), programme_id="programme-a")
        for h in range(3)
    ] + [
        _event(rating=2, occurred_at=NOW - timedelta(hours=h), programme_id="programme-b")
        for h in range(3)
    ]

    result = aggregate_operator_quality_posterior(events, now=NOW)

    a_cells = result.cells_for_programme("programme-a")
    b_cells = result.cells_for_programme("programme-b")

    assert len(a_cells) == 1
    assert len(b_cells) == 1
    assert a_cells[0].key.programme_id == "programme-a"
    assert b_cells[0].key.programme_id == "programme-b"


def test_private_summary_lines_omit_raw_text() -> None:
    events = [
        _event(
            rating=5,
            occurred_at=NOW - timedelta(hours=h),
            note="private operator note do-not-leak",
            emission_ref="chronicle:abc-secret",
            evidence_refs=("sample:secret",),
        )
        for h in range(4)
    ]

    result = aggregate_operator_quality_posterior(events, now=NOW)
    lines = result.private_summary_lines()

    assert lines, "expected at least one summary line"
    for line in lines:
        assert "do-not-leak" not in line
        assert "abc-secret" not in line
        assert "sample:secret" not in line


def test_private_summary_lines_when_only_insufficient() -> None:
    result = aggregate_operator_quality_posterior(
        [_event(rating=4, occurred_at=NOW - timedelta(hours=1))], now=NOW
    )

    lines = result.private_summary_lines()

    assert lines == (
        f"operator-quality posterior: {UncertaintyReason.LOW_SUPPORT.value} (events=1)",
    )


def test_private_summary_lines_when_empty() -> None:
    result = aggregate_operator_quality_posterior([], now=NOW)
    lines = result.private_summary_lines()

    assert lines == (
        f"operator-quality posterior: {UncertaintyReason.NO_OBSERVATIONS.value} (events=0)",
    )


def test_path_argument_reads_from_jsonl_sink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = tmp_path / "ratings.jsonl"
    monkeypatch.setenv(QUALITY_FEEDBACK_PATH_ENV, str(sink))

    for h in range(3):
        append_operator_quality_rating(
            _event(rating=5, occurred_at=NOW - timedelta(hours=h), event_id=f"oqr-jsonl-{h}"),
            path=sink,
        )

    result = aggregate_operator_quality_posterior(path=sink, now=NOW)

    assert result.total_events == 3
    assert len(result.rows) == 1
    assert result.rows[0].support_count == 3


def test_iterating_default_path_when_missing_returns_empty_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = tmp_path / "missing.jsonl"
    monkeypatch.setenv(QUALITY_FEEDBACK_PATH_ENV, str(sink))

    result = aggregate_operator_quality_posterior(now=NOW)

    assert result.total_events == 0
    assert result.insufficient_evidence[0].uncertainty_reason is UncertaintyReason.NO_OBSERVATIONS


def test_malformed_jsonl_lines_are_skipped(tmp_path: Path) -> None:
    sink = tmp_path / "ratings.jsonl"
    valid = _event(rating=5, occurred_at=NOW - timedelta(hours=1), event_id="oqr-valid")
    sink.write_text(
        "\n".join(
            [
                valid.model_dump_json(),
                "this line is not json",
                json.dumps({"event_type": "wrong_type"}),
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = aggregate_operator_quality_posterior(path=sink, now=NOW)

    assert result.total_events == 1


def test_condition_key_is_hashable_and_supports_set_membership() -> None:
    a = ConditionKey(programme_id="p", rating_axis="overall")
    b = ConditionKey(programme_id="p", rating_axis="overall")
    c = ConditionKey(programme_id="p", rating_axis="grounded")

    cells = {a, b, c}
    assert len(cells) == 2
    assert a == b
    assert a != c


def test_groupable_fields_set_is_documented() -> None:
    assert set(GROUPABLE_FIELDS) == {
        "programme_id",
        "condition_id",
        "source_surface",
        "rating_axis",
    }


def test_no_pii_or_secret_default_paths_in_module(tmp_path: Path) -> None:
    """Smoke check: PII guard hook prohibits operator-home path literals; this
    test pins behavior so refactors do not reintroduce one through the read
    model surface.
    """

    sink = tmp_path / "ratings.jsonl"
    append_operator_quality_rating(
        _event(rating=5, occurred_at=NOW - timedelta(hours=1)),
        path=sink,
    )

    result = aggregate_operator_quality_posterior(path=sink, now=NOW)
    payload = result.model_dump_json()

    assert "/home/" not in payload
    assert str(sink) not in payload
    assert isinstance(result, OperatorQualityPosteriorReadModel)
