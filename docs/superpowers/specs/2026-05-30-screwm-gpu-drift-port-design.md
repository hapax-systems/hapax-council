# Screwm Media-Drift GPU Port — Design Spec

**Date:** 2026-05-30
**Authority:** CASE-SCREWM-QUAKE-MIGRATION-20260523 · task `20260529-screwm-fullest-expression-build`
**Status:** Design (operator-greenlit 2026-05-30: "gpu port, fully researched, spec'd carefully done, use lanes where appropriate, go")
**Effort frame:** "Use the 5090/5060Ti for everything possible as it relates to compositing/video/pixel-pushing — using the CPU for that is silly."

---

## 1. Problem

The screwm render's 7 live-media producers (`scripts/quake-live-media-source.py`: 6 cameras + OARB youtube, plus the ward-atlas producer) each apply **per-pixel drift + projection in Python/numpy on every frame** (`scripts/quake_media_drift.py::apply_frame_drift`). Measured cost: **~3.8 CPU cores** (≈54% each ×7) at only **5–10 fps** per source — the decode is cheap; the numpy drift is the cost. Meanwhile the **5060 Ti sits at 0% util / ~14 GB free** and the 5090 at ~17%. Pixel-pushing on the CPU while the GPU idles is the inversion to fix.

**Non-goal:** cognition/LLM stay on CPU/their own GPU. This is purely the screwm pixel pipeline.

## 2. Key architecture fact (makes this clean)

The DarkPlaces engine (`assets/quake/darkplaces/hapax-live-texture.patch`) is a **plain BGRA blit**: `R_HapaxLiveTexture_ReadFrame` `fread`s a raw BGRA file from `/dev/shm/hapax-compositor/quake-live-*.bgra` and uploads it to the named texture. **There is no engine shader stage.** So if a GPU service writes the *same* `/dev/shm` slot paths with the drifted BGRA, **the engine is unchanged — no rebuild, no relaunch.** The drift simply moves from the Python producer (CPU) to a GPU service, upstream of the same file.

## 3. Data flow (target)

```
camera/OARB ─► producer (ffmpeg decode + projection)
                    │  writes RAW (undrifted) BGRA
                    ▼
        /dev/shm/hapax-compositor/quake-live-<slot>.raw.bgra
                    │
                    ▼
        hapax-screwm-media-drift  (NEW, wgpu, on 5060 Ti)
          per slot: upload → drift WGSL (DriftState uniforms) → readback → BGRA
                    │  writes DRIFTED BGRA (same path the engine reads)
                    ▼
        /dev/shm/hapax-compositor/quake-live-<slot>.bgra
                    │
                    ▼
        darkplaces engine (unchanged) blits the slot texture
```

The producer keeps decode + projection (cheap; the sphere-front UV warp for OARB is the only non-trivial projection and stays CPU for v1, or moves to the WGSL pass in v2 — see §9). It **drops the numpy drift** and writes the raw frame to a `.raw.bgra` sibling path. The GPU service owns the drift.

## 4. The drift to replicate (`apply_frame_drift`)

Single fragment pass per slot, in order, all gated by `intensity` (early-out ≤ 0.02):

1. **intensity** = `f(DriftState)` × `receiver_gain` × `intensity_scale` × `cadence_gain` (cadence from `fast_wave`/`slow_wave` = `0.5+0.5·sin(now·k + frame·k)`).
2. **reverie tonemap** (reverie receivers only): `_apply_reverie_tonemap` — luma-pivot contrast + saturation + `[1.08,0.68,1.12]` tint.
3. **chroma roll**: `red = roll(R, +dy,+dx)`, `blue = roll(B, −dy,−dx)`; `drift = sin/cos(phase)·chroma_px`; blend `chroma_mix` (camera-capped 0.52).
4. **feedback trails** (non-camera, needs previous frame): rolled previous × `feedback` factor.
5. **luma/saturation**: saturation boost (camera-capped 1.34).
6. **edge**: `|∂luma/∂x|+|∂luma/∂y|` → added to R/B (camera edge_gain 0.58).
7. **glitch blocks**: hash-seeded block displacements + tint (camera: fewer, capped mix).
8. **noise**: per-pixel normal noise → R/G/B (camera ×0.28).
9. **scanlines**: periodic horizontal rows → R/G/B (camera ×0.35).
10. **tonal pulse**: `rgb *= cyan_magenta·pulse + amber·(1−pulse)`.

