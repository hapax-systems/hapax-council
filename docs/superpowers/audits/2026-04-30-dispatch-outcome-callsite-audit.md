# Dispatch Outcome Callsite Audit

Date: 2026-04-30
Branch: `codex/cx-amber-dispatch-outcome-callsite-audit`
Task: `dispatch-outcome-callsite-audit`
Base reviewed: `origin/main` `39fd9de5e5a7c23965c70f2388555199868be58f`

## Scope

This is a static/code audit for legacy boolean outcome recording. It does not
migrate runtime callsites. The output is a migration map: where raw
`record_outcome(success=True)` or equivalent booleans can remain internal, where
they must become commanded/deferred outcomes, and where witnessed success is
required before learning or public/director readiness can trust the signal.

Policy baseline from the parent spec:

- A command accepted, file written, candidate selected, or API call completed is
  not a witnessed outcome.
- Public/live, director, runner, media, or world-surface claims cannot inherit
  raw boolean success.
- Missing, stale, private, blocked, or un-witnessed effects must fail closed for
  public claims and outcome learning.
- Exploration and aesthetic activation can keep local learning only when it is
  explicitly scoped away from public truth, rights, safety, and monetization
  claims.

## Search Evidence

Required task search:

```bash
rg -n "record_outcome|success=True|success: bool" agents shared logos tests
```

Result: 148 matching lines including tests.

Production-only version of the required search:

```bash
rg -n "record_outcome|success=True|success: bool" agents shared logos --glob '!**/__pycache__/**'
```

Result: 60 matching lines.

Expanded equivalent search:

```bash
rg -n "record_outcome\(|record_grounding_outcome\(|update_outcome\(|record_attempt\(|ExecutionResult\(|success=True|success: bool" agents shared logos --glob '!**/__pycache__/**'
```

Result: 92 matching lines.

## Classification Vocabulary

| Classification | Meaning |
| --- | --- |
| `witnessed_migration` | Must migrate to a `CapabilityOutcomeEnvelope` or equivalent with fresh witness refs before success learning or public/director readiness can use it. |
| `commanded_deferred` | The callsite may record that a command was accepted or deferred, but it must not update success until a downstream witness closes the loop. |
| `internal_only` | Boolean is local telemetry, hysteresis, fix execution, or metrics; it must not flow into public/director/world success claims. |
| `exploration_only` | Boolean is allowed only for cold-start or aesthetic recruitment priors; it must not validate manifestation, public safety, rights, or truth. |
| `blocked_safe` | Existing path records failure or no-op on missing evidence; no success migration is needed for the audited behavior. |
| `already_adapted` | Current code routes a legacy boolean through a fail-closed adapter or otherwise separates command/witness fields. |

## Callsite Classification

