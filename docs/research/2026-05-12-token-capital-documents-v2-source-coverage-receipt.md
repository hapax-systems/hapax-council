# Token Capital Documents V2 Source Coverage Receipt

Date: 2026-05-12

## Claim Status

Token Capital is upgraded from "self-falsified by broken retrieval" to
"repair-case result with bounded empirical support." It is still not an
existence proof for token compounding or appreciating token assets.

The narrower supported claim is: a non-destructive `documents_v2` shadow path
can recover audit-critical evidence retrieval when seeded with the May 2026
audit, research-basis, request, cc-task, and code evidence files.

## Runtime Repair

- Restored Ollama model storage by recreating `/store/ollama` as a symlink to
  `/mnt/nas/models/ollama`.
- Verified `nomic-embed-cpu` and `nomic-embed-text-v2-moe` are listed.
- Verified `/api/embed` returns 768-dimensional vectors for `nomic-embed-cpu`.
- Created the non-destructive `documents_v2` Qdrant collection at 768
  dimensions. The existing `documents` collection was not reindexed.

## Source Coverage

`scripts/rag_documents_v2_shadow.py reindex --dry-run --report-only` reported:

- files discovered: `182818`
- golden labels covered by selected source roots: `27/27`
- source-path labels covered by selected source roots: `18/18`
- uncovered labels: `0`

The default shadow roots now include audit, handoff, foundations, lab journals,
ledgers, active requests, active/closed cc-tasks, repo docs, scripts, agents,
shared modules, and `packages/agentgov`.

## Shadow Retrieval Result

Baseline was the current `documents` collection with inventory excluded.
Current was the seeded `documents_v2` collection after a bounded 22-file
golden-evidence backfill.

| Metric | `documents` | `documents_v2` | Delta |
|---|---:|---:|---:|
| mean precision@5 | `0.05` | `0.43` | `+0.38` |
| mean recall@k | `0.025` | `0.925` | `+0.9` |
| mean nDCG@k | `0.0169` | `0.8038` | `+0.7869` |
| mean metadata-hit rate | `0.0` | `0.0` | `0.0` |
| no relevant evidence rate | `0.95` | `0.0` | `-0.95` |
| golden-label utilization | `0/27` | `17/27` | `+0.6296` |
| source-label utilization | `0/18` | `17/18` | `+0.9444` |

Report artifacts were written locally during verification:

- `/tmp/rag-documents-v2-source-coverage-report.json`
- `/tmp/rag-golden-documents-source-coverage-baseline.json`
- `/tmp/rag-golden-documents-v2-golden-sources-compared.json`

## Remaining Limits

- `documents_v2` is seeded, not a complete replacement index.
- Corpus utilization is now explicit and non-zero for the golden suite, but the
  broader generated-token corpus still needs a full denominator beyond the
  audit-golden labels.
- Answer faithfulness remains intentionally unmeasured by this retrieval-only
  suite.
- The main `.venv` still cannot parse DOCX/PDF/PPTX through Docling; text,
  Markdown, HTML, and Python files now use a lightweight fast path.
