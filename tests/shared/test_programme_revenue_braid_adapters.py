"""Tests for programme/revenue braid adapter projections."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
from pydantic import ValidationError

from shared.programme_revenue_braid_adapters import (
    BraidSnapshotRowRef,
    load_programme_revenue_braid_adapter_fixtures,
    project_fixture,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "config" / "programme-revenue-braid-adapters.json"
SCHEMA_PATH = REPO_ROOT / "schemas" / "programme-revenue-braid-adapters.schema.json"


def test_adapter_fixture_validates_against_json_schema() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(payload)


def test_fixture_projections_match_expected_programme_and_conversion_contracts() -> None:
    fixtures = load_programme_revenue_braid_adapter_fixtures()

    for fixture in fixtures.fixtures:
        row = project_fixture(fixture)

        assert row.conversion_readiness.allowed is fixture.expected_allowed
        assert row.conversion_readiness.effective_state == fixture.expected_effective_state
        assert (
            row.programme_feedback.grounding_update_allowed
            is fixture.expected_grounding_update_allowed
        )
        assert (
            row.conversion_readiness.missing_gate_dimensions
            == fixture.expected_missing_gate_dimensions
        )
        assert (
            row.programme_feedback.allowed_posterior_families
            == fixture.expected_allowed_posterior_families
        )
        assert row.programme_feedback.public_truth_claim_allowed is False
        assert row.programme_feedback.audience_revenue_can_upgrade_grounding is False
        assert row.conversion_readiness.adapter_grants_public_authority is False
        assert row.conversion_readiness.adapter_grants_monetization_authority is False


def test_audience_and_revenue_signals_do_not_upgrade_grounding() -> None:
    fixtures = load_programme_revenue_braid_adapter_fixtures()
    fixture = next(
        item
        for item in fixtures.fixtures
        if item.fixture_id == "audience_revenue_cannot_upgrade_grounding"
    )
    row = project_fixture(fixture)

    assert row.programme_feedback.grounding_update_allowed is False
    assert "grounding_quality" not in row.programme_feedback.allowed_posterior_families
    assert "audience_response" in row.programme_feedback.allowed_posterior_families
    assert "revenue_support_response" in row.programme_feedback.allowed_posterior_families
    assert row.conversion_readiness.allowed is False
    assert row.conversion_readiness.effective_state == "blocked"


def test_revenue_potential_cannot_bypass_public_conversion_gates() -> None:
    fixtures = load_programme_revenue_braid_adapter_fixtures()
    fixture = next(
        item
        for item in fixtures.fixtures
        if item.fixture_id == "revenue_potential_missing_public_gates_blocks_youtube"
    )
    row = project_fixture(fixture)

    assert row.snapshot_row.potential.monetary == 0.99
    assert row.conversion_readiness.allowed is False
    assert set(row.conversion_readiness.missing_gate_dimensions) == {
        "egress",
        "no_hidden_operator_labor",
        "privacy",
        "provenance",
        "public_event",
        "rights",
    }
    assert row.conversion_readiness.revenue_potential_can_bypass_gates is False
    assert row.conversion_readiness.public_support_or_release_evidence_refs == ()


def test_private_grant_evidence_remains_distinct_from_public_release_evidence() -> None:
    fixtures = load_programme_revenue_braid_adapter_fixtures()
    fixture = next(
        item
        for item in fixtures.fixtures
        if item.fixture_id == "private_grant_evidence_distinct_from_public_release"
    )
    row = project_fixture(fixture)

    assert row.conversion_readiness.allowed is True
    assert row.conversion_readiness.effective_state == "private-evidence"
    assert row.conversion_readiness.evidence_scope == "private_grant_application"
    assert row.conversion_readiness.private_grant_application_evidence_refs
    assert row.conversion_readiness.public_support_or_release_evidence_refs == ()


def test_private_ceiling_rejects_public_claim_text() -> None:
    fixtures = load_programme_revenue_braid_adapter_fixtures()
    fixture = fixtures.fixtures[0]

    with_public_claim = fixture.snapshot_row.model_copy(update={"max_public_claim": "summary"})
    try:
        BraidSnapshotRowRef.model_validate(with_public_claim.model_dump())
    except ValidationError as exc:
        assert "private braid rows cannot carry public claim text" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("private mode with public claim text should be rejected")
