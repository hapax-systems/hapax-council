"""Perplexity Sonar grounding adapter.

Normalizes Perplexity API responses into the standard 17-field evidence
envelope defined by ``shared.grounding_provider_router.REQUIRED_EVIDENCE_FIELDS``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

_log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: USD-per-1M-token price table, pinned to Perplexity published pricing as of
#: the 2026-05-15 plan date. Data, not code — update the JSON when pricing
#: changes, never these sources.
PRICING_TABLE_PATH = _REPO_ROOT / "config" / "perplexity-pricing.json"

_REFUSAL_PATTERNS = re.compile(
    r"I cannot find|no results|I'm not sure|I don't have|unable to find|"
    r"could not find|no information available",
    re.IGNORECASE,
)


class PerplexitySearchParams(BaseModel):
    """Search parameters for Perplexity Sonar API calls."""

    domains: list[str] = Field(default_factory=list, max_length=20)
    recency: Literal["hour", "day", "week", "month"] | None = None
    context_size: Literal["low", "medium", "high"] = "medium"
    return_images: bool = False


class PerplexityClaimRequest(BaseModel):
    """Input for a grounding claim via Perplexity."""

    input_claim_request: str
    model_alias: str = "web-scout"
    search_params: PerplexitySearchParams = Field(
        default_factory=PerplexitySearchParams,
    )


class GroundingEvidenceEnvelope(BaseModel):
    """Standard 17-field evidence envelope."""

    provider_id: str = "perplexity_search_or_sonar"
    model_id: str
    tool_id: str = "sonar_api"
    input_claim_request: str
    retrieval_events: list[dict] = Field(default_factory=list)
    source_items: list[dict] = Field(default_factory=list)
    claim_items: list[dict] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    confidence_or_posterior: float = 0.5
    source_quality: str = "none"
    freshness: str = "unfiltered"
    refusal_or_uncertainty: str | None = None
    tool_errors: list[str] = Field(default_factory=list)
    raw_source_hashes: list[str] = Field(default_factory=list)
    retrieved_at: str = ""


_MODEL_ALIAS_TO_ID = {
    "web-scout": "sonar",
    "web-research": "sonar-pro",
    "web-reason": "sonar-reasoning-pro",
    "web-deep": "sonar-deep-research",
}


class PerplexityPricingError(ValueError):
    """The pricing table is missing, malformed, or lacks a model entry."""


class PerplexitySpendMetadata(BaseModel):
    """Per-call token counts and USD cost estimate for a Perplexity route."""

    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    request_id: str | None = None


def load_pricing_table(path: Path = PRICING_TABLE_PATH) -> dict[str, dict[str, float]]:
    """Load the per-model USD/1M-token price table from config."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        models = payload["models"]
        return {
            model_id: {
                "input_usd_per_mtok": float(rates["input_usd_per_mtok"]),
                "output_usd_per_mtok": float(rates["output_usd_per_mtok"]),
            }
            for model_id, rates in models.items()
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise PerplexityPricingError(
            f"invalid Perplexity pricing table at {path}: {exc} — "
            "restore config/perplexity-pricing.json from the design doc's "
            "Model Routes table"
        ) from exc


def build_spend_metadata(
    model_id: str,
    usage: dict,
    request_id: str | None = None,
    pricing_path: Path = PRICING_TABLE_PATH,
) -> PerplexitySpendMetadata:
    """Compute spend metadata for one call from its usage block.

    ``usage`` is the OpenAI-compatible block Perplexity returns
    (``prompt_tokens``/``completion_tokens``/``total_tokens``).
    """

    table = load_pricing_table(pricing_path)
    rates = table.get(model_id)
    if rates is None:
        raise PerplexityPricingError(
            f"no pricing for Perplexity model '{model_id}' — "
            f"add it to config/perplexity-pricing.json (have: {sorted(table)})"
        )

    prompt_tokens = int(usage.get("prompt_tokens", 0))
    completion_tokens = int(usage.get("completion_tokens", 0))
    total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens))

    # Decimal end-to-end so 1000 tokens at $3/1M is exactly 0.003, not a
    # float-accumulation artifact; single float conversion at the boundary.
    cost = (
        Decimal(prompt_tokens) * Decimal(str(rates["input_usd_per_mtok"]))
        + Decimal(completion_tokens) * Decimal(str(rates["output_usd_per_mtok"]))
    ) / Decimal(1_000_000)

    return PerplexitySpendMetadata(
        model=model_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=float(cost),
        request_id=request_id,
    )


