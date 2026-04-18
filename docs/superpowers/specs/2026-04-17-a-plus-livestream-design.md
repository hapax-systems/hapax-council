# A+ Livestream — Performance + Reliability Design

**Authored:** 2026-04-17 post-Epic-2 hothouse deploy
**Operator directive:** "perfectly performant and reliable solution for an A+ livestream solution. Performance and experience nailed first" before any further feature work.
**Research inputs:** 4 parallel deep-dives (compositor internals, camera/GStreamer architecture, output + GPU contention, external industry patterns). Bibliography at end.

---

## 1. Observed state (what broke tonight)

Operator returned to a stream that was stale, hot, and janky. Live measurement:
- `studio-compositor` process at **490% CPU** sustained, load average **19–23** on a 16-thread 7700X (CPU pressure `some avg10 ~24%`, full 0% so still making progress but heavily contended)
- Thread dump dominated by `fx-glmi+` (GL shader mixer, 54% of one thread) and 8+ `fbsrc_*` fallback-producer threads at 24–35% each even when all 6 primaries were healthy
- `c920-room` camera flapping on USB (operator resolved by replugging into a different port)
- `/dev/video42` → OBS reads stalling briefly = "stale output" the operator perceived
- HLS segment-deletion races under disk pressure

**Root cause is architectural, not one bad commit.** Tonight's Epic 2 work (hothouse surfaces, cadence tightening) added ~5% of the CPU load. The remaining ~95% is the pre-existing compositor design.

## 2. The architectural story — why it's hot

Pipeline topology, mapped end-to-end:

```
6× v4l2src (MJPEG) → jpegdec (CPU) → videoconvert (CPU)
                                        ↓ interpipesrc (hot-swap)
6× videotestsrc+textoverlay (fallback producers, ALWAYS RUNNING at 30fps)
                                        ↓
cudaupload → cudacompositor → cudadownload → videoconvert (BGRA)
                                        ↓
cairooverlay (23 Cairo sources, on streaming thread)
                                        ↓
videoconvert → glupload → glcolorconvert
                                        ↓
glvideomixer → 24× glfeedback slots (18-20 passthroughs at full 1080p)
                                        ↓
gldownload → videoconvert → cairooverlay (PiP, also on streaming thread)
                                        ↓
tee → v4l2sink (→ OBS)
    → nvh264enc (HLS, 4000kbps p2) → hlssink2
    → nvh264enc (RTMP, 6000kbps p4) → flvmux → rtmp2sink → MediaMTX → YouTube Live
```

Dominant costs, in order of CPU contribution:

| Cost | Estimated CPU | Why it's expensive |
|---|---|---|
| 4× GPU↔CPU roundtrips per frame | ~150% | `cudadownload → videoconvert(BGRA) → glupload` + `gldownload → videoconvert(NV12)` |
| 6× software JPEG decode | ~100% | No hardware path on desktop NVIDIA (`nvjpegdec` is still-image only; `nvv4l2decoder mjpeg=1` exists but unverified on this build) |
| 6× always-hot fallback producers | ~80% | `videotestsrc + textoverlay (Pango) + videoconvert` per camera at full 30fps regardless of primary health |
| 24-slot `glfeedback` chain at 1080p | ~60% | 18-20 slots running `PASSTHROUGH_SHADER` as full-screen quads every frame |
| ~23 `cairooverlay` blits on streaming thread | ~50% | `cairooverlay` is documented to crash 720p pipelines to 1-2fps; each of our 23 surfaces does `gldownload → cairo → glupload` |
| Cairo source filesystem IO | ~10% | 90-120 JSON/JSONL reads/sec from hothouse + legibility panels |
| NVMe fsync (2s HLS segments) | ~5% | Under load, segment write latency spikes cause upstream queue backpressure |

## 3. hapax-imagination over-renders 9× what the compositor consumes

Findings from the research:
- `hapax-logos/src-imagination/src/main.rs:496` hardcodes `Renderer::new(1920, 1080)`
- `headless.rs:134` sets a 16ms tokio interval → **62.5fps**
- The 8-pass wgpu pipeline runs at full 1920×1080@62.5fps
- The compositor samples at 30fps into a **640×360** PiP region
- Net: **~9× pixel over-render × 2× framerate over-render = ~18× wgpu work relative to what's visible**
- Per-write blob to `/dev/shm`: 8.3 MB; aggregate shm write ~260 MB/s

