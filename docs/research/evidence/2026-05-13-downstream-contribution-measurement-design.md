---
title: "Downstream Contribution Measurement Design"
date: 2026-05-13
authority_case: REQ-20260513-token-capital-public-surface-regate-v2
status: design_receipt
mutation_surface: source_docs
---

# Downstream Contribution Measurement Design

Generated at: `2026-05-13T00:00:00Z`

## Decision

- Overall decision: `measurement_design_only_no_claim_upgrade`
- Current ceiling: `downstream_contribution_not_measured`
- Allowed summary: The project may say it has a design for measuring downstream contribution and a candidate artifact stream.
- Denied summary: The project may not say downstream contribution, token appreciation, economic value, or compounding value has been demonstrated.

## Evidence Artifacts

| Artifact | PR | Role | Present | SHA-256 |
|---|---:|---|---:|---|
| `docs/research/2026-05-13-rag-answer-faithfulness-and-downstream-contribution-eval.md` | #3212 | shows existing downstream field is answer-metric ablation only | `True` | `75b438537c5e` |
| `docs/research/2026-05-13-token-capital-corpus-utilization-denominator.md` | #3213 | separates denominator, indexing, retrieval, answer context, and downstream use | `True` | `b55ec5b2afe8` |
| `docs/research/evidence/2026-05-13-token-capital-claim-regate-v2.md` | #3215 | denies downstream contribution and economic claim upgrades | `True` | `5f0705689d9d` |
| `docs/runbooks/public-surface-scrutiny-gate-v2.md` | #3216 | prevents unsupported public claim language | `True` | `cf2fef0494d8` |
| `docs/research/2026-05-12-carrier-dynamics-formalization-track.md` | #3158 | keeps provenance and consent synergies separate from Token Capital proof | `True` | `70aafbfe33d7` |

## Methodological Basis

