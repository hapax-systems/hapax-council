# Cam stability + perf rollup — consolidated picklist

**Date:** 2026-04-14
**Author:** delta (beta role — cam-stability focus)
**Scope:** Consolidates the cam-stability arc — drops
#2, #27, #28, #29, #30 — into one prioritized picklist
for alpha. Mirrors drop #7's general perf rollup format
but scoped to the camera path from BRIO/C920 capture
through to the v4l2sink that OBS reads.
**Register:** scientific, neutral
**Status:** organizational — no new investigation

## Executive summary

**The systematic camera pipeline walk produced 13
distinct fix candidates** spread across three rings:

- **Ring 1 (drop-everything fixes)**: 4 items, all
  ~1-6 lines each. Bundle into one PR. **Total
  expected impact: eliminates spurious recovery cycles,
  bumps end-to-end OBS-output buffer from 100 ms to
  ~430 ms cushion, eliminates ~233 MB/s of wasted
  smooth_delay bandwidth.**
- **Ring 2 (small refactors)**: 3 items, single-file
  diffs of 10-30 lines each. Bundle into a second PR.
  **Total expected impact: ~660 MB/s of fallback
  bandwidth reclaimed, ~20% of one CPU core saved on
  snapshot encoding, kernel drops decoupled from
  decode latency.**
- **Ring 3 (architectural)**: 3 items requiring
  prototype + measurement before commit. Each saves
  hundreds of MB/s of memory bandwidth or eliminates
  full GPU↔CPU round-trips. **Total expected impact:
  ~1 GB/s of CPU↔GPU PCIe traffic reclaimed,
  ~1-2 CPU cores saved on producer-side decode.**

**The brio-operator sustained deficit** (drop #2's
27-28 fps vs 30 fps) is **not** in any of these
rings — it requires the operator-in-the-loop physical
cable/port swap test from drop #2 § 4. Flagged
separately as "operator action required."

## Ring 1 — drop-everything (bundle 1 PR)

| # | Fix | Source | Effort | Expected impact |
|---|---|---|---|---|
| **A** | v4l2sink userspace queue: `max-size-buffers` 1 → 5 | drop #28 #9 | 1 line | OBS-output cushion: 33 ms → 167 ms |
| **B** | v4l2loopback kernel module: `max_buffers` 2 → 8 | drop #29 #1 | modprobe + reload | OBS-output cushion: +267 ms |
| **D** | Initial frame-flow grace period for camera startup | drop #27 | 2 lines | Eliminates ~3 s of brio-operator startup data loss per restart |
| **F** | smooth_delay frame-drop probe before `gldownload` | drop #29 #3 | ~6 lines | ~233 MB/s GPU→CPU bandwidth reclaimed |

**Combined effect of A + B**: end-to-end OBS-output
buffer goes from ~100 ms (3 frames) to ~430 ms (13
frames). OBS can stall for almost half a second
without dropping frames at any layer.

**Combined effect of A + B + D + F**: ~233 MB/s of
PCIe bandwidth reclaimed, ~3 seconds of brio-operator
data loss eliminated per compositor restart, OBS-output
becomes resilient to typical scene-transition / encoder
hiccups.

**Risk profile**: A, D, F are pure userspace
single-line changes. B requires `sudo modprobe -r
v4l2loopback && sudo modprobe v4l2loopback`, which
disconnects all v4l2loopback consumers (OBS, ffmpeg
youtube-player decoders) and requires reconnect.
**Coordinate B with operator** for a planned downtime
window.

## Ring 2 — small refactors (bundle 2 PR)

| # | Fix | Source | Effort | Expected impact |
|---|---|---|---|---|
| **C** | Add producer-chain `queue` between `v4l2src` and `jpegdec` | drop #28 #1 | ~6 lines per pipeline × 6 cameras | Decouples decode stalls from kernel buffer pressure → fewer kernel-layer drops (currently invisible per drop #2 § 2.3 false zero) |
| **E** | Static-frame fallback (replace `videotestsrc pattern=ball is-live=true` with single-frame loop) | drop #28 #3 | element rewrite per pipeline × 6 fallbacks | ~660 MB/s of fallback bandwidth reclaimed |
| **G** | Migrate `jpegenc` → `nvjpegenc` on 3 snapshot branches | drop #30 #3 | swap factories at 3 sites + add cudaupload | ~20% of one CPU core reclaimed (~200 ms/sec saved) |

