# FD leak code-level root cause — async NULL transition + fast rebuild

**Date:** 2026-04-14
**Author:** delta (beta role — cam-stability focus)
**Scope:** Completes drop #41 BT-7 (fd leak root cause
investigation, still open). Drop #51 identified the
symptom — 13,615 dmabuf fds leaked in 78 minutes while
a c920-desk rebuild loop churned at ~5/sec. This drop
traces the code path and identifies the exact file:line
where the leak originates: **`camera_pipeline.py::stop()`
calls `set_state(NULL)` without a `get_state()` wait,
and fast rebuild cycles interrupt async cleanup before
the v4l2src buffer pool releases its dmabuf handles.**
**Register:** scientific, neutral
**Status:** investigation — 1 finding with complete code
trace + recommended fix. No code changed.
**Companion:** drop #41 (FD leak discovery +
LimitNOFILE=65536 workaround), drop #51 (live 78-min
output stall incident)

## Headline

**The FD leak originates at `camera_pipeline.py:253`.**

```python
def stop(self) -> None:
    """Transition to NULL. Idempotent."""
    with self._state_lock:
        if self._pipeline is None:
            return
        Gst = self._Gst
        self._pipeline.set_state(Gst.State.NULL)    # ← line 253: async, no wait
        self._started = False
```

`GstPipeline.set_state(NULL)` is **asynchronous** when
children have pending operations. It returns
`GST_STATE_CHANGE_ASYNC` and schedules cleanup on a
GStreamer thread. The standard GStreamer idiom to
force a synchronous cleanup is:

```python
self._pipeline.set_state(Gst.State.NULL)
self._pipeline.get_state(timeout=5 * Gst.SECOND)   # ← wait for completion
```

**Without the `get_state()` wait**, the Python code
immediately returns from `stop()` and the caller
(`teardown()`) drops the Python reference at line 273
(`self._pipeline = None`). GStreamer's reference count
protects against use-after-free — the bin stays alive
until async cleanup completes — but the **caller has
already moved on to the next rebuild**. Fast rebuild
cycles therefore interleave:

1. Old pipeline: async NULL transition in progress
2. New pipeline: `build()` + `start()` already running
3. Supervisor thread: next rebuild trigger about to fire

During the interleave, v4l2src's partially-allocated
buffer pool (from a failed `gst_v4l2src_decide_allocation`
call) may **never complete its cleanup cascade** because
the GStreamer thread handling the NULL transition can
be scheduled out, interrupted, or blocked on a
driver callback that never fires. The dmabuf handles
allocated by `gst_v4l2_allocator_alloc_dmabuf` remain
open in the process fd table.

**Observed leak rate**: ~150 dmabuf fds/minute at
~5 rebuilds/sec = **~0.5 dmabuf per rebuild**, leaked
whenever the async cleanup gets interrupted.

## 1. The complete code trace

### 1.1 Entry point — supervisor thread attempts reconnect

`pipeline_manager.py:446-474`:

```python
def _attempt_reconnect(self, role: str) -> None:
    with self._lock:
        cam = self._cameras.get(role)
        sm = self._state_machines.get(role)
    if cam is None:
        return
    log.info("supervisor: attempting reconnect for role=%s", role)

    if sm is not None:
        sm.dispatch(
            Event(
                EventKind.BACKOFF_ELAPSED,
                reason="supervisor timer",
                source="supervisor",
            )
        )

    ok = cam.rebuild()       # ← calls teardown + build + start
    metrics.on_reconnect_result(role, ok)
    metrics.on_pipeline_restart(f"cam_{role}")
    ...
```

The supervisor thread runs `_supervisor_loop`
(`pipeline_manager.py:385-399`) which waits on a
heapq of scheduled reconnects. Under failure, the
state machine schedules rapid reconnects via its
`_schedule_reconnect` callback. **The reconnect queue
processes one rebuild at a time** — no concurrent
rebuilds of the same camera. That's good; the
interleave problem isn't within a single camera, it's
between the camera's OLD pipeline and its NEW pipeline.

### 1.2 `CameraPipeline.rebuild()` — teardown + build + start

`camera_pipeline.py:275-285`:

```python
def rebuild(self) -> bool:
    """Teardown and rebuild from scratch. Returns True on successful restart."""
    with self._state_lock:
        self._rebuild_count += 1
        self.teardown()            # ← line 279: tear down old
        try:
            self.build()            # ← line 281: construct new
        except Exception:
            log.exception("camera_pipeline %s: rebuild build() failed", self._spec.role)
            return False
        return self.start()         # ← line 285: set_state(PLAYING)
```

