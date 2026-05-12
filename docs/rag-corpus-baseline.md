# RAG Corpus Baseline Harness

Run the read-only baseline harness before any RAG corpus reindex, embedding model change,
chunking change, or `documents_v2` migration.

```bash
uv run python scripts/rag_corpus_baseline.py \
  --collection documents \
  --sample-size 500 \
  --output-path reports/rag-corpus-baseline/documents-baseline
```

The harness samples Qdrant payloads without mutating the collection and emits both
JSON and Markdown reports. Use `--query-list path/to/queries.txt` to add a small
top-N search smoke pass to the same report.
