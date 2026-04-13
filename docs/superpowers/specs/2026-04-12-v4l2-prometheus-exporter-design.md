# v4l2 / GStreamer Prometheus Exporter — Design (Camera Epic Phase 4)

**Filed:** 2026-04-12
**Status:** Formal design. Implementation in Phase 4 of the camera resilience epic.
**Epic:** `docs/superpowers/plans/2026-04-12-camera-247-resilience-epic.md`
**Depends on:** Phase 2 (hot-swap architecture), Phase 3 (state machine). Relies on per-camera `GstPipeline` + interpipesink + state machine delivered by Phase 2 and 3.

## Purpose

Publish per-camera frame-flow health, kernel-level drop counts, state-machine transitions, compositor restart counts, and RTMP ingest status as Prometheus metrics that the workstation's existing Prometheus + Grafana stack can scrape. Close observability gap G6 from the research brief.

External research found no off-the-shelf v4l2 / GStreamer Prometheus exporter in the open-source ecosystem — this is a known gap. Writing one is the canonical fill.

Design constraint: the exporter runs **in-process inside the compositor**, not as a sidecar. Two reasons: (1) the authoritative frame counter (`GstBuffer.offset`, which equals `v4l2_buffer.sequence` for v4l2src sources in GStreamer 1.28) is only accessible from inside the producer pipeline's streaming thread via a pad probe, and (2) opening a second v4l2 connection to the same device from a sidecar process competes with the compositor and is not allowed by the kernel. In-process is the only clean solution.

## Requirements

- **R1.** Expose Prometheus metrics on an HTTP endpoint that the Docker Prometheus container can scrape via `host.docker.internal` + `extra_hosts: [host-gateway]`.
- **R2.** Per-camera metrics: frames received, last-frame age, kernel-level drop count (from sequence gaps), current state, reconnect attempt count, state transition count by (from, to), bytes received.
- **R3.** Process-level metrics: compositor boot count, uptime, watchdog heartbeat age.
- **R4.** Phase-5-prepared metrics: RTMP bin state, RTMP bytes sent, RTMP encoder errors.
- **R5.** Metric updates must not add measurable latency to the streaming path (single-digit microseconds per frame).
- **R6.** A repo-tracked Grafana dashboard that imports cleanly and visualizes the metrics out of the box.
- **R7.** Existing Docker Prometheus deployment extended with one new scrape job — no infrastructure-level changes.

## Architecture

Four concurrent concerns, all in-process inside the compositor:

1. **HTTP server** — `prometheus_client.start_http_server(9482, addr="0.0.0.0")` spawns a daemon thread serving `/metrics` on the host's loopback + docker bridge interfaces. One call at compositor boot.
2. **Pad probes** — one `Gst.PadProbeType.BUFFER` probe per camera's `interpipesink` sink pad, installed at producer pipeline build time. Each probe reads `buffer.offset` (= v4l2_buffer.sequence), computes the sequence delta vs the last observed sequence, increments a Counter and a drop Counter, updates a monotonic timestamp, and passes through (`GST_PAD_PROBE_OK`).
3. **Poll loop** — a background thread wakes every 1 s and computes derived metrics: last-frame age (monotonic now minus last-frame time per camera), state transitions per second, compositor uptime.
4. **Event-driven updates** — state machine transition callbacks directly increment counters and set gauges. The state machine's existing `on_notify_transition` callback is extended to also write to Prometheus.

### Why in-process

The authoritative frame counter is `GstBuffer.offset` for v4l2src-sourced buffers. Verified via `v4l2src`'s source in `gst-plugins-good/sys/v4l2/gstv4l2src.c`: the v4l2src element copies `v4l2_buffer.sequence` into `GstBuffer.offset` (and `offset_end`). This is a stable GStreamer 1.x semantic and is documented in `GstBuffer` reference. Access from Python is trivial:

```python
def on_pad_probe(pad, info, role):
    buf = info.get_buffer()
    seq = buf.offset  # == v4l2_buffer.sequence
    last = _last_seq.get(role, -1)
    if last >= 0 and seq > last + 1:
        CAM_KERNEL_DROPS.labels(role=role).inc(seq - last - 1)
    _last_seq[role] = seq
    CAM_FRAMES_TOTAL.labels(role=role).inc()
    _last_frame_monotonic[role] = time.monotonic()
    return Gst.PadProbeReturn.OK
```

