"""Regression pins for the grounding/no-expert-system gate contract."""

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
    / "2026-04-29-grounding-commitment-no-expert-system-gate-design.md"
)
SCHEMA = REPO_ROOT / "schemas" / "grounding-commitment-gate.schema.json"


def _body() -> str:
    return SPEC.read_text(encoding="utf-8")


def _schema() -> dict[str, object]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def test_spec_covers_required_contract_sections() -> None:
    body = _body()

    for heading in (
        "## Machine-Readable Contract",
        "## Forbidden Grounding Infractions",
        "## Required Claim Fields",
        "## No-Expert-System Policy",
        "## Programme Format And Run Requirements",
        "## Refusal And Correction Artifacts",
        "## Latest-Model Policy",
        "## Downstream Machine-Readable Outputs",
    ):
        assert heading in body


def test_schema_has_required_gate_and_claim_fields() -> None:
    schema = _schema()
    required = set(schema["required"])
    properties = schema["properties"]

    for field in (
        "gate_id",
        "evaluated_at",
        "producer",
        "programme_id",
        "format_id",
        "run_id",
        "public_private_mode",
        "grounding_question",
        "permitted_claim_shape",
        "claim",
        "infractions",
        "gate_state",
        "gate_result",
        "no_expert_system_policy",
        "downstream",
    ):
        assert field in required
        assert field in properties

    claim_required = set(properties["claim"]["required"])
    for field in (
        "claim_text",
        "evidence_refs",
        "provenance",
        "confidence",
        "uncertainty",
        "scope_limit",
        "freshness",
        "rights_state",
        "privacy_state",
        "public_private_mode",
        "refusal_correction_path",
    ):
        assert field in claim_required


def test_schema_names_all_forbidden_grounding_infractions() -> None:
    schema = _schema()
    infractions = set(schema["$defs"]["grounding_infraction"]["enum"])

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
    for infraction in infractions:
        assert f"`{infraction}`" in body


def test_no_expert_system_policy_is_machine_readable_and_strict() -> None:
    schema = _schema()
    policy = schema["properties"]["no_expert_system_policy"]["properties"]

    assert policy["rules_may_gate_and_structure_attempts"]["const"] is True
    assert policy["authoritative_verdict_allowed"]["const"] is False
    assert policy["verdict_requires_evidence_bound_claim"]["const"] is True
    assert policy["latest_intelligence_default"]["const"] is True
    assert policy["older_model_exception_requires_grounding_evidence"]["const"] is True

    body = _body()
    for phrase in (
        "Hapax runs grounding attempts, not expert-system verdicts",
        "It may not emit hidden expertise",
        "Rules may",
        "Rules may not",
        "authoritative domain judgments",
    ):
        assert phrase in body


def test_example_gate_result_is_parseable_and_conservative() -> None:
    body = _body()
    schema = _schema()
    match = re.search(r"```json\n(?P<payload>.*?)\n```", body, re.DOTALL)
    assert match, "example GroundingCommitmentGateResult JSON block missing"

    gate = json.loads(match.group("payload"))

    assert gate["schema_version"] == 1
    assert re.match(schema["properties"]["gate_id"]["pattern"], gate["gate_id"])
    assert gate["public_private_mode"] == "dry_run"
    assert gate["permitted_claim_shape"]["authority_ceiling"] == "evidence_bound"
    assert gate["gate_state"] == "dry_run"
    assert gate["gate_result"]["may_publish_live"] is False
    assert gate["gate_result"]["may_monetize"] is False
    assert gate["no_expert_system_policy"]["authoritative_verdict_allowed"] is False
    assert gate["no_expert_system_policy"]["latest_intelligence_default"] is True
    assert "dry_run_until_provider_smoke" in gate["gate_result"]["blockers"]


def test_programme_formats_runs_refusals_and_downstream_surfaces_are_pinned() -> None:
    body = _body()

    for phrase in (
        "Every `ContentProgrammeFormat` and `ContentProgrammeRun` must declare",
        "`grounding_question`",
        "`permitted_claim_shape.claim_kind`",
        "`permitted_claim_shape.authority_ceiling`",
        "Blocked attempts are not silent skips",
        "refusal, correction, or failure artifact",
        "content format registry",
        "Bayesian opportunity model",
        "format grounding evaluator",
        "`ResearchVehiclePublicEvent`",
        "captions",
        "chapters",
        "YouTube metadata",
        "monetization readiness",
    ):
        assert phrase in body
