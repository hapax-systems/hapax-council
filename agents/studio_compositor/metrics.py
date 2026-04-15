"""In-process Prometheus exporter for the studio compositor.

Phase 4 of the camera 24/7 resilience epic.

See docs/superpowers/specs/2026-04-12-v4l2-prometheus-exporter-design.md

Exposes per-camera frame flow, kernel-level drop counts, state machine
transitions, reconnect attempts, compositor uptime, and (pre-reserved for
Phase 5) RTMP metrics on a small HTTP endpoint for the workstation's
existing Docker Prometheus container to scrape via host-gateway.

Thread model: pad probes execute on producer streaming threads; state
transition callbacks execute on the GLib main loop; the poll loop runs
on its own background thread. prometheus_client Counter/Gauge are
internally thread-safe, and the tracker dicts are guarded by a module-
level lock.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Delta retirement handoff item #3 / AC-13: the Rust
# ``hapax-imagination`` ``headless::Renderer`` publishes its
# ``DynamicPipeline::pool_metrics()`` to this path as a JSON document
# at ~1 Hz (every 60 render frames). The poll loop below reads it and
# mirrors the six fields onto the Prometheus gauges
# ``reverie_pool_*`` registered below.
_POOL_METRICS_SHM_PATH = Path("/dev/shm/hapax-imagination/pool_metrics.json")

# LRR Phase 0 item 4 / FINDING-Q step 4: the Rust imagination renderer
# also publishes ``DynamicPipeline::shader_rollback_total()`` to this
# sibling path at ~10 Hz (every 600 render frames). Lower cadence than
# pool metrics because rollbacks are rare. The poll loop reads this and
# publishes ``hapax_imagination_shader_rollback_total`` as a Prometheus
# counter. Spike doc:
# ``docs/superpowers/specs/2026-04-14-lrr-phase-0-finding-q-spike-notes.md``
_SHADER_HEALTH_SHM_PATH = Path("/dev/shm/hapax-imagination/shader_health.json")


_PROMETHEUS_AVAILABLE = False
try:
    from prometheus_client import (
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        start_http_server,
    )

    _PROMETHEUS_AVAILABLE = True
except ImportError:
    log.warning("prometheus_client not available — metrics disabled")


# Livestream-performance-map Sprint 6 F4 / W1.3: frame-interval histogram
# bucket edges (in seconds). Beta's research calls out ``p99 ≤ 34 ms`` as
# the headline target, so the buckets are dense around the 30 fps ideal
# (33 ms) and spread out for the long tail.
_FRAME_INTERVAL_BUCKETS: tuple[float, ...] = (
    0.005,  # 5 ms   — absurdly fast (rare; a frame gap that short is probably
    #                  a measurement artifact)
    0.010,  # 10 ms  — 100 fps, only a burst
    0.016,  # 16 ms  — 60 fps
    0.020,  # 20 ms  — 50 fps
    0.025,  # 25 ms  — 40 fps
    0.030,  # 30 ms  — 33 fps, just above target
    0.033,  # 33 ms  — target (30 fps nominal period)
    0.040,  # 40 ms  — 25 fps, noticeable
    0.050,  # 50 ms  — 20 fps, very noticeable
    0.067,  # 67 ms  — 15 fps, stuttering
    0.100,  # 100 ms — visible freeze
    0.200,  # 200 ms
    0.500,  # 500 ms — long stall
)


# --------------------------- metric definitions ---------------------------


REGISTRY: Any = None
CAM_FRAMES_TOTAL: Any = None
CAM_KERNEL_DROPS_TOTAL: Any = None
CAM_BYTES_TOTAL: Any = None
CAM_LAST_FRAME_AGE: Any = None
CAM_FRAME_INTERVAL: Any = None
CAM_STATE: Any = None
CAM_TRANSITIONS_TOTAL: Any = None
CAM_RECONNECT_ATTEMPTS_TOTAL: Any = None
CAM_CONSECUTIVE_FAILURES: Any = None
CAM_IN_FALLBACK: Any = None
COMP_BOOT_TIMESTAMP: Any = None
COMP_UPTIME: Any = None
COMP_WATCHDOG_LAST_FED: Any = None
COMP_CAMERAS_TOTAL: Any = None
COMP_CAMERAS_HEALTHY: Any = None
COMP_PIPELINE_RESTARTS_TOTAL: Any = None
COMP_GPU_VRAM_BYTES: Any = None
RTMP_BYTES_TOTAL: Any = None
RTMP_CONNECTED: Any = None
RTMP_ENCODER_ERRORS_TOTAL: Any = None
RTMP_BIN_REBUILDS_TOTAL: Any = None
RTMP_BITRATE_BPS: Any = None
REVERIE_POOL_BUCKET_COUNT: Any = None
REVERIE_POOL_TOTAL_TEXTURES: Any = None
REVERIE_POOL_TOTAL_ACQUIRES: Any = None
REVERIE_POOL_TOTAL_ALLOCATIONS: Any = None
REVERIE_POOL_REUSE_RATIO: Any = None
REVERIE_POOL_SLOT_COUNT: Any = None
COMP_MEMORY_FOOTPRINT: Any = None
COMP_TTS_CLIENT_TIMEOUT_TOTAL: Any = None
CAM_FRAME_FLOW_STALE_TOTAL: Any = None
COMP_VOICE_ACTIVE: Any = None
COMP_MUSIC_DUCKED: Any = None
HAPAX_IMAGINATION_SHADER_ROLLBACK_TOTAL: Any = None
COMP_GLFEEDBACK_RECOMPILE_TOTAL: Any = None
COMP_GLFEEDBACK_ACCUM_CLEAR_TOTAL: Any = None
# Drop #41 BT-5 + drop #52 FDL-2/3/4 observability triple: surface the
# compositor's fd count, per-camera rebuild count, and per-stop teardown
# duration as scrape-visible metrics so future regressions in the
# camera-rebuild-thrash path become alertable before they starve
# downstream fds (drop #51 live-incident pattern).
COMP_PROCESS_FD_COUNT: Any = None
COMP_CAMERA_REBUILD_TOTAL: Any = None
COMP_PIPELINE_TEARDOWN_DURATION_MS: Any = None
# Last value the mirror published, so we can detect rollback events
# (the gauge → counter delta must be non-negative since the underlying
# Rust counter is monotonic across imagination process lifetime).
_LAST_SHADER_ROLLBACK_TOTAL: int = 0


def _init_metrics() -> None:
    """Lazy-init all metric definitions. Safe to call multiple times."""
    global REGISTRY
    global CAM_FRAMES_TOTAL
    global CAM_KERNEL_DROPS_TOTAL
    global CAM_BYTES_TOTAL
    global CAM_LAST_FRAME_AGE
    global CAM_FRAME_INTERVAL
    global CAM_STATE
    global CAM_TRANSITIONS_TOTAL
    global CAM_RECONNECT_ATTEMPTS_TOTAL
    global CAM_CONSECUTIVE_FAILURES
    global CAM_IN_FALLBACK
    global COMP_BOOT_TIMESTAMP
    global COMP_UPTIME
    global COMP_WATCHDOG_LAST_FED
    global COMP_CAMERAS_TOTAL
    global COMP_CAMERAS_HEALTHY
    global COMP_PIPELINE_RESTARTS_TOTAL
    global COMP_GPU_VRAM_BYTES
    global RTMP_BYTES_TOTAL
    global RTMP_CONNECTED
    global RTMP_ENCODER_ERRORS_TOTAL
    global RTMP_BIN_REBUILDS_TOTAL
    global RTMP_BITRATE_BPS
    global REVERIE_POOL_BUCKET_COUNT
    global REVERIE_POOL_TOTAL_TEXTURES
    global REVERIE_POOL_TOTAL_ACQUIRES
    global REVERIE_POOL_TOTAL_ALLOCATIONS
    global REVERIE_POOL_REUSE_RATIO
    global REVERIE_POOL_SLOT_COUNT
    global COMP_MEMORY_FOOTPRINT
    global COMP_TTS_CLIENT_TIMEOUT_TOTAL
    global CAM_FRAME_FLOW_STALE_TOTAL
    global COMP_VOICE_ACTIVE
    global COMP_MUSIC_DUCKED
    global HAPAX_IMAGINATION_SHADER_ROLLBACK_TOTAL

    if not _PROMETHEUS_AVAILABLE:
        return
    if REGISTRY is not None:
        return

    REGISTRY = CollectorRegistry()

    CAM_FRAMES_TOTAL = Counter(
        "studio_camera_frames_total",
        "Frames observed at the producer interpipesink sink pad",
        ["role", "model"],
        registry=REGISTRY,
    )
    CAM_KERNEL_DROPS_TOTAL = Counter(
        "studio_camera_kernel_drops_total",
        "Frames dropped at the kernel/USB level (from v4l2 sequence gaps)",
        ["role", "model"],
        registry=REGISTRY,
    )
    CAM_BYTES_TOTAL = Counter(
        "studio_camera_bytes_total",
        "Buffer bytes observed at the producer interpipesink",
        ["role", "model"],
        registry=REGISTRY,
    )
    CAM_LAST_FRAME_AGE = Gauge(
        "studio_camera_last_frame_age_seconds",
        "Monotonic seconds since the last buffer observed",
        ["role", "model"],
        registry=REGISTRY,
    )
    # Livestream-performance-map Sprint 6 F4 / W1.3: frame-interval
    # histogram. Beta's Sprint 6 audit identified that
    # ``studio_camera_frames_total`` + ``studio_camera_last_frame_age_seconds``
    # (counter + gauge) are not enough to measure the research map's
    # headline target ``p99 ≤ 34 ms frame time`` — a long tail of 100 ms
    # frames hides inside a 30 fps counter-derived mean. This histogram
    # exposes the per-camera frame-interval distribution so a Prometheus
    # ``histogram_quantile(0.99, ...)`` query returns the actual p99.
    # Updated from ``pad_probe_on_buffer`` on every v4l2src-observed
    # buffer, which already has the monotonic timestamp bookkeeping.
    CAM_FRAME_INTERVAL = Histogram(
        "studio_camera_frame_interval_seconds",
        "Per-camera inter-frame interval distribution (seconds between "
        "consecutive buffers at the producer pad probe)",
        ["role", "model"],
        buckets=_FRAME_INTERVAL_BUCKETS,
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
        "CameraStateMachine transitions",
        ["role", "from_state", "to_state"],
        registry=REGISTRY,
    )
    CAM_RECONNECT_ATTEMPTS_TOTAL = Counter(
        "studio_camera_reconnect_attempts_total",
        "Reconnect attempts by result (succeeded | failed)",
        ["role", "result"],
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
        "1 if the consumer is listening to fb_<role>, 0 if cam_<role>",
        ["role"],
        registry=REGISTRY,
    )
    # Livestream-performance-map W5 NEW (silent-failure class): the
    # frame-flow watchdog dispatches FRAME_FLOW_STALE when a HEALTHY
    # camera's pad-probe last_frame_age exceeds the staleness threshold.
    # Counts per role so a Grafana alert can fire on rising rate.
    # Discovered 2026-04-14 from a brio-synths post-reboot incident
    # where the FSM reported HEALTHY but no frames had flowed for 77 s.
    CAM_FRAME_FLOW_STALE_TOTAL = Counter(
        "studio_camera_frame_flow_stale_total",
        "Frame-flow watchdog FRAME_FLOW_STALE dispatches",
        ["role"],
        registry=REGISTRY,
    )
    # Livestream-performance-map W3.3 / Sprint 4 item 190: voice +
    # music ducking observability. Two correlated gauges so the
    # voice-trigger → music-duck latency can be measured (delta
    # between voice_active going high and music_ducked going high)
    # and the steady-state ducking residency can be plotted.
    COMP_VOICE_ACTIVE = Gauge(
        "studio_compositor_voice_active",
        "1 when TTS playback is in progress (director loop _do_speak_and_advance), 0 otherwise",
        registry=REGISTRY,
    )
    COMP_MUSIC_DUCKED = Gauge(
        "studio_compositor_music_ducked",
        "1 when SlotAudioControl is in any non-idle envelope state (ducking/ducked/restoring), 0 when idle",
        registry=REGISTRY,
    )

    # LRR Phase 0 item 4 / FINDING-Q step 4: shader rollback counter.
    # Mirrors the Rust `DynamicPipeline::shader_rollback_total()` over
    # the SHM bridge at /dev/shm/hapax-imagination/shader_health.json.
    # The Rust counter is monotonic across imagination process lifetime;
    # the Python mirror reads the absolute value and bumps the
    # Prometheus counter by the delta on each poll. A nonzero rate over
    # any rolling window is a Grafana alert candidate — every rollback
    # event represents a hot-reload that was rejected by validation.
    HAPAX_IMAGINATION_SHADER_ROLLBACK_TOTAL = Counter(
        "hapax_imagination_shader_rollback_total",
        "Cumulative WGSL hot-reload rollback events (validation failures + runtime panics)",
        registry=REGISTRY,
    )

    # Phase 10 / delta metric-coverage-gaps C7 + C8: proof-of-fix
    # metrics for the glfeedback diff-check landing alongside this
    # phase. C7 counts shader recompile events (including no-op
    # re-sets until the diff check lands — after which the counter
    # rate should drop from ~336/hour to <= 20/hour of real changes).
    # C8 counts accumulation-buffer clears; the Rust plugin clears on
    # every real shader change, so its rate tracks the genuine
    # recompile rate after the fix. Together they give the operator
    # a direct before/after picture of the fix.
    global COMP_GLFEEDBACK_RECOMPILE_TOTAL
    global COMP_GLFEEDBACK_ACCUM_CLEAR_TOTAL
    global COMP_PROCESS_FD_COUNT
    global COMP_CAMERA_REBUILD_TOTAL
    global COMP_PIPELINE_TEARDOWN_DURATION_MS
    COMP_GLFEEDBACK_RECOMPILE_TOTAL = Counter(
        "compositor_glfeedback_recompile_total",
        "Number of times SlotPipeline.activate_plan set_property-ed a glfeedback "
        "fragment. Counts only real set_property calls; byte-identical re-sets "
        "are elided by the Phase 10 diff check.",
        registry=REGISTRY,
    )
    COMP_GLFEEDBACK_ACCUM_CLEAR_TOTAL = Counter(
        "compositor_glfeedback_accum_clear_total",
        "Number of times activate_plan triggered an accumulation-buffer clear "
        "(paired with recompile_total: every real shader change clears both "
        "accum FBOs in the Rust plugin).",
        registry=REGISTRY,
    )

    COMP_BOOT_TIMESTAMP = Gauge(
        "studio_compositor_boot_timestamp_seconds",
        "Unix time when this compositor process started",
        registry=REGISTRY,
    )
    COMP_UPTIME = Gauge(
        "studio_compositor_uptime_seconds",
        "Seconds since the compositor started",
        registry=REGISTRY,
    )
    COMP_WATCHDOG_LAST_FED = Gauge(
        "studio_compositor_watchdog_last_fed_seconds_ago",
        "Seconds since last WATCHDOG=1 was sent to systemd",
        registry=REGISTRY,
    )
    COMP_CAMERAS_TOTAL = Gauge(
        "studio_compositor_cameras_total",
        "Total registered cameras",
        registry=REGISTRY,
    )
    COMP_CAMERAS_HEALTHY = Gauge(
        "studio_compositor_cameras_healthy",
        "Cameras currently in the HEALTHY state",
        registry=REGISTRY,
    )
    COMP_PIPELINE_RESTARTS_TOTAL = Counter(
        "studio_compositor_pipeline_restarts_total",
        "Pipeline teardown + rebuild events",
        ["pipeline"],
        registry=REGISTRY,
    )

    # Drop #41 BT-5 / drop #52 FDL-2: process fd count gauge. Read from
    # /proc/self/fd in the status tick so any future regression in the
    # camera-rebuild-thrash path (drop #51 root cause) becomes
    # scrape-visible before it exhausts the LimitNOFILE=65536 drop-in
    # ceiling. Alert candidate: >80% of LimitNOFILE sustained for 5 min.
    COMP_PROCESS_FD_COUNT = Gauge(
        "studio_compositor_process_fd_count",
        "Number of open file descriptors in the compositor process (from /proc/self/fd)",
        registry=REGISTRY,
    )

    # Drop #52 FDL-3: per-camera rebuild counter. Increments on every
    # CameraPipeline.rebuild() call. Rate spikes are the signature of
    # the rebuild-thrash fault pattern from drop #51 — thousands of
    # rebuilds per hour on a single camera role means the USB/v4l2
    # layer is in a bad state. Alert candidate: rate >5/min sustained.
    COMP_CAMERA_REBUILD_TOTAL = Counter(
        "studio_compositor_camera_rebuild_total",
        "Cumulative camera pipeline rebuild events per role",
        ["role"],
        registry=REGISTRY,
    )

    # Drop #52 FDL-4: teardown duration histogram. Observes the
    # wall-clock cost of CameraPipeline.stop()'s get_state(NULL) wait
    # — long tail means the NULL transition is blocking on a v4l2 or
    # CUDA cleanup cascade and we should expect the rebuild path to
    # be sluggish. Primary use is validating that the FDL-1 5 s bound
    # is generous enough for normal teardown (<100 ms p99 expected).
    COMP_PIPELINE_TEARDOWN_DURATION_MS = Histogram(
        "studio_compositor_camera_teardown_duration_ms",
        "Wall-clock duration of CameraPipeline.stop() NULL transition, per role",
        ["role"],
        buckets=(1.0, 5.0, 10.0, 50.0, 100.0, 500.0, 1000.0, 2000.0, 5000.0),
        registry=REGISTRY,
    )

    # Livestream-performance-map Sprint 1 F4 / W1.9: compositor VRAM
    # self-report. The poll loop reads ``nvidia-smi --query-compute-apps``
    # filtered by this process's PID and publishes the observed VRAM.
    # Sprint 1 noted a 3 GB VRAM footprint for the GStreamer-only
    # compositor (post PR #751's libtorch removal) and flagged it as
    # worth investigating. Without this gauge, the compositor's VRAM
    # footprint is invisible to Grafana — it only shows up on host
    # ``nvidia-smi`` snapshots. Cross-ref queue 026 P3 (texture pool
    # ``reuse_ratio=0``, still open).
    COMP_GPU_VRAM_BYTES = Gauge(
        "studio_compositor_gpu_vram_bytes",
        "VRAM used by the compositor process, in bytes (0 if unavailable)",
        registry=REGISTRY,
    )

    # Reserved for Phase 5 RTMP output
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
        "NVENC errors surfaced on the RTMP bin bus",
        ["endpoint"],
        registry=REGISTRY,
    )
    RTMP_BIN_REBUILDS_TOTAL = Counter(
        "studio_rtmp_bin_rebuilds_total",
        "RTMP bin teardown + rebuild events",
        ["endpoint"],
        registry=REGISTRY,
    )
    RTMP_BITRATE_BPS = Gauge(
        "studio_rtmp_bitrate_bps",
        "Rolling 10-second average RTMP bitrate",
        ["endpoint"],
        registry=REGISTRY,
    )

    # Delta retirement handoff item #3 / AC-13: surface
    # ``DynamicPipeline::pool_metrics()`` from the Rust imagination
    # binary over the shared-memory JSON bridge at
    # ``/dev/shm/hapax-imagination/pool_metrics.json``. The Rust
    # ``headless::Renderer::render_frame`` writes one tmp+rename
    # atomic JSON document per 60 frames (~1 Hz). The poll loop below
    # reads that file every second and mirrors it onto these gauges.
    REVERIE_POOL_BUCKET_COUNT = Gauge(
        "reverie_pool_bucket_count",
        "Distinct (w, h, format) buckets currently allocated in DynamicPipeline",
        registry=REGISTRY,
    )
    REVERIE_POOL_TOTAL_TEXTURES = Gauge(
        "reverie_pool_total_textures",
        "Total GPU textures the DynamicPipeline transient pool currently owns",
        registry=REGISTRY,
    )
    REVERIE_POOL_TOTAL_ACQUIRES = Gauge(
        "reverie_pool_total_acquires",
        "Lifetime acquire_tracked calls on the transient texture pool",
        registry=REGISTRY,
    )
    REVERIE_POOL_TOTAL_ALLOCATIONS = Gauge(
        "reverie_pool_total_allocations",
        "Lifetime fresh-allocation count on the transient texture pool",
        registry=REGISTRY,
    )
    REVERIE_POOL_REUSE_RATIO = Gauge(
        "reverie_pool_reuse_ratio",
        "Fraction of pool acquires that reused a cached texture (1.0 = perfect)",
        registry=REGISTRY,
    )
    REVERIE_POOL_SLOT_COUNT = Gauge(
        "reverie_pool_slot_count",
        "Distinct named slots currently mapped in intermediate_slots",
        registry=REGISTRY,
    )

    # Queue 022 item #6 / queue 023 item #25: compositor self-report
    # of RSS so the grafana memory panel does not have to cross-reference
    # the system-wide Prometheus node_exporter cgroup series.
    COMP_MEMORY_FOOTPRINT = Gauge(
        "studio_compositor_memory_footprint_bytes",
        "Resident set size of the compositor process (bytes). Updated by the metrics poll loop.",
        registry=REGISTRY,
    )
    # Queue 023 item #32: surface the 90s TtsClient timeout so
    # repeated compositor→daimonion UDS failures become visible without
    # greping the journal. Incremented from
    # ``DaimonionTtsClient.synthesize`` on ``socket.timeout``.
    COMP_TTS_CLIENT_TIMEOUT_TOTAL = Counter(
        "compositor_tts_client_timeout_total",
        "Times the compositor's daimonion TTS UDS client hit its readall timeout.",
        registry=REGISTRY,
    )


_init_metrics()


# --------------------------- freshness gauge registration ---------------------------
#
# ``budget`` and ``budget_signal`` define module-level FreshnessGauge
# instances that publish the ``compositor_publish_{costs,degraded}_*``
# series. They need to be imported (module body executed) AFTER
# ``_init_metrics()`` populates ``REGISTRY`` so their gauges register
# on the compositor's custom collector. Neither module is otherwise
# imported at compositor startup — ``cairo_source.py`` only imports
# ``budget`` under ``TYPE_CHECKING`` — so without this force-import
# the gauges are never constructed and the dead-path observability
# stays invisible. Import is best-effort: if either module fails to
# load the metrics surface is unaffected.
if _PROMETHEUS_AVAILABLE:
    try:
        from agents.studio_compositor import (
            budget,  # noqa: F401
            budget_signal,  # noqa: F401
        )
    except Exception:  # pragma: no cover
        log.warning(
            "freshness-gauge force-import failed — compositor_publish_* series will not be exposed",
            exc_info=True,
        )


# --------------------------- runtime state ---------------------------


_last_seq: dict[str, int] = {}
_last_frame_monotonic: dict[str, float] = {}
_cam_models: dict[str, str] = {}
# Role → current state name. Mirrors CAM_STATE label values so
# _refresh_counts can compute studio_compositor_cameras_healthy
# without reading back from the Prometheus registry.
_cam_states: dict[str, str] = {}
_last_watchdog_monotonic: float = 0.0
_boot_monotonic: float = 0.0
_lock = threading.Lock()
_server_started = False
_poll_thread_started = False


# --------------------------- public API ---------------------------


def start_metrics_server(port: int = 9482, addr: str = "0.0.0.0") -> bool:
    """Start the Prometheus HTTP server. Safe to call multiple times."""
    global _server_started
    global _boot_monotonic
    global _poll_thread_started

    if not _PROMETHEUS_AVAILABLE:
        log.warning("prometheus_client unavailable — metrics server not started")
        return False
    if _server_started:
        return True

    _boot_monotonic = time.monotonic()
    if COMP_BOOT_TIMESTAMP is not None:
        COMP_BOOT_TIMESTAMP.set(time.time())

    try:
        start_http_server(port, addr=addr, registry=REGISTRY)
    except OSError:
        log.exception("metrics server failed to bind %s:%d", addr, port)
        return False

    _server_started = True

    if not _poll_thread_started:
        threading.Thread(target=_poll_loop, daemon=True, name="studio-metrics-poll").start()
        _poll_thread_started = True

    log.info("metrics server started on %s:%d", addr, port)
    return True


def register_camera(role: str, model: str) -> None:
    """Register a camera role so label-bearing metrics appear in scrapes
    even before the first frame arrives."""
    with _lock:
        _cam_models[role] = model
        _last_seq[role] = -1
        _last_frame_monotonic[role] = 0.0
        _cam_states[role] = "healthy"

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


def pad_probe_on_buffer(pad: Any, info: Any, role: str) -> int:
    """GStreamer pad probe callback. Runs on the producer streaming thread.

    Observes the buffer's GstBuffer.offset, which equals v4l2_buffer.sequence
    for v4l2src sources in GStreamer 1.28, and computes kernel-level drops
    from the sequence gap. Passes the buffer through unchanged.
    """
    try:
        buf = info.get_buffer() if info is not None else None
    except Exception:
        buf = None
    if buf is None:
        return 0  # Gst.PadProbeReturn.OK

    try:
        seq = buf.offset
        size = buf.get_size()
    except Exception:
        return 0

    now = time.monotonic()
    with _lock:
        model = _cam_models.get(role, "unknown")
        last = _last_seq.get(role, -1)
        prev_mono = _last_frame_monotonic.get(role, 0.0)
        _last_seq[role] = seq
        _last_frame_monotonic[role] = now

    if CAM_FRAMES_TOTAL is None:
        return 0

    CAM_FRAMES_TOTAL.labels(role=role, model=model).inc()
    CAM_BYTES_TOTAL.labels(role=role, model=model).inc(size)
    if last >= 0 and seq > last + 1:
        CAM_KERNEL_DROPS_TOTAL.labels(role=role, model=model).inc(seq - last - 1)

    # W1.3: observe the per-camera frame interval for the p99 histogram.
    # Skip the first observation (prev_mono == 0.0 before any frames) and
    # any negative / zero delta (shouldn't happen — monotonic clock — but
    # defensive against wraparounds on exotic platforms).
    if CAM_FRAME_INTERVAL is not None and prev_mono > 0.0:
        interval_s = now - prev_mono
        if interval_s > 0.0:
            CAM_FRAME_INTERVAL.labels(role=role, model=model).observe(interval_s)

    return 0


def on_state_transition(role: str, from_state: str, to_state: str) -> None:
    """Called by the state machine on transition (via PipelineManager)."""
    with _lock:
        _cam_states[role] = to_state
    if CAM_TRANSITIONS_TOTAL is None:
        return
    CAM_TRANSITIONS_TOTAL.labels(role=role, from_state=from_state, to_state=to_state).inc()
    for st in ("healthy", "degraded", "offline", "recovering", "dead"):
        CAM_STATE.labels(role=role, state=st).set(1 if st == to_state else 0)
    _refresh_counts()


def on_reconnect_result(role: str, succeeded: bool) -> None:
    if CAM_RECONNECT_ATTEMPTS_TOTAL is None:
        return
    result = "succeeded" if succeeded else "failed"
    CAM_RECONNECT_ATTEMPTS_TOTAL.labels(role=role, result=result).inc()


def on_consecutive_failures_changed(role: str, count: int) -> None:
    if CAM_CONSECUTIVE_FAILURES is None:
        return
    CAM_CONSECUTIVE_FAILURES.labels(role=role).set(count)


def on_swap(role: str, to_fallback: bool) -> None:
    if CAM_IN_FALLBACK is None:
        return
    CAM_IN_FALLBACK.labels(role=role).set(1 if to_fallback else 0)


def on_frame_flow_stale(role: str) -> None:
    if CAM_FRAME_FLOW_STALE_TOTAL is None:
        return
    CAM_FRAME_FLOW_STALE_TOTAL.labels(role=role).inc()


def set_voice_active(active: bool) -> None:
    if COMP_VOICE_ACTIVE is None:
        return
    COMP_VOICE_ACTIVE.set(1 if active else 0)


def set_music_ducked(ducked: bool) -> None:
    if COMP_MUSIC_DUCKED is None:
        return
    COMP_MUSIC_DUCKED.set(1 if ducked else 0)


def on_pipeline_restart(pipeline_name: str) -> None:
    if COMP_PIPELINE_RESTARTS_TOTAL is None:
        return
    COMP_PIPELINE_RESTARTS_TOTAL.labels(pipeline=pipeline_name).inc()


def mark_watchdog_fed() -> None:
    global _last_watchdog_monotonic
    with _lock:
        _last_watchdog_monotonic = time.monotonic()


def shutdown() -> None:
    """Clear registered cameras on graceful stop. The HTTP server and
    prometheus_client registry stay alive with the process."""
    with _lock:
        _last_seq.clear()
        _last_frame_monotonic.clear()
        _cam_models.clear()
        _cam_states.clear()


# --------------------------- internal helpers ---------------------------


def _refresh_counts() -> None:
    """Recompute studio_compositor_cameras_total / _healthy gauges."""
    if COMP_CAMERAS_TOTAL is None or COMP_CAMERAS_HEALTHY is None:
        return
    with _lock:
        total = len(_cam_models)
        healthy = sum(1 for st in _cam_states.values() if st == "healthy")
    COMP_CAMERAS_TOTAL.set(total)
    COMP_CAMERAS_HEALTHY.set(healthy)


def _poll_loop() -> None:
    """Background thread: update last-frame-age gauges, uptime, and
    mirror the reverie pool_metrics JSON from SHM onto gauges."""
    while True:
        time.sleep(1.0)
        now = time.monotonic()

        with _lock:
            boot = _boot_monotonic
            wd_age = now - _last_watchdog_monotonic if _last_watchdog_monotonic > 0 else -1.0
            ages = [
                (
                    role,
                    now - last_mono if last_mono > 0 else float("inf"),
                    _cam_models.get(role, "unknown"),
                )
                for role, last_mono in _last_frame_monotonic.items()
            ]

        if CAM_LAST_FRAME_AGE is None:
            continue

        for role, age, model in ages:
            CAM_LAST_FRAME_AGE.labels(role=role, model=model).set(age)

        if COMP_UPTIME is not None and boot > 0:
            COMP_UPTIME.set(now - boot)
        if COMP_WATCHDOG_LAST_FED is not None and wd_age >= 0:
            COMP_WATCHDOG_LAST_FED.set(wd_age)

        _update_memory_footprint()
        _update_gpu_vram()
        _mirror_reverie_pool_metrics()
        _mirror_imagination_shader_health()


def _update_memory_footprint() -> None:
    """Publish the compositor process RSS onto studio_compositor_memory_footprint_bytes.

    Reads ``/proc/self/status`` to avoid pulling psutil into the
    compositor's dependency set. VmRSS is reported in kB with an
    ``kB`` suffix; we convert to bytes. Swallows IO errors because the
    metrics poll loop must not crash on a transient /proc glitch.
    """
    if COMP_MEMORY_FOOTPRINT is None:
        return
    try:
        with open("/proc/self/status", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    kb_str = line.split()[1]
                    COMP_MEMORY_FOOTPRINT.set(int(kb_str) * 1024)
                    return
    except (OSError, ValueError, IndexError):
        pass


def record_tts_client_timeout() -> None:
    """Called by DaimonionTtsClient on readall timeout (queue 023 item #32)."""
    if COMP_TTS_CLIENT_TIMEOUT_TOTAL is None:
        return
    COMP_TTS_CLIENT_TIMEOUT_TOTAL.inc()


# Lazy-initialised subprocess command cache for the VRAM poll so we only
# build the argv list once per process. ``nvidia-smi`` is invoked at most
# once per second from ``_poll_loop``.
_NVIDIA_SMI_CMD: tuple[str, ...] = (
    "nvidia-smi",
    "--query-compute-apps=pid,used_memory",
    "--format=csv,noheader,nounits",
)


def _update_gpu_vram() -> None:
    """Publish the compositor's VRAM footprint to ``studio_compositor_gpu_vram_bytes``.

    Calls ``nvidia-smi --query-compute-apps=pid,used_memory --format=csv``
    and filters for the current process's PID. Falls back to 0 when
    nvidia-smi is missing (headless test environment), when the
    subprocess fails, or when the process has no GPU context yet.

    Sprint 1 F4 / W1.9: the compositor was observed at 3 GB VRAM
    post-libtorch-removal and flagged for attribution investigation. This
    gauge makes the ongoing footprint visible to Grafana + alertable.
    """
    if COMP_GPU_VRAM_BYTES is None:
        return
    try:
        import os
        import subprocess

        my_pid = os.getpid()
        result = subprocess.run(
            _NVIDIA_SMI_CMD,
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if result.returncode != 0:
            return
        # Format: "pid, used_memory" — used_memory is MiB (--nounits strips the suffix).
        for line in result.stdout.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                continue
            try:
                pid = int(parts[0])
            except ValueError:
                continue
            if pid != my_pid:
                continue
            try:
                mib = int(parts[1])
            except ValueError:
                return
            COMP_GPU_VRAM_BYTES.set(mib * 1024 * 1024)
            return
        # PID not in the output — no GPU context held yet. Set 0 so
        # Grafana sees a real ``0`` instead of stale values from a prior tick.
        COMP_GPU_VRAM_BYTES.set(0)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        # nvidia-smi missing (test environments), or subprocess hung.
        return


def _mirror_reverie_pool_metrics() -> None:
    """Read the latest pool_metrics.json published by the Rust
    ``hapax-imagination`` binary and update the six ``reverie_pool_*``
    gauges.

    File absence is normal (the reverie daemon may not be running, or
    may be on an older build without the publisher). Any parse or
    read error is logged at debug level and silently skipped so the
    camera-metric polling path stays unaffected.
    """
    if REVERIE_POOL_BUCKET_COUNT is None:
        return
    try:
        raw = _POOL_METRICS_SHM_PATH.read_text()
    except FileNotFoundError:
        return
    except OSError as exc:
        log.debug("reverie pool_metrics read failed: %s", exc)
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.debug("reverie pool_metrics parse failed: %s", exc)
        return
    if not isinstance(data, dict):
        return
    try:
        REVERIE_POOL_BUCKET_COUNT.set(float(data.get("bucket_count", 0)))
        REVERIE_POOL_TOTAL_TEXTURES.set(float(data.get("total_textures", 0)))
        REVERIE_POOL_TOTAL_ACQUIRES.set(float(data.get("total_acquires", 0)))
        REVERIE_POOL_TOTAL_ALLOCATIONS.set(float(data.get("total_allocations", 0)))
        REVERIE_POOL_REUSE_RATIO.set(float(data.get("reuse_ratio", 0.0)))
        REVERIE_POOL_SLOT_COUNT.set(float(data.get("slot_count", 0)))
    except (TypeError, ValueError) as exc:
        log.debug("reverie pool_metrics coerce failed: %s", exc)


def _mirror_imagination_shader_health() -> None:
    """LRR Phase 0 item 4 / FINDING-Q step 4: read shader_health.json
    published by the Rust ``hapax-imagination`` binary and bump the
    Prometheus counter by the delta against the last seen value.

    The Rust side exposes a monotonic counter
    (``DynamicPipeline::shader_rollback_total()``). Each poll reads the
    absolute value, computes ``current - _LAST_SHADER_ROLLBACK_TOTAL``,
    and increments the Prometheus counter by that delta. Restarts of
    the imagination process reset the Rust counter to 0 — when that
    happens, the delta is negative and we don't increment (the
    Prometheus counter is monotonic per scrape regardless).

    File absence is normal. Errors are debug-level.
    """
    global _LAST_SHADER_ROLLBACK_TOTAL
    if HAPAX_IMAGINATION_SHADER_ROLLBACK_TOTAL is None:
        return
    try:
        raw = _SHADER_HEALTH_SHM_PATH.read_text()
    except FileNotFoundError:
        return
    except OSError as exc:
        log.debug("imagination shader_health read failed: %s", exc)
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.debug("imagination shader_health parse failed: %s", exc)
        return
    if not isinstance(data, dict):
        return
    try:
        current = int(data.get("shader_rollback_total", 0))
    except (TypeError, ValueError) as exc:
        log.debug("imagination shader_health coerce failed: %s", exc)
        return
    if current < _LAST_SHADER_ROLLBACK_TOTAL:
        # Imagination process restarted — Rust counter reset to 0.
        # Re-baseline without bumping the Prometheus counter.
        _LAST_SHADER_ROLLBACK_TOTAL = current
        return
    delta = current - _LAST_SHADER_ROLLBACK_TOTAL
    if delta > 0:
        HAPAX_IMAGINATION_SHADER_ROLLBACK_TOTAL.inc(delta)
        _LAST_SHADER_ROLLBACK_TOTAL = current
