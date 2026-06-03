# Screwm Unified-FX — Phase 1 Spec (executable, ground-truth-validated)

Builds **from** the unified-fx solution basis. Synthesized by the screwm-phase1-readiness
workflow (5 ground-truth agents + 3 adversarial verifiers, 2026-06-03); all verifier
corrections folded in. Authority: CASE-SCREWM-QUAKE-MIGRATION-20260523. Follows #3837.

**Goal:** Lock the unified geometry+content effect abstraction end-to-end with `rutt_etra`
as the dual-domain existence proof, in **one mergeable, behavior-preserving increment**.

## Prime directive (GROUND TRUTH — non-negotiable)
The screen-space production override was deliberately downgraded to a **diagnostic
load-canary**; release-grade expression is **geometry-bound** (vertex `hpxD()` drift).
**Do NOT re-introduce a screen-space production override.** `combined_crc59807.glsl` /
`crc27804.glsl` stay byte-identical canaries; content effects compile as a **separate**
MODE_POSTPROCESS program lineage.

**Topology honored:** `coupling.qc` is a LISTEN SERVER → it CAN `cvar_set` CF_CLIENT cvars.
Geo cvar wire is ABSENT not blocked. DP output `/dev/video52` ("DarkPlaces"); broadcast
consumes `/dev/video50` (post `hapax-obs-video50-yuyv-compat-bridge.service`). Screwm
contract tests run ONLY in `test-full-shard` (merge_group) — invisible on PR pushes.

## Build order (corrected)

### STEP 1 — Manifest schema (IMPLEMENTABLE NOW) ✅ DONE
- `agents/shaders/nodes/rutt_etra.json` — `stage`/`domains:["both"]`/`displacement{kernel,c1_safe,height_from}`/`host_arity{wgpu:32,dp_postprocess:16}`/`cost_class`. (Distinct from the flat `params` dict.)
- `shared/affordance.py` — `domain: Literal["content","geometry","both"]="content"` on OperationalProperties.
- `shared/affordance_pipeline.py` — `"domain"` in **BOTH** payload writers (index_capability + index_capabilities_batch). Round-trip test pins both (a miss silently falls back to "content").

### STEP 0 — P0 precondition gates (IMPLEMENTABLE NOW)
- **0a CRC orphan guard** — new `scripts/check-shader-crc-override.sh`. **Corrected threat model:** the loader builds `glsl/combined_crc<builtincrc>.glsl` from the *current* builtin CRC (`gl_rmain.c:1111`); editing `shader_glsl.h` *orphans* the canaries (they stop loading), it does not silently load stale. Two-pronged gate: (1) ORPHAN GUARD — fail if any `combined_crc*.glsl` suffix ≠ current builtin CRC (regenerate to new CRC, never delete — a byte-exact contract test pins them); (2) NO-PRODUCTION-OVERRIDE GUARD — fail if regen reintroduces screen-space production expression; assert the diagnostic markers SURVIVE regen.
- **0b geo cvar CF_SERVER reflag** — dp-fork `gl_rmain.c:275-280`, 6 cvars `{CF_CLIENT|CF_ARCHIVE}`→`{CF_CLIENT|CF_SERVER|CF_ARCHIVE}`. Purely additive.
- **0c XVFB harness** — `darkplaces-v4l2-xvfb.sh` (:82→ximagesrc→v4l2sink /dev/video52); Xvfb reaped on exit; WatchdogSec.

### STEP 2 — Geometry target
- **2a (NOW)** dp-fork `shader_glsl.h` after `hpxDisp()` (~221) — `opRuttEtra_luma_height(p,lum,u)` → `vec3(0, lum*u*0.01, 0)` (C1-safe). Reuses HAPAXDRIFT bit 32, NO new permutation bit. ⚠ shader_glsl.h is a **C string-literal array** — emit as `"...\n",` lines.
- **2b (DESIGN-ONLY)** hook at `shader_glsl.h:1394` (macro `USEHAPAXDRIFT`). Document+stub, do NOT activate — `hpxDisp` always-applies; a second always-on op double-expresses. Decision: gate behind `HapaxDrift_RuttEtraEnable` cvar (Phase 2 = per-surface/currency mux).
- **2c (DESIGN-ONLY)** vertex stage has NO sampler — geometry form uses `hpxVNoise` proxy; `height_from:"luma"` is content lineage only. Declared `both`, proxied geometry.

