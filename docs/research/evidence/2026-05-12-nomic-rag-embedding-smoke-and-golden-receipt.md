---
title: "Nomic RAG Embedding Smoke And Golden Receipt"
date: 2026-05-12
authority_case: REQ-20260512-nomic-embedding-runtime-repair
cc_task: nomic-rag-embedding-smoke-and-golden-receipt
status: receipt
mutation_surface: runtime
---

# Nomic RAG Embedding Smoke And Golden Receipt

This receipt records the post-repair validation for the live Ollama embedding
runtime and the RAG golden-query retrieval path. No Qdrant collection was
reindexed or mutated.

## Runtime Smoke

- `shared.config.validate_embed_dimensions()` passed.
- `shared.config.EMBEDDING_MODEL`: `nomic-embed-cpu`
- `shared.config.EXPECTED_EMBED_DIMENSIONS`: `768`
- Direct batch `/api/embed` probe for `nomic-embed-cpu` returned two vectors
  with dimensions `[768, 768]`.
- `ollama list` showed both `nomic-embed-cpu:latest` and
  `nomic-embed-text-v2-moe:latest` with digest
  `ff9c2f10ef5e3722623a1b396e1e04efc27a93112c83e9b7b7b9ca1d05620965`.

## Golden Query Receipt

Command:

```bash
uv run python scripts/rag_golden_query_eval.py \
  --output reports/rag-golden-query/nomic-rag-embedding-smoke-and-golden-receipt.json
```

Outputs:

- `reports/rag-golden-query/nomic-rag-embedding-smoke-and-golden-receipt.json`
- `reports/rag-golden-query/nomic-rag-embedding-smoke-and-golden-receipt.md`

The generated reports were kept out of Git because raw retrieval hits include
live local source paths and text excerpts; this receipt records the required
output paths and summary metrics.

Summary metrics:

- `query_count`: 20
- `query_error_count`: 0
- `query_error_rate`: 0.0
- `mean_precision_at_5`: 0.05
- `mean_recall_at_k`: 0.025
- `mean_mrr`: 0.05
- `mean_ndcg_at_k`: 0.0766
- `mean_metadata_hit_rate`: 0.6
- `no_hits_rate`: 0.0
- `no_relevant_evidence_rate`: 0.95
- `unique_source_count`: 153
- `source_service_distribution`: `{'drive': 120, 'unknown': 49, 'gdrive': 27, 'git': 4}`

Inventory-excluded follow-up:

```bash
uv run python scripts/rag_golden_query_eval.py \
  --exclude-inventory \
  --output reports/rag-golden-query/nomic-rag-embedding-smoke-and-golden-receipt-exclude-inventory.json
```

Outputs:

- `reports/rag-golden-query/nomic-rag-embedding-smoke-and-golden-receipt-exclude-inventory.json`
- `reports/rag-golden-query/nomic-rag-embedding-smoke-and-golden-receipt-exclude-inventory.md`

The `--exclude-inventory` run also completed with an empty report-level
`errors` list and the same summary metrics. That keeps the blocker on live
collection retrieval quality and metadata filtering, not embedding model
availability.

## Interpretation

The embedding-runtime blocker is cleared for this path: the suite no longer
reports `model 'nomic-embed-cpu' not found`, and the report-level `errors` list
is empty.

RAG is not green. The next evidence-backed blocker is retrieval quality after
the embedding repair: 95% of queries had no relevant evidence and the mean
metadata-hit rate remained 60%. That requires a separate retrieval-quality
repair task rather than being hidden under the model-availability repair.

Recorded follow-up task:
`nomic-rag-post-embed-retrieval-quality-repair`.

## Verification

```bash
uv run pytest tests/scripts/test_rag_golden_query_eval.py -q
uv run pytest tests/test_config.py tests/test_embed_batch.py -q
```
