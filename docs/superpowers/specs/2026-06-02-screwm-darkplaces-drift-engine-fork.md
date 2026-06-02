# Screwm — DarkPlaces/QuakeC Drift-Engine Fork (GPU drift on EVERY surface)

**Date:** 2026-06-02
**Authority:** CASE-SCREWM-QUAKE-MIGRATION-20260523 · task `20260529-screwm-fullest-expression-build` (PR #3837)
**Status:** Design / buildable. Source-grounded against `~/.cache/hapax/darkplaces-live-texture/src`.
**Operator mandate (verbatim intent):** "drift + ALL previous compositing/effects tech FULLY REALIZED, GPU-resident, NOT CPU-bound; drift EVERYWHERE with ENDLESS VARIETY; except 4th wall. Fork DarkPlaces/QuakeC and adopt it fully — bake in whatever the vision needs. Go straight to the drift-everywhere architecture."

## Why this exists

DarkPlaces ingests live BGRA from `/dev/shm` as named live textures with **no engine shader stage**, so today drift only reaches the 14 media/ward live-texture slots (`screwm_media_drift`). The **spatial layer** (BSP floors/walls/ceilings/grid/AoA-lattice/edges) is rendered native with **no drift**, faked by CPU-bound CSQC (~250–400 `adddynamiclight`/frame + immediate-mode `R_BeginPolygon` ribbons + 307 `data/*.txt` reads/0.5s on the render thread). That is the operator's "NOTHING" and "CPU-bound."

**The fix: add an engine shader stage.** DarkPlaces already runs every world surface + model through its embedded GLSL (`builtinshaderstrings`/`shader_glsl.h`, permutation system, bound per-surface by `R_SetupShader_Surface`). We fork it: a `HAPAX_DRIFT` permutation + drift-currency uniforms + a drift-field texture sampler → every flagged BSP face / model / AoA-lattice drifts on the GPU in the engine's own render, world-bound, never fourth-wall.

## Aesthetic register (the target)

Dark breathing luminous-wireframe VOID. Effervescent, synthwave-shifting, drift-reactive surfaces; **endless variety** from three multiplied axes (per-pixel world position × daemon drift-field substrate × per-zone currency). Reactivity SPATIAL/TONAL/CYCLIC only — **never** a global luminance flash (anti_visualizer). Operator forks locked: "shallows" baseline (always slowly transiting), some standing neon accents over a mostly-desaturated lit field, distinct per-facet AoA content, fixed atmospheric palette, OARB nested inside AoA.

## Five-stage GPU-resident architecture (all world-bound, none 4th-wall)

1. **Engine drift stage** — `SHADERPERMUTATION_HAPAXDRIFT` (bit 32) in `shader_glsl.h`. VERTEX sub-stage: model-space `Attrib_Position` displacement BEFORE the MVP multiply (world-bound edge/geometry motion); same offset in the depth/shadow main so silhouettes/shadows track. FRAGMENT sub-stage: after lightmap+glow+fog, before `dp_FragColor` — luma-preserving hue rotation, chroma-roll, standing-neon edge accent, effervescence sparkle, scrim-floor weave; all gated by `signal_presence = smoothstep(luma(color))` so empty void never lights; every time term is `sin(ClientTime + worldpos)` (never `color.rgb *= envelope`).
2. **Drift-field daemon** — headless `DynamicPipeline` (the 62-node reverie vocab) on the **5060 Ti (GPU1)**, running the 8 temporal nodes (diff/echo/feedback/fluid_sim/reaction_diffusion/slitscan/stutter/trail) + Class-A generators → emits `/dev/shm/hapax-compositor/quake-drift-field.bgra` (256²/512² BGRA8) + `quake-drift-currency.f32`. The endless-variety substrate; sole drift-currency writer (retires the 307 `data/*.txt`).
3. **Surface flagging** — `MATERIALFLAG_HAPAXDRIFT 0x00400000` (the one free low bit) set at load time via (a) `.shader` keyword `hapax_drift <zone> <amp> [palette] [mode]` (per-facet AoA control), (b) `drift_*` texture-name fallback (already authored), (c) global default-on gate in `R_GetCurrentTexture` on `MATERIALFLAG_WALL` with a sky/HUD/OARB-interior exclusion predicate ("drift EVERYWHERE except 4th wall", opt-out style).
4. **QC retirement** — gut the CPU-bound CSQC/SSQC drift; daemon owns the hot loop. QC keeps clearscene/addentities/renderscene/camera only.
5. **Media path unchanged** — `media_drift.wgsl` stays the home for content-bound effects; OARB keeps its live-texture path, excluded from geometry drift.

## Engine modifications (exact, all into `assets/quake/darkplaces/hapax-live-texture.patch`)

| File | Location | Change |
|---|---|---|
| `render.h` | 73-105 | `#define SHADERPERMUTATION_HAPAXDRIFT (1ull<<32)` after OCCLUDE; `SHADERPERMUTATION_COUNT` 32u→33u |
| `gl_rmain.c` | 1123-1125 | `vert/geom/fragstrings_list[32+5+…]` literal `32`→`33` (all three) |
| `gl_rmain.c` | 742 | append `{"#define USEHAPAXDRIFT\n", " hapaxdrift"},` as 33rd `shaderpermutationinfo[]` row (index==bit order) |
| `gl_rmain.c` | struct `r_glsl_permutation_s` ~850 | add `loc_HapaxDrift_Currency`, `loc_HapaxDrift_Field2`, `tex_Texture_HapaxDriftField`, `loc_Texture_HapaxDriftField` |
| `gl_rmain.c` | qglGetUniformLocation ~1289 | look up the two uniforms + the sampler; init `tex_…=-1`; append sampler-unit claim LAST (preserve existing unit numbering) |
| `gl_rmain.c` | SetPermutationGLSL ~1478 | after ClientTime upload, `qglUniform4f` the two currency vec4s from `hapax_drift_currency[]` globals (runs every draw) |
| `gl_rmain.c` | R_SetupShader_Surface ~1665 | after trippy gate: `if (hapax_drift_enable.integer && (rsurface.texture->currentmaterialflags & MATERIALFLAG_HAPAXDRIFT)) permutation |= …HAPAXDRIFT;` + `R_Mesh_TexBind` the drift-field (fallback `r_texture_white`) |
| `gl_rmain.c` | R_GetCurrentTexture ~6854 | after `currentmaterialflags=basematerialflags`: cvar gate (`!hapax_drift_enable` strips flag) + optional default-on force-set on WALL minus exclusion predicate |
| `gl_rmain.c` | cvar table ~119-200 / init ~3587 / R_RenderView ~5956 | register `hapax_drift_*` cvars; add `R_HapaxDriftField_Update()` (mtime-gated `/dev/shm` BGRA read → dedicated `TEXF_ALLOWUPDATES` rtexture, NOT a skinframe; + currency blob → globals) beside `R_HapaxLiveTexture_Update` |
| `model_brush.h` | ~137 | `#define MATERIALFLAG_HAPAXDRIFT 0x00400000` (only free low bit) |
| `r_qshader.h` | shader_t COMPARE span | `qbool dphapaxdrift; int hapaxdrift_zone; float hapaxdrift_amp; int hapaxdrift_palette; int hapaxdrift_mode;` |
| `model_shared.c` | dp* chain ~1992 / copy ~2485-2582 / no-shader fallback | parse `hapax_drift` keyword; OR `MATERIALFLAG_HAPAXDRIFT` into basematerialflags + copy params; `drift_*` name fallback derives zone/palette from suffix a/c/g/r; mirror fields + init defaults in ALL loaders |
| `shader_glsl.h` | TrippyVertex ~159-181; six vertex mains (199/231/431/499/546/642/1153); frag exit 1800 | `#ifdef USEHAPAXDRIFT` `HapaxDriftOffset()` pre-MVP on model-space `Attrib_Position` + `DriftWorldPos` varying + SAME offset in depth/shadow main; `HapaxDriftColor()` before `dp_FragColor` |

## Build sequence (each phase witnessed before the next)

- **P0 — permutation plumbing** (engine compiles, no visual): all render.h/gl_rmain.c plumbing + EMPTY `#ifdef USEHAPAXDRIFT` block. Witness: clean sha-stamped rebuild, `r_glsl_dumpshader` shows the slot, existing surfaces byte-identical.
- **P1 — SMOKE TEST**: `MATERIALFLAG_HAPAXDRIFT` + flagging; flag ONE surface; FRAGMENT-only hue rotation from `ClientTime` + a hardcoded currency cvar (no daemon, no field). Witness: that one surface shows slow spatial hue transit **anchored to geometry** (stays put when camera moves — the decisive not-4th-wall test); all others unchanged; **frame mean-luminance flat** (anti-visualizer); `hapax_drift_enable 0` removes it instantly.
- **P2 — field sampler + ingest**: `R_HapaxDriftField_Update` + sampler; fragment samples by `DriftWorldPos`; prove with a static test BGRA.
- **P3 — vertex sub-stage**: `HapaxDriftOffset` pre-MVP + depth/shadow match; edges breathe in world space, depth/shadows track, no cracks.
- **P4 — daemon**: DynamicPipeline temporal nodes on GPU1 → field + currency to `/dev/shm`; endless variety; GPU0 frame time unchanged.
- **P5 — fan-out**: global default-on gate + map-generator emits `drift_*` + `hapax_drift` .shader for the AoA lattice/zones (keyed to `config/screwm-spatiotemporal-framework.json`).
- **P6 — retire CSQC/SSQC**: `wards.qc` lights ~250-400→~12 standing; remove ribbon draws + 307-file poll; `coupling.qc` drift reads/uservec writes retired; pin `r_glsl_postprocess 0`; recompile BOTH `.dat`.

## Critical traps (must automate / spike)

- **CRC filename coupling (highest risk):** editing `shader_glsl.h` changes the builtin CRC → the loose `glsl/combined_crc<CRC>.glsl` overrides (27804/59807) no longer match and the engine SILENTLY runs the stale builtin. `ensure-darkplaces-live-texture-build.sh` MUST, after `make`, run the binary headless with `r_glsl_dumpshader` to emit the new-CRC combined file and regenerate BOTH copies. Iterate GLSL in the override first; bake into the patch when stable. Keep the shader-load canary (`combined_crc27804.glsl:624-632`).
- **COUNT/array-size desync:** bump `SHADERPERMUTATION_COUNT`, the three `[32+5+…]` literals, and the table row in ONE atomic hunk; add a build-time `table length == COUNT` check.
- **Vertex/depth desync:** apply the IDENTICAL `HapaxDriftOffset` in the depth/shadow main (invariant `gl_Position`, `shader_glsl.h:47`); small world-keyed amplitude (welded verts move identically; physics see static geometry — correct for an ambient void).
- **Anti-visualizer is GLSL-enforced + witness-gated:** luma-preserving hue/chroma only, all time terms spatial; release gate = whole-frame mean-luminance-vs-time **flat with local variance**.
- **Spikes before fan-out:** (a) RGBA16F TEXTYPE support in `r_textures.h` (else BGRA8 + dither); (b) confirm `aoa.mdl`/`aoa_sphere.mdl` reach `R_SetupShader_Surface` (not sprite/particle path); (c) audit CSQC-ribbon/`data/*.txt` consumers (HLS/director/ward-atlas) before P6.

## Containment / rollback / VRAM

Three-way gate: `hapax_drift_enable` cvar (instant global off), the MATERIALFLAG (per-surface), the permutation degrade loop (`gl_rmain.c:1451` strips HAPAXDRIFT FIRST on link failure → buggy drift vanishes, never crashes). Fail-to-black: absent field → `r_texture_white` (neutral); failed compile → surface renders without drift. Rollback = revert the patch hunk → `ensure-build` detects the sha change → clean rebuild from pristine upstream. **Zero new bytes on GPU0 (5090)** — engine adds one 256²/512² rtexture (≤1MB) + a few KB of programs; the daemon's temporal buffers live ONLY on GPU1 (5060 Ti). `HAPAX_DRIFT_QUALITY`/distance-LOD cvar caps worst-case vertex/permutation cost.

## Witness (release gate)

1. **GPU-resident:** `perf top`/CSQC profiling shows the retired `adddynamiclight`/`R_BeginPolygon`/poll gone; `nvidia-smi` shows daemon load on GPU1, GPU0 frame time flat; `r_speeds 1` shows drift on world batches on the static-VBO fast path (no `dynamicvertex` flip); no `GLSL … failed`.
2. **World-bound, not 4th-wall:** capture via `scripts/compositor-frame-capture.sh`; moving the camera, drift STAYS anchored to geometry; sky/HUD/OARB-interior show zero geometry drift.
3. **Not a flash:** whole-frame mean-luminance-vs-time flat with local spatial variance; any global sawtooth = fail.
4. **Reversible:** `hapax_drift_enable 0` removes drift live; patch revert → byte-identical pre-drift binary.

Full reader findings + synthesis: workflow `wf_1724c6e8-fbe` (this session). Aesthetic corpus + invariants: `[[project_screwm_fullest_expression]]` memory + `2026-06-02-screwm-compositor-codex-handoff.md`.
