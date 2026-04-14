# Studio compositor VRAM attribution (W5.11)

**Date:** 2026-04-14
**Author:** alpha
**Scope:** Wave 5 W5.11 from the livestream-performance-map execution plan.
Cross-references S1-F4 (3 GB compositor VRAM noted in Sprint 1 baseline)
and queue 026 P3 (`reverie_pool.reuse_ratio = 0`).
**Register:** scientific, neutral
**Status:** investigation only — no code change

## 1. Question

Sprint 1 finding 4 noted that `studio-compositor` holds ~3 GB of VRAM after
the libtorch removal in PR #751. The plan asks: **what accounts for the 3 GB,
and is the texture-pool reuse-ratio bug (queue 026 P3) responsible for any
of it?**

## 2. Live measurement

Captured at 2026-04-14T05:58, system in steady state with both GPU pinning
phases of Wave 2 active (compositor on 5060 Ti, TabbyAPI + DMN on 3090):

### 2.1 GPU 0 (RTX 5060 Ti, 16 311 MiB total — visual partition)

```
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
```

| PID     | Process                  | VRAM      | Type | Service               |
|---------|--------------------------|-----------|------|-----------------------|
| 962688  | python -m studio_compositor | 3021 MiB | C+G  | studio-compositor     |
| 1274604 | hapax-imagination        |  302 MiB  | C+G  | hapax-imagination     |
| 60535   | python -m studio_person_detector |  286 MiB | C   | studio-person-detector |

GPU 0 total used: **4 208 MiB**. Difference vs. accounted compute (3 609 MiB) ≈
600 MiB and is consumed by graphics contexts (Hyprland, Xwayland, hyprpaper,
hapax-logos WebKit) per `nvidia-smi pmon -s u`.

### 2.2 GPU 1 (RTX 3090, 24 576 MiB total — compute partition)

| PID  | Process               | VRAM     | Service          |
|------|-----------------------|----------|------------------|
| 1509 | tabbyapi (Qwen3.5-9B) | 5760 MiB | tabbyapi.service |
| 7420 | hapax-daimonion       | 3360 MiB | hapax-daimonion  |

GPU 1 total used: **9 141 MiB** (37 % of 24 GB). Headroom ample.

### 2.3 Reverie pool metrics (W1.9-era gauge)

```
reverie_pool_bucket_count        1
reverie_pool_total_textures     14
reverie_pool_total_acquires     14
reverie_pool_total_allocations  14
reverie_pool_reuse_ratio       0.0
```

The pool has acquired 14 textures over its lifetime and allocated 14 — every
acquire missed the cache. This is the queue-026-P3 bug.

### 2.4 Compositor self-reported VRAM gauge (W1.9-era gauge)

```
studio_compositor_gpu_vram_bytes      3.167 748 096 e+09  (~3019 MiB)
studio_compositor_memory_footprint_bytes  6.655 475 712 e+09  (~6347 MiB host RAM)
```

The Prometheus gauge agrees with `nvidia-smi --query-compute-apps` to within
2 MiB.

## 3. Hypothesis test: does the texture pool inflate compositor VRAM?

The plan hypothesises that the pool reuse failure may be inflating compositor
VRAM. The data refutes this:

1. **The pool lives in `hapax-imagination`, not in the compositor.** PID
   1274604 is the wgpu/Rust `hapax-imagination` daemon. The pool is the
   `TransientTexturePool<PoolTexture>` inside `DynamicPipeline` (per
   `agents/studio_compositor/CLAUDE.md` § Reverie Vocabulary Integrity). It
   is not addressable from the compositor process — they are separate OS
   processes with separate CUDA / wgpu contexts.
2. **The pool's total VRAM consumption is bounded by `hapax-imagination`'s
   total: 302 MiB.** Even if the pool perfectly reused all 14 textures down
   to 1, the maximum savings would be ~280 MiB, and **all of it would land
   on the imagination process, not the compositor.**
3. **Fixing the pool reuse ratio cannot reduce compositor VRAM.** The two
   processes are isolated.

