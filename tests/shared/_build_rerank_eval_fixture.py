"""Offline builder for the RAG-rerank nDCG eval fixture.

Known-item retrieval eval: sample real council `documents` chunks, generate a
question each chunk answers (via the LOCAL appendix-fast route — no provider
spend, per ISAP S5-CAPACITY-ROUTING-COST-OFFLOAD-TIER1), retrieve top-K by
nomic, and record (query, candidates, gold_id, nomic_order). The gold = the
source chunk; rerank's job is to lift it. Run offline against the live fleet;
commits a frozen JSONL the regression test replays without Qdrant/LiteLLM.

Usage: LITELLM_KEY=$(pass show litellm/master-key) CUDA_VISIBLE_DEVICES="" \
       uv run python tests/shared/_build_rerank_eval_fixture.py <out.jsonl>
"""

from __future__ import annotations

import json
import math
import os
import random
import statistics as st
import sys

import requests
from qdrant_client import QdrantClient
from sentence_transformers import CrossEncoder

from shared.config import embed

QDRANT = "http://localhost:6333"
LITELLM = "http://localhost:4000/v1/chat/completions"
GEN_MODEL = "appendix-fast"  # local Command-R — no provider spend
N, TOPK, SEED = 50, 20, 13


def gen_question(key: str, text: str) -> str:
    body = {
        "model": GEN_MODEL,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Write ONE concise natural-language search question that the "
                    "passage below directly answers. Do not quote the passage. "
                    "Output only the question.\n\nPASSAGE:\n" + text[:1500]
                ),
            }
        ],
        "max_tokens": 60,
        "temperature": 0,
    }
    r = requests.post(LITELLM, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=90)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip().splitlines()[0]


def ndcg_at_10(order: list, gold_id) -> float:
    for rank, pid in enumerate(order[:10], 1):
        if pid == gold_id:
            return 1.0 / math.log2(rank + 1)
    return 0.0


def main() -> None:
    out_path = sys.argv[1]
    key = os.environ["LITELLM_KEY"]
    client = QdrantClient(url=QDRANT)
    random.seed(SEED)

    scroll, _ = client.scroll("documents", limit=600, with_payload=True, with_vectors=False)
    pool = [p for p in scroll if len(str(p.payload.get("text", ""))) > 200]
    sample = random.sample(pool, min(N, len(pool)))

    ce = CrossEncoder("tomaarsen/Qwen3-Reranker-0.6B-seq-cls", device="cpu")

    rows, nomic_n, rer_n = [], [], []
    for p in sample:
        try:
            q = gen_question(key, str(p.payload["text"]))
            qv = embed(q, prefix="search_query")
            pts = list(client.query_points("documents", query=qv, limit=TOPK).points)
        except Exception as e:  # noqa: BLE001
            print(f"skip (error): {e}", file=sys.stderr)
            continue
        ids = [pt.id for pt in pts]
        if p.id not in ids:
            continue  # retrieval miss — rerank can't surface a chunk that wasn't retrieved
        pairs = [(q, str(pt.payload.get("text", ""))) for pt in pts]
        scores = ce.predict(pairs)
        rer_order = [
            pts[i].id for i in sorted(range(len(pts)), key=lambda i: scores[i], reverse=True)
        ]
        nomic_n.append(ndcg_at_10(ids, p.id))
        rer_n.append(ndcg_at_10(rer_order, p.id))
        rows.append(
            {
                "query": q,
                "gold_id": str(p.id),
                "nomic_order": [str(i) for i in ids],
                "candidates": [
                    {"id": str(pt.id), "text": str(pt.payload.get("text", ""))[:1200]} for pt in pts
                ],
            }
        )

    with open(out_path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    print(f"sampled={len(sample)} gold_in_top{TOPK}={len(rows)}")
    if rows:
        nm, rm = st.mean(nomic_n), st.mean(rer_n)
        print(f"nomic  nDCG@10 = {nm:.4f}")
        print(f"rerank nDCG@10 = {rm:.4f}")
        print(f"delta          = {rm - nm:+.4f}   (gate: >= +0.05)")


if __name__ == "__main__":
    main()
