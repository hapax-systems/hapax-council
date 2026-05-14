# ISAP: Camera Sharing Sidecar — Per-Camera v4l2loopback

**Date**: 2026-05-14
**Request**: REQ-20260509-camera-sharing-sidecar

## Problem

V4L2 devices are exclusive-access. Compositor grabs all 4 cameras.
Operator cannot use cameras for calls without killing livestream.

## Proposed Solution

Per-camera shmsink branch reusing existing bridge infrastructure (#2908).

```
camera_pipeline.py (per camera):
  v4l2src -> tee
    -> existing compositor branch
    -> new: shmsink(socket=/dev/shm/hapax-compositor/cam-{role}.sock)

sidecar (per camera):
  shmsrc -> v4l2sink(/dev/video7X)
```

## Effort: Medium (2-3 sessions)
## Dependencies: none (shmsink infra exists)
