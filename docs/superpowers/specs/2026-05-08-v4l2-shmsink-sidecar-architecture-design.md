# shmsink sidecar architecture — decouple compositor from v4l2loopback

**Date:** 2026-05-08
**Author:** beta
**Status:** spec (ready for implementation)
**CC-task:** `v4l2-shmsink-sidecar-architecture` (WSJF 7.0, P1)
**Train:** `v4l2-pipeline-reliability-2026-05`
**Depends on:** `v4l2-appsink-os-write-replacement` (WSJF 7.5, P0)
**Research:** `docs/research/2026-04-20-v4l2sink-stall-prevention.md`

---

## §1 Problem statement

The studio compositor currently owns the `/dev/video42` v4l2loopback file descriptor via `V4l2OutputPipeline` (`agents/studio_compositor/v4l2_output_pipeline.py`). Despite the interpipe isolation introduced to avoid GL-chain flush latency, the compositor process remains coupled to v4l2loopback kernel state. Eight documented failure modes (research doc §2) can stall or deadlock the v4l2sink branch:

1. NVIDIA GL context loss
2. Format renegotiation deadlock (`exclusive_caps=1` + OBS reopen)
3. v4l2loopback buffer exhaustion (`max_buffers=8` ring full)
4. V4L2 driver `select()` timeout (OBS symptom)
5. Internal queue stall (blocked QBUF propagates)
6. `glcolorconvert`/`gldownload` GL stall
7. GLib main loop vs streaming thread contention
8. dmabuf fd leak / descriptor exhaustion

The existing stall recovery (`v4l2_stall_recovery.py`) cycles the `V4l2OutputPipeline` state (PLAYING → NULL → PLAYING), but the compositor process still holds the fd. A kernel-level deadlock on the v4l2loopback device requires killing the entire compositor.

**Goal:** Move the v4l2loopback fd into a separate process. The compositor writes frames to shared memory. A lightweight sidecar reads from shared memory and writes to `/dev/video42`. The sidecar can crash, restart, or be upgraded without touching the compositor pipeline.

## §2 Architecture

```
┌─────────────────────────────────────────────────────────┐
│  studio-compositor.service                              │
│                                                         │
│  output_tee ─→ queue ─→ videoconvert ─→ capsfilter     │
│                          (NV12/720p/30fps)              │
│                ─→ shmsink                               │
│                   socket-path=/dev/shm/hapax-compositor │
│                   /v4l2-bridge.sock                     │
│                   wait-for-connection=False              │
│                   shm-size=16777216                      │
│                                                         │
└──────────────────────────┬──────────────────────────────┘
                           │ Unix domain socket
                           │ + POSIX shared memory
┌──────────────────────────▼──────────────────────────────┐
│  hapax-v4l2-bridge.service                              │
│  (Type=simple, Restart=always, RestartSec=1s)           │
│  BindsTo=studio-compositor.service                      │
│                                                         │
│  shmsrc ─→ v4l2sink device=/dev/video42                 │
│            sync=False qos=False                         │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### §2.1 Why shmsink over raw `/dev/shm` RGBA

The reverie visual pipeline uses raw RGBA files on `/dev/shm`. This works for reverie because the producer (wgpu) and consumer (Tauri frame server) are tightly coupled and use a single-writer-single-reader pattern with no backpressure. The compositor output path has different requirements:

- **Backpressure signalling**: shmsink/shmsrc use socket-based ACK for buffer lifecycle. A slow sidecar drops frames at the shmsink boundary rather than filling an unbounded ring.
- **Format negotiation**: GStreamer caps propagate through the socket. The sidecar's shmsrc receives format metadata without a sideband channel.
- **Zero-copy**: shmsrc maps the same SHM segment. No `memcpy` on the consumer side.
- **Standard GStreamer element**: Well-tested in `gst-plugins-bad`. No custom protocol to maintain.

### §2.2 Why NOT shmsink (alternatives considered)

| Alternative | Pros | Cons | Verdict |
|---|---|---|---|
| Raw `/dev/shm` + inotify | Simpler, no GStreamer on sidecar | No caps negotiation, custom protocol, race conditions | Rejected |
| `interpipesrc`/`interpipesink` cross-process | Already used internally | Same-process only; does not cross process boundaries | Rejected |
| TCP/UDP socket | Cross-machine capable | Unnecessary latency, serialization overhead, no zero-copy | Rejected |
| `appsink` → `os.write()` to SHM file | Python-level control | Still needs a consumer protocol; reinvents shmsink | Rejected for compositor side; viable for sidecar v4l2 write |

## §3 Compositor-side changes

### §3.1 New shmsink output branch

In `pipeline.py`, the current `interpipesink("compositor_v4l2_out")` tap on `output_tee` (lines 177–206) is replaced with a `shmsink` branch when the env flag `HAPAX_V4L2_SHMSINK=1` is set. The interpipe path remains as the fallback.

```
output_tee → queue (leaky=downstream, max-size-buffers=5)
           → videoconvert (dither=0)
           → capsfilter (video/x-raw, format=NV12, width=W, height=H, framerate=F/1)
           → shmsink (socket-path=SOCKET_PATH, shm-size=16777216,
                       wait-for-connection=False, sync=False)
