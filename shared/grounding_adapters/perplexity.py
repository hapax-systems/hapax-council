"""Perplexity Sonar grounding adapter.

Normalizes Perplexity API responses into the standard 17-field evidence
envelope defined by ``shared.grounding_provider_router.REQUIRED_EVIDENCE_FIELDS``.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

_log = logging.getLogger(__name__)

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


def build_envelope_from_response(
    request: PerplexityClaimRequest,
    response_text: str,
    citation_urls: list[str],
    cost: dict | None = None,
) -> GroundingEvidenceEnvelope:
    """Build a standard evidence envelope from a Perplexity API response."""

    now = datetime.now(UTC).isoformat()
    model_id = _MODEL_ALIAS_TO_ID.get(request.model_alias, request.model_alias)

    raw_hashes = [
        hashlib.sha256(url.encode("utf-8")).hexdigest() for url in citation_urls
    ]
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