| Reference | Role |
|---|---|
| [W3C PROV-DM](https://www.w3.org/TR/prov-dm/) | Use entities, activities, agents, derivations, attribution, and primary source relations as the minimum provenance vocabulary. |
| [Rubin 1974 causal effects of treatments](https://www.ets.org/research/policy_research_reports/publications/article/1974/hrbx.html) | Treat contribution as a potential-outcome question: compare observed artifact outcome with a specified no-source-token counterfactual. |
| [Pearl 2009 causal inference overview](https://projecteuclid.org/journals/statistics-surveys/volume-3/issue-none/Causal-inference-in-statistics-An-overview/10.1214/09-SS057.full) | Keep causal assumptions explicit instead of inferring contribution from association, retrieval, or temporal proximity. |
| [MacKinlay 1997 event studies in economics and finance](https://econpapers.repec.org/RePEc:aea:jeclit:v:35:y:1997:i:1:p:13-39) | Use predeclared event and estimation windows for any event-study-style diagnostic; do not treat a window alone as causal proof. |
| [Koh and Liang 2017 influence functions](https://proceedings.mlr.press/v70/koh17a.html) | Reserve influence-style attribution for future model-training influence questions; current RAG evidence should use replay/ablation first. |

## Metric Separation

| Layer | Question | Claim status |
|---|---|---|
| `retrieval_substrate` | Can an approved source be indexed, retrieved, and placed in answer context? | `substrate_only_not_value` |
| `answer_support` | Does a generated or extractive answer faithfully support required claims? | `answer_quality_not_downstream_value` |
| `downstream_contribution` | Did a source token change a later durable artifact or operator decision? | `not_measured_until_ledger_run` |

## Candidate Source Requirements

- Persisted text or code artifact in the approved denominator or evidence corpus.
- Stable path and SHA-256 hash at measurement time.
- Known authority class and claim ceiling.
- Consent/privacy label sufficient for the intended ledger visibility.
- Availability timestamp or merge/publication timestamp.

## Contribution Event Classes

### `artifact_derivation`

A later durable artifact explicitly derives from a source token through citation, path reference, commit reference, or provenance edge.

Minimum evidence:
- source_token_path_or_hash
- downstream_artifact_path_or_hash
- explicit derivation edge or citation
- operator or reviewer acceptance if the artifact is public-facing

Counterfactual: Replay the production step without the source token, or compare against a matched baseline artifact that had no access to the source token.

Negative results:
- explicit citation absent
- artifact not durable
- artifact exists but counterfactual delta is zero or unfavorable

### `operator_decision_support`

An operator-approved decision record cites a source token and changes a choice, priority, acceptance, rejection, or scope boundary.

Minimum evidence:
- decision_record_path
- source_token_path_or_hash
- decision_before_or_available_alternative
- operator-visible acceptance or override state

Counterfactual: Compare with the documented pre-decision state, or run a blinded proposal generation pass without the source token and score the chosen difference.

Negative results:
- operator motive inferred without a decision record
- decision only temporally follows the source token
- decision lacks a documented alternative

### `quality_gate_unblock`

A prior source token enables a deterministic gate, validator, or claim ceiling to pass or fail correctly on a later artifact.

Minimum evidence:
- gate_command
- gate_input_receipt
- source_token_path_or_hash
- observed_gate_outcome
- leave_one_out_gate_outcome

Counterfactual: Run the same gate with the source token or receipt removed, masked, or replaced by the previous baseline receipt.

Negative results:
- gate outcome unchanged under leave-one-out
- gate is nondeterministic or has hidden dependencies
- gate pass relies on unsupported claim language

### `public_surface_revision`

A source token causes public copy to become more accurate, bounded, or source-reconciled without upgrading unsupported Token Capital claims.

Minimum evidence:
- before_copy_hash
- after_copy_hash
- source_token_path_or_hash
- public_surface_gate_result

Counterfactual: Compare against the pre-revision copy and the gate result that would have occurred without the source token's bound or citation.

Negative results:
- copy is unpublished and unreviewed
- copy passes only because denied claims were removed manually without provenance
- revision creates new unsupported claims

### `research_hypothesis_revision`

A source token changes the status of a theory claim by strengthening, weakening, bounding, or falsifying it in a durable research artifact.

Minimum evidence:
- prior_claim_state
- new_claim_state
- source_token_path_or_hash
- reviewed rationale

Counterfactual: Compare against the previous claim state and require the revision rationale to identify why the source token changed the state.

Negative results:
- claim state changes without a cited evidence path
- revision imports Shapley-value or appreciation math without a measured utility
- revision conflates Carrier Dynamics or provenance with economic value

## Eligible Downstream Artifacts

- merged PRs and merge commits
- source-controlled research/evidence receipts
- vault mirrors with source-controlled canonical counterparts
- closed cc-tasks with closure evidence
- operator-authored request state changes
- public copy sources that pass the public-surface gate

## Excluded Signals

- raw retrieval hit
- answer-context exposure without a later artifact
- unpersisted chat output
- model-drafted text with no operator or reviewer acceptance
- temporal proximity without a derivation edge
- engagement, attention, or aesthetic preference without a measured artifact outcome
- private or consent-sensitive content that cannot be logged with approved labels

## Attribution Windows

| Window | Duration | Strength | Requirements |
|---|---|---|---|
| `same_task_or_request` | from task claim to task closure, or from request update to next closure | `strong` | same authority_case; explicit source reference |
| `default_short_window` | 7 days after source token availability | `moderate` | explicit source reference; no incompatible intervening source |
| `extended_bridge_window` | 30 days maximum | `weak_without_bridge` | explicit bridge record; unchanged claim target; reviewer or operator acceptance |

## Negative Result Handling

| Status | Meaning |
|---|---|
| `no_downstream_artifact` | The source token was retrieved or read, but no durable later artifact exists. |
| `no_attribution_edge` | The later artifact has no explicit citation, derivation, or decision record. |
| `counterfactual_no_effect` | Leave-one-out or matched baseline comparison shows no useful delta. |
| `negative_or_harmful_effect` | The source token worsened claim accuracy, gate behavior, or artifact quality. |
| `privacy_or_consent_blocked` | The event cannot be logged without violating consent or disclosure limits. |
| `answer_unfaithful` | The downstream artifact relied on an answer that failed support or faithfulness checks. |

## Privacy And Operator Agency

- No hidden operator surveillance: count explicit artifact and decision records, not inferred motive.
- No non-operator person data unless consent labels and redaction policy allow the record.
- Log hashes, paths, claim classes, and short bounded excerpts only when public-safe.
- Operator veto or override can block event logging without being treated as a negative motive.
- Consent revocation or missing labels produces a fail-closed privacy_or_consent_blocked event.

## Measurement Record Schema

Required fields:
- event_id
- event_class_id
- source_token_path
- source_token_sha256
- downstream_artifact_path
- downstream_artifact_sha256
- authority_case
- attribution_window_id
- provenance_edges
- counterfactual_method
- observed_outcome
- counterfactual_outcome
- delta
- negative_result_status
- privacy_label
- operator_acceptance_state
- claim_upgrade_allowed

Fail-closed defaults:
- `claim_upgrade_allowed`: `False`
- `negative_result_status`: `no_attribution_edge`
- `privacy_label`: `unknown`

## Instrumentable Event Stream

- Status: `identified`
- Stream id: `artifact_provenance_and_gate_receipts_v0`
- Description: A first ledger can be built from existing source-controlled receipts, PR metadata, closed cc-task closure evidence, public-surface gate outputs, and explicit path/hash references. This is an artifact stream, not operator activity surveillance.

Inputs:
- docs/research/evidence/*.json
- docs/research/evidence/*.md
- docs/runbooks/public-surface-scrutiny-gate-v2.md
- $HOME/Documents/Personal/20-projects/hapax-cc-tasks/closed/*.md
- $HOME/Documents/Personal/20-projects/hapax-requests/active/*.md
- GitHub PR numbers and merge commits recorded in task closure evidence

Limits:
- Cannot infer downstream contribution from retrieval logs alone.
- Cannot infer operator motive without an explicit operator-visible decision record.
- Cannot upgrade public claims until a future ledger run and public gate permit it.

## Gate Predicates

- `all_design_evidence_present`: `True`
- `instrumentable_event_stream_identified`: `True`
- `future_ledger_run_receipt_consumed`: `False`
- `future_public_claim_gate_permits_downstream_language`: `False`
- `eligible_positive_events_above_threshold`: `False`
- `privacy_and_operator_agency_passed`: `False`
- `answer_support_passed_when_generation_is_in_path`: `False`
- `claim_upgrade_allowed_now`: `False`

## First Follow-Up Task

- Task id: `downstream-contribution-ledger-v0-instrumentation`
- Title: Implement downstream contribution ledger v0 instrumentation
- WSJF: `16.0` (BV 8, TC 6, RR/OE 8, size 1.4 -> WSJF 15.7, rounded to 16.0)
- Branch: `codex/downstream-contribution-ledger-v0`

Acceptance:
- Ledger schema implements the measurement record fields and fail-closed defaults.
- Validator rejects records without artifact hashes, attribution edge, privacy label, counterfactual method, or negative-result status.
- Read-only ingest covers source receipts, closed cc-tasks, and public-surface gate receipts without scraping private content or inferring operator motive.
- A fixture run records at least one positive, one negative, and one privacy-blocked example using synthetic or existing public-safe fixtures.
- The ledger receipt states that no Token Capital claim upgrade is allowed until a future public claim gate explicitly permits it.