```

**Socket path:** `/dev/shm/hapax-compositor/v4l2-bridge.sock`

**SHM size calculation:** NV12 at 1920×1080 = 3,110,400 bytes/frame. At 4-frame headroom: ~12.4 MB. Spec: 16 MB (`shm-size=16777216`) for safety margin. Lower resolutions (1280×720 = 1,382,400 bytes/frame) use the same 16 MB allocation — ample.

**`wait-for-connection=False`:** The compositor pipeline MUST NOT block on the sidecar. Frames are silently dropped when no consumer is attached. This is correct — the sidecar's absence is the sidecar's problem.

### §3.2 Buffer probe for watchdog

A `Gst.PadProbeType.BUFFER` probe on the shmsink's `sink` pad replaces the existing v4l2sink probe. The probe updates `_shmsink_last_frame_monotonic` (same pattern as the current `_v4l2_last_frame_monotonic` in `v4l2_output_pipeline.py:135`).

The watchdog tick in `lifecycle.py` gates on `shmsink_frame_seen_within(45.0)` instead of `v4l2_frame_seen_within(45.0)`. This detects compositor-side output stalls (GL chain death, cudacompositor blockage) but NOT sidecar-side stalls — those are the sidecar's responsibility.

### §3.3 V4l2OutputPipeline env-flag rollback

`V4l2OutputPipeline` is NOT deleted. When `HAPAX_V4L2_SHMSINK` is unset or `0`, the existing interpipe + `V4l2OutputPipeline` path remains active. The feature flag lives in `pipeline.py` at branch-construction time.

When `HAPAX_V4L2_SHMSINK=1`:
- `V4l2OutputPipeline` is not constructed
- `v4l2_stall_recovery.py` is not initialized
- The shmsink branch is built instead

### §3.4 Metrics

| Metric | Type | Description |
|---|---|---|
| `studio_compositor_shmsink_frames_total` | Counter | Buffers crossing the shmsink sink pad |
| `studio_compositor_shmsink_last_frame_seconds_ago` | Gauge | Staleness of shmsink output |
| `studio_compositor_shmsink_drops_total` | Counter | Frames dropped (no consumer connected) |

Existing `V4L2SINK_*` metrics remain for the rollback path.

### §3.5 Socket lifecycle

The compositor creates the socket directory (`/dev/shm/hapax-compositor/`) in its init path (already exists for `snapshot.jpg`, `status.json`, etc). The shmsink element creates and manages the socket file. On compositor restart, shmsink recreates the socket; the sidecar must handle reconnection (see §4.3).

## §4 Sidecar design

### §4.1 Script: `scripts/hapax-v4l2-bridge`

A standalone Python script. Minimal dependencies: GStreamer (`gi.repository.Gst`), `os`, `signal`, `sys`, `time`, `logging`.

**Pipeline:**

```
shmsrc socket-path=/dev/shm/hapax-compositor/v4l2-bridge.sock
       is-live=True do-timestamp=True
  → queue leaky=downstream max-size-buffers=3
  → v4l2sink device=/dev/video42 sync=False qos=False
             enable-last-sample=False