| Surface | Current signal | Classification | Required migration/test before public readiness |
| --- | --- | --- | --- |
| `shared/affordance_pipeline.py:883-923` | Core `record_outcome(success: bool)` primitive mutates activation state, metrics, and Hebbian context; `record_capability_outcome()` now gates typed envelopes first. | `already_adapted` core primitive, with direct-call hazard | Keep direct `record_outcome()` as low-level internal/exploration only. Public/runtime callsites should migrate to `record_capability_outcome()` and prove no direct boolean can increment success for claim-bearing output. |
| `shared/affordance_pipeline.py:937-947` | Dismissal bridges to `record_outcome(success=False)`. | `blocked_safe` | Failure-only dismissal is acceptable; keep tests that dismissal cannot validate success. |
| `agents/hapax_daimonion/run_loops_aux.py:270-302` | Compositional compositor dispatch records success when `family != "unknown"` after SHM/control dispatch. | `commanded_deferred` -> `witnessed_migration` | Add fixture that a compositor command write does not count as success until lane/read-model/frame witness confirms fresh manifestation for the same target. |
| `agents/hapax_daimonion/run_loops_aux.py:313-447` | Autonomous narration records failure for silence/write failure, and records success according to `triad.learning_update_allowed` after emit. Voice-output witness and narration triad refs are present. | `witnessed_migration` in progress | Add focused tests that narration success requires fresh speech/route/egress witness refs, not only composed text or write success. Public speech must also prove destination safety. |
| `agents/hapax_daimonion/run_loops_aux.py:490-507` | Narration drive inhibition records `success=False` when required evidence is missing. | `blocked_safe` | Keep regression that missing conative evidence records failure/no-update, never success. |
| `agents/hapax_daimonion/run_loops_aux.py:721-738` | `system.notify_operator` records success immediately after `activate_notification()`. | `commanded_deferred` | If notification priors remain useful, convert to commanded/deferred and add witness for notification delivery/operator-visible state before success learning. |
| `agents/hapax_daimonion/run_loops_aux.py:755-767` | `studio.toggle_livestream` records success after writing compositor control. | `witnessed_migration` | High risk. Success must require `LivestreamEgressState`, broadcast manifest, and kill-switch/egress evidence showing the requested transition actually took effect and stayed public-safe. |
| `agents/hapax_daimonion/run_loops_aux.py:781-815` | Generic `studio.*` control affordances record success after logging recruitment. | `commanded_deferred` | Convert to commanded/deferred until WCS/control-plane readback proves the specific surface/route accepted the command. Do not let recruitment log success affect director readiness. |
| `agents/hapax_daimonion/run_loops_aux.py:818-841` | World-domain affordances record success after logging recruitment when feature flag is enabled. | `commanded_deferred` | Require WCS adapter evidence for target/source/freshness before success learning. Add negative test that enabled world routing plus recruitment log alone is not public/world truth. |
| `agents/reverie/mixer.py:292-303` | `node.*` visual satellite activation records success after recruitment to prevent cold-start Thompson collapse. | `exploration_only` | Keep allowed only as aesthetic/cold-start prior. Add tests/documentation that it cannot validate manifestation, public safety, or visual claim confidence. |
| `agents/reverie/mixer.py:304-318` | `content.yt.feature` records success after state-file/content-router activation. | `commanded_deferred` | Require content slot/readback/manifest witness before counting visual/public manifestation. |
| `agents/reverie/mixer.py:319-347` | `content.*`, `knowledge.*`, and `space.*` record success after router activation or camera route selection. | `exploration_only` for aesthetic priors; `commanded_deferred` for rendered media/camera claims | Split activation credit from manifestation credit. Camera/content surfaces need fresh rendered frame/source/span evidence before claim-bearing use. |
| `agents/hapax_daimonion/conversation_pipeline.py:1415-1418` plus `agents/hapax_daimonion/tool_recruitment.py:36-47` | Conversation infers tool success from absence of `"error"`, but `ToolRecruitmentGate.record_outcome()` converts the legacy boolean into a no-witness envelope. | `already_adapted` | Existing adapter should continue proving no-witness tool booleans cannot increment success. Future tool provider envelopes can add witnessed source/artifact refs. |
| `agents/hapax_daimonion/cpal/runner.py:601-621` | CPAL records grounding success after `pipeline.process_utterance()` completes and failure on exception. | `internal_only` / `commanded_deferred` | Keep as local gain hysteresis only. If exposed to public speech or claim learning, require typed speech/egress/grounding refs. |
| `agents/hapax_daimonion/cpal/loop_gain.py:77-90` | Boolean grounding outcome adjusts local gain hysteresis. | `internal_only` | Do not treat gain recovery as proof of grounding or public delivery. |
| `agents/hapax_daimonion/cpal/grounding_bridge.py:75-84` | No-op bridge accepts boolean outcome. | `blocked_safe` | No migration needed while it remains a no-op; any future bridge must use typed witnessed outcomes. |
| `shared/affordance_metrics.py:43-92` | Metrics record boolean outcome events. | `internal_only` | Metrics may store legacy boolean after an upstream gate, but should not decide policy or public readiness. |
| `shared/endogenous_drive.py:192-197` | Narrative drive updates a Thompson posterior from a boolean. | `exploration_only` | Keep scoped to internal drive calibration. Do not reuse as narration/public success. |
| `shared/incident_knowledge.py:34-39` | Fix knowledge success rate updates from boolean fix outcomes. | `internal_only` | Fine for incident remediation memory; if fixes become autonomous public-action claims, add fix witness envelopes. |
| `shared/fix_capabilities/*` and `shared/fix_capabilities/base.py:57-60` | `ExecutionResult(success=True)` records command execution for repair capabilities. | `internal_only` | Execution success must not become WCS/public truth. A future fix-outcome envelope should separate command accepted, service state witnessed, and operator-visible recovery. |
| `shared/scrim_refusal_correction_boundary_gestures.py:272-333` | `programme_output_success` is validated against public-safe refusal/correction artifacts and blocked posture constraints. | `already_adapted` | Existing validators constrain laundering risk. Keep fixture coverage that blocked/private gestures cannot become programme successes. |
| `shared/wcs_witness_probe_runtime.py:102` | `command_result_success` is a separate field from witness refs. | `already_adapted` | Maintain separation between command result and witness-derived claim state. |
| `agents/_telemetry.py:438`, `shared/telemetry.py:511`, `agents/visual_layer_aggregator/aggregator.py:214` | Boolean success used for trace/API poll telemetry. | `internal_only` | Telemetry success is not capability success. It can support diagnostics only. |
| `agents/dev_story/models.py:40` | Dev story model defaults `success=True`. | `internal_only` test/dev surface | Excluded from runtime migration unless dev-story output starts feeding production claims. |
| `tests/**` matches | Tests assert current behavior or fixtures instantiate success booleans. | test evidence | Update when runtime migrations happen; do not count as production risks. |

