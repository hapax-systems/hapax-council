# Autonomous Segment Prep Implementation Research Synthesis

**Status:** research synthesis; partial implementation documented; prep remains `research_only`
**Checked at:** 2026-05-07T01:06:48Z
**Depends on:** `2026-05-06-autonomous-segment-prep-authority-transition-doctrine.md`
**Scope:** segment prep freedom layer, authority gates, review/release, no-candidate/no-release outcomes, source recruitment, runtime layout/actionability, and non-anthropomorphic register.

## Summary

The team convergence is strong:

> Forms are generated; authority is gated.

The implementation target is not a looser script generator. It is a stricter
authority system around a freer inquiry process. The freedom layer may generate
topic, source path, form, structure, action plan, layout needs, refusal, or
no-candidate outcomes. The authority layer decides which transitions are earned.

This pass adds the missing bridge between doctrine and implementation: six
framework artifacts, safety replacements for old rubric filters, and a concrete
migration order.

The current direction is sharper than "make better segment prompts." Prep may
generate an authority hypothesis, but the hypothesis has no force until it is
bound to source packets, the final script, a contract hash, a release receipt,
and any required runtime readback. Source work should follow live gaps and
source consequences autonomously; it should not become expert micro-rule
research where fixed form standards quietly decide release.

## Research Inputs

Local inputs:

- coordinated lane reports from cx-red, cx-gold, cx-green, cx-blue, alpha,
  gamma, epsilon, and zeta;
- pointed research agents Kuhn and Mendel;
- `docs/research/unified-activation-interface-architectures.md`;
- `docs/superpowers/specs/2026-05-06-segment-source-action-live-event-contract.md`;
- `docs/superpowers/specs/2026-05-06-systems-control-segment-prep-runtime-map.md`;
- `docs/superpowers/specs/2026-05-06-content-prep-consultation-review-gates.md`;
- `docs/superpowers/specs/2026-04-29-grounding-commitment-no-expert-system-gate-design.md`;
- `shared/segment_iteration_review.py`;
- `shared/segment_quality_actionability.py`;
- `shared/segment_prep_contract.py`;
- `agents/hapax_daimonion/daily_segment_prep.py`;
- `agents/programme_manager/prompts/programme_plan.md`;
- `agents/programme_manager/planner.py`.

External anchors used as engineering constraints, not prompt-facing slogans:

- blackboard and opportunistic control architectures;
- active learning and cost-aware query selection;
- mixed initiative;
- runtime assurance / Simplex;
- Ashby/Conant regulator theory;
- provenance systems such as W3C PROV;
- situated action critiques of plan-as-execution.

## Framework Artifact 1: Form-Capability Contract

Replace closed role eligibility with a generated form declaration.

Existing roles such as `tier_list`, `top_10`, `rant`, `react`, `iceberg`,
`interview`, and `lecture` remain useful exemplars and priors. They must not be
the ontology of valid segment forms.

Minimum contract fields:

- `form_id`: stable local id for this generated form.
- `form_label`: human-readable label, not an enum authority.
- `form_origin`: generated, selected exemplar, operator requested, fixture, or
  refusal/no-candidate.
- `grounding_question`: what the form tries to establish or why it refuses.
- `claim_shape`: allowed claim verbs, authority ceiling, scope, uncertainty, and
  correction path.
- `authority_hypothesis`: generated request for the next authority transition,
  with the evidence that would make it earned.
- `source_classes`: source kinds needed or already consulted.
- `evidence_requirements`: what source facts would change, narrow, or block the
  candidate.
- `live_event_object`: visible/doable/inspectable object when the form claims
  responsible livestream action.
- `action_primitives`: proposed actions as structured objects.
- `layout_need_classes`: needed runtime effects, not concrete layouts.
- `readback_requirements`: what runtime must witness before success can count.
- `public_private_ceiling`: private, dry-run, public-live, public-archive, or
  monetizable ceiling.
- `refusal_mode`: how the form declines, narrows, or emits a no-candidate
  dossier if authority is not earned.

