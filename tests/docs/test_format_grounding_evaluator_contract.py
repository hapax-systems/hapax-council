"""Regression pins for the format grounding evaluator contract."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = (
    REPO_ROOT / "docs" / "superpowers" / "specs" / "2026-04-29-format-grounding-evaluator-design.md"
)
SCHEMA = REPO_ROOT / "schemas" / "format-grounding-evaluator.schema.json"


def _body() -> str:
    return SPEC.read_text(encoding="utf-8")


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def test_spec_covers_required_contract_sections() -> None:
    body = _body()

    for heading in (
        "## Evaluation Contract",
        "## Per-Format Dimension Profiles",
        "## Claim Evidence And Confidence Requirements",
        "## Grounding Infractions",
        "## Reward Vector Inputs",
        "## Engagement Separation Policy",
        "## Feedback Ledger Interface",
    ):
        assert heading in body


def test_schema_defines_required_top_level_evaluation_fields() -> None:
    schema = _schema()
    required = set(schema["required"])
    properties = schema["properties"]

    for field in (
        "run_ref",
        "format_evaluator_profile",
        "gate_refs",
        "grounding_question",
        "dimension_scores",
        "scored_claims",
        "infractions",
        "evaluator_result",
        "no_expert_system_policy",
        "reward_vector_inputs",
        "feedback_ledger_interface",
        "separation_policy",
        "audit",
    ):
        assert field in required
        assert field in properties


def test_dimension_scores_cover_required_grounding_attempt_types() -> None:
    schema = _schema()
    dimensions = set(schema["properties"]["dimension_scores"]["required"])
    weights = set(
        schema["properties"]["format_evaluator_profile"]["properties"]["dimension_weights"][
            "required"
        ]
    )

    required_dimensions = {
        "perception",
        "classification",
        "comparison",
        "ranking",
        "explanation",
        "refusal",
        "uncertainty",
        "correction",
        "claim_confidence_movement",
    }

    assert dimensions == required_dimensions
    assert weights == required_dimensions
    assert schema["$defs"]["dimension_score"]["required"] == [
        "dimension_name",
        "applicable",
        "weight",
        "score",
        "evidence_refs",
        "confidence",
        "posterior_state",
        "failure_modes",
        "reward_signal",
    ]

    body = _body()
    for dimension in required_dimensions:
        assert f"`{dimension}`" in body


def test_scored_claims_require_evidence_refs_confidence_and_posterior_state() -> None:
    schema = _schema()
    scored_claim = schema["$defs"]["scored_claim"]
    required = set(scored_claim["required"])

    for field in (
        "evidence_refs",
        "confidence",
        "posterior_state",
        "claim_confidence_movement",
        "support_state",
        "scope_limit",
        "infraction_refs",
    ):
        assert field in required

    assert scored_claim["properties"]["evidence_refs"]["minItems"] == 1
    posterior = schema["$defs"]["posterior_state"]
    assert posterior["properties"]["evidence_refs"]["minItems"] == 1

    body = _body()
    for phrase in (
        "Evidence refs are mandatory even when the claim is a refusal",
        "Posterior state is mandatory for every scored claim",
        "`claim_confidence_movement` is a movement record, not a truth guarantee",
        "Confidence without evidence is recorded as `confidence_without_evidence`",
    ):
        assert phrase in body


def test_infractions_record_unsupported_overbroad_and_metric_substitution() -> None:
    schema = _schema()
    infractions = set(schema["$defs"]["grounding_infraction"]["enum"])

    for infraction in (
        "unsupported_claim",
        "overbroad_claim",
        "missing_evidence_ref",
        "missing_posterior_state",
        "confidence_without_evidence",
        "engagement_metric_substituted_for_grounding",
        "missing_reward_vector_input",
    ):
        assert infraction in infractions
        assert f"`{infraction}`" in _body()

    body = _body()
    for phrase in (
        "Unsupported and overbroad claims are not soft notes",
        "Unsupported means the claim lacks evidence",
        "Overbroad means the claim exceeds the candidate set",
    ):
        assert phrase in body


def test_reward_vector_inputs_keep_grounding_artifacts_revenue_and_engagement_separate() -> None:
    schema = _schema()
    reward = schema["properties"]["reward_vector_inputs"]
    required = set(reward["required"])

    assert required == {
        "grounding_reward_inputs",
        "artifact_reward_inputs",
        "revenue_reward_inputs",
        "engagement_observations",
        "posterior_update_targets",
    }

    grounding = reward["properties"]["grounding_reward_inputs"]
    assert set(grounding["required"]) == {
        "evidence_yield",
        "classification_quality",
        "comparison_quality",
        "ranking_stability",
        "explanation_quality",
        "uncertainty_quality",
        "refusal_quality",
        "correction_value",
        "posterior_update",
        "inconsistency_discovery",
    }

    engagement = reward["properties"]["engagement_observations"]["properties"]
    assert engagement["kept_separate"]["const"] is True
    assert engagement["may_override_grounding"]["const"] is False

    separation = schema["properties"]["separation_policy"]["properties"]
    assert separation["engagement_can_override_grounding"]["const"] is False
    assert separation["engagement_metrics_stored_separately"]["const"] is True
    assert (
        separation["substitution_infraction"]["const"]
        == "engagement_metric_substituted_for_grounding"
    )


def test_no_expert_system_policy_is_machine_readable_and_strict() -> None:
    schema = _schema()
    policy = schema["properties"]["no_expert_system_policy"]["properties"]

    assert policy["rules_may_score_attempt_quality"]["const"] is True
    assert policy["authoritative_verdict_allowed"]["const"] is False
    assert policy["domain_truth_adjudication_allowed"]["const"] is False
    assert policy["score_requires_evidence_bound_claim"]["const"] is True
    assert policy["score_may_block_or_refuse"]["const"] is True

    body = _body()
    for phrase in (
        "It does not decide domain truth",
        "They may not declare an authoritative domain verdict",
        "without acting as an expert-system verdict engine",
    ):
        assert phrase in body


def test_example_evaluation_is_parseable_conservative_and_ledger_ready() -> None:
    body = _body()
    schema = _schema()
    match = re.search(r"```json\n(?P<payload>.*?)\n```", body, re.DOTALL)
    assert match, "example FormatGroundingEvaluation JSON block missing"

    evaluation = json.loads(match.group("payload"))

    assert evaluation["schema_version"] == 1
    assert re.match(schema["properties"]["evaluation_id"]["pattern"], evaluation["evaluation_id"])
    assert evaluation["run_ref"]["format_id"] == "tier_list"
    assert evaluation["run_ref"]["public_private_mode"] == "dry_run"
    assert evaluation["evaluator_result"]["public_claim_allowed"] is False
    assert evaluation["evaluator_result"]["refusal_required"] is True
    assert evaluation["no_expert_system_policy"]["authoritative_verdict_allowed"] is False
    assert evaluation["feedback_ledger_interface"]["event_kind"] == "format_grounding_evaluation"
    assert evaluation["feedback_ledger_interface"]["only_if_evidence_bound"] is True
    assert evaluation["reward_vector_inputs"]["engagement_observations"]["kept_separate"] is True
    assert (
        evaluation["reward_vector_inputs"]["engagement_observations"]["may_override_grounding"]
        is False
    )
    assert (
        "grounding_yield_probability"
        in evaluation["reward_vector_inputs"]["posterior_update_targets"]
    )