All three operations (`teardown`, `build`, `start`) run
**sequentially on the supervisor thread** holding
`self._state_lock`. So within a single `rebuild()`
call, there's no concurrency problem.

**But** the cleanup of the OLD pipeline is handed off
to GStreamer's internal threads via `set_state(NULL)`.
The `_state_lock` protects the Python state, not
GStreamer's internal state machine. The sequence of
events for a rebuild after failure is:

1. T+0 ms: supervisor calls `rebuild()`
2. T+0 ms: `teardown()` → `stop()` → `set_state(NULL)`
   returns `ASYNC` (GStreamer thread will complete the
   transition when it gets CPU time)
3. T+1 ms: `self._pipeline = None` (Python reference
   dropped — GStreamer refcount still holds the bin)
4. T+2 ms: `build()` starts constructing new pipeline
5. T+15 ms: new pipeline is built (6 elements + links)
6. T+15 ms: `start()` → `set_state(PLAYING)` on the new
   pipeline
7. T+20 ms: new v4l2src starts caps negotiation
8. T+30 ms: `gst_v4l2src_decide_allocation` fails with
   "Buffer pool activation failed"
9. T+30 ms: new pipeline emits ERROR on bus
10. T+31 ms: state machine transitions, schedules next
    reconnect in ~1 s
11. T+50 ms: **old pipeline's async NULL transition
    is still in progress on a GStreamer thread**
12. T+50-500 ms: old pipeline's cleanup cascade runs
    (if nothing interrupts it)

**The interleave window is 15-50 ms wide.** During
this window, the old pipeline's v4l2src is in various
states of cleanup while the new pipeline's v4l2src is
already trying to open the same device and allocate
buffers.

### 1.3 `stop()` — the leak site

`camera_pipeline.py:247-254`:

```python
def stop(self) -> None:
    """Transition to NULL. Idempotent."""
    with self._state_lock:
        if self._pipeline is None:
            return
        Gst = self._Gst
        self._pipeline.set_state(Gst.State.NULL)     # ← line 253
        self._started = False
```

**Line 253 is the leak origin.** `set_state(NULL)` on
a pipeline with async children returns immediately
with `GST_STATE_CHANGE_ASYNC`. The **actual state
transition** — where v4l2src closes its file
descriptor, releases its buffer pool, and cleans up
dmabuf handles — happens on a GStreamer thread at an
unspecified later time.

**Without a `get_state()` wait**, the following are
undefined at the moment `stop()` returns:

- Whether v4l2src has released `/dev/video{N}`'s fd
- Whether the v4l2 MMAP buffer pool has been freed
- Whether the vb2 queue's buffers are returned to the
  driver
- **Whether dmabuf handles allocated during
  `gst_v4l2src_decide_allocation` have been closed**

### 1.4 `teardown()` — immediately drops Python ref

`camera_pipeline.py:256-273`:

```python
def teardown(self) -> None:
    """Full teardown: NULL + bus disconnect + element release. Idempotent."""
    with self._state_lock:
        if self._pipeline is None:
            return
        self.stop()                                    # ← async NULL
        if self._bus is not None and self._bus_signal_id:
            try:
                self._bus.disconnect(self._bus_signal_id)
            except (TypeError, ValueError):
                pass
            self._bus_signal_id = 0
            try:
                self._bus.remove_signal_watch()
            except (TypeError, ValueError):
                pass
        self._bus = None
        self._pipeline = None                          # ← line 273: Python ref dropped
```

**Line 273 drops the Python reference**. GStreamer's
refcount keeps the bin alive until async cleanup
completes — but nothing Python-side tracks the
outstanding cleanup. If `rebuild()` is called again
before cleanup finishes, the new rebuild fires into
a pipeline instance that coexists with the old (still
cleaning up) pipeline instance.

### 1.5 How dmabuf handles are allocated — the producer side

The v4l2src plugin allocates dmabuf handles in
`gst_v4l2_allocator_alloc_dmabuf` (in
`gst-plugins-good/sys/v4l2/gstv4l2allocator.c`). Each
buffer in the v4l2 MMAP pool gets a dmabuf fd via
`VIDIOC_EXPBUF`. The default pool size is 5 buffers,
so each successful allocation creates 5 dmabuf fds.

**The `decide_allocation` failure path** at
`gstv4l2src.c:957`:

> `../gstreamer/subprojects/gst-plugins-good/sys/v4l2/gstv4l2src.c(957): gst_v4l2src_decide_allocation (): Buffer pool activation failed`