Design rule: the form contract is generated in the freedom layer. Deterministic
validators may reject or downgrade it, but they must not author the form.

Generated authority is a claim about what should be allowed, not a grant. The
grant comes only from deterministic transition checks and bound review/runtime
receipts.

## Framework Artifact 2: Inquiry Blackboard

Segment prep should be an autonomous inquiry workspace, not fixed pass
choreography.

Blackboard object classes:

- `Lead`: candidate topic, source pressure, live event, operator-local pressure,
  or prior-release feedback.
- `SourceGap`: missing, stale, thin, conflicting, rights-unclear, or temporally
  mismatched evidence.
- `ClaimGap`: unsupported claim, unlabelled uncertainty, scope problem, source
  consequence missing, or currentness mismatch.
- `FormProposal`: generated form-capability contract.
- `ActionGap`: claimed action lacks object, operation, evidence, capability,
  readback, or fallback.
- `LayoutGap`: visible/doable claim lacks payload-bound runtime obligation.
- `PersonageGap`: anthropomorphic subject-position, fake human feeling,
  audience-co-presence, or framework-vocabulary leakage.
- `AuthorityGap`: transition not earned: source, consent, privacy, rights,
  selected release, runtime readback, or public archive.
- `ReviewGap`: required risk-tier receipt missing, stale, unbound, or
  contradictory.
- `NoCandidateReason`: explicit outcome when no artifact/refusal is justified.

Capability recruitment rules:

- Capabilities bid on blackboard objects they can improve.
- Bids include expected value, source/cost budget, authority boundary, risk,
  and expected observable change.
- Scheduling is opportunistic and budget-aware, not fixed round count.
- A capability can add evidence, create a new gap, close a gap, abandon a lead,
  or recommend no-candidate/no-release.
- External source recruitment is valid when a knowledge gap has enough pressure
  and the source class is allowed by egress/privacy policy.

Source-following rule:

- Source inquiry follows the next material gap: freshness, contradiction,
  source consequence, rights/privacy, runtime object identity, or refusal/no
  release justification.
- Expert standards, role packets, and counterexamples may calibrate judgment,
  but they do not schedule research as fixed micro-rules or fixed pass counts.
- A source follow-up must name the claim, action, form, refusal, or release
  decision it could change. Otherwise it is source theater.
- A source-following branch can terminate in `no_candidate`, `no_release`,
  narrowed scope, or return-to-prep; it does not have to terminate in a script.

Quiescence criteria:

- no unresolved lead/source/claim/action/layout/personage/authority/review gap
  above the risk threshold;
- no source follow-up bid with positive expected value inside remaining budget;
- no candidate awaiting deterministic authority transition;
- no review receipt required for selected release;
- budget exhausted with a dossier written;
- or an artifact/refusal/no-candidate/no-release outcome has been witnessed.

Quiescence is rest, not convergence to a quality setpoint.

## Framework Artifact 3: Authority Transition Lattice

Authority transitions are deterministic and conservative.

States:

1. `scratch`: private inquiry state, no public claim.
2. `no_candidate`: prep ran and found no justified artifact or refusal brief.
3. `refusal_brief_candidate`: refusal-as-data drafted, not yet publishable.
4. `eligible_candidate`: artifact passes hard authority gates, not selected.
5. `no_release`: candidate-set review found no selected release justified.
6. `selected_release`: candidate selected by bound risk-tier receipts.
7. `runtime_pool`: selected artifact can be loaded by the runtime pool.
8. `runtime_attempted`: runtime attempted speech/action/layout.
9. `runtime_readback_matched`: required payload/effect readback was witnessed.
10. `public_live`: live public emission authorized.
11. `public_archive`: archived public artifact authorized.
12. `monetizable`: monetization-specific gates passed.
13. `correction_or_retraction`: public correction path activated.

Transition owners:

- Freedom layer can propose `scratch`, `no_candidate`, form proposals, and
  refusal/artifact candidates.
- Prep validators can move `scratch -> no_candidate`,
  `scratch -> refusal_brief_candidate`, or `scratch -> eligible_candidate`.
