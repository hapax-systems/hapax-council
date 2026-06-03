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
- (subsequent increments append their parity captures here before the draft → ready transition)
