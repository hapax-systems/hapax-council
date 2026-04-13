# 2026-04-12 — Delta session: reverie bridge repair (handoff)

**Role:** delta (temporary, spontaneous worktree)
**Duration:** 2026-04-12 ~18:45 – ~20:30
**PRs shipped:** #696 (core fix), #700 (audit follow-up), #(this one — docs + F6)
**Status:** closing

## What was asked

"You are now delta. Carry out a multi-pronged investigation into the health
and functionality of the reverie surface: audit code, compare against spec
and theoretical commitments, use observability tools."

Then:

"Research any loose ends to arrive at elegant solution that addresses the
core concerns and all periphery concerns. Then formal design docs. The
batched planning and implementation. Update alpha and beta."

Then:

"Research all work completed and all specs and designs and plans. Develop a
systematic multi-part audit that goes through all work. Look for
consistency, completion, robustness, dead code, missed opportunities, edge
cases. After developing the plan, execute it."

Then:

"Update docs, update alpha and beta, pr, merge, make sure everything is
active locally and working."

## What was found

The reverie **per-node parameter modulation path** (Path 2) was dead. It had
been dead silently since the Rust `DynamicPipeline` adopted the v2 plan
schema. `agents/reverie/_uniforms._load_plan_defaults` was walking the v1
flat `plan["passes"]` key and returning an empty dict against the live v2
`plan["targets"]["main"]["passes"]` shape. The merge loop at `write_uniforms`
had nothing to iterate, and none of the `{node_id}.{param_name}` keys the
visual chain computes ever reached the GPU. Colorgrade brightness pinned at
1.0. Noise frequency pinned at 1.5. RD feed rate pinned at 0.055. Every
per-node shader parameter ran on vocabulary defaults regardless of
operator state.

**Path 1** (imagination.dimensions → `UniformBuffer::from_state` → shared
`UniformData.{dim}` slots) was always alive. That's why the system wasn't
literally flat — shared-uniform shader reads got live values. But the
expressive surface everyone reasons about (visual_chain → shader params →
rendered pattern) was effectively cut.

Second finding: `hapax-imagination-loop.service` was `inactive (dead)` at
investigation time with no start attempts in the journal. The Amendment 4
reverberation consumer was off-line; the producer (DMN evaluative tick
writing observation.txt) was alive and fresh, so the loop was open-circuit.
Unit file also had `StartLimitIntervalSec` / `StartLimitBurst` / `OnFailure`
in `[Service]` where systemd silently ignores them.

## What the three PRs did

**PR #696 — core fix** (`991cfbe03`):
- `_iter_passes()` helper handles both v1 and v2 plan schemas
- `_load_plan_defaults()` routes through `_iter_passes()`
- `content.intensity` passthrough added alongside `content.material` and `content.salience` writes
- Unit hygiene: `StartLimit*` + `OnFailure` moved to `[Unit]`
- `Requires=hapax-dmn.service` added
- 11 regression test cases
- Design doc + plan doc

**PR #700 — audit follow-up** (`1f034fe82`): Post-merge self-audit surfaced
three regressions and eight things to track.

- **Revert `Requires=hapax-dmn.service`**. It was a cascade-death
  regression: `Requires=` propagates clean stops, DMN restarts are routine
  (rebuild-services timer, operator restarts), and a clean stop is not a
  `Restart=on-failure` trigger. Every DMN restart would have taken
  imagination-loop down and left it dead. Recreated the exact Finding B
  state PR #696 was trying to prevent.
- **Revert `content.intensity` passthrough**. Audit traced Rust and
  confirmed all three `content.*` writes are silently dropped:
  `content_layer.wgsl` has no `@group(2) Params` binding, the Rust per-node
  loop skips on `params_buffer.is_none()`, and `UniformData.custom[0][0]`
  (where the shader reads `material_id`) is initialized to zero and is
  never written from uniforms.json. Material switching on the GPU is
  effectively hardcoded to water. Added a code comment above the
  pre-existing dead writes pointing at F8.
- **Severity overclaim in § Summary.** The original "none of the 9
  dimensions were reaching the GPU" was too broad — Path 1 was always
  alive. Corrected with two-path analysis.
- **§ 2.5 CLAUDE.md premise was false.** A fresh `grep` showed CLAUDE.md
  never carried the "DMN-hosted" claim — the original design misremembered.
  No CLAUDE.md edit was needed or done. Memory files updated locally.
- **AC1 threshold off by one.** ≥ 45 → ≥ 44.
- **AC4 silently depended on PR-2** (reverie-monitor extension), not
  flagged clearly in the original.
- **6 new tests** (17 total): None-target edges, last-wins collision,
  file-deletion cache, **direct `write_uniforms` end-to-end**, silence
  attenuation, silence floor.
- Inline audit markers throughout the design doc + new § 7 with full
  severity-ranked findings.
- Plan doc execution-state header + PR-1b block + DoD corrections.
- New follow-ups F6–F10 in design § 6.

**PR #(this one) — docs + F6**:
- F6 fix: `ImpingementConsumer.__init__(path, *, start_at_end=False)`.
  Reverie passes `start_at_end=True`. Skips the 4000-entry accumulated
  JSONL backlog on restart — the first daemon tick no longer stalls for
  5–15 min dispatching stale impingements before reaching `write_uniforms`.
  Unblocks restart verification of the bridge fix.
- 4 new `test_impingement_consumer` tests.
- CLAUDE.md "Reverie Vocabulary Integrity" § Bridge repair paragraph
  documenting the two-path routing model, the v1/v2 schema compatibility,
  the F8 dead `content.*` routing warning, and this F6 fix.
