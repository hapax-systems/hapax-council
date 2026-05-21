# V4L2 Bridge Sidecar Architecture

**Date:** 2026-05-21
**Status:** Implemented (bridge opt-in, direct path default)
**Predecessor spec:** `docs/superpowers/specs/2026-05-08-v4l2-shmsink-sidecar-architecture-design.md`

## 1. Overview

The studio compositor writes final composited frames to `/dev/video42` (a v4l2loopback
virtual camera device), which OBS reads for livestreaming. Two output paths exist:

1. **Direct path** (current default): compositor process holds the v4l2loopback fd directly
   via `V4l2OutputPipeline` — `interpipesrc → videoconvert → appsink → os.write(/dev/video42)`.
2. **Sidecar path** (opt-in): compositor writes to shared memory via `ShmsinkOutputPipeline`.
   A separate process (`hapax-v4l2-bridge.service`) reads from shared memory and writes to
   `/dev/video42`.

The sidecar isolates the compositor from v4l2loopback kernel state so driver-level stalls,
buffer exhaustion, or consumer (OBS) disconnects cannot propagate into the compositor
pipeline.

## 2. Process boundary and IPC mechanism

### 2.1 shmsink / shmsrc (GStreamer shared memory)

The IPC boundary uses GStreamer's `shmsink` and `shmsrc` elements, which communicate via:

- **Unix domain socket** at `/dev/shm/hapax-compositor/v4l2-bridge.sock` — carries buffer
  lifecycle signalling (new-buffer notifications, ACKs). shmsink creates and manages this
  socket; shmsrc connects to it.
- **POSIX shared memory segment** — the actual frame data. shmsink allocates a SHM region
  (`shm-size` = 8 frames × NV12 frame size ≈ 11 MB at 1280×720). shmsrc maps the same
  segment. Zero-copy: no `memcpy` between processes.

Caps (format, resolution, framerate) propagate through the socket connection, eliminating
any sideband negotiation protocol.

### 2.2 Compositor side (`ShmsinkOutputPipeline`)

File: `agents/studio_compositor/shmsink_output_pipeline.py`

```
interpipesrc(listen-to="compositor_v4l2_out")
  → queue(leaky=downstream, max-size-buffers=5)
  → videorate(skip-to-first=True)
  → capsfilter(framerate lock)
  → videoconvert(dither=0)
  → capsfilter(video/x-raw, format=NV12, 1280×720, 30fps)
  → shmsink(socket-path=v4l2-bridge.sock, wait-for-connection=False)
```

Key property: `wait-for-connection=False`. The compositor pipeline never blocks waiting for
the sidecar. Frames are silently dropped when no consumer is attached. The compositor's
watchdog gates on its own shmsink pad probe, not on whether the sidecar consumed the frame.

A `Gst.PadProbeType.BUFFER` probe on the shmsink pad updates `last_frame_monotonic` for
watchdog liveness and writes a proof JPEG snapshot (`fx-snapshot.jpg`) to `/dev/shm` to
verify the exact NV12 frame reaching the egress boundary.

### 2.3 Sidecar side (`ShmToV4l2Bridge`)

File: `agents/studio_compositor/v4l2_shm_bridge.py`
Launcher: `scripts/hapax-v4l2-bridge`

```
shmsrc(socket-path=v4l2-bridge.sock, is-live=True)
  → capsfilter(NV12, 1280×720, 30fps)
  → queue(leaky=downstream, max-size-buffers=5)
  → videoconvert(dither=0)
  → capsfilter(NV12)
  → appsink(emit-signals=True, drop=True)
        └→ Python: os.write(v4l2_fd, buffer)
```

The sidecar uses `appsink` + `os.write()` rather than GStreamer's `v4l2sink` element.
Runtime canaries found that `v4l2sink` can fail inside its V4L2 buffer pool while the same
loopback device remains writable through the direct `os.write()` path. The `appsink` approach
gives Python-level control over the file descriptor lifecycle — on write failure (EAGAIN, EIO,
ENODEV, ENXIO), the fd is closed and reopened without tearing down the GStreamer pipeline.