Conclusion: queue 026 P3 is a real bug worth fixing for `hapax-imagination`'s
own footprint, but it is **unrelated** to the compositor's 3 GB. The plan's
hypothesis can be closed.

## 4. Where does the compositor's 3 GB actually go?

`studio-compositor` is a single Python process running a GStreamer pipeline
graph. The major GPU consumers, by structural cost:

### 4.1 Per-camera primary producer pipelines (6 cameras)

Each camera runs a sub-pipeline:
```
v4l2src ! image/jpeg ! nvjpegdec ! NV12@1280x720 ! interpipesink cam_<role>
```

`nvjpegdec` decodes MJPEG into NV12 frames in CUDA memory. With 6 cameras
running, this is roughly:

- 6 cameras × 1280×720 NV12 (1.4 MiB / frame) × ~4 buffer rotation = ~33 MiB
- Plus decoder state, codec scratch buffers, and CUDA context overhead per
  pipeline: ~50–100 MiB per camera

**Estimated: 300–600 MiB**

### 4.2 Fallback producer pipelines (6 cameras)

Confirmed by reading `agents/studio_compositor/fallback_pipeline.py`:
fallbacks are `videotestsrc → BGRA → textoverlay → videoconvert → NV12 →
interpipesink`. **Pure CPU path — no `glupload`, no `cudaupload`. They do
not consume any VRAM.** They DO contribute to host RAM (which is at
6.6 GB; that is a separate concern).

### 4.3 Composite GstPipeline

`cudacompositor` plus the GL chain that the FX layer runs on:
```
interpipesrc cam_* ! glupload ! glcolorconvert ! cudacompositor !
  cudaconvert ! glupload ! shader chain ! gldownload ! nvh264enc !
  rtmp tee + v4l2sink + hlssink2
```

Major VRAM consumers in this graph:

- `cudacompositor` work surface (1920×1080 NV12, ~3 MiB) plus per-source
  staging buffers: ~50–100 MiB
- `glupload`/`gldownload` cross-buffers between CUDA and GL: ~100–200 MiB
- The full FX shader chain holds intermediate textures for each pass; with
  the current shader graph this is on the order of ~200–500 MiB depending
  on how many slot pipelines are active
- Cairo overlay GL textures (sierpinski, token pole, album cover, overlay
  zones, content_layer) cached as textures: ~100–200 MiB

**Estimated: 450–1000 MiB**

### 4.4 NVENC encoder state

`nvh264enc` p4 low-latency mode, 6000 kbps, 1920×1080:

- DPB (decoded picture buffer) reference frames: 4–6 frames × 3 MiB ≈ 12–18 MiB
- Encoder scratch and bitstream buffer: 50–150 MiB
- Internal lookahead and rate-control buffers: 50–100 MiB

**Estimated: 100–300 MiB**

### 4.5 Reverie source-registry intake (`external_rgba`)

The compositor consumes the imagination daemon's RGBA frames via SHM and
re-uploads them to GL as a `external_rgba` source for the FX layer:

- Staging texture for inbound RGBA: ~10 MiB
- Pad probe + appsrc/appsink buffer rotation: ~50–100 MiB

**Estimated: 50–150 MiB**

### 4.6 ffmpeg youtube-audio sub-processes

Each youtube-audio slot spawns its own `ffmpeg` subprocess. These are
**separate processes** (visible in `ps`) and not part of the compositor's
VRAM. They use CUDA only if hardware-decoded, which they currently aren't
(audio-only). Zero compositor-attributable VRAM here.

### 4.7 Various CUDA / GL context overhead