- Candidate review can move `eligible_candidate -> selected_release` or
  `eligible_candidate -> no_release`.
- Loader can move `selected_release -> runtime_pool`.
- Runtime controllers can move `runtime_pool -> runtime_attempted` and
  `runtime_attempted -> runtime_readback_matched`.
- Public/publishing gates own `public_live`, `public_archive`, `monetizable`,
  and `correction_or_retraction`.

Hard rule: no artifact may self-author its transition. LLM output is proposal,
not authority.

## Framework Artifact 4: Evidence Transform Calculus

Sources must do work. They are not decorative.

Each material claim/action should carry:

- `grounds`: source refs, chunk refs, local artifacts, runtime receipts, or
  operator-authorized notes.
- `warrant`: why these grounds support this claim/action.
- `qualifier`: uncertainty, scope, public/private ceiling, freshness band.
- `rebuttal_or_gap`: what would weaken, block, or force a narrower claim.
- `source_consequence`: what changes if the source is present, absent, stale, or
  contradicted.
- `source_removal_test`: whether removing the source changes the claim,
  action, rank, contrast, pause, or refusal.
- `temporality_band`: current, rolling, evergreen, operator-local, or
  constitutional.

Authority consequences:

- If no source changes the candidate, the candidate is source theater.
- If currentness is claimed without current/fresh evidence, downgrade or block.
- If source evidence is thin but promising, recruit sources rather than fill
  prose.
- If evidence remains insufficient, produce refusal/no-candidate.

## Source/Script/Contract Binding

The current binding target is a three-way invariant:

- source packets and source hashes bind the evidence available to prep;
- the generated form/source/action contract binds the intended authority,
  claims, actions, refusal path, and readback obligations;
- the post-refinement final script hash binds the exact text that review,
  release, runtime loading, and public correction are judging.

If refinement changes the material script, the contract must either be refreshed
and rehashed or invalidated. Deterministic replay may verify hashes and
freshness; it must not backfill missing source/action reasoning after the fact.

Release receipts should therefore bind candidate-set hash, artifact hash, final
script hash, contract hash, source packet hashes, review notes, and the
authority transition requested. A mismatch is return-to-prep or diagnostic
`no_release`, not a silent repair opportunity.

## Framework Artifact 5: Validator Calibration Protocol

Validators must be tested against negative controls, not only happy paths.

Required fixture classes:

- `rubric_recitation`: recites review vocabulary and scores high on old prose
  cues but has no source consequence.
- `regex_theater`: uses exact action phrases without structured action intent
  or runtime capability.
- `polished_essay`: fluent and coherent but no visible/doable counterpart under
  responsible hosting.
- `valid_weird_form`: short, non-standard, source-bound, capability-bound,
  and eligible despite low old craft scores.
- `valid_no_candidate`: no artifact, with witness/ledger and evidence-bound
  reason.
- `valid_no_release`: eligible candidate set reviewed, no selected release
  justified, diagnostic-only dossier with closed runtime boundary.
- `valid_refusal_brief`: refusal-as-data with no smuggled artifact content.
- `anthropomorphic_subtle`: no first person, but Hapax-as-subject, mental-state
  attribution, audience-co-presence, or human-host rapport.
- `validator_backfill_laundering`: deterministic maps present but
  model-authored source/action reasoning absent.
- `stale_layout_success`: LayoutStore/gauge/default/static success without
  payload-bound readback.
- `selected_release_bypass`: eligible artifact exposed to runtime/Qdrant
  without selected-release boundary.

Calibration rule: the hard gate must reject every negative control and accept
valid weird/no-candidate/no-release/refusal fixtures when their authority
obligations are met.

## Framework Artifact 6: Feedback And Prediction Policy

Feedback is a prior surface, not runtime authority.

Feedback inputs:

- selected-release receipts;
- refusal/no-candidate/no-release dossiers;
- source recruitment outcomes;
- runtime readback receipts;
- layout fallback/hold/refusal receipts;
- public correction/retraction events;
- operator re-aims;
- canary review notes.

Feedback must record:

