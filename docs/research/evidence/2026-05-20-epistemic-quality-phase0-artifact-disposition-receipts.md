---
title: "Epistemic Quality Phase 0 Artifact Disposition Receipts"
date: 2026-05-20
authority_case: REQ-20260512-epistemic-quality-infrastructure
cc_task: epistemic-quality-phase0-artifact-disposition-receipts
status: receipt
mutation_surface: vault_docs
authority_level: support_non_authoritative
---

# Epistemic Quality Phase 0 Artifact Disposition Receipts

This receipt index prevents Phase 0 evidence from existing only in `/tmp`,
chat, relay text, or PR comments. It records current canonical paths, privacy
classes, source refs, backlinks, dispositions, freshness rules, authority
ceilings, and hashes for the Phase 0 artifacts that exist now. It also records
the missing/failed predicates that deny downstream authority.

Machine-readable index:
`docs/research/evidence/2026-05-20-epistemic-quality-phase0-artifact-disposition-receipts.json`.

Generated: `2026-05-20T17:24:12Z`.

Parent request:
`vault://Documents/Personal/20-projects/hapax-requests/active/REQ-20260512-epistemic-quality-infrastructure.md`.

## Current Phase 0 Verdict

Phase 0 has not passed.

Exact blockers:

- `strict_label_validation_ok=false`: 10 of 200 required round-one label rows
  are present, and the relabel freeze file is missing.
- `labels_complete=false`: the current validation gate report has
  `valid_round1_count=0` because existing label rows use `id` rather than the
  gate contract's `manifest_id` field, and the remaining required rows are
  absent.
- `scores_complete=false`: no scorer output rows are present for the 200
  manifest records.
- `reliability_gate_passed=false`: no relabel rows are present; the relabel
  count, seven-day delay, per-axis kappa, and overall kappa predicates all
  fail.

The canonical current reports are:

- `vault://Documents/Personal/20-projects/hapax-research/datasets/epistemic-quality/phase0-label-validation-strict-current-v0.json`
- `vault://Documents/Personal/20-projects/hapax-research/datasets/epistemic-quality/phase0-validation-gate-current-v0.json`
- `vault://Documents/Personal/20-projects/hapax-research/datasets/epistemic-quality/phase0-validation-gate-current-v0.md`
- `vault://Documents/Personal/20-projects/hapax-research/datasets/epistemic-quality/phase0-relabel-reliability-report-v0.json`
- `vault://Documents/Personal/20-projects/hapax-research/datasets/epistemic-quality/phase0-relabel-reliability-report-v0.md`

## Consumer Authority Denials

Publication consumers receive no authority from these artifacts for public
claim upgrades, publication-bus release decisions, automated copy acceptance,
or evidence-bound novelty/quality claims. Independent publication hardening
gates remain required even after Phase 0 passes.

Token Capital consumers receive no authority for claim upgrades, downstream
contribution proof, economic value/appreciation claims, or source-coverage
substitution. EQI Phase 0 has not passed and cannot replace RAG/source
coverage, answer-faithfulness, downstream-contribution, privacy, legal, or
publication gates.

## Artifact Records