## 3. Compositor code paths touching v4l2loopback kernel state

### 3.1 Direct output path (active when `HAPAX_V4L2_BRIDGE_ENABLED != 1`)

| Code path | Kernel interaction | File |
|---|---|---|
| `V4l2OutputPipeline._open_fd()` | `os.open(/dev/video42, O_WRONLY\|O_NONBLOCK)` | `v4l2_output_pipeline.py:212-230` |
| `V4l2OutputPipeline._write_frame()` | `os.write(fd, NV12_data)` | `v4l2_output_pipeline.py:257-278` |
| `V4l2OutputPipeline._reopen_fd()` | `os.close()` + `os.open()` cycle | `v4l2_output_pipeline.py:241-255` |
| `_enforce_v4l2_output_format()` | `v4l2-ctl --set-fmt-video-out`, `--set-parm`, `-c keep_format=1` | `v4l2_output_pipeline.py:99-150` |
| `v4l2_stall_recovery.try_recover()` | Cycles V4l2OutputPipeline state to force fd reopen | `v4l2_stall_recovery.py:245-340` |

### 3.2 Sidecar path (active when `HAPAX_V4L2_BRIDGE_ENABLED=1`)

The compositor process makes **zero** v4l2loopback kernel calls. All kernel interaction
moves to the sidecar process:

| Code path | Kernel interaction | File |
|---|---|---|
| `ShmToV4l2Bridge._open_fd()` | `os.open(/dev/video42, O_WRONLY\|O_NONBLOCK)` | `v4l2_shm_bridge.py:114-131` |
| `ShmToV4l2Bridge._write_frame()` | `os.write(fd, NV12_data)` | `v4l2_shm_bridge.py:152-167` |
| `ShmToV4l2Bridge._reopen_fd()` | `os.close()` + `os.open()` cycle | `v4l2_shm_bridge.py:143-149` |
| `_enforce_v4l2_output_format()` | `v4l2-ctl` (imported from `v4l2_output_pipeline`) | `v4l2_shm_bridge.py:24` |

### 3.3 Camera per-camera loopback branches

`camera_pipeline.py:440-477` builds per-camera v4l2sink branches for individual camera
loopback devices (not `/dev/video42`). These write directly to per-camera loopback devices
(e.g., `/dev/video70`–`/dev/video75`) and are NOT part of the sidecar boundary. They remain
in-process because each camera's loopback is consumed only by specialized tools (face
detection, classification), not by the high-availability livestream path.

### 3.4 Format guard (shared by both paths)

`hapax-video42-format-guard.service` (oneshot, `RemainAfterExit=yes`) runs before both the
compositor and the sidecar. It pins `/dev/video42` to NV12, 1280×720, 30fps via `v4l2-ctl`.
The `keep_format=1` control prevents OBS from renegotiating the format on reconnect.

### 3.5 v4l2loopback kernel module configuration

`config/modprobe.d/v4l2loopback-hapax.conf` defines 14 loopback devices. `/dev/video42`
(index 1) has `exclusive_caps=0`, meaning multiple processes can open the device. This is
compatible with the sidecar model — a stale fd from a crashed sidecar does not block the
next instance from opening the device.

### 3.6 Output path selection (env flag matrix)

Controlled in `pipeline.py:127-142` and `pipeline.py:393-450`:

| `HAPAX_V4L2_BRIDGE_ENABLED` | `HAPAX_COMPOSITOR_DISABLE_V4L2_OUTPUT` | `HAPAX_3D_COMPOSITOR` | Result |
|---|---|---|---|
| `0` (default) | `0` | `0` | Direct `V4l2OutputPipeline` |
| `1` | `0` | `0` | `ShmsinkOutputPipeline` + sidecar |
| any | `1` | any | No v4l2/shm output (incident containment) |
| any | any | `1` | 3D compositor mode; v4l2 owned by hapax-imagination |