- `prediction_id` or mechanism id;
- affected gate or prior;
- expected observable;
- baseline;
- observation window;
- confidence;
- falsification criterion;
- result update ref;
- authority ceiling.

Positive learning is allowed only from selected and witnessed outcomes. Eligible
but unselected artifacts remain diagnostic. Runtime fallback/hold/refusal is
negative or uncertain evidence, not success.

No-release and no-candidate outcomes should update priors about source
landscape, gaps, and budget. They must not be treated as failure merely because
no segment was produced.

## Return-To-Prep Gate

Return-to-prep is an authority transition, not an automatic retry loop.

A failed review, `no_release`, runtime fallback, or readback mismatch may return
to prep only when a dossier identifies:

- the exact source, script, contract, review, personage, or runtime-readback gap;
- the bounded work item that could close it;
- the budget and egress authority for that work;
- the expected observable change;
- the falsification criterion that would end the attempt as `no_candidate`,
  `no_release`, refusal, or quarantine.

Absent that gate, the correct result is a terminal diagnostic outcome and a
ledger row. The system should not convert failed selection into another
unbounded generation pass.

## Review And Release Redesign

Current review mixes hard authority and craft quotas. The redesign should split
them.

### Hard Authority Gate

Hard gates include:

- resident Command-R only;
- no Qwen/fallback/unload/swap;
- `prior_only` prep authority;
- source/provenance hashes;
- claim evidence, uncertainty, scope, freshness where relevant;
- privacy/rights/consent;
- selected-release boundary;
- proposal-only layout;
- no default/static/camera/spoken-only laundering in responsible hosting;
- runtime readback before layout success;
- no validator rewrite/backfill for critical reasoning;
- non-anthropomorphic register;
- witness and ledger entries for every prep run;
- valid outcome type: `artifact`, `refusal_brief`, `no_candidate`, or
  review-bound `no_release`.

### Structural Readout

Old craft scores should become descriptive data, not release authority:

- beat count;
- script length;
- source refs;
- action kinds proposed;
- evidence density;
- unresolved gaps;
- old quality heuristic scores if kept at all;
- consultation refs;
- role/form exemplars consulted.

Structural readouts must not have pass/fail thresholds.

### Advisory Excellence Review

Craft/excellence belongs to bound review receipts, not hidden code rubrics.
Receipts should be risk-tiered by publicness, rights/privacy, operator
involvement, layout claims, currentness, and runtime action claims.

Each receipt should bind:

- artifact or dossier hash;
- candidate set hash;
- iteration id;
- risk tier;
- authority class;
- quality range refs if used;
- reviewer;
- substantive notes;
- approve/revise/block;
- uncertainty or dissent.

## Non-Anthropomorphic Register Update

Simple first-person bans are necessary but not sufficient.

Hard-block register patterns:

- first-person singular and plural;
- "Claude" as actor or addressee;
- Hapax/the system/the substrate as subject of folk-psychological verbs;
- mental-state verbs attributed to non-operator subjects;
- audience co-presence constructions such as "you will notice" or "let's";
- fake feeling, empathy, taste, concern, preference, private intuition, or
  human-host rapport;
- framework vocabulary in public prose.

Preferred registers:

- agentless evidence statements;
- operator-subject statements where the operator is the actual subject;
- instrument-subject statements where a sensor/source is the actor;
- evidence-subject statements where a source shows or constrains a claim;
- operational verbs only when they name actual system operations: routed,
  selected, refused, quarantined, narrowed, recorded, or withheld.

Open question: total "Hapax as non-subject" may be too austere for all public
contexts. It is the safe default until examples prove a non-anthropomorphic
personage can speak with force without becoming a human-host persona.

## Runtime Layout And Actionability Consequences

Generated forms are valid only if they compile to bounded runtime obligations.

Required runtime-facing contract:

- stable obligation ids across prep, active segment state, layout driver,
  compositor readback, review, and ledger;
- payload refs/digests for source/action objects;
- bounded layout need classes;
- capability witness registry mapping needs to sensors/actuators/readbacks;
- rendered payload readback, not generic ward visibility;
- stable first-seen/requested-at timestamps keyed by obligation id;
- fallback/hold/refusal receipts;
- no static/default responsible success.

