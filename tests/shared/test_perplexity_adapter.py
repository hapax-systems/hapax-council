"""Tests for the Perplexity grounding adapter."""

from __future__ import annotations

import hashlib

from shared.grounding_adapters.perplexity import (
    GroundingEvidenceEnvelope,
    PerplexityClaimRequest,
    PerplexitySearchParams,
    build_envelope_from_response,
    build_error_envelope,
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
    assert envelope.model_id == "sonar"
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
