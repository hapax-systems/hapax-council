# Token Capital Corpus Utilization Denominator

Date: 2026-05-13

## Scope

This receipt defines the generated/persisted token-corpus denominator used by
Token Capital remediation after the full `documents_v2` backfill and the
answer-faithfulness evaluation. It separates:

- denominator membership;
- Qdrant indexing;
- evaluation-time retrieval;
- answer-context use; and
- downstream contribution.

None of these are dollar value, appreciation, or proof of token compounding.

## Source Artifacts

- `scripts/token_capital_corpus_utilization.py`
- `tests/scripts/test_token_capital_corpus_utilization.py`

The denominator tool reuses the `audit-publication` source profile from
`scripts/rag_documents_v2_shadow.py`, which is the same approved source
universe used by the non-destructive `documents_v2` backfill.

## Denominator Definition

Included:

- generated or operator-authored persisted text in the approved
  `audit-publication` evidence profile;
- extensions: `.html`, `.md`, `.py`, `.txt`;
- artifact classes: research audits, foundations/lab journals/ledgers,
  handoffs, exposition drafts, requests, cc-tasks, repo docs, repo scripts,
  agents/shared code, and `agentgov`.

Excluded:

- binary/parser-dependent files until extracted text is available to this
  denominator tool;
- empty/unreadable text files;
- metadata-only inventory records;
- retrieval-ineligible records;
- metadata sidecars.

Token estimate:

- `ceil(characters / 4)`, explicitly approximate and reproducible.

## Verification Commands

```bash
uv run ruff format scripts/token_capital_corpus_utilization.py tests/scripts/test_token_capital_corpus_utilization.py
uv run ruff check scripts/token_capital_corpus_utilization.py tests/scripts/test_token_capital_corpus_utilization.py
uv run pytest tests/scripts/test_token_capital_corpus_utilization.py -q
uv run python scripts/token_capital_corpus_utilization.py --source-profile audit-publication --collection documents_v2 --eval-report /tmp/rag-golden-documents-v2-full-backfill-20260513T065654Z.json --eval-report /tmp/rag-answer-faithfulness-extractive-20260513T0816Z.json --eval-report /tmp/rag-answer-faithfulness-ollama-phi4-mini-20260513T0816Z.json --output /tmp/token-capital-utilization-denominator-20260513T0918Z.json
```

Unit result: `5 passed`.

## Live Report

Report:

- `/tmp/token-capital-utilization-denominator-20260513T0918Z.json`
- `/tmp/token-capital-utilization-denominator-20260513T0918Z.md`

### Denominator

| Measure | Value |
|---|---:|
| Files discovered | 5,134 |
| Files in denominator | 5,117 |
| Files excluded | 17 |
| Characters in denominator | 51,735,225 |
| Words in denominator | 5,664,884 |
| Estimated tokens in denominator | 12,935,712 |

### Artifact Classes

| Artifact class | Files | Estimated tokens |
|---|---:|---:|
| implementation_docs | 1,312 | 5,873,804 |
| implementation_substrate | 2,079 | 5,220,327 |
| research_audit | 16 | 44,770 |
| research_basis | 25 | 209,811 |
| research_coordination | 5 | 10,900 |
| research_publication_draft | 6 | 13,521 |
| work_state | 1,674 | 1,562,579 |

### Utilization Numerators

| Numerator | Files | File rate | Estimated tokens | Interpretation |
|---|---:|---:|---:|---|
| Indexed in `documents_v2` | 5,051 / 5,117 | 0.9871 | 12,619,035 | Search substrate coverage, not utilization proof. |
| Retrieved in eval reports | 97 / 5,117 | 0.0190 | 457,467 | Evidence surfaced during current golden/answer evaluations. |
| Used as answer context | 22 / 5,117 | 0.0043 | 77,809 | Evidence passed into answer artifacts. |
| Downstream contribution | not measured | n/a | n/a | No durable action/artifact influence ledger consumed. |

Audit-golden label utilization from the full backfill remains `17/27`
(`0.6296`). That is much higher than whole-corpus retrieved-file utilization
because it measures expected audit labels, not the generated-token corpus
denominator.

## Claim Ceiling

Allowed language:

- The approved text denominator is now explicit and reproducible.
- `documents_v2` indexes nearly all denominator files by source path.
- Current evaluation retrieval touches only a small fraction of the denominator.
- Current answer-context use is smaller still.

Forbidden language:

- Token Capital has demonstrated token appreciation.
- Whole-corpus utilization proves compounding.
- Retrieval presence equals downstream value.
- Answer-context use equals economic contribution.

The result remains measurement infrastructure. Token Capital stays a hypothesis
and repair-case narrative until a durable downstream contribution ledger exists
and answer faithfulness improves materially.