**Per-receiver class** (`_receiver_gain`/`_receiver_is_camera`/`_receiver_is_reverie`): `camera` 1.12+damped · `oarb/youtube` 1.38 · `ticker` 1.62 · `atlas/ward` 1.42 · `reverie` 1.46+tonemap. The shader takes a `receiver_class: u32` and branches.

**Stochastic ops (glitch blocks, noise):** Python uses `np.random.default_rng(_stable_seed(receiver, frame, now))`. The WGSL port uses a per-fragment hash seeded identically (receiver hash ⊕ frame ⊕ floor(now·3)). Result is **visually equivalent, not pixel-exact** — the parity test (§7) must allow statistical tolerance on these layers.

## 5. Components (file-by-file)

New crate-internal module + a new bin target in `hapax-logos/crates/hapax-visual/` (reuses `gpu.rs` device setup, the WGSL node loader, and the `output.rs` BGRA pattern — no second wgpu stack).

| Component | Where | Notes |
|---|---|---|
| **`media_drift.wgsl`** | `agents/shaders/nodes/media_drift.wgsl` (+ `.json`) | One combined fragment shader replicating §4. May `#include`/inline the existing `chromatic_aberration`/`feedback`/`edge_detect`/`glitch_block`/`noise_gen`/`scanlines` logic, or be authored standalone. Bindings: current tex, previous tex (feedback), `DriftUniforms`, sampler. |
| **`DriftUniforms`** | `crates/hapax-visual/src/media_drift.rs` | Rust port of `load_drift_state` (reads the 27 `.txt` from the engine `data/` dir) → a `#[repr(C)]` uniform struct (27 scalars + `intensity` + `frame` + `now` + `phase` + `receiver_class` + `width`/`height`). Reload at `state_interval_s=0.5` like `MediaDriftRenderer`. |
| **Multi-slot ingest** | `crates/hapax-visual/src/media_drift.rs` | Per slot: read `.raw.bgra` (size-guarded, like the engine's reader), upload to a `Rgba8Unorm`/BGRA texture. Mirrors `content_sources.rs` shm ingestion. |
| **Multi-slot output** | `crates/hapax-visual/src/media_drift.rs` | Per slot: readback (async map, not the blocking `Maintain::Wait` of `output.rs` — see §8) → BGRA → atomic `tmp+rename` to `quake-live-<slot>.bgra`. Reuses the R↔B swap from `output::write_side_output`. Per-slot dims (atlas 2048×2304, cameras 1280×720, OARB 2048×1024, tickers 1344×176, reverie 960×540). |
| **Feedback history** | `crates/hapax-visual/src/media_drift.rs` | Per-slot "previous" texture (ping-pong) for the feedback-trails layer. Camera slots skip it (matches Python). |
| **Service binary** | `crates/hapax-visual/src/bin/screwm_media_drift.rs` | Render loop over the configured slots; 5060 Ti adapter selection; slot config from env/`config/screwm-media-drift.toml`. |
| **systemd unit** | `systemd/units/hapax-screwm-media-drift.service` | `CUDA_VISIBLE_DEVICES`/wgpu adapter pinned to the 5060 Ti; `After=` the producers; restart-on-failure. |
| **Producer change** | `scripts/quake-live-media-source.py` + `config/quake-live-cameras/*.env` | New flag: when a slot is GPU-drifted, write `.raw.bgra` and **skip** `MediaDriftRenderer.apply`. Default off (Python drift) per slot → safe rollout. |

## 6. Cutover plan (per-slot, lowest-blast-radius first)

Gated by `HAPAX_SCREWM_GPU_DRIFT_SLOTS` (comma list). A slot is GPU-drifted iff listed; otherwise the producer keeps the Python drift (fallback always present).

1. **ward-atlas** (slot 8, highest single-producer CPU 0.60 core, tolerates 0.5 fps, one ward) — first cutover. Producer writes `.raw.bgra`, service drifts slot 8, **verify visual parity** against the Python reference (§7) on the live broadcast frame.
2. **OARB** (slot 1) + **tickers** (9–11).
3. **cameras** (slots 2–7) — the bulk (~3.3 cores). Camera-class damping must match.
4. **reverie** (slot 12) last (the tonemap path).

Each step: enable the slot in the flag → restart the producer (writes raw) + the service picks it up → AVSDLC duration-bound witness (the slot looks the same, 1080p60 holds, CPU drops).

## 7. Verification — preserve the vocabulary + improve (not pixel-parity)

The goal is **not** to mimic numpy pixel-for-pixel — that shackles the GPU to the CPU's limits and wastes the headroom. The goal: **preserve the drift vocabulary + per-receiver character** (chroma-roll, feedback, edge, glitch, noise, scanlines, tonal; camera-damped, oarb/atlas/ticker/reverie-gained) so the screwm reads consistently, **and use the GPU headroom to go richer** where it serves fullest expression ([[feedback_never_remove_always_improve]]).

Verification per cutover step:
1. **AVSDLC duration-bound OBS-frame witness** (the task's acceptance contract): the slot looks at least as rich as the Python drift, the drift tracks `DriftState` (induce a stimulus → the drift responds), no global flash/dim/pulse ([[feedback_no_global_flash_dim_pulse]]), 1080p60 holds.
2. **Coarse headless sanity** (`tests/test_media_drift_gpu.py`): one run confirms each layer moves the expected channels in the expected direction at a known `DriftState` (chroma-roll separates R/B; edge lifts on high `edge`; camera-class visibly damped vs atlas). Statistical, not pixel-exact.

`apply_frame_drift` is the **reference for the vocabulary** (what each layer does + the per-receiver gains), not a pixel oracle.

## 8. Performance

- **CPU freed:** ~3.8 cores (the producers' numpy drift). Producers retain only decode+projection (cheap at 5–10 fps).
- **GPU cost (5060 Ti):** N slots × (upload + 1 fragment pass + readback) at 5–10 fps. Trivial for the 5060 Ti (idle, ~14 GB free; the textures total < ~150 MB).
- **Readback:** `output.rs` blocks on `Maintain::Wait` every frame — fine for one 30 fps surface, **wrong for N slots**. The service must use **async map + poll without full wait** (submit all slots, then drain completed maps), so slots pipeline. Cap total readback to the slot fps.
- **Guardrails (inherited):** 1080p60 always; the service must not starve the 5090 render; witness fps after each cutover.

## 9. Open decisions / v2

- **Sphere-front projection (OARB):** v1 keeps it CPU (producer-side, cheap relative to drift). v2 can move it into `media_drift.wgsl` as a UV warp (the one genuinely new shader node) — defer until cameras are ported and parity is proven.
- **Decode→GPU directly (NVDEC):** out of scope here; decode is cheap at these fps. Revisit only if the producers' residual cost matters.
- **Single binary vs. extend `hapax-imagination`:** spec chooses a **separate `screwm_media_drift` binary** for clean separation + independent cutover; it links the `hapax-visual` library for the device/nodes/output primitives.

## 10. Rollback

Per-slot, instant: remove the slot from `HAPAX_SCREWM_GPU_DRIFT_SLOTS` → the producer resumes the Python drift on the next frame; stop the service. The `.bgra` output path is unchanged throughout, so the engine never notices. No engine rebuild is ever involved.

## 11. Build sequence (lanes)

Independent, parallelizable (worktree-isolated subagents that push, or direct):
- **A — shader:** `media_drift.wgsl` + the parity-test harness (Python reference vs. shader, headless wgpu).
- **B — uniforms:** `DriftUniforms` Rust loader (port `load_drift_state`) + buffer upload.
- **C — io:** multi-slot ingest (`.raw.bgra` read) + multi-slot async-readback BGRA output.
- **D — service + producer:** the `screwm_media_drift` bin (wires A+B+C, 5060 Ti, slot config) + the producer `--gpu-drift` flag.
Integrate → **ward-atlas cutover** → parity witness → roll OARB/tickers → cameras → reverie.

## 12. Risks

| Risk | Mitigation |
|---|---|
| Stochastic-layer parity (glitch/noise) | Statistical tolerance in the parity test; hash seed mirrors `_stable_seed`. |
| Per-slot readback stalls (N× blocking poll) | Async map + batched drain (§8); never the per-slot `Maintain::Wait`. |
| Camera damping mismatch (faces over-glitched) | Parity test per receiver_class; cameras cut over last, after atlas/oarb proven. |
| 5060 Ti adapter selection in wgpu | Explicit adapter pin + a startup assertion logging the chosen GPU. |
| `.raw.bgra` partial-frame read | Producer writes atomically (`tmp+rename`), service size-guards (engine pattern). |
| Producer still CPU-bound after drift removal | Measure post-cutover; if decode/projection still high, consider NVDEC (v2). |
