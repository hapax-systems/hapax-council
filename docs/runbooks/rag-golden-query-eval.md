# RAG Golden Query Evaluation

Use this suite after the baseline report and before claiming RAG repair. It
measures retrieval quality only; answer faithfulness remains a separate review
surface.

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
