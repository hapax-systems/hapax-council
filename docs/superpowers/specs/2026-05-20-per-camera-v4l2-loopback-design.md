# Per-Camera v4l2loopback Sidecar

CC-task: `camera-sidecar-per-camera-loopback`
Authority: `REQ-20260509-camera-sharing-sidecar`

## Problem

The compositor exclusively owns all USB cameras via v4l2src. Chrome/Meet cannot access individual cameras while the compositor is running. The operator needs to join video calls without stopping the livestream pipeline.

## Approach

Tee each camera's decoded NV12 stream inside `CameraPipeline` before the interpipesink. The second branch writes to a per-camera v4l2loopback device that Chrome sees via PipeWire camera portal.

```
v4l2src → decode → convert → capsfilter(NV12) → tee ─┬─ interpipesink (compositor)
                                                      └─ queue(leaky) → videoconvert → capsfilter(YUY2) → v4l2sink
```

## Device Allocation

Expand v4l2loopback from 8 to 14 devices. New devices `/dev/video70-75`:

| Device | Label | Camera |
|--------|-------|--------|
| /dev/video70 | Hapax BRIO Operator | brio-operator |
| /dev/video71 | Hapax BRIO Room | brio-room |
| /dev/video72 | Hapax BRIO Synths | brio-synths |
| /dev/video73 | Hapax C920 Desk | c920-desk |
| /dev/video74 | Hapax C920 Room | c920-room |
| /dev/video75 | Hapax C920 Overhead | c920-overhead |

All with `exclusive_caps=0` so Chrome can open/close freely. Pi HTTP JPEG cameras are excluded (not useful for Meet — no continuous v4l2 stream).

## Changes

### 1. `/etc/modprobe.d/v4l2loopback-hapax.conf`

Add 6 devices to the existing 8. Total: 14 devices.

### 2. `agents/studio_compositor/models.py` — CameraSpec

Add `loopback_device: str | None = None`. When set, `CameraPipeline` creates the tee+v4l2sink branch.

### 3. `agents/studio_compositor/camera_pipeline.py` — CameraPipeline._build_graph()

When `spec.loopback_device` is set:
- Replace direct `interpipesink` link with a `tee` element
- Branch 1: existing interpipesink path (unchanged)
- Branch 2: `queue(max-size-buffers=2, leaky=downstream)` → `videoconvert` → `capsfilter(video/x-raw,format=YUY2)` → `v4l2sink(device=loopback_device, sync=false)`
- v4l2sink errors logged as warnings, never propagated. The queue's `leaky=downstream` ensures the compositor path is never backpressured.

### 4. `~/.config/hapax-compositor/config.yaml`

Add `loopback_device` to each USB camera entry.

### 5. `systemd/units/hapax-camera-loopback-setup.service`

Oneshot unit that runs before `studio-compositor.service`. Ensures v4l2loopback module is loaded with correct parameters and all 14 devices exist.

### 6. Tests

- Unit test: `CameraPipeline` builds successfully with `loopback_device` set (mock GStreamer)
- Unit test: `CameraPipeline` builds successfully without `loopback_device` (regression)
- Integration: verify loopback device receives frames when compositor is running

## Caps Negotiation

Chrome via WebRTCPipeWireCapturer expects YUY2 or I420. The `videoconvert` in the loopback branch converts NV12→YUY2. The capsfilter pins the format so Chrome doesn't attempt renegotiation.

## Error Isolation

The `queue` element between `tee` and `v4l2sink` is the isolation boundary. If `v4l2sink` errors (device busy, removed), the queue fills and drops buffers. The interpipesink branch is unaffected. The `CameraPipeline` logs the v4l2sink error as a warning and continues.

## Recovery

On compositor restart, `CameraPipeline` rebuilds the full graph including the tee+v4l2sink branch. The v4l2loopback device persists across compositor restarts (kernel module, not process-scoped). PipeWire re-advertises the device automatically when frames resume.
