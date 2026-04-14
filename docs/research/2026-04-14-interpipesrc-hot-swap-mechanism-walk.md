# interpipesrc hot-swap mechanism + consumer queue audit

**Date:** 2026-04-14
**Author:** delta (beta role — cam-stability focus)
**Scope:** Systematic walk of the `interpipesrc` hot-swap
mechanism — the runtime code path that swaps a consumer
from the primary camera producer to the fallback, or
back. Drops #28-#30 covered producers; drops #35 + #36
covered the composite and orchestration layers. This
drop covers the seam between them: the specific
GStreamer mechanism that handles camera failures
transparently to the composite pipeline.
**Register:** scientific, neutral
**Status:** investigation — 4 findings focused on
interpipesrc property defaults, swap latency, and
observability. No code changed.
**Companion:** drops #28 (camera pipeline walk), #35
(cudacompositor internals), #36 (threading model)

## Headline

**The hot-swap is literally one line:**
`src.set_property("listen-to", target_sink_name)`
(`pipeline_manager.py:183, 207`). That property write
is the entire swap operation from the council side —
the `interpipesrc` plugin handles unhooking from the
old sink, subscribing to the new sink, caps
renegotiation, and first-buffer delivery internally.

**Four findings:**

1. **`interpipesrc` has unset queue bounds for
   720p MJPEG-derived NV12 frames.** The default
   `max-bytes=200000` (200 KB) is smaller than a
   single NV12 720p frame (1.4 MB). Combined with
   `max-buffers=0` (unlimited) and `max-time=0`
   (unlimited), the queue is bounded by the
   byte cap alone, which is always instantly
   exceeded. The plugin's behavior under this
   condition depends on `leaky-type` (default
   `none`) — worth explicitly setting for
   deterministic semantics.
2. **`interpipesrc.dropped` is a readable counter
   that is never scraped.** Per-consumer dropped
   buffers is a first-class signal for swap-related
   frame loss, and it's free to expose — no element
   modification needed.
3. **Swap runs via `GLib.idle_add`** rather than
   inline. `_idle_swap_to_fallback` and
   `_idle_swap_to_primary` are enqueued on the main
   loop from state machine callbacks, adding up to
   ~33 ms of latency (the next main loop iteration
   at default priority) before the swap actually
   fires. For fallback recovery this is acceptable;
   for primary-on-recovery swaps it extends the
   fallback-active window.
4. **`automatic-eos=true` is the default** but is
   not explicitly set. For a hot-swap consumer, an
   EOS from one interpipesink should NOT propagate
   downstream (it would cascade through the composite
   pipeline). Explicitly setting
   `automatic-eos=false` is defensive — today the
   council relies on the default which is the wrong
   direction.

## 1. The hot-swap as written

`agents/studio_compositor/pipeline_manager.py:176-209`:

```python
def swap_to_fallback(self, role: str) -> None:
    with self._lock:
        src = self._interpipe_srcs.get(role)
        fb = self._fallbacks.get(role)
    if src is None or fb is None:
        return
    src.set_property("listen-to", fb.sink_name)
    metrics.on_swap(role, to_fallback=True)
    log.info("swap_to_fallback: role=%s → %s", role, fb.sink_name)
    # W5 NEW: dispatch SWAP_COMPLETED back into the FSM so DEGRADED
    # advances to OFFLINE and the supervisor schedules a rebuild.
    ...

def swap_to_primary(self, role: str) -> None:
    with self._lock:
        src = self._interpipe_srcs.get(role)
        cam = self._cameras.get(role)
    if src is None or cam is None:
        return
    src.set_property("listen-to", cam.sink_name)
    metrics.on_swap(role, to_fallback=False)
    log.info("swap_to_primary: role=%s → %s", role, cam.sink_name)
```

**Two `set_property` calls are the entire swap
surface.** Everything else is metrics + state machine
plumbing.

### 1.1 What the plugin does internally

When `listen-to` is written:

1. `interpipesrc` unhooks its internal app-source
   queue from the old `interpipesink` node
2. Subscribes to the new node
3. Discards any buffers still queued from the old
   source
4. The new node's buffers start flowing into the
   consumer's internal queue
5. Downstream receives a CAPS event (if
   `allow-renegotiation=true` and caps differ)
6. Downstream receives a SEGMENT event (if
   `stream-sync=restart-ts`)
7. The first buffer from the new source arrives at
   the consumer's src pad

**Latency budget** (theoretical, not measured):