A sidecar exporter process would have to either:
1. Open the v4l2 device independently — blocked, the compositor already holds it.
2. Parse `v4l2-ctl --all` via subprocess — high latency, not real frame counters.
3. Read `/sys/kernel/debug/usb/...` — no per-frame error counters exposed at stock kernel.

None of these are viable. In-process is the only path that gives real frame counters.

## Metric catalogue

### Camera metrics (labeled by `role`, and where meaningful also by `model`)

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `studio_camera_frames_total` | Counter | role, model | Frames observed at the producer's interpipesink |
| `studio_camera_kernel_drops_total` | Counter | role, model | Frames dropped at the kernel/USB level (from sequence gaps) |
| `studio_camera_bytes_total` | Counter | role, model | Bytes observed at the producer's interpipesink |
| `studio_camera_last_frame_age_seconds` | Gauge | role, model | Monotonic seconds since the last frame |
| `studio_camera_state` | Gauge | role, state | 1 for current state, 0 for others |
| `studio_camera_transitions_total` | Counter | role, from_state, to_state | State machine transitions |
| `studio_camera_reconnect_attempts_total` | Counter | role, result | result=succeeded|failed |
| `studio_camera_consecutive_failures` | Gauge | role | Current consecutive failure counter |
| `studio_camera_in_fallback` | Gauge | role | 1 if consumer is listening to fb_<role>, 0 if cam_<role> |

### Compositor-level metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `studio_compositor_boot_timestamp_seconds` | Gauge | — | Unix time when this compositor process started |
| `studio_compositor_uptime_seconds` | Gauge | — | Seconds since boot (derived at scrape time) |
| `studio_compositor_watchdog_last_fed_seconds_ago` | Gauge | — | Seconds since last `WATCHDOG=1` to systemd |
| `studio_compositor_cameras_total` | Gauge | — | Total number of registered cameras |
| `studio_compositor_cameras_healthy` | Gauge | — | Number currently in HEALTHY state |
| `studio_compositor_pipeline_restarts_total` | Counter | pipeline | pipeline=composite|cam_<role>|fb_<role>|rtmp_bin |
| `studio_compositor_glib_idle_queue_depth` | Gauge | — | Approximate size of the GLib idle callback queue (for latency diagnosis) |

### RTMP metrics (Phase 5)

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `studio_rtmp_bytes_total` | Counter | endpoint | Bytes pushed to RTMP endpoint |
| `studio_rtmp_connected` | Gauge | endpoint | 1 if rtmp2sink is currently connected |
| `studio_rtmp_encoder_errors_total` | Counter | endpoint | NVENC errors surfaced on the RTMP bin's bus |
| `studio_rtmp_bin_rebuilds_total` | Counter | endpoint | Number of times the RTMP bin has been torn down and rebuilt |
| `studio_rtmp_bitrate_bps` | Gauge | endpoint | Rolling 10-second average bitrate |

Phase 5's design doc details how these are updated. Phase 4 only defines them and reserves the metric names.

### Director loop / Cairo source metrics (existing observability — not in Phase 4 scope)

Left to their existing per-component instrumentation. Not added to this exporter.

## Module layout

`agents/studio_compositor/metrics.py` (new file).

