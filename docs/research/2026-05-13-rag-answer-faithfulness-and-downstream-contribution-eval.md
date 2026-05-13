# RAG Answer Faithfulness And Downstream Contribution Eval

Date: 2026-05-13

## Scope

This receipt records the first answer-level RAG evaluation after the
`documents_v2` full backfill. It deliberately separates retrieval metrics from
answer correctness, answer faithfulness, refusal behavior, and downstream
contribution deltas.

This is not a Token Capital claim upgrade.

## Research Basis

RAGAS and DeepEval both treat answer evaluation as a separate artifact shape
from retriever evaluation: query/user input, retrieved contexts, generated
response, and reference answer are explicit fields. The implementation follows
that contract without adding those dependencies yet; it emits compatible
interchange records for later judge-based review.

Ollama Python current docs show `Client(host=...)` with `client.chat(...)` and
`response.message.content`; the live local-generation mode uses that path with
temperature `0`.

## Source Artifacts

- `scripts/rag_answer_faithfulness_eval.py`
- `evals/rag/answer_faithfulness_v1.json`
- `tests/scripts/test_rag_answer_faithfulness_eval.py`

The companion answer suite has six audit-critical questions and twelve
required claims. Each query carries a reference answer, required claim checks,
forbidden claim checks, expected retrieval sources, and insufficient-evidence
terms.

## Verification Commands

```bash
uv run ruff format scripts/rag_answer_faithfulness_eval.py tests/scripts/test_rag_answer_faithfulness_eval.py
uv run ruff check scripts/rag_answer_faithfulness_eval.py tests/scripts/test_rag_answer_faithfulness_eval.py
uv run pytest tests/scripts/test_rag_answer_faithfulness_eval.py -q
uv run python scripts/rag_answer_faithfulness_eval.py --suite evals/rag/answer_faithfulness_v1.json --include-no-context --collections documents documents_v2 --limit 8 --answer-mode extractive --output /tmp/rag-answer-faithfulness-extractive-20260513T0816Z.json
uv run python scripts/rag_answer_faithfulness_eval.py --suite evals/rag/answer_faithfulness_v1.json --include-no-context --collections documents documents_v2 --limit 6 --answer-mode ollama --generator-model phi4-mini:latest --output /tmp/rag-answer-faithfulness-ollama-phi4-mini-20260513T0816Z.json
```

Unit result: `7 passed`.

## Extractive Evidence Proxy

Report:

- `/tmp/rag-answer-faithfulness-extractive-20260513T0816Z.json`
- `/tmp/rag-answer-faithfulness-extractive-20260513T0816Z.md`

| Variant | Precision@5 | Recall@k | nDCG@k | No Relevant | Label Utilization | Required Recall | Supported Claim Rate | Faithfulness | Refusal Hit Rate | Forbidden Hits |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `no_context` | 0.0 | 0.0 | 0.0 | 1.0 | 0/12 | 0.0 | 0.0 | null | 1.0 | 0 |
| `documents` | 0.1667 | 0.0833 | 0.0562 | 0.8333 | 1/12 | 0.25 | 0.0 | 0.0 | 0.4 | 1 |
| `documents_v2` | 0.5 | 0.6111 | 0.4387 | 0.0 | 7/12 | 0.75 | 0.5 | 0.5833 | null | 1 |

Extractive `documents_v2` improves supported-claim contribution over both
`no_context` and legacy `documents`, but it still fails half of the required
claim support checks and includes one forbidden-claim hit because raw retrieved
evidence can contain disputed claim language. This is useful diagnostic
evidence, not a safe public answer generator.

## Local Generator Evidence

Report:

- `/tmp/rag-answer-faithfulness-ollama-phi4-mini-20260513T0816Z.json`
- `/tmp/rag-answer-faithfulness-ollama-phi4-mini-20260513T0816Z.md`

| Variant | Precision@5 | Recall@k | nDCG@k | No Relevant | Label Utilization | Required Recall | Supported Claim Rate | Faithfulness | Refusal Hit Rate | Forbidden Hits |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `no_context` | 0.0 | 0.0 | 0.0 | 1.0 | 0/12 | 0.0 | 0.0 | null | 1.0 | 0 |
| `documents` | 0.1667 | 0.0833 | 0.0562 | 0.8333 | 1/12 | 0.0 | 0.0 | null | 1.0 | 0 |
| `documents_v2` | 0.5 | 0.6111 | 0.4387 | 0.0 | 7/12 | 0.0833 | 0.0 | 0.0 | null | 0 |

The local generator properly refused no-context and weak legacy-context cases,
but `documents_v2` did not yet produce grounded answers that satisfy the
required-claim support checks. It answered part of the Shapley repair query and
refused or under-specified several others.

A `qwen3:4b` trial was rejected as evidence because the model spent the token
budget in hidden/thinking content and returned empty visible answer strings.
The harness now reports empty model outputs as per-query errors.

## Claim Ceiling

Token Capital remains below existence-proof level.

Allowed language after this task:

- `documents_v2` improves answer-evidence substrate quality over legacy
  `documents` on the six-question answer suite.
- The extractive proxy shows partial supported-claim contribution.
- The local generator path is instrumented but not yet producing reliable
  grounded answers.

Forbidden language after this task:

- Hapax proves token compounding.
- Token Capital has publication-grade answer faithfulness.
- The RAG repair is complete.
- Downstream contribution has been demonstrated for generated-token capital
  claims.

## Follow-Up Queue

- Tune the local answer prompt or generator contract only after preserving
  this negative/partial baseline.
- Diagnose `documents_v2` ranking/source-prior failures on the unsupported
  answer claims.
- Complete the generated-token corpus-utilization denominator before any
  Token Capital claim re-gate.
- Feed public-surface source-of-truth reconciliation with this claim ceiling.
