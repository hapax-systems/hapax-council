"""Unit tests for the grounding provider router helpers."""

from __future__ import annotations

import json

from shared.grounding_provider_router import (
    REQUIRED_EVAL_CATEGORIES,
    REQUIRED_PROVIDER_ADAPTERS,
    build_eval_artifact,
    build_privacy_egress_preflight,
    claim_requires_grounding,
    load_provider_specs,
    route_candidates_for_claim,
    validate_eval_suite,
    validate_provider_registry,
)


def _provider_registry() -> dict[str, object]:
    with open("config/grounding-providers.json", encoding="utf-8") as handle:
        return json.load(handle)


def _eval_suite() -> dict[str, object]:
    with open("config/grounding-eval-suite.json", encoding="utf-8") as handle:
        return json.load(handle)


def test_provider_registry_validator_accepts_seed_registry() -> None:
    registry = _provider_registry()

    assert validate_provider_registry(registry) == []
    assert {item["adapter_id"] for item in registry["providers"]} == REQUIRED_PROVIDER_ADAPTERS


def test_provider_specs_pin_command_r_as_source_conditioned_only() -> None:
    providers = {provider.provider_id: provider for provider in load_provider_specs()}
    command_r = providers["local_supplied_evidence_command_r"]

    assert command_r.provider_kind == "source_conditioned"
    assert command_r.requires_supplied_evidence is True
    assert command_r.can_satisfy_open_world_claims is False
    assert command_r.director_default_allowed is True
    assert command_r.exception_record is not None
    assert command_r.exception_record["reason"] == "local_director_grounding_evidence"


def test_cloud_providers_require_latest_routes_and_egress_preflight() -> None:
    providers = load_provider_specs()

    cloud_providers = [provider for provider in providers if provider.cloud_route]
    assert cloud_providers

    for provider in cloud_providers:
        assert provider.latest_model_default is True
        assert provider.egress_preflight_required is True
        assert provider.director_default_allowed is False
        assert provider.can_satisfy_open_world_claims is True


def test_claim_routing_excludes_command_r_for_open_world_without_supplied_evidence() -> None:
    without_supplied = route_candidates_for_claim(
        "open_world_factual_claim",
        supplied_evidence=False,
    )
    with_supplied = route_candidates_for_claim(
        "open_world_factual_claim",
        supplied_evidence=True,
    )

    assert claim_requires_grounding("open_world_factual_claim") is True
    assert claim_requires_grounding("private_brainstorm") is False
    assert "local_supplied_evidence_command_r" not in {
        provider.provider_id for provider in without_supplied
    }
    assert "local_supplied_evidence_command_r" in {
        provider.provider_id for provider in with_supplied
    }


def test_knowledge_recruitment_guidance_is_grounded_but_not_local_source_acquired() -> None:
    without_supplied = route_candidates_for_claim(
        "knowledge_recruitment_guidance_request",
        supplied_evidence=False,
    )
    with_supplied = route_candidates_for_claim(
        "knowledge_recruitment_guidance_request",
        supplied_evidence=True,
    )

    assert claim_requires_grounding("knowledge_recruitment_guidance_request") is True
    assert "local_supplied_evidence_command_r" not in {
        provider.provider_id for provider in without_supplied
    }
    assert "local_supplied_evidence_command_r" in {
        provider.provider_id for provider in with_supplied
    }


def test_eval_suite_validator_accepts_seed_suite_and_required_categories() -> None:
    suite = _eval_suite()
    items = suite["eval_items"]

    assert validate_eval_suite(suite) == []
    assert 30 <= len(items) <= 50
    assert {item["category"] for item in items} >= REQUIRED_EVAL_CATEGORIES


def test_eval_artifact_shell_is_deterministic_and_replayable() -> None:
    eval_item = _eval_suite()["eval_items"][0]
    observed = {
        "source_items": [{"url": "https://example.com", "title": "Example"}],
        "claim_items": [{"text": "Example claim"}],
    }

    first = build_eval_artifact("openai_web_search", eval_item, observed=observed)
    second = build_eval_artifact("openai_web_search", eval_item, observed=observed)

    assert first == second
    assert first["schema_version"] == 1
    assert first["provider_id"] == "openai_web_search"
    assert first["eval_id"] == eval_item["eval_id"]
    assert first["scores"]
    assert first["pass"] is None
    assert len(first["raw_hash"]) == 64


def test_privacy_egress_preflight_blocks_cloud_routes_without_redaction_pass() -> None:
    blocked = build_privacy_egress_preflight(
        "openai_web_search",
        redaction_passed=False,
        payload_refs=["local:private-note-excerpt"],
    )
    passed = build_privacy_egress_preflight(
        "openai_web_search",
        redaction_passed=True,
        payload_refs=["local:redacted-claim-request"],
    )
    local = build_privacy_egress_preflight(
        "local_supplied_evidence_command_r",
        redaction_passed=False,
        payload_refs=["local:private-note-excerpt"],
    )

    assert blocked["egress_preflight_required"] is True
    assert blocked["pass"] is False
    assert blocked["blockers"] == ["cloud_route_redaction_not_passed"]
    assert passed["pass"] is True
    assert passed["blockers"] == []
    assert local["egress_preflight_required"] is False
    assert local["pass"] is True
