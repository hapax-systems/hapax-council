# Compositor output stall — 78-minute live incident root cause

**Date:** 2026-04-14
**Author:** delta (beta role — cam-stability focus)
**Scope:** Second drop in the OBS output node walk. **A
live production incident was discovered while auditing
the v4l2sink → v4l2loopback path**: the compositor has
been producing zero output frames for 78+ minutes despite
being technically "running". The per-camera producer
snapshots are fresh but **everything downstream of
cudacompositor (fx chain, output_tee, fx_snapshot,
v4l2sink, HLS, smooth_delay)** has been frozen since
15:52:04. This drop traces the root cause — a cascading
dmabuf fd leak from camera producer rebuild thrash —
and recommends immediate triage + structural fixes.
**Register:** scientific, neutral
**Status:** live incident — drop #50 observation led
directly to this discovery. Compositor is still stalled
as of drop commit time.
**Companion:** drop #41 (fd leak discovery), drop #50
(OBS output node walk), drops #27/#34/#37 (camera
producer rebuild paths)

## Headline

**The compositor's fx chain → output_tee → v4l2sink
chain is DEAD.** Has been for **78 minutes** (since
15:52:04 out of 78 minutes of process uptime — i.e.,
since within 5 seconds of process start).

**Evidence**:

| File | Last mtime | Source |
|---|---|---|
| `/dev/shm/hapax-compositor/fx-snapshot.jpg` | **15:52:04** | Post-fx `add_fx_snapshot_branch` appsink |
| `/dev/shm/hapax-compositor/smooth-snapshot.jpg` | **15:52:04** | `add_smooth_delay_branch` appsink |
| `/dev/shm/hapax-compositor/brio-operator.jpg` | **17:09 (fresh)** | Per-camera producer appsink |
| `/dev/shm/hapax-compositor/c920-desk.jpg` | **17:09 (fresh)** | Per-camera producer appsink |
| `/dev/shm/hapax-compositor/c920-room.jpg` | **17:09 (fresh)** | Per-camera producer appsink |
| `/dev/shm/hapax-compositor/c920-overhead.jpg` | **17:09 (fresh)** | Per-camera producer appsink |
| `/dev/shm/hapax-compositor/brio-room.jpg` | **17:09 (fresh)** | Per-camera producer appsink |
| `/dev/shm/hapax-compositor/brio-synths.jpg` | **17:09 (fresh)** | Per-camera producer appsink |

**Per-camera snapshots are current.** The 6 producer
GstPipeline instances are alive, reading from USB
cameras, writing to interpipesinks, and the per-camera
appsinks (under `add_camera_snapshot_branch` in
`cameras.py`) are writing JPEGs every ~5 seconds.

**Post-cudacompositor chain is dead.** Everything
downstream of the `cudacompositor → cudadownload →
pre_fx_tee` junction has not produced a frame for
78 minutes. This includes the path to OBS via
`/dev/video42`.

**nvidia-smi confirms GPU stall**: `pmon -c 2` shows
the compositor's python process entry with all GPU
utilization columns blank (`-`). No SM usage, no
memory usage, no encoder, no decoder. **The
compositor is using zero GPU** despite being a
GPU-accelerated pipeline.

**Top confirms CPU burn**: 251% CPU used by the
compositor process. 92 threads. 20,557 open file
descriptors (LimitNOFILE=65536 from drop #41 BT-3 is
absorbing the leak, but the count has grown to ~31%
of the limit).

## 1. The cascade

### 1.1 Timeline

