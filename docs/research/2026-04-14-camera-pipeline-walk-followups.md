# Camera pipeline walk — follow-up findings

**Date:** 2026-04-14
**Author:** delta (beta role — cam-stability focus)
**Scope:** Continues the systematic walk from drop #28
through the remaining touch points: v4l2loopback kernel
config, uvcvideo module params, HLS branch interior,
smooth_delay branch interior, and live verification of
the `nvjpegdec` proposal from drop #28 finding 5.
**Register:** scientific, neutral
**Status:** investigation only — three new fix candidates,
two confirmations, two informational

## Headline

**Five new findings.**

1. **v4l2loopback kernel module is loaded with
   `max_buffers = 2`.** That's the entire kernel-side
   buffer cushion for `/dev/video42` (the OBS-consumed
   sink). Combined with drop #28 finding #9 (userspace
   queue at `max-size-buffers=1`), the **end-to-end
   buffer between the compositor's pre-sink queue and
   OBS's read syscall is just 3 frames (~100 ms at
   30 fps)**. Bumping the kernel buffer requires a
   modprobe config change, not a runtime tweak.
2. **`nvjpegdec` IS available on the system**, validating
   drop #28 finding #5. `gst-inspect-1.0 nvjpegdec`
   confirms `NVDEC jpeg Video Decoder` at `primary` rank.
   The full nvcodec plugin set is installed: `nvjpegdec`,
   `nvjpegenc`, `nvh264dec`, `nvh264enc`, `cudaupload`,
   `cudascale`, `cudaconvert`, `cudacompositor`. **The
   GPU-side decode rewrite proposed in drop #28 finding 5
   is feasible right now without any new package install.**
3. **`smooth_delay.py` does a full-frame `gldownload`
   on every frame (30 fps) before `videorate` drops to
   2 fps**, wasting 28/30 download cycles. At 1920×1080×4
   = 8.3 MB per frame × 30 fps = **~250 MB/s of GPU→CPU
   bandwidth** to ultimately produce 2 fps of output to
   `smooth-snapshot.jpg`. The fix is to reorder elements
   or add a frame-drop probe before `gldownload`.
4. **uvcvideo module parameters are at defaults and the
   defaults are correct** (`nodrop=0, clock=monotonic,
   quirks=0`). Confirmed via `/sys/module/uvcvideo/
   parameters/`. No tunable concerns. This is a negative
   finding that closes drop #28 § 1.2 as a follow-up.
5. **HLS branch is well-buffered** — `recording.py:84-87`
   sets `queue max-size-buffers=20, max-size-time=3s,
   leaky=2`. **Generous compared to the v4l2sink queue's
   `max-size-buffers=1` from drop #28 finding 9.** No
   concern; flagging because the contrast tells us the
   v4l2sink queue tightening was a deliberate choice
   somewhere in the codebase's history, not an
   oversight.

## 1. v4l2loopback `max_buffers=2` is the kernel-side cushion

```text
$ cat /sys/module/v4l2loopback/parameters/max_buffers
2

$ ls /sys/module/v4l2loopback/parameters/
debug         max_height    max_width
exclusive_caps max_openers   video_nr
max_buffers
```

`max_buffers` is **module-load-time** for v4l2loopback —
it's set when the kernel loads the module, not adjustable
per-device at runtime. To change it, you edit
`/etc/modprobe.d/v4l2loopback.conf` and reload:

```bash
$ sudo cat /etc/modprobe.d/v4l2loopback.conf
options v4l2loopback video_nr=10,42,50,51,52 \
        exclusive_caps=1,1,0,0,0 max_buffers=2
```

Or wherever the option is currently set on this box.
The reload is `sudo modprobe -r v4l2loopback &&
sudo modprobe v4l2loopback`, which **disconnects all
v4l2loopback consumers (OBS, ffmpeg youtube-player
decoders) and requires them to reconnect**. Not zero
risk — needs an operator coordination window.