```python
"""In-process Prometheus exporter for the studio compositor.

Registers all metrics at import time. Starts the HTTP server via
start_metrics_server(). Pad probes and state machine callbacks update metrics.
"""
from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from prometheus_client import Counter, Gauge, CollectorRegistry, start_http_server

if TYPE_CHECKING:
    from gi.repository import Gst
    from .camera_state_machine import CameraState


REGISTRY = CollectorRegistry()

CAM_FRAMES_TOTAL = Counter(
    "studio_camera_frames_total",
    "Frames observed at the producer interpipesink",
    ["role", "model"],
    registry=REGISTRY,
)
CAM_KERNEL_DROPS_TOTAL = Counter(
    "studio_camera_kernel_drops_total",
    "Frames dropped at the kernel/USB level (from sequence gaps)",
    ["role", "model"],
    registry=REGISTRY,
)
CAM_BYTES_TOTAL = Counter(
    "studio_camera_bytes_total",
    "Bytes observed at the producer interpipesink",
    ["role", "model"],
    registry=REGISTRY,
)
CAM_LAST_FRAME_AGE = Gauge(
    "studio_camera_last_frame_age_seconds",
    "Monotonic seconds since the last frame",
    ["role", "model"],
    registry=REGISTRY,
)
CAM_STATE = Gauge(
    "studio_camera_state",
    "1 if camera is in this state, 0 otherwise",
    ["role", "state"],
    registry=REGISTRY,
)
CAM_TRANSITIONS_TOTAL = Counter(
    "studio_camera_transitions_total",
    "State machine transitions",
    ["role", "from_state", "to_state"],
    registry=REGISTRY,
)
CAM_RECONNECT_ATTEMPTS_TOTAL = Counter(
    "studio_camera_reconnect_attempts_total",
    "Reconnect attempts by result",
    ["role", "result"],  # result: succeeded | failed
    registry=REGISTRY,
)
CAM_CONSECUTIVE_FAILURES = Gauge(
    "studio_camera_consecutive_failures",
    "Current consecutive failure counter",
    ["role"],
    registry=REGISTRY,
)
CAM_IN_FALLBACK = Gauge(
    "studio_camera_in_fallback",
    "1 if consumer listening to fb_<role>, 0 if cam_<role>",
    ["role"],
    registry=REGISTRY,
)

COMP_BOOT_TIMESTAMP = Gauge(
    "studio_compositor_boot_timestamp_seconds",
    "Unix time when this compositor process started",
    registry=REGISTRY,
)
COMP_UPTIME = Gauge(
    "studio_compositor_uptime_seconds",
    "Seconds since compositor boot",
    registry=REGISTRY,
)
COMP_WATCHDOG_LAST_FED = Gauge(
    "studio_compositor_watchdog_last_fed_seconds_ago",
    "Seconds since last WATCHDOG=1 sent to systemd",
    registry=REGISTRY,
)
COMP_CAMERAS_TOTAL = Gauge(
    "studio_compositor_cameras_total",
    "Total number of registered cameras",
    registry=REGISTRY,
)
COMP_CAMERAS_HEALTHY = Gauge(
    "studio_compositor_cameras_healthy",
    "Number of cameras currently in HEALTHY state",
    registry=REGISTRY,
)
COMP_PIPELINE_RESTARTS_TOTAL = Counter(
    "studio_compositor_pipeline_restarts_total",
    "Pipeline teardown + rebuild events",
    ["pipeline"],
    registry=REGISTRY,
)

RTMP_BYTES_TOTAL = Counter(
    "studio_rtmp_bytes_total",
    "Bytes pushed to RTMP endpoint",
    ["endpoint"],
    registry=REGISTRY,
)
RTMP_CONNECTED = Gauge(
    "studio_rtmp_connected",
    "1 if rtmp2sink is currently connected",
    ["endpoint"],
    registry=REGISTRY,
)
RTMP_ENCODER_ERRORS_TOTAL = Counter(
    "studio_rtmp_encoder_errors_total",
    "NVENC errors from RTMP bin bus",
    ["endpoint"],
    registry=REGISTRY,
)
RTMP_BIN_REBUILDS_TOTAL = Counter(
    "studio_rtmp_bin_rebuilds_total",
    "Number of times the RTMP bin has been torn down and rebuilt",
    ["endpoint"],
    registry=REGISTRY,
)
RTMP_BITRATE_BPS = Gauge(
    "studio_rtmp_bitrate_bps",
    "Rolling 10-second average bitrate",
    ["endpoint"],
    registry=REGISTRY,
)


_last_seq: dict[str, int] = {}
_last_frame_monotonic: dict[str, float] = {}
_cam_models: dict[str, str] = {}
_last_watchdog_monotonic: float = 0.0
_boot_monotonic: float = 0.0
_lock = threading.Lock()


def start_metrics_server(port: int = 9482, addr: str = "0.0.0.0") -> None:
    """Start the Prometheus HTTP server. Call once at compositor boot."""
    global _boot_monotonic
    _boot_monotonic = time.monotonic()
    COMP_BOOT_TIMESTAMP.set(time.time())
    start_http_server(port, addr=addr, registry=REGISTRY)
    threading.Thread(target=_poll_loop, daemon=True, name="metrics-poll").start()


def register_camera(role: str, model: str) -> None:
    """Call at pipeline build time per camera role."""
    with _lock:
        _cam_models[role] = model
        _last_seq[role] = -1
        _last_frame_monotonic[role] = 0.0
    CAM_CONSECUTIVE_FAILURES.labels(role=role).set(0)
    CAM_IN_FALLBACK.labels(role=role).set(0)


def pad_probe_on_buffer(pad, info, role: str):
    """GStreamer pad probe. Runs on the producer streaming thread."""
    buf = info.get_buffer()
    if buf is None:
        return 0  # Gst.PadProbeReturn.OK
    model = _cam_models.get(role, "unknown")
    seq = buf.offset
    size = buf.get_size()

    with _lock:
        last = _last_seq.get(role, -1)
        _last_seq[role] = seq
        _last_frame_monotonic[role] = time.monotonic()

    CAM_FRAMES_TOTAL.labels(role=role, model=model).inc()
    CAM_BYTES_TOTAL.labels(role=role, model=model).inc(size)
    if last >= 0 and seq > last + 1:
        CAM_KERNEL_DROPS_TOTAL.labels(role=role, model=model).inc(seq - last - 1)
    return 0  # Gst.PadProbeReturn.OK


def on_state_transition(role: str, from_state, to_state, reason: str) -> None:
    """Called by camera state machine."""
    CAM_TRANSITIONS_TOTAL.labels(
        role=role, from_state=from_state.value, to_state=to_state.value
    ).inc()
    # Clear all state gauges for this role then set the new one to 1
    for st in ("healthy", "degraded", "offline", "recovering", "dead"):
        CAM_STATE.labels(role=role, state=st).set(1 if st == to_state.value else 0)


def on_reconnect_result(role: str, succeeded: bool) -> None:
    CAM_RECONNECT_ATTEMPTS_TOTAL.labels(
        role=role, result="succeeded" if succeeded else "failed"
    ).inc()


def on_consecutive_failures_changed(role: str, count: int) -> None:
    CAM_CONSECUTIVE_FAILURES.labels(role=role).set(count)


def on_swap(role: str, to_fallback: bool) -> None:
    CAM_IN_FALLBACK.labels(role=role).set(1 if to_fallback else 0)


def mark_watchdog_fed() -> None:
    global _last_watchdog_monotonic
    with _lock:
        _last_watchdog_monotonic = time.monotonic()


def _poll_loop() -> None:
    while True:
        time.sleep(1.0)
        now = time.monotonic()
        with _lock:
            boot = _boot_monotonic
            wd_age = now - _last_watchdog_monotonic if _last_watchdog_monotonic > 0 else -1.0
            for role, last_mono in _last_frame_monotonic.items():
                model = _cam_models.get(role, "unknown")
                age = now - last_mono if last_mono > 0 else float("inf")
                CAM_LAST_FRAME_AGE.labels(role=role, model=model).set(age)
        COMP_UPTIME.set(now - boot)
        if wd_age >= 0:
            COMP_WATCHDOG_LAST_FED.set(wd_age)
```