def _emit_spend_to_token_ledger(spend: PerplexitySpendMetadata) -> None:
    """Best-effort emission to the shared cost-tracking hook.

    Same idiom as the director loop's LiteLLM call site: cost tracking must
    never break the grounding call, so any ledger failure is logged and
    swallowed.
    """

    try:
        sys.path.insert(0, str(_REPO_ROOT / "scripts"))
        from token_ledger import record_spend

        record_spend(
            f"perplexity:{spend.model}",
            spend.prompt_tokens,
            spend.completion_tokens,
            spend.estimated_cost_usd,
        )
    except Exception:
        _log.warning("token_ledger spend emission failed", exc_info=True)


def build_envelope_from_response(
    request: PerplexityClaimRequest,
    response_text: str,
    citation_urls: list[str],
    cost: dict | None = None,
    usage: dict | None = None,
    request_id: str | None = None,
) -> GroundingEvidenceEnvelope:
    """Build a standard evidence envelope from a Perplexity API response.

    When the response's OpenAI-compatible ``usage`` block is supplied, the
    envelope carries a ``perplexity_spend`` retrieval event with per-call
    token counts and the USD cost estimate from the config price table, and
    the spend is emitted to the shared token ledger.
    """

    now = datetime.now(UTC).isoformat()
    model_id = _MODEL_ALIAS_TO_ID.get(request.model_alias, request.model_alias)

    raw_hashes = [hashlib.sha256(url.encode("utf-8")).hexdigest() for url in citation_urls]
    source_items = [
        {"url": url, "index": i, "hash": h}
        for i, (url, h) in enumerate(zip(citation_urls, raw_hashes, strict=True))
    ]

    has_citations = bool(citation_urls)
    confidence = 0.7 if has_citations else 0.3

    refusal = None
    if _REFUSAL_PATTERNS.search(response_text):
        refusal = "refusal_or_uncertainty_detected"
        confidence = min(confidence, 0.2)

    freshness = "unfiltered"
    if request.search_params.recency:
        freshness = f"recency_{request.search_params.recency}"

    retrieval_events = []
    if cost:
        retrieval_events.append({"type": "perplexity_search", "cost": cost})
    if usage is not None:
        spend = build_spend_metadata(model_id, usage, request_id=request_id)
        retrieval_events.append({"type": "perplexity_spend", "spend": spend.model_dump()})
        _emit_spend_to_token_ledger(spend)

    return GroundingEvidenceEnvelope(
        model_id=model_id,
        input_claim_request=request.input_claim_request,
        retrieval_events=retrieval_events,
        source_items=source_items,
        claim_items=[{"text": response_text[:2000]}],
        citations=citation_urls,
        confidence_or_posterior=confidence,
        source_quality="web_search" if has_citations else "none",
        freshness=freshness,
        refusal_or_uncertainty=refusal,
        tool_errors=[],
        raw_source_hashes=raw_hashes,
        retrieved_at=now,
    )


def build_error_envelope(
    request: PerplexityClaimRequest,
    error: str,
) -> GroundingEvidenceEnvelope:
    """Build an evidence envelope for a failed Perplexity call."""

    return GroundingEvidenceEnvelope(
        model_id=_MODEL_ALIAS_TO_ID.get(request.model_alias, request.model_alias),
        input_claim_request=request.input_claim_request,
        confidence_or_posterior=0.0,
        source_quality="none",
        tool_errors=[error],
        retrieved_at=datetime.now(UTC).isoformat(),
    )