Zeta's layout conflict register adds a broader warning: static layout switchers,
static preset family fallbacks, stale v4l2 keep-alive frames, and broad
`broadcast_authorized` strings can violate the same doctrine outside segment
prep. These are not content-prep implementation prerequisites unless they
directly affect selected-release/runtime pool behavior, but they are doctrine
debt.

## Production Pause Authority Gap

The team found an operational conflict: RTE/service remediation can restart prep
while the design says prep is paused.

Before generation resumes, there should be a machine-readable prep pause gate
observed by:

- `hapax-segment-prep.service`;
- `hapax-segment-prep.timer`;
- RTE remediation/restart paths;
- manual prep runners;
- canary scripts;
- batch prep scripts.

The pause gate should distinguish:

- `research_only`;
- `docs_only`;
- `canary_allowed`;
- `pool_generation_allowed`;
- `runtime_pool_load_allowed`.

This is an authority issue. A chat-level pause is not sufficient if service
controllers can resume generation.

## Current Dangerous Residues

Implementation order from the local audit:

1. Exact phrase action hooks: wording still acts as actionability authority.
2. Automatic deterministic canary fallback: planner failure can become canned
   content instead of no-candidate/source-recruitment.
3. Closed segmented-role eligibility: fixed roles still act like admission
   criteria.
4. Universal beat anatomy/duration: opening/body/closing, 8+ beats, and
   30-60 minute assumptions still shape generation.
5. Character-count floors: verbosity still masquerades as quality.
6. Source readiness as shape validation: some checks gate role template shape,
   not source sufficiency.
7. Fixed quality rubric/floors: hidden expert-system risk.
8. Spoken-only responsible beat ban: correct for responsible visual hosting,
   wrong as universal outcome rule.
9. Fixed six-role review choreography: useful canary fixture, not general
   release architecture.
10. Bounded action/layout ontology: useful shim, but new capabilities need a
    registry rather than validator edits.
11. Validator backfill: acceptable only for non-critical ids/normalization.
12. Legacy Qdrant candidate upsert path: eligible-but-unselected artifacts must
    not leak into affordance memory.

## Implementation Preconditions

Implementation should not resume until these are specified enough to test:

- form-capability contract;
- inquiry blackboard state objects;
- authority transition lattice;
- no-candidate/refusal dossier schema;
- hard authority gate vs structural readout vs advisory excellence report;
- risk-tiered review receipts;
- non-anthropomorphic register policy;
- source/action evidence transform calculus;
- source-following policy replacing fixed expert micro-rule research;
- source/script/contract/final-script binding;
- runtime obligation/readback identity;
- prep pause authority gate;
- return-to-prep gate;
- validator calibration fixtures.

## First Implementation Slice

The first code slice should prove the architecture rather than produce ten
segments.

Minimum target:

- one valid weird generated form fixture;
- one valid no-candidate fixture;
- one valid no-release fixture;
- one return-to-prep refusal when the dossier lacks a bounded next action;
- one source-theater failure;
- one regex-theater failure;
- one anthropomorphic-subtle failure;
- one selected-release bypass failure;
- no automatic canary fallback in normal prep;
- deterministic canary available only as explicit fixture mode.

Only after that should prep generate a new one-segment canary.

## Prediction

Expected effects after this research-to-implementation bridge:

- major reduction in topic anchoring and canned fallback;
- major reduction in actionability theater;
- medium-large improvement in source specificity;
- strong increase in no-candidate/refusal dossiers;
- increased prep latency and variability;
- initial decrease in "loadable segment count";
- lower false-positive loadability;
- better support for interview prep once consent/turn receipts/readback are
  integrated.

Falsification criteria:

- prep still emits canned topic/form after planner/source failure;
- artifacts pass because they hit old rubric terms or phrase triggers;
- no-candidate runs vanish without witness/ledger;
- selected-release boundary is bypassed by eligible artifacts;
- runtime claims layout/action success without payload-bound readback;
- script refinement changes the final text without contract/hash refresh;
- failed candidate review automatically restarts prep without a bounded
  return-to-prep dossier;
