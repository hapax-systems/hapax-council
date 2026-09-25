"""Tests for the Perplexity grounding adapter."""

from __future__ import annotations

import hashlib
import json

import pytest

from shared.grounding_adapters.perplexity import (
    PRICING_TABLE_PATH,
    GroundingEvidenceEnvelope,
    PerplexityClaimRequest,
    PerplexityPricingError,
    PerplexitySearchParams,
    PerplexitySpendMetadata,
    build_envelope_from_response,
    build_error_envelope,
    build_spend_metadata,
    load_pricing_table,
)
from shared.grounding_provider_router import REQUIRED_EVIDENCE_FIELDS


def test_successful_grounding_produces_valid_envelope():
    request = PerplexityClaimRequest(input_claim_request="What is stigmergy?")
    citations = ["https://example.com/1", "https://example.com/2"]

    envelope = build_envelope_from_response(
        request=request,
        response_text="Stigmergy is an indirect coordination mechanism.",
        citation_urls=citations,
    )

    envelope_fields = set(GroundingEvidenceEnvelope.model_fields.keys())
    assert REQUIRED_EVIDENCE_FIELDS.issubset(envelope_fields)
    assert envelope.provider_id == "perplexity_search_or_sonar"
    assert envelope.model_id == "web-scout"
    assert not envelope.model_id.startswith("sonar")
    assert len(envelope.citations) == 2
    assert len(envelope.source_items) == 2
    assert envelope.confidence_or_posterior == 0.7
    assert envelope.source_quality == "web_search"


def test_empty_citations_produces_low_confidence():
    request = PerplexityClaimRequest(input_claim_request="obscure query")
    envelope = build_envelope_from_response(
        request=request,
        response_text="I cannot find information about this topic.",
        citation_urls=[],
    )

    assert envelope.confidence_or_posterior <= 0.3
    assert envelope.source_quality == "none"
    assert envelope.refusal_or_uncertainty is not None


def test_rate_limit_error_captured_in_tool_errors():
    request = PerplexityClaimRequest(input_claim_request="test")
    envelope = build_error_envelope(request=request, error="429 rate limit exceeded")

    assert len(envelope.tool_errors) == 1
    assert "429" in envelope.tool_errors[0]
    assert envelope.confidence_or_posterior == 0.0


def test_auth_failure_captured_in_tool_errors():
    request = PerplexityClaimRequest(input_claim_request="test")
    envelope = build_error_envelope(request=request, error="401 Invalid API key")

    assert len(envelope.tool_errors) == 1
    assert "401" in envelope.tool_errors[0]


def test_domain_filter_in_search_params():
    params = PerplexitySearchParams(domains=["arxiv.org", "dl.acm.org"])
    request = PerplexityClaimRequest(
        input_claim_request="test",
        search_params=params,
    )
    assert request.search_params.domains == ["arxiv.org", "dl.acm.org"]


def test_recency_filter_maps_to_freshness():
    params = PerplexitySearchParams(recency="week")
    request = PerplexityClaimRequest(
        input_claim_request="recent events",
        search_params=params,
    )
    envelope = build_envelope_from_response(
        request=request,
        response_text="Recent result.",
        citation_urls=["https://example.com"],
    )
    assert envelope.freshness == "recency_week"


def test_raw_source_hashes_are_sha256_of_urls():
    urls = ["https://example.com/page1", "https://example.com/page2"]
    expected = [hashlib.sha256(u.encode("utf-8")).hexdigest() for u in urls]

    request = PerplexityClaimRequest(input_claim_request="test")
    envelope = build_envelope_from_response(
        request=request,
        response_text="Result.",
        citation_urls=urls,
    )
    assert envelope.raw_source_hashes == expected


def test_retrieved_at_is_iso8601():
    request = PerplexityClaimRequest(input_claim_request="test")
    envelope = build_envelope_from_response(
        request=request,
        response_text="Result.",
        citation_urls=["https://example.com"],
    )
    assert "T" in envelope.retrieved_at
    assert envelope.retrieved_at.endswith("+00:00")