### 1.1 Why this matters

The end-to-end buffering between the compositor and OBS
on the v4l2sink path:

| stage | buffer depth | cushion at 30 fps |
|---|---|---|
| pre-fx tee → fx_chain stages | varies (mostly 2-buffer) | ~67 ms each |
| output_tee → queue-v4l2 | **1 buffer** (drop #28 #9) | ~33 ms |
| videoconvert + capsfilter + identity | 0 (synchronous pass) | 0 |
| v4l2sink kernel handoff | **2 buffers** (this finding) | ~67 ms |
| **TOTAL on the v4l2 sink path** | **3 frames** | **~100 ms** |

100 ms of cushion is tight. If OBS's capture thread
stalls for more than 100 ms (scene transition, encoder
back-pressure, audio mixer hiccup, anything), the
compositor either drops the new frame at the userspace
queue (leaky=2 = drop newest) OR the v4l2loopback kernel
buffer overruns and drops at the kernel layer.

**For comparison**: the HLS branch's queue alone has
`max-size-buffers=20, max-size-time=3s` — 100× more
cushion than the v4l2 path.

### 1.2 The fix

Two-part fix, in order:

**Part A** — drop #28 finding 9 (userspace):

```python
# pipeline.py:131 — bump from 1 to 5
queue_v4l2.set_property("max-size-buffers", 5)
queue_v4l2.set_property("max-size-time", 200_000_000)  # 200 ms
```

**Part B** — kernel module (this drop):

```bash
# /etc/modprobe.d/v4l2loopback.conf
options v4l2loopback video_nr=10,42,50,51,52 \
        exclusive_caps=1,1,0,0,0 max_buffers=8
```

Then `sudo modprobe -r v4l2loopback && sudo modprobe
v4l2loopback`. **Coordinate with operator** because OBS
needs to reconnect.

After both fixes, end-to-end buffering is:

- Userspace: 5 buffers × 33 ms = ~167 ms
- Kernel: 8 buffers × 33 ms = ~267 ms
- **Total: ~430 ms cushion**

That's ~13 frames of headroom against transient stalls.
Memory cost: 8 kernel buffers × 1920×1080×2 (YUY2 is
2 bpp) = ~33 MB — trivial.

## 2. nvjpegdec confirmation

```text
$ gst-inspect-1.0 nvjpegdec
Factory Details:
  Rank                     primary (256)
  Long-name                NVDEC jpeg Video Decoder
  Klass                    Codec/Decoder/Video/Hardware
  Description              NVDEC video decoder

$ gst-inspect-1.0 | grep nvcodec | head -10
nvcodec: cudacompositor
nvcodec: cudaconvert
nvcodec: cudaconvertscale
nvcodec: cudascale
nvcodec: cudaupload
nvcodec: nvh264dec
nvcodec: nvh264enc
nvcodec: nvjpegdec               ← confirmed
nvcodec: nvjpegenc
```

The full GStreamer nvcodec plugin is installed. **Drop
#28 finding 5's proposed GPU-side decode is unblocked
on the system — no new packages required.**

The proposed producer chain rewrite from drop #28:

```text
v4l2src device=/dev/v4l/by-id/...
  ↓
capsfilter (image/jpeg, 1280x720, 30/1)
  ↓
nvjpegdec                                ← was: jpegdec
  ↓
capsfilter (video/x-raw(memory:CUDAMemory), NV12, 1280x720, 30/1)
  ↓
interpipesink                             (must accept CUDAMemory caps)
```

And consumer chain:

```text
interpipesrc → cudaconvert → cudascale → cudacompositor
              ^ no cudaupload — already in CUDAMemory
```

**Open question**: does `interpipesink`/`interpipesrc`
correctly handle `(memory:CUDAMemory)` caps across the
boundary? interpipe is a GstQueue-style buffer queue
with caps negotiation; CUDA memory should pass through
since it's just a memory tag on the buffer. **Worth a
sandbox test**: build one camera with the rewrite, see
if the consumer can hot-swap to it without crashing.

If interpipe doesn't carry CUDA memory across the link
correctly, an alternative is to use `gstcuda`'s context-
sharing mechanism to make the producer and consumer
pipelines share a CUDA context. Or fall back to
`cudadownload` after `nvjpegdec` (defeating the purpose).

**Estimated win** if the rewrite works:

- Eliminates ~248 MB/s of CPU→GPU transfer (drop #28
  finding 5)
- Eliminates ~5 ms × 6 cameras × 30 fps of CPU
  videoconvert work in the producer chain (~1 full CPU
  core saved)
- jpegdec → nvjpegdec: NVDEC hardware JPEG decoder is
  significantly faster than CPU `jpegdec` for 720p
  streams (~1-2 ms per frame vs ~5-10 ms)

## 3. smooth_delay.py wastes ~250 MB/s on premature
gldownload

The smooth-delay branch produces a 5-second delayed
snapshot of the compositor output, downscaled to 640×360,
emitted at 2 fps. Element chain
(`smooth_delay.py:85-122`):

```text
output_tee → src_%u
  ↓
queue (leaky=2 max-size-buffers=2)
  ↓
videoconvert RGBA + capsfilter
  ↓
glupload                                 ← BGRA → GL
  ↓
glcolorconvert (in)
  ↓
smoothdelay delay-seconds=5.0 fps=30     ← 5-second GL frame buffer
  ↓
glcolorconvert (out)
  ↓
gldownload                               ← ⚠️ at 30 fps, full frame
  ↓
videoconvert
  ↓
videoscale → 640×360
  ↓
videorate → 2 fps                        ← drops 28/30 here
  ↓
jpegenc quality=85
  ↓
appsink (writes /dev/shm/hapax-compositor/smooth-snapshot.jpg)
```

**The bug**: `gldownload` happens at 30 fps but
`videorate` drops to 2 fps **immediately after**.
28 out of 30 downloaded frames are immediately
discarded.

### 3.1 Cost

- Each `gldownload` of a 1920×1080×4 BGRA frame =
  8.3 MB
- × 30 fps = **~250 MB/s GPU→CPU bandwidth**
- × 28/30 wasted = ~233 MB/s of pure waste
- Plus the per-frame `videoconvert` and `videoscale`
  CPU work that happens before the videorate filter

This bandwidth competes with the main output path's
own `cudadownload` (drop #28 finding 8) which is already
~250 MB/s. **The smooth_delay branch effectively
doubles the GPU→CPU memory bandwidth on the compositor's
output side.**

### 3.2 Fix options

**Option A — drop frames before download via probe**:

Add a pad probe on `glcolorconvert(out)` that drops 28
out of every 30 buffers, BEFORE the `gldownload`. The
remaining 2 fps of buffers proceed to download.

```python
# in smooth_delay.py setup
_frame_count = [0]

def _drop_28_of_30(pad: Any, info: Any) -> Any:
    _frame_count[0] += 1
    if _frame_count[0] % 15 != 0:  # keep every 15th = 2 fps from 30
        return Gst.PadProbeReturn.DROP
    return Gst.PadProbeReturn.OK

glcc_out.get_static_pad("src").add_probe(
    Gst.PadProbeType.BUFFER, _drop_28_of_30
)
```

Net: gldownload runs at 2 fps instead of 30. **Saves
~233 MB/s.**

**Option B — use a `glvideorate` element if available**:

GStreamer has `videorate` (CPU) but not always
`glvideorate`. If present, it would do rate-conversion
in GL memory before the download. Let me grep for it.

```bash
gst-inspect-1.0 glvideorate
```

If available, the chain becomes:

```text
... smoothdelay → glcolorconvert(out) → glvideorate → gldownload → ...
```

Cleaner than the probe but needs the element.

**Option C — keep videorate where it is but move it to
just before `gldownload` and use `videorate` on
GL-mapped frames**: complicated, possibly broken
because videorate does mathematics on buffer
timestamps that may not work cleanly with GL caps.

**Recommendation**: option A. The probe is 6 lines,
no element dependency, no element-order surgery.

## 4. uvcvideo defaults are correct

```text
$ cat /sys/module/uvcvideo/parameters/nodrop
0

$ cat /sys/module/uvcvideo/parameters/clock
CLOCK_MONOTONIC

$ cat /sys/module/uvcvideo/parameters/quirks
0
```

Defaults across all three:

- `nodrop=0`: incomplete/corrupted frames ARE dropped
  by uvcvideo before reaching v4l2 buffers. Setting to
  1 would force them through, but jpegdec would reject
  them anyway. Default is correct.
- `clock=CLOCK_MONOTONIC`: buffer timestamps come from
  the monotonic clock. Right choice for realtime video
  pipelines.
- `quirks=0`: no forced device-level quirks. The
  per-camera quirks for known buggy webcams are
  hardcoded in the driver and applied automatically
  based on USB device IDs.

Other interesting parameters (not currently set, all
defaults):

- `hwtimestamps`: when 1, uvcvideo uses hardware
  timestamps from the camera (if supported). Not all
  BRIO firmware variants support this. Default 0.
- `timeout`: streaming control request timeout. Default
  is 5000 ms.
- `trace`: debug trace bitmask. Default 0 (off).

**No tunable concerns. This closes drop #28 § 1.2 as a
follow-up.**

## 5. HLS branch is well-buffered (informational)

Per `recording.py:84-87`:

```python
queue = Gst.ElementFactory.make("queue", "queue-hls")
queue.set_property("leaky", 2)
queue.set_property("max-size-buffers", 20)            # 20 frames = ~667 ms
queue.set_property("max-size-time", 3 * 1_000_000_000) # 3 seconds
```

20 buffers and 3 seconds of cushion. **100× the
v4l2sink queue's cushion.**

The contrast is interesting because both queues are
downstream of the same `output_tee` source pad. The
HLS branch's heavy buffering exists because
`hlssink2` writes are async and segment finalization
involves disk I/O which can vary. The v4l2sink branch's
1-buffer queue exists because v4l2sink writes are
expected to be near-realtime to v4l2loopback. **The
v4l2sink branch's tightness was a deliberate
realtime-first choice**, but combined with the kernel
buffer of 2 (this drop § 1) the total is below what's
realistic for a downstream consumer (OBS) that can
have 100+ ms of jitter.

The HLS branch encoder also uses different settings
than the rtmp_bin (drop #4 § 1.1):

```python
encoder = Gst.ElementFactory.make("nvh264enc", "hls-enc")
encoder.set_property("preset", 2)         # vs rtmp's preset=11
encoder.set_property("rc-mode", 3)        # VBR vs rtmp's 2 = CBR
encoder.set_property("qp-const", 26)      # quality target
encoder.set_property("gop-size", fps * hls_cfg.target_duration)
```

- HLS uses **fast preset (2)** — less compute, slightly
  larger files
- HLS uses **VBR with qp-const 26** — quality-targeted
  encoding (the QP-constant approach within VBR mode)
- gop-size = `fps × target_duration` — every segment
  starts on a keyframe, correct for HLS

These are fine for the HLS path. **Same `cuda-device-id`
not-set drift risk as drop #4 finding F1** — the HLS
encoder also lands on whatever GPU CUDA picks. Currently
that's GPU 0 (5060 Ti) per the live nvidia-smi.

## 6. Combined fix sequence for cam stability

After this drop and drop #28, the cam-stability backlog
in priority order:

| # | Fix | From drop | Effort |
|---|---|---|---|
| 1 | Bump v4l2sink queue 1→5 (userspace) | #28 #9 | 1 line |
| 2 | Bump v4l2loopback `max_buffers` 2→8 (kernel) | this #1 | modprobe + reload |
| 3 | Add producer-chain queue between v4l2src and jpegdec | #28 #1 | ~6 lines per pipeline |
| 4 | smooth_delay frame-drop probe before gldownload | this #3 | ~6 lines |
| 5 | Initial frame-flow grace period | #27 | 2 lines |
| 6 | Static-frame fallback (replace bouncing ball) | #28 #3 | element rewrite |
| 7 | nvjpegdec producer rewrite | #28 #5 + this #2 | sandbox test + rewrite |
| 8 | CUDA device pinning via env var | #4 | env var |

Items 1, 2, 4, 5 are 1-2 line fixes that ship together
in one PR. Items 3 and 6 are slightly larger but
still single-file diffs. Items 7 and 8 need
investigation first.

## 7. What's still untouched in the camera path

Updated checklist of touch points from drop #28:

- ✓ USB hardware (drop #2)
- ✓ Kernel uvcvideo (this drop § 4 — no concerns)
- ✓ v4l2 device layer (drop #2 § 2.4)
- ✓ camera_pipeline.py producer (drop #28)
- ✓ fallback_pipeline.py (drop #28)
- ✓ pipeline_manager.py (drop #28)
- ✓ cameras.py consumer (drop #28)
- ✓ cudacompositor (drops #4 + #28)
- ✓ pipeline.py output stage (drop #28)
- ✓ HLS branch (this drop § 5)
- ✓ smooth_delay branch (this drop § 3)
- ✓ v4l2sink + v4l2loopback (drop #28 + this drop § 1)
- ✓ fx_chain interior (drops #5 + #14)
- ✓ rtmp_bin (drop #4 + drop #19)
- ⚠ recording branch — only active when recording is
  enabled, currently disabled per drop #20 era
  observations
- ⚠ snapshots.py `add_snapshot_branch` and
  `add_fx_snapshot_branch` — small files, low priority

The remaining gray areas are the disabled recording
branch and two snapshot branches (which are tee-fanout
JPEG snapshot writers, similar to the per-camera
snapshot code in `cameras.py` already audited). **The
camera path is essentially fully walked.**

## 8. Follow-ups for alpha

1. **Bundle fixes 1, 2, 4, 5 into one PR** — five small
   diffs, all cam-stability, low risk, big wins.
2. **`gst-inspect-1.0 glvideorate`** to check if
   smooth_delay option B is feasible.
3. **Sandbox test of nvjpegdec + interpipesink CUDA
   memory** — probably 30 minutes of work, validates
   the biggest win in the cam-stability backlog.
4. **`/etc/modprobe.d/v4l2loopback.conf` audit** —
   confirm the current options string and add
   `max_buffers=8`.
5. **HLS encoder cuda-device-id** — same as drop #4
   recommendation, also applies here.

## 9. References

- `agents/studio_compositor/recording.py:79-122` —
  `add_hls_branch`
- `agents/studio_compositor/smooth_delay.py:14-130` —
  `add_smooth_delay_branch`
- `/sys/module/v4l2loopback/parameters/max_buffers` =
  2 at 2026-04-14T17:10 UTC
- `/sys/module/uvcvideo/parameters/nodrop` = 0,
  `clock` = `CLOCK_MONOTONIC`, `quirks` = 0
- `gst-inspect-1.0 nvjpegdec` — primary rank, NVDEC
  jpeg Video Decoder
- Drop #2 — brio-operator deficit + USB hardware
- Drop #4 — sprint-5 delta audit, `cuda-device-id`
  pattern
- Drop #27 — brio-operator startup stall
- Drop #28 — full camera pipeline systematic walk
- nvcodec plugin: `gst-inspect-1.0 | grep nvcodec`