```

No `videoconvert` needed — the compositor's shmsink branch already produces NV12; the sidecar's shmsrc receives it directly.

**Alternative v4l2 write path (from predecessor task):** If the `v4l2-appsink-os-write-replacement` task ships first, the sidecar MAY use `appsink` + `os.write()` instead of `v4l2sink`:

```
shmsrc → queue → appsink → Python: os.write(v4l2_fd, buffer)
```

This gives Python-level control over the fd lifecycle (reopen on ENODEV/EBUSY/EIO). The spec is agnostic — either approach satisfies the acceptance criteria. The GStreamer-native path (`shmsrc → v4l2sink`) is simpler; the appsink path is more resilient to kernel-level v4l2loopback issues.

### §4.2 Error handling

| Failure | Sidecar behavior | Recovery |
|---|---|---|
| shmsink socket disappears (compositor restart) | shmsrc posts bus ERROR | Sidecar exits → systemd `Restart=always` → reconnects to new socket |
| v4l2loopback EBUSY/ENODEV | v4l2sink posts bus ERROR | Sidecar exits → systemd restarts → v4l2sink reopens device |
| v4l2loopback buffer exhaustion | v4l2sink blocks → queue drops frames | Self-healing via leaky queue; no intervention needed |
| OBS not reading `/dev/video42` | v4l2loopback ring fills | Sidecar queue drops frames; no upstream impact |
| SHM format mismatch | shmsrc caps negotiation fails | Sidecar exits → restart → renegotiates from shmsink |

The sidecar is designed to be stateless and crash-tolerant. Every failure mode resolves with a process restart. The `RestartSec=1s` + `Restart=always` systemd configuration bounds recovery to under 2 seconds.

### §4.3 Reconnection after compositor restart

When the compositor restarts, it recreates the shmsink socket. The sidecar's existing shmsrc connection becomes invalid (the old socket fd points to a deleted inode). The sidecar receives a bus ERROR from shmsrc and exits. systemd restarts it; the new instance connects to the new socket.

**Stale socket cleanup:** The sidecar's systemd unit includes `ExecStartPre=/bin/rm -f /dev/shm/hapax-compositor/v4l2-bridge.sock`. This prevents a stale socket from blocking shmsink's bind. The compositor's shmsink also unlinks-and-recreates the socket on startup (GStreamer shmsink behavior), so this is defense-in-depth.

### §4.4 Signal handling

The sidecar traps SIGTERM and SIGINT to set the pipeline to NULL before exiting. This ensures the v4l2loopback fd is released cleanly so the next instance can open it.

## §5 systemd unit: `hapax-v4l2-bridge.service`

```ini
[Unit]
Description=v4l2loopback bridge (shmsrc → /dev/video42)
BindsTo=studio-compositor.service
After=studio-compositor.service
ConditionPathExists=/dev/video42

[Service]
Type=simple
ExecStartPre=/bin/rm -f /dev/shm/hapax-compositor/v4l2-bridge.sock
ExecStart=%h/projects/hapax-council/.venv/bin/python \
    %h/projects/hapax-council/scripts/hapax-v4l2-bridge \
    --socket /dev/shm/hapax-compositor/v4l2-bridge.sock \
    --device /dev/video42
Restart=always
RestartSec=1
StartLimitBurst=60
StartLimitIntervalSec=300
Environment=CUDA_VISIBLE_DEVICES=
MemoryMax=256M
Nice=5

