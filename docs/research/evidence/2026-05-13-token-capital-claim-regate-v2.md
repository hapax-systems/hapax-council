---
title: "Token Capital Claim Re-Gate V2"
date: 2026-05-13
authority_case: REQ-20260513-token-capital-public-surface-regate-v2
status: receipt
mutation_surface: source_docs
---

# Token Capital Claim Re-Gate V2

Generated at: `2026-05-13T00:00:00Z`

## Decision

- Overall decision: `claim_upgrade_denied`
- Claim ceiling: `hypothesis_and_repair_case_only`
- Allowed summary: Nomic availability, documents_v2 repair-case retrieval improvement, denominator measurement infrastructure, and public source-of-truth receipts may be described with their limits.
- Denied summary: Token Capital existence proof, token appreciation, compounding value, publication-grade answer faithfulness, and downstream contribution claims remain unsupported.

## Evidence Artifacts

| Artifact | PR | Role | Present | SHA-256 |
|---|---:|---|---:|---|
| `docs/research/evidence/2026-05-12-nomic-rag-embedding-smoke-and-golden-receipt.md` | #3163 | embedding availability evidence | `True` | `25881e75a281` |
| `docs/research/2026-05-13-rag-documents-v2-full-backfill-and-parser-coverage.md` | #3211 | retrieval substrate evidence | `True` | `247774b030f4` |
| `docs/research/2026-05-13-rag-answer-faithfulness-and-downstream-contribution-eval.md` | #3212 | answer-level evidence | `True` | `75b438537c5e` |
| `docs/research/2026-05-13-token-capital-corpus-utilization-denominator.md` | #3213 | corpus denominator evidence | `True` | `b55ec5b2afe8` |
| `docs/research/evidence/2026-05-13-public-surface-source-of-truth-reconciliation.md` | #3214 | public surface evidence | `True` | `08f09baf6d3d` |

## Claim Classes

| Claim class | Status | Public ceiling |
|---|---|---|
| `nomic_embedding_availability` | `supported` | Nomic embedding availability is repaired: the configured stable alias is available and dimensionality validation passes. |
| `documents_v2_repair` | `bounded_supported` | documents_v2 is a non-destructive approved-corpus repair case with explicit parser coverage accounting. |
| `retrieval_improvement` | `bounded_supported` | Full documents_v2 materially improves golden-query retrieval over legacy documents, while remaining weaker than the focused seed. |
| `corpus_utilization_denominator` | `measurement_infrastructure_only` | The generated/persisted corpus denominator is explicit; indexing, retrieval, answer context, and downstream contribution remain separate numerators. |
| `answer_faithfulness` | `not_upgraded` | Answer-level evaluation is instrumented, but current generated answers are not publication-grade and do not support answer-faithfulness claims. |
| `downstream_contribution` | `not_measured` | Downstream contribution has not been measured; no value or economic contribution claim is supported. |
| `public_source_of_truth` | `supported` | Live public weblog/OMG entries have source-of-truth disposition rows; this is a source receipt, not a Token Capital claim upgrade. |
| `token_capital_existence_proof` | `denied` | Denied. The current evidence supports only a hypothesis and repair-case narrative, not an existence proof. |
| `token_appreciation` | `denied` | Denied. There is no measurement showing generated tokens appreciate as assets. |
| `compounding_value` | `denied` | Denied. Retrieval and answer-context exposure do not prove compounding value. |

## Forbidden Public Claim Patterns

- `token_capital_existence_proof`: `\bexistence[-\s]+proof\b` - Current post-RAG evidence denies existence-proof language.
- `token_appreciation`: `\bappreciat(?:e|ing|ion)\b.*\btoken` - No appreciation metric or asset-value run exists.
- `compounding_value`: `\b(token\s+)?compounding\b|\bcompounding\s+value\b` - Downstream contribution is not measured.
- `answer_faithfulness`: `\banswer[-\s]+faithfulness\s+(?:is\s+)?(?:solved|proven|repaired)\b` - Generated answers are currently weak on the answer suite.
- `downstream_contribution`: `\bdownstream\s+(?:value|contribution)\s+(?:is\s+)?(?:proven|demonstrated|measured)\b` - No downstream contribution ledger has been consumed.

## Gate Predicates

- `all_dependency_receipts_present`: `True`
- `claim_upgrade_allowed`: `False`
- `token_capital_exists_proof_allowed`: `False`
- `answer_faithfulness_upgrade_allowed`: `False`
- `downstream_contribution_upgrade_allowed`: `False`
- `compounding_value_upgrade_allowed`: `False`

## Required Next Evidence

- durable downstream contribution ledger
- materially improved generated-answer support and faithfulness
- ranking/source-prior diagnosis for full documents_v2
- future public claim gate receipt that explicitly permits stronger language
