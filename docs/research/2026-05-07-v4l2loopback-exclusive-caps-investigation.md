# v4l2loopback exclusive_caps Investigation

**Date:** 2026-05-07
**Author:** delta session
**Status:** research complete, recommendation ready
**Trigger:** GStreamer `v4l2sink` rejects `/dev/video42` during stall recovery because `exclusive_caps=1` makes the device report only `V4L2_CAP_VIDEO_CAPTURE` when no OUTPUT fd is held.
**Prior art:** `2026-04-20-v4l2sink-stall-prevention.md` §4 flagged `exclusive_caps=1` for review; `2026-03-16-v4l2loopback-direct-investigation.md` documents the v4l2loopback write path.

---

## §1 The Problem

### 1.1 Mechanism

`v4l2loopback.c` implements `VIDIOC_QUERYCAP` with conditional capability advertisement:

- **`exclusive_caps=1`:** Reports `V4L2_CAP_VIDEO_OUTPUT` if the opener holds an output stream token, `V4L2_CAP_VIDEO_CAPTURE` otherwise. Never both.
- **`exclusive_caps=0`:** Always reports `V4L2_CAP_VIDEO_CAPTURE | V4L2_CAP_VIDEO_OUTPUT`.

GStreamer's `v4l2sink` calls `VIDIOC_QUERYCAP` immediately on `open()`. If the device reports only `V4L2_CAP_VIDEO_CAPTURE`, `v4l2sink` refuses with `"Device is not a output device"`.

### 1.2 Chicken-and-egg

With `exclusive_caps=1` and no active producer fd, the device only advertises CAPTURE. The producer (`v4l2sink`) refuses to open because it sees no OUTPUT flag. The device won't advertise OUTPUT until a producer opens it. Deadlock. Documented in [umlaeute/v4l2loopback#370](https://github.com/umlaeute/v4l2loopback/issues/370).

### 1.3 Where this bites us

**Stall recovery.** `V4l2OutputPipeline.rebuild()` (`v4l2_output_pipeline.py:198`) calls `teardown()` → `build()` → `start()`. During teardown, the v4l2sink fd on `/dev/video42` closes, releasing the output stream token. In the window between teardown and the new `v4l2sink` element's `open()`, no OUTPUT fd is held. The new v4l2sink queries caps, sees only CAPTURE, and the `set_state(PLAYING)` transition fails.

The same pattern exists in `v4l2_stall_recovery.py:_cycle_sink_state()` which cycles `PLAYING → NULL → PLAYING` on the v4l2sink element directly. The `NULL` state closes the fd, releasing the token.

**Service restart.** When `studio-compositor.service` restarts, if OBS still holds `/dev/video42` open for capture, the first v4l2sink open races the same condition.

**Confirmed live state** (2026-05-07):
```
/dev/video42 (StudioCompositor): exclusive_caps=Y → reports CAPTURE only
/dev/video50-52 (YouTube0-2):    exclusive_caps=N → reports CAPTURE + OUTPUT
```
The compositor (PID 2495155) actively holds the fd and pushes frames, but a separate `v4l2-ctl --info` call sees only CAPTURE caps — confirming that `exclusive_caps=1` hides OUTPUT from non-producer openers.

## §2 Current Configuration

`/etc/modprobe.d/v4l2loopback-hapax.conf`:
```
options v4l2loopback devices=8 video_nr=10,42,50,51,52,60,61,62
  card_label="OBS_Virtual_Camera,StudioCompositor,YouTube0,YouTube1,YouTube2,
  hapax-rtsp-pi4-brio,hapax-rtsp-pi5-c920,hapax-rtsp-pi1-brio-synths"
  exclusive_caps=1,1,0,0,0,1,1 max_buffers=8
```

8 devices, 7 `exclusive_caps` values — device 62 gets the default (0).

| Device | Name | exclusive_caps | Consumer | Issue |
|--------|------|---------------|----------|-------|
| /dev/video10 | OBS_Virtual_Camera | 1 | Chrome/WebRTC | **Needs** exclusive_caps=1 |
| /dev/video42 | StudioCompositor | 1 | OBS only | Does NOT need exclusive_caps=1 |
| /dev/video50 | YouTube0 | 0 | OBS | Works fine |
| /dev/video51 | YouTube1 | 0 | OBS | Works fine |
| /dev/video52 | YouTube2 | 0 | OBS | Works fine |
| /dev/video60 | hapax-rtsp-pi4-brio | 1 | Compositor | Same chicken-and-egg risk |
| /dev/video61 | hapax-rtsp-pi5-c920 | 1 | Compositor | Same chicken-and-egg risk |
| /dev/video62 | hapax-rtsp-pi1-brio-synths | 0 | Compositor | Works fine |

## §3 Can `v4l2loopback-ctl set-caps` Help?

**No, not durably.**