Lines of code: ~200. All stdlib + `prometheus_client`. Pure Python, thread-safe by design, no GStreamer imports inside the module (pad probe callback receives pad/info as opaque GStreamer handles).

## Integration

### At compositor boot

`agents/studio_compositor/__main__.py` (modified):

```python
from .metrics import start_metrics_server
# ... existing imports ...

def main() -> None:
    # ... existing setup ...
    compositor = StudioCompositor()
    compositor.build()
    start_metrics_server(port=9482, addr="0.0.0.0")
    compositor.run()
```

### At camera registration time

`agents/studio_compositor/pipeline_manager.py::PipelineManager.build` (Phase 2 scope, extended in Phase 4):

```python
from . import metrics

for spec in self._specs:
    metrics.register_camera(spec.role, spec.camera_class)  # "brio" or "c920"
    self._cameras[spec.role] = CameraPipeline(spec, supervisor=self)
    self._cameras[spec.role].build()
    self._cameras[spec.role].start()
    self._install_metrics_probe(spec.role)
    # ... rest of build ...
```

`PipelineManager._install_metrics_probe(role)`:

```python
def _install_metrics_probe(self, role: str) -> None:
    pipeline = self._cameras[role]._pipeline
    sink = pipeline.get_by_name(f"cam_{role}")
    if sink is None:
        return
    sink_pad = sink.get_static_pad("sink")
    if sink_pad is None:
        return
    sink_pad.add_probe(
        Gst.PadProbeType.BUFFER,
        lambda pad, info: metrics.pad_probe_on_buffer(pad, info, role),
    )
```