- reviewers treat old structural readout as pass/fail rubric.

## Implementation Update: Authority Gate and No-Candidate Witness

Implemented in the first ancillary slice:

- `shared.segment_prep_pause` now provides a machine-readable segment-prep
  authority gate. Missing authority state fails closed to `research_only`;
  generation requires `pool_generation_allowed`; runtime pool loading and
  selected-manifest writing require `runtime_pool_load_allowed`.
- `hapax-segment-prep.service` checks the authority gate with `ExecCondition`
  before the resident Command-R check. A deliberate pause therefore skips the
  unit instead of becoming a failed-unit restart loop.
- `daily_segment_prep.run_prep()` writes `prep-status.json` with
  `status=paused` and returns no artifacts when the gate blocks generation,
  without probing TabbyAPI or constructing the planner.
- `scripts/batch_prep_segments.sh` checks the authority gate before model
  probing and before each batch, and counts eligible candidates with
  `require_selected=False` so selected-release gating does not cause runaway
  over-generation.
- `scripts/hapax-rte-remediate` skips `hapax-segment-prep.service` and
  `hapax-segment-prep.timer` restarts while the authority gate blocks
  generation, reporting the skip as `skipped_pause_gate`.
- `load_prepped_programmes(require_selected=True)` now returns an empty runtime
  pool below `runtime_pool_load_allowed`, even if a selected manifest exists.
  Review/research callers may still use `require_selected=False`.
- `scripts/review_segment_candidate_set.py --write-manifest` now checks
  `runtime_pool_load_allowed` before writing `selected-release-manifest.json`.
- `shared.segment_prep_contract.validate_segment_prep_outcome()` and
  `daily_segment_prep` now support diagnostic-only `no_candidate` outcome
  dossiers. When a run saves no candidates, it writes an `outcomes/*.json`
  dossier and a `candidate-ledger.jsonl` row without adding anything to the
  eligibility manifest, selected-release manifest, Qdrant, or runtime pool.

Live state after implementation: the authority file was explicitly set to
`research_only` at `~/hapax-state/segment-prep/prep-authority.json` while the
full prep-system audit remains pending.

Verification:

- `uv run pytest tests/shared/test_segment_prep_pause.py tests/shared/test_segment_prep_contract_outcomes.py tests/scripts/test_segment_prep_pause_runtime_surfaces.py tests/systemd/test_content_prep_residency_units.py tests/systemd/test_content_prep_residency_guards.py tests/hapax_daimonion/test_daily_segment_prep_residency.py::test_run_prep_paused_writes_status_and_skips_model_check tests/hapax_daimonion/test_daily_segment_prep_residency.py::test_run_prep_one_segment_writes_status_and_exact_planner_target tests/hapax_daimonion/test_daily_segment_prep_residency.py::test_load_prepped_programmes_blocks_runtime_load_below_authority_gate tests/hapax_daimonion/test_daily_segment_prep_residency.py::test_load_prepped_programmes_accepts_valid_provenance -q`
  passed: 25 tests, 1 environment warning for unset `LITELLM_API_KEY`.
- `uv run pytest tests/hapax_daimonion/test_daily_segment_prep_layout_contract.py tests/hapax_daimonion/test_segment_quality_actionability.py::test_loader_rejects_artifact_requiring_unsupported_runtime_action_rewrite tests/shared/test_segment_iteration_review.py::test_one_segment_review_accepts_real_loader_objects_without_enriched_hash_mismatch tests/hapax_daimonion/test_segment_release_publication.py -q`
  passed: 13 tests, 1 environment warning for unset `LITELLM_API_KEY`.
- `uv run ruff check ...` passed on touched Python modules and tests.

Remaining deliberate next step: dispatch the full-team audit across prep
systems for completion, consistency, correctness, and missed opportunities
before any new content-prep generation.

## Full-Team Audit Follow-Up

The first pointed audit returns found issues severe enough to fix before the
audit is considered complete:

- planner failure and empty planner output could still auto-generate the
  deterministic canary instead of producing a witnessed no-candidate outcome;
- `canary_allowed` existed as an authority mode but no generation path used the
  `canary` activity;
- a retired `_upsert_programmes_to_qdrant()` helper still encoded the old
  eligible-candidate-to-Qdrant path;
- selected-release publication could validate an in-memory review manifest while
  runtime loading read a different disk manifest;
- selected-release receipts were materially weaker than canary review receipts;
- candidate ledger auditability checked existence more than valid linkage;
- source-readiness diagnostics still looked like prior-only artifact-shaped
  files rather than diagnostic-only outcomes;
- hard-gate/structural/advisory review sections existed only as a projection
  helper, not in receipts.

Fixes applied:

- deterministic canary generation is now explicit only: it requires
  `HAPAX_SEGMENT_PREP_CANARY_SEED=1`, `MAX_SEGMENTS=1`, and authority for the
  `canary` activity. Planner failure/empty output now falls through to a
  no-candidate outcome.
- source-readiness failure writes a diagnostic-only outcome under `outcomes/`
  and the ledger row records diagnostic authority and closed release/runtime
  boundaries.
- `_upsert_programmes_to_qdrant()` is now a retired no-op with a warning; the
  only Qdrant/RAG path is selected-release feedback through runtime loader
  gates.
- selected-release feedback now requires the disk
  `selected-release-manifest.json` hash to match the review receipt manifest
  hash when a receipt manifest is supplied.
- selected-release manifest construction requires structured release receipts
  with reviewer, checked_at, programme_id, receipt_id, and notes.
- candidate-set review now rejects invalid ledger rows and requires selected
  artifact hashes to appear in valid candidate-ledger rows.
- one-segment review receipts now include `review_gate_sections` projection, so
  the hard/structural/advisory split is visible even while the current blocking
  gate remains unchanged.

Additional verification:

- `uv run pytest tests/shared/test_segment_candidate_selection.py tests/shared/test_segment_iteration_review.py::test_one_segment_review_accepts_real_loader_objects_without_enriched_hash_mismatch tests/shared/test_segment_review_gate_sections.py tests/hapax_daimonion/test_daily_segment_prep_residency.py::test_run_prep_one_segment_writes_status_and_exact_planner_target tests/hapax_daimonion/test_daily_segment_prep_residency.py::test_run_prep_canary_seed_switch_bypasses_heavy_planner tests/hapax_daimonion/test_daily_segment_prep_residency.py::test_legacy_qdrant_upsert_path_is_retired tests/hapax_daimonion/test_segment_release_publication.py tests/hapax_daimonion/test_daily_segment_prep_layout_contract.py::test_load_prepped_programmes_accepts_prior_only_responsible_artifact -q`
  passed: 20 tests, 1 environment warning for unset `LITELLM_API_KEY`.
- `uv run pytest tests/shared/test_segment_prep_pause.py tests/shared/test_segment_prep_contract_outcomes.py tests/scripts/test_segment_prep_pause_runtime_surfaces.py tests/systemd/test_content_prep_residency_units.py tests/systemd/test_content_prep_residency_guards.py tests/hapax_daimonion/test_daily_segment_prep_residency.py::test_run_prep_paused_writes_status_and_skips_model_check tests/hapax_daimonion/test_daily_segment_prep_residency.py::test_run_prep_one_segment_writes_status_and_exact_planner_target tests/hapax_daimonion/test_daily_segment_prep_residency.py::test_load_prepped_programmes_blocks_runtime_load_below_authority_gate tests/hapax_daimonion/test_daily_segment_prep_residency.py::test_load_prepped_programmes_accepts_valid_provenance tests/hapax_daimonion/test_daily_segment_prep_layout_contract.py tests/hapax_daimonion/test_segment_quality_actionability.py::test_loader_rejects_artifact_requiring_unsupported_runtime_action_rewrite tests/shared/test_segment_iteration_review.py::test_one_segment_review_accepts_real_loader_objects_without_enriched_hash_mismatch tests/hapax_daimonion/test_segment_release_publication.py -q`
  passed: 38 tests, 1 environment warning for unset `LITELLM_API_KEY`.
