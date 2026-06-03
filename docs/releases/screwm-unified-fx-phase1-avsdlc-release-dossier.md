# AVSDLC Release Dossier — Screwm Unified-FX Phase 1

Task: `20260603-screwm-unified-fx-phase1` · Authority: CASE-SCREWM-QUAKE-MIGRATION-20260523 · Follows #3837
Axes: visual, audiovisual · Risk: T3 (aesthetic_theory_sensitive, audio_or_live_egress_sensitive)
Spec: `docs/superpowers/specs/2026-06-03-screwm-unified-fx-phase1.md`

## Release thesis: behavior-preserving by construction

Phase 1 locks the unified geometry+content effect abstraction with `rutt_etra` as the
dual-domain existence proof. **It does NOT change live visual or audiovisual output.** Every
implementable step is behavior-preserving until Phase 2 drives the recruiter:

- `R_BlendView_N` ships with a `NULL, 0` caller → **pixel-identical** to the existing
  single-pass `R_BlendView` (backward-compat proof).
- Geometry `rutt_etra` (`opRuttEtra_luma_height`) is **stubbed-not-activated** — `hpxDisp`
  remains the sole always-applied vertex operator; the second operator is gated behind a
  default-off `HapaxDrift_RuttEtraEnable` cvar.
- The diagnostic-canary shader overrides (`combined_crc59807.glsl` / `crc27804.glsl`) stay
  **byte-identical** — no screen-space production override is (re)introduced; expression
  remains geometry-bound.
- The geo cvar drive wire only emits/applies under the existing `is_live` SlotDrift gate.
- Schema / CI / contract changes are data + test only.

The visual/audiovisual **witness IS the backward-compatibility proof**: for a behavior-preserving
increment, the evidence is verified absence-of-change.

## Evidence approach (collected per increment, appended below before ready-for-merge)

1. **Offscreen frame parity** — via the xvfb harness, capture the screwm frame on
   `/dev/video50` (post `hapax-obs-video50-yuyv-compat-bridge.service`, the broadcast device)
   with the Phase 1 build vs the pre-Phase-1 build; assert pixel-identity for the
   default-driven path (`pass_count=0`, RuttEtraEnable off).
2. **Engine backward-compat unit proof** — `R_BlendView_N(..., NULL, 0)` ≡ `R_BlendView` capture.
3. **Canary integrity** — `test_screwm_shader_effects_are_diagnostic_screen_space_only` stays
   green after any shader-CRC regeneration (byte-exact diagnostic markers preserved).
4. **No audio-egress change** — Phase 1 touches no audio path; the golden chain and
   `scripts/hapax-audio-routing-check` are unaffected (asserted by absence of audio-path edits).

## Increment evidence log

- **STEP 1 (schema) — landed `e3b5ab0f2`:** data-model only (`domain/stage/host_arity` on the
  manifest + OperationalProperties, serialized through both Qdrant writers). No rendered output;
  nothing consumes `domain` yet. Round-trip test pins both serialization paths. 57 affordance
  tests green. **Visual witness: N/A (no rendering touched).**
- **STEP 7 (CI visibility) — landed `6a3158776`:** test-only + ci.yml — the port-owner gate joins
  the PR-admission slice; manifest invariants stay in the merge-queue suite. No source/runtime/render
  change. **Visual witness: N/A.**
- **STEP 0a (CRC guard) — landed `75590e9cf`:** new repo-side gate script enforcing the canary
  prime directive pre-build. No engine edit, no render change. **Visual witness: N/A.**
- **Engine Commit 1 (CRC-safe gl_rmain.c):** geo cvar `CF_SERVER` reflag, `USERUTT_ETRA`
  SHADERSTATICPARM plumbing (inert until the shader references it; default-off cvar),
  `R_BlendView_N` with a `NULL,0` caller (≡ `R_BlendView`, pixel-identical), `r_blendview_pass_t`
  typedef. Re-exported into the deploy patch. **Verified:** compiles clean (`darkplaces-sdl`
  links); the `shader_glsl.h` patch section is **byte-identical to pre-edit** (CRC-safe — canaries
  unaffected, `check-shader-crc-override.sh` OK); migration-contract + port-owner tests green.
  **Visual witness: behavior-preserving by construction** (NULL/0≡R_BlendView; the static-parm
  emits a no-op string until the shader pass references `USERUTT_ETRA`). Offscreen frame-parity
  deferred — the default-driven path is provably unchanged and the live device is shared with the
  running screwm.
