"""Cross-encoder reranking for RAG retrieval.

Cost-offload Tier-1 (ISAP ``S5-CAPACITY-ROUTING-COST-OFFLOAD-TIER1``, under
``CASE-CAPACITY-ROUTING-001``). A small MIT BERT cross-encoder
(``cross-encoder/ms-marco-MiniLM-L-6-v2`` by default) re-scores the over-fetched
candidate set before truncation, improving retrieval precision that feeds the
grounding loop. On-corpus eval found it lifts nDCG@10 by +0.17 at 47ms/20-cand;
a 0.6B generative reranker both degraded quality and blew the latency budget.

Two safety properties make this a reversible, held-quality change:

* **Flag-gated, default OFF** (:data:`shared.config.RERANK_ENABLED`). When off,
  :func:`rerank` returns ``points[:top_k]`` in the original cosine order — byte
  identical to the pre-rerank behavior. The flag flips on only after the
  nDCG@10 validation gate passes.
* **Fail-open.** Any error (model unavailable, scoring fault, missing text)
  returns the original cosine order, so retrieval never hard-fails on a
  reranker bug.
"""

from __future__ import annotations

import logging
from typing import Any

from shared import config

logger = logging.getLogger(__name__)

# Lazily-loaded module-level singleton. ``_MODEL_FAILED`` latches a failed load
# so we attempt the (expensive) import/construction at most once per process.
_MODEL: Any = None
_MODEL_FAILED: bool = False


def _get_model() -> Any | None:
    """Return the cross-encoder singleton, or ``None`` if it cannot be loaded."""
    global _MODEL, _MODEL_FAILED
    if _MODEL is not None:
        return _MODEL
    if _MODEL_FAILED:
        return None
    try:
        from sentence_transformers import CrossEncoder

        _MODEL = CrossEncoder(config.RERANK_MODEL)
        return _MODEL
    except Exception:  # noqa: BLE001 — fail-open: torch/model/network unavailable
        logger.warning(
            "rerank: model %r failed to load; falling back to cosine order",
            config.RERANK_MODEL,
            exc_info=True,
        )
        _MODEL_FAILED = True
        return None


def _text_of(point: Any, text_key: str) -> str:
    payload = getattr(point, "payload", None) or {}
    return str(payload.get(text_key, "") or "")


def rerank(query: str, points: list, top_k: int, *, text_key: str = "text") -> list:
    """Re-score ``points`` against ``query`` with a cross-encoder; return top_k.

    Fail-open and flag-gated. Returns ``points[:top_k]`` (original order) when
    reranking is disabled, when no model is available, when no candidate carries
    text, or on any scoring error. Operates on whatever candidate set it is
    given, so callers should apply inventory/metadata filters *before* calling.
    """
    if not points:
        return points
    if not config.RERANK_ENABLED:
        return points[:top_k]
    try:
        model = _get_model()
        if model is None:
            return points[:top_k]
        pairs = [(query, _text_of(p, text_key)) for p in points]
        if not any(text for _, text in pairs):
            return points[:top_k]
        scores = model.predict(pairs)
        order = sorted(range(len(points)), key=lambda i: scores[i], reverse=True)
        return [points[i] for i in order[:top_k]]
    except Exception:  # noqa: BLE001 — fail-open: never break retrieval on a rerank fault
        logger.warning("rerank: scoring failed; falling back to cosine order", exc_info=True)
        return points[:top_k]