**Combined effect**: ~660 MB/s of fallback CPU
bandwidth + ~250 MB/s avoided cudaupload (since
fallbacks no longer produce 30 fps × 6 cameras of
NV12 frames) + ~20% CPU core for snapshots. Plus
the producer queue prevents whole classes of
"transient decode stall" → "kernel buffer overflow"
→ "frame loss" cascades.

**Risk profile**: E is the most invasive — it changes
how the always-running fallback producers behave. The
hot-swap design assumes the fallback is always
producing fresh frames; a single-frame loop
producer might surprise interpipesrc on the first
swap event. **Sandbox-test E before shipping.**

## Ring 3 — architectural (each = own prototype PR)

| # | Fix | Source | Effort | Expected impact |
|---|---|---|---|---|
| **H** | `nvjpegdec` producer rewrite (decode in CUDA memory) | drop #28 #5 + drop #29 #2 | sandbox test interpipe with CUDA caps + rewrite producer | ~248 MB/s CPU→GPU saved + ~1 CPU core (jpegdec + videoconvert) |
| **J** | Eliminate `cudadownload → glupload` round-trip after compositor | drop #30 #1 | CUDA-GL interop OR replace cudacompositor with glvideomixer | ~500 MB/s GPU↔CPU saved |
| **K** | Single `glupload` in fx_chain (share base + flash GL textures) | drop #30 #2 | refactor cairooverlay rendering path to GL | ~250 MB/s CPU→GPU saved |

**Combined effect**: ~1 GB/s of PCIe bandwidth
reclaimed across the camera-to-output path. Plus
~1 CPU core freed in the producer chain.

**Risk profile**: All three are architectural moves
that need validation. H needs interpipe to handle
CUDA memory caps (untested). J needs CUDA-GL interop
or a glvideomixer-replacement of cudacompositor (each
has its own quirks). K needs cairooverlay's text
output rendered via a GL path. **Each is a 1-2 day
prototype before commit.**

## Operator-action items (not delta-shippable)

| # | Item | Source | Why operator |
|---|---|---|---|
| **OA1** | Cable/port swap test for brio-operator | drop #2 § 4 | Distinguishes physical (cable / port signal integrity) from firmware (BRIO unit-specific) hypothesis for the sustained deficit |
| **OA2** | Decide if sustained brio-operator deficit (~28 fps on 720p) is acceptable | drop #2 + drop #27 § 5 | Operator confirmed 720p is fine. Open question: is 27.5 fps fine, or should we chase 30 fps? |
| **OA3** | Modprobe reload coordination for Ring 1 fix B | drop #29 #1 | Disconnects OBS / youtube-player consumers; needs a planned window |

## Drop #2 sustained deficit — separate track

