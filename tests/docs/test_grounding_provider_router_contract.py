"""Regression pins for the grounding provider router and eval harness."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = (
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-04-29-grounding-provider-model-router-eval-harness-design.md"
)
PROVIDER_SCHEMA = REPO_ROOT / "schemas" / "grounding-provider-router.schema.json"
EVAL_SCHEMA = REPO_ROOT / "schemas" / "grounding-eval-suite.schema.json"
PROVIDER_REGISTRY = REPO_ROOT / "config" / "grounding-providers.json"
EVAL_SUITE = REPO_ROOT / "config" / "grounding-eval-suite.json"


def _body() -> str:
    return SPEC.read_text(encoding="utf-8")


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_spec_covers_required_contract_sections() -> None:
    body = _body()

    for heading in (
        "## Provider Registry",
        "## Evidence Envelope",
        "## Routing Policy",
        "## Current Provider Facts",
        "## Eval Suite",
        "## Scoring Dimensions",
        "## Artifact Contract",
        "## Downstream Contract",
        "## Verification",
    ):
        assert heading in body


def test_schemas_configs_and_required_adapter_ids_are_parseable() -> None:
    provider_schema = _json(PROVIDER_SCHEMA)
    eval_schema = _json(EVAL_SCHEMA)
    registry = _json(PROVIDER_REGISTRY)
    suite = _json(EVAL_SUITE)

    assert provider_schema["title"] == "GroundingProviderRouterRegistry"
    assert eval_schema["title"] == "GroundingProviderEvalSuite"
    assert registry["schema_version"] == 1
    assert suite["schema_version"] == 1

    adapter_ids = {item["adapter_id"] for item in registry["providers"]}
    assert adapter_ids == {
        "local_supplied_evidence_command_r",
        "openai_web_search",
        "anthropic_web_search",
        "gemini_google_search",
        "gemini_deep_research",
        "perplexity_search_or_sonar",
    }


def test_provider_schema_pins_evidence_envelope_and_policy_constants() -> None:
    schema = _json(PROVIDER_SCHEMA)
    policy = schema["properties"]["routing_policy"]["properties"]
    evidence_fields = set(schema["$defs"]["evidence_field"]["enum"])
    grounded_claim_types = set(schema["$defs"]["grounding_required_claim_type"]["enum"])

    for field in (
        "provider_id",
        "model_id",
        "tool_id",
        "input_claim_request",
        "retrieval_events",
        "source_items",
        "claim_items",
        "citations",
        "confidence_or_posterior",
        "source_quality",
        "freshness",
        "refusal_or_uncertainty",
        "tool_errors",
        "raw_source_hashes",
        "retrieved_at",
    ):
        assert field in evidence_fields
        assert f"`{field}`" in _body()

    assert policy["open_world_claims_require_grounding"]["const"] is True
    assert policy["latest_cloud_model_default"]["const"] is True
    assert policy["older_model_exception_required"]["const"] is True
    assert policy["command_r_source_supplied_only"]["const"] is True
    assert policy["director_model_swap_requires_eval_pass"]["const"] is True
    assert "knowledge_recruitment_guidance_request" in grounded_claim_types
    assert "`knowledge_recruitment_guidance_request`" in _body()


def test_live_route_policy_records_required_latest_aliases() -> None:
    registry = _json(PROVIDER_REGISTRY)
    policy = registry["routing_policy"]

    assert policy["anthropic_required_aliases"] == {
        "claude-sonnet": "claude-sonnet-4-6",
        "claude-opus": "claude-opus-4-7",
    }
    assert policy["gemini_required_route_family"] == "gemini-3"

    providers = {provider["provider_id"]: provider for provider in registry["providers"]}
    assert providers["gemini_google_search"]["model_id"].startswith("gemini-3")
    assert providers["gemini_deep_research"]["model_id"] == "deep-research-preview-04-2026"
    assert providers["anthropic_web_search"]["model_id"] == "claude-sonnet-4-6"
    assert providers["openai_web_search"]["model_id"] == "gpt-5.5"


def test_command_r_is_not_an_open_world_grounder_or_director_swap() -> None:
    registry = _json(PROVIDER_REGISTRY)
    providers = {provider["provider_id"]: provider for provider in registry["providers"]}
    command_r = providers["local_supplied_evidence_command_r"]

    assert command_r["provider_kind"] == "source_conditioned"
    assert command_r["requires_supplied_evidence"] is True
    assert command_r["can_satisfy_open_world_claims"] is False
    assert command_r["director_default_allowed"] is True
    assert command_r["exception_record"]["reason"] == "local_director_grounding_evidence"

    body = _body()
    assert "It may not satisfy open-world" in body
    assert "`director_model_swap_requires_eval_pass: true`" in body


def test_eval_suite_has_30_to_50_items_and_all_required_categories() -> None:
    suite = _json(EVAL_SUITE)
    items = suite["eval_items"]

    assert 30 <= len(items) <= 50
    assert {item["category"] for item in items} >= {
        "global_competence_gap_guidance",
        "current_model_release_scouting",
        "content_opportunity_discovery",
        "tier_list_react_video_evidence_packets",
        "local_only_obsidian_facts",
        "contradicted_sources",
        "stale_documentation",
        "public_rights_provenance_claims",
        "refusal_required_prompts",
        "tool_error_surfacing",
    }

    for item in items:
        assert item["requires_grounding"] is True
        assert item["expected_behaviors"]
        assert item["failure_modes"]
        assert abs(sum(item["scoring_weights"].values()) - 1) < 0.000001


def test_sources_and_downstream_gates_are_named() -> None:
    body = _body()

    for source in (
        "https://developers.openai.com/api/docs/guides/tools-web-search",
        "https://platform.claude.com/docs/en/release-notes/overview",
        "https://ai.google.dev/gemini-api/docs/google-search",
        "https://ai.google.dev/gemini-api/docs/deep-research",
        "https://docs.perplexity.ai/docs/sonar/quickstart",
    ):
        assert source in body

    for downstream in (
        "trend-current-event-constraint-gate",
        "format-grounding-evaluator",
        "content-candidate-discovery-daemon",
        "content-programming-grounding-runner",
    ):
        assert downstream in body


def test_public_grounding_configs_do_not_embed_operator_home_paths() -> None:
    for path in (PROVIDER_REGISTRY, EVAL_SUITE, SPEC):
        text = path.read_text(encoding="utf-8")
        assert "/home/hapax" not in text
        assert "local:/home/" not in text
