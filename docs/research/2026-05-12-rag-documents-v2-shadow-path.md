# RAG documents_v2 Shadow Path

Status: implementation runbook for `epistemic-rag-documents-v2-shadow-path`

The live `documents` collection remains the default ingest and search target.
Use `documents_v2` only through explicit CLI flags or environment overrides.

## Sequence

1. Capture a read-only baseline:

   ```bash
   uv run python scripts/rag_baseline_report.py --collection documents --query "constitutional memory"
   ```

2. Plan the shadow reindex without writes:

   ```bash
   uv run python scripts/rag_documents_v2_shadow.py reindex --dry-run --max-files 25
   ```

3. Create the shadow schema from the selected embedding model:

   ```bash
   uv run python scripts/rag_documents_v2_shadow.py ensure-schema --collection documents_v2
   ```

4. Reindex into the shadow collection:

   ```bash
   uv run python scripts/rag_documents_v2_shadow.py reindex --target-collection documents_v2 --max-files 100
   ```

5. Compare retrieval side by side:

   ```bash
   uv run python scripts/rag_documents_v2_shadow.py compare --query "constitutional memory"
   ```

## Safety Notes

- `reindex --dry-run` and `reindex --report-only` do not create collections or
  write Qdrant points.
- `agents.ingest` still defaults to `documents`; systemd watch-only behavior is
  unchanged unless the unit is explicitly configured with `--collection` or
  `HAPAX_RAG_COLLECTION`.
- Non-default collections use collection-scoped dedup keys, so indexing
  `documents_v2` does not inherit the existing `documents` processed-file state.
