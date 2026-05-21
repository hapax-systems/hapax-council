# V4L2 Bridge Sidecar — Implementation Plan

**Date:** 2026-05-21
**Author:** delta
**Architecture doc:** `docs/architecture/v4l2-bridge-sidecar.md`
**Design spec:** `docs/superpowers/specs/2026-05-08-v4l2-shmsink-sidecar-architecture-design.md`
**Parent request:** `REQ-202605181733-v4l2-bridge-sidecar.md`

## Current state

The V4L2 bridge sidecar is **already implemented** across multiple prior tasks:

| Component | File | Status |
|---|---|---|
| SHM producer (compositor side) | `agents/studio_compositor/shmsink_output_pipeline.py` | Implemented |
| SHM consumer + v4l2 writer (sidecar) | `agents/studio_compositor/v4l2_shm_bridge.py` | Implemented |
| Sidecar launcher | `scripts/hapax-v4l2-bridge` | Implemented |
| systemd unit | `systemd/units/hapax-v4l2-bridge.service` | Implemented |
| Bridge watchdog | `systemd/units/hapax-v4l2-bridge-watchdog.{service,timer}` | Implemented |
| Format guard | `systemd/units/hapax-video42-format-guard.service` | Implemented |
| Compositor drop-in | `systemd/units/studio-compositor.service.d/v4l2-bridge.conf` | Implemented |
| Direct path (fallback) | `agents/studio_compositor/v4l2_output_pipeline.py` | Implemented |
| Stall recovery (direct path) | `agents/studio_compositor/v4l2_stall_recovery.py` | Implemented |
| Pipeline wiring + env flag | `agents/studio_compositor/pipeline.py:393-450` | Implemented |
| Prometheus metrics (sidecar) | `v4l2_shm_bridge.py:298-322` | Implemented |

The sidecar is **disabled by default** via `HAPAX_V4L2_BRIDGE_ENABLED=0` in the compositor
drop-in. The 3D compositor mode (`HAPAX_3D_COMPOSITOR=1`) is the current runtime default,
where `hapax-imagination` owns `/dev/video42` directly.

**What remains:** verification, activation, and test coverage — not new implementation.

## Step sequence

### Step 1: Verify sidecar process skeleton

**Maps to cc-task:** `p1-sidecar-process-skeleton`

**Work:** Verify the existing `ShmToV4l2Bridge` class and launcher script satisfy the
design spec. No new code unless gaps are found.

- [ ] `v4l2_shm_bridge.py` builds a GStreamer pipeline: `shmsrc → capsfilter → queue → videoconvert → capsfilter → appsink`
- [ ] `appsink` callback writes frames via `os.write()` to the v4l2loopback fd
- [ ] Signal handling (SIGTERM, SIGINT) cleanly stops pipeline and releases fd
- [ ] Socket wait loop (`wait_for_socket`) polls for shmsink socket with configurable timeout
- [ ] `scripts/hapax-v4l2-bridge` launcher handles env vars, format guard, bridge-disabled checks, and `exec python -m agents.studio_compositor.v4l2_shm_bridge`
- [ ] Add unit tests for `ShmToV4l2Bridge` if none exist (mock GStreamer, verify fd lifecycle)

**Acceptance:** `scripts/hapax-v4l2-bridge --check` passes on a machine with `/dev/video42` present and compositor running with `HAPAX_V4L2_BRIDGE_ENABLED=1`.

### Step 2: Verify shmsink producer in compositor

**Maps to cc-task:** `p1-compositor-shmsink`

**Work:** Verify `ShmsinkOutputPipeline` satisfies the design spec.

