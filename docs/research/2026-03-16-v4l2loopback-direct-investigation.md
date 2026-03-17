# v4l2loopback Direct Write Investigation

**Date:** 2026-03-16
**Context:** Studio compositor outputs to `/dev/video50` via GStreamer's `v4l2sink`. Investigated whether bypassing GStreamer for the v4l2loopback output could reduce latency or complexity.

## Current Architecture

```
GStreamer pipeline → v4l2sink device=/dev/video50 → v4l2loopback kernel module → consumers (OBS, browser, etc.)
```

The v4l2loopback module is loaded with:
```bash
modprobe v4l2loopback devices=1 video_nr=50 card_label="Hapax Studio" exclusive_caps=1 max_buffers=2
```

GStreamer's `v4l2sink` uses the mmap (VIDIOC_QBUF/VIDIOC_DQBUF) streaming I/O interface internally.

## Direct Write Approaches

### Option A: write() syscall (simplest)

v4l2loopback supports direct `write()` to the device node:

```python
import struct
fd = open("/dev/video50", "wb")
# Set format via ioctl first, then:
fd.write(raw_frame_bytes)
```

FFmpeg uses this approach. It's simpler than mmap but:
- Requires format negotiation via V4L2 ioctls (VIDIOC_S_FMT)
- Each write() copies the entire frame through the kernel
- No zero-copy possible

### Option B: mmap streaming I/O (what GStreamer does)

The V4L2 streaming API:
1. VIDIOC_REQBUFS — allocate kernel buffers
2. mmap() — map buffers to userspace
3. VIDIOC_QBUF — queue a filled buffer
4. VIDIOC_DQBUF — dequeue a consumed buffer

**Known issue with v4l2loopback:** The mmap write path has historical bugs. The `sequence` field isn't set in `vidioc_qbuf()` (only in `v4l2_loopback_write()`), and `ready_for_capture` flag management can cause consumers to fail format negotiation if the producer hasn't started streaming yet.

### Option C: DMA-BUF export (theoretical zero-copy)

V4L2 supports DMA-BUF (VIDIOC_EXPBUF) for zero-copy buffer sharing between devices. In theory:
1. GStreamer GL context renders to a DMA-BUF
2. DMA-BUF fd is passed to v4l2loopback
3. Consumer reads directly from GPU memory

**Status:** v4l2loopback does not support DMA-BUF import as of the current version. The kernel module only implements mmap and write() buffer types. This would require kernel module patches.

## Feasibility Assessment

### Why bypass GStreamer?

Potential reasons:
- Lower latency (skip GStreamer's buffer management overhead)
- Simpler crash recovery (no pipeline rebuild needed)
- Direct control over buffer timing

### Why NOT bypass GStreamer?

- **v4l2sink already works well.** GStreamer handles format negotiation, buffer management, and error recovery automatically.
- **Minimal latency benefit.** GStreamer's v4l2sink adds ~1-2ms overhead at most. The pipeline's latency is dominated by camera capture (~33ms at 30fps) and GL shader processing (~5ms).
- **Format handling complexity.** Without GStreamer, we'd need to manually handle colorspace conversion (GL outputs RGBA, v4l2loopback consumers typically expect YUY2 or NV12). GStreamer's `videoconvert` does this automatically.
- **Error recovery.** GStreamer handles device disconnection, format renegotiation, and pipeline state management. A raw V4L2 writer would need all of this reimplemented.
- **The mmap path in v4l2loopback has bugs** that GStreamer's v4l2sink works around internally.

### Verdict: Keep GStreamer's v4l2sink

The current approach is correct. GStreamer's v4l2sink:
- Handles format negotiation with consumers
- Manages buffer lifecycle
- Provides error recovery
- Adds negligible overhead (~1ms)

Direct write would add complexity with no measurable benefit. The only scenario where bypassing GStreamer makes sense is if we need to write frames from a non-GStreamer source (e.g., a pure OpenCV or PyTorch pipeline). Even then, using `v4l2sink` in a minimal GStreamer pipeline or using the `pyvirtualcam` library would be simpler than raw V4L2 ioctls.

## Alternative Considered: pyvirtualcam

The `pyvirtualcam` Python library wraps v4l2loopback with a clean API:

```python
import pyvirtualcam
with pyvirtualcam.Camera(width=1920, height=1080, fps=30, device="/dev/video50") as cam:
    cam.send(frame)  # numpy array, RGB
```

This could be useful for a standalone Python-only compositor (no GStreamer), but that's not our architecture. Filed for reference.

## References

- [v4l2loopback GitHub](https://github.com/v4l2loopback/v4l2loopback)
- [v4l2loopback ArchWiki](https://wiki.archlinux.org/title/V4l2loopback)
- [Virtual webcam with GStreamer and v4l2loopback](https://aweirdimagination.net/2020/07/12/virtual-web-cam-using-gstreamer-and-v4l2loopback/)
- [V4L2 mmap streaming I/O docs](https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/mmap.html)
- [v4l2loopback mmap write issues](https://github.com/umlaeute/v4l2loopback/issues/9)
- [VIDIOC_QBUF/DQBUF kernel docs](https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/vidioc-qbuf.html)