- `uv run python -m py_compile shared/segment_prep_pause.py shared/segment_prep_contract.py shared/segment_candidate_selection.py shared/segment_iteration_review.py agents/hapax_daimonion/daily_segment_prep.py scripts/review_segment_candidate_set.py`
  passed.

Still open after the follow-up fixes:

- generated form contracts are not implemented; fixed role enums and exact
  tier-list trigger language still impose form authority;
- source recruitment/free inquiry is not wired into planning with resolved
  source packets, hashes, freshness, and source-consequence transforms;
- final script/contract alignment after refinement still needs a final-script
  contract hash or post-refinement contract refresh;
- review `no_release` is now first-class enough to prevent selected-release
  publication; refusal-brief/no-release dossiers still need richer source-gap,
  source-follow-up, and return-to-prep fields;
- runtime readback identity remains incomplete for layout/action claims;
- interview prep needs consent, answer-authority, turn-taking, and release-scope
  receipts before it can be treated as ordinary segment prep.

## Second Audit Return Corrections

Additional read-only audit returns found more actionable issues:

- actionability validation still exposed a sanitized `prepared_script` on
  invalid results, making the validator API look like a rewrite affordance;
- the anti-personification sweep missed autonomous segment prompt and review
  surfaces even though tests expected those paths;
- `_build_seed()` constructed `NarrativeContext` without required fields,
  causing source/live-prior context to fall back to topic-only seed text;
- runtime layout readback remains object-weak: ward visibility can be true
  without proving the specific cited source/item/action is visible;
- tier-list actionability crosses contracts through lossy mapping rather than a
  first-class tier visual/action contract;
- explicit static fallback semantics still need separation between fallback
  permitted and fallback success;
- interview prep lacks action kinds for consent, question ask, answer/no-answer,
  refusal/off-record, and public answer-scope readback.

Fixes applied:

- `validate_segment_actionability()` now returns `prepared_script` only when
  `ok=True`. Invalid results expose `diagnostic_sanitized_script` only, and prep
  diagnostics record that field rather than treating a validator cleanup as a
  script rewrite.
- `scripts/lint_personification.py` now includes
  `agents/hapax_daimonion/autonomous_narrative/segment_prompts.py` and
  `shared/segment_iteration_review.py`; the current sweep returns zero findings.
- `_build_seed()` now builds `NarrativeContext` with explicit
  `stimmung_tone="segment_prep_source_bound"` and
  `director_activity="offline_segment_preparation"` so the autonomous narrative
  seed path can include live priors/assets instead of falling through to topic
  text.

Additional verification:

- `uv run pytest tests/hapax_daimonion/test_segment_quality_actionability.py::test_actionability_quarantines_unsupported_visual_claims_without_prepared_script tests/hapax_daimonion/test_segment_quality_actionability.py::test_actionability_rejects_camera_director_command_prose tests/scripts/test_lint_personification.py tests/shared/test_segment_candidate_selection.py tests/hapax_daimonion/test_daily_segment_prep_residency.py::test_run_prep_one_segment_writes_status_and_exact_planner_target tests/hapax_daimonion/test_daily_segment_prep_residency.py::test_run_prep_canary_seed_switch_bypasses_heavy_planner tests/hapax_daimonion/test_daily_segment_prep_residency.py::test_legacy_qdrant_upsert_path_is_retired tests/hapax_daimonion/test_segment_release_publication.py -q`
  passed: 19 tests, 1 environment warning for unset `LITELLM_API_KEY`.
- `uv run python scripts/lint_personification.py --json` returned
  `{"count": 0, "findings": []}`.

The remaining blockers are now clearer and larger than a bug patch:

- generated form-contract architecture;
- resolved source-packet inquiry before planning;
- object-bound layout/action readback;
- first-class tier/interview action contracts;
- post-refinement final-script contract binding;
- richer refusal/no-release dossiers and return-to-prep routing.