- [ ] `shmsink_output_pipeline.py` builds: `interpipesrc → queue → videorate → capsfilter → videoconvert → capsfilter → shmsink`
- [ ] `wait-for-connection=False` — compositor never blocks on sidecar absence
- [ ] Buffer probe updates `last_frame_monotonic` for watchdog liveness
- [ ] Proof snapshot writer (`_maybe_write_proof_snapshot`) captures the exact NV12 frame at the egress boundary
- [ ] `pipeline.py` correctly selects `ShmsinkOutputPipeline` when `HAPAX_V4L2_BRIDGE_ENABLED=1` and `V4l2OutputPipeline` otherwise
- [ ] `is_v4l2_output_disabled()` short-circuits both paths when `HAPAX_COMPOSITOR_DISABLE_V4L2_OUTPUT=1`
- [ ] Add unit tests for `ShmsinkOutputPipeline` if none exist (mock GStreamer, verify pipeline construction and probe wiring)

**Acceptance:** With `HAPAX_V4L2_BRIDGE_ENABLED=1`, the compositor creates a shmsink socket at `/dev/shm/hapax-compositor/v4l2-bridge.sock` and writes NV12 frames.

### Step 3: Verify v4l2loopback write path in sidecar

**Maps to cc-task:** `p2-v4l2-write-path`

**Work:** Verify the sidecar's fd lifecycle and error recovery.

- [ ] `_open_fd()` calls `_enforce_v4l2_output_format()` (v4l2-ctl format pin) before opening device
- [ ] `_write_frame()` handles EAGAIN, EIO, ENODEV, ENXIO as recoverable — triggers fd reopen
- [ ] `_reopen_fd()` closes fd, waits 100ms, reopens with format enforcement
- [ ] Partial write detection (written != len(data)) counted as error
- [ ] Prometheus metrics file updated on every frame and every error
- [ ] Add test: mock `os.write` returning EAGAIN → verify reopen triggered
- [ ] Add test: mock `os.open` raising ENODEV → verify sidecar exits cleanly

**Acceptance:** Sidecar recovers from transient v4l2 write errors within one frame interval (33ms at 30fps) and from device disappearance within `RestartSec` (1s).

### Step 4: Verify systemd unit file

**Maps to cc-task:** `p2-systemd-unit`

**Work:** Verify the systemd unit and dependency graph.

- [ ] `hapax-v4l2-bridge.service` has `BindsTo=studio-compositor.service` (stops with compositor)
- [ ] `PartOf=studio-compositor.service` (restarts with compositor)
- [ ] `After` + `Requires` on `hapax-video42-format-guard.service` and `studio-compositor.service`
- [ ] `ConditionPathExists` on the bridge script
- [ ] `ExecStartPre` runs source-check and format guard verify-only
- [ ] Socket cleanup in compositor's `ExecStartPre` (`find ... -delete` for stale sockets)
- [ ] Drop-in `v4l2-bridge.conf` correctly sets `HAPAX_V4L2_BRIDGE_ENABLED=0` on compositor
- [ ] `install-units.sh` deploys the bridge service and timer
- [ ] Verify `hapax-v4l2-bridge-watchdog.timer` (10s poll) reads sidecar's `.prom` file

**Acceptance:** `systemctl --user cat hapax-v4l2-bridge.service` shows correct unit with all dependencies. `systemctl --user list-dependencies studio-compositor.service` includes the bridge.

### Step 5: Integration verification

**Maps to cc-task:** `p3-integration-verification`

**Work:** End-to-end test of the sidecar path under operator control.

- [ ] Set `HAPAX_V4L2_BRIDGE_ENABLED=1` in compositor drop-in, daemon-reload, restart compositor
- [ ] Verify shmsink socket appears at `/dev/shm/hapax-compositor/v4l2-bridge.sock`
- [ ] Start sidecar: `systemctl --user start hapax-v4l2-bridge.service`
- [ ] Verify OBS receives frames on `/dev/video42` capture source
- [ ] Kill sidecar: `systemctl --user kill hapax-v4l2-bridge.service` → verify recovery within 2s
- [ ] Restart compositor: `systemctl --user restart studio-compositor.service` → verify sidecar reconnects
- [ ] Check sidecar metrics: `cat /dev/shm/hapax-compositor/v4l2-bridge.prom` → verify counters increment
- [ ] Check proof snapshot: `ls -la /dev/shm/hapax-compositor/fx-snapshot.jpg` → verify freshness
- [ ] Measure latency via `hapax_v4l2_bridge_heartbeat_seconds_ago` gauge
- [ ] Revert to direct path: set `HAPAX_V4L2_BRIDGE_ENABLED=0`, restart → verify fallback works