## 4. systemd unit design

### 4.1 `hapax-v4l2-bridge.service`

| Property | Value | Rationale |
|---|---|---|
| `Type` | `simple` | No sd_notify — process liveliness is the sidecar's only contract |
| `Restart` | `on-failure` | Every failure mode resolves with a process restart |
| `RestartSec` | `1s` | Bound recovery to <2 seconds |
| `BindsTo` | `studio-compositor.service` | Sidecar stops when compositor stops |
| `PartOf` | `studio-compositor.service` | Sidecar restarts when compositor restarts |
| `After` / `Requires` | `hapax-video42-format-guard.service`, `studio-compositor.service` | Format is pinned before sidecar opens the device; socket exists before shmsrc connects |
| `ConditionPathExists` | `scripts/hapax-v4l2-bridge` | Prevents activation on machines without the bridge script |
| `TimeoutStartSec` | `45s` | Socket wait budget (bridge waits up to 60s internally, systemd kills at 45s) |
| `GST_DEBUG` | `2` | Warnings only, no per-frame noise |
| cgroup | Default (no `MemoryMax`) | Sidecar steady-state is ~50 MB |
| OOM | Default priority (compositor has OOMScoreAdjust, sidecar does not) | Under pressure, sidecar is killed before compositor |

### 4.2 Dependency graph

```
hapax-video42-format-guard.service (oneshot, RemainAfterExit)
    ↓ Before
studio-compositor.service
    ↓ Wants, After (compositor creates shmsink socket)
hapax-v4l2-bridge.service (BindsTo + PartOf compositor)
    ↓ After
hapax-v4l2-bridge-watchdog.timer (10s poll)
    → hapax-v4l2-bridge-watchdog.service (oneshot, checks bridge egress health)
hapax-obs-v4l2-source-reset.service (monitors OBS capture source, resets on stall)
```

### 4.3 Drop-in override

`systemd/units/studio-compositor.service.d/v4l2-bridge.conf` sets
`HAPAX_V4L2_BRIDGE_ENABLED=0` on the compositor, keeping the direct path as default.
To activate the sidecar path: change to `HAPAX_V4L2_BRIDGE_ENABLED=1`, then
`systemctl --user daemon-reload && systemctl --user restart studio-compositor`.

### 4.4 Watchdog hierarchy

- **Compositor watchdog** (`WatchdogSec=60s`): gates on "at least one camera has frames
  within 20s." In sidecar mode, also checks `ShmsinkOutputPipeline.is_alive(45.0)` —
  frames reaching the shmsink pad, not whether the sidecar consumed them.
- **V4L2 bridge watchdog** (`hapax-v4l2-bridge-watchdog.timer`, 10s): reads the sidecar's
  Prometheus metrics file (`/dev/shm/hapax-compositor/v4l2-bridge.prom`) and checks
  `hapax_v4l2_bridge_heartbeat_seconds_ago`. Triggers recovery if stale.
- **V4L2 heartbeat watchdog** (`hapax-v4l2-watchdog.timer`, 10s): legacy watchdog that
  detects stalled frame output regardless of which path is active.
- **OBS v4l2 source reset** (`hapax-obs-v4l2-source-reset.service`): monitors OBS's V4L2
  capture source and resets it on disconnect/stall events (WatchdogSec=120s, Type=notify).

## 5. Failure modes and recovery

### 5.1 Sidecar crash

1. Sidecar process exits (bus ERROR, SIGKILL, OOM).
2. v4l2loopback fd is released by kernel (process death closes all fds).
3. systemd restarts sidecar after `RestartSec=1s`.
4. New sidecar waits for shmsink socket (up to 60s).
5. shmsrc connects, pipeline goes PLAYING, frames resume.
6. **Compositor impact:** none. shmsink continues to accept frames from the compositor
   with `wait-for-connection=False`. Frames are dropped into the void during the ~1s
   recovery window. The compositor's watchdog does not trigger because its probe sees
   frames reaching the shmsink pad.