This is hidden load on the 3090 (wgpu/Vulkan compute on the same GPU as `cudacompositor` and NVENC).

## 4. Output pipeline is over-bitrting 720p content

- RTMP: **6000 kbps CBR, preset p4, 1-second keyframes** → YouTube Live
- HLS: **4000 kbps CBR, preset p2, 2-second keyframes** → local-only archive
- Industry consensus (OBS, Twitch, YouTube guidance): 720p30 needs **2500–4000 kbps CBR** with preset `p1–p4`, `tune=ll`, `gop-size=60`, **no B-frames**
- HLS is currently local-only and still runs a full NVENC session 24/7 even when nobody is watching YouTube

The encoders themselves don't cost much (NVENC ASIC is isolated from SMs), but the **`videoconvert` CPU colorspace pass before each `nvh264enc`** does — and this is already optimized in the per-camera recording branch with `cudaupload → cudaconvert`, just not in the RTMP/HLS branches.

## 5. The paired fallback producer pattern is unusual

The camera-247 resilience epic runs a **hot-standby** `videotestsrc + textoverlay` producer alongside every primary camera so `interpipesrc.listen-to` can hot-swap with zero state change on USB bus-kick.

External research: **no pro broadcast switcher uses this pattern.** ATEM, vMix, Ross all use freeze-frame-plus-reacquire — on camera loss, the switcher either cuts to a slate, freezes the last-good frame for 1-3 seconds while reacquiring, or auto-cuts to a designated backup input. 100-500ms swap latency is routinely acceptable. The hot-standby pattern doubles USB bandwidth + CPU cost in steady state.

## 6. GPU contention is not the bottleneck (but it's relevant)

- NVENC is a **separate ASIC** — it does not contend with CUDA compute for SMs. tabbyAPI inference bursts do not stall the encoder.
- Consumer 3090 does **not** support MIG (H100/A100 only)
- The 5060 Ti (16 GB) is currently hosting `ollama` + `studio-compositor`'s CUDA engines. The 3090 hosts tabbyAPI. `hapax-imagination` is on GPU 0 (5060 Ti).
- True contention today is **VRAM bandwidth** on whichever GPU the compositor lives on — between `cudacompositor`, NVENC, and `hapax-imagination`'s wgpu pipeline.

## 7. Dormant perf levers that already exist

Ten configuration knobs surfaced by the research, zero code required to try them:

1. `CompositorConfig.framerate` (default 30) — propagates to every pipeline fps
2. `--no-hls` CLI flag — kills the entire HLS branch + its nvh264enc
3. `HlsConfig.enabled=False` via `~/.config/hapax-compositor/config.yaml`
4. `source.rate_hz` / `params.fps` per Cairo source in layout JSON
5. `SlotPipeline(num_slots=24)` reducible to 12 or 8 (hardcoded currently)
6. `HAPAX_TWITCH_DIRECTOR_ENABLED` / `HAPAX_STRUCTURAL_DIRECTOR_ENABLED` env toggles
7. `HAPAX_NARRATIVE_CADENCE_S` env var
8. `HlsConfig.target_duration` + `max_files` to reduce segment churn
9. `CompositorConfig.status_interval_s`
10. Global camera fps via `CompositorConfig.framerate`

## 8. The plan — prioritized remediation

### Stage 0: Tonight — zero-risk config changes (expected: 200-300% CPU saved)

All of these are config-only; no code changes, no restart risk.

