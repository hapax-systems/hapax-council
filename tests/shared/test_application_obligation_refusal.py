"""Tests for the application obligation refusal gate."""

from __future__ import annotations

import json
from pathlib import Path

from shared.application_obligation_refusal import (
    OBLIGATION_POLICIES,
    ApplicationObligation,
    ApplicationOpportunity,
    evaluate_application_obligation,
    load_application_obligation_fixtures,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "config" / "application-obligation-refusal-fixtures.json"


def test_fixture_packet_is_valid_json_and_loads() -> None:
    json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    fixture_set = load_application_obligation_fixtures()

    assert fixture_set.policy_id == "application_obligation_refusal_gate"
    assert len(fixture_set.obligation_policies) == 9
    assert len(fixture_set.fixtures) >= 7
    assert {policy.class_id for policy in fixture_set.obligation_policies} == set(
        OBLIGATION_POLICIES
    )


def test_all_required_obligation_classes_have_dispositions() -> None:
    assert set(OBLIGATION_POLICIES) == {
        "legal_attestation",
        "bootstrap_setup",
        "reporting",
        "public_demo",
        "custom_deliverable",
        "private_data_exposure",
        "institution_requirement",
        "community_client_service",
        "recurring_manual_labor",
    }

    assert OBLIGATION_POLICIES["legal_attestation"].disposition == "allowed"
    assert OBLIGATION_POLICIES["bootstrap_setup"].disposition == "allowed"
    assert OBLIGATION_POLICIES["public_demo"].disposition == "guarded"
    assert OBLIGATION_POLICIES["institution_requirement"].disposition == "guarded"
    assert OBLIGATION_POLICIES["custom_deliverable"].disposition == "refused"
    assert OBLIGATION_POLICIES["private_data_exposure"].disposition == "refused"
    assert OBLIGATION_POLICIES["community_client_service"].disposition == "refused"
    assert OBLIGATION_POLICIES["recurring_manual_labor"].disposition == "refused"


def test_fixture_decisions_match_expected_contract() -> None:
    fixture_set = load_application_obligation_fixtures()

    for fixture in fixture_set.fixtures:
        decision = evaluate_application_obligation(fixture.opportunity)

        assert decision.decision == fixture.expected_decision, fixture.fixture_id
        assert set(fixture.expected_refusal_reasons) <= set(decision.refusal_reasons)
        assert set(fixture.expected_operator_actions) <= set(decision.operator_actions)


def test_openai_style_attestation_and_bootstrap_are_not_recurring_labor() -> None:
    fixture = next(
        fixture
        for fixture in load_application_obligation_fixtures().fixtures
        if fixture.fixture_id == "openai_style_attestation_allowed"
    )

    decision = evaluate_application_obligation(fixture.opportunity)

    assert decision.decision == "allowed"
    assert decision.refusal_reasons == ()
    assert set(decision.operator_actions) == {
        "explicit_legal_attestation",
        "one_time_bootstrap",
    }


def test_residency_public_demo_is_guarded_but_not_refused() -> None:
    fixture = next(
        fixture
        for fixture in load_application_obligation_fixtures().fixtures
        if fixture.fixture_id == "residency_demo_guarded_not_custom_performance"
    )

    decision = evaluate_application_obligation(fixture.opportunity)

    assert decision.decision == "guarded"
    assert decision.refusal_reasons == ()
    assert "guarded_public_demo_review" in decision.operator_actions


def test_compute_credit_bootstrap_is_allowed() -> None:
    fixture = next(
        fixture
        for fixture in load_application_obligation_fixtures().fixtures
        if fixture.fixture_id == "compute_credit_bootstrap_allowed"
    )

    decision = evaluate_application_obligation(fixture.opportunity)

    assert decision.decision == "allowed"
    assert decision.operator_actions == ("one_time_bootstrap",)


def test_fake_affiliation_refuses_even_when_institution_requirement_is_guarded() -> None:
    opportunity = ApplicationOpportunity(
        opportunity_id="institutional-program",
        title="Institutional-only program",
        requires_fake_affiliation=True,
        obligations=(
            ApplicationObligation(
                class_id="institution_requirement",
                recurrence="one_time",
                automation_fit="operator_attestation",
                summary="Institutional affiliation claim required.",
            ),
        ),
    )

    decision = evaluate_application_obligation(opportunity)

    assert decision.decision == "refused"
    assert "fake_affiliation" in decision.refusal_reasons
    assert "institution_requirement_review" in decision.operator_actions


def test_recurring_manual_reporting_refuses() -> None:
    opportunity = ApplicationOpportunity(
        opportunity_id="monthly-reporting",
        title="Monthly reporting grant",
        obligations=(
            ApplicationObligation(
                class_id="reporting",
                recurrence="recurring",
                automation_fit="manual",
                summary="Manual monthly reports required.",
            ),
        ),
    )

    decision = evaluate_application_obligation(opportunity)

    assert decision.decision == "refused"
    assert decision.refusal_reasons == ("recurring_reports",)


def test_private_data_custom_performance_and_customer_service_refuse() -> None:
    fixture_set = load_application_obligation_fixtures()
    by_id = {fixture.fixture_id: fixture for fixture in fixture_set.fixtures}

    for fixture_id, expected_reason in {
        "private_data_exposure_refused": "private_data_exposure",
        "custom_performance_refused": "custom_performance",
        "customer_service_obligation_refused": "customer_service_obligation",
    }.items():
        decision = evaluate_application_obligation(by_id[fixture_id].opportunity)

        assert decision.decision == "refused"
        assert expected_reason in decision.refusal_reasons


def test_manual_opportunity_chasing_refuses_otherwise_bootstrap_shape() -> None:
    fixture = next(
        fixture
        for fixture in load_application_obligation_fixtures().fixtures
        if fixture.fixture_id == "manual_opportunity_chasing_refused"
    )

    decision = evaluate_application_obligation(fixture.opportunity)

    assert decision.decision == "refused"
    assert "manual_opportunity_chasing" in decision.refusal_reasons
    assert "one_time_bootstrap" in decision.operator_actions
