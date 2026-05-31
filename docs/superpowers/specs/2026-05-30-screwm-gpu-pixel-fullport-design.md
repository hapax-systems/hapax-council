# Screwm GPU Pixel-Path Full Port — Implementation Spec

**Status:** Design / deployable spec
**Date:** 2026-05-30
**Author:** lead architect (alpha)
**Predecessor:** `2026-05-30-screwm-gpu-drift-port-design.md` (the drift port; PR #3759)
**Mandate (operator, verbatim):** "use the 5090/GPU for everything possible as it relates to compositing, video, and pixel-pushing; using the CPU for that is silly."
**Out of scope (explicit):** cognition / LLM inference stays on CPU+TabbyAPI as today. This spec is about *pixels*, not tokens.

> **State-of-the-world honesty note (load-bearing).** The task brief describes PR #3759 as "already landed." At the time of writing, on this worktree (`alpha/screwm-meet-camera`, `hapax-council--cx-alpha`), `gh pr view 3759` reports **state OPEN, not merged**, and the drift service ships with `HAPAX_SCREWM_DRIFT_SLOTS=` **empty** — i.e. the GPU drift binary, shader, and producer cutover flag exist and are wired, but **no slot is GPU-drifted by default and no real-producer `*.raw.bgra` is present in `/dev/shm/hapax-compositor`** (only `quake-live-drifttest.raw.bgra` / `quake-live-gputest.raw.bgra` test fixtures). This spec therefore treats the drift port as the *immediate predecessor whose cutover is the first build step here*, and is written to be correct whether #3759 lands as-is or is amended. **Do not begin Lane B (project fold-in) until the drift cutover for at least one real slot is green** (§6).

---

## 1. Context — what #3759 moved, what remains on CPU

### 1.1 The screwm pixel topology (13 mounts, 4 producer programs, 1 GPU service, 1 engine)

The screwm scene is DarkPlaces (patched: `assets/quake/darkplaces/hapax-live-texture.patch`, 12 hardcoded slots) reading final `quake-live-*.bgra` files from `/dev/shm/hapax-compositor` and `glTexSubImage2D`-uploading them into live-texture slots every rendered frame (`R_HapaxLiveTexture_Update` from `R_RenderView`, patch L322). Producers:

- `quake-live-media-source.py` — 7 systemd instances: 1 OARB/YouTube (`sphere-front`, `quake-live-yt.bgra`, 2048×1024) + 6 MJPEG cameras (`flat`, `quake-live-cam-<role>.bgra`, 1920×1080).
- `quake-live-reverie-source.py` — 1 instance (`quake-live-reverie.bgra`, 960×540).
- `quake-live-ticker-source.py` — 3 instances (Cairo/Pango, 1344×176, 8 fps).
- `quake-live-ward-atlas-source.py` — 1 instance (Cairo, 2048×2304, 36 cells, 2 fps).

The capture/egress tail is separate: DarkPlaces renders under headless `Xvfb :82`, and `darkplaces-v4l2-xvfb.sh` scrapes the X framebuffer via **`x11grab` (CPU readback)** → libswscale RGB→YUYV422 (CPU) → raw to `/dev/video52` (v4l2loopback), which the studio compositor ingests (`v4l2src → videoconvert → cudaupload → cudacompositor`) and NVENC-encodes for RTMP.

### 1.2 What the drift port (#3759) moves to GPU

Only the `MediaDriftRenderer.apply` numpy step (chromatic shift, feedback trail, saturation, edge, block-displacement, noise, scanlines, color-cast — `scripts/quake_media_drift.py:186-378`) moves to the **5060 Ti**, and **only** for slots listed in `HAPAX_SCREWM_DRIFT_SLOTS` whose producer carries `HAPAX_QUAKE_GPU_DRIFT=1`. The GPU service (`hapax-logos/crates/hapax-visual/src/bin/screwm_media_drift.rs`) per slot does: `fs::read(*.raw.bgra)` → `queue.write_texture` → single fragment pass (`agents/shaders/nodes/media_drift.wgsl`) → `copy_texture_to_buffer` → `map_async` + **per-slot `Maintain::Wait`** → de-pad → atomic `tmp+rename` to `*.bgra`. Pinned `HAPAX_SCREWM_DRIFT_GPU=5060`, polls `HAPAX_SCREWM_DRIFT_FPS=20`.

The drift shader is **single-pass v1**: feedback-trail and glitch-block are `TODO v2` because they need a per-slot previous-frame (ping-pong) texture the service does not yet hold.

### 1.3 What remains on CPU after the drift port (the full-port target surface)

| Stage | Where | Notes |
|---|---|---|
| **OARB decode + scale** | ffmpeg, CPU, no `-hwaccel` | H.264/avc1 (selector prefers avc1 mp4); libswscale lanczos upscale to 2048×1024. **Currently ~2.5% of one core** (480p H.264 source — see §5). |
| **6 camera MJPEG decode** | ffmpeg `mjpeg`, CPU | ~3.3–5.4% core each; ~27% aggregate. The aggregate CPU hog **by count**. |
| **OARB projection (`_compose_sphere_front`)** | Python row-slice + cached equirect | Seam-wrap onto sphere texture. |
| **OARB mask (`_apply_mask` circle)** | Python per-pixel double loop | **Disabled in production: OARB ships `--mask none`** (`hapax-quake-live-youtube.service:10`). The "heaviest Python step" framing in the MAP is wrong for the shipped config. |
| **freshness overlay** | Python, cheap | default `none`. |
| **Python projection/mask byte loops (cameras `flat`)** | Python | `flat` head: mask `none`, so minimal. The dominant per-producer Python cost is the parent loop's own per-pixel handling + atomic shm write (~55–73% of a core per media producer per live `top`). |
| **reverie drift** | numpy, CPU | not on `--gpu-drift`. |
| **ticker raster + drift** | Cairo/Pango + numpy, CPU | 1344×176 @ 8 fps ×3 — negligible. |
| **ward-atlas raster + drift** | Cairo (36 cells) + numpy, CPU | 2048×2304 @ 2 fps. **Heaviest single screwm CPU producer** (~69% core in live `top`) — but it is *Cairo compositing*, not decode. |
| **Capture/egress** | x11grab + libswscale + compositor `videoconvert` | ~2–3 cores burned bracketing a GPU render and a GPU NVENC encode. |

**The dominant CPU costs are NOT decode.** Live `top`/`ps` on podium (2026-05-30) shows: ward-atlas Cairo ~69% core, each media producer's Python loop ~55–73% core (×6 cameras ≈ 3.5 cores), capture x11grab+convert ~2–3 cores. The ffmpeg decoders are the *cheap* slice (~4% core each). This reorders the whole plan: **per-pixel projection/mask/drift + Cairo + capture-readback are the prize, not decode.**

---

## 2. Architecture decision — piecemeal shm-staged vs unified GPU pipeline

### 2.1 The single fact that dominates

The engine ingest is `fopen`/`fread` into a host buffer then `qglTexSubImage2D(host_ptr)` (patch L136 → `gl_textures.c:958`). DarkPlaces is **GLX-over-SDL, no PBO, no EGL, no Vulkan, no CUDA** in the ingest. As long as the IPC contract is "a `.bgra` file of host bytes," **every frame crosses PCIe at least twice — GPU→host at the producer, host→GPU at the engine — by construction.** This is symmetric (verdict 5, conditional): the file *contract*, not the engine `fread` alone, is the wall; a zero-copy pipeline requires changing the engine ingest **and** the producer handoff together.

### 2.2 PCIe-crossing accounting (the decisive comparison)

Per slot, per frame, tracing where a pixel lives:

| Architecture | Crossings (camera) | Crossings (OARB+NVDEC) | `.raw.bgra` intermediate | Readback |
|---|---|---|---|---|
| **CPU baseline** (all on CPU, born host-resident) | **1** (final engine upload) | 1 | n/a | n/a |
| **A — piecemeal** (NVDEC decode proc + GPU drift proc, separate shm hops) | **4** | 4 | yes (extra hop) | per-stage, serialized `Maintain::Wait` |
| **B1 — unified GPU compute, shm egress** (project+drift fused, one upload, one readback) | **3** | 4 | **gone** | one, batched async-drain |
| **B2 — unified + engine interop fork** (dmabuf/EGLImage or CUDA IPC) | **1** | 0–1 | gone | none (zero-copy import) |

The killer finding: **piecemeal GPU acceleration across shm process boundaries ADDS round-trips.** Putting NVDEC in the producer *and* GPU drift in a separate service makes each stage download-to-host to hand off — 4 crossings vs the CPU baseline's 1. It maximizes "stages on GPU" while erasing the benefit, and at 8–15 fps the per-pixel compute it offloads is cheap relative to the PCIe round-trips it adds.

### 2.3 Decision: **Build B1 (unified GPU compute, shm egress). Do NOT fork the engine now.**

Rationale, with the verdicts folded in:

1. **A is a trap.** Confirmed by the unified-architecture design and the 4-vs-1 crossing math. The drift port is only a net win in *isolation* (drift-only-GPU, decode+everything-else CPU, single readback). Treat the landed drift cutover as **step 1 of B1**, not the start of an A-style per-stage offload campaign.
2. **B1 reaches the fullest GPU expression for everything that matters** — projection, masking, drift, feedback/glitch all GPU-resident in **one upload** — using primitives that already exist (`pick_adapter`, `DynamicPipeline`, `temporal_textures`, `content_sources::upload_rgba`, `output.rs` readback). The drift-port spec §5 already mandated "no second wgpu stack"; B1 realizes that intent.
3. **The engine fork (B2) is a non-bottleneck win at maximal risk.** It removes 2 of 3 PCIe crossings — but PCIe at ~25 GB/s is not the bottleneck at 8–15 fps (~150 MB/s saved across 9 slots), and the fork is **render-thread surgery (~400–700 LOC for the cleanest dmabuf/EGLImage route, which also requires adding an EGL context path to `vid_sdl.c` that does not exist) on an engine with an unsolved black-frame problem on the GPU-pinned route, under an active hardware-stability containment gate** (post-2026-05-23 AMD data-fabric reset). Introducing CUDA context-sharing or EGL into that render thread under containment is precisely where *not* to take risk. The `.bgra` shm seam is also the stable, debuggable, fail-open boundary the whole stack relies on (atomic tmp+rename, sidecar liveness JSON, torn-frame-safe reads, fail-to-black-never-crash).

**The engine-patch interop change (B2) is deferred to a later phase, explicitly gated.** It becomes worth reconsidering only if BOTH hold: (a) the black-frame / hardware-containment issues on the real-Xorg / GPU-pinned route are resolved, AND (b) a genuine end-to-end NVDEC-in→NVENC-out path materializes so the pixel never needs to touch host. Until then, shm-staging is the correct engineering choice. PBO (~80–150 LOC) is explicitly rejected as a half-measure: it pipelines the upload but stays host-resident, so it does not remove the round-trip and buys nothing for "everything on GPU."

### 2.4 The incremental path that maximizes GPU usage at each step

Each step ships independently and never regresses (full sequence in §6):

1. **Drift cutover** (one real slot first) — drift-only-GPU. One extra crossing for a measurable per-pixel win; a stepping stone, not the end state.
2. **Fold projection into the drift service** (`media_project.wgsl` prepended pass) — deletes the `.raw.bgra` intermediate (project+drift now share GPU residency, 4→3 crossings) and deletes the Python projection/mask/seam-wrap.
3. **Migrate per-slot driver onto `DynamicPipeline`** + add `media_drift_v2` feedback/glitch via `temporal_textures`. The real unified pipeline.
4. **Batched async-drain readback** — the single most important multi-slot perf-correctness fix.
5. **NVDEC the OARB only** — one stream's decode CPU recovered (modest; see §5).
6. **Capture-path GPU-ification** (the actual ~2–3 core prize) — DarkPlaces emits its final composite as a `/dev/shm` BGRA producer (O5), gated on a GL-renderer preflight and the containment switch. This is itself a B2-flavored engine change but on the *export* side, not the ingest side, and is sequenced last with its own gates.

---

## 3. The lanes (priority-ordered)

Priority is set by **CPU actually recovered**, not by "stages moved to GPU." Lanes that the verdicts refuted or conditionalized are deprioritized accordingly.

> **Placement summary (all lanes):** the **5090 (GPU0) stays frozen** — GL render (~401 MiB) + the single existing compositor NVENC egress (~250 MiB) + Command-R (23.3 GB). It has ~5 GiB free against a hard 30.5 GiB ceiling. **The port must add 0 bytes to GPU0.** All new screwm GPU work lands on the **5060 Ti (GPU1)** (~9.4 GiB free after STT warms, idle enc/dec ASICs, already the drift pin). **Appendix is rejected for the hot path** (1080p60 BGRA = ~4 Gbit/s one-way, ~8 Gbit/s round-trip + double network hop on an already-doubled host round-trip).

### Lane P0 — Projection + mask folded into the drift service (HIGHEST PRIORITY)

**What:** author `agents/shaders/nodes/media_project.wgsl` as a fragment pass prepended to the existing drift pass in `screwm_media_drift.rs`, doing sphere-front UV warp + circle mask + freshness overlay. Producer stops calling `_project_frame` and writes the *raw decoded media frame* to `*.raw.bgra`.

**Why P0:** it deletes the heaviest *Python* per-pixel work on the media producers and removes the `.raw.bgra` intermediate (4→3 crossings). It is ~0.75 day, reuses the shipped binary, touches no engine code, and is the concrete realization of B1 step 2.

**Honest caveat (verdict 1 incidental):** OARB ships `--mask none`, so the circle-mask sub-step is a **no-op for the only slot that has projection at all**. Cameras are `flat`/`mask none` too. So P0's *mask* code is dormant infrastructure for now; its *projection* (sphere-front seam-wrap + analytic equirect background, replacing the Python row-slice + LRU-cached background) is the real win. Build the mask anyway (5 lines, future-proofs re-enabling it), but do not claim it as a current CPU saving.

**Design (fragment-stage, gather-vs-scatter inversion of the Python forward copy):**

`ProjectUniforms` (std140, sibling of `DriftUniforms`), all values computed CPU-side once per slot:
```wgsl
struct ProjectUniforms {
    out_dims:  vec4<u32>,  // (out_w, out_h, frame_w, frame_h)
    layout:    vec4<f32>,  // (offset_y, seam_left_w, seam_right_w, right_edge_x)  texels
    mask:      vec4<f32>,  // (cx, cy, radius, feather)  px ; radius<=0 => mask off
    bg:        vec4<f32>,  // (r, g, b, mode)  mode 0=flat,1=sphere-front
    overlay:   vec4<f32>,  // (freshness_mode, frame, bar_w, bar_h)
};
```

Sphere-front branch (replaces `_compose_sphere_front` + `_sphere_background`, deleting the LRU cache — the GPU recomputes the equirect latitude shade per fragment for free):
- For output texel `(px,py)`, compute analytic `sphere_background()` (latitude shade `0.54 + 0.30*(1 - |y/h-0.5|*2)` + guide lines).
- If inside the media band `py in [offset_y, offset_y+frame_h)`: left output band ← right media half, right edge band ← left media half (the seam-wrap, now a UV remap), with **handedness `1.0 - su` baked in** (see critical note).
- Sampler **`FilterMode::Nearest`** for this pass (the Python uses integer row copy; sphere-front media bands are 1:1 horizontal, no scaling).

Circle mask (replaces `_apply_mask`): `a = clamp((radius - d)/feather, 0, 1); rgb = mix(bg, rgb, a)` — bit-faithful to the Python feather.

Freshness overlay (replaces `_apply_freshness_overlay`): analytic two-bar rectangle test with the existing pulse math.

**Critical cross-process coordination:** today the sphere-front ffmpeg `-vf` does `hflip` so the Python seam-wrap doesn't. When projection moves to GPU, **remove `hflip` from the sphere-front `-vf`** and bake handedness into the shader UV (`1.0 - su`). Otherwise double-flip. This is a one-line `_ffmpeg_command` change paired with the shader.

**Rust changes (`screwm_media_drift.rs`):** add `mid_tex` (`Bgra8Unorm`, `TEXTURE_BINDING|RENDER_ATTACHMENT`) + project pipeline/bind group per slot, gated by a per-slot `needs_project` flag (extend slot spec to `name:WxH[:intensity][:proj=sphere-front,mask=circle]`, or read `config/screwm-quake-media-mounts.json`). `process` emits PASS 0 (`in_tex→mid_tex`) then repoints the drift pass source to `mid_tex` — **same command encoder, one submit, no extra readback.** Skip PASS 0 entirely for flat slots with no projection (drift reads `in_tex`).

**Producer changes (`quake-live-media-source.py`):** for `sphere-front` + `--gpu-drift`, skip `_compose_sphere_front`/`_apply_mask`/`_apply_freshness_overlay`, write the raw media frame (frame_w×frame_h, not out_w×out_h) to `*.raw.bgra`, drop `hflip` from the vf. OARB raw output shrinks from 2048×1024 to media-frame size → smaller shm write too.

**GPU placement:** 5060 Ti, in-process with drift (~40 MiB for the OARB slot's textures). No new sessions.

**Failure/rollback:** the project pass is behind the same `--gpu-drift` / `HAPAX_SCREWM_DRIFT_SLOTS` cutover as drift. A slot not in the list runs the unchanged Python projection + CPU/GPU drift. A bad shader is caught by the existing `naga` static-validate before compile; on any GPU error the slot logs and the producer's fallback writes the offline color card via the existing atomic path. The engine never sees a torn/missing file.

**AVSDLC witness:** per-mount duration-bound OBS-frame motion metric (§4). For OARB: window = max(2 s, 3/10 fps) ≈ 2 s; PASS if mean-abs per-pixel delta over the OARB screen region > ε_oarb AND sidecar `drift_output_hash` changed across the window. Additionally assert the OARB `*.bgra` is exactly 2048×1024×4 (engine rejects size drift). NO-GO: zero motion on a should-be-live slot.

---

### Lane P1 — Batched async-drain readback in the GPU service (HIGHEST PRIORITY, perf-correctness)

**What:** replace the per-slot `device.poll(Maintain::Wait)` (bin L256) with submit-all-slots-then-drain-async-maps. Render+copy every slot into its own staging buffer, submit, then `map_async` all and drain on a single poll.

**Why P1:** the shipped binary renders and reads slots **one at a time, blocking per slot** (drift-infra MAP §3; named as the §8 improvement that is unimplemented). With 1 slot it is fine; the moment B1 carries multiple slots through one service, the serialized blocking readback — not VRAM, not engine sessions — is the throughput killer at the 60 fps engine consume. This is the single most important multi-slot change and it is pure Rust, no shader, no engine.

**Design:** reuse `output.rs::copy_to_staging` pattern. Per tick: for each slot, encode upload→project→drift→`copy_texture_to_buffer`→its staging buffer; `queue.submit(all_encoders)`; then for each slot `slice.map_async(Read, cb)`; single `device.poll(Maintain::Wait)` (or `Poll` loop); drain each channel, de-pad, atomic write. Factor a `BatchedReadback` helper into `hapax-visual` so `output.rs` can adopt it too.

**GPU placement:** 5060 Ti (no change). No new VRAM beyond N staging buffers (already allocated per slot in `SlotGpu`).

**Failure/rollback:** behind a `HAPAX_SCREWM_DRIFT_BATCHED=1` flag (default ON after validation, per features-on-by-default; one env flip to revert to the serialized path). If a map callback never fires within a timeout, fall back to the per-slot `Maintain::Wait` for that tick and log.

**AVSDLC witness:** aggregate — all active slots must PASS their per-mount motion check within one witness window with the batched path enabled, AND the service's per-tick wall time (Prometheus gauge) must be ≤ `1/HAPAX_SCREWM_DRIFT_FPS`. NO-GO: per-tick time exceeds the period (the readback is still serializing) or any slot's cadence drops below its producer fps for >2 s.

---

### Lane P2 — `media_drift_v2` feedback/glitch + `DynamicPipeline` migration (MEDIUM)

**What:** finish the drift shader's `TODO v2` (feedback-trail, glitch-block) by giving each slot a previous-frame ping-pong texture, and migrate the per-slot driver from the bespoke single-pipeline bin onto the existing `DynamicPipeline` node-graph runner.

**Why P2:** v2 is the visual upgrade the drift shader was always heading toward, and the ping-pong primitive already exists verbatim (`temporal_textures` / `prime_temporal_textures`, `dynamic_pipeline.rs:688-692, 2486-2511`). Migrating onto `DynamicPipeline` gives hot-reload, the transient pool, and `@accum_*` feedback "for free," and is the cleanest long-term host for the project+drift+post chain. Medium priority because it is a visual/architecture win, not a CPU recovery — P0/P1 deliver the CPU and throughput wins first.

**Design:** author `media_project.wgsl` (from P0) and `media_drift_v2.wgsl` as ordinary nodes in `agents/shaders/nodes/` (model after `transform`/`circular_mask`/`fisheye` and the existing `feedback`/`trail`/`echo` temporal nodes). Drive a 2–3 node plan per slot through `DynamicPipeline` (project → drift_v2 → optional post). `media_drift_v2` samples `@accum_<slot>` for the trail/feedback and writes the new frame back; `prime_temporal_textures` guarantees no undefined first-frame sample.

**GPU placement:** 5060 Ti. Adds ~1 ping-pong texture per slot (~frame size each); total wgpu working set across all 12 slots stays well under 500 MiB. ~5× VRAM margin holds.

**Failure/rollback:** keep the v1 single-pass `screwm_media_drift` bin as the fallback binary; `HAPAX_SCREWM_DRIFT_ENGINE={v1|dynpipe}` selects. `DynamicPipeline` already has last-known-good hot-reload rollback for bad shaders. If the dynpipe path fails to produce frames, revert the env and restart.

**AVSDLC witness:** per-mount motion metric with a *higher* ε floor than P0 (feedback/glitch should increase inter-frame motion); corroborated by `drift_output_hash` change. Visual regression check: capture before/after stills and confirm the trail/glitch is present (per visual-verification mandate). NO-GO: motion drops to zero or the dynpipe path produces dimensionally-wrong output.

---

### Lane P3 — NVDEC decode for the OARB stream only (LOW — modest, conditional win)

**What:** move the OARB/YouTube decode + scale to the 5060 Ti NVDEC engine. **Cameras stay on CPU `jpegdec` — do not build a camera NVDEC lane.**

**Why LOW and conditional (verdicts 1, 2, 6 — refuted/conditionalized):**
- **The OARB is NOT the heaviest decode** (verdict 1, refuted). Live: the OARB ffmpeg is ~2.46% of one core (decoding 480p avc1, not 1080p, because the live source resolves to itag=135 480p and the yt-dlp selector prefers avc1 mp4). A single camera decode (~4.85%) is ~2× heavier; the 6-camera aggregate (~27%) is ~11× heavier. The OARB is one of the *lightest* decodes.
- **The win is modest, not dramatic** (verdict 3, refuted "erases most"): NVDEC saves the decode (~0.3–0.6 core for H.264, more for VP9/AV1) plus moves the lanczos upscale to the cuvid `-resize` ASIC (the OARB's actual dominant ffmpeg cost). ~25–40% is clawed back by the mandatory `hwdownload` + NV12→BGRA libswscale convert (CUDA hwframes are NV12/P010/YUV444, never BGRA). So ~60–75% survives — but at the shipped 480p/avc1/fps=10 config the absolute decode saving is sub-0.1 core; the `-resize` saving is the real value. Honest net: **moderate at best, marginal at the shipped config, larger only if the OARB is ever reconfigured to a true 1080p VP9/AV1 source.**
- **Cameras cannot use NVDEC at all** (verdicts 2, 6, refuted): MJPEG is not on the NVDEC matrix; `mjpeg_cuvid` routes to NVJPG and is empirically broken on this rig (file-path `decode→hwdownload→bgra` fails with swscale -95 `nv12 csp:gbr → bgra`, live V4L2 path fails -38 / -5). Only `/dev/video2` (one BRIO) offers native H.264. **Splitting camera decode to the 5090 or appendix does not help — MJPEG is unsupported on every NVDEC engine.** Cameras stay CPU.
- Decode is not the bottleneck anyway (verdict 2): the per-producer Python loop (~55–73% core) and ward-atlas Cairo (~69% core) dwarf decode (~4% core). NVDEC touches none of that.

**Build it anyway?** Yes, but last and small — it is a legitimate piecemeal producer-local win (decode and shm-write are the same process, so NVDEC adds one one-way DMA, not a round-trip; verdict 3 confirms it is shippable piecemeal). It recovers the heaviest *per-instance* ffmpeg decoder's CPU and frees the lanczos pass. Just do not oversell it.

**ffmpeg invocation (OARB, H.264 common case; decoder chosen from the resolved stream codec, not hardcoded):**
```
ffmpeg -hide_banner -loglevel warning -nostdin \
  -hwaccel cuda -hwaccel_device 0 -hwaccel_output_format cuda \
  -c:v h264_cuvid -resize 2048x1024 \
  -re -i <video_url> -an \
  -vf "fps=10,hwdownload,format=nv12,format=bgra" \
  -f rawvideo -pix_fmt bgra -
```
VP9 → `-c:v vp9_cuvid`; AV1 → `-c:v av1_cuvid` (all confirmed compiled in). `-resize` is the cuvid built-in scaler (replaces libswscale lanczos). `-hwaccel_output_format cuda` keeps frames in VRAM through decode/scale; without it the win evaporates. **Note:** with Lane P0 landed, the producer writes the raw media frame and the GPU service does sphere-front — so the OARB no longer needs the `hflip` here, and `-resize` targets the media frame dims, not 2048×1024.

> **GPU pin nuance:** `-hwaccel_device` indexes the CUDA-visible device list. Pin via `CUDA_VISIBLE_DEVICES=1` in the systemd unit so the only visible device is the 5060 Ti, then `-hwaccel_device 0` refers to it. (Do not rely on `-hwaccel_device 1` against the full fleet — the project's own GPU-pinning caveats make `CUDA_VISIBLE_DEVICES` the reliable pin.) NVDEC decode VRAM ~150–400 MiB; the 5060 Ti has ~9.4 GiB free. NVDEC has no GeForce session cap; this adds zero NVENC sessions.

**Failure/rollback (fail-open to software, per-instance, never dark a slot):**
1. Capability gate at producer start: confirm the relevant `*_cuvid` decoder is present and the resolved codec maps to one; 1-second NVDEC smoke probe pinned to GPU1; on non-zero exit, use software automatically. Cache per-codec for the session.
2. Runtime watchdog: reuse the producer's existing ffmpeg-restart + sidecar liveness. On hwaccel ffmpeg non-zero exit or stall (no new frame within N×(1/fps)), respawn with the software command. Order: hwaccel → software-decode → offline color card.
3. Flag: `HAPAX_QUAKE_HWACCEL_DECODE=1` (OARB instance only). Camera H.264 sub-lane `HAPAX_QUAKE_CAMERA_H264=0` (default OFF, marginal, experimental — BRIO only).

**AVSDLC witness:** OARB motion metric (as P0) AND `nvidia-smi --query-gpu=utilization.decoder -i 1` must read >0% only after cutover. If decoder util stays 0%, the hwaccel silently fell back to software — treat as lane failure, not success. Hold-down: 60 s with `drift_changed=true` before declaring healthy. Byte-dimension check on the output.

---

### Lane P4 — Capture/egress GPU-ification (LARGEST CPU PRIZE, but heavily gated — LATER PHASE)

**What:** eliminate the x11grab CPU readback + two libswscale colorspace converts (~2–3 cores). Recommended route: **O5 — DarkPlaces emits its final composite as a `/dev/shm` BGRA producer** (the stack's existing pattern), deleting the Xvfb→x11grab→ffmpeg→`/dev/video52` leg; the compositor `cudaupload`s the shm BGRA directly.

**Why this is the largest prize but sequenced last:** the capture bracket burns ~2–3 cores — more than every other lane combined — doing nothing but moving pixels between a GPU render and a GPU NVENC encode. But it is the riskiest change and is multiply gated:

**NVENC does NOT help here (verdict 4, refuted) — do not add NVENC:**
- The dominant cost is the x11grab readback + convert, not encode (the current path does no encode — `-f v4l2` writes raw YUYV).
- `/dev/video52` is v4l2loopback, which transports **raw only**. Pushing H.264 in would require NVDEC-decoding it right back to raw — strictly worse.
- **NvFBC is blocked** (verdict 4, refuted): `Xvfb :82` is the X.Org dummy DDX, not the NVIDIA DDX (probed: server GLX vendor "SGI", X vendor "The X.Org Foundation"). NvFBC needs a server-side NVIDIA X screen and fails "version mismatch between NvFBC and the X driver interface" on Xvfb. Compounded by: GeForce NvFBC needs the keylase unlock, which is broken on driver ≥560 (this rig is 595.71.05); ffmpeg here exposes no nvfbc capture device.
- **Correction to prior context (verdict 4):** DarkPlaces under `:82` *does* get a hardware NVIDIA GLX context (probed: renderer "NVIDIA GeForce RTX 5090/PCIe/SSE2", direct rendering Yes, 32 GB). The "llvmpipe/software framebuffer" framing is empirically false. This is good news for O5/O4: the frame genuinely lives on the GPU, so a GL→PBO export (O5) or GL→CUDA interop (O4) is feasible.

**Design (O5, primary):** add a DarkPlaces frame-*export* hook symmetric to the existing `hapax_live_texture` ingest patch: after the final composite, `glReadPixels`-into-PBO → atomic write to `/dev/shm/hapax-compositor/quake-live-screwm-final.bgra`; compositor ingests it via the existing shm/`cudaupload` path. **O4 (GL→CUDA interop via `cudaGraphicsGLRegisterImage`) is the zero-copy upgrade** but adds a CUDA dep + render-thread context-sharing — defer to a follow-on.

**Blocking preflight gate (do not write the export patch until green):**
```bash
DISPLAY=:82 glxinfo -B | grep -E "OpenGL renderer|Device"   # must report NVIDIA, not llvmpipe
```
Confirm DarkPlaces' *own* init-logged renderer is NVIDIA (probe says it is). If software, O5-GPU is impossible without first fixing hardware GL under headless X — fall back to O5-shm (export CPU BGRA, still deletes x11grab + double-convert, ~2 cores).

**Hard gates (must all hold before P4 ships):**
- The post-2026-05-23 AMD data-fabric hardware-containment switch (`~/.cache/hapax/enable-darkplaces-runtime`, `darkplaces-runtime-guard.sh` exit 78) stays the master kill — the export hook inherits it. **No P4 work ships without an attended hardware-validation session.**
- Keep `/dev/video52` until O5 is proven through a full broadcast (v4l2loopback reload disconnects all consumers; reboot-coupled). O5 publishes to `/dev/shm` *in addition to* the v4l2 leg first; cut the v4l2 leg as a final, separate, reversible commit. Note O5 would break the parallel OBS-direct-`/dev/video52` topology (`zzzz-screwm-quake-video52.conf`) — confirm the compositor-ingest topology is the only live one, or keep a thin re-export, before retiring it.

**GPU placement:** the GL render + the single compositor NVENC egress stay on the 5090 (unchanged, 0 new bytes). O5 adds no new GPU work — it deletes CPU work. O4 (later) would register the GL texture on whatever GPU holds the GL context (currently the 5090's GLX context per the probe).

**Failure/rollback:** `HAPAX_SCREWM_CAPTURE_MODE={x11grab|shm|glcuda}` (default `x11grab`). Export hook is a no-op unless mode is set; launcher selects ffmpeg-x11grab vs shm-emit. One env flip + `systemctl --user restart` reverts to the known-good software path. The export patch goes through `ensure-darkplaces-live-texture-build.sh`'s sha256-stamped rebuild; reverting the patch restores the prior stamp.

**AVSDLC witness:** motion metric on the *final composited* OBS frame (`/dev/video42` / OBS source) over a 2 s window — the whole point is that screwm pixels reach broadcast (L-12 invariant). PASS if motion > ε AND the new `quake-live-screwm-final.bgra` sidecar mtime/hash advances. NO-GO: black/frozen broadcast, OR any rise in 5090 `memory.used`, OR the host shows instability under the containment validation.

---

### Lane K (keep-CPU, decided): Cairo/ticker raster

**Decision: keep all Cairo/Pango on CPU.** (Verdict-consistent; this is the projection-mask-cairo design's verdict.)

- **Tickers:** 1344×176 = 236K px ×3 @ 8 fps ≈ 5.7 Mpx/s — trivial. Pango shaping of ≤3 short rows is microseconds. Text shaping has no cheap wgpu path; glyphon/cosmic-text would reimplement Pango layout for a marginal raster saving. Not worth it.
- **Ward-atlas:** 2048×2304 @ 2 fps. It is the heaviest single screwm CPU producer (~69% core), but its cost is **36 `tick_once()` source backends + 36 scaled blits**, not the raster primitive — and its vector content (`_paint_reverie_state_proxy`: gradients, 14 radial auras, 18 Bézier strokes, 42 sediment rects) has no clean GPU text/vector path. A glyphon+quad-compositor port (~2 days) helps only if it ever profiles hot; do not pre-emptively port.

**Cheap interim win for the Cairo producers (no new shaders):** give the reverie/ticker/atlas producers `--gpu-drift` + `*.raw.bgra` output so just their numpy drift step moves onto the existing GPU service. This reuses #3759 wholesale. Sequence it as a trailing config-only change after P1 (batched readback) lands, since it adds 5 more slots to the service. **Honest note:** for the atlas this *adds* one PCIe crossing (the producer is already CPU-resident; GPU drift forces a download+upload to re-enter shm). Only do it if the numpy drift CPU on these surfaces shows up in a profile — at 2 fps (atlas) and 8 fps (tickers) it likely does not. Default: keep their drift on CPU.

---

## 4. Hard perf guardrails + per-lane witness

### 4.1 Hard invariants (NO-GO thresholds)

1. **1080p60 always.** The engine consumes at 60 fps on its render thread; the drift service runs at `HAPAX_SCREWM_DRIFT_FPS=20` independently. **NO-GO:** any drifted slot's effective output cadence < its producer fps for >2 s, OR the engine's `R_RenderView` frame interval > 16.6 ms sustained.
2. **5090 VRAM ceiling = 30.5 GiB (hard).** Probe: 27044 MiB used, ~4.2 GiB live margin for Command-R + GL + NVENC. **The port must add 0 bytes to GPU0.** Guardrail: pre-deploy assertion `memory.used(GPU0) ≤ 27500 MiB` after screwm services start. **NO-GO:** any screwm change that raises GPU0 `memory.used`.
3. **Audio cores fenced.** The drift service and any new decode inherit `CPUAffinity`/`AllowedCPUs` excluding the audio-reserved cores (never-drop-speech invariant). **NO-GO:** any screwm process scheduled onto a fenced audio core, OR PipeWire xruns appearing after a screwm deploy.
4. **5060 Ti VRAM soft ceiling = 14.0 GiB** (of 16.3), leaving ~2.3 GiB for STT warm-spikes + imagination growth. **NO-GO:** screwm footprint pushing GPU1 `memory.used` past 14000 MiB.
5. **NVENC ≤ 5 sessions system-wide.** (Conservative; GeForce was raised to 8, but plan to 5.) The port adds **0** NVENC sessions. **NO-GO:** any commit introducing a new NVENC session.
6. **Never break the `.bgra` contract.** Drift/project output stays atomic `tmp+rename` BGRA8888, tightly packed, exact `W·H·4` (engine rejects mismatched `st_size` and silently no-ops). **NO-GO:** torn frames or dimension drift.
7. **Net CPU must drop, not rise.** P0 deletes Python projection; P3 moves OARB decode off-CPU; P4 deletes ~2–3 capture cores. **NO-GO:** aggregate non-audio CPU higher after a lane lands than before it (the piecemeal-trap signature).

### 4.2 The AVSDLC witness (per-mount, duration-bound OBS-frame motion metric)

Witnessing must prove **pixels actually move through to broadcast**, not merely that a service is up (verify-before-claiming-done + L-12==livestream invariants).

**Metric:** sample the mount's final frame (its `quake-live-*.bgra`, or the compositor `/dev/video42` region it feeds) at two timestamps Δt apart; compute a motion score = mean-abs per-pixel delta over the mount's region, normalized 0–1.

- **Duration-bound window** = `max(2 s, 3 / producer_fps)` so even the 2 fps ward-atlas gets ≥3 expected new frames.
- **PASS:** motion > ε (tuned per slot — near-static atlas low ε, cameras higher) AND the sidecar `*.json` `drift_output_hash` changed across the window (producers publish `drift_input_hash`/`drift_output_hash`/`drift_changed` every `fps*5` frames — cheap liveness corroborator that catches a frozen-but-fresh frame, which mtime alone misses).
- **FAIL/NO-GO:** zero motion for the full window on a should-be-live mount → dead lane (frozen producer, stale shm, or engine not blitting).
- **Aggregate gate:** all 13 mounts must PASS before the port (or any lane) is declared live. Wire as a post-deploy systemd oneshot (analogous to `hapax-darkplaces-v4l2-ready` but motion-based) that ntfy's on any FAIL.

Per-lane witness specifics are stated in each lane above (P0: OARB motion + dim check; P1: aggregate motion + per-tick wall-time gauge ≤ period; P2: higher-ε motion + visual still diff; P3: decoder util >0% + motion + 60 s hold-down; P4: final-composite OBS-frame motion + GPU0 byte-ceiling assertion + host stability).

---

## 5. Honest open questions / where the wins are marginal

1. **OARB NVDEC is a marginal win at the shipped config, not "the heaviest decode."** (Verdict 1, refuted.) Live OARB decode is ~2.46% of one core (480p avc1); a single camera is ~2× heavier; the 6-camera aggregate is ~11× heavier. NVDEC's real value here is the `-resize` ASIC replacing libswscale lanczos, not the decode itself. The decode saving only becomes substantial if the OARB is reconfigured to a genuine 1080p VP9/AV1 source. **Plan: build P3 last and small; do not present it as a decode rescue.**

2. **Camera MJPEG NVDEC is dead — do not build it.** (Verdicts 2, 6, refuted.) Matrix-unsupported; `mjpeg_cuvid` routes to NVJPG and is empirically broken on this rig (swscale -95 `nv12 csp:gbr → bgra`; live -38/-5). Only 1 of 6 cameras (a BRIO) offers native H.264. Splitting to the 5090 or appendix does not help — MJPEG is unsupported on all NVDEC. **The aggregate-CPU hogs (the 6 cameras) get nothing from decode offload.** The honest camera win is a marginal, default-OFF BRIO-as-H.264 experimental sub-lane.

3. **Decode is not the bottleneck.** (Verdict 2.) The per-producer Python loop (~55–73% core) and ward-atlas Cairo (~69% core) and the capture readback (~2–3 cores) dwarf all decode. P0 (Python projection→GPU) and P4 (capture readback→deleted) are where the CPU actually is.

4. **The mask lane is dormant infra.** OARB ships `--mask none`; cameras are `mask none`. P0's circle-mask code is built but recovers no current CPU. State it plainly.

5. **The engine fork (B2) is a non-bottleneck win at maximal risk — deferred, not dismissed.** PCIe at 8–15 fps is not the bottleneck; the fork is render-thread surgery under hardware containment with an unsolved black-frame problem. The `.bgra` shm seam is acceptable and correct for now. Revisit only if the containment/black-frame issues resolve AND a true NVDEC-in→NVENC-out path is on the table.

6. **P4 (capture) is the largest prize but the most gated.** It depends on an attended hardware-validation session (containment), a green GL-renderer preflight, and a careful two-step `/dev/video52` retirement. Its absolute saving (~2–3 cores) is real and the largest in the spec, but it cannot be rushed and NVENC does not help it.

7. **Appendix is out for the hot path.** 1080p60 BGRA = ~4 Gbit/s one-way / ~8 Gbit/s round-trip + double network hop on an already-doubled host round-trip. Reserve for cold/offline burst only. If the 5060 Ti ever saturates, move *imagination* to appendix, not screwm pixels.

8. **The `.raw.bgra` contract drift between #3759 and reality.** #3759 is OPEN with `HAPAX_SCREWM_DRIFT_SLOTS=` empty and no real-producer raw files present. The first build step is to actually cut over one slot and confirm the producer↔service↔engine `*.raw.bgra` ↔ `*.bgra` naming + dims agree end-to-end. Do not assume the contract is exercised in production until witnessed.

---

## 6. Build sequence

Each step is independently shippable, witnessed (§4.2) before the next, and never regresses CPU (guardrail 7). One-binary-rebuild vs config-only is noted.

| Step | Lane | Depends on | Build kind | Witness gate before proceeding |
|---|---|---|---|---|
| **0. Drift cutover (one real slot)** | predecessor #3759 | #3759 merged | **config** (set `HAPAX_SCREWM_DRIFT_SLOTS=<slot>:WxH`, set that producer's `HAPAX_QUAKE_GPU_DRIFT=1`, restart) | that slot's motion metric PASS + `drift_output_hash` advancing + `*.raw.bgra`↔`*.bgra` dims agree end-to-end |
| **1. P0 — projection fold-in** | P0 | step 0 green | **binary rebuild** (`screwm_media_drift` gains `media_project.wgsl` + `mid_tex`) **+ producer edit** (skip `_project_frame`, write raw media frame, drop sphere-front `hflip`) | OARB motion PASS + 2048×1024×4 dim check + net CPU drop (Python projection gone) |
| **2. P1 — batched async-drain readback** | P1 | step 1 green (multi-pass amplifies the serialization) | **binary rebuild** (no shader) | all active slots PASS in one window + per-tick wall-time gauge ≤ `1/FPS` |
| **3. P2 — drift_v2 + DynamicPipeline** | P2 | steps 1–2 green | **binary rebuild + new WGSL nodes** | higher-ε motion PASS + visual still diff shows trail/glitch + no dim drift |
| **4. P3 — OARB NVDEC** | P3 | independent of 1–3 (producer-local); do after to avoid confounding CPU measurements | **producer edit + unit env** (`CUDA_VISIBLE_DEVICES=1`, `HAPAX_QUAKE_HWACCEL_DECODE=1`) — **no binary** | decoder util >0% + OARB motion PASS + 60 s hold-down |
| **5. Cairo producers `--gpu-drift` (optional)** | Lane K interim | step 2 green; only if numpy-drift CPU profiles hot | **config** (producer flags + extend `HAPAX_SCREWM_DRIFT_SLOTS`) | new slots PASS; abort if it raises aggregate CPU (atlas crossing penalty) |
| **6. P4 — capture export (O5)** | P4 | attended hardware-validation session + green GL-renderer preflight + containment ACK | **engine patch (export hook) + launcher + new producer mount** — biggest rebuild | final-composite OBS-frame motion PASS + GPU0 `memory.used` ≤ 27500 MiB + host stable through a full broadcast |
| **7. P4b — retire `/dev/video52` leg** | P4 follow-on | step 6 proven through a full broadcast | **config** (separate reversible commit; confirm no live OBS-direct topology) | broadcast unbroken with v4l2 leg removed |

**What is one binary rebuild vs config:**
- **Binary rebuilds (`~/.local/bin/screwm-media-drift`):** steps 1, 2, 3 (the GPU service evolves: project pass → batched readback → dynpipe+v2). All built from the existing `hapax-visual` crate; no new wgpu stack.
- **Engine rebuild (`ensure-darkplaces-live-texture-build.sh`, sha256-stamped):** only step 6 (the export-hook patch). This is the one engine touch in the whole spec, on the *export* side, gated.
- **Config / producer-script / unit-env only:** steps 0, 4, 5, 7.

**Next after the drift cutover:** Lane P0 (projection fold-in) — it deletes the heaviest Python per-pixel work, removes the `.raw.bgra` intermediate (4→3 crossings), and is the concrete first realization of the unified B1 architecture. P1 (batched readback) follows immediately because P0's multi-pass makes the serialized per-slot `Maintain::Wait` bite harder.

### Load-bearing file anchors

- **Reuse (no new wgpu stack):** `hapax-logos/crates/hapax-visual/src/bin/screwm_media_drift.rs` (`pick_adapter` 284-302, `SlotGpu::new` 83-159, `SlotGpu::process` 163-281, per-slot `Maintain::Wait` 256); `dynamic_pipeline.rs` (runner 669+, `temporal_textures` 688-692 / 2486-2511, `set_live_texture_override` 2338-2363 — the future B2 seam); `content_sources.rs` (`read_complete_rgba_frame` 708-749, `upload_rgba` 1068-1117); `output.rs` (`copy_to_staging` 79-109, `write_frame` 137-214 — base for the batched-drain helper); `agents/shaders/nodes/media_drift.wgsl` (extend; v2 TODOs 15-16, 183, 204).
- **New:** `agents/shaders/nodes/media_project.wgsl` (model after `transform`/`circular_mask`/`fisheye`); `media_drift_v2.wgsl`; a `BatchedReadback` helper in `hapax-visual`.
- **Producer edits:** `scripts/quake-live-media-source.py` (`_ffmpeg_command` 178-264, projection dispatch 452-477, `--gpu-drift` raw write 546/578-584).
- **Config / units:** `systemd/units/hapax-screwm-media-drift.service` (`HAPAX_SCREWM_DRIFT_SLOTS=` empty — the cutover knob); `systemd/units/hapax-quake-live-youtube.service` (`--mask none`, OARB ExecStart); `hapax-quake-live-camera@.service`; `config/screwm-quake-media-mounts.json` (slot dims).
- **Untouched until P4 (the decision NOT to fork ingest):** `assets/quake/darkplaces/hapax-live-texture.patch:136,322` (`fread`→`glTexSubImage2D`); `~/.cache/hapax/darkplaces-live-texture/src/gl_textures.c:958`; `src/vid_sdl.c:1798/1813` (GLX-only, no EGL — the B2 blocker).
- **Capture path (P4):** `scripts/darkplaces-v4l2-xvfb.sh` (x11grab leg 251-262), `darkplaces-gl-preflight.sh` (extend for renderer assert), `darkplaces-runtime-guard.sh` (master kill, exit 78), `systemd/units/hapax-darkplaces-v4l2.service` (containment gate L10), `config/modprobe.d/v4l2loopback-hapax.conf` (video52, reboot-coupled), `systemd/units/hapax-obs-v4l2-source-reset.service.d/zzzz-screwm-quake-video52.conf` (OBS-direct topology O5 would break), `agents/studio_compositor/pipeline.py:200` (compositor ingest), `scripts/ensure-darkplaces-live-texture-build.sh` (sha256 rebuild = engine rollback).