| Artifact | Disposition | Privacy | Authority ceiling | Hash |
|---|---|---|---|---|
| `phase0-golden-dataset-v0-curated` | `canonical_current_unlabeled_manifest` | `internal_mixed` | `candidate_unlabeled_not_public_authority` | `927f2b75e6f3e887dcebf008ba5e612e73fff8f099fa7c8317f5e532d5cf37c0` |
| `phase0-source-notes-v0` | `canonical_source_curation_receipt` | `internal_mixed` | `source_curation_receipt_only_no_phase0_pass` | `2650b9b67e9fb4bcf42c68199580e5af36daf17fe21da3e1328388ee14772a95` |
| `phase0-source-curation-report-v0` | `canonical_curation_report` | `internal` | `support_non_authoritative_source_curation_receipt` | `81eacd1733f7f8ef1a33bafbed4df2971015ef331b03c8fae1a3d28b52687596` |
| `phase0-human-labels-round1-v0` | `partial_round_one_labels_blocked` | `internal` | `partial_label_receipt_no_phase0_authority` | `86a5fc8bf836d72ca18b16ea488316dc2c6d6c8c2834d3fa5fa28e6c9fd2d842` |
| `phase0-council-labels-round1-v0-tmp` | `intermediate_not_operator_ground_truth` | `internal` | `support_non_authoritative_review_input_only` | `b6ac8edf6f6ba2f021f04e66be4d554539feeea1aab321d951352bcc98998b5f` |
| `phase0-review-queue-round1-v0` | `operator_review_pending` | `internal` | `review_queue_only_no_ground_truth` | `27f44f9e55912d846d348fde9131c533cf08aa9b905fcb45489b849e7dde101f` |
| `phase0-review-queue-operator-review` | `operator_review_packet_pending` | `internal` | `operator_action_packet_only_no_phase0_pass` | `e3d9c1d9ea9178d9a27c2b6328530b84b32e4b6921884f177818a375cd12357e` |
| `phase0-label-validation-strict-current-v0-json` | `canonical_current_fail_closed_label_report` | `internal` | `negative_result_receipt_only_no_phase0_authority` | `a4c513f9bfcba2eb8926d1474d03495fba9be83f62aff800e00c8b40855d0231` |
| `phase0-validation-gate-current-v0-json` | `canonical_current_fail_closed_validation_report` | `internal` | `negative_result_receipt_only_no_phase0_authority` | `9b3b2405bb23135102c2314ba2372080e0243ffe2b4c8c3172111987be4494dc` |
| `phase0-validation-gate-current-v0-md` | `canonical_current_fail_closed_human_report` | `internal` | `human_readable_negative_result_receipt_only` | `d7296371b5fbe286652386518092b7a3bcc2286d023ecca90dcd29c1ebf94497` |
| `phase0-relabel-reliability-report-v0-json` | `canonical_current_fail_closed_reliability_report` | `internal` | `negative_result_receipt_only_no_phase0_authority` | `7ed5f590079b2fae8bdefe1f2f288e3d8f026e6fdf43dfec49fc5ebc8b5158c2` |
| `phase0-relabel-reliability-report-v0-md` | `canonical_current_fail_closed_human_report` | `internal` | `human_readable_negative_result_receipt_only` | `e7568cacc0049cc3f3b1995e57ac5ea861330bed76200d46919cb5db107f0a34` |
| `phase0-scorer-outputs-current-absence` | `missing_scorer_outputs_recorded` | `internal` | `absence_receipt_no_scorer_or_public_authority` | `9b3b2405bb23135102c2314ba2372080e0243ffe2b4c8c3172111987be4494dc` |
| `phase0-human-relabel-labels-current-absence` | `missing_relabel_rows_recorded` | `internal` | `absence_receipt_no_reliability_or_public_authority` | `7ed5f590079b2fae8bdefe1f2f288e3d8f026e6fdf43dfec49fc5ebc8b5158c2` |
| `phase0-labeling-pack-v0-curated` | `canonical_labeling_packet` | `internal` | `operator_labeling_support_only` | `1f32f7051d5173737583b665b71ee20d1324cf6f55f65173a75d6ba4aecc9827` |
| `phase0-operator-labeling-readiness-2026-05-13` | `canonical_operator_readiness_packet` | `internal` | `operator_action_support_only_no_phase0_pass` | `75a343e830c1acdbb257d6bd97a24116d70c2c15e8ceea6e708aa0ac555d7ebc` |

Freshness for every row is hash-based: a record becomes stale when its named
vault artifact, source manifest, labels, scorer outputs, relabel rows, or gate
code changes. Exact stale conditions are captured per row in the JSON index.

## Acceptance Mapping

- Dataset manifest, source curation notes, labels, scorer outputs, validation
  reports, delayed relabel report, and negative results have canonical records
  in the JSON index.
- Each artifact record includes privacy class, source refs, request/task
  backlinks, disposition, freshness, authority ceiling, and hash.
- Current reports expose exact predicates and blockers; this receipt does not
  use `OK` as an authority label.
- The parent request was updated with this artifact index path.
- Publication and Token Capital consumers are explicitly denied authority while
  Phase 0 predicates are missing or failed.
