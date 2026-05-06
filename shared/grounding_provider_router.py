"""Grounding-provider registry and eval-suite helpers.

The router contract is intentionally provider-neutral. Live adapters can call
OpenAI, Anthropic, Gemini, Perplexity, or local Command-R later, but they must
all normalize into the same evidence envelope before public claims consume them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PROVIDER_REGISTRY = REPO_ROOT / "config" / "grounding-providers.json"
EVAL_SUITE = REPO_ROOT / "config" / "grounding-eval-suite.json"

REQUIRED_PROVIDER_ADAPTERS = frozenset(
    {
        "local_supplied_evidence_command_r",
        "openai_web_search",
        "anthropic_web_search",
        "gemini_google_search",
        "gemini_deep_research",
        "perplexity_search_or_sonar",
    }
)

REQUIRED_EVIDENCE_FIELDS = frozenset(
    {
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
    }
)

REQUIRES_GROUNDING_CLAIM_TYPES = frozenset(
    {
        "open_world_factual_claim",
        "current_event_claim",
        "knowledge_recruitment_guidance_request",
        "model_vendor_comparison",
        "rights_provenance_claim",
        "public_content_programming_assertion",
    }
)

REQUIRED_EVAL_CATEGORIES = frozenset(
    {
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
)


class ProviderKind(StrEnum):
    """Provider grounding capability classes."""

    SOURCE_ACQUIRING = "source_acquiring"
    SOURCE_CONDITIONED = "source_conditioned"
    GENERAL_REASONING = "general_reasoning"


@dataclass(frozen=True)
class GroundingProviderSpec:
    """A provider route normalized from the registry."""

    provider_id: str
    adapter_id: str
    provider_kind: ProviderKind
    model_id: str
    tool_id: str
    cloud_route: bool
    latest_model_default: bool
    requires_supplied_evidence: bool
    can_satisfy_open_world_claims: bool
    egress_preflight_required: bool
    director_default_allowed: bool
    evidence_contract: frozenset[str]
    exception_record: dict[str, Any] | None

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> GroundingProviderSpec:
        return cls(
            provider_id=str(payload["provider_id"]),
            adapter_id=str(payload["adapter_id"]),
            provider_kind=ProviderKind(str(payload["provider_kind"])),
            model_id=str(payload["model_id"]),
            tool_id=str(payload["tool_id"]),
            cloud_route=bool(payload["cloud_route"]),
            latest_model_default=bool(payload["latest_model_default"]),
            requires_supplied_evidence=bool(payload["requires_supplied_evidence"]),
            can_satisfy_open_world_claims=bool(payload["can_satisfy_open_world_claims"]),
            egress_preflight_required=bool(payload["egress_preflight_required"]),
            director_default_allowed=bool(payload["director_default_allowed"]),
            evidence_contract=frozenset(payload["evidence_contract"]["required_fields"]),
            exception_record=payload.get("exception_record"),
        )


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON object from disk."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return payload


def load_provider_specs(path: Path = PROVIDER_REGISTRY) -> list[GroundingProviderSpec]:
    """Load the grounding-provider registry as typed specs."""

    payload = load_json(path)
    return [GroundingProviderSpec.from_mapping(item) for item in payload["providers"]]


def provider_by_id(path: Path = PROVIDER_REGISTRY) -> dict[str, GroundingProviderSpec]:
    """Return provider specs keyed by provider id."""

    return {provider.provider_id: provider for provider in load_provider_specs(path)}


def claim_requires_grounding(claim_type: str) -> bool:
    """Return whether a claim type must use a grounding-capable route."""

    return claim_type in REQUIRES_GROUNDING_CLAIM_TYPES


def route_candidates_for_claim(
    claim_type: str,
    *,
    supplied_evidence: bool,
    path: Path = PROVIDER_REGISTRY,
) -> list[GroundingProviderSpec]:
    """Return provider candidates that can satisfy a claim request shape."""

    candidates = load_provider_specs(path)
    if not claim_requires_grounding(claim_type):
        return candidates

    eligible: list[GroundingProviderSpec] = []
    for provider in candidates:
        if provider.can_satisfy_open_world_claims or (
            supplied_evidence and provider.requires_supplied_evidence
        ):
            eligible.append(provider)
    return eligible


def validate_provider_registry(payload: dict[str, Any]) -> list[str]:
    """Return human-readable registry contract violations."""

    errors: list[str] = []
    providers = payload.get("providers", [])
    if not isinstance(providers, list):
        return ["providers must be a list"]

    adapters = {
        str(item["adapter_id"])
        for item in providers
        if isinstance(item, dict) and isinstance(item.get("adapter_id"), str)
    }
    missing_adapters = REQUIRED_PROVIDER_ADAPTERS - adapters
    for adapter_id in sorted(missing_adapters):
        errors.append(f"missing required provider adapter: {adapter_id}")

    policy = payload.get("routing_policy", {})
    if policy.get("open_world_claims_require_grounding") is not True:
        errors.append("open-world claims must require grounding")
    if policy.get("latest_cloud_model_default") is not True:
        errors.append("cloud routes must default to latest/highest-intelligence models")
    if policy.get("older_model_exception_required") is not True:
        errors.append("older cloud models must require exception records")
    if policy.get("director_model_swap_requires_eval_pass") is not True:
        errors.append("director swaps must require eval harness pass")
    policy_claim_types = policy.get("grounding_required_claim_types", [])
    if not isinstance(policy_claim_types, list):
        errors.append("grounding_required_claim_types must be a list")
        policy_claim_types = []
    policy_claim_type_set = {str(item) for item in policy_claim_types}
    for claim_type in sorted(REQUIRES_GROUNDING_CLAIM_TYPES - policy_claim_type_set):
        errors.append(f"missing grounded claim type: {claim_type}")
    for claim_type in sorted(policy_claim_type_set - REQUIRES_GROUNDING_CLAIM_TYPES):
        errors.append(f"unknown grounded claim type: {claim_type}")

    for item in providers:
        provider = GroundingProviderSpec.from_mapping(item)
        missing_fields = REQUIRED_EVIDENCE_FIELDS - provider.evidence_contract
        for field in sorted(missing_fields):
            errors.append(f"{provider.provider_id} missing evidence field: {field}")

        if provider.cloud_route and not provider.egress_preflight_required:
            errors.append(f"{provider.provider_id} cloud route lacks egress preflight")

        if provider.cloud_route and not provider.latest_model_default:
            if not provider.exception_record:
                errors.append(f"{provider.provider_id} lacks older-model exception record")

        if provider.adapter_id == "local_supplied_evidence_command_r":
            if provider.can_satisfy_open_world_claims:
                errors.append("Command-R may not satisfy open-world claims by itself")
            if not provider.requires_supplied_evidence:
                errors.append("Command-R route must require supplied evidence")

        if (
            provider.director_default_allowed
            and provider.adapter_id != "local_supplied_evidence_command_r"
        ):
            errors.append(f"{provider.provider_id} is incorrectly marked director-default")

    return errors


def validate_eval_suite(payload: dict[str, Any]) -> list[str]:
    """Return human-readable eval-suite contract violations."""

    errors: list[str] = []
    items = payload.get("eval_items", [])
    if not isinstance(items, list):
        return ["eval_items must be a list"]

    if not 30 <= len(items) <= 50:
        errors.append("eval suite must contain 30-50 items")

    categories = {
        str(item["category"])
        for item in items
        if isinstance(item, dict) and isinstance(item.get("category"), str)
    }
    missing_categories = REQUIRED_EVAL_CATEGORIES - categories
    for category in sorted(missing_categories):
        errors.append(f"missing eval category: {category}")

    for item in items:
        eval_id = item.get("eval_id", "<missing>")
        if item.get("requires_grounding") is not True:
            errors.append(f"{eval_id} must require grounding")
        if not item.get("expected_behaviors"):
            errors.append(f"{eval_id} missing expected behaviors")
        weights = item.get("scoring_weights", {})
        if not isinstance(weights, dict) or not weights:
            errors.append(f"{eval_id} missing scoring weights")
        elif not 0.99 <= sum(float(value) for value in weights.values()) <= 1.01:
            errors.append(f"{eval_id} scoring weights must sum to 1")

    return errors


def build_eval_artifact(
    provider_id: str,
    eval_item: dict[str, Any],
    *,
    observed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a replayable machine-readable eval artifact shell."""

    observed = observed or {}
    raw = json.dumps(
        {
            "provider_id": provider_id,
            "eval_id": eval_item["eval_id"],
            "prompt": eval_item["prompt"],
            "observed": observed,
        },
        sort_keys=True,
    )
    artifact_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return {
        "schema_version": 1,
        "artifact_id": f"grounding_eval:{provider_id}:{eval_item['eval_id']}",
        "provider_id": provider_id,
        "eval_id": eval_item["eval_id"],
        "category": eval_item["category"],
        "requires_grounding": eval_item["requires_grounding"],
        "expected_behaviors": eval_item["expected_behaviors"],
        "observed": observed,
        "scores": {key: None for key in eval_item["scoring_weights"]},
        "pass": None,
        "blockers": [],
        "raw_hash": artifact_hash,
    }