[Install]
WantedBy=default.target
```

**Key decisions:**

- **`BindsTo=studio-compositor.service`**: Sidecar stops when compositor stops. Prevents orphaned v4l2loopback writes.
- **`After=studio-compositor.service`**: Ordering guarantee — shmsink socket exists before shmsrc tries to connect.
- **`CUDA_VISIBLE_DEVICES=`**: Sidecar has no GPU work. Prevents accidental CUDA context allocation.
- **`MemoryMax=256M`**: Tight cap. The sidecar's steady-state is ~50 MB (GStreamer + SHM mapping).
- **`StartLimitBurst=60` / `StartLimitIntervalSec=300`**: Allows up to 60 restarts in 5 minutes before systemd gives up. With 1s restart interval, this covers sustained compositor instability without permanent failure.
- **`Nice=5`**: Lower priority than the compositor (Nice=-10 via OOMScoreAdjust on compositor). If the system is under load, the sidecar drops frames rather than competing with the compositor.
- **No `WatchdogSec`**: The compositor's watchdog detects output absence. The sidecar's only job is to proxy frames; if it dies, systemd restarts it. A sidecar-side watchdog would add complexity without additional safety.

## §6 Latency analysis

| Segment | Expected latency | Source |
|---|---|---|
| Compositor `output_tee` → shmsink | <1 ms | In-process GStreamer push + SHM write |
| shmsink → shmsrc (IPC) | <0.5 ms | Socket notification + SHM mmap (zero-copy) |
| shmsrc → v4l2sink | <1 ms | In-process GStreamer push + VIDIOC_QBUF |
| v4l2loopback kernel → OBS read | <1 ms | Kernel ring buffer read |
| **Total shmsink path** | **<4 ms** | Well under the 50 ms acceptance criterion |

For comparison, the current interpipe + `V4l2OutputPipeline` path adds ~2 ms (interpipe socket overhead). The shmsink path is comparable or slightly faster because the sidecar pipeline is shorter (no interpipesrc caps negotiation overhead).

## §7 File manifest

| File | Action | Description |
|---|---|---|
| `agents/studio_compositor/pipeline.py` | Modify | Add shmsink branch behind `HAPAX_V4L2_SHMSINK` env flag |
| `agents/studio_compositor/shmsink_output.py` | Create | shmsink element construction, probe wiring, metrics |
| `agents/studio_compositor/lifecycle.py` | Modify | Gate watchdog on shmsink staleness when flag is set |
| `agents/studio_compositor/metrics.py` | Modify | Add `SHMSINK_*` Prometheus metrics |
| `scripts/hapax-v4l2-bridge` | Create | Sidecar script (shmsrc → v4l2sink) |
| `systemd/units/hapax-v4l2-bridge.service` | Create | systemd unit for sidecar |
| `agents/studio_compositor/v4l2_output_pipeline.py` | Retain | Unchanged; rollback path |
| `agents/studio_compositor/v4l2_stall_recovery.py` | Retain | Unchanged; rollback path |
| `agents/studio_compositor/output_router.py` | Retain | `SinkKind.shm` already present |

## §8 Migration sequence

### Phase A: Feature-flagged shmsink (this task)

1. Implement `shmsink_output.py` with the shmsink branch construction.
2. Wire the env-flag branch in `pipeline.py`.
3. Write `scripts/hapax-v4l2-bridge`.
4. Write `systemd/units/hapax-v4l2-bridge.service`.
5. Update `lifecycle.py` watchdog to gate on shmsink metrics when flag is on.
6. Add metrics to `metrics.py`.

### Phase B: Operator validation

1. Set `HAPAX_V4L2_SHMSINK=1` in compositor env.
2. `systemctl --user enable --now hapax-v4l2-bridge.service`.
3. Verify OBS receives frames.
4. Kill sidecar: `systemctl --user kill hapax-v4l2-bridge.service`. Verify 1–2s recovery.
5. Restart compositor: `systemctl --user restart studio-compositor.service`. Verify sidecar reconnects.
6. Measure frame latency via embedded frame counter (Prometheus `shmsink_last_frame_seconds_ago`).

### Phase C: Default-on (follow-up task)

1. Flip `HAPAX_V4L2_SHMSINK` default to `1`.
2. Remove or archive `V4l2OutputPipeline` and `v4l2_stall_recovery.py` after one sprint of stable operation.

## §9 Rollback

Unset `HAPAX_V4L2_SHMSINK` (or set to `0`). Restart compositor. The interpipe + `V4l2OutputPipeline` path resumes. Disable sidecar: `systemctl --user disable --now hapax-v4l2-bridge.service`.

## §10 Acceptance criteria (from cc-task)

- [ ] Compositor runs without any direct v4l2loopback fd
- [ ] Sidecar restart recovers OBS feed within 2s
- [ ] `systemctl --user restart hapax-v4l2-bridge` does not interrupt compositor pipeline
- [ ] Frame latency shm → v4l2 → OBS < 50 ms

## §11 Open questions

1. **Should the sidecar also write the heartbeat file at `/dev/shm/hapax-compositor/v4l2-heartbeat`?** The compositor's shmsink probe tells the compositor "I wrote a frame to SHM." The sidecar's v4l2sink probe would tell "a frame reached the v4l2loopback device." Both signals are useful. Recommendation: yes, the sidecar writes its own heartbeat file at `/dev/shm/hapax-compositor/v4l2-bridge-heartbeat` for external watchers.

2. **GStreamer `shmsink` reconnection behavior**: Does shmsink accept a new shmsrc connection after the first client disconnects, or must the element be cycled? Per GStreamer docs, shmsink accepts new connections on the same socket. Needs empirical verification.

3. **Should the sidecar expose its own Prometheus metrics?** The compositor already scrapes at `127.0.0.1:9482`. Options: (a) sidecar writes a separate metrics endpoint; (b) sidecar writes metrics to a file the compositor reads; (c) no sidecar metrics — the compositor's shmsink probe is sufficient. Recommendation: (a) with a separate port (e.g. `127.0.0.1:9483`).

4. **`exclusive_caps` interaction**: The predecessor task (`v4l2-exclusive-caps-modprobe-change`) sets `exclusive_caps=0` on `/dev/video42`. With `exclusive_caps=0`, multiple processes can open the device. This is compatible with the sidecar model — but if the predecessor hasn't shipped, the sidecar inherits `exclusive_caps=1`, meaning a stale fd from a crashed sidecar blocks the next instance. The sidecar's SIGTERM handler (§4.4) mitigates this; `RestartSec=1s` gives the kernel time to release the fd.