## Highest-Risk Migration Order

1. `agents/hapax_daimonion/run_loops_aux.py:755-767`:
   `studio.toggle_livestream` can affect live/public egress and should be the
   first witnessed migration if it still influences learning.
2. `agents/hapax_daimonion/run_loops_aux.py:270-302` and `:781-841`:
   compositor/studio/world control paths should record command/defer status
   until WCS/readback witnesses prove fresh manifestation.
3. `agents/hapax_daimonion/run_loops_aux.py:313-447`:
   narration is partly hardened by triad and voice-output witness refs, but
   success learning should require route/egress/private-destination evidence.
4. `agents/reverie/mixer.py:304-347`:
   content and camera activation should be split into exploration prior vs
   rendered/source-qualified manifestation.

## Tests Needed Before Migration

- Compositional control write does not increment success without fresh
  compositor/lane/frame witness for the same capability and target.
- Livestream toggle write does not increment success without matching
  `LivestreamEgressState`, broadcast manifest, and kill-switch evidence.
- Autonomous narration composed or written text does not increment success
  without fresh speech route plus public/private egress witness.
- Tool result absence of `"error"` continues to produce no success update unless
  a future provider envelope includes required witness refs.
- Reverie activation of `node.*`, `content.*`, `knowledge.*`, or `space.*`
  remains exploration/local activation credit and cannot validate public visual
  manifestation.
- World-domain recruitment log alone cannot validate WCS truth, safety,
  freshness, or public status.
- Fix capability `ExecutionResult(success=True)` remains command execution
  telemetry and cannot become public or WCS recovery truth without service-state
  witness.

## Downstream Dependency Notes

The task note already lists `affordance-outcome-adapter` and
`outcome-learning-no-false-grounding-tests` as downstream work. This audit
refines the dependency surface:

- `affordance-outcome-adapter` is partially satisfied for tool recruitment and
  core envelope gating, but direct production callsites still need migrations.
- `outcome-learning-no-false-grounding-tests` should use the highest-risk rows
  above as fixtures.
- Director/public readiness should stay blocked on witnessed migration for
  livestream toggle, compositor/studio control, world-domain routing, and
  narration egress.
- Reverie/content work should add a separate manifestation witness path rather
  than reusing exploration success.

## Residual Risk

This audit does not remove any legacy success write. Until follow-up migrations
land, the safe interpretation is:

- direct `record_outcome(success=True)` in runtime control paths is at most
  command/exploration credit;
- no direct boolean success can be cited as public, director, WCS, rights,
  monetization, or truth authority;
- migration work should prefer `record_capability_outcome()` or domain-specific
  typed envelopes that include source refs, witness refs, freshness, public
  policy, and learning-policy decisions.