- Steps 1-3: sub-millisecond (property write is
  atomic)
- Step 5: CAPS renegotiation cost varies by
  downstream element — if the downstream chain
  (queue → cudaupload → cudaconvert → cudascale →
  cudacompositor) needs to reconfigure its buffer
  pools, this can take 1-10 ms
- Step 7: up to one frame interval (33 ms at
  30 fps) — the new source produces buffers on its
  own cadence and the first one arrives within
  that window

**Practical worst case: ~40 ms** from the property
write to the first new frame reaching cudacompositor.
During this window, cudacompositor's aggregator
decision matters — with drop #35 finding's
`latency=0` default, a swap-in-progress pad loses
its buffer for that tick. Drop #35 Ring 1 fix COMP-1
(`latency=33_000_000`) directly addresses this.

### 1.2 The `idle_add` indirection

`pipeline_manager.py:350-356`:

```python
def _idle_swap_to_fallback(self, role: str) -> bool:
    self.swap_to_fallback(role)
    return False  # remove idle source

def _idle_swap_to_primary(self, role: str) -> bool:
    self.swap_to_primary(role)
    return False
```

State machine callbacks do not call `swap_*` directly.
Instead they enqueue `_idle_swap_*` onto the GLib main
loop via `idle_add`:

```python
def _swap_fb() -> None:
    self._GLib.idle_add(self._idle_swap_to_fallback, role)
```

**Rationale**: GStreamer property writes should
ideally happen on the thread that owns the element's
GObject lifecycle. The main loop thread is that
owner for the composite pipeline. Dispatching via
`idle_add` ensures the property write happens there,
not on the state machine's invocation thread (which
could be the supervisor thread, a watchdog thread,
or a bus message handler).

**Cost**: up to one main loop iteration of latency.
At default `fx_tick_callback` scheduling (drop #36
finding 3), the main loop is busy every 33 ms, so
the idle callback fires within 0-33 ms of the
enqueue. Acceptable.

**Mitigation if needed**: `GLib.idle_add_full` with
`PRIORITY_HIGH_IDLE` (-100) would schedule the swap
before default-priority callbacks. One-line change
if swap latency ever becomes a measured issue.

## 2. interpipesrc property audit

Council sets 5 properties (`cameras.py:109-113`):

```python
src.set_property("listen-to", f"cam_{role}")
src.set_property("stream-sync", "restart-ts")
src.set_property("allow-renegotiation", True)
src.set_property("is-live", True)
src.set_property("format", Gst.Format.TIME)
```

Everything else defaults. From `gst-inspect-1.0
interpipesrc`:

| Property | Default | Set? | Effect |
|---|---|---|---|
| `accept-eos-event` | true | no | EOS from sink propagates to src → risk of cascade on swap |
| `accept-events` | true | no | All events propagate |
| `allow-renegotiation` | true | **yes (explicit)** | Caps can differ between primary and fallback |
| `automatic-eos` | true | no | **Finding 4** |
| `block` | false | no | `push-buffer` is non-blocking; correct for live |
| `block-switch` | false | no | Switching IS allowed; correct for hot-swap |
| `blocksize` | 4096 | no | N/A (not a byte-based source) |
| `caps` | NULL | no | Accept any caps from the listener |
| `do-timestamp` | false | no | Downstream uses upstream timestamps |
| `emit-signals` | false | no | No need-data / enough-data signals |
| `format` | bytes | **yes (TIME)** | Time-based seeking semantics |
| `handle-segment-change` | false | no | No handling for upstream segment changes |
| `is-live` | false | **yes (true)** | Live-source semantics (no seeking, no pre-roll) |
| `leaky-type` | none | no | **Finding 1** |
| `listen-to` | null | **yes (cam_<role>)** | Subscribes to the named sink |
| `max-bytes` | **200000** | no | **Finding 1** — smaller than one 720p NV12 frame |
| `max-buffers` | 0 (unlimited) | no | **Finding 1** |
| `max-time` | 0 (unlimited) | no | **Finding 1** |
| `max-latency` / `min-latency` | -1 (default) | no | Pipeline-computed |
| `min-percent` | 0 | no | N/A |
| `stream-sync` | — | **yes (restart-ts)** | Resets timestamps on swap |
| `current-level-buffers/bytes/time` | — (read-only) | **never read** | **Finding 2** |
| `dropped` | — (read-only) | **never read** | **Finding 2** |
| `in` | — (read-only) | **never read** | Input buffer counter |

