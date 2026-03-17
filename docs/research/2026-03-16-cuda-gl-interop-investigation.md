# CUDA-GL Interop Investigation

**Date:** 2026-03-16
**Context:** Studio compositor uses GStreamer with gleffects/glshader for GPU FX, plus CUDA for YOLOv8n person detection. Investigated whether CUDA-GL interop could eliminate CPU round-trips.

## Current Architecture

The compositor pipeline flows:
```
v4l2src → glupload → glcolorconvert → gleffects/glshader → gldownload → v4l2sink
                                                         → appsink (snapshot)
```

Person detection (new) reads JPEG snapshots from `/dev/shm` — a CPU-memory path:
```
appsink → jpegenc → file write → [person detector reads file] → YOLO inference on CUDA
```

This means frames travel: GPU (GL texture) → CPU (gldownload) → disk (/dev/shm JPEG) → CPU (imread) → GPU (CUDA tensor). Two unnecessary GPU↔CPU transfers per frame.

## CUDA-GL Interop: What It Enables

CUDA and OpenGL can share GPU memory directly via `cudaGraphicsGLRegisterImage` / `cudaGraphicsGLRegisterBuffer`. The workflow:

1. Register an OpenGL texture/buffer as a CUDA graphics resource
2. Map the resource (`cudaGraphicsMapResources`)
3. Get CUDA device pointer (`cudaGraphicsSubResourceGetMappedArray`)
4. Run CUDA kernel on the data
5. Unmap before GL rendering resumes

This eliminates all CPU-side copies. The texture stays on the GPU throughout.

## GStreamer's Support

GStreamer has partial infrastructure for this:

- **`GstGLMemory`** wraps OpenGL textures and is used by glupload/glshader/gleffects
- **`GstCudaMemory`** wraps CUDA device memory, used by nvcodec elements
- **`cudaupload` / `cudadownload`** elements transfer between system memory and CUDA memory
- As of GStreamer 1.24+, there is experimental GL-CUDA interop in `gst-plugins-bad` via `GstCudaGraphicsResource`

However, the interop path is primarily designed for **nvcodec decode → GL display**, not for **GL shader output → CUDA inference**. The reverse direction (GL texture → CUDA tensor) requires:

1. A custom GStreamer element or appsink callback that accesses the `GstGLMemory` directly
2. Registering the GL texture with CUDA in that callback
3. Copying to a CUDA tensor (or using mapped access)
4. Feeding into the YOLO model

## Feasibility Assessment

**Pros:**
- Eliminates ~4ms per frame of GPU↔CPU transfer overhead
- At 2fps detection rate, saves ~8ms/s (negligible)
- Would matter more at higher detection rates or with multiple models

**Cons:**
- Requires custom C/Cython GStreamer element or complex appsink GL context sharing
- GStreamer's GL context must be shared with the CUDA context — threading and context management is fragile
- ultralytics/PyTorch expects tensors in CUDA memory, not raw GL textures; still need a format conversion
- The person detector runs as a separate process for failure isolation; shared GPU memory across processes requires CUDA IPC or EGL export, adding significant complexity
- Current JPEG-based approach adds ~2-3ms latency per frame — acceptable at 2fps

**Verdict: Not worth it now.** The current `/dev/shm` JPEG approach is simple, debuggable, and fast enough. The person detector's 2fps rate means the overhead is ~5ms/frame, dominated by YOLO inference time (~15-30ms) anyway. Revisit if:
- Detection rate needs to increase to 10+ fps
- Multiple inference models share the same frames
- A GStreamer CUDA-GL bridge element matures in upstream

## Alternative: CUDA appsink (medium complexity)

A middle-ground approach that avoids the JPEG encode/decode but keeps process isolation:

```
gldownload → appsink (raw RGB) → shared memory (no JPEG) → person detector reads raw
```

This skips JPEG encode/decode (~1ms savings) but still crosses CPU memory. Could use a `multiprocessing.shared_memory` buffer instead of JPEG files. Worth considering if the JPEG path becomes a bottleneck.

## References

- [GStreamer GL/CUDA interop discussion](https://discourse.gstreamer.org/t/graphics-api-interoperability-and-zero-copy-memory/464)
- [CUDA-OpenGL interop overview](https://gist.github.com/MulattoKid/90462aaed943099719e6948f9488dff8)
- [GstCUDA framework (RidgeRun)](https://developer.ridgerun.com/wiki/index.php?title=GstCUDA)
- [GStreamer OpenGL upload and memory management](https://deepwiki.com/GStreamer/gstreamer/5.1-video-formats-and-conversion)
- [GstHip: cross-vendor HIP backend with GL interop](https://centricular.com/devlog/2025-07/amd-hip-integration/)
