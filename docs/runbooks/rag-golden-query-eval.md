# RAG Golden Query Evaluation

Use this suite after the baseline report and before claiming RAG repair. It
measures retrieval quality only; answer faithfulness remains a separate review
surface.

Run the local embedding guardrail first when checking the runtime directly:

```bash
uv run python scripts/nomic_embedding_health_check.py --pretty
```

`scripts/rag_golden_query_eval.py` runs the same guardrail by default before it
queries Qdrant. The guardrail verifies that Ollama's API is reachable, that the
configured `nomic-embed-cpu` alias and `nomic-embed-text-v2-moe` base model are
listed, and that `/api/embed` returns a 768-dimensional vector. It does not call
cloud services and does not mutate Qdrant.

```bash
uv run python scripts/rag_golden_query_eval.py \
  --suite evals/rag/golden_queries.json \
  --collection documents \
  --limit 10 \
  --output reports/rag-golden-query/latest.json
```

To evaluate the post-gate default behavior, exclude inventory/metadata-only
records that carry `retrieval_eligible: false`:

```bash
uv run python scripts/rag_golden_query_eval.py --exclude-inventory
```

`--exclude-inventory` also applies source-side post-filtering for legacy
Google Drive `.meta` stubs and Drive-link metadata records that predate
`retrieval_eligible: false`. If metadata-hit rate drops but Precision/Recall do
not improve, treat that as a source coverage or reindex blocker, not as an
embedding-runtime failure.

The report emits JSON and Markdown. It includes Precision@5, Recall@k, MRR,
nDCG@k, metadata-hit rate, no-hit rate, no-relevant-evidence rate, and corpus
utilization counts. Use `--compare previous-report.json` to produce before/after
deltas for design-science writeups.

## Embedding Guardrail Failure Modes

- `storage_inaccessible`: Ollama responds, but its model storage path or mount
  is inaccessible. Repair the storage mount or permissions, restart Ollama, and
  rerun the guardrail.
- `base_model_absent`: `nomic-embed-text-v2-moe` is not listed. Pull it with
  `ollama pull nomic-embed-text-v2-moe`.
- `alias_absent`: `nomic-embed-cpu` is not listed. Recreate it with
  `ollama cp nomic-embed-text-v2-moe nomic-embed-cpu`.
- `wrong_dimension`: `/api/embed` returned a vector size other than 768. Restore
  the configured Nomic alias before any RAG evaluation, publication, or reindex
  work continues.
- `api_unavailable`: `/api/tags` or `/api/embed` cannot be reached. Start or
  repair the local Ollama service, then rerun the guardrail.