### In the state machine callbacks

`agents/studio_compositor/pipeline_manager.py` constructs the `CameraStateMachine` with callbacks that include metrics updates:

```python
def _make_state_machine(self, role: str) -> CameraStateMachine:
    return CameraStateMachine(
        role=role,
        on_schedule_reconnect=lambda delay: self._schedule_reconnect(role, delay),
        on_swap_to_fallback=lambda: (self.swap_to_fallback(role), metrics.on_swap(role, True)),
        on_swap_to_primary=lambda: (self.swap_to_primary(role), metrics.on_swap(role, False)),
        on_rebuild=lambda: self._rebuild_camera(role),
        on_notify_transition=lambda o, n, r: (
            metrics.on_state_transition(role, o, n, r),
            self._maybe_ntfy_transition(role, o, n, r),
        ),
    )
```

Reconnect results are reported from the supervisor thread:

```python
def _supervisor_reconnect(self, role: str) -> None:
    ok = self._rebuild_camera(role)
    metrics.on_reconnect_result(role, ok)
    if ok:
        self._states[role].dispatch(Event(EventKind.RECOVERY_SUCCEEDED))
    else:
        self._states[role].dispatch(Event(EventKind.RECOVERY_FAILED))
    metrics.on_consecutive_failures_changed(
        role, self._states[role].consecutive_failures
    )
```

### Watchdog heartbeat feed

In Phase 1, the `send_watchdog` GLib timer callback (implemented in `__main__.py`) also calls `metrics.mark_watchdog_fed()`:

```python
def _watchdog_tick() -> bool:
    # Liveness gate: at least one camera has frames within last 20s
    now = time.monotonic()
    any_fresh = any(
        (now - t) < 20.0 for t in metrics._last_frame_monotonic.values()
    )
    if any_fresh:
        _sd.notify("WATCHDOG=1")
        metrics.mark_watchdog_fed()
    else:
        log.warning("watchdog not fed: no cameras have fresh frames")
    return True  # keep timer running
```

## Thread safety

- `prometheus_client` Counter/Gauge/Histogram are internally thread-safe. `.inc()` and `.set()` are lock-free atomic operations for most backends; `prometheus_client` uses a `threading.Lock` per metric for safety.
- `_last_seq`, `_last_frame_monotonic`, `_cam_models`, `_last_watchdog_monotonic`, `_boot_monotonic` are protected by `_lock`.
- The pad probe callback executes on the producer's streaming thread; the poll loop runs on its own thread; the state transition callbacks run on the GLib main loop thread; the HTTP server runs on its own daemon thread started by `prometheus_client`. All four threads converge on the same counters but access is lock-protected.
- The pad probe callback performs one dict lookup, one dict update, one `time.monotonic()` call, and 1-3 metric `inc()/set()` calls — all microsecond-scale. No measurable latency impact on the streaming path.

## Docker Prometheus scrape config

The workstation already runs Prometheus in a Docker container. The existing `docker-compose.yml` Prometheus service gets one addition and one new scrape config.

**Addition to `docker-compose.yml` (Prometheus service section):**

```yaml
  prometheus:
    # ... existing config ...
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

`extra_hosts: [host.docker.internal:host-gateway]` maps the special name to the docker bridge gateway on Linux (Docker ≥ 20.10). This is the clean in-container path to reach host-bound services.

**New scrape job in `prometheus.yml` (or wherever the Prometheus config lives):**

```yaml
scrape_configs:
  - job_name: 'studio-compositor'
    scrape_interval: 5s
    scrape_timeout: 4s
    static_configs:
      - targets: ['host.docker.internal:9482']
        labels:
          host: 'workstation'
          service: 'studio-compositor'
