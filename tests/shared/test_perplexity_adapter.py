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


# --- Cost tracking / spend metadata -----------------------------------------

#: Perplexity published pricing as of the 2026-05-15 plan date (USD per 1M
#: tokens, in/out), pinned by the design doc's Model Routes table.
_PLAN_DATE_PRICING = {
    "sonar": (1.0, 1.0),
    "sonar-pro": (3.0, 15.0),
    "sonar-reasoning-pro": (2.0, 8.0),
    "sonar-deep-research": (2.0, 8.0),
}


def test_pricing_table_is_config_data_matching_plan_date_pricing():
    """Rates live in a config file (not code) and match published pricing."""

    payload = json.loads(PRICING_TABLE_PATH.read_text(encoding="utf-8"))
    assert PRICING_TABLE_PATH.name == "perplexity-pricing.json"
    assert PRICING_TABLE_PATH.parent.name == "config"
    for model_id, (in_rate, out_rate) in _PLAN_DATE_PRICING.items():
        entry = payload["models"][model_id]
        assert entry["input_usd_per_mtok"] == in_rate
        assert entry["output_usd_per_mtok"] == out_rate

    table = load_pricing_table()
    assert set(table) == set(_PLAN_DATE_PRICING)


def test_spend_metadata_correct_cost_for_known_token_counts():
    """Fixture response with known token counts → exact cost per the table."""

    usage = {"prompt_tokens": 1000, "completion_tokens": 2000, "total_tokens": 3000}
    spend = build_spend_metadata("sonar-pro", usage, request_id="req-fixture-1")

    assert spend.model == "sonar-pro"
    assert spend.prompt_tokens == 1000
    assert spend.completion_tokens == 2000
    assert spend.total_tokens == 3000
    # 1000 * $3/1M + 2000 * $15/1M = 0.003 + 0.030
    assert spend.estimated_cost_usd == 0.033
    assert spend.request_id == "req-fixture-1"


@pytest.mark.parametrize(
    ("model_id", "expected_cost"),
    [
        ("sonar", 0.003),  # 1000*1 + 2000*1 per 1M
        ("sonar-pro", 0.033),  # 1000*3 + 2000*15 per 1M
        ("sonar-reasoning-pro", 0.018),  # 1000*2 + 2000*8 per 1M
        ("sonar-deep-research", 0.018),  # 1000*2 + 2000*8 per 1M
    ],
)
def test_all_four_routes_have_priced_spend(model_id: str, expected_cost: float):
    usage = {"prompt_tokens": 1000, "completion_tokens": 2000}
    spend = build_spend_metadata(model_id, usage)
    assert spend.estimated_cost_usd == expected_cost
    assert spend.total_tokens == 3000  # defaults to prompt + completion


def test_zero_usage_costs_nothing():
    spend = build_spend_metadata("sonar", {})
    assert spend.prompt_tokens == 0
    assert spend.completion_tokens == 0
    assert spend.total_tokens == 0
    assert spend.estimated_cost_usd == 0.0
    assert spend.request_id is None


def test_unpriced_model_raises_actionable_error():
    with pytest.raises(PerplexityPricingError, match="perplexity-pricing.json"):
        build_spend_metadata("sonar-unknown", {"prompt_tokens": 1})


def test_envelope_surfaces_spend_metadata_in_retrieval_events():
    """Each route call's envelope carries the spend metadata object."""

    request = PerplexityClaimRequest(
        input_claim_request="What is stigmergy?",
        model_alias="web-research",
    )
    usage = {"prompt_tokens": 500, "completion_tokens": 100, "total_tokens": 600}

    envelope = build_envelope_from_response(
        request=request,
        response_text="Stigmergy is an indirect coordination mechanism.",
        citation_urls=["https://example.com/1"],
        usage=usage,
        request_id="req-abc-123",
    )

    spend_events = [
        event for event in envelope.retrieval_events if event["type"] == "perplexity_spend"
    ]
    assert len(spend_events) == 1
    spend = spend_events[0]["spend"]
    assert spend["model"] == "sonar-pro"
    assert spend["prompt_tokens"] == 500
    assert spend["completion_tokens"] == 100
    assert spend["total_tokens"] == 600
    # 500 * $3/1M + 100 * $15/1M = 0.0015 + 0.0015
    assert spend["estimated_cost_usd"] == 0.003
    assert spend["request_id"] == "req-abc-123"


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


def test_spend_emitted_via_token_ledger_hook(monkeypatch, tmp_path):
    """Spend metadata reaches the existing cost-tracking hook (token_ledger)."""

    from pathlib import Path

    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    import token_ledger

    monkeypatch.setattr(token_ledger, "LEDGER_FILE", tmp_path / "token-ledger.json")

    request = PerplexityClaimRequest(input_claim_request="test", model_alias="web-scout")
    build_envelope_from_response(
        request=request,
        response_text="Result.",
        citation_urls=["https://example.com"],
        usage={"prompt_tokens": 1000, "completion_tokens": 2000},
    )

    state = token_ledger.get_state()
    assert state["total_tokens"] == 3000
    assert state["total_cost_usd"] == pytest.approx(0.003)
    component = state["components"]["perplexity:sonar"]
    assert component["tokens"] == 3000
    assert component["calls"] == 1
