# 2026-05-07 Segment Prep Full-System Audit

Status: partial implementation complete; prep remains `research_only`

Scope: all systems that research, compose, validate, review, select, publish,
load, restart, or document Hapax livestream segment prep.

Design rubric:

- Forms are generated; authority is gated.
- Generated authority is only a hypothesis until bound by source, script,
  contract, release, and readback receipts.
- Resident Command-R only; no Qwen, fallback, unload, or model swap.
- No expert-rule form authority.
- Autonomous source-following before content confidence; no expert micro-rule
  research choreography.
- No-candidate/refusal/no-release are valid diagnostic outcomes.
- Hard gates: provenance, rights/privacy/consent, `prior_only`, selected release,
  runtime readback, and non-anthropomorphic register.
- Craft standards are calibration surfaces, not hidden release authority.

## Completion Findings

Completed enough to preserve:

- Machine-readable authority gate now blocks generation, runtime pool loading,
  selected-manifest writing, systemd service execution, batch prep, and RTE
  restart paths.
- Live authority state is set to `research_only`.
- No-candidate prep runs write diagnostic-only outcome dossiers and
  `prep-diagnostic-outcomes.jsonl` rows.
- Deterministic canary generation is explicit only and uses the `canary`
  authority activity.
- Eligible-candidate Qdrant publication is retired; selected-release feedback is
  the only Qdrant/RAG publication route.
- Selected-release publication checks disk manifest hash against review receipt
  manifest hash.
- Selected-release receipts now require reviewer, checked_at, programme_id,
  receipt_id, and notes.
- Candidate-set review rejects invalid ledger rows and selected artifacts
  without valid ledger linkage.
- Failed candidate-set review now writes a diagnostic-only `no_release` outcome
  rather than silently returning to generation or publishing a weak manifest.
- One-segment review receipts now include hard/structural/advisory section
  projection.
- Prepared artifacts now bind the selected script path to contract/provenance
  surfaces; post-refinement rewrites must refresh the model contract or
  invalidate it before save/release.
- Invalid actionability validation no longer exposes `prepared_script`; it emits
  `diagnostic_sanitized_script` only.
- Anti-personification lint coverage now includes autonomous segment prompts and
  segment iteration review surfaces.
- Prep seed construction now supplies required offline context fields instead
  of falling back to topic-only text.

## Consistency Findings

Remaining inconsistencies:

- Fixed role enums and exact tier-list trigger language still act as form
  authority. This conflicts with generated-form doctrine.
- Source readiness still validates many source-shaped references without
  dereferencing source packets, snippets, freshness, rights, or claim
  consequence.
- Source-recruitment failures are witnessed, but not yet routed into autonomous
  source-following blackboard objects with expected-value bids.
- Model-emitted prep contracts are now invalidated when script refinement
  changes material text without a refreshed final contract.
- Review gate section projection is visible, but the current blocking gate still
  treats structural/craft criteria as release authority.
- Runtime layout readback now requires object refs for cited source/item/action
  targets in addition to layout and ward visibility.
- Tier-list actionability still maps through lossy trigger/need conversion
  rather than a first-class tier action contract.
- Interview prep has source/consent concepts, but lacks action/readback kinds
  for question ask, answer/no-answer, refusal/off-record, and public answer
  scope.

## Correctness Findings

Correctness risks fixed in this pass:

- Planner failure no longer auto-manufactures a canned canary.
- `canary_allowed` is now operationally meaningful for explicit canary mode.
- the raw-manifest Qdrant publication path is removed; selected-release
  feedback is the only prep-to-Qdrant publication path.
- Manifest mismatch between review receipt and disk selected-release manifest
  blocks selected-release feedback.
- Thin release receipts no longer satisfy selected-release review.
- Invalid JSON ledger rows no longer count as good audit evidence.
- Unsupported-action validator cleanup is no longer a loadable script surface.
- Missing lint coverage no longer makes the personage sweep claim false.

Correctness risks still open:

- No-candidate dossiers are too thin: they need lead ids, source gaps, tried
  sources, recruited sources, confidence, budget, authority ceiling, and
  falsification criteria.
- Refusal/no-release dossiers are terminal enough to block release, but still
  need richer source-follow-up, review-gap, script/contract, and return-to-prep
  fields.
- Source-readiness diagnostics are diagnostic-only now, but other invalid
  diagnostic files still resemble artifact-shaped payloads.
- Publication `ok` and `publication_ok` remain semantically split; callers must
  not treat publication diagnostics as release failure unless the claim is
  publication success.
- Publication witness paths are observability, not a fully reliable feedback
  sensor.

## Missed Opportunities

Highest-leverage missed opportunities:

1. Form capability contract.
   Replace fixed roles/exact phrases with a generated `form_contract` that
   declares audience job, event object, action vocabulary, source obligations,
   runtime readback obligations, and deviation policy.

2. Inquiry blackboard.
   Source gaps should become durable knowledge-gap objects with query leads,
   source packets, attempted searches, excluded sources, rights/freshness, and
   why the recruited source changed or refused a claim. This replaces expert
   micro-rule research with autonomous source-following.

3. Source-packet planning.
   `ProgrammePlanner` should receive resolved source packets through
   `content_state`/`vault_state`, not naked topic strings.

4. First-class action contracts.
   Add canonical tier and interview action kinds instead of relying on regex
   phrases and generic layout needs.