def build_privacy_egress_preflight(
    provider_id: str,
    *,
    redaction_passed: bool,
    payload_refs: list[str] | None = None,
    filter_id: str = "openai_privacy_filter_or_equivalent_local_redaction_candidate",
    path: Path = PROVIDER_REGISTRY,
) -> dict[str, Any]:
    """Build a fail-closed privacy/egress preflight artifact for provider calls."""

    providers = provider_by_id(path)
    if provider_id not in providers:
        raise KeyError(f"unknown provider_id: {provider_id}")

    provider = providers[provider_id]
    payload_refs = payload_refs or []
    required = provider.egress_preflight_required
    passed = (not required) or redaction_passed
    blockers: list[str] = []
    if required and not redaction_passed:
        blockers.append("cloud_route_redaction_not_passed")

    raw = json.dumps(
        {
            "provider_id": provider_id,
            "filter_id": filter_id,
            "payload_refs": payload_refs,
            "redaction_passed": redaction_passed,
            "required": required,
            "passed": passed,
            "blockers": blockers,
        },
        sort_keys=True,
    )
    return {
        "schema_version": 1,
        "artifact_id": f"grounding_egress_preflight:{provider_id}",
        "provider_id": provider_id,
        "filter_id": filter_id,
        "egress_preflight_required": required,
        "redaction_passed": redaction_passed,
        "payload_refs": payload_refs,
        "pass": passed,
        "blockers": blockers,
        "raw_hash": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    }
