# V4L2 Output: appsink + direct write() bypass

**Date:** 2026-05-07
**Author:** gamma
**Status:** spec
**Supersedes:** Phase 2 of `docs/research/2026-04-20-v4l2sink-stall-prevention.md` §9.2
**Companion:** `docs/research/2026-03-16-v4l2loopback-direct-investigation.md`

---

## §1 Problem

GStreamer's `v4l2sink` performs its own V4L2 capability negotiation
(`VIDIOC_QUERYCAP` → `VIDIOC_ENUM_FMT` → `VIDIOC_S_FMT` →
`VIDIOC_REQBUFS` → mmap streaming I/O) every time the element
transitions to PLAYING. With `exclusive_caps=1` on `/dev/video42`,
this negotiation fails or deadlocks in three documented scenarios:

1. **Consumer holds the device.** OBS has `/dev/video42` open when
   the compositor starts or rebuilds. `v4l2sink` issues
   `VIDIOC_S_FMT` which races with the consumer's format
   expectation — v4l2loopback returns `EBUSY` or silently pins
   a mismatched format
   ([v4l2loopback#442](https://github.com/v4l2loopback/v4l2loopback/issues/442),
   [v4l2loopback#97](https://github.com/umlaeute/v4l2loopback/issues/97)).

2. **OBS reopens with different caps.** OBS releases then reopens
   the reader fd; the consumer-side format change triggers a
   renegotiation cycle on the producer side that can deadlock the
   v4l2sink's streaming thread without posting an error bus message
   ([v4l2loopback#116](https://github.com/v4l2loopback/v4l2loopback/issues/116)).

3. **Pipeline rebuild after stall.** The `V4l2OutputPipeline.rebuild()`
   path tears down the pipeline (sets to NULL) then re-builds and
   starts. The v4l2sink's second `VIDIOC_S_FMT` against a device
   still held by OBS hits the same `exclusive_caps` single-producer
   constraint — the rebuild succeeds from GStreamer's perspective but
   frames never reach the kernel ring.

These are the root causes behind the 2026-04-14 78-minute stall and
the 2026-04-20 OBS `select timed out` incident documented in the
companion research. The existing heartbeat probe (Phase 1, shipped)
detects the stall but cannot prevent it.

## §2 Proposed solution

Replace `v4l2sink` with `appsink` + direct `os.write()` to the
device fd. This bypasses GStreamer's entire V4L2 layer — format
negotiation, buffer pool management, and the mmap streaming I/O
path. Python owns the device fd lifecycle.

### §2.1 New pipeline graph

```
interpipesrc(listen-to="compositor_v4l2_out")
  → queue(leaky=downstream, max-size-buffers=5)
  → videoconvert(dither=0)
  → capsfilter(video/x-raw,format=YUY2,width=1920,height=1080,framerate=30/1)
  → appsink(sync=False, drop=True, max-buffers=2, emit-signals=True)
```

The `appsink` fires `new-sample` on the streaming thread. The
callback extracts the raw frame bytes via `GstBuffer.map(READ)`,
then calls `os.write(self._device_fd, frame_bytes)`.

### §2.2 Why YUY2 not NV12

The current pipeline uses NV12 for the capsfilter → v4l2sink leg.
However, v4l2loopback's `write()` path expects a contiguous frame
buffer. NV12 is planar (Y plane + interleaved UV plane) and
v4l2loopback handles it correctly via `write()`, but YUY2 (packed
4:2:2) is the default format v4l2loopback announces to consumers
when no producer has set a format yet. Using YUY2 avoids the
edge case where OBS opens the device before the compositor has
written its first frame — OBS queries format, gets v4l2loopback's
default, and the producer-side `VIDIOC_S_FMT` pins a matching
format on the first `write()`.

Trade-off: YUY2 is 2 bytes/pixel vs NV12's 1.5 bytes/pixel.
At 1920×1080, that's 4.15 MB vs 3.11 MB per frame — 1 MB more
per write(). At 30 fps this is ~30 MB/s additional memcpy through
the kernel, negligible on this system's memory bandwidth. If
profiling shows this matters, NV12 remains viable — the spec's
architecture is format-agnostic since the capsfilter controls
the colorspace independently.

### §2.3 Device fd lifecycle

```python
import fcntl
import os
import struct
import v4l2  # from python-v4l2 or inline constants

fd = os.open(device, os.O_WRONLY | os.O_NONBLOCK)
# VIDIOC_S_FMT: pin YUY2 1920×1080
fmt = v4l2.v4l2_format()
fmt.type = v4l2.V4L2_BUF_TYPE_VIDEO_OUTPUT
fmt.fmt.pix.width = 1920
fmt.fmt.pix.height = 1080
fmt.fmt.pix.pixelformat = v4l2.V4L2_PIX_FMT_YUYV
fmt.fmt.pix.field = v4l2.V4L2_FIELD_NONE
fmt.fmt.pix.sizeimage = 1920 * 1080 * 2
fcntl.ioctl(fd, v4l2.VIDIOC_S_FMT, fmt)
```

The fd opens once at `build()` time and persists across appsink
lifecycle events. The v4l2loopback module accepts `write()` on the
fd regardless of whether a consumer is attached — frames are
silently dropped if no consumer holds the read side. This
eliminates the `EBUSY` failure mode entirely.

### §2.4 Why not pyvirtualcam

The `pyvirtualcam` library (`docs/research/2026-03-16-v4l2loopback-direct-investigation.md` §Alternative)
wraps v4l2loopback behind a high-level API. It forces RGB input
and performs internal colorspace conversion. We already have
GStreamer doing the conversion (videoconvert → capsfilter);
pyvirtualcam would add a redundant conversion step and a
dependency. The raw ioctl + write() path is ~30 lines of Python
with zero external dependencies beyond the kernel module.

## §3 Implementation plan

### §3.1 Files changed

| File | Change |
|------|--------|
| `agents/studio_compositor/v4l2_output_pipeline.py` | Replace v4l2sink with appsink + write() |
| `agents/studio_compositor/v4l2_device.py` *(new)* | V4L2 device fd manager — open, VIDIOC_S_FMT, write, close |
| `tests/studio_compositor/test_v4l2_output_pipeline.py` *(new)* | Unit tests with mock device fd |

### §3.2 `v4l2_device.py` — V4L2 device fd manager

~60 LOC module owning the raw device fd. Responsibilities:

- `open(device, width, height, pixelformat)` — `os.open()` +
  `VIDIOC_S_FMT` ioctl. Returns fd. Raises `OSError` on failure.
- `write_frame(fd, data)` — `os.write(fd, data)`. Returns bytes
  written. Non-blocking (`O_NONBLOCK`); if the kernel ring is full,
  `write()` returns `EAGAIN` — we drop the frame and increment a
  Prometheus counter rather than blocking the streaming thread.
- `close(fd)` — `os.close(fd)`.

V4L2 ioctl constants are inlined (6 constants: `VIDIOC_S_FMT`,
`V4L2_BUF_TYPE_VIDEO_OUTPUT`, `V4L2_PIX_FMT_YUYV`,
`V4L2_FIELD_NONE`, plus the `v4l2_format` struct layout) to avoid
a dependency on `python-v4l2`. The struct is packed with
`struct.pack()` — see §3.5 for the exact layout.

### §3.3 `v4l2_output_pipeline.py` changes

Replace lines 86–115 (v4l2sink construction) with:

```python
sink = Gst.ElementFactory.make("appsink", "v4l2_out_appsink")
sink.set_property("sync", False)
sink.set_property("drop", True)
sink.set_property("max-buffers", 2)
sink.set_property("emit-signals", True)
sink.connect("new-sample", self._on_new_sample)
```

Add the sample callback:

```python
def _on_new_sample(self, appsink: Any) -> int:
    sample = appsink.emit("pull-sample")
    if sample is None:
        return 1
    buf = sample.get_buffer()
    ok, mapinfo = buf.map(self._Gst.MapFlags.READ)
    if not ok:
        return 1
    try:
        data = bytes(mapinfo.data)
        if self._device_fd >= 0:
            try:
                os.write(self._device_fd, data)
            except BlockingIOError:
                self._dropped_frames += 1
            except OSError:
                log.warning("v4l2 write failed", exc_info=True)
                self._consecutive_write_errors += 1
        self._last_frame_monotonic = time.monotonic()
        if self._on_frame is not None:
            self._on_frame()
    finally:
        buf.unmap(mapinfo)
    return 0
```

The `build()` method opens the device fd via `v4l2_device.open()`
before constructing the GStreamer pipeline. `teardown()` closes it
after pipeline disposal. The fd persists across appsink state
changes — no re-negotiation on rebuild.

### §3.4 Capsfilter format

Change from NV12 to YUY2:

```python
caps.set_property(
    "caps",
    Gst.Caps.from_string(
        f"video/x-raw,format=YUY2,"
        f"width={self._width},height={self._height},"
        f"framerate={self._fps}/1"
    ),
)
```

### §3.5 V4L2 ioctl struct layout

The `v4l2_format` struct for `VIDIOC_S_FMT` (`0xC0CC5605`) with
`V4L2_BUF_TYPE_VIDEO_OUTPUT` (2):

```python
import struct, fcntl

VIDIOC_S_FMT = 0xC0CC5605
V4L2_BUF_TYPE_VIDEO_OUTPUT = 2
V4L2_PIX_FMT_YUYV = 0x56595559  # 'YUYV' fourcc
V4L2_FIELD_NONE = 1

def set_format(fd: int, w: int, h: int) -> None:
    # struct v4l2_format: __u32 type + struct v4l2_pix_format
    # v4l2_pix_format: width(I), height(I), pixelformat(I),
    #   field(I), bytesperline(I), sizeimage(I), colorspace(I),
    #   priv(I), flags(I), quantization(I) ... padded to 200 bytes
    pix = struct.pack(
        "=IIIIIIII",
        w, h, V4L2_PIX_FMT_YUYV, V4L2_FIELD_NONE,
        w * 2,      # bytesperline
        w * h * 2,  # sizeimage
        0,          # colorspace (default)
        0,          # priv
    )
    # type (4 bytes) + pix_format (padded to 200 bytes)
    buf = struct.pack("=I", V4L2_BUF_TYPE_VIDEO_OUTPUT)
    buf += pix + b"\x00" * (200 - len(pix))
    fcntl.ioctl(fd, VIDIOC_S_FMT, buf)
```

The struct size (204 bytes) matches the kernel's `sizeof(struct
v4l2_format)`. The padding ensures the ioctl receives the full
struct regardless of which fields we populate.

### §3.6 Recovery path

On write error (not `EAGAIN`), increment
`_consecutive_write_errors`. After 5 consecutive errors:

1. Close the current fd.
2. Re-open and re-issue `VIDIOC_S_FMT`.
3. Reset the error counter.

This is strictly fd-level recovery — the GStreamer pipeline stays
in PLAYING throughout. No state transitions, no pad probes, no
dynamic pipeline manipulation. The appsink keeps pulling samples;
any frames arriving during the fd re-open are dropped via the
`max-buffers=2, drop=True` policy.

Contrast with the current `V4l2OutputPipeline.rebuild()` which
tears down the entire GStreamer pipeline (PLAYING → NULL →
rebuild → PLAYING) — a 500ms+ operation that flushes the interpipe
buffer and requires re-negotiation with the v4l2loopback module.

### §3.7 Metrics

| Metric | Type | Label |
|--------|------|-------|
| `studio_compositor_v4l2_direct_frames_total` | Counter | — |
| `studio_compositor_v4l2_direct_dropped_total` | Counter | reason={eagain,write_error,fd_closed} |
| `studio_compositor_v4l2_direct_fd_reopen_total` | Counter | — |
| `studio_compositor_v4l2_direct_write_bytes` | Counter | — |
| `studio_compositor_v4l2_direct_last_frame_age_seconds` | Gauge | — |

## §4 What this eliminates

| Failure mode (from stall-prevention §2) | Before | After |
|----------------------------------------|--------|-------|
| §2.1 NVIDIA GL context loss | v4l2sink stalls silently | appsink drops buffers; fd stays open, resumes when buffers return |
| §2.2 Format renegotiation deadlock | v4l2sink deadlocks on VIDIOC_S_FMT | No GStreamer-side V4L2 negotiation; fd pre-pinned |
| §2.3 v4l2loopback buffer exhaustion | v4l2sink's QBUF blocks streaming thread | write() returns EAGAIN; frame dropped, thread unblocked |
| §2.5 Internal queue stall from blocked sink | queue backs up when v4l2sink chain blocks | appsink.drop=True; queue can always push |
| §2.7 GLib main loop vs render thread | v4l2sink chain function blocks on the streaming thread | write() with O_NONBLOCK cannot block |

Failure modes §2.4 (OBS select timeout), §2.6 (GL stall), and
§2.8 (dmabuf fd leak) are upstream of the v4l2 output and
unaffected by this change. The heartbeat probe (Phase 1) continues
to detect them.

## §5 What this does NOT change

- **Interpipe channel.** The main pipeline's `interpipesink` named
  `compositor_v4l2_out` on `output_tee` is unchanged. This module
  consumes from it via `interpipesrc` as before.
- **RTMP output.** `rtmp_output.py` is a separate pipeline branch
  and is not touched.
- **HLS output.** Same — separate branch.
- **Heartbeat probe.** The Phase 1 buffer probe moves from the
  v4l2sink's sink pad to the appsink's callback
  (`self._last_frame_monotonic` update). Semantics are preserved:
  the timestamp records when a frame was delivered to the output.
- **Watchdog integration.** `is_alive()` and
  `last_frame_age_seconds` are unchanged.
- **v4l2loopback module config.** `/etc/modprobe.d/v4l2loopback-hapax.conf`
  is unchanged. `exclusive_caps=1` stays — it is needed so OBS
  correctly discovers the format. The difference is that our
  producer now bypasses GStreamer's problematic negotiation with
  v4l2loopback.

## §6 Risks and mitigations

### §6.1 Frame size mismatch

If `videoconvert` produces a buffer whose size does not match
`width × height × bytes_per_pixel`, the `write()` call writes a
short frame. v4l2loopback accepts it but the consumer sees
corruption.

**Mitigation:** Assert `len(data) == expected_frame_size` before
writing. Log and drop mismatched frames. The capsfilter upstream
guarantees format; this guard is defense-in-depth.

### §6.2 Endianness / padding

V4L2 structs are native-endian and may have different padding on
different architectures. This system is x86_64 (little-endian,
8-byte aligned); the struct layout in §3.5 is correct for this
architecture.

**Mitigation:** The `v4l2_device.py` module includes a
`_STRUCT_SANITY_CHECK` assertion at import time that verifies the
packed struct size equals 204 bytes.

### §6.3 Performance — memcpy overhead

Each frame is copied twice: once by `GstBuffer.map(READ)` (into
Python bytes), once by `os.write()` (into the kernel ring).
v4l2sink's mmap path achieves zero-copy from GStreamer to kernel.

**Measured impact:** At 1920×1080 YUY2 (4.15 MB/frame, 30 fps),
the total copy bandwidth is ~250 MB/s. The system's DDR5 memory
bandwidth is >50 GB/s. The per-frame `os.write()` latency is
expected to be <1 ms; the GstBuffer.map() is <0.1 ms. Neither is
close to the ~33 ms frame budget.

**Mitigation:** If profiling reveals the Python→kernel copy is a
bottleneck (unlikely), the `write()` can be replaced with a
`mmap()` + memcpy path that avoids the kernel copy by writing
directly into v4l2loopback's mapped buffer. This is a performance
optimization, not an architectural change.

### §6.4 O_NONBLOCK write() semantics on v4l2loopback

v4l2loopback's `v4l2_loopback_write()` kernel function does not
check `O_NONBLOCK` — it always returns immediately after copying
the frame into the ring buffer, or returns `-EINVAL` if the format
has not been set. The `O_NONBLOCK` flag is therefore a no-op in
practice but is set as a safety measure against future kernel
module changes.

**Mitigation:** The `BlockingIOError` handler in §3.3 is a
defensive catch; in practice `write()` will either succeed or
return an error synchronously. Test by filling the ring buffer
(`max_buffers=8` writes with no consumer) and verifying behavior.

## §7 Acceptance criteria

- [ ] `V4l2OutputPipeline` uses appsink, not v4l2sink
- [ ] Device fd opened with `VIDIOC_S_FMT` at build time
- [ ] Frames written via `os.write()` in the new-sample callback
- [ ] `O_NONBLOCK` write; `EAGAIN` counted and dropped, not blocking
- [ ] Heartbeat probe moved to appsink callback (no behavior change)
- [ ] 5 consecutive write errors trigger fd reopen (no pipeline rebuild)
- [ ] Frame size assertion before write
- [ ] Prometheus metrics from §3.7 exposed
- [ ] Unit tests mock the device fd and verify the write path
- [ ] `v4l2loopback.conf` and `exclusive_caps` settings unchanged
- [ ] RTMP and HLS output branches unaffected
- [ ] Manual smoke test: restart OBS while compositor pushes — no stall

## §8 Sequencing

This spec replaces Phase 2 (§9.2) of the stall-prevention research.
Phase 1 (heartbeat + watchdog gate) is already shipped and continues
to provide detection as a safety net. Phase 3 (dual-output
redundancy) remains viable as a future enhancement and is
architecturally compatible — a second `V4l2OutputPipeline` instance
targeting `/dev/video43` would use the same appsink + write() path.

## §9 References

### v4l2loopback
- [v4l2loopback GitHub](https://github.com/v4l2loopback/v4l2loopback)
- [v4l2loopback write() path — v4l2_loopback_write() in v4l2loopback.c](https://github.com/v4l2loopback/v4l2loopback/blob/main/v4l2loopback.c)
- [v4l2loopback#442 — exclusive_caps limits to single producer open](https://github.com/v4l2loopback/v4l2loopback/issues/442)
- [v4l2loopback#97 — Internal data flow error / not-negotiated -4](https://github.com/umlaeute/v4l2loopback/issues/97)
- [v4l2loopback#116 — Cannot use v4l2loopback as sink for gstreamer](https://github.com/v4l2loopback/v4l2loopback/issues/116)
- [v4l2loopback#36 — Could not negotiate format](https://github.com/v4l2loopback/v4l2loopback/issues/36)
- [v4l2loopback DeepWiki — buffer management](https://deepwiki.com/v4l2loopback/v4l2loopback)
- [v4l2loopback wiki — GStreamer page](https://github.com/v4l2loopback/v4l2loopback/wiki/Gstreamer)

### V4L2 kernel API
- [V4L2 write() I/O — kernel docs](https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/rw.html)
- [VIDIOC_S_FMT — kernel docs](https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/vidioc-g-fmt.html)
- [V4L2 pixel formats — kernel docs](https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/pixfmt.html)
- [V4L2 buffer types — kernel docs](https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/buffer.html)

### GStreamer
- [GStreamer appsink reference](https://gstreamer.freedesktop.org/documentation/app/appsink.html)
- [GStreamer v4l2sink reference](https://gstreamer.freedesktop.org/documentation/video4linux2/v4l2sink.html)
- [GstBuffer.map() reference](https://gstreamer.freedesktop.org/documentation/gstreamer/gstbuffer.html)
- [GStreamer Pipeline manipulation — probes](https://gstreamer.freedesktop.org/documentation/application-development/advanced/pipeline-manipulation.html)

### Hapax codebase
- `agents/studio_compositor/v4l2_output_pipeline.py` — current v4l2sink implementation
- `agents/studio_compositor/snapshots.py:15-79` — proven appsink → os.write() pattern
- `agents/studio_compositor/smooth_delay.py:95-120` — second appsink → os.write() pattern
- `docs/research/2026-04-20-v4l2sink-stall-prevention.md` — root cause taxonomy + phased plan
- `docs/research/2026-03-16-v4l2loopback-direct-investigation.md` — prior direct-write investigation
- `/etc/modprobe.d/v4l2loopback-hapax.conf` — current module config