`v4l2loopback-ctl set-caps /dev/video42 "NV12:1920x1080@30/1"` opens the device, calls `VIDIOC_S_FMT` (acquiring an output stream token and enabling `keep_format=1`), then **closes the fd on exit**. Once the fd closes, the output stream token is released and the device reverts to CAPTURE-only advertisement.

`keep_format=1` preserves the **pixel format and resolution** across producer disconnects. It does NOT preserve the `V4L2_CAP_VIDEO_OUTPUT` flag in `QUERYCAP`. The output flag is purely a function of whether an output stream token is currently held, which requires an open fd.

Running `set-caps` as `ExecStartPre` in the systemd unit would transiently set the format but the effect vanishes before `v4l2sink` opens the device.

A background process holding the fd open would work but adds unnecessary complexity when a simpler solution exists.

## §4 Is `exclusive_caps=0` Safe for Our OBS Consumer?

**Yes.** Five reasons:

1. **`exclusive_caps=1` was designed for Chrome/WebRTC.** Chrome's `getUserMedia` rejected devices advertising both CAPTURE and OUTPUT. Only `/dev/video10` (OBS Virtual Camera) serves browser consumers.

2. **OBS handles dual-cap devices correctly.** The YouTube loopback devices (50/51/52) already use `exclusive_caps=0` and OBS reads from them without issues. OBS uses `V4L2_CAP_VIDEO_CAPTURE` for source setup and ignores OUTPUT.

3. **No format renegotiation risk.** With `exclusive_caps=0`, both caps are always advertised. v4l2sink sees OUTPUT immediately — no chicken-and-egg.

4. **Stall recovery works cleanly.** `V4l2OutputPipeline.rebuild()` can teardown and rebuild without the caps-advertisement gap because `exclusive_caps=0` always advertises OUTPUT regardless of fd state.

5. **Single-producer enforcement is separate.** `exclusive_caps` does not enforce single-producer access — `max_openers` does that. With `exclusive_caps=0`, the kernel module still rejects a second producer at the `VIDIOC_S_FMT` / `VIDIOC_QBUF` level with `EBUSY`.

## §5 Recommendation

Change `exclusive_caps` from `1` to `0` for `/dev/video42`, `/dev/video60`, and `/dev/video61`. Keep `/dev/video10` at `exclusive_caps=1` (Chrome/WebRTC compatibility). Add the missing 8th value for `/dev/video62` (explicit `0`).

### Proposed config

```
options v4l2loopback devices=8 video_nr=10,42,50,51,52,60,61,62
  card_label="OBS_Virtual_Camera,StudioCompositor,YouTube0,YouTube1,YouTube2,
  hapax-rtsp-pi4-brio,hapax-rtsp-pi5-c920,hapax-rtsp-pi1-brio-synths"
  exclusive_caps=1,0,0,0,0,0,0,0 max_buffers=8
```

### Deployment steps

1. Edit `/etc/modprobe.d/v4l2loopback-hapax.conf` (requires sudo)
2. Stop all consumers: `systemctl --user stop studio-compositor.service` + close OBS
3. Unload module: `sudo modprobe -r v4l2loopback`
4. Reload: `sudo modprobe v4l2loopback`
5. Restart compositor: `systemctl --user start studio-compositor.service`
6. Verify: `v4l2-ctl -d /dev/video42 --info` should show both Video Capture and Video Output

### Risk assessment

**Low.** The YouTube devices have run `exclusive_caps=0` since the compositor was deployed with zero issues. The only behavioral difference: `v4l2-ctl --info` from a separate process will show both CAPTURE and OUTPUT flags. Chrome would see `/dev/video42` as a potential camera source, but Chrome is not used for camera capture in this system.

## §6 References

- [umlaeute/v4l2loopback#370](https://github.com/umlaeute/v4l2loopback/issues/370) — "not a output device" chicken-and-egg
- [umlaeute/v4l2loopback#442](https://github.com/umlaeute/v4l2loopback/issues/442) — exclusive_caps single-producer limits
- [umlaeute/v4l2loopback PR #611](https://github.com/umlaeute/v4l2loopback/pull/611) — set-caps stream token behavior
- [v4l2loopback kernel module source](https://github.com/umlaeute/v4l2loopback/blob/main/v4l2loopback.c) — QUERYCAP conditional logic
- [v4l2loopback-ctl source](https://github.com/umlaeute/v4l2loopback/blob/main/utils/v4l2loopback-ctl.c) — set-caps fd lifecycle
- `docs/research/2026-04-20-v4l2sink-stall-prevention.md` §4 — prior exclusive_caps analysis
- `agents/studio_compositor/v4l2_output_pipeline.py` — isolated output pipeline with rebuild()
- `agents/studio_compositor/v4l2_stall_recovery.py` — stall recovery state-cycle