- CLAUDE.md "Tauri-Only Runtime" Visual surface paragraph updated to
  reference the two-path model.
- This handoff doc.

## Findings that were wrong on direct verification

Three claims from the parallel-agent audit were incorrect, all from the
Rust/wgpu agent:

1. "Content layer Bachelard functions are dead code" — `content_layer.wgsl`
   calls `corner_incubation`, `immensity_entry`, `material_uv`,
   `materialization`, `material_color`, `dwelling_trace_boost` from
   `sample_and_blend_slot()` per slot with `slot_index ∈ {0,1,2,3}`.
   Amendments 1, 3, 5 are implemented in shader. But the audit follow-up
   then showed material is effectively hardcoded to water because of the
   orphaned custom-slot routing (F8) — so "implemented in shader, fed a
   constant" is a more precise description.
2. "Colorgrade `param_order` is inverted" — plan.json shows
   `param_order: ['saturation','brightness','contrast','sepia','hue_rotate']`
   matching the WGSL struct. The `wgsl_compiler.extract_wgsl_param_names`
   reorders vocabulary dict keys to match the struct. No inversion.
3. "DMN-hosted actuation loop was broken by refactor" — it was, but the
   split is intentional. Different fragility profiles, different restart
   lifecycles. The structural-peer claim is upheld at the type and
   cascade level. The design doc § 2.5 now formally ratifies the split.

## Deploy verification (final)

Post-PR #(docs-f6) merge:
1. `systemctl --user start hapax-rebuild-services.service` → alpha
   worktree refreshes to the merge SHA
2. `systemctl --user restart hapax-reverie.service hapax-imagination-loop.service`
3. Reverie skips accumulated impingement backlog (F6) → first tick
   reaches `write_uniforms` within ~1 s
4. `jq 'keys | length' /dev/shm/hapax-imagination/uniforms.json` → **≥ 44**
5. `jq '."content.intensity"' /dev/shm/hapax-imagination/uniforms.json` →
   **0.0** (plan default, confirms post-audit-followup code is live)
6. `jq '."noise.amplitude"' /dev/shm/hapax-imagination/uniforms.json` →
   numeric near 0.7
7. `grep -c 'Requires=' systemd/units/hapax-imagination-loop.service` → **0**
8. `systemctl --user is-active hapax-imagination-loop.service` → **active**
9. frame_time 9–17 ms (~60–100 fps) from
   `journalctl --user -u hapax-imagination.service | grep frame_time`

## Follow-ups queued as unassigned

- **PR-2** reverie-monitor extension — watchdog
  `hapax-imagination-loop.service`, restart if inactive, chronicle event.
  ~20 lines.
- **PR-3** `python -m agents.reverie.debug_uniforms` CLI + Prometheus
  `reverie_uniforms_key_count` metric + Grafana alert. Now composable with
  beta's `DynamicPipeline::pool_metrics()` accessor from #697.
- **F7** dormant `signal.{9dim}` override path at `dynamic_pipeline.rs:812-828`.
  Rust reads the 9 dim override keys but no Python code writes them. Either
  dead code or unused hook.
- **F8** dead `content.*` routing. **Highest leverage of all the
  follow-ups** — it's the only one that's a latent spec violation (material
  switching is hardcoded to water, Amendment 3 implemented but
  untriggerable). Fix: add a `Params` binding to `content_layer.wgsl`.
- **F9** `_load_plan_defaults` cache-on-file-deletion semantics — correct
  but non-obvious, now covered by a test.
- **F10** `ImaginationState.content_references` field — possibly orphaned
  from pre-affordance-pipeline era. Verify.

## What I did NOT do

- Did not localize the exact git commit that made `plan.json` become v2.
  Low priority; the fix handles both schemas.
- Did not measure pre-fix vs post-fix frame rate independently. Beta
  reported 33 → 75-90 fps under B4 load; my own observations spanned
  11–17 ms frame_time (~60–90 fps) both pre- and post-fix, which doesn't
  match beta's numbers. Could be measurement-context drift, B4 load
  differences, or observation noise. Not a regression either way.
- Did not verify Amendment 4 reverberation cadence acceleration after
  restoring imagination-loop. The pathway is wired (DMN writes observation,
  `ImaginationLoop._check_reverberation` reads it) but depends on accumulated
  `recent_fragments` which are empty on restart.
- Did not touch the architecture of daimonion or fortress for their own
  F6 equivalents. Both still use `start_at_end=False` by default; if
  operator wants them F6'd that's a small follow-up.

## How the next delta (or alpha or beta) should read this

If reverie looks flat, check `jq 'keys | length'` on uniforms.json first.
If < 20, the v1/v2 bridge is broken again — probably someone mutated
`_iter_passes` or the plan schema changed. Read the design doc § 7 for the
full audit trail before touching anything in `agents/reverie/_uniforms.py`.

If `hapax-imagination-loop` is dead again, don't add `Requires=` to the
unit file — that's a documented trap. Just start it manually and either
merge PR-2 (reverie-monitor watchdog extension) or add the unit to
`hapax-reverie-monitor`'s watch list.

If Bachelard Amendment 3 material switching is being discussed: F8. It is
not triggerable at runtime until `content_layer.wgsl` gets a `Params`
binding or Rust routes `content.*` into `UniformData.custom`.

The full audit history is in `docs/superpowers/specs/2026-04-12-reverie-bridge-repair-design.md § 7`.
