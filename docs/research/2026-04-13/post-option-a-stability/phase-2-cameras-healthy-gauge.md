# Phase 2 — `studio_compositor_cameras_healthy` accumulator bug

**Queue item:** 023
**Phase:** 2 of 6
**Depends on:** Queue 022 BETA-FINDING-2026-04-13-E (the initial sighting)
**Date:** 2026-04-13 CDT
**Register:** scientific, neutral (per `feedback_scientific_register.md`)

## Headline

`studio_compositor_cameras_healthy` is permanently stuck at `0.0` on the
live compositor scrape, regardless of how many cameras are registered or
which FSM state they occupy. The root cause is a documented-but-never-
implemented accumulator in `agents/studio_compositor/metrics.py`
(`_refresh_counts`, lines 382–394). The bug has been present since the
Phase 4 Prometheus exporter shipped in the camera 24/7 epic (April 2026).

**A correction to queue 022's BETA-FINDING-E is required.** Queue 022
reported that Grafana dashboard panel 0 "displays wrong number." This
turns out to be false: panel 0 queries
`sum(studio_camera_state{state="healthy"})`, not the broken compositor-
level gauge, and that derived sum is populated correctly on every
transition. Grep for the broken gauge name across the codebase returns
**zero downstream consumers** — no panel, no alert, no Python caller, no
React code, no Rust code. The gauge is both wrong and unused. Severity
re-rates from **MEDIUM** (as originally filed in the queue 022 handoff)
to **LOW** — the correctness gap is real but has no operational impact
today.

That said, the fix is still worth shipping: the gauge is publicly
documented in
`docs/superpowers/specs/2026-04-12-v4l2-prometheus-exporter-design.md`
§ Compositor-level metrics, so any future consumer (a Phase 5 alert
rule, an external MCP query, a compositor-health banner in Logos) would
inherit the broken behavior. The fix is a six-line change in one file.

## Live reproduction

### Live scrape (PID 2913194, uptime 8 min)

```text
$ systemctl --user show -p MainPID --value studio-compositor.service
2913194

$ curl -s http://127.0.0.1:9482/metrics | grep cameras_healthy
# HELP studio_compositor_cameras_healthy Cameras currently in the HEALTHY state
# TYPE studio_compositor_cameras_healthy gauge
studio_compositor_cameras_healthy 0.0

$ curl -s http://127.0.0.1:9482/metrics | grep 'studio_camera_state{' | grep 'state="healthy"'
studio_camera_state{role="brio-operator",state="healthy"} 1.0
studio_camera_state{role="c920-desk",state="healthy"} 1.0
studio_camera_state{role="c920-room",state="healthy"} 1.0
studio_camera_state{role="c920-overhead",state="healthy"} 1.0
studio_camera_state{role="brio-room",state="healthy"} 1.0
studio_camera_state{role="brio-synths",state="healthy"} 1.0
```

All six cameras report `state="healthy"=1.0` on the per-camera gauge.
The compositor-level aggregate gauge reports `0.0`. These two facts
are incompatible in a correctly-instrumented exporter.

### Standalone harness reproduction

A minimal reproduction is shipped at
`docs/research/2026-04-13/post-option-a-stability/data/repro_cameras_healthy.py`.
It imports `agents.studio_compositor.metrics` directly (no GStreamer,
no subprocess, no network), drives `register_camera` and
`on_state_transition` with synthetic input, and reads the module-level
`REGISTRY.get_sample_value` after each step.

```text
$ uv run python docs/research/2026-04-13/post-option-a-stability/data/repro_cameras_healthy.py
=== Reproduction: studio_compositor_cameras_healthy accumulator bug ===
  t0 empty: cameras_total=0.0 cameras_healthy=0.0
  after register_camera x2 (both HEALTHY): cameras_total=2.0 cameras_healthy=0.0
  after 1 healthy->degraded: cameras_total=2.0 cameras_healthy=0.0
  after degraded->healthy: cameras_total=2.0 cameras_healthy=0.0
  after 1 healthy->offline: cameras_total=2.0 cameras_healthy=0.0
  after shutdown: cameras_total=2.0 cameras_healthy=0.0
```

Every scenario shows `cameras_healthy=0.0`. The gauge is not correlated
with any observable state of the module.