### STEP 3 — Content target (R_BlendView N-pass + rutt_etra MODE_POSTPROCESS)
- **3a-pre (NOW — the invisible work)** USERUTT_ETRA needs full SHADERSTATICPARM plumbing: (1) `SHADERSTATICPARM_POSTPROCESS_RUTTETRA=15` in the enum (gl_rmain.c:~962); (2) bump `SHADERSTATICPARMS_COUNT` 15→16; (3) `r_glsl_postprocess_ruttetra_enable` cvar (~:288) + register (~:3795); (4) detect clause in `R_CompileShader_CheckStaticParms` (~:998); (5) `R_COMPILESHADER_STATICPARM_EMIT(...,"USERUTT_ETRA")` (~:1029). Without all 5 the `#ifdef` is dead code.
- **3a (NOW)** generalize `R_BlendView` (gl_rmain.c:5769, single call site :6245) → `R_BlendView_N(passes, n)`; KEEP old. Per-pass: `R_RenderTarget_Get` scratch (bloom precedent :5581-5624), bind prev as Texture_First, set UserVecs, draw, cycle; final→screen. **Phase 1 caller passes `NULL,0` → pixel-identical (backward-compat proof).**
- **3b (NOW)** rutt_etra content fragment — **inside USEPOSTPROCESSING (before USEBLOOM @427), NOT after USEGAMMARAMPS** (else samples gamma-corrected buffer). UV normalized [0,1]; `viewport_height=1.0/PixelSize.y`; map 4 params into UserVec3.
- **⚠ CRC GATE — CORRECTED (2026-06-03 ground-truth, supersedes the original byte-identical-regen instruction):**
  this shader edit changes the builtin CRC (measured **9143 → 36975** via the engine's exact
  `CRC_Block` = CRC-16-CCITT poly 0x1021/init 0xffff, reproduced offline through the real C
  preprocessor; self-test `123456789`→0x29B1). **Do NOT regenerate a byte-identical
  `combined_crc<NEW>.glsl`.** VALIDATED across 18 build clones that the canary stopped loading on
  2026-06-03 15:18 when the #3837 deploy moved the builtin CRC **59807 → 9143** with no matching
  override — the deployed engine already uses the geometry-bound builtin, not the canary. A
  byte-identical copy at the new CRC would make the engine load the **stale pre-#3837 59807-era
  screen-space suite** (a regression). Correct, behavior-preserving action: leave
  `combined_crc59807/27804.glsl` byte-frozen, let the builtin run; `check-shader-crc-override.sh`
  stays green (it pins canary *file* identity, not loading). Re-ran the contract + guard locally —
  green. **Follow-ups (need `r_glsl_dumpshader`, offscreen xvfb — no device conflict):** re-arm the
  tripwire from the *current* builtin; add an orphaning-detection gate (the file-content contract
  test missed the silent orphan). Full evidence: the AVSDLC dossier.

### STEP 4 — Drive wire (IMPLEMENTABLE NOW)
- **4a** `darkplaces-state-export.py` near `_slotdrift_local_effect_proxy_mix`(:1100)+`is_live`(:2081) — emit `data/drift-geo-{amp,ampmax,freq,speed,swirl,content}.txt` from the same `spatial_pressure` (is_live-gated). Additive.
- **4b** `coupling.qc` (density reads :347-355) — 6× `coupling_read_float`(@135)+EMA+range-map+`cvar_set("hapax_drift_geo_*")` (cvar_set proven @190-217).
- **4c (corrected)** `coupling_write_uservecs` is fixed-16-arg, **preset-indexed** (:179, tuples :258-294). Phase 1 **hardcodes** rutt_etra's 4 params as literals into ONE chosen review-preset's u3* slots (recruiter-conditional = Phase 2).

### STEP 5 — Legibility floor (DESIGN-ONLY, blocks geometry release)
- **5f** cull-bbox↔ampmax: dp-fork `model_shared.h:~453-457` → `AMPMAX_SAFE=min(bbox extent)*(1-CULL_MARGIN)`; export via drift-field hook (:3113); shader clamp (:232-234).
- **5g** rest-pose divergence metric: `final_frame_classifier.py:159-165` can't tell deformed-legibly from shredded. Spec `0.4·IoU + 0.3·(1−max_disp/AMPMAX_SAFE) + 0.3·edge_corr`, floor ≥0.70, AND-gated. → geometry amplitude stays at conservative defaults until implemented.

### STEP 6 — Perf gate (IMPLEMENTABLE NOW)
- **Corrected:** classify on `/dev/video50` (POST bridge — the broadcast device), not video52. Keep video52 raw sanity. Document the bridge's `Conflicts=studio-fx-output.service` + YUYV chroma-subsampling risk on scan-lines. Loop: frame→classifier (0.45/0.25 floor). Content gates now; geometry deferred to 5g. Baseline N-pass cost (pass_count=1 vs 0) under TabbyAPI contention.