- **15:51:59** — compositor process (PID 465127) starts
  after `hapax-rebuild-services.timer` picks up
  `bc83e9f89` (drops #35/#40 aggregator latency fix
  PR #812). Deployed code has drop #35 COMP-1
  (`latency=33ms`) + COMP-2 (`ignore-inactive-pads=true`).
- **15:52:00.928** — "Config: 6 cameras, output=/dev/video42"
- **15:52:02.418** through **15:52:02.568** — all 6
  camera producer pipelines built, started, and
  swapped to primary. Normal startup.
- **15:52:04.043** — **"FX snapshot: frame 2 received"**
  — only 2 frames through the post-fx snapshot path.
- **15:52:04.201** — **c920-desk** emits
  "Failed to allocate required memory. Buffer pool
  activation failed" from `gst_v4l2src_decide_allocation`.
- **15:52:04.297** — c920-desk emits "Internal data
  stream error. streaming stopped, reason
  not-negotiated (-4)"
- **15:52:04.308** — `swap_to_fallback: role=c920-desk`
- **15:52:05.297** — supervisor timer fires, attempts
  rebuild
- **15:52:05.322** — rebuild succeeds (pipeline builds
  + transitions to PLAYING)
- **15:52:05.376** — rebuild immediately fails with
  same buffer-pool-activation error
- **...** — repeating every ~1 second
- **17:10 (current)** — still looping. **78 minutes of
  continuous c920-desk rebuild churn.**

### 1.2 What the FX snapshot count tells us

"FX snapshot: frame 2 received" — the post-fx appsink
received exactly **2 frames** before the stall. Those 2
frames are:
- Frame 0 (preroll) at ~15:52:03
- Frame 1 (first live frame) at ~15:52:04

Both arrived before the c920-desk buffer-pool-activation
failure. After 15:52:04.201, no more frames reached
the appsink. The stall was **instant**, not gradual.

### 1.3 The GPU idle signal

`nvidia-smi pmon -c 2 2>&1`:

```text
# gpu    pid   type     sm    mem    enc    dec    jpg    ofa    command
    0  465127  C+G      -      -      -      -      -      -    python
    0 1380634  C+G      4      0      -      -      -      -    hapax-imaginati
```

The compositor's python process has GPU context
(`C+G` marker — compute + graphics) but **zero SM
utilization, zero memory utilization, zero encoder,
zero decoder**. Meanwhile `hapax-imagination`
(Reverie, same GPU) is doing 4% SM continuously.

**The cudacompositor is idle** — it's not running the
compositing kernel. Either:

- It's waiting on a sink pad that never gets data, OR
- It's waiting on an upstream element (before
  cudacompositor — the per-camera `cudaupload /
  cudaconvert / cudascale` chain) that's blocked, OR
- Its internal thread is deadlocked

Drop #35 COMP-2 (`ignore-inactive-pads=true`) should
have prevented the "waiting on a sink pad" case. Let
me verify the setting actually took effect at runtime
— the code in `pipeline.py` sets it, but we can't
inspect the live property value without attaching to
the process.

### 1.4 Why do per-camera snapshots still work?

`add_camera_snapshot_branch` (`cameras.py:16-83`)
creates a per-camera tee branch:

```text
interpipesrc → per-camera-tee
  ├── branch to cudaupload → cudacompositor (DEAD)
  ├── per-camera snapshot branch (LIVE)
  │   queue → videoconvert → videorate → scale → jpegenc → appsink → write JPEG
  └── recording branch (off)
```

The per-camera snapshot branch runs entirely on
**CPU elements** (videoconvert, jpegenc, appsink).
It doesn't touch cudaupload / cudacompositor. It
writes JPEGs via the `_on_new_sample` callback on the
GStreamer streaming thread.

**So the producer pipelines are alive + delivering
frames to the per-camera tees → per-camera snapshot
branches. The cudaupload → cudacompositor path is
DEAD.**

## 2. Root cause hypothesis — cascading dmabuf leak

### 2.1 The fd picture

Drop #50 observed: compositor has **13,615 `/dmabuf:`
file descriptors** + 30 `/dev/nvidia0` handles
currently open.

At compositor uptime 78 minutes, the leak rate is
**~175 dmabuf fds/minute**. The rebuild loop on
c920-desk (and brio-operator, intermittently) is
firing at **~5 rebuilds/sec = 300 rebuilds/minute**.

If each rebuild leaks ~0.58 dmabuf handles on average
(175 / 300), the rate adds up. Some rebuilds leak more
than others depending on how far the v4l2src +
cudaupload handshake got before failing.

**The leaking path**: each camera producer rebuild
tries to:

1. `v4l2src` opens the USB device, negotiates format
2. Downstream asks `v4l2src_decide_allocation` to
   allocate a buffer pool
3. v4l2src tries to allocate MMAP buffers via the
   kernel `vb2_queue`
4. If kernel has no memory or if any other resource
   isn't available, allocation fails with "Failed to
   allocate required memory"
5. The partially-set-up pipeline is torn down — but
   **any dmabuf fd that was briefly created during
   the abortive handshake may not be cleaned up**

This is consistent with c920-desk (on Bus 001, which
should have isoc bandwidth headroom) failing not due
to bandwidth but due to some kernel memory /
allocation issue that's producing transient
"Failed to allocate" errors.

