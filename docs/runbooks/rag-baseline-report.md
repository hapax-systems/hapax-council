# RAG Baseline Report

Run `scripts/rag_baseline_report.py` before any RAG reindex, embedding-model
change, chunking-policy change, or `documents` collection migration.

The report is read-only against Qdrant. It samples the live `documents`
collection, estimates metadata-stub contamination, summarizes payload schema
keys, source services, extensions, text lengths, token-length estimates, chunk
health, and optional top-N retrieval smoke queries.

Example:

```bash
uv run scripts/rag_baseline_report.py \
  --collection documents \
  --sample-size 1000 \
  --query "token capital empirical evidence" \
  --output reports/rag-baseline
```

If Qdrant is unavailable, the command still exits successfully and writes JSON
and Markdown reports with `qdrant_available: false` and the captured error.
