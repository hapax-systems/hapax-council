"""Regression pins for the Bayesian content opportunity model contract."""

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
    / "2026-04-29-bayesian-content-opportunity-model-design.md"
)
SCHEMA = REPO_ROOT / "schemas" / "content-opportunity-model.schema.json"


def _body() -> str:
    return SPEC.read_text(encoding="utf-8")


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def test_spec_covers_required_contract_sections() -> None:
    body = re.sub(r"\s+", " ", _body())

    for heading in (
        "## ContentOpportunity Contract",
        "## Eligibility Gates",
        "## Reward Vector",
        "## Posterior Families",
        "## Hierarchical Thompson Sampling",
        "## Cold-Start Priors",
        "## Persistence And Audit",
        "## Downstream Interfaces",
    ):
        assert heading in body


def test_schema_defines_content_opportunity_tuple() -> None:
    schema = _schema()
    opportunity = schema["properties"]["opportunity"]
    required = set(opportunity["required"])

    for field in (
        "format_id",
        "input_source_id",
        "subject",
        "time_window",
        "substrate_refs",
        "public_mode",
        "rights_state",
    ):
        assert field in required
        assert field in opportunity["properties"]

    body = re.sub(r"\s+", " ", _body())
    assert (
        "ContentOpportunity = format + input_source + subject + time_window + substrates "
        "+ public_mode + rights_state"
    ) in body


def test_schema_names_all_required_eligibility_gates() -> None:
    schema = _schema()
    eligibility = schema["properties"]["eligibility"]
    required = set(eligibility["required"])

    for gate in (
        "truth_gate",
        "rights_gate",
        "consent_gate",
        "monetization_gate",
        "substrate_freshness_gate",
        "egress_gate",
        "no_expert_system_gate",
    ):
        assert gate in required
        assert gate in eligibility["properties"]
        assert f"`{gate}`" in _body()


def test_reward_vector_pins_values_penalties_and_expected_score() -> None:
    schema = _schema()
    reward = schema["properties"]["reward_vector"]
    required = set(reward["required"])

    for component in (
        "grounding_value",
        "audience_value",
        "artifact_value",
        "revenue_value",
        "novelty_bonus",
        "cost_penalty",
        "risk_penalty",
        "expected_total",
    ):
        assert component in required
        assert component in reward["properties"]

    body = _body()
    assert "score = E[grounding_value] + E[audience_value] + E[artifact_value]" in body
    assert "- cost_penalty - risk_penalty" in body


def test_posterior_state_tracks_each_required_family() -> None:
    schema = _schema()
    posterior_state = schema["properties"]["posterior_state"]
    required = set(posterior_state["required"])

    for posterior in (
        "format_prior",
        "source_prior",
        "rights_pass_probability",
        "grounding_yield_probability",
        "artifact_conversion_probability",
        "audience_response",
        "revenue_support_response",
        "trend_decay",
    ):
        assert posterior in required
        assert posterior in posterior_state["properties"]
        assert f"`{posterior}`" in _body()


def test_sampler_policy_is_hierarchical_bounded_and_cooldown_aware() -> None:
    schema = _schema()
    sampler = schema["properties"]["sampler_policy"]["properties"]

    hierarchy = sampler["hierarchy"]["prefixItems"]
    assert [item["const"] for item in hierarchy] == ["format", "source", "subject_cluster"]

    budget_required = set(sampler["exploration_budget"]["required"])
    for field in (
        "budget_window",
        "max_exploration_fraction",
        "used_fraction",
        "remaining_fraction",
        "private_first",
        "max_public_risk_tier",
    ):
        assert field in budget_required

    cooldown_required = set(sampler["cooldowns"]["required"])
    for field in (
        "format_cooldown_s",
        "source_cooldown_s",
        "subject_cluster_cooldown_s",
        "public_mode_cooldown_s",
        "refusal_cooldown_s",
    ):
        assert field in cooldown_required


def test_cold_start_and_persistence_require_audit_replay_update_and_refusal() -> None:
    schema = _schema()

    cold_start = schema["properties"]["cold_start_priors"]["properties"]
    assert cold_start["low_rights_high_grounding_bias"]["const"] is True

    persistence_required = set(schema["properties"]["persistence"]["required"])
    for field in (
        "audit_log_ref",
        "replay_key",
        "posterior_update_ref",
        "refusal_artifact_ref",
        "decision_trace_refs",
        "state_store_ref",
        "idempotency_key",
    ):
        assert field in persistence_required

    body = re.sub(r"\s+", " ", _body())
    for phrase in (
        "low-rights/high-grounding",
        "audit, replay, posterior update, and refusal",
        "Blocked candidates become a refusal, correction, or failure artifact",
    ):
        assert phrase in body


def test_example_decision_is_parseable_and_fail_closed_for_public_claims() -> None:
    body = _body()
    schema = _schema()
    match = re.search(r"```json\n(?P<payload>.*?)\n```", body, re.DOTALL)
    assert match, "example ContentOpportunityModelDecision JSON block missing"

    decision = json.loads(match.group("payload"))

    assert decision["schema_version"] == 1
    assert re.match(schema["properties"]["decision_id"]["pattern"], decision["decision_id"])
    assert decision["opportunity"]["public_mode"] == "dry_run"
    assert decision["eligibility"]["eligible"] is True
    assert decision["eligibility"]["public_selectable"] is False
    assert decision["eligibility"]["monetizable"] is False
    assert decision["eligibility"]["egress_gate"]["state"] == "fail"
    assert "egress_blocked" in decision["sampler_decision"]["held_reasons"]
    assert decision["sampler_policy"]["exploration_budget"]["private_first"] is True
    assert decision["sampler_decision"]["decision"] == "select_dry_run"