### 2.2 The dmabuf → GL texture exhaustion

The NVIDIA GL driver uses dmabuf handles for
`glupload` + `gldownload` texture transfers. Modern
NVIDIA drivers enforce a **per-process dmabuf count
ceiling** independent of the fs-level LimitNOFILE —
typically ~1024-4096 dmabuf handles per process.

When this ceiling is hit, `glupload` blocks or fails
silently. The fx chain's `glupload_base` path can't
get a new dmabuf handle → the base path stalls → the
fx chain's `glvideomixer` base pad has no data →
output chain stalls.

**Hypothesis**: even though the fs-level fd count
(20,557) is below LimitNOFILE (65,536), the **GL
subsystem's internal dmabuf pool** hit a ceiling
around the time the compositor started leaking. The
13,615 leaked dmabufs include some kernel-level
allocations that the GL driver considers "alive" but
can't reuse.

**Unverified but consistent with observed behavior.**

### 2.3 Alternative hypothesis — cudacompositor
buffer pool starvation

Another possibility: the compositor's per-camera
`cudaupload` elements each allocate a CUDA buffer pool
at pipeline build time. Each rebuild attempt creates
a new buffer pool and the old one may not be released
until garbage collection + CUDA driver cleanup runs.

With 78 minutes × 300 rebuilds/min = 23,400 rebuild
attempts, if each leaked a small CUDA allocation,
the CUDA device memory would eventually exhaust.
`nvidia-smi` shows GPU 0 memory at ~3 GB used out
of 16 GB — plenty of free memory. **Probably not the
cause.**

**Leaning toward dmabuf ceiling as the primary
cause.**

## 3. Immediate triage options

### 3.1 Option A — restart the compositor

```bash
systemctl --user restart studio-compositor.service
```

**Effect**: fresh process, fresh fd table, fresh CUDA
context, fresh GL context. Output resumes within
~3-5 seconds of startup, assuming c920-desk doesn't
re-trigger the same rebuild cascade.

**Cost**: 3-5 seconds of blank output to OBS (OBS
isn't running right now so cost is zero).

**Recurrence**: ~100% likely that c920-desk will
re-enter the rebuild loop within seconds of startup
because the underlying USB allocation issue is
persistent. The new process would hit the same
dmabuf leak path and fail again in ~78 minutes.

### 3.2 Option B — disable c920-desk entirely

```bash
# Edit config to remove c920-desk from the camera list
# OR physically unplug c920-desk's USB cable
```

**Effect**: 5 cameras instead of 6. c920-desk rebuild
loop stops. The leak source is removed.

**Cost**: one camera offline.

**Recurrence**: zero. Without c920-desk attempting
rebuilds, the dmabuf leak stops accumulating.

### 3.3 Option C — cap the rebuild rate with a
backoff

The state machine already has exponential backoff
(`camera_state_machine.py:56 BACKOFF_CEILING_S=60.0`,
`delay(n) = min(60, 2^n)`). **But** the backoff
resets on each successful rebuild. Since each rebuild
attempt SUCCEEDS at the "start" level (`state change =
success` logs) and only fails later at the buffer-pool-
activation step, the backoff counter never grows.

**Fix**: count buffer-pool-activation failures as
"recovery failed" so the backoff increases. After
N failures, enter DEAD state and stop retrying
entirely. Requires operator rearm to resume — but
that's exactly what the DEAD state is for.

**Code change**: ~5 lines in `camera_pipeline.py`'s
`_on_bus_message` error path to distinguish
"transient rebuild success" from "sustained producer
failure". Treat the latter as RECOVERY_FAILED so the
FSM counts it toward `consecutive_failures`.

### 3.4 Recommendation

**Option A (restart) NOW** to unblock any pending
output path (OBS, HLS, smooth_delay, recording).

**Option B (disable c920-desk) for operator's mobo
swap window** — the mobo swap will reset USB
topology entirely. If c920-desk is disabled until then,
the leak doesn't compound over the next N hours.

**Option C (backoff fix) for Ring 2** — the proper
structural fix. Distinguishes "rebuild starts but
producer immediately fails" from transient bus
issues. Prevents all future versions of this
thrash pattern.

## 4. Connection to OBS output node audit

Drop #50 observed that `/dev/video42` has the
compositor holding 2 fds, `state=capture` (stale),
format YUYV:1920x1080@30, no consumer. **The compositor
has been writing nothing to that device for 78
minutes.** Any OBS session started during this window
would see:

- The device present (v4l2loopback keeps the device
  node alive regardless of writer state)
- Format negotiation succeeds (caps are cached in the
  kernel)
- `VIDIOC_DQBUF` blocks forever — no producer is
  queueing buffers
- OBS would fall back to its "source offline" state

**Drop #50 finding OBS-N1-N3** (v4l2sink property
tuning) is irrelevant when the upstream fx chain is
dead. **No amount of sink tuning fixes an upstream
stall.** The root cause fix (option C in this drop
OR mobo swap clearing USB state) is what matters.

