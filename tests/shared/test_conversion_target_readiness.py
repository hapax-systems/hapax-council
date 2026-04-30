"""Tests for the conversion target readiness threshold matrix."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from shared.conversion_target_readiness import (
    PUBLIC_READINESS_STATES,
    REQUIRED_GATE_DIMENSIONS,
    REQUIRED_TARGET_FAMILIES,
    decide_readiness_state,
    evaluate_failure_fixture,
    load_conversion_target_readiness_matrix,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = REPO_ROOT / "config" / "conversion-target-readiness-threshold-matrix.json"
SCHEMA_PATH = REPO_ROOT / "schemas" / "conversion-target-readiness-threshold-matrix.schema.json"


def test_matrix_fixture_validates_against_json_schema() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    payload = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(payload)


def test_matrix_loads_required_families_states_and_gate_dimensions() -> None:
    matrix = load_conversion_target_readiness_matrix()
    by_family = matrix.by_family_id()

    assert set(by_family) == REQUIRED_TARGET_FAMILIES
    assert matrix.readiness_states == (
        "blocked",
        "private-evidence",
        "dry-run",
        "public-archive",
        "public-live",
        "public-monetizable",
        "refused",
    )

    for target in matrix.target_families:
        assert set(target.gate_requirements) == REQUIRED_GATE_DIMENSIONS
        assert "blocked" in target.allowed_states
        assert "refused" in target.allowed_states


def test_public_and_money_states_require_public_chain_and_monetization_gate() -> None:
    matrix = load_conversion_target_readiness_matrix()

    for target in matrix.target_families:
        for state in set(target.allowed_states) & PUBLIC_READINESS_STATES:
            required = target.required_dimensions_for_state(state)
            assert {
                "wcs",
                "programme",
                "public_event",
                "archive",
                "rights",
                "privacy",
                "provenance",
                "egress",
                "no_hidden_operator_labor",
            } <= required
            if state == "public-monetizable":
                assert "monetization" in required


def test_grants_allow_private_evidence_only_with_operator_attestation() -> None:
    matrix = load_conversion_target_readiness_matrix()
    grants = matrix.by_family_id()["grants_fellowships"]
    private_gates = grants.required_dimensions_for_state("private-evidence")

    allowed = decide_readiness_state(
        matrix,
        "grants_fellowships",
        "private-evidence",
        private_gates,
    )
    missing_attestation = decide_readiness_state(
        matrix,
        "grants_fellowships",
        "private-evidence",
        private_gates - {"operator_attestation"},
    )
    public_live = decide_readiness_state(
        matrix,
        "grants_fellowships",
        "public-live",
        private_gates,
    )

    assert allowed.allowed is True
    assert allowed.effective_state == "private-evidence"
    assert missing_attestation.allowed is False
    assert missing_attestation.effective_state == "blocked"
    assert "operator_attestation" in missing_attestation.missing_gate_dimensions
    assert public_live.allowed is False
    assert public_live.effective_state == "blocked"


def test_failure_fixtures_keep_value_signals_from_upgrading_readiness() -> None:
    matrix = load_conversion_target_readiness_matrix()
    by_fixture = {fixture.fixture_id: fixture for fixture in matrix.failure_fixtures}

    assert set(by_fixture) == {
        "high_money_missing_egress",
        "missing_rights_blocks_youtube",
        "missing_provenance_blocks_dataset",
        "private_only_source_blocks_support",
        "operator_attestation_required_for_fellowship",
    }

    for fixture in matrix.failure_fixtures:
        decision = evaluate_failure_fixture(matrix, fixture)

        assert fixture.high_monetary_value or fixture.input_signals
        assert decision.effective_state == fixture.expected_state
        assert decision.allowed is False
        assert set(fixture.missing_gate_dimensions) & set(decision.missing_gate_dimensions)


def test_public_monetizable_path_fails_closed_without_monetization_or_labor_gate() -> None:
    matrix = load_conversion_target_readiness_matrix()
    target = matrix.by_family_id()["support_prompt"]
    all_required = target.required_dimensions_for_state("public-monetizable")

    ready = decide_readiness_state(
        matrix,
        "support_prompt",
        "public-monetizable",
        all_required,
    )
    missing_monetization = decide_readiness_state(
        matrix,
        "support_prompt",
        "public-monetizable",
        all_required - {"monetization"},
    )
    hidden_labor = decide_readiness_state(
        matrix,
        "support_prompt",
        "public-monetizable",
        all_required - {"no_hidden_operator_labor"},
    )

    assert ready.allowed is True
    assert ready.effective_state == "public-monetizable"
    assert missing_monetization.allowed is False
    assert "monetization" in missing_monetization.missing_gate_dimensions
    assert hidden_labor.allowed is False
    assert "no_hidden_operator_labor" in hidden_labor.missing_gate_dimensions


def test_anti_overclaim_policy_is_deny_wins() -> None:
    matrix = load_conversion_target_readiness_matrix()
    policy = matrix.anti_overclaim_policy

    assert policy.engagement_can_upgrade is False
    assert policy.revenue_potential_can_upgrade is False
    assert policy.trend_can_upgrade is False
    assert policy.operator_desire_can_upgrade is False
    assert policy.selected_or_commanded_is_success is False
    assert policy.refusal_can_validate_refused_claim is False