## 3. Findings

### 3.1 Finding 1 — queue bounds for 720p NV12

`max-bytes=200000` (200 KB) is the default byte cap
on interpipesrc's internal queue. One 720p NV12
frame is:

```
1280 × 720 × 1.5 (NV12 bits per pixel) = 1,382,400 bytes ≈ 1.35 MB
```

**200 KB < 1.35 MB**, so one frame does not fit in
the byte cap. With `max-buffers=0` and `max-time=0`,
the byte cap is the only bound; with `leaky-type=none`,
the plugin does not drop buffers when the cap is
exceeded.

**What happens in practice**: `interpipesrc` is an
app-source wrapper, and when the internal queue
exceeds `max-bytes`, the plugin may:

- Block `push-buffer` calls from the upstream
  interpipesink (if upstream is blocking — which
  council's `interpipesink sync=false, async=false`
  deliberately isn't)
- Signal `enough-data` and wait for
  `need-data` callbacks (emit-signals=false, so
  this path is disabled)
- Silently accept buffers beyond the cap (likely
  behavior given the defaults)

**The practical effect**: the byte cap is functionally
ignored because no propagation mechanism is enabled.
The actual queue depth is unbounded, and the only
back-pressure is whatever the consumer downstream
applies (the `queue_comp` 2-buffer leaky queue, drop
#35 finding 1).

**Fix**: set explicit sane bounds.

```python
src.set_property("max-buffers", 5)  # 5 frames of internal cushion
src.set_property("max-bytes", 0)     # don't constrain by bytes
src.set_property("max-time", 5 * 33_000_000)  # 5 × 33 ms = 165 ms
src.set_property("leaky-type", "downstream")  # drop oldest on overflow
```

This makes the internal queue semantics predictable
and matches the downstream `queue_comp` cushion.

### 3.2 Finding 2 — dropped + current-level counters unscraped

`interpipesrc` exposes three readable properties
that give direct visibility into per-consumer swap
health:

- `dropped` — count of buffers the internal queue
  dropped (under `leaky-type=downstream` conditions)
- `in` — count of buffers the consumer received from
  the upstream interpipesink
- `current-level-buffers` / `current-level-bytes` /
  `current-level-time` — instantaneous queue depth

**Not one of these is scraped today.** The metrics
module in drop #36 finding 5's observability gap
list grows by three more per-camera histograms.

**Fix** (ring 3 in this drop): read each interpipesrc
via its Python wrapper in the existing compositor
metric-publish tick. ~20 lines of code per counter,
~60 lines total for all three.

### 3.3 Finding 3 — idle_add adds ~33 ms of swap latency

Discussed in § 1.2 above. **Not a bug — a
deliberate safety pattern.** The cost is bounded
and acceptable.

**Optional mitigation**: upgrade `idle_add` →
`idle_add_full(PRIORITY_HIGH_IDLE, ...)` for swap
callbacks only. Schedules ahead of default-priority
work but still on the main loop. One-line change per
call site (two call sites).

**Not recommended to ship** unless measurement shows
swap-related latency is actually hurting livestream
smoothness — which nothing currently measures (see
finding 2).

### 3.4 Finding 4 — automatic-eos default risks EOS cascade

`automatic-eos=true` is the default. From the
GStreamer docs: "Automatically EOS when the segment
is done." For a hot-swap consumer, a segment-done
condition on one side (e.g., the primary camera
pipeline produces EOS because its device was
removed) should NOT propagate to the downstream
composite pipeline — the whole point of hot-swap is
that the composite continues uninterrupted.

The council does NOT explicitly set
`automatic-eos=false`. It relies on the default,
which is the wrong direction.

**Whether this actually causes problems in practice
depends on how often the primary producer emits
segment-done events**. With `interpipesink
forward-eos=false` (set in `camera_pipeline.py:171`),
the primary sink does NOT forward EOS to the
consumer. That effectively mitigates the risk —
the cascade can't happen because the event is
blocked at the source side. **But the defense is
one-sided**: if the fallback sink ever forwards EOS
(and its `forward-eos` is not set explicitly —
worth checking), the cascade path is open.

**Fix**: explicit `accept-eos-event=false` on
interpipesrc + explicit `forward-eos=false` on every
interpipesink (council already does the latter for
primary, should verify for fallback). Belt and
suspenders defense.

## 4. Live verification of current state

`agents/studio_compositor/fallback_pipeline.py` —
check if `forward-eos` is set on the fallback sink.

(This drop does not include the verification — the
file was not read during this investigation. A
follow-up would check and either confirm the
fallback sink is also `forward-eos=false` or flag it
as a gap.)

## 5. Ring summary

### Ring 1 — drop-everything

| # | Fix | File | Lines | Impact |
|---|---|---|---|---|
| **SWAP-1** | Explicit queue bounds on interpipesrc (`max-buffers=5`, `max-bytes=0`, `max-time=165ms`, `leaky-type=downstream`) | `cameras.py:109-113` | 4 | Deterministic queue semantics, 5-frame cushion matches downstream |
| **SWAP-2** | Explicit `automatic-eos=false` + `accept-eos-event=false` on interpipesrc | `cameras.py:109-113` | 2 | Defensive EOS cascade prevention |

### Ring 2 — observability

| # | Fix | File | Lines | Impact |
|---|---|---|---|---|
| **SWAP-3** | Per-camera `interpipesrc.dropped` counter → Prometheus | `metrics.py` + tick | ~20 | Per-consumer swap-related frame loss visibility |
| **SWAP-4** | Per-camera `interpipesrc.current-level-buffers` gauge | `metrics.py` + tick | ~20 | Per-consumer queue depth visibility |

### Ring 3 — architectural (deferred)

| # | Fix | File | Notes |
|---|---|---|---|
| **SWAP-5** | Upgrade swap `idle_add` to `idle_add_full(PRIORITY_HIGH_IDLE)` | `pipeline_manager.py:319, 322` | Only if measurement shows swap latency hurts livestream; today nothing measures it |

## 6. Cross-references to other cam drops

- **Drop #35 COMP-1**: `cudacompositor.set_property("latency", 33_000_000)`.
  Directly interacts with this drop — during the ~40 ms
  swap window, COMP-1 gives the aggregator a frame of
  grace so the swap-in-progress pad isn't dropped.
- **Drop #35 COMP-2**: `cudacompositor.set_property("ignore-inactive-pads", True)`.
  Also interacts — if the swap takes longer than a
  frame and the consumer has no new buffer, this
  property lets the aggregator produce output with the
  other 5 pads' data.
- **Drop #27** (brio-operator cold-start grace): the
  watchdog-grace fix shipped as PR #806 covers the
  other side — making sure the FSM doesn't falsely
  report stale frames during a freshly-rebuilt primary
  producer's warmup window.

**Together, drops #27 + #35 + #37 (this drop) form
the full "recovery-from-producer-failure" fix set**:

- Drop #27: don't mistakenly mark a recovering primary
  as stale during warmup
- Drop #37 SWAP-1+SWAP-2: make the swap itself
  predictable + defensive
- Drop #35 COMP-1+COMP-2: make the cudacompositor
  tolerate the swap-in-progress window gracefully

## 7. Cumulative impact estimate

Ring 1 SWAP-1 + SWAP-2 are 6 lines of code total.
Ring 2 SWAP-3 + SWAP-4 add per-camera swap observability.

**Expected user-visible effect**: during a
primary-to-fallback swap (e.g., when a camera
temporarily disconnects), the composite output
maintains continuity better — no stall, no black
frame, no aggregator skip.

## 8. References

- `agents/studio_compositor/pipeline_manager.py:176-209`
  — `swap_to_fallback` / `swap_to_primary`
- `agents/studio_compositor/pipeline_manager.py:350-356`
  — `_idle_swap_*` main-loop indirection
- `agents/studio_compositor/pipeline_manager.py:318-322`
  — state machine callback → idle_add
- `agents/studio_compositor/cameras.py:104-116`
  — interpipesrc construction + property set
- `agents/studio_compositor/camera_pipeline.py:168-171`
  — interpipesink sink property set including
  `forward-eos=false`
- `gst-inspect-1.0 interpipesrc` — full property list
- Drops #27, #28, #35 — companion fixes in the same
  recovery-path area

## 9. Open question for operator

**Is there any measurement of swap latency today?**
`metrics.on_swap(role, to_fallback=...)` is a counter,
not a timer. There is no histogram. The only way to
verify this drop's Ring 1 fixes is either:

1. Run a USB disconnect test with the fixes applied,
   observe composite output for stalls (qualitative)
2. Add a latency histogram before shipping Ring 1
   (SWAP-3 + SWAP-4 observability first, then
   SWAP-1 + SWAP-2 fixes after)

The second order is safer.
