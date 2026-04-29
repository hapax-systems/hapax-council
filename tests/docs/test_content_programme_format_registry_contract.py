"""Regression pins for the content programme format registry contract."""

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
    / "2026-04-29-autonomous-content-programming-format-registry-design.md"
)
SCHEMA = REPO_ROOT / "schemas" / "content-programme-format.schema.json"


def _body() -> str:
    return SPEC.read_text(encoding="utf-8")


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def test_spec_covers_required_contract_sections() -> None:
    body = _body()

    for heading in (
        "## `ContentProgrammeFormat` Schema Seed",
        "## Initial Format Registry",
        "## Grounding Attempt Semantics",
        "## No-Expert-System And Evidence Fields",
        "## Rights And Consent Fail-Closed Policy",
        "## Public Output Mapping",
        "## Bayesian Selection And Rewards",
        "## Revenue And Artifact Mapping",
        "## Operator Labor Constraint",
        "## Downstream Unblockers",
    ):
        assert heading in body


def test_schema_has_required_content_programme_format_fields() -> None:
    schema = _schema()
    required = set(schema["required"])
    properties = schema["properties"]

    for field in (
        "format_id",
        "traditional_content_analogue",
        "grounding_question",
        "grounding_attempt_types",
        "input_substrates",
        "allowed_media_classes",
        "director_verbs",
        "permitted_claim_shape",
        "evidence_requirement",
        "no_expert_system_policy",
        "rights_posture",
        "public_claim_policy",
        "public_output_mapping",
        "archive_outputs",
        "monetization_posture",
        "bayesian_policy",
        "metrics",
        "grounding_infraction_behavior",
        "operator_labor_policy",
        "boundary_event_types",
    ):
        assert field in required
        assert field in properties


def test_schema_and_spec_seed_all_initial_formats() -> None:
    schema = _schema()
    formats = set(schema["$defs"]["format_id"]["enum"])

    assert formats == {
        "tier_list",
        "react_commentary",
        "ranking",
        "comparison",
        "review",
        "watch_along",
        "explainer",
        "rundown",
        "debate",
        "bracket",
        "what_is_this",
        "refusal_breakdown",
        "evidence_audit",
    }

    body = _body()
    for format_id in formats:
        assert f"`{format_id}`" in body


def test_grounding_attempt_types_and_gate_fields_are_machine_readable() -> None:
    schema = _schema()
    attempt_types = set(schema["$defs"]["grounding_attempt_type"]["enum"])

    assert attempt_types >= {
        "perception",
        "classification",
        "comparison",
        "ranking",
        "explanation",
        "refusal",
        "uncertainty",
        "correction",
        "claim_confidence_update",
        "timed_attention",
        "evidence_validation",
        "inconsistency_testing",
    }

    claim_required = set(schema["properties"]["permitted_claim_shape"]["required"])
    evidence_required = set(schema["properties"]["evidence_requirement"]["required"])

    for field in (
        "claim_kind",
        "authority_ceiling",
        "confidence_policy",
        "uncertainty_language",
        "scope_limit",
    ):
        assert field in claim_required

    for field in (
        "required_evidence_classes",
        "minimum_evidence_refs",
        "freshness_ttl_s",
        "requires_rights_provenance",
        "requires_grounding_gate",
        "requires_public_event_mapping",
    ):
        assert field in evidence_required

    body = _body()
    for phrase in (
        "Every format must explicitly name what counts as a successful or failed",
        "`claim_confidence_update` never means a truth guarantee",
        "`ProgrammeBoundaryEvent` records",
        "`permitted_claim_shape.authority_ceiling`",
    ):
        assert phrase in body


def test_no_expert_system_policy_and_infraction_behavior_are_strict() -> None:
    schema = _schema()
    policy = schema["properties"]["no_expert_system_policy"]["properties"]
    infractions = set(schema["properties"]["grounding_infraction_behavior"]["required"])

    assert policy["rules_may_gate_and_structure_attempts"]["const"] is True
    assert policy["authoritative_verdict_allowed"]["const"] is False
    assert policy["trend_as_truth_allowed"]["const"] is False
    assert policy["hidden_expertise_allowed"]["const"] is False
    assert policy["must_emit_uncertainty"]["const"] is True

    assert infractions == {
        "unsupported_claim",
        "hidden_expertise",
        "unlabelled_uncertainty",
        "stale_source_claim",
        "rights_provenance_bypass",
        "trend_as_truth",
        "false_public_live_claim",
        "false_monetization_claim",
        "missing_grounding_question",
        "missing_permitted_claim_shape",
        "expert_verdict_without_evidence",
    }

    body = _body()
    for phrase in (
        "Hapax cannot act as a hidden rule engine",
        "rules may not become a hidden domain authority",
        "trend/currentness is input evidence, not truth",
        "no format may convert a blocked infraction into public content except as an",
    ):
        assert phrase in body