7. **OBS impact:** ~1–2 second black frame or freeze, then automatic recovery.

### 5.2 v4l2loopback kernel module unload

1. `rmmod v4l2loopback` destroys all `/dev/video*` device nodes.
2. Sidecar's `os.write()` fails with `ENODEV`; sidecar attempts fd reopen, which fails
   (`os.open` raises `FileNotFoundError` or `ENODEV`).
3. Sidecar exits after exhausting reopen attempts → systemd restart loop hits
   `StartLimitBurst` (not configured on current unit; defaults apply).
4. **Compositor impact (sidecar mode):** none — compositor writes to SHM, not device.
5. **Compositor impact (direct mode):** `V4l2OutputPipeline._write_frame()` fails with
   ENODEV; fd reopen loop runs until device reappears.
6. **Recovery:** `modprobe v4l2loopback` recreates devices. Format guard must re-run
   (`systemctl --user restart hapax-video42-format-guard`). Sidecar or compositor
   reopens the fd on next write attempt.

### 5.3 Compositor restart

1. Compositor receives SIGTERM or watchdog kill.
2. shmsink socket inode is deleted (process death).
3. Sidecar's shmsrc detects socket disappearance → bus ERROR → sidecar exits.
4. Compositor restarts via `Restart=on-failure`.
5. Compositor creates new shmsink socket.
6. systemd restarts sidecar (`PartOf=studio-compositor` triggers restart on compositor
   restart). Sidecar connects to new socket.
7. **Socket cleanup:** compositor's `ExecStartPre` deletes stale socket files:
   `find /dev/shm/hapax-compositor -maxdepth 1 -type s -name v4l2-bridge.sock* -delete`.

### 5.4 OBS not reading `/dev/video42`

v4l2loopback's internal ring buffer fills (`max_buffers=8`). With the direct path,
`os.write()` returns EAGAIN; fd is reopened. With the sidecar path, the same EAGAIN
handling applies in the sidecar. In both cases, upstream frames are dropped at the
leaky queue boundary. No propagation to the compositor.

### 5.5 Shared memory exhaustion

If `/dev/shm` fills (tmpfs full), shmsink allocation fails. The compositor's bus ERROR
handler logs the failure. Since `wait-for-connection=False`, the compositor pipeline
continues without stalling — the shmsink branch becomes a no-op. Recovery requires
freeing `/dev/shm` space.

## 6. Metrics and observability

### 6.1 Sidecar metrics (file-based Prometheus)

Written to `/dev/shm/hapax-compositor/v4l2-bridge.prom` every second and on every frame:

| Metric | Type | Description |
|---|---|---|
| `hapax_v4l2_bridge_write_frames_total` | counter | Frames written to `/dev/video42` |
| `hapax_v4l2_bridge_write_bytes_total` | counter | Bytes written |
| `hapax_v4l2_bridge_write_errors_total` | counter | Failed `os.write()` calls |
| `hapax_v4l2_bridge_reconnects_total` | counter | Successful fd reopen cycles |
| `hapax_v4l2_bridge_heartbeat_seconds_ago` | gauge | Staleness of last successful write |

### 6.2 Compositor-side metrics

`ShmsinkOutputPipeline` reports via the same Prometheus endpoint as the compositor
(`:9482`). The pad probe updates `last_frame_age_seconds` for the watchdog and writes
proof snapshots for visual verification.

## 7. Current deployment state

As of 2026-05-21:
- `HAPAX_V4L2_BRIDGE_ENABLED=0` in the compositor service drop-in.
- The direct `V4l2OutputPipeline` path is active for livestream.
- `hapax-v4l2-bridge.service` exists but is not the active egress path.
- The 3D compositor mode (`HAPAX_3D_COMPOSITOR=1`) is the runtime default, where
  `hapax-imagination` owns `/dev/video42` directly and the GStreamer v4l2 path is skipped.
- The bridge sidecar is ready for activation when the operator switches back to GStreamer
  compositing mode.