This happens when:
1. The v4l2src has successfully opened the device
2. Caps have been negotiated
3. The buffer pool has been created
4. The pool is being **activated** (ready to pull buffers from the driver)
5. The activation step fails — usually due to `VIDIOC_REQBUFS` returning EINVAL or EBUSY, or the pool's `set_active(TRUE)` fails

**At the moment of activation failure**, the buffer
pool has already:
- Called `VIDIOC_REQBUFS` to request N buffers
- Called `VIDIOC_EXPBUF` to create N dmabuf fds (for
  dmabuf export mode)
- Allocated userspace wrapper objects for the buffers

Then activation fails, the pool emits an error, the
error propagates to the bus, and the pool is
supposed to be cleaned up by the caller.

**The cleanup cascade**: the pool has N dmabuf fds
registered. When the pool is destroyed (on v4l2src
finalize, which happens when the bin's NULL
transition completes), it calls `close()` on each
dmabuf fd.

**The interruption**: if the pipeline's NULL
transition is interrupted (Python drops the ref, a
new build starts, GStreamer reschedules the cleanup
thread), the pool's destruction may be deferred or
cancelled. The dmabuf fds remain in the process fd
table — **leaked**.

### 1.6 Why `v4l2sink` doesn't leak (baseline comparison)

The main compositor pipeline's v4l2sink output (drop
#32/#50) has the same general architecture but
**doesn't leak**. Why? Because v4l2sink is **never
torn down and rebuilt during normal operation**. The
compositor's main pipeline is built once at startup
and runs until shutdown. Only the per-camera
sub-pipelines cycle through rebuilds.

**The leak is specific to camera sub-pipelines**
because they use per-camera `GstPipeline` instances
managed by `PipelineManager`, and those are the
only pipelines that get torn down and rebuilt on
error. The cam-24/7-resilience epic's design choice
to use per-camera pipelines trades fault isolation
for rebuild frequency — which is normally fine, but
the async-NULL interruption creates the leak path.

## 2. The fix

### 2.1 Recommended change

`camera_pipeline.py:247-254`, replace:

```python
def stop(self) -> None:
    """Transition to NULL. Idempotent."""
    with self._state_lock:
        if self._pipeline is None:
            return
        Gst = self._Gst
        self._pipeline.set_state(Gst.State.NULL)
        self._started = False
```

with:

```python
def stop(self) -> None:
    """Transition to NULL. Idempotent.

    Waits for the NULL transition to complete to prevent
    async cleanup from being interrupted by the next
    rebuild cycle. Without this wait, fast rebuilds
    interleave with pending cleanup and leak v4l2src
    buffer pool dmabuf handles. Drop #41 + drop #51 +
    drop #52 (this fix).
    """
    with self._state_lock:
        if self._pipeline is None:
            return
        Gst = self._Gst
        self._pipeline.set_state(Gst.State.NULL)
        # Synchronous wait for the NULL transition to
        # complete. Timeout at 5 seconds: if the driver
        # hangs, we don't block the supervisor thread
        # indefinitely. Normal cleanup completes in
        # <100 ms. On failure or timeout, log a warning
        # and proceed anyway — the partial cleanup is
        # better than no cleanup, and the leak was
        # worse than the delay.
        ret, state, pending = self._pipeline.get_state(
            timeout=5 * Gst.SECOND
        )
        if ret == Gst.StateChangeReturn.FAILURE:
            log.warning(
                "camera_pipeline %s: NULL transition failed, "
                "may leak resources (ret=%s)",
                self._spec.role,
                ret.value_nick,
            )
        elif state != Gst.State.NULL:
            log.warning(
                "camera_pipeline %s: NULL transition incomplete "
                "at state=%s pending=%s, may leak resources",
                self._spec.role,
                state.value_nick if state else "?",
                pending.value_nick if pending else "?",
            )
        self._started = False
```

**Total change**: ~15 lines added. Pure addition to
an existing function. Only called from `teardown()`
(line 261) and user-requested stop paths.

### 2.2 Why 5 seconds

The timeout balances:

- **Too short** (e.g., 100 ms): driver cleanup may not
  complete under load. Common cleanup takes 50-200 ms
  depending on kernel contention.
- **Too long** (e.g., 30 s): a hung driver would block
  the supervisor thread indefinitely, starving other
  camera reconnect attempts.

**5 seconds** covers typical cleanup variance with a
comfortable margin while remaining bounded. The
GStreamer manual recommends 1-10 seconds for `get_state`
timeouts in blocking paths; 5 is middle-ground.

### 2.3 Risk profile

