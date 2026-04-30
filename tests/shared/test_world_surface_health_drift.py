"""Tests for WCS health drift rules over claim-bearing text fixtures."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest

from shared.world_surface_health_drift import (
    REQUIRED_ARTIFACT_KINDS,
    REQUIRED_FINDING_CLASSES,
    WORLD_SURFACE_HEALTH_DRIFT_FIXTURES,
    DriftFindingClass,
    WorldSurfaceHealthDriftFixtureSet,
    build_fixture_drift_report,
    evaluate_claim_fixture,
    load_world_surface_health_drift_fixtures,
)


def _json(path: Path = WORLD_SURFACE_HEALTH_DRIFT_FIXTURES) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def test_fixture_set_covers_artifact_kinds_and_finding_classes() -> None:
    fixture_set = load_world_surface_health_drift_fixtures()

    assert {kind.value for kind in fixture_set.artifact_kinds} == REQUIRED_ARTIFACT_KINDS
    assert {kind.value for kind in fixture_set.finding_classes} == REQUIRED_FINDING_CLASSES
    assert {fixture.artifact_kind.value for fixture in fixture_set.claim_fixtures} >= (
        REQUIRED_ARTIFACT_KINDS
    )


def test_drift_report_is_machine_readable_for_dashboard_api_consumers() -> None:
    report = build_fixture_drift_report()

    assert report.schema_version == 1
    assert report.dashboard_api_contract == {
        "primary_key": "finding_id",
        "classification_field": "classification",
        "blocking_field": "blocks_public_escalation",
        "source_field": "source_path",
    }
    assert report.summary.total_fixtures == 7
    assert report.summary.total_findings == len(report.findings)
    assert report.summary.blocks_public_escalation_count == len(report.findings)
    assert set(report.summary.by_classification) == REQUIRED_FINDING_CLASSES
    for finding in report.findings:
        assert finding.finding_id.startswith(f"{finding.fixture_id}:")
        assert finding.reason_codes
        assert finding.blocks_public_escalation is True


def test_missing_surface_and_missing_evidence_fail_closed() -> None:
    fixture_set = load_world_surface_health_drift_fixtures()
    fixture = next(
        item
        for item in fixture_set.claim_fixtures
        if item.fixture_id == "doc.reverie_lane_live_missing_surface"
    )
    classes = {finding.classification for finding in evaluate_claim_fixture(fixture)}

    assert classes == {
        DriftFindingClass.MISSING,
        DriftFindingClass.UNSUPPORTED,
        DriftFindingClass.FALSE_LIVE,
    }


def test_wrong_route_and_stale_claims_are_classified_separately() -> None:
    report = build_fixture_drift_report()
    by_fixture = {
        finding.fixture_id: finding.classification
        for finding in report.findings
        if finding.classification in {DriftFindingClass.WRONG_ROUTE, DriftFindingClass.STALE}
    }

    assert by_fixture["prompt.desktop_control_wrong_route"] is DriftFindingClass.WRONG_ROUTE
    assert by_fixture["public_copy.archive_replay_false_live"] is DriftFindingClass.STALE
    assert by_fixture["dashboard.audio_safe_stale"] is DriftFindingClass.STALE


def test_false_live_and_false_monetization_block_public_escalation() -> None:
    report = build_fixture_drift_report()
    false_monetization = [
        finding
        for finding in report.findings
        if finding.classification is DriftFindingClass.FALSE_MONETIZATION
    ]
    false_live = [
        finding
        for finding in report.findings
        if finding.classification is DriftFindingClass.FALSE_LIVE
    ]

    assert [finding.fixture_id for finding in false_monetization] == [
        "grant.support_copy_false_monetization"
    ]
    assert false_live
    assert all(finding.blocks_public_escalation for finding in false_live)


def test_planned_or_historical_claims_do_not_create_drift_findings() -> None:
    fixture_set = load_world_surface_health_drift_fixtures()
    planned = next(
        item
        for item in fixture_set.claim_fixtures
        if item.fixture_id == "doc.planned_visual_adapter_not_drift"
    )

    assert evaluate_claim_fixture(planned) == []


def test_sample_sources_cover_recent_task_and_research_notes() -> None:
    fixture_set = load_world_surface_health_drift_fixtures()
    source_paths = {fixture.source_path for fixture in fixture_set.claim_fixtures}

    assert "vault:hapax-cc-tasks/active/ytb-009-production-wire.md" in source_paths
    assert (
        "vault:hapax-research/specs/2026-04-29-world-surface-health-no-false-grounding.md"
        in source_paths
    )


def test_fixture_contract_rejects_unexpected_finding_drift() -> None:
    payload = _json()
    bad = deepcopy(payload)
    fixture = next(
        item
        for item in bad["claim_fixtures"]
        if item["fixture_id"] == "grant.support_copy_false_monetization"
    )
    fixture["monetization_allowed"] = True

    with pytest.raises(ValueError):
        WorldSurfaceHealthDriftFixtureSet.model_validate(bad).validate_contract()