### Secondary finding: `cameras_total` does not decrement on shutdown

The same reproduction surfaces a minor second bug: `cameras_total` stays
at `2.0` after `metrics.shutdown()` is called, even though
`_cam_models` is emptied. `shutdown()` does not re-invoke `_refresh_counts()`,
and the Gauge object stays alive on the registry. Operational impact
on the live compositor is nil (the process exits immediately after
shutdown on the normal path), but the bug is identical in shape to the
`cameras_healthy` bug — a gauge whose source of truth is a separate
data structure, updated by writes-through-a-function that the write
path does not call on every mutation. Flagged for the backlog at the
bottom of this doc.

## Code trace

### `_refresh_counts` definition (`agents/studio_compositor/metrics.py:382–394`)

```python
def _refresh_counts() -> None:
    """Recompute studio_compositor_cameras_total / _healthy gauges."""
    if COMP_CAMERAS_TOTAL is None or CAM_STATE is None:
        return
    with _lock:
        total = len(_cam_models)
    COMP_CAMERAS_TOTAL.set(total)
    # _healthy is derived from CAM_STATE.value — can't read label values
    # back cleanly, so increment via callers when they know a camera reached
    # HEALTHY. Cheap sum using the internal registry is not exposed —
    # instead, store healthy count separately via on_state_transition.
    # For simplicity we just set total here; _healthy is updated lazily
    # from on_state_transition's count accumulator.
```

The inline comment commits to *two* promises:

1. That `on_state_transition` will maintain a `_healthy` count
   accumulator separate from `CAM_STATE`.
2. That the call site semantics will "store healthy count separately via
   `on_state_transition`" and the gauge will be "updated lazily from
   `on_state_transition`'s count accumulator."

**Neither promise is honored** anywhere in the module. There is no
`_healthy_count` or equivalent module-level integer, and
`on_state_transition` never computes one.

### `on_state_transition` definition (`agents/studio_compositor/metrics.py:329–336`)

```python
def on_state_transition(role: str, from_state: str, to_state: str) -> None:
    """Called by the state machine on transition (via PipelineManager)."""
    if CAM_TRANSITIONS_TOTAL is None:
        return
    CAM_TRANSITIONS_TOTAL.labels(role=role, from_state=from_state, to_state=to_state).inc()
    for st in ("healthy", "degraded", "offline", "recovering", "dead"):
        CAM_STATE.labels(role=role, state=st).set(1 if st == to_state else 0)
    _refresh_counts()
```

It increments `CAM_TRANSITIONS_TOTAL`, updates the per-camera state
labels, and calls `_refresh_counts()`. The accumulator the inline
comment in `_refresh_counts` references does not exist, so the call to
`_refresh_counts` only sets `CAM_CAMERAS_TOTAL`; it has no path to
update `COMP_CAMERAS_HEALTHY`.

### `register_camera` definition (`agents/studio_compositor/metrics.py:271–290`)

```python
def register_camera(role: str, model: str) -> None:
    with _lock:
        _cam_models[role] = model
        _last_seq[role] = -1
        _last_frame_monotonic[role] = 0.0

    if not _PROMETHEUS_AVAILABLE or CAM_FRAMES_TOTAL is None:
        return

    CAM_FRAMES_TOTAL.labels(role=role, model=model).inc(0)
    CAM_KERNEL_DROPS_TOTAL.labels(role=role, model=model).inc(0)
    CAM_BYTES_TOTAL.labels(role=role, model=model).inc(0)
    CAM_LAST_FRAME_AGE.labels(role=role, model=model).set(float("inf"))
    CAM_CONSECUTIVE_FAILURES.labels(role=role).set(0)
    CAM_IN_FALLBACK.labels(role=role).set(0)
    for st in ("healthy", "degraded", "offline", "recovering", "dead"):
        CAM_STATE.labels(role=role, state=st).set(1 if st == "healthy" else 0)
    _refresh_counts()
```

At registration time every camera is stamped as HEALTHY on the
per-camera `CAM_STATE` label. This is an optimistic default — the FSM
actually starts in HEALTHY too (`camera_state_machine.py:80`). The
registration path calls `_refresh_counts()` but, per the above, that
path only updates the total gauge. The implicit state change "camera
just became HEALTHY" at registration time is never fed into the
healthy-count accumulator either (since no such accumulator exists).