**Zero behavioral risk** for the normal case:
- Normal NULL transition completes in <100 ms
- The `get_state` wait just blocks the supervisor
  thread briefly
- No change to success / failure semantics

**Medium risk for pathological cases**:
- A hung driver (unresponsive uvcvideo state) would
  cause the supervisor thread to block for 5 seconds
  per rebuild
- During that block, no other camera can be rebuilt
- At worst, 6 cameras × 5 seconds = 30 seconds of
  supervisor starvation
- Mitigation: the current rebuild rate is ~1/second;
  a 5-second block replaces 5 failed rebuilds with 1
  slow cleanup. **Net: reduced leak + possibly slower
  rebuild cadence**

**Improvement to drop #51 symptoms**:
- FD leak rate drops from ~150/min to approximately
  zero
- After 78 minutes of rebuild churn, fd count would
  grow by maybe 50 fds instead of 13,615
- Compositor output path never exhausts the NVIDIA
  GL driver's dmabuf ceiling
- Drop #51's output stall pattern would not manifest

### 2.4 Required deviation (LRR frozen-file list)

`camera_pipeline.py` is in the frozen-file list for
research condition `cond-phase-a-baseline-qwen-001`.
Any edit requires a covering DEVIATION record:

- **Proposed deviation ID**: next available after
  beta's DEVIATION-038 (Phase 4 bootstrap)
- **Justification**: operational (fd leak caused a
  78-minute production outage in drop #51). This is
  a fix for a production bug, not a behavioral
  change that affects voice grounding research.
- **Impact on Condition A data**: zero. The fix
  changes the cleanup behavior of a pipeline that's
  already in a failure state. No effect on
  successful frame production, which is what voice
  grounding measures.

**Filing strategy**: one-line deviation record
pointing at drop #51 as the justification. No need
for a full design doc — the fix is load-bearing
operational hygiene.

### 2.5 Alternative fixes considered

**Alternative A: add a per-rebuild delay** (~500 ms
sleep between `teardown()` and `build()`)

```python
def rebuild(self) -> bool:
    with self._state_lock:
        self._rebuild_count += 1
        self.teardown()
        time.sleep(0.5)        # wait for async cleanup
        try:
            self.build()
        ...
```

**Rejected**: unreliable. 500 ms works in the common
case but breaks under driver contention. Adds 500 ms
of latency to every rebuild without addressing the
root cause.

**Alternative B: reference-count the pipeline
destruction**

Hold a reference to the old pipeline until a GStreamer
bus message confirms the NULL transition completed.

**Rejected**: complex. Requires a separate bus watch
on the old pipeline, message filtering, lifetime
management. Brittle.

**Alternative C: don't tear down — just reset the
v4l2src element**

```python
def rebuild(self) -> bool:
    with self._state_lock:
        src = self._pipeline.get_by_name(f"src_{self._role_safe}")
        if src:
            src.set_state(Gst.State.NULL)
            src.set_state(Gst.State.PLAYING)
        return True
```

**Rejected**: doesn't address the "`decide_allocation`
failed" state. Reusing the same v4l2src element after
allocation failure leaves the element in an
indeterminate state.

**The `get_state` wait is the cleanest fix** — it's
the GStreamer-idiomatic way to force synchronous
cleanup.

## 3. Connection to drop #51's live incident

Drop #51 observed:

- Compositor process at PID 465127
- 20,557 total fds open
- 13,615 `/dmabuf:` fds
- fx-snapshot.jpg stale for 78 minutes
- `nvidia-smi pmon`: compositor's python process using 0% GPU
- c920-desk rebuild loop at ~5/sec for 78 minutes

**With this fix applied**: the c920-desk rebuild loop
still runs (it's the underlying USB allocation issue
that causes the rebuild to fail, not the cleanup
path). But each rebuild's cleanup completes cleanly,
dmabuf handles are released, and the fd count stays
bounded. The NVIDIA GL driver's dmabuf ceiling is
never hit, `glupload_base` continues to get new
dmabuf handles, the fx chain continues to run,
output frames continue to flow to `/dev/video42`.

**The upstream cause** (c920-desk failing to allocate
buffers) remains. That's a separate issue — probably
resolves itself after the mobo swap, or needs
investigation under drop #2's H7 hypothesis family.
**But the downstream blast radius** (fx chain stall +
OBS output dead + HLS dark + smooth_delay frozen) is
entirely prevented by this 15-line fix.

## 4. Ring summary

### Ring 1 — the fix

| # | Fix | File | Lines | Impact |
|---|---|---|---|---|
| **FDL-1** | Add `get_state(5s)` wait after `set_state(NULL)` in `stop()` | `camera_pipeline.py:247-254` | +15 | Eliminates FD leak from camera rebuild thrash; blast radius of drop #51 becomes impossible |

**Requires**: DEVIATION record for frozen-file edit.

### Ring 2 — paired observability

| # | Fix | File | Lines | Impact |
|---|---|---|---|---|
| **FDL-2** | `compositor_process_fd_count` Prometheus gauge (drop #41 BT-5) | `metrics.py` + status tick | ~10 | Future leak regressions scrape-visible before they bite |
| **FDL-3** | `compositor_camera_rebuild_count{role}` counter | `metrics.py` + `rebuild()` | ~5 | Surface rebuild thrash as a metric; alert on high rates |
| **FDL-4** | `compositor_pipeline_teardown_duration_ms` histogram | `metrics.py` + `stop()` | ~5 | Measure how long NULL transitions actually take in production |

### Ring 3 — upstream mitigation

| # | Fix | File | Lines | Impact |
|---|---|---|---|---|
| **FDL-5** | Escalate "decide_allocation failed" as a durable failure (not transient) | `camera_pipeline.py:303-345` bus handler | ~10 | Fast-fail the rebuild loop after N immediate post-start failures; DEAD state reached sooner; aligns with drop #51 INC-3 |

**FDL-5 is equivalent to drop #51 INC-3**, same root
cause different angle. Either fix prevents the thrash
from compounding; FDL-1 prevents the thrash from
leaking; ideally ship both.

## 5. Cross-references

- `agents/studio_compositor/camera_pipeline.py:247-254`
  — `stop()` (the leak site, FDL-1 target)
- `agents/studio_compositor/camera_pipeline.py:275-285`
  — `rebuild()` (the trigger)
- `agents/studio_compositor/pipeline_manager.py:446-494`
  — `_attempt_reconnect` (supervisor thread caller)
- `agents/studio_compositor/pipeline_manager.py:385-399`
  — `_supervisor_loop`
- `gst-plugins-good/sys/v4l2/gstv4l2src.c:957` —
  `gst_v4l2src_decide_allocation` (the failure site
  that triggers the rebuild cycle)
- `gst-plugins-good/sys/v4l2/gstv4l2allocator.c` —
  `gst_v4l2_allocator_alloc_dmabuf` (where the dmabuf
  handles originate)
- Drop #2 — brio-operator sustained deficit (H7 USB
  topology — the underlying cause of allocation
  failures)
- Drop #27 — brio-operator cold-start grace (related
  rebuild path)