| # | Change | Where | Expected impact |
|---|---|---|---|
| 0.1 | HLS disabled by default (keep archive via splitmuxsink on v4l2 → loopback consumer instead) | `~/.config/hapax-compositor/config.yaml` `hls.enabled: false` | ~40% CPU (1 entire NVENC session + fsync cascade removed) |
| 0.2 | RTMP bitrate 6000 → 3000, preset p4 → p1, tune=ll explicit | `pipeline.py:276`, `rtmp_output.py:124` | ~10% CPU (encoder + upstream convert), bandwidth halved |
| 0.3 | `hapax-imagination` render resolution 1920×1080 → 640×360 | `hapax-logos/src-imagination/src/main.rs:496` | 9× wgpu work dropped, ~5% CPU + 7.4 MB shm write/frame freed |
| 0.4 | `hapax-imagination` render rate 62.5fps → 30fps | `headless.rs:134` (`Duration::from_millis(33)`) | 50% wgpu work dropped |
| 0.5 | All hothouse + legibility Cairo sources: `rate_hz: 2` in layout JSON | `config/layouts/garage-door.json`, `config/compositor-layouts/default.json` | ~5% CPU (file IO from 90/s → 18/s) |
| 0.6 | Fallback producer fps 30 → 1 | `fallback_pipeline.py:78,100` (`fps={self._fps}/1` → `fps=1/1` when idle) | ~20-25% CPU (the #3 drain in the table above) |
| 0.7 | `SlotPipeline.num_slots` 24 → 8 | `fx_chain.py:273` | ~20-30% CPU (fewer passthrough draws); risk: presets with >8 nodes silently truncate — verify preset max is ≤8 |

**Target after Stage 0: load average ≤10, compositor ≤250% CPU, full livestream functional.**

### Stage 1: Next few days — real architectural wins (expected: additional 200% CPU saved)

| # | Change | Effort | Impact |
|---|---|---|---|
| 1.1 | RTMP + HLS branches use `cudaupload → cudaconvert` instead of CPU `videoconvert` before `nvh264enc` | S (~half day; pattern already exists in per-camera recording branch) | ~30% CPU |
| 1.2 | Pause fallback producers (NULL state) while primary HEALTHY; start on first swap | S (~1 day; ~30 lines in `pipeline_manager.py`) | ~30% CPU in steady state |
| 1.3 | Consolidate 23 Cairo overlays → single GL-composited overlay surface | M (~2-3 days) | ~50-100% CPU (each `cairooverlay` today forces gldownload→cairo→glupload) |
| 1.4 | Move `hapax-imagination` to RTX 5060 Ti via `HAPAX_IMAGINATION_DEVICE=1` + systemd `Environment=` | S (~hour) | Eliminates 3-way VRAM contention on the primary GPU |
| 1.5 | Decouple the Prometheus `_lock` from pad probe hot path (brio-operator is losing ~2fps to lock contention) | S | Restores smooth hero camera |
| 1.6 | Replace `jpegdec` with `nvv4l2decoder mjpeg=1` per camera (if `gst-inspect-1.0` confirms availability) | M (~half day per camera, plus NVMM plumbing) | 20-30% CPU |

**Target after Stage 1: compositor ≤100% CPU, load average ≤5, zero jitter on cameras or effects.**

### Stage 2: 2-3 weeks — structural redesign

| # | Change | Rationale |
|---|---|---|
| 2.1 | `compositor` (software) → `glvideomixer` + keep GL memory end-to-end | The single largest architectural win. OBS-class performance is only reachable via on-GPU composition |
| 2.2 | OBS-style architecture: per-source capture threads, single clocked `glvideomixer` render tick, shared GPU texture pool | Matches `libobs` model — eliminates the multi-clock thread proliferation |
| 2.3 | Drop the paired fallback producers entirely; switch to **freeze-frame + reacquire** (ATEM/vMix pattern) | Matches industry standard, eliminates the entire fallback producer CPU category |
| 2.4 | SRT uplink via local MediaMTX relay, RTMP as fallback only | SRT handles packet loss (ARQ); MediaMTX decouples local encoder from platform ingest so YouTube blips don't touch the compositor |
| 2.5 | Resolution decision: canvas to 1280×720 permanently; layout JSON coordinates all scaled by 0.6667 | Operator-authorized; 2.25× fewer pixels through every GL pass |

**Target after Stage 2: zero-jank 720p30 livestream 24/7 with <100% compositor CPU and quality imperceptibly different from 1080p.**

### Stage 3 (optional "nuclear option"): Custom wgpu compositor

The operator already ships production wgpu code in `hapax-imagination`. A custom 6-input wgpu compositor with NVENC output via `cudaEGL` would give OBS-class or better performance. **2-3 week epic.** Only pursue if Stage 2 doesn't close the gap, or if the operator wants to own the full stack for future flexibility (multi-scene, custom transitions, etc.).

## 9. Proposed deploy order (sequenced, safe, reversible)

1. **Stage 0 tonight**, in this order: 0.1 → 0.2 → 0.3 → 0.4 → 0.5 → 0.6 → 0.7. Each change is config-only, single compositor restart between each, revert path is `git revert` or edit config.
2. **Stage 1 over the next few dev sessions**, PR per change, measure before/after CPU + load averages each time.
3. **Stage 2 as a scoped epic** ("livestream architectural rebuild"), with research spike on `glvideomixer` compatibility, OBS architecture study, ATEM-pattern freeze-frame design.
4. Stage 3 only if needed.

## 10. What good looks like (success criteria)

After Stage 0+1:
- Compositor CPU ≤ 100% sustained (from 490%)
- Load average 1-min ≤ 5 (from 19-23)
- c920-room USB flap: auto-recover to freeze-frame within 500ms, swap back to live within 2s of reconnect
- HLS segment deletion race: zero events in 4-hour soak
- Director LLM stall: stream continues at last-frame; ≤8s timeout surfaces to JSONL
- RTMP uplink survives 10-second network blip without encoder rebuild

After Stage 2:
- Compositor CPU ≤ 50%, load average ≤ 3
- 720p30 output indistinguishable from 1080p30 to human viewer
- Camera disconnect: imperceptible in real time (freeze-frame → reacquire)
- 24-hour uptime soak with no CPU pressure events, no HLS races, no jank

## 11. Risks + open questions

- **`nvv4l2decoder mjpeg=1`** availability on desktop NVIDIA GStreamer (1.28.2 on CachyOS) — this is primarily a Jetson plugin; needs `gst-inspect-1.0` verification before Stage 1.6
- **`glvideomixer` vs software `compositor`** — Stage 2.1 assumes `glvideomixer` handles the current effect chain; a small spike should prove this before committing the architectural pivot
- **Layout coordinate rescale** for Stage 2.5 — the garage-door.json and fallback layout use absolute pixels; need automated rescale pass (0.6667 multiplier) and visual QA
- **OBS downstream** — the v4l2loopback consumer is OBS (via `/dev/video42`). OBS must be reconfigured to expect 1280×720 when Stage 2.5 ships
- **Hardware replacement** — `scripts/mediamtx-start.sh` confirms YouTube Live is the only external broadcast; HLS is local-only research archive; no Twitch / private-only to consider

## 12. Bibliography

Internal research docs (this session):
- Agent 1: Internal compositor deep map (1500 words, file-level)
- Agent 2: Camera + GStreamer architecture audit (1200 words, per-camera cost + 14 intervention options)
- Agent 3: Output pipeline + GPU contention (1200 words, 10-option intervention menu)
- Agent 4: External livestream perf research (700 words with 35 industry citations)

External citations worth anchoring design decisions on:
- NVENC Application Note (NVIDIA Video Codec SDK 13.0)
- NVIDIA NVENC OBS Guide + `nvh264enc` GStreamer docs
- GStreamer `glvideomixer` + `compositor` docs + Yocto composition notes
- OBS Studio backend design docs + DeepWiki libobs core walkthrough
- vMix User Guide + Broadcast Bridge IBC 2024 capture review
- MediaMTX GitHub + StableLearn deployment guide
- SRT vs RTMP vs WebRTC 2026 comparison (Shoutcastnet)
- Characterizing Concurrency Mechanisms for NVIDIA GPUs (arXiv 2110.00459) for MPS/MIG
- NVIDIA MPS docs (sharing compute across contexts)
- Cairo overlay performance issues (narkive gstreamer-devel, RidgeRun fast-overlay)

---

**Status:** research complete; plan ready for operator review.
**Next action:** operator picks Stage 0 sequence to ship tonight, or approves full plan for execution.
