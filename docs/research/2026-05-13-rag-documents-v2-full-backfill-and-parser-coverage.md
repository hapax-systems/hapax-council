# RAG documents_v2 Full Backfill And Parser Coverage Receipt

Date: 2026-05-13

## Claim Status

The `documents_v2` shadow collection now contains a non-destructive
audit-publication backfill of the approved May 2026 research/request/task/source
surface, not only the earlier 22-file golden-evidence seed.

This upgrades the RAG state from "seeded repair case only" to "full approved
shadow-corpus retrieval repair case." It still does not upgrade Token Capital
to an existence proof, an appreciating-token-asset proof, an answer-faithfulness
result, or a downstream contribution result.

## Backfill Run

Command:

```bash
CUDA_VISIBLE_DEVICES="" "$HOME/projects/hapax-council/.venv-ingest/bin/python" \
  scripts/rag_documents_v2_shadow.py reindex \
  --source-profile audit-publication \
  --target-collection documents_v2 \
  --force \
  --omit-selected-files \
  --output /tmp/rag-documents-v2-audit-publication-backfill-20260513T053226Z.json
```

Runtime:

- generated at: `2026-05-13T05:35:28.733352+00:00`
- ingest completed at: `2026-05-13T06:56:30Z`
- processed files: `5126`
- target collection: `documents_v2`
- legacy collection: `documents` was not reindexed or mutated

Final Qdrant counts:

| Collection | Points |
|---|---:|
| `documents` | `253034` |
| `documents_v2` | `15368` |

## Source Manifest

The run used `--source-profile audit-publication`, which intentionally excludes
the raw `~/documents/rag-sources` firehose and includes the approved
audit/publication evidence surface.

Selected source categories:

| Category | Files |
|---|---:|
| `agentgov` | `26` |
| `audit` | `16` |
| `cc_task` | `1604` |
| `exposition` | `6` |
| `foundation` | `16` |
| `handoff` | `5` |
| `lab_journal` | `5` |
| `ledger` | `4` |
| `repo_agents` | `1372` |
| `repo_docs` | `1310` |
| `repo_scripts` | `167` |
| `repo_shared` | `528` |
| `request` | `67` |

Golden-label source coverage before writes:

- expected golden labels: `27`
- covered golden labels: `27`
- expected source-path labels: `18`
- covered source-path labels: `18`

## Parser Coverage

Selected audit-publication manifest:

| Extension | Files | Parser mode |
|---|---:|---|
| `.html` | `1` | plain text fast path |
| `.md` | `3069` | plain text fast path |
| `.py` | `2046` | plain text fast path |
| `.txt` | `10` | plain text fast path |

Docling status for the selected write runtime:

- Docling imports available in `.venv-ingest`: `true`
- selected DOCX/PDF/PPTX files: `0`
- unsupported selected files: `0`
- fail-closed required: `false`

Binary-parser gate evidence for the broader `all` profile:

| Runtime | Selected files | DOCX | PDF | PPTX | Docling available | Unsupported | Fail closed |
|---|---:|---:|---:|---:|---|---:|---|
| main `uv` venv | `182820` | `212` | `159` | `9` | `false` | `380` | `true` |
| `.venv-ingest` | `182820` | `212` | `159` | `9` | `true` | `0` | `false` |

That proves the write path can parse Docling-backed file classes when the
ingest runtime is used, and that the main project venv reports the gap as an
explicit fail-closed condition instead of silently accepting partial coverage.

## Retrieval Comparison

Both golden-query runs used Nomic embeddings and excluded inventory records:

```bash
uv run python scripts/rag_golden_query_eval.py \
  --suite evals/rag/golden_queries.json \
  --collection documents \
  --limit 10 \
  --exclude-inventory \
  --output /tmp/rag-golden-documents-baseline-20260513T065654Z.json

uv run python scripts/rag_golden_query_eval.py \
  --suite evals/rag/golden_queries.json \
  --collection documents_v2 \
  --limit 10 \
  --exclude-inventory \
  --compare /tmp/rag-golden-documents-baseline-20260513T065654Z.json \
  --output /tmp/rag-golden-documents-v2-full-backfill-20260513T065654Z.json
```

| Metric | `documents` | full `documents_v2` | Delta |
|---|---:|---:|---:|
| mean precision@5 | `0.05` | `0.31` | `+0.26` |
| mean recall@k | `0.025` | `0.5417` | `+0.5167` |
| mean MRR | `0.05` | `0.5451` | `+0.4951` |
| mean nDCG@k | `0.0169` | `0.4617` | `+0.4448` |
| mean metadata-hit rate | `0.0` | `0.0` | `0.0` |
| no-hits rate | `0.55` | `0.0` | `-0.55` |
| no-relevant-evidence rate | `0.95` | `0.15` | `-0.8` |
| golden-label utilization | `1/27` (`0.037`) | `17/27` (`0.6296`) | `+0.5926` |
| source-label utilization | `0/18` (`0.0`) | `12/18` (`0.6667`) | `+0.6667` |

Compared with the earlier 22-file seeded repair case, the full backfill is
strictly better than legacy `documents` but weaker than the focused seed on the
golden suite: the seed reached precision@5 `0.43`, recall `0.925`, nDCG
`0.8038`, no-relevant-evidence rate `0.0`, golden-label utilization `18/27`,
and source-label utilization `17/18`.

Interpretation: the full approved corpus fixes coverage and non-destructive
backfill, but broader retrieval competition still needs ranking/source-prior
work before it can support publication-grade answer or contribution claims.

## Artifact Paths

- Backfill manifest:
  `/tmp/rag-documents-v2-audit-publication-backfill-20260513T053226Z.json`
- Audit-publication dry-run report:
  `/tmp/rag-documents-v2-audit-publication-report-20260513T053226Z.json`
- Audit-publication ingest-runtime parser report:
  `/tmp/rag-documents-v2-audit-publication-ingest-venv-report-20260513T053226Z.json`
- All-profile main-venv fail-closed parser report:
  `/tmp/rag-documents-v2-all-profile-main-venv-report-20260513T053226Z.json`
- All-profile ingest-runtime parser report:
  `/tmp/rag-documents-v2-all-profile-ingest-venv-report-20260513T053226Z.json`
- Legacy baseline golden eval:
  `/tmp/rag-golden-documents-baseline-20260513T065654Z.json`
- Full backfill golden eval:
  `/tmp/rag-golden-documents-v2-full-backfill-20260513T065654Z.json`

## Claim Ceiling

Allowed after this receipt:

- `documents_v2` can non-destructively backfill the approved May 2026
  audit-publication corpus.
- The selected manifest has explicit parser coverage and fail-closed binary
  parser accounting.
- Full `documents_v2` substantially improves retrieval over legacy `documents`
  with inventory excluded.
- The full backfill is a better empirical substrate than the legacy collection
  for the next RAG evaluation tasks.

Still forbidden:

- "Hapax proves Token Capital."
- "Tokens are appreciating assets."
- "RAG now proves downstream value creation."
- "Answer faithfulness is solved."
- "Generated-token corpus utilization has been measured."

Those claims remain blocked on grounded answer-faithfulness evaluation,
generated-token corpus denominator work, downstream contribution measurement,
and public-surface claim review.
