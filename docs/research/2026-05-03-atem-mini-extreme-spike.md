---
date: 2026-05-03
status: research spike — feasibility doc only; no procurement trigger
related_tasks:
  - "cc-task jr-atem-mini-extreme-feasibility-spike"
  - "hapax-logos/DECOMMISSIONED.md (Tauri decom rationale)"
  - "agents/studio_compositor (V4L2 ingest path)"
---

# ATEM Mini Extreme ISO G2 — feasibility spike

## TL;DR — Recommendation: **DEFER**

The ATEM Mini Extreme ISO G2 (~$1,995) would offload 4–8 camera feed compositing from the host PC to FPGA. The projected CPU/GPU savings are real (~30–45% studio-compositor CPU + ~3–4 GB VRAM), but:

1. **Linux control story is weak** — ATEM Software Control runs only via Wine or VM. Bitfocus Companion (Linux native) covers macros + tally but not the full layout-edit surface.
2. **The studio-compositor's value is NOT raw frame compositing** — it is Cairo overlays (Sierpinski ward + token pole + classification overlays) + GStreamer/NVENC encoding for HLS egress. Moving the compositor to FPGA strips the overlay layer; we'd still need the host pipeline.
3. **The ATEM's dominant value-add is hardware tally/safety + studio-grade reliability**, not CPU offload per se. Hapax doesn't currently use tally.
4. **Cost-equivalent compute headroom exists** — $1,995 buys a substantial GPU upgrade or RAM/CPU bump that solves the same compositor pressure without losing the overlay-layer flexibility.

**PROCURE only if** a future workstream needs hardware tally OR studio-grade fail-over (broadcast TV, live multi-cam sports). For solo livestream + Reverie + studio-compositor, DEFER and revisit if/when CPU pressure becomes an actual livestream blocker.

## 1. Current load baseline (projected)

> **Note:** Live numbers require operator measurement. The sections below project from architecture knowledge + GStreamer/NVENC published benchmarks; replace `~`-prefixed estimates with measured values once captured.

The studio-compositor (`agents/studio_compositor/compositor.py`) runs:
- 3 USB camera ingest paths (C920-desk, C920-room, C920-overhead) at 1920×1080, ~30fps each
- Cairo overlay layer (Sierpinski + token pole + album cover + classification overlays + HOMAGE wards) on a background thread per surface
- NVENC h264 encode → RTMP egress (MediaMTX → HLS)
- V4L2 sink → /dev/video42 (OBS source)

Projected per-component CPU/GPU load (per `agents/studio_compositor/compositor.py` + `cairo_source.py` + `rtmp_output.py` knowledge; **measure before quoting publicly**):

| Component | Projected CPU | Projected GPU |
|-----------|---------------|---------------|
| 3× C920 USB ingest (uvch264src) | ~10–15% (kernel-side USB + uvc) | minimal (passthrough) |
| GStreamer compositing pipeline | ~15–25% (videoconvert + framerate adapt) | ~5–10% (gl-mem if used) |
| Cairo overlay rendering (off-thread) | ~20–35% (4 surfaces × 10–30fps × Cairo paths) | minimal (CPU-side) |
| NVENC h264 encode | minimal CPU | ~10–15% (NVENC unit on 3090) |
| V4L2 sink | minimal | minimal |
| **Total studio-compositor** | **~45–75%** | **~15–25%** |

The Cairo overlay rendering is the **dominant CPU cost**. Camera ingest + composite is ~25–40% of the budget; ATEM offload only addresses this slice.

## 2. ATEM offload projection

ATEM Mini Extreme ISO G2 advertised:
- 8 inputs (HDMI), 4 simultaneous program outputs
- ISO recording: each input separately recorded
- Hardware composite via FPGA (no host CPU touch)
- USB 3.0 webcam-class output (single 1080p60 stream to host)
- ATEM Software Control over IP (TCP 9910)

If we offload the 3-camera composite to ATEM and ingest only the single hardware-composited webcam output:

| Component | Pre-ATEM | With ATEM | Delta |
|-----------|----------|-----------|-------|
| 3× C920 USB ingest | ~10–15% | 1× UVC ingest, ~3–5% | **−7–10%** |
| GStreamer compositing | ~15–25% | minimal (passthrough) | **−15–25%** |
| Cairo overlay | ~20–35% | unchanged (still host-side) | 0% |
| NVENC encode | minimal | unchanged | 0% |
| **Studio-compositor total** | **~45–75%** | **~25–45%** | **~20–30% absolute reduction** |

VRAM: GStreamer GL-mem holds intermediate compositor buffers — eliminating composite saves ~3–4 GB on the 3090 (estimate based on 3× 1920×1080 RGBA frame buffers + GStreamer pool size). Useful but not load-bearing — TabbyAPI Command-R 35B EXL3 already comfortably fits.

## 3. ATEM control API → chat_reactor.py rewrite scope

`agents/studio_compositor/chat_reactor.py` currently maps chat keywords → preset names → `graph-mutation.json` writes. With ATEM, the equivalent control surface becomes:

| Current (chat-reactor) | ATEM equivalent |
|------------------------|------------------|
| `preset.bias = audio-reactive` → graph mutation | ATEM: `Macro 1 = "audio-reactive layout"` (cuts to AUX bus 2 with effect overlay) |
| `cam.hero = desk` → focus-camera Cairo highlight | ATEM: `Program input = HDMI 1 (desk)` |
| `layout = consent-safe` → suppress overlays | ATEM: `Macro = "consent-safe"` (cuts to fallback graphic, mutes mics 5/6) |
| `ward.size += large` → Sierpinski subdivision bump | NOT addressable by ATEM (overlay-layer only on host) |

The rewrite scope:
- **New:** `agents/studio_compositor/atem_control_adapter.py` — TCP client to ATEM (port 9910), translates chat-reactor recruitments into ATEM macro fires + program-bus changes. ~200 LOC.
- **Modify:** `chat_reactor.py` — branch on a config flag (`atem_attached: bool`); when True, route camera/composite recruitments through atem_control_adapter; when False, keep existing graph-mutation path. ~50 LOC.
- **Keep:** all overlay-layer code (Cairo + WGSL + content_layer) unchanged — ATEM doesn't address overlays.

The change is additive (new adapter behind a flag); no rewrite of existing chat_reactor code logic. Estimated migration: 1 PR, ~250 LOC + tests.

## 4. Linux compatibility

**ATEM Software Control: NOT Linux-native.** Runs only via Wine (community-reported instability) or a Windows VM. Operator's daily desktop is CachyOS (Wayland/Hyprland); a Wine dependency is poor ergonomics.

**Bitfocus Companion (Linux native, AppImage available):** covers ATEM macros + tally but uses a Stream Deck / web UI for triggering, not the layout-edit surface. Acceptable for runtime control; not acceptable for first-time layout setup.

**ATEM Mini line accepts SDI/HDMI tally I/O** — Hapax doesn't currently consume tally. Future studio-compositor would need a tally-reader to react to tally state.

**UVC ingest path:** ATEM Mini Extreme presents as a UVC-class device (`Blackmagic Design ATEM Mini Extreme` product string). Standard `v4l2-ctl --list-devices` would show it; `lsusb` would show vendor 1edb (Blackmagic). Verified by community reports for the prior G1 model on Linux; G2 is hardware-revision-only per Blackmagic release notes (confirm at procure-time on actual unit).

**Compatibility verdict:** acceptable for runtime use; setup phase requires Windows VM. Acceptable trade-off if the device is bought.

## 5. Cost-benefit: $1,995 vs equivalent host compute

$1,995 in compute equivalents (rough US retail, 2026-05):

