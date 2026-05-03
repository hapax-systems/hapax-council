"""Tests for World Capability Surface health envelope fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.world_surface_health import (
    HEALTH_ENVELOPE_REQUIRED_FIELDS,
    HEALTH_RECORD_REQUIRED_FIELDS,
    REQUIRED_CLAIM_BLOCKER_CASES,
    REQUIRED_CLAIMABLE_DIMENSIONS,
    REQUIRED_HEALTH_STATUSES,
    REQUIRED_SURFACE_FAMILIES,
    FixtureCase,
    HealthDimensionState,
    HealthStatus,
    SurfaceFamily,
    WitnessPolicy,
    WorldSurfaceHealthError,
    WorldSurfaceHealthRecord,
    load_world_surface_health_fixtures,
)


def test_world_surface_health_loader_covers_statuses_families_and_fields() -> None:
    fixtures = load_world_surface_health_fixtures()

    assert {status.value for status in fixtures.health_statuses} == REQUIRED_HEALTH_STATUSES
    assert {family.value for family in fixtures.surface_families} >= REQUIRED_SURFACE_FAMILIES
    assert set(fixtures.health_record_required_fields) == set(HEALTH_RECORD_REQUIRED_FIELDS)
    assert set(fixtures.health_envelope_required_fields) == set(HEALTH_ENVELOPE_REQUIRED_FIELDS)
    assert {case.value for case in fixtures.claim_blocker_cases} == REQUIRED_CLAIM_BLOCKER_CASES

    records = fixtures.all_records()
    assert {record.status.value for record in records} == REQUIRED_HEALTH_STATUSES
    assert {record.surface_family.value for record in records} >= REQUIRED_SURFACE_FAMILIES


def test_only_fresh_witnessed_healthy_record_satisfies_claimable_health() -> None:
    fixtures = load_world_surface_health_fixtures()
    claimable = [record for record in fixtures.all_records() if record.satisfies_claimable_health()]

    assert [record.surface_id for record in claimable] == ["audio.broadcast_voice.health"]
    healthy = claimable[0]
    assert healthy.status is HealthStatus.HEALTHY
    assert healthy.witness_policy is WitnessPolicy.WITNESSED
    assert healthy.public_claim_allowed is True
    assert healthy.claimability.public_live is True
    assert healthy.claimability.action is True
    assert healthy.claimability.grounded is True


@pytest.mark.parametrize(
    ("fixture_case", "expected_surface"),
    [
        (FixtureCase.CANDIDATE, "visual.overlay.candidate"),
        (FixtureCase.UNKNOWN, "perception.camera-scene.unknown"),
        (FixtureCase.STALE, "archive.session-replay.stale"),
        (FixtureCase.MISSING, "provider.tool-soundcloud.missing"),
        (FixtureCase.INFERRED, "archive.local-pool.inferred"),
        (FixtureCase.SELECTED_ONLY, "control.selected-scene.selected-only"),
        (FixtureCase.COMMANDED_ONLY, "control.midi-transport.commanded-only"),
        (FixtureCase.WRONG_ROUTE, "control.scene-route.wrong-route"),
        (FixtureCase.LEAK, "audio.private-route.leak"),
        (FixtureCase.UNSUPPORTED_CLAIM, "public-event.unsupported-claim.blocked"),
        (FixtureCase.FALSE_MONETIZATION, "public-event.support.false-monetization"),
    ],
)
def test_false_grounding_fixture_cases_cannot_satisfy_claimable_health(
    fixture_case: FixtureCase,
    expected_surface: str,
) -> None:
    fixtures = load_world_surface_health_fixtures()
    rows = fixtures.rows_for_fixture_case(fixture_case)

    assert [row.surface_id for row in rows] == [expected_surface]
    assert rows[0].satisfies_claimable_health() is False
    assert rows[0].public_claim_allowed is False
    assert rows[0].claimable_health is False
    assert rows[0].monetization_allowed is False
    assert f"fixture_case:{fixture_case.value}" in rows[0].claimability_blockers()


def test_status_fixtures_are_non_permissive_except_healthy() -> None:
    fixtures = load_world_surface_health_fixtures()

    by_status = {fixture.status: fixture for fixture in fixtures.status_fixtures}
    assert by_status[HealthStatus.HEALTHY].claimable_health_allowed is True
    for status in HealthStatus:
        if status is HealthStatus.HEALTHY:
            continue
        assert by_status[status].claimable_health_allowed is False
        assert by_status[status].public_live_allowed_without_witness is False


@pytest.mark.parametrize(
    "surface_id",
    [
        "visual.overlay.candidate",
        "perception.camera-scene.unknown",
        "archive.session-replay.stale",
        "provider.tool-soundcloud.missing",
        "archive.local-pool.inferred",
        "control.selected-scene.selected-only",
        "control.midi-transport.commanded-only",
        "control.scene-route.wrong-route",
        "audio.private-route.leak",
        "public-event.unsupported-claim.blocked",
        "public-event.support.false-monetization",
    ],
)
def test_mutated_false_grounding_rows_raise_explicit_errors(surface_id: str) -> None:
    fixtures = load_world_surface_health_fixtures()
    payload = fixtures.require_surface(surface_id).model_dump(mode="json")
    payload["claimable_health"] = True
    payload["public_claim_allowed"] = True
    payload["claimability"]["public_live"] = True
    payload["claimability"]["action"] = True
    payload["claimability"]["grounded"] = True

    with pytest.raises(ValueError, match="claimable_health is true but blockers remain"):
        WorldSurfaceHealthRecord.model_validate(payload)


def test_envelope_summary_mismatch_fails_closed(tmp_path: Path) -> None:
    fixtures = load_world_surface_health_fixtures()
    payload = fixtures.model_dump(mode="json")
    payload["envelopes"][0]["summary"]["claimable_health_count"] = 99

    path = tmp_path / "bad-world-surface-health-fixtures.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(WorldSurfaceHealthError, match="summary does not match records"):
        load_world_surface_health_fixtures(path)


def test_positive_public_live_action_grounded_states_require_relevant_witness_evidence() -> None:
    fixtures = load_world_surface_health_fixtures()
    claimable = [record for record in fixtures.all_records() if record.satisfies_claimable_health()]

    assert [record.surface_id for record in claimable] == ["audio.broadcast_voice.health"]
    for record in claimable:
        assert record.witness_refs
        assert record.grounding_gate_refs
        assert record.public_event_refs

        dimensions = {
            dimension.dimension.value: dimension for dimension in record.health_dimensions
        }
        for dimension_id in REQUIRED_CLAIMABLE_DIMENSIONS:
            dimension = dimensions[dimension_id]
            assert dimension.required_for_claimable is True
            assert dimension.state is HealthDimensionState.PASS
            assert dimension.evidence_refs


def test_runner_scheduler_director_and_public_adapters_share_fixture_vocabulary() -> None:
    fixtures = load_world_surface_health_fixtures()
    expected_consumers = {
        "consumer:runner-public-mode",
        "consumer:content-scheduler",
        "consumer:director-read-model",
        "consumer:public-adapter",
    }

    shared_cases = {
        FixtureCase.WRONG_ROUTE,
        FixtureCase.LEAK,
        FixtureCase.UNSUPPORTED_CLAIM,
        FixtureCase.FALSE_MONETIZATION,
    }
    assert shared_cases <= set(fixtures.claim_blocker_cases)
    for fixture_case in shared_cases:
        rows = fixtures.rows_for_fixture_case(fixture_case)
        assert rows
        assert expected_consumers <= set(rows[0].consumer_refs)


def test_refusal_or_correction_success_does_not_validate_refused_unsafe_claim() -> None:
    fixtures = load_world_surface_health_fixtures()
    correction = fixtures.require_surface("refusal.public-claim-correction.blocked")
    unsupported = fixtures.require_surface("public-event.unsupported-claim.blocked")

    assert correction.surface_family is SurfaceFamily.REFUSAL_CORRECTION
    assert unsupported.fixture_case is FixtureCase.UNSUPPORTED_CLAIM
    assert unsupported.outcome_envelope_refs == [
        "outcome-envelope:public-event.unsupported-claim:refused"
    ]
    for record in (correction, unsupported):
        assert record.fallback.mode.value == "correction_required"
        assert record.public_claim_allowed is False
        assert record.claimability.grounded is False
        assert record.satisfies_claimable_health() is False


def test_downstream_adapters_can_import_status_and_surface_vocabulary() -> None:
    assert HealthStatus.UNKNOWN.value == "unknown"
    assert HealthStatus.CANDIDATE.value == "candidate"
    assert SurfaceFamily.PROVIDER_TOOL.value == "provider_tool"
    assert SurfaceFamily.REFUSAL_CORRECTION.value == "refusal_correction"
    assert WitnessPolicy.SELECTED_ONLY.value == "selected_only"
    assert FixtureCase.WRONG_ROUTE.value == "wrong_route"
    assert FixtureCase.LEAK.value == "leak"
    assert FixtureCase.UNSUPPORTED_CLAIM.value == "unsupported_claim"
    assert FixtureCase.FALSE_MONETIZATION.value == "false_monetization"