5. Refusal/no-release terminal outcomes.
   Candidate-set review with no acceptable selection should produce a valid
   diagnostic terminal outcome, not just `ok=false`.

6. Return-to-prep gate.
   Failed selection, `no_release`, runtime fallback, or readback mismatch should
   return to prep only when a bounded dossier names the gap, budget, expected
   observable, and falsification criterion. Otherwise it should remain a
   terminal diagnostic.

## Recommended Implementation Order

1. Build `FormCapabilityContract` and demote fixed roles/exact phrases to
   examples.
2. Add source-packet inquiry objects and require resolved packets before
   planning.
3. Add tier-list and interview action-contract schemas.
4. Enrich refusal/no-release dossiers and candidate-set outcome summaries.
5. Add return-to-prep gating from diagnostic outcomes.
6. Revisit hard/structural/advisory gate release policy after the above gives
   enough evidence to avoid weakening real authority gates.

## Verification

- `uv run pytest tests/shared/test_segment_prep_pause.py tests/shared/test_segment_prep_contract_outcomes.py tests/scripts/test_segment_prep_pause_runtime_surfaces.py tests/systemd/test_content_prep_residency_units.py tests/systemd/test_content_prep_residency_guards.py tests/hapax_daimonion/test_daily_segment_prep_residency.py::test_run_prep_paused_writes_status_and_skips_model_check tests/hapax_daimonion/test_daily_segment_prep_residency.py::test_run_prep_one_segment_writes_status_and_exact_planner_target tests/hapax_daimonion/test_daily_segment_prep_residency.py::test_load_prepped_programmes_accepts_valid_provenance tests/hapax_daimonion/test_daily_segment_prep_layout_contract.py tests/hapax_daimonion/test_segment_quality_actionability.py::test_loader_rejects_artifact_requiring_unsupported_runtime_action_rewrite tests/shared/test_segment_iteration_review.py::test_one_segment_review_accepts_real_loader_objects_without_enriched_hash_mismatch tests/hapax_daimonion/test_segment_release_publication.py -q`
  passed: 38 tests.
- `uv run pytest tests/shared/test_segment_candidate_selection.py tests/shared/test_segment_iteration_review.py::test_one_segment_review_accepts_real_loader_objects_without_enriched_hash_mismatch tests/shared/test_segment_review_gate_sections.py tests/hapax_daimonion/test_daily_segment_prep_residency.py::test_run_prep_one_segment_writes_status_and_exact_planner_target tests/hapax_daimonion/test_daily_segment_prep_residency.py::test_raw_manifest_candidates_are_not_published_to_qdrant tests/hapax_daimonion/test_segment_release_publication.py tests/hapax_daimonion/test_daily_segment_prep_layout_contract.py::test_load_prepped_programmes_accepts_prior_only_responsible_artifact -q`
  passed: 20 tests.
- `uv run pytest tests/hapax_daimonion/test_segment_quality_actionability.py::test_actionability_quarantines_unsupported_visual_claims_without_prepared_script tests/hapax_daimonion/test_segment_quality_actionability.py::test_actionability_rejects_camera_director_command_prose tests/scripts/test_lint_personification.py tests/shared/test_segment_candidate_selection.py tests/hapax_daimonion/test_daily_segment_prep_residency.py::test_run_prep_one_segment_writes_status_and_exact_planner_target tests/hapax_daimonion/test_daily_segment_prep_residency.py::test_raw_manifest_candidates_are_not_published_to_qdrant tests/hapax_daimonion/test_segment_release_publication.py -q`
  passed: 19 tests.
- `uv run python scripts/lint_personification.py --json` returned zero findings.
- `uv run python -m py_compile shared/segment_prep_pause.py shared/segment_prep_contract.py shared/segment_candidate_selection.py shared/segment_iteration_review.py agents/hapax_daimonion/daily_segment_prep.py scripts/review_segment_candidate_set.py`
  passed.

All pytest runs had the existing environment warning for unset
`LITELLM_API_KEY`.

Current branch verification after the contract/authority hardening pass:

- `uv run pytest tests/shared/test_segment_prep_pause.py tests/scripts/test_segment_prep_pause_runtime_surfaces.py tests/shared/test_segment_prep_contract_outcomes.py tests/shared/test_segment_live_event_quality.py tests/hapax_daimonion/test_segment_quality_actionability.py tests/shared/test_segment_iteration_review.py tests/shared/test_segment_candidate_selection.py tests/scripts/test_review_segment_candidate_set.py tests/hapax_daimonion/test_daily_segment_prep_residency.py tests/hapax_daimonion/test_segment_release_publication.py -q`
  passed: 123 tests, 1 environment warning for unset `LITELLM_API_KEY`.
- `uv run ruff check agents/hapax_daimonion/daily_segment_prep.py shared/segment_prep_pause.py shared/segment_prep_contract.py shared/segment_quality_actionability.py shared/segment_live_event_quality.py shared/segment_candidate_selection.py shared/segment_iteration_review.py shared/segment_review_gate_sections.py scripts/review_one_segment_iteration.py tests/hapax_daimonion/test_daily_segment_prep_residency.py tests/hapax_daimonion/test_segment_quality_actionability.py tests/shared/test_segment_candidate_selection.py tests/shared/test_segment_iteration_review.py`
  passed.
