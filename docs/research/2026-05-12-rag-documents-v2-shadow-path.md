# RAG documents_v2 Shadow Path

Status: implementation runbook for `epistemic-rag-documents-v2-shadow-path`

The live `documents` collection remains the default ingest and search target.
Use `documents_v2` only through explicit CLI flags or environment overrides.

## Sequence

1. Capture a read-only baseline:

   ```bash
   uv run python scripts/rag_baseline_report.py --collection documents --query "constitutional memory"
   ```

2. Plan the shadow reindex without writes. Use `audit-publication` for the
   approved audit/request/task/research/code proof surface; use `all` only when
   intentionally inspecting the raw `~/documents/rag-sources` firehose:

   ```bash
   uv run python scripts/rag_documents_v2_shadow.py reindex \
     --source-profile audit-publication \
     --dry-run --report-only \
     --omit-selected-files \
     --output /tmp/rag-documents-v2-audit-publication-report.json
   ```

3. Create the shadow schema from the selected embedding model:

   ```bash
   uv run python scripts/rag_documents_v2_shadow.py ensure-schema --collection documents_v2
   ```

4. Reindex into the shadow collection. For any profile that may include
   DOCX/PDF/PPTX files, run through `.venv-ingest`; that venv carries Docling
   while the main project venv intentionally does not:

   ```bash
   CUDA_VISIBLE_DEVICES="" "$HOME/projects/hapax-council/.venv-ingest/bin/python" \
     scripts/rag_documents_v2_shadow.py reindex \
     --source-profile audit-publication \
     --target-collection documents_v2 \
     --force \
     --omit-selected-files \
     --output /tmp/rag-documents-v2-audit-publication-backfill.json
   ```

5. Compare retrieval side by side:

   ```bash
   uv run python scripts/rag_golden_query_eval.py \
     --suite evals/rag/golden_queries.json \
     --collection documents \
     --limit 10 \
     --exclude-inventory \
     --output /tmp/rag-golden-documents-baseline.json

   uv run python scripts/rag_golden_query_eval.py \
     --suite evals/rag/golden_queries.json \
     --collection documents_v2 \
     --limit 10 \
     --exclude-inventory \
     --compare /tmp/rag-golden-documents-baseline.json \
     --output /tmp/rag-golden-documents-v2-compared.json
   ```

## Safety Notes

- `reindex --dry-run` and `reindex --report-only` do not create collections or
  write Qdrant points.
- `agents.ingest` still defaults to `documents`; systemd watch-only behavior is
  unchanged unless the unit is explicitly configured with `--collection` or
  `HAPAX_RAG_COLLECTION`.
- Non-default collections use collection-scoped dedup keys, so indexing
  `documents_v2` does not inherit the existing `documents` processed-file state.
- `reindex` writes the exact selected manifest to a temporary
  `--source-file-list` for `agents.ingest`; it does not ask ingest to rescan
  broader watch roots.
- Parser coverage is reported for the selected manifest. Writes fail closed
  when Docling-backed file types are selected but Docling imports are not
  available, unless `--allow-parser-gaps` is passed intentionally.
- Metadata-only inventory records are retained as artifacts, but default
  retrieval comparisons should use `--exclude-inventory`.
