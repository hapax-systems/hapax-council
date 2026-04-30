"""Regression pins for the content programme feedback ledger contract."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = (
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-04-29-content-programme-feedback-ledger-design.md"
)
SCHEMA = REPO_ROOT / "schemas" / "content-programme-feedback-ledger.schema.json"
LEDGER = REPO_ROOT / "config" / "content-programme-feedback-ledger.json"

EXPECTED_STATES = {
    "selected",
    "blocked",
    "dry_run",
    "public_run",
    "completed",
    "aborted",
    "refused",
    "corrected",
    "private_only",
    "conversion_held",
}
EXPECTED_POSTERIOR_FAMILIES = {
    "grounding_quality",
    "audience_response",
    "artifact_conversion",
    "revenue_support_response",
    "rights_pass_probability",
    "safety_refusal_rate",
    "format_prior",
    "source_prior",
}
EXPECTED_CONSUMERS = {
    "content_opportunity_model",
    "programme_scheduler_policy",
    "content_programme_run_store",
    "format_grounding_evaluator",
    "conversion_broker",
    "metrics_dashboard",
}


def _body() -> str:
    return SPEC.read_text(encoding="utf-8")


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def _ledger() -> dict[str, object]:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def test_spec_covers_required_contract_sections() -> None:
    body = _body()

    for heading in (
        "## Feedback Event Contract",
        "## Lifecycle Coverage",
        "## Gate And Grounding Inputs",
        "## Witnessed Outcomes Versus Commands",
        "## Posterior Update Families",
        "## Aggregate Audience And Revenue Policy",
        "## Exploration And Novelty",
        "## Safety And Refusal Learning",
        "## Downstream Contract",
    ):
        assert heading in body


def test_schema_defines_feedback_event_fields_and_lifecycle_states() -> None:
    schema = _schema()
    event = schema["$defs"]["content_programme_feedback_event"]
    required = set(event["required"])

    for field in (
        "programme_state",
        "gate_outcomes",
        "grounding_outputs",
        "artifact_outputs",
        "audience_outcome",
        "revenue_proxies",
        "safety_metrics",
        "witnessed_capability_outcomes",
        "nested_programme_outcome_refs",
        "posterior_updates",
        "exploration",
        "separation_policy",
        "learning_policy",
        "append_only",
        "idempotency_key",
    ):
        assert field in required

    assert set(schema["$defs"]["programme_outcome_state"]["enum"]) == EXPECTED_STATES
    assert set(schema["$defs"]["posterior_update_family"]["enum"]) == EXPECTED_POSTERIOR_FAMILIES
    assert event["properties"]["append_only"]["const"] is True


def test_global_policy_and_separation_policy_forbid_metric_substitution() -> None:
    schema = _schema()
    global_policy = schema["properties"]["global_policy"]["properties"]
    separation = schema["$defs"]["separation_policy"]["properties"]

    for policy in (global_policy, separation):
        assert policy["engagement_can_override_grounding"]["const"] is False
        assert policy["revenue_can_override_grounding"]["const"] is False
        assert policy["selected_commanded_states_update_posteriors"]["const"] is False
        assert policy["blocked_claims_become_public_truth"]["const"] is False

    assert global_policy["posterior_store_mutation_allowed"]["const"] is False
    assert separation["audience_data_aggregate_only"]["const"] is True
    assert separation["per_person_audience_state_allowed"]["const"] is False
    assert separation["public_payer_identity_allowed"]["const"] is False


def test_schema_keeps_audience_and_revenue_aggregate_only() -> None:
    schema = _schema()
    audience = schema["$defs"]["audience_outcome"]["properties"]
    metric = schema["$defs"]["audience_metric"]["properties"]
    revenue = schema["$defs"]["revenue_proxy"]["properties"]

    assert audience["aggregate_only"]["const"] is True
    assert audience["per_person_identity_allowed"]["const"] is False
    assert audience["raw_comment_text_allowed"]["const"] is False
    assert audience["public_payer_identity_allowed"]["const"] is False
    assert metric["identity_scope"]["const"] == "aggregate"
    assert revenue["aggregate_only"]["const"] is True
    assert revenue["public_payer_identity_allowed"]["const"] is False

    body = _body()
    for phrase in (
        "Audience data is aggregate-only",
        "`per_person_audience_state_allowed = false`",
        "`public_payer_identity_allowed = false`",
        "`raw_comment_text_allowed = false`",
    ):
        assert phrase in body


def test_schema_separates_witnessed_capability_outcomes_from_commands() -> None:
    schema = _schema()
    witness = schema["$defs"]["capability_outcome_witness"]
    event = schema["$defs"]["content_programme_feedback_event"]

    assert "selected_state_refs" in event["required"]
    assert "commanded_state_refs" in event["required"]
    assert "witnessed_capability_outcomes" in event["required"]
    assert witness["properties"]["capability_outcome_envelope_ref"]["pattern"] == (
        "^CapabilityOutcomeEnvelope:"
    )

    body = _body()
    for phrase in (
        "Selected, commanded, accepted, queued, and executed states are execution facts",
        "They are not witnessed outcomes",
        "`selected_commanded_states_update_posteriors=false`",
    ):
        assert phrase in body


def test_seeded_ledger_covers_required_states_families_and_consumer_contract() -> None:
    ledger = _ledger()
    events = ledger["events"]
    states = {event["programme_state"] for event in events}
    update_families = {
        update["posterior_family"] for event in events for update in event["posterior_updates"]
    }

    assert ledger["schema_version"] == 1
    assert re.match(r"^[a-z][a-z0-9_:-]*$", ledger["ledger_id"])
    assert set(ledger["outcome_states"]) == EXPECTED_STATES
    assert set(ledger["posterior_update_families"]) == EXPECTED_POSTERIOR_FAMILIES

    for state in {
        "selected",
        "blocked",
        "dry_run",
        "public_run",
        "completed",
        "aborted",
        "refused",
        "corrected",
        "private_only",
    }:
        assert state in states

    for family in {
        "grounding_quality",
        "audience_response",
        "artifact_conversion",
        "revenue_support_response",
        "rights_pass_probability",
        "safety_refusal_rate",
    }:
        assert family in update_families

    contract = ledger["downstream_contract"]
    assert set(contract["machine_consumers"]) == EXPECTED_CONSUMERS
    for forbidden in (
        "engagement_as_truth",
        "revenue_as_truth",
        "selected_state_as_witness",
        "command_acceptance_as_witness",
        "blocked_claim_as_public_truth",
    ):
        assert forbidden in contract["forbidden_inferences"]


def test_seeded_ledger_keeps_blocked_refused_corrected_private_only_non_public_truth() -> None:
    for event in _ledger()["events"]:
        state = event["programme_state"]
        if state in {"blocked", "refused", "corrected", "private_only", "aborted"}:
            assert event["learning_policy"][
                "blocked_refused_corrected_private_only_are_learning_events"
            ]
            assert event["learning_policy"]["public_truth_claim_allowed"] is False
            assert event["separation_policy"]["blocked_claims_become_public_truth"] is False
            assert event["safety_metrics"], state


def test_example_feedback_event_is_parseable_and_conservative() -> None:
    body = _body()
    match = re.search(r"```json\n(?P<payload>.*?)\n```", body, re.DOTALL)
    assert match, "example ContentProgrammeFeedbackEvent JSON block missing"

    event = json.loads(match.group("payload"))

    assert event["schema_version"] == 1
    assert event["programme_state"] == "completed"
    assert event["audience_outcome"]["aggregate_only"] is True
    assert event["audience_outcome"]["per_person_identity_allowed"] is False
    assert event["revenue_proxies"][0]["aggregate_only"] is True
    assert event["witnessed_capability_outcomes"][0]["capability_outcome_envelope_ref"].startswith(
        "CapabilityOutcomeEnvelope:"
    )
    assert event["separation_policy"]["selected_commanded_states_update_posteriors"] is False
    assert event["separation_policy"]["engagement_can_override_grounding"] is False
    assert event["learning_policy"]["posterior_store_mutation_allowed"] is False
