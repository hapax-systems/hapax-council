"""Tests for temporal/perceptual WCS health projection."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from shared.world_surface_health import (
    AuthorityCeiling,
    HealthDimensionId,
    HealthDimensionState,
    HealthStatus,
    SurfaceFamily,
)
from shared.world_surface_temporal_perceptual_health import (
    FAIL_CLOSED_POLICY,
    REQUIRED_OBSERVATION_CATEGORIES,
    TEMPORAL_FALSE_GROUNDING_METRIC,
    TEMPORAL_PERCEPTUAL_HEALTH_FIXTURES,
    FalseGroundingRiskCause,
    ObservationCategory,
    TemporalBand,
    TemporalPerceptualHealthError,
    TemporalPerceptualHealthFixtureSet,
    load_temporal_perceptual_health_fixtures,
    project_temporal_false_grounding_risk_metrics,
    project_temporal_perceptual_health_envelope,
    project_temporal_perceptual_health_records,
)


def _json(path: Path = TEMPORAL_PERCEPTUAL_HEALTH_FIXTURES) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _dimension_state(record, dimension_id: HealthDimensionId) -> HealthDimensionState:
    dimensions = {dimension.dimension: dimension for dimension in record.health_dimensions}
    return dimensions[dimension_id].state


def test_fixture_rows_cover_required_categories_and_temporal_bands() -> None:
    fixture_set = load_temporal_perceptual_health_fixtures()
    rows_by_id = {row.row_id: row for row in fixture_set.rows}

    assert {
        category.value for category in fixture_set.required_observation_categories
    } == REQUIRED_OBSERVATION_CATEGORIES
    assert rows_by_id["temporal.producer.unknown"].status is HealthStatus.UNKNOWN
    assert {row.category for row in fixture_set.rows} >= set(ObservationCategory)
    assert {
        row.temporal_band
        for row in fixture_set.rows
        if row.category is ObservationCategory.TEMPORAL_BAND
    } >= {
        TemporalBand.RETENTION,
        TemporalBand.IMPRESSION,
        TemporalBand.PROTENTION,
        TemporalBand.SURPRISE,
    }
    assert fixture_set.fail_closed_policy == FAIL_CLOSED_POLICY


def test_projected_rows_are_bounded_perception_observation_wcs_records() -> None:
    records = project_temporal_perceptual_health_records()

    assert records
    for record in records:
        assert record.surface_family is SurfaceFamily.PERCEPTION_OBSERVATION
        assert record.public_claim_allowed is False
        assert record.monetization_allowed is False
        assert record.claimable_health is False
        assert record.claimability.public_live is False
        assert record.claimability.action is False
        assert record.claimability.grounded is False
        assert record.satisfies_claimable_health() is False
        assert "temporal_perceptual_health_does_not_grant_public_claim_authority" in (
            record.warnings
        )
        assert any(ref.startswith("temporal_band:") for ref in record.capability_refs)


def test_rows_expose_freshness_authority_evidence_band_and_blocker_reason() -> None:
    fixture_set = load_temporal_perceptual_health_fixtures()

    for row in fixture_set.rows:
        record = row.to_world_surface_health_record()

        assert record.freshness == row.freshness
        assert record.authority_ceiling is row.authority_ceiling
        assert record.evidence_envelope_refs == row.evidence_envelope_refs
        assert f"temporal_band:{row.temporal_band.value}" in record.capability_refs
        if row.false_grounding_risk_causes:
            assert row.blocker_reason
            assert row.blocker_reason in record.blocking_reasons
            for cause in row.false_grounding_risk_causes:
                assert f"false_grounding_risk:{cause.value}" in record.blocking_reasons


@pytest.mark.parametrize(
    "row_id",
    [
        "temporal.retention.camera_scene.stale",
        "temporal.producer.missing",
        "temporal.producer.unknown",
        "perception.state.unknown",
    ],
)
def test_stale_missing_unknown_rows_cannot_satisfy_public_live_or_current_claims(
    row_id: str,
) -> None:
    records = {
        record.surface_id.removesuffix(".health"): record
        for record in project_temporal_perceptual_health_records()
    }
    record = records[row_id]

    assert record.status in {HealthStatus.STALE, HealthStatus.MISSING, HealthStatus.UNKNOWN}
    assert record.public_claim_allowed is False
    assert record.claimability.public_live is False
    assert record.claimability.action is False
    assert record.claimability.grounded is False
    assert record.satisfies_claimable_health() is False
    assert any(blocker.startswith("freshness:") for blocker in record.claimability_blockers())


def test_blocked_and_degraded_surfaces_remain_visible_with_reasons() -> None:
    records = {
        record.surface_id.removesuffix(".health"): record
        for record in project_temporal_perceptual_health_records()
    }

    for row_id in (
        "temporal.protention.audio_readiness.expected",
        "temporal.surprise.camera_scene.mismatch",
        "perceptual_field.current_track.spanless",
        "autonomous_narration.context.ungated",
        "impingement.evidence.inferred_only",
    ):
        record = records[row_id]
        assert record.status in {HealthStatus.DEGRADED, HealthStatus.BLOCKED}
        assert record.blocking_reasons


def test_perceptual_field_false_grounding_risks_block_grounding_dimensions() -> None:
    records = {
        record.surface_id.removesuffix(".health"): record
        for record in project_temporal_perceptual_health_records()
    }
    spanless = records["perceptual_field.current_track.spanless"]
    inferred = records["perceptual_field.camera.classifications.inferred"]

    assert _dimension_state(spanless, HealthDimensionId.WORLD_WITNESS) is (
        HealthDimensionState.MISSING
    )
    assert _dimension_state(spanless, HealthDimensionId.GROUNDING_GATE) is (
        HealthDimensionState.BLOCKED
    )
    assert _dimension_state(inferred, HealthDimensionId.WORLD_WITNESS) is (
        HealthDimensionState.BLOCKED
    )
    assert spanless.authority_ceiling is AuthorityCeiling.NO_CLAIM
    assert inferred.authority_ceiling is AuthorityCeiling.NO_CLAIM


@pytest.mark.parametrize(
    ("cause", "row_id"),
    [
        (
            FalseGroundingRiskCause.STALE_TEMPORAL_XML,
            "temporal.xml.camera_scene.stale",
        ),
        (
            FalseGroundingRiskCause.FRESH_TEMPORAL_XML_WITHOUT_EVIDENCE_REFS,
            "temporal.xml.broadcast_health.fresh_without_evidence_refs",
        ),
        (
            FalseGroundingRiskCause.STALE_PERCEPTUAL_FIELD,
            "perceptual_field.camera.frame.stale",
        ),
        (
            FalseGroundingRiskCause.EMPTY_REAL_PROVENANCE,
            "perceptual_field.real_provenance.empty",
        ),
        (
            FalseGroundingRiskCause.SYNTHETIC_ONLY_PROVENANCE,
            "perceptual_field.provenance.synthetic_only",
        ),
        (
            FalseGroundingRiskCause.PROTENTION_AS_FACT,
            "temporal.protention.audio_readiness.expected",
        ),
        (
            FalseGroundingRiskCause.CONTRADICTORY_PERCEPTION_TEMPORAL_EPOCHS,
            "temporal.perception_epoch.contradictory",
        ),
    ],
)
def test_required_temporal_perceptual_negative_fixtures_block_public_success(
    cause: FalseGroundingRiskCause,
    row_id: str,
) -> None:
    fixture_set = load_temporal_perceptual_health_fixtures()
    row = next(item for item in fixture_set.rows if item.row_id == row_id)
    record = row.to_world_surface_health_record()

    assert cause in row.false_grounding_risk_causes
    assert f"false_grounding_risk:{cause.value}" in record.blocking_reasons
    assert record.public_claim_allowed is False
    assert record.claimability.public_live is False
    assert record.claimability.action is False
    assert record.claimability.grounded is False
    assert record.satisfies_claimable_health() is False


def test_false_grounding_metrics_count_temporal_causes_by_cause() -> None:
    counts = project_temporal_false_grounding_risk_metrics()

    assert counts[FalseGroundingRiskCause.STALE_TEMPORAL_BAND.value] == 1
    assert counts[FalseGroundingRiskCause.MISSING_TEMPORAL_BAND.value] == 1
    assert counts[FalseGroundingRiskCause.UNKNOWN_TEMPORAL_BAND.value] == 1
    assert counts[FalseGroundingRiskCause.UNKNOWN_PERCEPTION_STATE.value] == 1
    assert counts[FalseGroundingRiskCause.INFERRED_PERCEPTUAL_DATA.value] == 1
    assert counts[FalseGroundingRiskCause.SPANLESS_PERCEPTUAL_DATA.value] == 1
    assert counts[FalseGroundingRiskCause.PROTENTION_AS_CURRENT.value] == 1
    assert counts[FalseGroundingRiskCause.PROTENTION_AS_FACT.value] == 1
    assert counts[FalseGroundingRiskCause.STALE_TEMPORAL_XML.value] == 1
    assert counts[FalseGroundingRiskCause.FRESH_TEMPORAL_XML_WITHOUT_EVIDENCE_REFS.value] == 1
    assert counts[FalseGroundingRiskCause.STALE_PERCEPTUAL_FIELD.value] == 1
    assert counts[FalseGroundingRiskCause.EMPTY_REAL_PROVENANCE.value] == 1
    assert counts[FalseGroundingRiskCause.SYNTHETIC_ONLY_PROVENANCE.value] == 1
    assert counts[FalseGroundingRiskCause.CONTRADICTORY_PERCEPTION_TEMPORAL_EPOCHS.value] == 1
    assert counts[FalseGroundingRiskCause.IMPINGEMENT_WITHOUT_WITNESS.value] == 1


def test_temporal_perceptual_envelope_exposes_metric_refs_and_counts() -> None:
    envelope = project_temporal_perceptual_health_envelope()

    assert envelope.public_live_allowed is False
    assert envelope.public_archive_allowed is False
    assert envelope.public_monetization_allowed is False
    assert envelope.false_grounding_risk_count >= 1
    assert f"metrics:{TEMPORAL_FALSE_GROUNDING_METRIC}" in envelope.metrics_refs
    assert envelope.blocked_surface_count >= 1
    assert envelope.stale_surface_count >= 1
    assert envelope.unknown_surface_count >= 1


def test_mutated_stale_row_with_fresh_freshness_raises() -> None:
    payload = _json()
    bad = deepcopy(payload)
    row = next(
        item for item in bad["rows"] if item["row_id"] == "temporal.retention.camera_scene.stale"
    )
    row["freshness"]["state"] = "fresh"
    row["freshness"]["observed_age_s"] = 1

    with pytest.raises(ValidationError):
        TemporalPerceptualHealthFixtureSet.model_validate(bad)


def test_false_grounding_risk_without_blocker_reason_raises() -> None:
    payload = _json()
    bad = deepcopy(payload)
    row = next(
        item for item in bad["rows"] if item["row_id"] == "perceptual_field.current_track.spanless"
    )
    row["blocker_reason"] = None

    with pytest.raises(ValidationError):
        TemporalPerceptualHealthFixtureSet.model_validate(bad)


def test_missing_temporal_evidence_ref_fails_closed(tmp_path: Path) -> None:
    payload = _json()
    bad = deepcopy(payload)
    row = next(
        item
        for item in bad["rows"]
        if item["row_id"] == "temporal.impression.broadcast_health.fresh"
    )
    row["evidence_envelope_refs"] = ["temporal-evidence:not-real"]

    path = tmp_path / "bad-temporal-perceptual-health.json"
    path.write_text(json.dumps(bad), encoding="utf-8")

    with pytest.raises(TemporalPerceptualHealthError, match="missing temporal evidence"):
        load_temporal_perceptual_health_fixtures(path)


def test_missing_grounding_key_ref_fails_closed(tmp_path: Path) -> None:
    payload = _json()
    bad = deepcopy(payload)
    row = next(
        item for item in bad["rows"] if item["row_id"] == "perceptual_field.registry.available"
    )
    row["grounding_key_paths"] = ["not.a.real.key"]

    path = tmp_path / "bad-temporal-perceptual-health.json"
    path.write_text(json.dumps(bad), encoding="utf-8")

    with pytest.raises(TemporalPerceptualHealthError, match="missing grounding key"):
        load_temporal_perceptual_health_fixtures(path)