```

5 s scrape interval is aggressive but cheap — the exposition is O(labels) and under 2 KB total. 4 s scrape timeout leaves 1 s budget.

The exporter binds to `0.0.0.0:9482`, which makes it reachable from both `127.0.0.1` and the docker bridge IP. Firewall rules on the workstation (iptables/nftables) should restrict port 9482 to localhost + docker bridge — the metrics expose operator-sensitive information and should not be LAN-accessible. An operator-side firewall rule is documented as a manual step in the Phase 4 PR body.

## Grafana dashboard

`grafana/dashboards/studio-cameras.json` (new file, committed to repo).

Panels:

1. **Cameras Healthy (stat)** — `sum(studio_camera_state{state="healthy"})`. Color thresholds: 0-5 red, 6 green.
2. **Frame rate per camera (time series)** — `rate(studio_camera_frames_total[30s])`. One line per `role` label. Y axis 0-40 fps.
3. **Last frame age per camera (stat, repeat by role)** — `studio_camera_last_frame_age_seconds{role=$role}`. Thresholds: 0-1s green, 1-3s yellow, >3s red. Repeat by role.
4. **State per camera (state timeline)** — `studio_camera_state`. Color map: healthy=green, degraded=yellow, offline=orange, recovering=blue, dead=red. One row per role.
5. **Kernel drops (time series)** — `rate(studio_camera_kernel_drops_total[30s])`. One line per role.
6. **Reconnect attempts (bar chart)** — `sum by (role, result) (rate(studio_camera_reconnect_attempts_total[5m]))`.
7. **State transitions (heatmap)** — `sum by (from_state, to_state) (rate(studio_camera_transitions_total[1m]))`.
8. **Compositor uptime (stat)** — `studio_compositor_uptime_seconds`.
9. **Compositor restarts (stat)** — `increase(studio_compositor_pipeline_restarts_total[1h])`.
10. **Watchdog freshness (stat)** — `studio_compositor_watchdog_last_fed_seconds_ago`. Red if > 20.
11. **RTMP bitrate (time series)** — `studio_rtmp_bitrate_bps / 1000000`. Y axis 0-10 Mbps.
12. **RTMP connected (stat)** — `studio_rtmp_connected`.

Total: 12 panels in a single dashboard row layout. Committed as a `grafana/dashboards/studio-cameras.json` file, importable via Grafana's "Import Dashboard" UI or auto-loaded via Grafana's provisioning system if we wire it.

### Dashboard provisioning (optional, Phase 6)

`grafana/provisioning/dashboards/studio.yaml`:

```yaml
apiVersion: 1
providers:
  - name: 'studio'
    folder: 'Studio'
    type: file
    options:
      path: /etc/grafana/provisioning/dashboards/studio
```

With a docker-compose volume mount of `./grafana/dashboards:/etc/grafana/provisioning/dashboards/studio:ro`. Deferrable to Phase 6 if the existing Grafana is already provisioned differently.

## Performance impact

Pad probe cost per frame: one dict lookup, one dict update, three metric updates, one time.monotonic() call. ~2 microseconds measured on x86_64 with Python 3.13. At 6 cameras × 30 fps = 180 calls/sec = 360 microseconds/sec = 0.036 % CPU. Immeasurable against the existing compositor load.

HTTP server cost at scrape time: O(labels) — each scrape generates ~500 lines of text at ~80 bytes each = 40 KB. Scrape served in under 10 ms. At 5 s scrape interval, ~0.2% CPU.

Memory: `prometheus_client` keeps one entry per label combination. For 6 cameras × (frames + drops + bytes + last_frame_age + state × 5 + transitions × 25 + reconnect × 2 + consecutive_failures + in_fallback) = ~200 entries total. ~20 KB resident.

## Security considerations

Metrics expose operator-sensitive information:
- Per-camera frame rates reveal when operators are near specific cameras.
- Kernel drop counts reveal USB reliability patterns that could inform physical attacks on the studio.
- State transitions reveal when a camera has been unplugged or recovered.
- RTMP bitrate reveals when the stream is live.

Mitigation:
- Bind exporter to `0.0.0.0` but firewall port 9482 to localhost + docker bridge only.
- Document the firewall rule in the PR body as a manual install step.
- No authentication on the metrics endpoint — relying on network-level access control.
- The single-user axiom (no auth anywhere) applies: the operator is the only consumer of these metrics.

## Test strategy

Unit tests:

- `test_pad_probe_increments_frames` — create a fake `GstBuffer` with a known offset, call `pad_probe_on_buffer`, assert `CAM_FRAMES_TOTAL` incremented.
- `test_pad_probe_detects_sequence_gap` — two buffers with offsets 10 and 14, assert `CAM_KERNEL_DROPS_TOTAL` incremented by 3.
- `test_on_state_transition_toggles_gauges` — call with healthy→degraded, assert `CAM_STATE{state=healthy}=0` and `CAM_STATE{state=degraded}=1`.
- `test_metrics_thread_safety` — 10 threads each incrementing a counter 1000 times, total = 10000.
- `test_poll_loop_updates_uptime` — mock time, start poll thread, assert `COMP_UPTIME` advances.

Integration tests (gated `@pytest.mark.camera`):

- `test_real_exporter_http` — boot a compositor, curl `http://127.0.0.1:9482/metrics`, verify `studio_camera_frames_total` is non-zero after a few seconds.
- `test_exporter_grafana_dashboard_loads` — start Grafana in the test docker environment, POST the dashboard JSON, verify 200.