**Acceptance:** Full round-trip: compositor → shmsink → sidecar → v4l2loopback → OBS, with recovery from sidecar crash and compositor restart demonstrated.

## Risk items

### R1: v4l2loopback kernel module availability

**Risk:** If the kernel module is unloaded or fails to load at boot, both paths fail.
**Mitigation:** `ConditionPathExists=/dev/video42` on the format guard and bridge units prevents
activation. The `install-v4l2loopback-config.sh` script and modprobe config
(`config/modprobe.d/v4l2loopback-hapax.conf`) are already deployed. The module is built via
DKMS and survives kernel updates.
**Severity:** Low — the module has been stable for 6+ months of daily use.

### R2: Shared memory cleanup on crash

**Risk:** A compositor crash can leave stale shmsink socket files. The sidecar's shmsrc
connects to the stale socket and receives no frames.
**Mitigation:** Compositor's `ExecStartPre` deletes stale socket files before startup.
shmsink creates a fresh socket on each startup. The sidecar's `wait_for_socket()` function
checks that the socket is actively LISTEN-ing (via `ss -xlH`), not just present on disk.
**Severity:** Low — triple defense (cleanup + shmsink recreate + listen check).

### R3: Latency budget

**Risk:** The shmsink IPC adds latency to the compositor→OBS path.
**Mitigation:** Design spec estimates <4ms total (§6). The sidecar uses `appsink(sync=False, drop=True)` and a leaky queue, so it never blocks. The NV12 frame transfer is zero-copy via mmap. Empirically comparable to the interpipe path.
**Severity:** Low — well within the 50ms acceptance criterion (one frame at 30fps = 33ms).

### R4: 3D compositor mode interaction

**Risk:** When `HAPAX_3D_COMPOSITOR=1`, hapax-imagination owns `/dev/video42` directly.
Activating the bridge sidecar in this mode creates a conflict.
**Mitigation:** `scripts/hapax-v4l2-bridge` checks `direct_v4l2_owner_reason()` and exits
gracefully if `HAPAX_3D_COMPOSITOR=1` or `HAPAX_IMAGINATION_V4L2_OUTPUT=1` is set on the
compositor or imagination units. The bridge launcher is self-disabling.
**Severity:** Low — explicit mutual exclusion is already implemented.

### R5: `exclusive_caps` interaction

**Risk:** If `/dev/video42` has `exclusive_caps=1`, a stale fd from a crashed sidecar blocks
the next instance from opening the device.
**Mitigation:** Current modprobe config sets `exclusive_caps=0` for device index 1 (video42).
The sidecar's SIGTERM handler releases the fd cleanly. `RestartSec=1s` gives the kernel
time to release the fd after an unclean exit.
**Severity:** Low — `exclusive_caps=0` is the deployed configuration.

## Downstream task disposition

The five downstream cc-tasks (`p1-sidecar-process-skeleton`, `p1-compositor-shmsink`,
`p2-v4l2-write-path`, `p2-systemd-unit`, `p3-integration-verification`) describe work
that is already implemented. Each task should be:

1. Claimed by a session
2. Verified against the acceptance criteria above (code review + targeted tests)
3. Closed with reference to the existing implementation PRs
4. Or, if gaps are found, fixed and PRed

The p1 and p2 tasks can be done in parallel. p3 (integration) depends on all p1/p2 tasks.

## Review request

This plan is ready for review. The architecture is already built; the plan sequences
verification and activation rather than new implementation.