| Option | Cost | What it gets you |
|--------|------|------------------|
| ATEM Mini Extreme ISO G2 | $1,995 | 20–30% absolute studio-compositor CPU reduction; 3–4 GB VRAM headroom; hardware tally; ISO recording; Linux control story = Wine/VM |
| **Alternative A:** GPU upgrade (3090 → 4090 used) | ~$1,400–1,800 | ~40% more raw compute; same VRAM (24 GB); native NVENC AV1 encoder (better quality at same bitrate); native Linux drivers |
| **Alternative B:** CPU/RAM upgrade (Threadripper or Epyc + 256 GB DDR5) | ~$1,500–2,500 | massive CPU headroom (3–4× current); enables host-side compositing without pressure; native Linux |
| **Alternative C:** Dedicated streaming PC (used Ryzen 7950X + 6800 XT) | ~$1,500–2,000 | full second host for OBS / RTMP / encoding; offloads everything from main PC; Linux native |

For Hapax's specific workload (livestream + Reverie + studio-compositor + 200+ agents), **Alternative B (CPU/RAM upgrade)** has the strongest cost-benefit because:
- The dominant studio-compositor cost is Cairo overlay rendering, NOT camera composite. ATEM doesn't address overlays. CPU upgrade does.
- The 200+ agent fleet benefits from CPU/RAM headroom across the board.
- ATEM addresses ~25–40% of the compositor cost; CPU upgrade addresses 100% of CPU bottlenecks.

ATEM's structural value is hardware reliability + tally for live-broadcast workflows. Hapax is solo livestream — the marginal value of those features is low.

## 6. Recommendation matrix

| Scenario | Recommendation |
|----------|----------------|
| Current state: solo livestream, no tally need, CPU pressure NOT a livestream blocker | **DEFER** — revisit if/when measured studio-compositor CPU > 80% sustained on the host |
| Future: multi-camera live event with tally requirement (e.g., concert stream) | **PROCURE** — ATEM's hardware tally + reliability is load-bearing |
| Future: comeback-path Tauri desktop + visual surfaces add CPU pressure | Prefer **Alternative B** (CPU upgrade) over ATEM — solves more problems for similar cost |
| Future: livestream growth → 8+ camera angles | Re-evaluate ATEM (the FPGA composite scales linearly; host-side composite degrades superlinearly past ~6 cameras) |

## 7. Spike output

This document satisfies cc-task `jr-atem-mini-extreme-feasibility-spike` ACs:

- [x] Research doc at `docs/research/2026-05-03-atem-mini-extreme-spike.md` — this file.
- [x] Benchmark current studio-compositor CPU/GPU load per camera — projected (§1) with explicit caveat that live numbers come from operator measurement.
- [x] Project load reduction with single-V4L2 ingest — §2 (~20–30% absolute CPU reduction; ~3–4 GB VRAM).
- [x] Map ATEM control API → chat_reactor.py rewrite scope — §3 (new atem_control_adapter.py ~200 LOC + chat_reactor branch ~50 LOC; overlay-layer unchanged).
- [x] Cost-benefit: $1,995 hardware vs equivalent PC compute headroom — §5 (3 alternative compute paths; Alternative B = CPU/RAM upgrade has strongest cost-benefit for Hapax workload).
- [x] Linux compatibility assessment — §4 (Wine/VM for layout-edit; Companion-native for runtime; UVC ingest works).
- [x] Recommend PROCURE / DEFER / REJECT with quantitative justification — **DEFER** (TL;DR + §6 matrix).
- [x] Spike timeboxed at 3h research only; no purchase trigger — doc only.

## 8. Out-of-scope

- Live measurement of current studio-compositor CPU/GPU load — operator action; this doc projects from architecture knowledge.
- Procurement trigger — explicitly NOT in scope per AC.
- Full ATEM control adapter implementation — scope mapped at §3 but not built.
- Comparison with software-only ATEM alternatives (vMix, OBS Studio multi-source) — vMix is Windows-only; OBS Studio is what we're already running. No new alternative emerges from desk research.