def test_rights_consent_and_public_output_mapping_fail_closed() -> None:
    schema = _schema()
    rights = schema["properties"]["rights_posture"]["properties"]
    output_required = set(schema["properties"]["public_output_mapping"]["required"])
    false_claim_controls = set(schema["$defs"]["false_claim_control"]["enum"])

    assert rights["consent_required_media_allowed"]["const"] is False
    assert rights["uncleared_media_allowed_publicly"]["const"] is False
    assert rights["monetization_requires_rights_clearance"]["const"] is True

    assert output_required >= {
        "title_policy",
        "description_policy",
        "chapter_policy",
        "caption_policy",
        "shorts_policy",
        "archive_replay_policy",
        "public_event_policy",
        "false_claim_controls",
    }
    assert false_claim_controls >= {
        "no_live_claim_without_egress",
        "no_archive_claim_without_archive_ref",
        "no_monetization_claim_without_ledger",
        "no_rights_claim_without_provenance",
        "no_source_claim_without_evidence_refs",
        "no_short_without_owned_or_cleared_media",
    }

    body = _body()
    for phrase in (
        "Third-party media is unsafe by default",
        "Unknown means unavailable, not safe",
        "no third-party rebroadcast",
        "YouTube title policy",
        "`ResearchVehiclePublicEvent` policy",
        "Dry-run outputs must say they are dry-run or remain private",
    ):
        assert phrase in body


def test_bayesian_revenue_and_operator_labor_fields_are_pinned() -> None:
    schema = _schema()
    bayesian_required = set(schema["properties"]["bayesian_policy"]["required"])
    revenue_routes = set(schema["$defs"]["revenue_route"]["enum"])
    labor = schema["properties"]["operator_labor_policy"]["properties"]

    assert bayesian_required == {
        "format_prior",
        "source_compatibility",
        "grounding_reward_dimensions",
        "artifact_revenue_reward_dimensions",
        "exploration_eligibility",
        "cooldown_policy",
    }
    assert revenue_routes == {
        "platform_native",
        "support_prompt",
        "artifact",
        "replay",
        "edition",
        "grant_demo_evidence",
        "refusal_artifact",
    }
    assert labor["recurring_operator_labor_allowed"]["const"] is False
    assert labor["community_obligation_allowed"]["const"] is False
    assert labor["request_queue_allowed"]["const"] is False
    assert labor["personalized_supporter_treatment_allowed"]["const"] is False

    body = _body()
    for phrase in (
        "`bayesian_policy.format_prior.grounding_value`",
        "`bayesian_policy.source_compatibility`",
        "`bayesian_policy.cooldown_policy`",
        "Revenue mapping is allowed only as posture, not as a promise",
        "Paid promotion, affiliate, free-product review compensation",
        "If a format requires recurring operator authorship",
    ):
        assert phrase in body


def test_example_format_row_is_parseable_and_conservative() -> None:
    body = _body()
    schema = _schema()
    match = re.search(r"```json\n(?P<payload>.*?)\n```", body, re.DOTALL)
    assert match, "example ContentProgrammeFormat JSON block missing"

    row = json.loads(match.group("payload"))

    assert row["schema_version"] == 1
    assert row["format_id"] in schema["$defs"]["format_id"]["enum"]
    assert row["format_id"] == "tier_list"
    assert row["rights_posture"]["default_public_mode"] == "dry_run"
    assert row["rights_posture"]["consent_required_media_allowed"] is False
    assert row["rights_posture"]["uncleared_media_allowed_publicly"] is False
    assert row["public_claim_policy"]["public_live_allowed"] is False
    assert row["public_claim_policy"]["correction_artifact_required_on_public_error"] is True
    assert row["monetization_posture"]["paid_promotion_allowed"] is False
    assert row["operator_labor_policy"]["recurring_operator_labor_allowed"] is False
    assert "no_live_claim_without_egress" in row["public_output_mapping"]["false_claim_controls"]