### FSM cross-reference (`agents/studio_compositor/camera_state_machine.py:24–29, 80`)

```python
class CameraState(enum.Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    RECOVERING = "recovering"
    DEAD = "dead"

# CameraStateMachine.__init__:
self._state = CameraState.HEALTHY
```

The string value `"healthy"` matches exactly between the FSM enum and
the metrics labels. The transition-notifying callback in
`pipeline_manager.py:272` uses `old.value, new.value`, so the metrics
module sees the same string the FSM emits. No string mismatch
contributes to this bug.

## Consumer survey

| Consumer candidate | Finding |
|---|---|
| `grafana/dashboards/studio-cameras.json` panel 0 "Cameras Healthy" | Queries `sum(studio_camera_state{state="healthy"})` — **does NOT use the broken gauge**. Correct output. |
| All other panels in the studio-cameras dashboard (11 panels) | None query `studio_compositor_cameras_healthy` or `studio_compositor_cameras_total`. |
| Alert rules (`alerts/`, `monitoring/`) | Directories do not exist — no alert rules are shipped in this repo. |
| Python callers (`grep -rn 'studio_compositor_cameras_healthy' agents/ shared/ logos/ --include='*.py'`) | Only the definition (`metrics.py:176`) and its docstring reference (`metrics.py:383`). **Zero callers outside the module.** |
| React callers (`grep -rn 'studio_compositor_cameras_healthy' hapax-logos/ --include='*.ts' --include='*.tsx'`) | Zero matches. |
| Rust callers (`grep -rn 'studio_compositor_cameras_healthy' hapax-logos/src-tauri/ hapax-logos/src-imagination/ --include='*.rs'`) | Zero matches. |
| Spec + design docs | Only descriptive documentation (`docs/superpowers/specs/2026-04-12-v4l2-prometheus-exporter-design.md:82–83`). |

`studio_compositor_cameras_healthy` has **no downstream consumers** in
the current codebase. Grafana panel 0 is wired to the per-camera
state gauge, which is correctly maintained. The bug has no observable
impact on any current dashboard, alert, or UI surface.

## Root cause

One sentence: **the inline comment in `_refresh_counts` delegates the
`_healthy` accumulator to `on_state_transition`, but `on_state_transition`
does not maintain an accumulator, and `register_camera` does not feed
one either, so the Gauge is never set and stays at its default value
(`0.0`).**

The choice not to use `CAM_STATE.labels(...).value`-style introspection
is reasonable — that introspection is not part of the public
`prometheus_client` API. But the chosen alternative (a separate
accumulator) was never implemented. The comment is load-bearing
documentation for a code path that was deferred and forgotten.

Git archaeology: the bug is present in the original Phase 4 exporter
commit and has not been touched since.

```text
$ git log --oneline --all -- agents/studio_compositor/metrics.py
6481d7605 fix(compositor): ALPHA-FINDING-1 — delegate TTS to daimonion via UDS (#751)
... (earlier commits from the Phase 4 ship)
```

(The `_refresh_counts` comment has been unchanged since its introduction
in the camera 24/7 resilience epic, April 2026.)

## Proposed fix

Six-line change in `agents/studio_compositor/metrics.py`. The pattern
is a module-level accumulator guarded by `_lock`, updated on every
mutation path (register, transition, shutdown), and read from a single
place (`_refresh_counts`).