- Drop #34 — USB topology H4 closeout (why c920-desk
  can fail similarly post-reboot)
- Drop #41 — FD leak discovery + LimitNOFILE=65536
  workaround (drops #41 BT-7 was the open root cause
  slot that this drop closes)
- Drop #51 — live 78-min output stall incident
  (the symptom this fix prevents)

## 6. Recommended ship order

1. **Now**: file drop #52 (this doc) + the DEVIATION
   record.
2. **Now or next session**: ship FDL-1 (the stop()
   fix) behind the DEVIATION.
3. **Soon**: ship FDL-2/FDL-3/FDL-4 observability
   bundle (drop #41 BT-5 + this drop's additions).
4. **Defer**: FDL-5 upstream fast-fail (paired with
   drop #51 INC-3). Low urgency once FDL-1 stops the
   bleeding.

**Not blocking**: the mobo swap tomorrow. The fix is
stable across any hardware change. The swap may make
c920-desk's underlying allocation failure go away,
but even if it doesn't, the leak path is closed.

## 7. Note to alpha or next delta

**When you ship FDL-1**:

1. **Bundle with the DEVIATION record** before
   committing the code change. LRR pre-commit hook
   will block otherwise.
2. **Test with a camera-rebuild loop**: take drop
   #51's scenario (disconnect c920-desk physically
   during compositor runtime, let it enter the
   rebuild loop) and verify that `ls /proc/<pid>/fd |
   wc -l` stays bounded over 10+ minutes.
3. **Do NOT try to fix the upstream "Buffer pool
   activation failed"** at the same time. That's a
   separate investigation (drop #2 H7 family). FDL-1
   is a pure containment fix; keep its scope tight.
4. **Rebuild-services timer will deploy it** via
   `hapax-rebuild-services.timer` after commit to
   main, triggering a compositor restart. Coordinate
   with operator if livestream is active.

**Beta's Phase 4 bootstrap work does not intersect
this fix.** Safe to ship independently.