# --- Cost tracking / spend metadata -----------------------------------------

_RETIRED_SONAR_MODELS = (
    "sonar",
    "sonar-pro",
    "sonar-reasoning-pro",
    "sonar-deep-research",
)


def test_pricing_table_has_no_sonar_models():
    """Sonar Chat Completions prices are removed. The file still parses."""

    payload = json.loads(PRICING_TABLE_PATH.read_text(encoding="utf-8"))
    assert PRICING_TABLE_PATH.name == "perplexity-pricing.json"
    assert PRICING_TABLE_PATH.parent.name == "config"
    assert payload["models"] == {}
    assert "perplexity-api-integration-design" not in str(payload["source_doc"])
    table = load_pricing_table()
    assert table == {}
    for model_id in _RETIRED_SONAR_MODELS:
        assert model_id not in table


@pytest.mark.parametrize("model_id", _RETIRED_SONAR_MODELS)
def test_retired_sonar_models_are_unpriced(model_id: str):
    usage = {"prompt_tokens": 1000, "completion_tokens": 2000}
    with pytest.raises(PerplexityPricingError, match="no pricing"):
        build_spend_metadata(model_id, usage)


def test_zero_usage_on_retired_sonar_is_unpriced():
    with pytest.raises(PerplexityPricingError, match="no pricing"):
        build_spend_metadata("sonar", {})


def test_unpriced_model_raises_actionable_error():
    with pytest.raises(PerplexityPricingError, match="perplexity-pricing.json"):
        build_spend_metadata("sonar-unknown", {"prompt_tokens": 1})


def test_retired_alias_with_usage_does_not_price_sonar():
    """A retired alias is not rewritten onto a Sonar model id, and is unpriced."""

    request = PerplexityClaimRequest(
        input_claim_request="What is stigmergy?",
        model_alias="web-research",
    )
    with pytest.raises(PerplexityPricingError, match="no pricing"):
        build_envelope_from_response(
            request=request,
            response_text="Stigmergy is an indirect coordination mechanism.",
            citation_urls=["https://example.com/1"],
            usage={"prompt_tokens": 500, "completion_tokens": 100, "total_tokens": 600},
            request_id="req-abc-123",
        )


def test_envelope_without_usage_has_no_spend_event():
    """No-usage calls (and the legacy cost= path) are unchanged — regression."""

    request = PerplexityClaimRequest(input_claim_request="test")
    envelope = build_envelope_from_response(
        request=request,
        response_text="Result.",
        citation_urls=[],
        cost={"total_cost": 0.01},
    )
    types = [event["type"] for event in envelope.retrieval_events]
    assert types == ["perplexity_search"]
    assert envelope.retrieval_events[0]["cost"] == {"total_cost": 0.01}


def test_spend_metadata_model_dump_has_required_fields():
    spend = PerplexitySpendMetadata(model="sonar")
    dumped = spend.model_dump()
    for field in (
        "model",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "estimated_cost_usd",
    ):
        assert field in dumped


def test_retired_alias_does_not_emit_sonar_spend(monkeypatch, tmp_path):
    """Unpriced Sonar aliases raise before the token ledger is written."""

    from pathlib import Path

    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    import token_ledger

    ledger_path = tmp_path / "token-ledger.json"
    monkeypatch.setattr(token_ledger, "LEDGER_FILE", ledger_path)

    request = PerplexityClaimRequest(input_claim_request="test", model_alias="web-scout")
    with pytest.raises(PerplexityPricingError, match="no pricing"):
        build_envelope_from_response(
            request=request,
            response_text="Result.",
            citation_urls=["https://example.com"],
            usage={"prompt_tokens": 1000, "completion_tokens": 2000},
        )
    assert not ledger_path.exists()