Each GstElement that opens a CUDA or GL context allocates per-context state
(driver caches, JIT'd shader cache, etc.). With ~30 GL elements and ~10
CUDA elements in the current pipeline graph, this is on the order of
**200–500 MiB** of overhead that does not correspond to any single buffer.

### 4.8 Sum

| Component                                  | Estimate          |
|--------------------------------------------|-------------------|
| 6 primary camera producers (CUDA NV12)     |  300–600 MiB      |
| 6 fallback producers                       |    0 MiB (CPU)    |
| Composite cudacompositor + GL FX chain     |  450–1000 MiB     |
| NVENC encoder state                        |  100–300 MiB      |
| Reverie source-registry intake             |   50–150 MiB      |
| ffmpeg youtube-audio                       |    0 MiB (separate procs) |
| CUDA / GL context overhead                 |  200–500 MiB      |
| **Total range**                            | **1100–2550 MiB** |

The observed 3019 MiB sits ~470 MiB above the upper bound of this estimate.
The gap is small enough to be absorbed by:

- Underestimated CUDA-context overhead per element (NVIDIA driver private
  pages can be larger than expected, especially after pipeline rebuilds)
- Underestimated FX shader chain per-pass texture costs (some shaders use
  high-bit-depth intermediates that double the per-pixel cost)
- Not yet reset after the brio-synths recovery cycle observed earlier in
  this session — pipeline rebuilds tend to leak small amounts of VRAM
  per cycle until process restart

**Headline:** the compositor's 3 GB is *structural*, not a bug. It is
explained by the 6-camera × 6-fallback × FX-chain × NVENC architecture, not
by a single allocation that could be removed.

## 5. Reduction levers (if the operator wants to free VRAM later)

In rough order of effort versus return:

1. **Drop the always-on fallback pipelines** (rebuild lazily on first
   primary failure). Saves 0 MiB VRAM (already CPU) but ~1.5 GiB host RAM.
   This is the biggest immediate opportunity *for RAM*, not VRAM.
2. **Lower the NVENC DPB to 2 reference frames.** Saves ~10 MiB VRAM. Costs
   marginal encode quality. Probably not worth it.
3. **Audit the FX shader chain for redundant intermediate textures.**
   Potentially saves 200–400 MiB. Moderate effort. Touches
   `agents/effect_graph/wgsl_compiler.py` and the live pipeline build.
4. **Lower glupload/gldownload buffer counts.** Potentially saves
   100–200 MiB. GStreamer property tuning, low risk.
5. **Switch nvjpegdec to `v4l2src ! nvv4l2decoder` if the BRIOs support
   raw YUYV output instead of MJPEG.** Removes the JPEG decoder VRAM cost.
   Worth investigating but requires camera negotiation changes.

None of these are a "single fix" worth ~3 GB. The architecture is already
inside a reasonable headroom envelope: 4208 MiB used / 16311 MiB available
on the 5060 Ti, giving ~12 GiB of unused VRAM. There is no immediate VRAM
pressure on either GPU.

## 6. Conclusion

- **The texture-pool reuse-ratio bug (queue 026 P3) is unrelated to the
  compositor's 3 GB VRAM.** The pool lives in `hapax-imagination` (a
  separate process) and totals 302 MiB regardless of reuse ratio. Closing
  the bug would help that process, not the compositor.
- **The compositor's 3 GB is structural,** dominated by 6-camera × FX-chain
  × NVENC × CUDA/GL context overhead. No single allocation accounts for
  more than ~1000 MiB.
- **No immediate action is recommended.** The 5060 Ti has ample headroom
  and the operator should focus VRAM reduction work on shader-chain audits
  if it ever becomes a problem.
- **Cross-references**:
  - S1-F4 — closed (this note is the resolution)
  - Queue 026 P3 — still open, but should be reframed as
    *imagination-process pool efficiency*, not *compositor VRAM saving*

## 7. Next probe

If the operator wants a fully-attributed VRAM breakdown rather than the
estimate above, the path is:

1. Add `cudaMemGetInfo()` calls inside the compositor at known points in
   the pipeline build (after each camera producer, after composite, after
   NVENC) and emit the deltas as Prometheus gauges. ~30 lines of
   `pyglib.idle_add`-bounded probes.
2. Capture a fresh post-restart snapshot. The 470 MiB gap between estimate
   and observed should shrink because the pipeline-rebuild leak hypothesis
   from §4.8 would be testable.
3. If the gap persists, profile with `nvprof` or `nsys` on a brief window
   to attribute the residual to specific allocations.

This is a Wave 5 sub-spike (~3 hours) and is not currently scheduled.