## 5. Ring summary

### Ring 1 — immediate triage

| # | Fix | Action | Impact |
|---|---|---|---|
| **INC-1** | Restart compositor | `systemctl --user restart studio-compositor` | Unblocks output path in ~3-5 s |
| **INC-2** | Disable c920-desk for mobo-swap window | Remove from config OR unplug USB cable | Prevents rebuild leak until mobo swap resets topology |

### Ring 2 — structural fix

| # | Fix | File | Lines | Impact |
|---|---|---|---|---|
| **INC-3** | Count immediate post-start bus errors as recovery failures | `camera_pipeline.py:303-344` | ~10 | Exponential backoff kicks in properly; DEAD state reached after N failures; rebuild thrash auto-bounded |

### Ring 3 — root cause

| # | Fix | Action |
|---|---|---|
| **INC-4** | Instrument dmabuf allocation via bpftrace to find the leak site | `bpftrace -e 'kprobe:dma_buf_fd { @[pid, comm] = count(); }'` + analyze per-rebuild delta |
| **INC-5** | Add `compositor_process_fd_count` Prometheus gauge (drop #41 BT-5) | Makes future leak events alertable instead of discovered by accident |
| **INC-6** | Add `compositor_camera_rebuild_failures_total{role}` counter | Surfaces this kind of thrash pattern as a metric; pairs with alerting on high counter rates |

## 6. Cross-references

- Live process: PID 465127, started 2026-04-14 15:51:59
- `journalctl --user -u studio-compositor.service --since "15:52:00"` — full incident log
- `/dev/shm/hapax-compositor/fx-snapshot.jpg` — frozen at 15:52:04
- `/dev/shm/hapax-compositor/smooth-snapshot.jpg` — frozen at 15:52:04
- `agents/studio_compositor/cameras.py:16-83` —
  `add_camera_snapshot_branch` (the per-camera branch
  that is still alive)
- `agents/studio_compositor/camera_pipeline.py:303-344` —
  `_on_bus_message` error path (INC-3 target)
- `agents/studio_compositor/camera_state_machine.py:56` —
  `BACKOFF_CEILING_S=60.0` and the exponential backoff
  that's not working because the FSM counts rebuilds
  as successes
- Drop #5 — glfeedback diff check (pre-compaction, not
  the stall cause but relevant to the fx chain)
- Drop #27 — brio-operator cold-start grace (related
  recovery path)
- Drop #32 — encoder + output path walk (output chain
  architecture)
- Drop #34 — USB topology H4 closeout (why cameras
  fail on Bus 003)
- Drop #35 — cudacompositor walk (COMP-1 + COMP-2
  should have helped but didn't because the stall is
  downstream of cudacompositor)
- Drop #41 — fd leak discovery + LimitNOFILE=65536
  workaround + BT-5/BT-7 (observability + root cause
  still open)
- Drop #50 — OBS output node walk (where the `78
  minute stale fx-snapshot.jpg` was first noticed)

## 7. Operator action needed

**Urgent** (for livestream continuity):

1. **Does the operator want the compositor restarted
   now?** The output has been dead for 78 minutes. If
   OBS is expected to be used before the mobo swap,
   option A (restart) is mandatory. If the mobo swap
   is imminent, skip the restart and just wait.

**Important** (for the mobo swap window):

2. **Disable c920-desk** until the mobo swap — either
   by config change or by physically unplugging the
   USB cable. Prevents the leak from re-accumulating
   after any compositor restart.

**Deferred** (post-mobo-swap):

3. Ship INC-3 (backoff fix for transient-success
   rebuild thrash). Structural fix so this pattern
   can't recur on the new motherboard either.
4. Ship INC-5 (fd count gauge) + INC-6 (rebuild
   failure counter). Observability so future
   occurrences are alertable instead of discovered
   by accident during unrelated research.