```diff
--- a/agents/studio_compositor/metrics.py
+++ b/agents/studio_compositor/metrics.py
@@ -223,6 +223,7 @@ _init_metrics()
 _last_seq: dict[str, int] = {}
 _last_frame_monotonic: dict[str, float] = {}
 _cam_models: dict[str, str] = {}
+_healthy_roles: set[str] = set()
 _last_watchdog_monotonic: float = 0.0
 _boot_monotonic: float = 0.0
 _lock = threading.Lock()
@@ -275,6 +276,7 @@ def register_camera(role: str, model: str) -> None:
     with _lock:
         _cam_models[role] = model
         _last_seq[role] = -1
         _last_frame_monotonic[role] = 0.0
+        _healthy_roles.add(role)  # register_camera stamps HEALTHY below

     if not _PROMETHEUS_AVAILABLE or CAM_FRAMES_TOTAL is None:
         return
@@ -332,6 +334,11 @@ def on_state_transition(role: str, from_state: str, to_state: str) -> None:
     CAM_TRANSITIONS_TOTAL.labels(role=role, from_state=from_state, to_state=to_state).inc()
     for st in ("healthy", "degraded", "offline", "recovering", "dead"):
         CAM_STATE.labels(role=role, state=st).set(1 if st == to_state else 0)
+    with _lock:
+        if to_state == "healthy":
+            _healthy_roles.add(role)
+        else:
+            _healthy_roles.discard(role)
     _refresh_counts()

@@ -373,6 +380,7 @@ def shutdown() -> None:
         _last_seq.clear()
         _last_frame_monotonic.clear()
         _cam_models.clear()
+        _healthy_roles.clear()


 # --------------------------- internal helpers ---------------------------
@@ -383,12 +391,11 @@ def _refresh_counts() -> None:
     if COMP_CAMERAS_TOTAL is None or CAM_STATE is None:
         return
     with _lock:
         total = len(_cam_models)
+        healthy = len(_healthy_roles)
     COMP_CAMERAS_TOTAL.set(total)
+    COMP_CAMERAS_HEALTHY.set(healthy)
-    # _healthy is derived from CAM_STATE.value — can't read label values
-    # back cleanly, so increment via callers when they know a camera reached
-    # HEALTHY. Cheap sum using the internal registry is not exposed —
-    # instead, store healthy count separately via on_state_transition.
-    # For simplicity we just set total here; _healthy is updated lazily
-    # from on_state_transition's count accumulator.
```

Why a `set[str]` rather than a plain integer: a set gives idempotent
semantics. Spurious re-registration of an already-healthy role (which
can happen if `register_camera` is called twice, or if the FSM emits
`healthy → healthy`) does not double-count. Plain `int += 1` would
drift on idempotent callers. Memory cost for six cameras is trivial.

A `shutdown()` call now also clears `_healthy_roles`, which (coupled
with a follow-up fix to `shutdown()` also calling `_refresh_counts()`
to flush `cameras_total` to zero) addresses the secondary bug the
reproduction surfaced.

### Verification plan for the fix

After applying the diff:

1. Re-run `docs/research/2026-04-13/post-option-a-stability/data/repro_cameras_healthy.py`
   and confirm the `EXPECTED` block in the script matches the actual
   output line-for-line.
2. Add two regression pins to `tests/test_metrics_phase4.py`:
   ```python
   def test_cameras_healthy_gauge_tracks_healthy_state():
       metrics.register_camera("a", "brio")
       metrics.register_camera("b", "c920")
       assert metrics.REGISTRY.get_sample_value("studio_compositor_cameras_healthy") == 2.0
       metrics.on_state_transition("a", "healthy", "degraded")
       assert metrics.REGISTRY.get_sample_value("studio_compositor_cameras_healthy") == 1.0
       metrics.on_state_transition("a", "degraded", "healthy")
       assert metrics.REGISTRY.get_sample_value("studio_compositor_cameras_healthy") == 2.0
   ```
3. Restart `studio-compositor.service` and verify the live scrape
   reports `studio_compositor_cameras_healthy 6.0` within 1 second.

## Downstream consumer impact

None, per the consumer survey above. The fix makes the gauge
*correct*; no dashboard, alert, or UI surface will change in response.
This means the fix can land in any PR that already touches
`metrics.py`, without coordinated dashboard edits.

Recommendation: roll into the next compositor-touching PR (e.g., the
Phase 3 `budget_signal` wiring PR from queue 023). Do not ship as an
isolated PR unless the scope of that PR is already broad enough to
absorb it — a single-file six-line change is reviewer-cheap to
piggyback.

## Backlog additions (for retirement handoff)

1. **Six-line fix as specified above** (LOW severity, but easy win,
   good as a CI regression pin).
2. **`shutdown()` should call `_refresh_counts()`** — trivial,
   one-line, pairs with item 1.
3. **Regression pin in `tests/test_metrics_phase4.py`** as drafted
   above.
4. **Update PR #752 BETA-FINDING-E severity downgrade**: the claim
   that Grafana panel 0 displays a wrong number is false. File this
   as a correction in the retirement handoff and the queue 022
   handoff doc, not as a code change.
