# Nomic RAG Post-Embedding Retrieval Quality Repair

Generated: `2026-05-12T17:41:04Z`

Scope: source-side retrieval filtering and audit receipt only. No destructive
reindexing or Qdrant mutation was performed.

## Commands

- Before default: `uv run python scripts/rag_golden_query_eval.py --suite evals/rag/golden_queries.json --collection documents --limit 10 --output /tmp/nomic-rag-before-default.json`
- Before inventory-excluded: `uv run python scripts/rag_golden_query_eval.py --suite evals/rag/golden_queries.json --collection documents --limit 10 --exclude-inventory --output /tmp/nomic-rag-before-exclude-inventory.json`
- After default: `uv run python scripts/rag_golden_query_eval.py --suite evals/rag/golden_queries.json --collection documents --limit 10 --output /tmp/nomic-rag-after-default.json`
- After inventory-excluded: `uv run python scripts/rag_golden_query_eval.py --suite evals/rag/golden_queries.json --collection documents --limit 10 --exclude-inventory --compare /tmp/nomic-rag-before-default.json --output /tmp/nomic-rag-after-exclude-inventory.json`

## Summary Metrics

| Run | Precision@5 | Recall@k | MRR | nDCG@k | Metadata-hit rate | No-hit rate | No-relevant-evidence rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Before default | 0.05 | 0.025 | 0.05 | 0.0766 | 0.6 | 0.0 | 0.95 |
| Before `--exclude-inventory` | 0.05 | 0.025 | 0.05 | 0.0766 | 0.6 | 0.0 | 0.95 |
| After default | 0.05 | 0.025 | 0.05 | 0.0766 | 0.6 | 0.0 | 0.95 |
| After `--exclude-inventory` | 0.05 | 0.025 | 0.05 | 0.0766 | 0.0 | 0.55 | 0.95 |

`--exclude-inventory` now removes legacy Google Drive `.meta` stubs and
Drive-link metadata records that predate `retrieval_eligible: false`. The
metadata-hit rate dropped from `0.6` to `0.0`.

The relevance metrics did not improve. Filtering is sufficient to remove the
metadata contamination from the retrieved set, but it is not sufficient to make
the current `documents` collection answer the golden suite.

## Source Coverage Scan

Read-only scan command:

```bash
uv run python - <<'PY'
import json
from collections import defaultdict
from pathlib import Path
from qdrant_client import QdrantClient

suite = json.loads(Path("evals/rag/golden_queries.json").read_text())
source_needles = sorted({
    str(label["source_contains"]).lower()
    for q in suite["queries"]
    for label in q.get("expected_sources", [])
    if "source_contains" in label
})
client = QdrantClient(url="http://localhost:6333")
offset = None
scanned = 0
source_hits = defaultdict(int)
while True:
    points, offset = client.scroll(
        collection_name="documents",
        limit=2048,
        offset=offset,
        with_payload=["source", "text"],
        with_vectors=False,
    )
    if not points:
        break
    scanned += len(points)
    for point in points:
        source = str((point.payload or {}).get("source", "")).lower()
        for needle in source_needles:
            if needle in source:
                source_hits[needle] += 1
    if offset is None:
        break
print("scanned", scanned)
for needle in source_needles:
    print(f"{needle}\t{source_hits[needle]}")
PY
```

Result: `253034` points scanned. Every `source_contains` label in
`evals/rag/golden_queries.json` had `0` source matches in the current
`documents` collection, including the audit/task sources:

- `2026-05-12-full-corpus-hardening-audit`
- `2026-05-12-epistemic-audit-handoff`
- `2026-05-12-epistemic-audit-realignment`
- `epistemic-rag-baseline-harness`
- `epistemic-rag-golden-query-suite`
- `epistemic-rag-metadata-quality-gates`
- `epistemic-rag-documents-v2-shadow-path`

## Blocker

The remaining retrieval-quality failure is source coverage, not embedding
availability and not only metadata filtering. The current `documents`
collection does not contain the source paths named by the golden labels, so a
non-destructive ingest/reindex path, preferably the governed `documents_v2`
shadow path, is required before these golden queries can become green.