The brio-operator sustained 27-28 fps vs 30 fps
deficit (drop #2) is **not** addressed by any of the
fixes in Rings 1-3. They reduce data loss from
*reproducible bugs in the pipeline*; the sustained
deficit is the *intrinsic* throughput of brio-operator
in the current configuration.

Drop #2 left three open hypotheses:

- H4: physical cable / port signal integrity
- H5: BRIO firmware variance (this specific unit)
- H6: jpegdec / interpipesink back-pressure

Drop #2 § 4 proposes a cable/port swap test that
distinguishes H4 from H5 in 60 s of operator action.
H6 would need a v4l2-ctl `--stream-count=300
--stream-to=/dev/null` parallel run on brio-operator
and brio-synths to compare.

**If the operator declares 27-28 fps acceptable for
brio-operator** (and given the operator already
confirmed 720p is fine, an explicit "27 fps is fine
too" would close drop #2), the entire sustained-
deficit thread can close. Otherwise it requires the
hardware test.

## Cumulative impact estimate

If alpha ships **all of Ring 1 + Ring 2** (7 fixes,
2 PRs):

- ~900 MB/s of CPU↔GPU bandwidth reclaimed (smooth
  delay + fallback waste + snapshot offload)
- ~20-30% of one CPU core saved (snapshots + fallback
  CPU work)
- ~3 seconds of brio-operator data loss eliminated
  per restart
- OBS-output buffer cushion: 100 ms → 430 ms
- Producer queue absorbs decode variance →
  fewer kernel buffer drops

If alpha then ships **Ring 3 prototypes** that
validate (H + J + K, 3 PRs):

- Additional ~1 GB/s of CPU↔GPU bandwidth reclaimed
- Additional ~1-2 CPU cores saved (producer decode
  + jpegenc)

**Total compositor budget reclaimed across all
findings**: roughly 1.5-2 GB/s PCIe bandwidth and
~2-3 CPU cores. For a compositor that today runs at
~560% CPU during livestream operation (per the
opening CPU audit), that's roughly **10-15% of the
compositor's total CPU budget** plus substantial
PCIe bandwidth headroom for other work.

## Cross-references to existing observability

The Phase 10 observability work shipped earlier today
(per drop #14 → multiple closes) gives alpha tools to
measure the impact of these fixes:

- `studio_camera_frame_interval_seconds` histogram
  (per camera) — verify Ring 1 fix D eliminates the
  startup gap
- `compositor_glfeedback_recompile_total` — already
  proving drop #5 is fixed
- `compositor_publish_costs_*` — drop #1's wired
  BudgetTracker, useful for measuring the per-source
  cost impact of Ring 2 fix E
- `studio_camera_kernel_drops_total` — currently a
  false zero (drop #2 § 2.3); fixing it would make
  Ring 1 fix C measurable

## Recommended ship order

1. **Today / next session**: Ring 1 bundle (A + B + D
   + F). Lowest risk, biggest immediate cushion gain.
2. **Within a week**: Ring 2 bundle (C + E + G). Need
   sandbox test of E first.
3. **Background investigations**: Ring 3 prototypes
   (H, J, K) — start with whichever has the most
   tractable sandbox test (probably H since drop #29
   confirmed nvjpegdec is available).
4. **Operator action**: OA1 cable swap test for
   brio-operator. 60 seconds of physical work,
   resolves the open hypothesis question from drop #2.
5. **Operator decision**: OA2 — declare whether
   27-28 fps on brio-operator is acceptable. If yes,
   drop #2's sustained deficit thread closes.

## References — every drop in the cam-stability arc

- `2026-04-14-brio-operator-producer-deficit.md`
  (drop #2) — sustained 7 % deficit, 5 hypotheses
- `2026-04-14-brio-operator-startup-stall-reproducible.md`
  (drop #27) — reproducible FRAME_FLOW_STALE on every
  cold start, no initial grace
- `2026-04-14-camera-pipeline-systematic-walk.md`
  (drop #28) — 11 findings across producer, fallback,
  consumer, compositor, output stages
- `2026-04-14-camera-pipeline-walk-followups.md`
  (drop #29) — v4l2loopback kernel buffer +
  smooth_delay download waste + nvjpegdec confirmed
- `2026-04-14-camera-pipeline-final-walk-closure.md`
  (drop #30) — fx_chain GPU↔CPU round-trips, snapshot
  CPU jpegenc, 3 architectural items

Plus the cross-cutting drops that interact with the
cam path:

- `2026-04-14-sprint-5-delta-audit.md` (drop #4) —
  cudacompositor `cuda-device-id` fragility, RTMP
  encoder pinning
- `2026-04-14-glfeedback-shader-recompile-storm.md`
  (drop #5) — fx_chain interior, **already shipped**
- `2026-04-14-metric-coverage-gaps.md` (drop #14) —
  observability gaps, including kernel-drops false
  zero