### STEP 7 — CI visibility (IMPLEMENTABLE NOW — LEGAL path)
**Do NOT add a parallel required workflow** — violates 3 governance pins (PR slice asserted = exactly 4 files; standalone path-filtered required checks forbidden; `REQUIRED_BRANCH_PROTECTION_JOBS` closed tuple).
- **7a** add `TestDomainStageHostArityFields` + `TestBothBasesGeometryContentCoverage` to `tests/test_wgsl_node_affordance_coverage.py` (xfail-visibility @105; only rutt_etra tagged; MIN_REGISTERED_NODES=60).
- **7b** add those test files (AND the diagnostic-canary subset of `test_screwm_quake_migration_contract.py`) to the **EXISTING** PR-admission slice in `ci.yml` (~:690), AND update `tests/ci/test_python_test_throughput_policy.py`'s literal assertion + `config/ci/python-test-throughput-evidence.yaml` rollout_policy **in the same commit**. Keep inside the existing `test` job.

### STEP 8 — Register new owners in the port-owner contract (NEW)
Phase 1 adds owners (geo `cvar_set` + `drift-geo-*.txt`; `R_BlendView_N` + `opRuttEtra`). **Update `config/screwm-aggregate-port-owners.json`** + run `tests/scripts/test_screwm_aggregate_port_owner_gate.py` locally (merge-queue-only) before pushing. This is the *actual* screwm gate.

### STEP 9 — Deploy durability (NEW)
Live DP runs from the SCRATCH dp-fork, not the merged tree. Name + gate the
`patch → ensure-darkplaces-live-texture-build.sh (from the merged commit tree) → live binary`
path so the merged patch is provably re-applied. Until named, the engine increment is mergeable-but-not-deployed.

## Ratified design decisions (do not gate on operator)
1. Geometry activation = static `HapaxDrift_RuttEtraEnable` cvar (Phase 2 = per-surface/currency mux).
2. Geometry luma = `hpxVNoise` proxy; `height_from:"luma"` is content lineage only.
3. rutt_etra owns UserVec3 in Phase 1; per-effect demux is Phase 2.
4. `R_BlendView_N` ships `NULL,0` caller (backward-compat-identical); recruiter population is Phase 2.

## Mergeability guarantee
Every implementable step is behavior-preserving by default — `R_BlendView_N`≡`R_BlendView` until the
recruiter populates passes (Phase 2); geo wire only fires under `is_live`; geometry rutt_etra is
stubbed-not-activated; canaries stay byte-identical. Ships the unified abstraction end-to-end
(content live, geometry declared+proxied) without changing live visual output until Phase 2 drives it.

## Commit sequencing (one branch, verifiable chunks) — status 2026-06-03
1. **Schema + serialization safeguard** (STEP 1) — ✅ DONE (`e3b5ab0f2`).
2. **CI visibility + port-owner** (STEP 7) — ✅ DONE (`6a3158776`); **STEP 0a CRC guard** — ✅ DONE (`75590e9cf`).
3. **Engine** — ✅ DONE: Commit 1 `1feabd35a` (geo cvar CF_SERVER reflag, `R_BlendView_N` NULL/0≡R_BlendView, USERUTT_ETRA SHADERSTATICPARM plumbing, `r_blendview_pass_t`); Commit 2 `cd4b4ac7b` (`opRuttEtra_luma_height` + USERUTT_ETRA MODE_POSTPROCESS content pass + UserVec3, default-off). **CRC-regen gate REMOVED** — ground-truth showed the canary is already orphaned (corrected STEP 3b); no regen.
4. **Drive wire + perf gate + deploy path** (STEP 4, 6, 9) — PENDING. STEP 4 mutates the LIVE `coupling.qc` (722 ln) + `darkplaces-state-export.py` (2416 ln) → deserves a fresh focused session (drives live geometry); STEP 6/9 need offscreen engine runs.
5. **Legibility-floor** (STEP 5) — design recorded above (5f/5g); the conservative geo defaults (amp=24 ≤ ampmax=36, content=5 — below the floor) are pinned in `test_screwm_quake_migration_contract.py` so any increase is a conscious decision that requires implementing 5f/5g first.

**PR #3870 (draft):** chunks 1–3 landed, CI-green, behavior-preserving by construction. Marking
ready needs real offscreen frame-parity evidence (chunk 4 perf/deploy harness) + the canary re-arm.
