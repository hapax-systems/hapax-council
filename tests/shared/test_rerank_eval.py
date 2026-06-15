"""On-corpus nDCG@10 gate for the RAG reranker (opt-in, real-torch only).

Replays a frozen fixture of real council `documents` queries (built offline via
`_build_rerank_eval_fixture.py`) through the actual `shared.rerank.rerank()`
path and asserts the configured cross-encoder lifts single-gold nDCG@10 by at
least +0.05 over nomic — the held-quality gate for flipping `RERANK_ENABLED` on.

Opt-in (`HAPAX_RERANK_EVAL=1`) AND requires a REAL torch: the council pytest
harness mocks torch, so this skips there. Validated result (appendix 5060 Ti,
2026-06-13, gold-in-top-20 subset n=10): ms-marco-MiniLM-L-6-v2 → nDCG@10 +0.168
at 47ms/20-cand; bge-reranker-base → +0.190 at 221ms; the original
Qwen3-Reranker-0.6B pick → -0.417 at 1219ms (refuted). The metric is single-gold
known-item (a deliberately strict lower bound).
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "rerank_eval.jsonl"

pytestmark = pytest.mark.skipif(
    os.environ.get("HAPAX_RERANK_EVAL") != "1",
    reason="set HAPAX_RERANK_EVAL=1 (with the rerank extra, real torch) to run the on-corpus gate",
)


class _Pt:
    def __init__(self, pid: str, text: str) -> None:
        self.id = pid
        self.payload = {"text": text}


def _ndcg_at_10(order: list[str], gold: str) -> float:
    for rank, pid in enumerate(order[:10], 1):
        if pid == gold:
            return 1.0 / math.log2(rank + 1)
    return 0.0


def _require_real_torch():
    try:
        import torch
    except ImportError:
        pytest.skip("torch unavailable")
    if not isinstance(getattr(torch, "__version__", None), str):
        pytest.skip("torch is mocked in this test env; run the gate where torch is real")
    if torch.__spec__ is None:  # pytest can null it → transformers' find_spec("torch") would raise
        import importlib.machinery

        torch.__spec__ = importlib.machinery.ModuleSpec(
            "torch", getattr(torch, "__loader__", None), origin=getattr(torch, "__file__", None)
        )


def test_rerank_lifts_ndcg_on_council_corpus() -> None:
    _require_real_torch()
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        pytest.skip("rerank extra not installed")

    # import after the torch/deps guards so module import never breaks collection
    if "shared.rerank" in sys.modules:
        rerank_mod = sys.modules["shared.rerank"]
    else:
        from shared import rerank as rerank_mod
    rerank = rerank_mod.rerank

    rows = [json.loads(ln) for ln in FIXTURE.read_text().splitlines() if ln.strip()]
    assert rows, "empty eval fixture"
    nomic, reranked = [], []
    for r in rows:
        pts = [_Pt(c["id"], c["text"]) for c in r["candidates"]]
        with patch.object(rerank_mod.config, "RERANK_ENABLED", True):
            out = rerank(r["query"], pts, 20)
        nomic.append(_ndcg_at_10(r["nomic_order"], r["gold_id"]))
        reranked.append(_ndcg_at_10([p.id for p in out], r["gold_id"]))
    mean_nomic = sum(nomic) / len(nomic)
    mean_rer = sum(reranked) / len(reranked)
    assert mean_rer >= mean_nomic + 0.05, (
        f"rerank nDCG@10 {mean_rer:.3f} did not beat nomic {mean_nomic:.3f} by >=0.05 "
        f"(model={rerank_mod.config.RERANK_MODEL})"
    )