- **Engine Commit 2 (rutt_etra content operator, default-off):** `shader_glsl.h` gains the
  `opRuttEtra_luma_height` fragment operator, a `USERUTT_ETRA`-gated MODE_POSTPROCESS content pass
  (luma-height UV displacement, dialect-matched to the canary: `dp_texture2D(Texture_First, …)` /
  `TexCoord1.xy` / `dp_FragColor` / `UserVec3`), and a `USERUTT_ETRA`-guarded `UserVec3` declaration.
  This is the **content side of the dual-domain proof**, routed through Commit 1's `R_BlendView_N`
  seam → builtin MODE_POSTPROCESS → `USERUTT_ETRA` permutation. **Default-off** (no
  `r_glsl_postprocess_ruttetra_enable`), so the GLSL permutation never compiles and release stays
  geometry-bound — consistent with the established opt-in screen-space pattern (the canary itself is
  one: "Release-grade expression is geometry-bound in CSQC; this path is opt-in"). Re-exported into
  the deploy patch (936 lines; 8 `opRuttEtra`/`USERUTT_ETRA` markers). **Verified:** compiles as
  valid C (the `#include`-based CRC harness built clean); guard green (canaries byte-identical,
  no production override); 91 contract/port-owner/wgsl-coverage gates pass — incl. the
  patch-visibility grep for `opRuttEtra_luma_height`. **Visual witness: behavior-preserving by
  construction** (default-off → permutation uncompiled → release path unchanged).

### Ground-truth finding (CRC mechanism) — corrects the runbook's CRC-regen step

The builtin shader CRC drives override loading: the engine loads
`glsl/combined_crc<CRC_Block(builtinstring)>.glsl`, where `builtinstring` is the concatenation of
the `shader_glsl.h` literal array (`gl_rmain.c:698` `{ #include "shader_glsl.h" 0 }`). I replicated
the engine's exact `CRC_Block` (CRC-16-CCITT, poly 0x1021, init 0xffff, no reflect/final-xor;
self-test "123456789"→0x29B1) via the real C preprocessor and measured every build clone:

| State | builtin CRC | override loaded |
|-------|------------|-----------------|
| All 18 historical builds, 2026-05-27 → 06-01 | **59807** | `combined_crc59807.glsl` ✓ (canary active) |
| Deployed build, **today 2026-06-03 15:18** (the #3837 density-drift deploy) | **9143** | none — **canary orphaned** |
| This Commit 2 (USERUTT_ETRA edits) | **36975** | none — still orphaned |

**The diagnostic canary stopped loading today**, when the #3837 shader change moved the builtin CRC
off 59807 without a matching `combined_crc9143.glsl`. The contract test pins canary *file content*,
not *runtime loading*, so the orphaning was silent. **Release impact: nil** — the canary override is
the opt-in screen-space effect suite (room_absorption/prismatic/fisheye/feedback), explicitly
non-release; release expression is geometry-bound (CSQC vertex drift), which is unaffected whether
the canary loads or not.

**Why this commit does NOT regenerate the canary:** the runbook's "add a byte-identical
`combined_crc<NEWCRC>.glsl`" assumed the canary was loading under 59807. It is not (since today).
A byte-identical copy at 36975 would make the engine load the **stale pre-#3837 59807-era screen-space
suite** — a real regression. The correct behavior-preserving action is exactly what this commit does:
leave the canary files byte-frozen, let the builtin (geometry-bound) be used.

**Tracked follow-ups (need an engine run — `r_glsl_dumpshader` — deferred: device shared with the
live screwm):** (1) re-arm the canary by regenerating `combined_crc<currentCRC>.glsl` from the
*current* builtin + the diagnostic block, so the shader-load tripwire is live again; (2) add an
orphaning-detection gate (assert the patched builtin CRC has a matching override) to close the
silent-orphaning gap that the file-content contract test missed.

- (subsequent increments append their parity captures here before the draft → ready transition)