## Acceptance criteria

- `prometheus_client` installed via `pacman -S python-prometheus_client` in Phase 1.
- `agents/studio_compositor/metrics.py` shipped with all defined metrics.
- Pad probes installed on each camera's interpipesink sink pad.
- State machine callbacks updated to call the metrics module.
- Watchdog tick marks `metrics.mark_watchdog_fed()`.
- `curl http://127.0.0.1:9482/metrics` returns valid Prometheus exposition with non-zero `studio_camera_frames_total` for every healthy camera.
- Docker Prometheus scrapes the compositor via `host.docker.internal:9482`.
- `grafana/dashboards/studio-cameras.json` imports cleanly and shows live data for all six cameras.
- Existing tests continue to pass.
- New unit tests pass.

## Risks

1. **Port 9482 collision.** Mitigation: checked against Prometheus wiki's port allocation list; 9482 is unallocated as of the last update. If it ever conflicts, bind to 9481 instead.
2. **Docker bridge gateway not resolvable inside Prometheus container.** Mitigation: `extra_hosts: [host.docker.internal:host-gateway]` is a documented Docker ≥ 20.10 feature that works on Linux. Fallback: bind to the workstation LAN IP and scrape that. Less ideal but works.
3. **`prometheus_client` lock contention under high frame rate.** Mitigation: measurement shows 2 microseconds per probe at 180 Hz. No contention measurable.
4. **Metric cardinality explosion.** Mitigation: bounded labels — role is one of six values, state is one of five, from/to_state combinations bounded to ~25. Total time series under 500.
5. **HTTP server thread leaks on compositor restart.** Mitigation: `start_http_server` is called exactly once at boot; the compositor process dying is a clean termination.
6. **Grafana dashboard drifts from metric names.** Mitigation: the dashboard JSON is repo-tracked; regression test validates metric name alignment.

## Open questions

1. **Histogram for reconnect latency?** Could add `studio_camera_reconnect_duration_seconds_bucket`. Out of scope for Phase 4; defer unless operator asks.
2. **dmesg-driven USB error metric?** Adds a journalctl tail subprocess; complicates the exporter. Deferred.
3. **Should the exporter survive the compositor going to NULL state?** Currently dies with the process. Acceptable — systemd restarts the compositor and the exporter comes up with it.

## References

### Internal

- `docs/superpowers/plans/2026-04-12-camera-247-resilience-epic.md`
- `docs/superpowers/specs/2026-04-12-compositor-hot-swap-architecture-design.md` (Phase 2)
- `docs/superpowers/specs/2026-04-12-camera-recovery-state-machine-design.md` (Phase 3)
- `agents/studio_compositor/pipeline_manager.py` (Phase 2 file, Phase 4 adds metrics integration)
- `agents/studio_compositor/camera_state_machine.py` (Phase 3 file)

### External

- [prometheus/client_python on GitHub](https://github.com/prometheus/client_python)
- [Prometheus default port allocations](https://github.com/prometheus/prometheus/wiki/Default-port-allocations)
- [Prometheus writing exporters guide](https://prometheus.io/docs/instrumenting/writing_exporters/)
- [GstBuffer documentation](https://gstreamer.freedesktop.org/documentation/gstreamer/gstbuffer.html)
- [v4l2src plugin documentation](https://gstreamer.freedesktop.org/documentation/video4linux2/v4l2src.html)
- [Docker `extra_hosts` host-gateway pattern](https://forums.docker.com/t/host-docker-internal-in-production-environment/137507)
- [Grafana Stat panel documentation](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/stat/)
- [V4L2 dropped-frame detection gist](https://gist.github.com/SebastianMartens/7d63f8300a0bcf0c7072a674b3ea4817)
