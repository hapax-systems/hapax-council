# Camera pipeline systematic walk — capture → compositor → OBS sink

**Date:** 2026-04-14
**Author:** delta (beta role — cam-stability focus)
**Scope:** Per the operator's request, walks the entire
camera path from USB capture through every GStreamer
element to the `v4l2sink` that OBS consumes
(`/dev/video42`). Identifies perf and stability concerns
at every touch point in the chain. Companion to drop #2
(brio-operator sustained deficit) and drop #27 (startup
stall).
**Register:** scientific, neutral
**Status:** investigation only — many small fix
candidates plus one structural observation about
GPU-side decode

## Headline

**Eleven findings across the pipeline**, ordered roughly
by data-flow position:

1. **No `queue` between `v4l2src` and `jpegdec` in the
   producer chain**
   (`camera_pipeline.py:152-165`). Decode stalls
   backpressure directly into v4l2src → kernel buffer
   queue exhaustion → frame drops at the v4l2 layer
   (silently, because `studio_camera_kernel_drops_total`
   is the false-zero from drop #2). **A 1-element queue
   here decouples decode latency from capture.**
2. **`v4l2src` only sets `device` and `do-timestamp`**
   — no `io-mode`, no `num-buffers`, no `blocksize`.
   Default `io-mode=auto` typically picks `mmap` with a
   small queue depth. Bumping `num-buffers` or switching
   to `userptr` could improve resilience to short
   stalls.
3. **6 always-running `videotestsrc pattern=ball
   is-live=true` fallback pipelines** at 1280x720 BGRA
   30fps + textoverlay + videoconvert NV12 + interpipesink
   (`fallback_pipeline.py:60-130`). Each costs ~110 MB/s
   of synthetic frame production + cairo text rendering.
   **~660 MB/s aggregate of mostly-unused fallback CPU
   work.** A static "OFFLINE" frame held in interpipesink
   buffer would cost zero.
4. **`watchdog timeout=2000ms` hardcoded** in producer
   chain (`camera_pipeline.py:121`) with no upstream
   buffering. Combined with `STALENESS_THRESHOLD_S=2.0`
   from drop #27, **a 2-second stall anywhere in the
   producer chain kills the pipeline**.
5. **6 separate `cudaupload` operations per frame**
   (`cameras.py:150`). Each camera has its own
   `interpipesrc → cudaupload → cudaconvert → cudascale →
   cudacompositor` chain. **At 1280×720 NV12 (1.38 MB)
   × 6 cameras × 30 fps = ~248 MB/s of CPU→GPU
   transfer** for camera frames alone.
6. **Camera consumer queues are `max-size-buffers=2,
   leaky=2`** — 2-frame cushion is ~67 ms at 30 fps.
   Tight but possibly intentional for low latency.
   Combined with the producer-side absence of queues
   (finding 1), the entire path has < 100 ms of buffer
   anywhere.
7. **`cudacompositor` sink pads are set with raw
   `xpos`/`ypos`/`width`/`height`** but **no
   `cuda-device-id`** (`cameras.py:184-187`). Per drop
   #4, the compositor's CUDA element falls back to
   CUDA's default device — currently lands on GPU 0
   (5060 Ti). Will silently move if CUDA enumeration
   changes.
8. **Output stage costs a full `cudadownload` per frame**
   (`pipeline.py:91-94`): cudacompositor → cudadownload
   → videoconvert (BGRA) → bgra-caps. 1920×1080×4 = **8.3
   MB downloaded per frame from GPU to CPU**, every
   single frame. Required because v4l2sink doesn't accept
   GPU memory.
9. **v4l2sink branch has `max-size-buffers=1` queue**
   (`pipeline.py:131`). A single-buffer cushion before
   the OBS-consumed sink. Any 33 ms hiccup in v4l2sink
   drops the frame. Very tight — a 3-5 frame buffer would
   absorb transient stalls without dropping.
10. **`videoconvert` BGRA→YUY2 conversion happens on CPU
    after cudadownload** (`pipeline.py:132-141`). This is
    a second full-frame CPU pass on every frame. Could
    happen on GPU before download via `cudaconvert` to
    NV12 → smaller download → CPU NV12→YUY2 (or
    `cudaconvert` direct to YUY2 if supported).
11. **`identity drop-allocation=true`** is correctly used
    as the standard v4l2loopback workaround (`pipeline.py:144`).
    No concern — flagging because it's a defensive
    pattern worth understanding for future modifications.

## 1. Detailed walk — every touch point

### 1.1 USB hardware layer

Per drop #2 § 2.4: 6 cameras across multiple xHCI
controllers. brio-operator + brio-synths share the AMD
Matisse controller (PCI 09:00.3) at IRQ 66 on CPU 7.
brio-room shares AMD 500 Series (PCI 01:00.0) at IRQ 57
on CPU 5. C920s spread across both. **No USB IRQ
affinity tuning** — IRQs land where the kernel default
puts them.

Per drop #2: USB power control on each camera is
individually configured (`auto` for brio-room,
`on` for the others). USB 3.0 cameras use 5000 Mbps
links. No bus contention identified.

**No tunable here that delta hasn't already flagged in
drop #2.**

### 1.2 Kernel uvcvideo driver

`/sys/module/uvcvideo/parameters/` exposes module
parameters. Not inspected in this drop. Common knobs
worth checking:

- `nodrop` — when set to 1, uvcvideo never drops frames
  on buffer overrun (instead, the next read returns the
  oldest unconsumed frame). Default 0.
- `quirks` — per-device workarounds, set via the device
  ID. Logitech BRIO has known quirks for some
  generations.
- `clock` — clock source for buffer timestamps
  (`monotonic` vs `realtime`). Default monotonic.

Worth a follow-up audit but not core to today's
investigation.

### 1.3 v4l2 device layer

The compositor configures each camera via `v4l2-ctl`
in `webcam-setup` udev hooks (per drop #20-area udev
rules). Configurations include:

- `exposure=333` for both BRIOs and C920s
- `sharpness=128` on BRIOs, `sharpness=110` on C920s
- `gain=140` on C920s (BRIOs auto)
- `exposure_dynamic_framerate=0` (forced fixed
  framerate, 720p 30fps)

Per drop #2: all configurations are identical between
brio-operator and brio-synths, so the sustained 7%
deficit is not caused by per-camera v4l2 control
differences.

### 1.4 `camera_pipeline.py` — producer chain

Built per-camera, owned by `PipelineManager`. Element
chain:

```text
v4l2src device=/dev/v4l/by-id/...
   do-timestamp=true                     ← only knobs set
  ↓
capsfilter (image/jpeg, 1280x720, 30/1)
  ↓
watchdog timeout=2000                    ← 2s timeout
  ↓
jpegdec
  ↓
videoconvert dither=0
  ↓
capsfilter (video/x-raw, NV12, 1280x720, 30/1)
  ↓
interpipesink name=cam_<role>
   sync=false async=false
   forward-events=false forward-eos=false
```

**No queue elements anywhere in this chain.** Backpressure
from any element propagates synchronously upstream to
v4l2src.

**Pad probe on interpipesink.sink** updates
`_last_frame_monotonic` per frame. This feeds the
FRAME_FLOW_STALE check from drop #27 and the
`studio_camera_frame_interval_seconds` histogram.

**Findings 1, 2, 4 above pertain to this section.**

### 1.5 `fallback_pipeline.py` — synthetic standby

Built per-camera, also owned by PipelineManager. Always
running, even when the primary camera is healthy. Hot-
swap design: instant switching via `interpipesrc.listen-to`
property write, no state change required.

```text
videotestsrc pattern=ball is-live=true
  ↓
capsfilter (video/x-raw, BGRA, 1280x720, 30/1)
  ↓
textoverlay text="CAMERA <ROLE> OFFLINE"
   font-desc="Sans Bold 60"
  ↓
videoconvert dither=0
  ↓
capsfilter (video/x-raw, NV12, 1280x720, 30/1)
  ↓
interpipesink name=fb_<role>
   sync=false async=false
```

**Finding 3 above pertains to this section.** Cost
breakdown per camera:

- `videotestsrc` BGRA generation: 1280×720×4 = 3.69 MB
  per frame × 30 fps = **110 MB/s**
- `textoverlay` cairo render: small fixed cost per
  frame (~0.1-0.5 ms)
- `videoconvert` BGRA→NV12: ~5-10 ms CPU per frame
- × 6 cameras

**Estimated aggregate cost of the fallback layer:
~660 MB/s of memory bandwidth + several ms of CPU per
frame per camera.** The pattern in the journal shows
fallback is rarely consumed (only during the initial
brio-operator startup stall window from drop #27). Most
of this work is wasted.

**Optimization candidates:**

- **Static frame instead of bouncing ball**: replace
  `videotestsrc pattern=ball` with `videotestsrc
  pattern=black` rendered once and held by interpipesink
  in its sink-buffer. Costs ~zero per frame after the
  first.
- **Lower fps**: drop fallback to 5 fps. The "OFFLINE"
  display doesn't need motion. Saves 5/6 of the
  aggregate cost.
- **Remove textoverlay**: render the "OFFLINE" text
  into a static PNG once at startup, blit via
  appsrc → imagefreeze. No per-frame cairo cost.

The instant-hot-swap design assumed always-running
fallbacks were "free." They aren't — they cost ~660 MB/s
of CPU bandwidth.

### 1.6 `pipeline_manager.py` — supervisor and hot swap

Manages 12 sub-pipelines (6 cameras + 6 fallbacks) plus
6 interpipesrc consumers. Provides:

- `swap_to_fallback(role)`: single property set
  (`src.set_property("listen-to", fb.sink_name)`)
- `swap_to_primary(role)`: same shape
- Per-camera state machine integration
- Frame-flow watchdog (covered in drop #27)
- `_REBUILD_DELAY_S = 5.0` fixed reconnect delay (no
  exponential backoff)

**No findings here that aren't already in drop #27.**

The `_REBUILD_DELAY_S = 5.0` fixed delay is worth a note:
under sustained USB flakiness (e.g., a marginal cable),
the supervisor reconnects every 5s indefinitely. Adding
exponential backoff (5s → 10s → 20s → 60s cap) would
reduce the storm of rebuild attempts when a camera is
genuinely unrecoverable.

### 1.7 `cameras.py` `add_camera_branch` — consumer side

For each camera, builds:

```text
interpipesrc consumer_<role>
   listen-to=cam_<role>
   stream-sync=restart-ts
   allow-renegotiation=true
   is-live=true
   format=time
  ↓
tee tee_<role> allow-not-linked=true
  ├─→ branch 1: compositor input
  │     queue (leaky=2 max-size-buffers=2)
  │     cudaupload                              ← per-camera GPU upload
  │     cudaconvert
  │     cudascale
  │     capsfilter (CUDAMemory, tile.w x tile.h)
  │     → cudacompositor sink_%u (xpos/ypos/w/h on pad)
  ├─→ branch 2: snapshot
  │     queue (leaky=2 max-size-buffers=2)
  │     videoconvert dither=0
  │     videorate (fps=1/5)
  │     videoscale → 640×360
  │     jpegenc quality=75
  │     appsink → /dev/shm/<role>.jpg
  └─→ branch 3: recording (conditional)
        add_recording_branch
```

**Findings 5, 6, 7 above pertain to this section.**

The 6 separate `cudaupload` operations are the
fundamental unavoidable cost of doing camera capture in
CPU and composition in GPU. The alternative is a CPU
compositor (which `pipeline.py:43-47` falls back to),
which would skip the upload but pay the full cudacompositor
work cost on CPU. Order of magnitude difference: CPU
compositing 6×1280×720 → 1920×1080 with alpha is
expensive (~10-20 ms per frame), GPU compositing is
~1-2 ms.

**Net: the cudaupload cost is real but probably the
right design choice.** Worth noting it because if the
operator ever wants to reduce CPU→GPU bandwidth, this
is a substantial chunk.

A potential alternative: `nvjpegdec` (NVIDIA hardware
JPEG decoder, ships with `gst-plugin-nvcodec`) decodes
MJPG directly into CUDA memory, eliminating the
`videoconvert` and `cudaupload` steps in the producer
chain. **Worth checking if `nvjpegdec` is available**:

```bash
gst-inspect-1.0 nvjpegdec
```

If it is, the producer chain becomes:

```text
v4l2src → image/jpeg caps → nvjpegdec → cuda NV12 caps → interpipesink
```

And the consumer chain becomes:

```text
interpipesrc → cudaconvert → cudascale → cudacompositor
```

No `cudaupload` step. Net saving: ~248 MB/s of CPU→GPU
transfer + the cost of `videoconvert` in the producer.
Real win.

But: `interpipesink`/`interpipesrc` would need to handle
CUDAMemory-flagged caps for the hot-swap to work. May
require interpipe upgrades.

### 1.8 `cudacompositor` composite stage

Single instance, takes 6 sink pads (one per camera tile),
produces the 1920×1080 BGRA composite. Per
`pipeline.py:41-47`:

- Tries `cudacompositor` first
- Falls back to CPU `compositor` if cudacompositor
  unavailable
- No `cuda-device-id` set — uses CUDA default device

Per drop #4 § 1.2, the runtime currently lands on GPU 0
(RTX 5060 Ti). Drop #4 flagged that the lack of explicit
pinning is fragile across CUDA reorderings.

**Finding 7 above pertains to this section.** Already
covered, fix proposed in drop #4 § 1.2.

### 1.9 Output chain — cudacompositor → tee → branches

```text
cudacompositor
  ↓
cudadownload                             ← finding 8
  ↓
videoconvert (BGRA) dither=0
  ↓
capsfilter BGRA, 1920×1080, 30/1
  ↓
pre_fx_tee
  ├─→ snapshot branch (add_snapshot_branch)
  └─→ fx_chain: build_inline_fx_chain
        → output_tee
            ├─→ v4l2sink branch
            ├─→ HLS branch (if enabled)
            ├─→ fx snapshot branch
            ├─→ smooth_delay branch
            └─→ rtmp_bin (detached until toggle)
```

The fx_chain (covered in drops #5 + #14) sits between
pre_fx_tee and output_tee, applying the 24-slot
glfeedback shader pipeline. Findings already addressed.

### 1.10 v4l2sink branch — the OBS-consumed output

```text
output_tee → src_%u
  ↓
queue queue-v4l2 leaky=2 max-size-buffers=1   ← finding 9
  ↓
videoconvert convert-out dither=0             ← finding 10 (CPU)
  ↓
capsfilter sink-caps (YUY2, 1920×1080, 30/1)
  ↓
identity drop-allocation=true                  ← finding 11
  ↓
v4l2sink output device=/dev/video42 sync=false
```

Plus a `_caps_dedup_probe` on `queue_v4l2.sink` that
drops duplicate CAPS events to prevent v4l2sink
renegotiation when input-selector switches sources.
Defensive against a known v4l2loopback edge case.

**Findings 9, 10, 11 pertain to this section.**

The `max-size-buffers=1` is the most concerning. Voice-
quality realtime audio uses similarly tight buffers, but
voice has 1-2 ms quanta where video has 33 ms quanta.
A 33 ms hiccup in v4l2sink at the kernel layer (e.g.,
v4l2loopback userspace consumer briefly stalled) drops
a frame entirely. Bumping to 3-5 frames (~100-167 ms
cushion) absorbs realistic transient stalls without
introducing meaningful latency.

### 1.11 Other branches off the output_tee

- **HLS branch** (`add_hls_branch`): writes
  `~/.cache/hapax-compositor/hls/segment_NNNNN.ts` via
  hlssink2. Per drop #20, the rotation timer was
  dormant until earlier today. **Now rotating.**
- **fx_snapshot branch** (`add_fx_snapshot_branch`):
  produces `/dev/shm/hapax-compositor/fx-*.jpg`
  snapshots for the visual layer aggregator and
  classifier.
- **smooth_delay branch** (`add_smooth_delay_branch`):
  exact purpose unverified — likely a delayed copy
  of the output for synchronized playback or A/V
  sync. Worth a separate look.
- **rtmp_bin** (constructed but detached): NVENC →
  flvmux → rtmpsink → MediaMTX. Drop #4 § 5.1
  covered the detached state.

## 2. Findings ordered by fix effort × impact

Where "Ring 1" = drop-everything, "Ring 2" = small fix
candidate, "Ring 3" = research follow-up:

| # | Finding | Ring | Effort | Estimated impact |
|---|---|---|---|---|
| 9 | v4l2sink queue `max-size-buffers=1` | 2 | 1 line | Eliminates frame drops on transient stalls |
| 1 | No queue between v4l2src and jpegdec | 2 | 1 element add per pipeline | Decouples decode from capture, reduces kernel drops |
| 3 | Always-running fallback @ 30 fps with cairo overlay | 2 | Replace with static frame | Reclaims ~660 MB/s of CPU bandwidth |
| 4 | watchdog 2s + no upstream buffering | 2 | Bump watchdog to 5s OR add producer queue | Less spurious recovery cycles |
| 8 | cudadownload per frame (8.3 MB each) | 3 | Architectural — investigate `cudaconvert` to YUY2 before download | Saves ~250 MB/s GPU→CPU + half a CPU core |
| 10 | CPU videoconvert BGRA→YUY2 in output | 3 | Pair with finding 8 | ~5-10 ms/frame CPU saved |
| 5 | 6 cudauploads per frame (~248 MB/s) | 3 | Investigate `nvjpegdec` for GPU-side decode | Saves ~250 MB/s CPU→GPU + producer videoconvert |
| 2 | v4l2src has no `io-mode`/`num-buffers` set | 3 | Tune both | Marginal — defaults usually OK |
| 6 | Consumer queue `max-size-buffers=2` | 3 | 1 line per branch | Marginal at current cadence |
| 7 | cudacompositor no `cuda-device-id` | 3 | Set explicitly OR `CUDA_VISIBLE_DEVICES=0` | Drop #4 already covers |
| 11 | identity drop-allocation=true (informational) | — | — | Already correct, noted for awareness |

## 3. The v4l2sink queue is the highest-leverage fix

Of all 11 findings, **#9 is the cheapest and most
directly improves cam stability**. One config line on
one queue. Bumps `max-size-buffers` from 1 to ~5, gives
v4l2sink ~167 ms of headroom against transient stalls,
zero added latency in the steady state (the queue only
fills under back-pressure). Specifically:

```python
# pipeline.py:131 — current
queue_v4l2.set_property("max-size-buffers", 1)

# proposed
queue_v4l2.set_property("max-size-buffers", 5)
```

Also worth bumping `max-size-time` to make the limit
explicit in time units rather than buffer count:

```python
queue_v4l2.set_property("max-size-time", 200_000_000)  # 200 ms in ns
```

**leaky=2 (downstream)** stays — when the queue does
fill, drop the newest frame to keep latency bounded.
This is the right choice for a realtime sink that has
no consumer-side buffering (OBS reads what's there
when its capture thread runs).

## 4. The producer queue absence is the highest-leverage
stability fix

The structural decision in `camera_pipeline.py` to chain
elements directly without queues means **every camera
producer is one decode stall away from a kernel buffer
drop**. Adding a single queue between v4l2src and
jpegdec gives jpegdec a small buffer to absorb decode
variance:

```python
# camera_pipeline.py — propose adding before the existing chain
queue_decode = Gst.ElementFactory.make("queue", f"queue_decode_{self._role_safe}")
queue_decode.set_property("leaky", 0)  # don't drop, backpressure instead
queue_decode.set_property("max-size-buffers", 4)  # ~133 ms cushion
queue_decode.set_property("max-size-time", 200_000_000)
queue_decode.set_property("max-size-bytes", 0)  # disable byte limit

elements = [src, src_caps, watchdog, queue_decode]
if decoder is not None:
    elements.append(decoder)
elements.extend([convert, out_caps, sink])
```

Note `leaky=0` here (backpressure rather than drop) —
because the producer chain is the FIRST place to absorb
variance. If we drop here, kernel still loses the next
frame. If we backpressure, decode catches up within the
buffer window and capture continues without loss.

**Test**: with the queue in place, `studio_camera_frame_interval_seconds`
should show fewer gaps in the >40 ms buckets for cameras
under decode-stall scenarios.

## 5. The fallback layer cost is real

660 MB/s is **not negligible**. For comparison, drop #2
showed brio-operator running at 27.94 fps consuming
~5-6 ms of producer thread per frame. The aggregate
fallback cost (660 MB/s) is roughly equivalent to running
six additional medium-bandwidth video decoders in the
background.

The justification for always-running fallbacks is
"instant hot-swap with no state change." But the
hot-swap cost is **one property write** —
`src.set_property("listen-to", new_sink)`. The state
change is on the interpipesrc side, not the producer
side. The producer doesn't need to actually be
producing fresh frames in the fallback case — it just
needs to have a current buffer in its sink that
interpipesrc can read.

**Hypothesis**: a fallback pipeline configured with
`videotestsrc num-buffers=1 is-live=false` would produce
one frame at startup, the interpipesink would hold it,
and the videotestsrc would terminate. The interpipesrc
on hot-swap would still read the held buffer.

If this works (untested), the fallback cost drops from
660 MB/s aggregate to ~zero. Worth a 5-minute test in a
sandbox pipeline.

## 6. nvjpegdec investigation

`gst-inspect-1.0 nvjpegdec` would tell us if the
NVIDIA hardware JPEG decoder is available on this
system. If yes, the producer chain can do MJPEG →
CUDA memory directly without the CPU jpegdec → CPU
videoconvert → CPU NV12 → cudaupload chain.

Per workspace CLAUDE.md, the `gst-plugin-nvcodec`
package on Arch usually provides the full set of
NVIDIA elements: `nvh264dec`, `nvh264enc`,
`nvjpegdec`, `nvjpegenc`, `nvv4l2decoder`, etc. Worth
verifying.

## 7. What's not in this drop

- **Recording branch** (`add_recording_branch`) — only
  active when `compositor.config.recording.enabled` is
  true. Likely off in the current config; flagging as
  a follow-up if recording becomes active.
- **smooth_delay branch** purpose — the function exists
  but I didn't read its source. Worth a follow-up.
- **HLS branch internals** — only relevant now that the
  rotation timer is enabled (drop #20 fix). Worth a
  follow-up audit on the hlssink2 element itself.
- **rtmp_bin internals** — covered by drop #4 (sprint-5
  delta audit).
- **cudacompositor sink-pad alpha blending** — could be
  a perf factor if any tile uses alpha. Not investigated.
- **cudascale algorithm** — bilinear vs lanczos can
  have CPU/GPU cost differences. Not investigated.
- **GStreamer thread pool sizing** — `GST_DEBUG_DUMP_DOT_DIR`
  would visualize the threading topology. Not done.
- **Kernel uvcvideo module parameters** — flagged in
  § 1.2 as a follow-up area.

## 8. Follow-ups for alpha (cam-stability sprint)

Ordered by ratio:

1. **Bump v4l2sink queue from 1 → 5 buffers** — finding 9.
   1-line fix. Eliminates frame drops on the
   OBS-consumed output for any 33-167 ms transient
   stall.
2. **Add producer queue between v4l2src and jpegdec** —
   finding 1. ~6 lines per pipeline. Decouples decode
   from capture, reduces kernel drops.
3. **Try the static-frame fallback hypothesis** —
   finding 3 § 5. Sandbox test with
   `num-buffers=1 is-live=false`. If it works, ship
   the change for ~660 MB/s reclaimed.
4. **Bump producer watchdog from 2s → 5s OR add producer
   queue** — finding 4. Reduces false-positive spurious
   recovery cycles.
5. **Verify `nvjpegdec` availability** — finding 5 § 1.7.
   `gst-inspect-1.0 nvjpegdec`. If present, prototype
   GPU-side decode in one camera and measure the
   resulting CPU savings.
6. **Investigate `cudaconvert` to YUY2 before
   `cudadownload`** — findings 8 + 10. Possibly
   `cudaconvert` doesn't support YUY2 in CUDAMemory;
   need to check supported formats.
7. **Add a `studio_camera_pipeline_rebuild_count`
   metric** — `CameraPipeline._rebuild_count` is
   tracked but not published. Same pattern as the
   other Phase 10 observability shipped today.
8. **Inspect `/sys/module/uvcvideo/parameters/`** for
   `nodrop`, `quirks`, `clock`. Out of scope for this
   drop but worth a follow-up audit.

## 9. References

- `agents/studio_compositor/camera_pipeline.py` — full file
- `agents/studio_compositor/fallback_pipeline.py` — full file
- `agents/studio_compositor/cameras.py` — `add_camera_branch`,
  `add_camera_snapshot_branch`
- `agents/studio_compositor/pipeline.py` — `build_pipeline`
- `agents/studio_compositor/pipeline_manager.py` —
  `swap_to_primary`/`swap_to_fallback`
- Drop #2 (brio-operator deficit) — sustained-deficit
  context for the brio-operator camera
- Drop #4 (sprint-5 delta audit) — cudacompositor
  device pinning, RTMP path
- Drop #5 (glfeedback storm) — fx_chain interior
- Drop #14 (metric coverage gaps) — observability
  context
- Drop #27 (brio-operator startup stall) — frame-flow
  watchdog on the producer pad probe
- Live process: `studio-compositor.service` PID
  4157979 at 2026-04-14T17:00 UTC
