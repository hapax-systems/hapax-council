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
import os
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

_PROC_STATUS_MEMORY_FIELDS: frozenset[str] = frozenset(
    {
        "VmHWM",
        "VmRSS",
        "RssAnon",
        "RssFile",
        "RssShmem",
        "VmSwap",
    }
)
_CGROUP_MEMORY_FILES: dict[str, str] = {
    "current": "memory.current",
    "peak": "memory.peak",
    "high": "memory.high",
    "max": "memory.max",
    "swap_current": "memory.swap.current",
}


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
V4L2SINK_LAST_FRAME_AGE: Any = None
V4L2SINK_FRAMES_TOTAL: Any = None
SHMSINK_LAST_FRAME_AGE: Any = None
SHMSINK_FRAMES_TOTAL: Any = None
# Cc-task ``compositor-v4l2sink-graph-mutation-stall`` (2026-05-04).
V4L2SINK_STALL_TOTAL: Any = None
V4L2SINK_RECOVERY_TOTAL: Any = None
V4L2SINK_FD_REOPENS_TOTAL: Any = None
V4L2SINK_WRITE_ERRORS_TOTAL: Any = None
COMP_RUNTIME_FEATURE_ACTIVE: Any = None
GEM_SUBSTRATE_ACTIVE: Any = None
GEM_SUBSTRATE_PAINT_TOTAL: Any = None
GEM_SUBSTRATE_STEP_ERRORS_TOTAL: Any = None
GEM_SUBSTRATE_MAX_BRIGHTNESS: Any = None
COMP_RENDER_STAGE_FRAMES_TOTAL: Any = None
COMP_RENDER_STAGE_LAST_FRAME_AGE: Any = None
DIRECTOR_LAST_INTENT_AGE: Any = None
DIRECTOR_INTENT_TOTAL: Any = None
HAPAX_REFUSAL_GATE_REROLLS: Any = None
COMP_CAMERAS_TOTAL: Any = None
COMP_CAMERAS_HEALTHY: Any = None
COMP_PIPELINE_RESTARTS_TOTAL: Any = None
COMP_GPU_VRAM_BYTES: Any = None
COMP_SCALED_BLIT_CACHE_ENTRIES: Any = None
COMP_SCALED_BLIT_CACHE_BYTES: Any = None
COMP_SCALED_BLIT_CACHE_EVICTIONS_TOTAL: Any = None
COMP_V4L2_APPSINK_COPIED_BYTES_TOTAL: Any = None
COMP_V4L2_APPSINK_COPIED_FRAMES_TOTAL: Any = None
RTMP_BYTES_TOTAL: Any = None
RTMP_CONNECTED: Any = None
RTMP_ENCODER_ERRORS_TOTAL: Any = None
RTMP_BIN_REBUILDS_TOTAL: Any = None
RTMP_SIDE_EFFECT_ERRORS_TOTAL: Any = None
RTMP_BITRATE_BPS: Any = None
HAPAX_MOBILE_SUBSTREAM_FRAMES_TOTAL: Any = None
HAPAX_MOBILE_SUBSTREAM_BITRATE_KBPS: Any = None
HAPAX_BROADCAST_MODE: Any = None
HAPAX_MOBILE_CAIRO_RENDER_DURATION_MS: Any = None
REVERIE_POOL_BUCKET_COUNT: Any = None
REVERIE_POOL_TOTAL_TEXTURES: Any = None
REVERIE_POOL_TOTAL_ACQUIRES: Any = None
REVERIE_POOL_TOTAL_ALLOCATIONS: Any = None
REVERIE_POOL_REUSE_RATIO: Any = None
REVERIE_POOL_SLOT_COUNT: Any = None
COMP_MEMORY_FOOTPRINT: Any = None
COMP_PROCESS_PID: Any = None
COMP_PROCESS_START_TIME: Any = None
COMP_PROCESS_MEMORY_BYTES: Any = None
COMP_CGROUP_MEMORY_BYTES: Any = None
COMP_CGROUP_MEMORY_EVENTS: Any = None
COMP_TTS_CLIENT_TIMEOUT_TOTAL: Any = None
CAM_FRAME_FLOW_STALE_TOTAL: Any = None
COMP_VOICE_ACTIVE: Any = None
COMP_MUSIC_DUCKED: Any = None
# CVS #145 — bidirectional audio-ducking state machine. One-hot
# gauge (one label per state, 1 for the current state and 0 for the
# others) so Grafana can plot dwell time in each state and alert on
# anomalous residency (e.g. stuck in BOTH_ACTIVE).
HAPAX_AUDIO_DUCKING_STATE: Any = None
HAPAX_IMAGINATION_SHADER_ROLLBACK_TOTAL: Any = None
COMP_GLFEEDBACK_RECOMPILE_TOTAL: Any = None
COMP_GLFEEDBACK_ACCUM_CLEAR_TOTAL: Any = None
# R9 (2026-05-02): dynamic compositor-layout switching. See
# layout_switcher.py for the trigger vocabulary.
HAPAX_COMPOSITOR_LAYOUT_SWITCH_TOTAL: Any = None
# U6 (cc-task u6-four-layouts-switching-followup, 2026-05-03):
# which layout is currently active. Single 1.0 entry at any time
# (the active one); dashboards can sum-by-layout to compute the
# 10-min reachability check the U6 acceptance asked for, OR
# instant-query to confirm the current selection. Set on every
# LayoutStore.set_active call.
HAPAX_COMPOSITOR_LAYOUT_ACTIVE: Any = None
# u6-periodic-tick-driver (cc-task u6-periodic-tick-driver, 2026-05-03):
# every tick of the layout-switch driver dispatches a recommendation,
# regardless of whether the cooldown gate accepts it. Counter covers
# all driver runs so the operator can see the driver is alive even
# when the surface looks frozen (cooldown-blocked / same-layout no-op).
# ``layout`` = the recommendation; ``reason`` = the trigger that
# named it (consent_safe, vinyl_playing, director_activity_<name>,
# stream_mode_deep, default_fallback). Distinct from
# ``hapax_compositor_layout_switch_total`` which fires only on
# applied switches.
HAPAX_LAYOUT_SWITCH_DISPATCHED_TOTAL: Any = None
# FINDING-R diagnostics (2026-04-21 wiring audit): per-ward blit
# accounting on the post-FX cairooverlay. WARD_BLIT_TOTAL counts every
# successful blit_scaled call labeled by ward; WARD_BLIT_SKIPPED_TOTAL
# counts every skip path labeled by ward + reason. Operators query
# the skip counter to identify which of the 16 (now 20) wards aren't
# blitting and why — the previous diagnosis path was "wards visually
# absent, no signal," which led to a phantom architectural finding.
WARD_BLIT_TOTAL: Any = None
WARD_BLIT_SKIPPED_TOTAL: Any = None
# Ward stimmung modulator (Phase 2 of the z-axis spec). The modulator
# runs at ~5 Hz when ``HAPAX_WARD_MODULATOR_ACTIVE=1`` and translates
# imagination dimensions into per-ward depth attenuations. The four
# metrics here let Grafana attribute "modulator never ran" vs
# "imagination loop is dead" vs "the modulator is shifting depth on
# these wards." Counters are total-since-process-start; the gauge
# reflects current per-plane ward population; the histogram observes
# the ``z_index_float`` value the modulator just wrote, labelled by
# ``z_plane`` and ``driving_dim``.
HAPAX_WARD_MODULATOR_TICK_TOTAL: Any = None
HAPAX_WARD_MODULATOR_STALE_TOTAL: Any = None
HAPAX_WARD_Z_PLANE_COUNT: Any = None
HAPAX_WARD_DEPTH_ATTENUATION: Any = None
# FINDING-W deepening (2026-04-21): per-ward source-surface dimensions.
# Gauge labelled by ward holds the most recent source-surface
# width × height (in pixels²) the post-FX cairooverlay just blitted.
# Distinguishes "ward is blitting a transparent / 1×1 / canvas-sized
# empty surface" from "ward is blitting real pixels". Combined with
# WARD_BLIT_TOTAL rate, identifies the per-ward render-vs-content gap
# the wiring audit's visual sweep flagged. Updated from
# fx_chain.pip_draw_from_layout once per blit.
WARD_SOURCE_SURFACE_PIXELS: Any = None
# Task #129 Stage 3 — per-camera face-obscure observability. Increments
# every time ``face_obscure_integration.obscure_frame_for_camera`` is
# called, labelled by camera role and whether any bboxes were obscured
# in this call (``has_faces=true|false``). Runs on the capture-branch
# appsink thread — prometheus_client Counter is thread-safe.
HAPAX_FACE_OBSCURE_FRAME_TOTAL: Any = None
HAPAX_FACE_OBSCURE_ERRORS_TOTAL: Any = None
# Drop #41 BT-5 + drop #52 FDL-2/3/4 observability triple: surface the
# compositor's fd count, per-camera rebuild count, and per-stop teardown
# duration as scrape-visible metrics so future regressions in the
# camera-rebuild-thrash path become alertable before they starve
# downstream fds (drop #51 live-incident pattern).
COMP_PROCESS_FD_COUNT: Any = None
COMP_CAMERA_REBUILD_TOTAL: Any = None
COMP_PIPELINE_TEARDOWN_DURATION_MS: Any = None
COMP_SOURCE_RENDER_DURATION_MS: Any = None
COMP_SOURCE_BACKEND_ERRORS_TOTAL: Any = None
COMP_STOP_ERRORS_TOTAL: Any = None
COMP_FX_PASSTHROUGH_SLOTS: Any = None
# Task #157 — per-source count of frames whose assignment alpha was
# clamped below the requested value because ``Assignment.non_destructive``
# was set. Increments from ``fx_chain.pip_draw_from_layout`` whenever the
# effective clamp ceiling (0.6) would lower the requested opacity.
COMP_NONDESTRUCTIVE_CLAMPS_TOTAL: Any = None
# HOMAGE Phase 6 Layer 5 — ward↔FX bidirectional coupling counters.
# Incremented by ``shared.ward_fx_bus`` on every publish (ward-side or
# fx-side) so Grafana can plot the rate of bidirectional traffic,
# per-ward and per-preset-family. Companion latency histogram observes
# the transition→response delta so we can alert when coupling falls
# behind the single-frame budget.
HAPAX_WARD_FX_EVENTS_TOTAL: Any = None
HAPAX_WARD_FX_LATENCY_SECONDS: Any = None
# Researcher audit (2026-05-03) halftone-monoculture root-cause #3:
# preset load failures are now surfaced as a counter labelled by preset
# name and exception class (was DEBUG-swallowed before, masking a 64%
# load-fail rate).
HAPAX_COMPOSITOR_PRESET_LOAD_FAILED_TOTAL: Any = None
# Task #136 — follow-mode cut counter. Incremented from
# ``state.py``'s hero-override consumer when follow-mode drives the
# hero-camera selection (no manual override present). Labelled by
# ``from_role`` and ``to_role`` so Grafana can answer "which transitions
# is follow-mode actually making" and verify the creative-bias scoring
# isn't getting stuck on one camera.
HAPAX_FOLLOW_MODE_CUTS_TOTAL: Any = None
# Task #122 — director degraded hold counter, see ``_init_metrics`` below.
DIRECTOR_DEGRADED_HOLDS_TOTAL: Any = None
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
    global V4L2SINK_LAST_FRAME_AGE
    global V4L2SINK_FRAMES_TOTAL
    global SHMSINK_LAST_FRAME_AGE
    global SHMSINK_FRAMES_TOTAL
    global V4L2SINK_STALL_TOTAL
    global V4L2SINK_RECOVERY_TOTAL
    global V4L2SINK_FD_REOPENS_TOTAL
    global V4L2SINK_WRITE_ERRORS_TOTAL
    global COMP_RUNTIME_FEATURE_ACTIVE
    global GEM_SUBSTRATE_ACTIVE
    global GEM_SUBSTRATE_PAINT_TOTAL
    global GEM_SUBSTRATE_STEP_ERRORS_TOTAL
    global GEM_SUBSTRATE_MAX_BRIGHTNESS
    global COMP_RENDER_STAGE_FRAMES_TOTAL
    global COMP_RENDER_STAGE_LAST_FRAME_AGE
    global DIRECTOR_LAST_INTENT_AGE
    global DIRECTOR_INTENT_TOTAL
    global HAPAX_REFUSAL_GATE_REROLLS
    global COMP_CAMERAS_TOTAL
    global COMP_CAMERAS_HEALTHY
    global COMP_PIPELINE_RESTARTS_TOTAL
    global COMP_GPU_VRAM_BYTES
    global RTMP_BYTES_TOTAL
    global RTMP_CONNECTED
    global RTMP_ENCODER_ERRORS_TOTAL
    global RTMP_BIN_REBUILDS_TOTAL
    global RTMP_SIDE_EFFECT_ERRORS_TOTAL
    global RTMP_BITRATE_BPS
    global HAPAX_MOBILE_SUBSTREAM_FRAMES_TOTAL
    global HAPAX_MOBILE_SUBSTREAM_BITRATE_KBPS
    global HAPAX_BROADCAST_MODE
    global HAPAX_MOBILE_CAIRO_RENDER_DURATION_MS
    global REVERIE_POOL_BUCKET_COUNT
    global REVERIE_POOL_TOTAL_TEXTURES
    global REVERIE_POOL_TOTAL_ACQUIRES
    global REVERIE_POOL_TOTAL_ALLOCATIONS
    global REVERIE_POOL_REUSE_RATIO
    global REVERIE_POOL_SLOT_COUNT
    global COMP_MEMORY_FOOTPRINT
    global COMP_PROCESS_PID
    global COMP_PROCESS_START_TIME
    global COMP_PROCESS_MEMORY_BYTES
    global COMP_CGROUP_MEMORY_BYTES
    global COMP_CGROUP_MEMORY_EVENTS
    global COMP_TTS_CLIENT_TIMEOUT_TOTAL
    global CAM_FRAME_FLOW_STALE_TOTAL
    global COMP_VOICE_ACTIVE
    global COMP_MUSIC_DUCKED
    global HAPAX_IMAGINATION_SHADER_ROLLBACK_TOTAL
    global WARD_BLIT_TOTAL
    global WARD_BLIT_SKIPPED_TOTAL
    global WARD_SOURCE_SURFACE_PIXELS

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

    # CVS #145 — bidirectional ducker state machine. Pre-register
    # every label value below so Grafana scrapes always see the full set.
    global HAPAX_AUDIO_DUCKING_STATE
    HAPAX_AUDIO_DUCKING_STATE = Gauge(
        "hapax_audio_ducking_state",
        "Current AudioDuckingController state (1 for the active label, 0 for others)",
        ["state"],
        registry=REGISTRY,
    )
    for _st in ("normal", "voice_active", "yt_active", "both_active"):
        HAPAX_AUDIO_DUCKING_STATE.labels(state=_st).set(1 if _st == "normal" else 0)

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

    # FINDING-R diagnostics (2026-04-21 wiring audit): per-ward blit
    # accounting at the post-FX cairooverlay. The pip_draw_from_layout
    # callback emits one increment per blit decision: success → ward
    # label only; skip → ward + reason. Operator queries:
    #   rate(studio_compositor_ward_blit_total{ward="album"}[5m]) > 0
    #     ⇒ album is rendering at the expected cadence
    #   rate(studio_compositor_ward_blit_skipped_total{reason="source_surface_none"}[5m]) > 0
    #     ⇒ that ward's runner returned a transparent surface (input
    #     deprivation, HOLD-state at startup, render_content short-circuit)
    WARD_BLIT_TOTAL = Counter(
        "studio_compositor_ward_blit_total",
        "Successful per-ward blit_scaled calls on the post-FX cairooverlay",
        ["ward"],
        registry=REGISTRY,
    )
    WARD_BLIT_SKIPPED_TOTAL = Counter(
        "studio_compositor_ward_blit_skipped_total",
        (
            "Per-ward blit skips on the post-FX cairooverlay, labelled by reason: "
            "surface_not_found | source_not_registered | source_surface_none | "
            "alpha_clamped_to_zero"
        ),
        ["ward", "reason"],
        registry=REGISTRY,
    )
    WARD_SOURCE_SURFACE_PIXELS = Gauge(
        "studio_compositor_ward_source_surface_pixels",
        (
            "Most recent source-surface width × height (px²) the post-FX "
            "cairooverlay blitted per ward. Pairs with ward_blit_total: a "
            "non-zero blit rate alongside a near-zero pixel area indicates "
            "the source is producing a degenerate (1×1 / empty) surface."
        ),
        ["ward"],
        registry=REGISTRY,
    )

    # Ward stimmung modulator (z-axis spec Phase 2).
    global HAPAX_WARD_MODULATOR_TICK_TOTAL
    global HAPAX_WARD_MODULATOR_STALE_TOTAL
    global HAPAX_WARD_Z_PLANE_COUNT
    global HAPAX_WARD_DEPTH_ATTENUATION
    HAPAX_WARD_MODULATOR_TICK_TOTAL = Counter(
        "hapax_ward_modulator_tick_total",
        "Ward stimmung modulator ticks (successful dim reads + ward writes).",
        registry=REGISTRY,
    )
    HAPAX_WARD_MODULATOR_STALE_TOTAL = Counter(
        "hapax_ward_modulator_stale_total",
        "Modulator ticks skipped because current.json was stale or missing.",
        registry=REGISTRY,
    )
    HAPAX_WARD_Z_PLANE_COUNT = Gauge(
        "hapax_ward_z_plane_count",
        "Number of wards currently assigned to each z-plane.",
        ["z_plane"],
        registry=REGISTRY,
    )
    HAPAX_WARD_DEPTH_ATTENUATION = Histogram(
        "hapax_ward_depth_attenuation",
        "z_index_float values written by the modulator, labelled by z_plane and driving_dim.",
        ["z_plane", "driving_dim"],
        buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
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
    global COMP_SOURCE_RENDER_DURATION_MS
    global COMP_SOURCE_BACKEND_ERRORS_TOTAL
    global COMP_STOP_ERRORS_TOTAL
    global COMP_FX_PASSTHROUGH_SLOTS
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

    # R9 (2026-05-02 effect+cam orchestration audit): dynamic
    # compositor-layout switching. Records every applied switch by
    # ``from_layout`` / ``to_layout`` / ``trigger`` (see
    # ``layout_switcher.LayoutSelection.trigger`` for the trigger
    # vocabulary — currently consent_safe, vinyl_playing,
    # director_activity_<name>, stream_mode_deep, default_fallback).
    # Until this counter started populating, the surface had been
    # running ``default`` exclusively post-boot.
    global HAPAX_COMPOSITOR_LAYOUT_SWITCH_TOTAL
    HAPAX_COMPOSITOR_LAYOUT_SWITCH_TOTAL = Counter(
        "hapax_compositor_layout_switch_total",
        "Compositor layout swaps applied via the R9 dynamic switcher, "
        "labelled by from_layout, to_layout, and the input trigger that "
        "named the new layout.",
        ["from_layout", "to_layout", "trigger"],
        registry=REGISTRY,
    )

    # U6 (cc-task u6-four-layouts-switching-followup, 2026-05-03):
    # which layout is currently active. Always exactly one label set
    # has value 1.0 (the active layout); all others are 0. Updated on
    # every LayoutStore.set_active() call. Operators query
    # ``hapax_compositor_layout_active{layout="default"}`` to confirm
    # the current selection without scraping the switch counter.
    global HAPAX_COMPOSITOR_LAYOUT_ACTIVE
    HAPAX_COMPOSITOR_LAYOUT_ACTIVE = Gauge(
        "hapax_compositor_layout_active",
        "1 when this layout is the currently active compositor layout, 0 otherwise. "
        "Sum over labels = 1 at all times (modulo a microsecond gap during the swap).",
        ["layout"],
        registry=REGISTRY,
    )

    # u6-periodic-tick-driver (cc-task u6-periodic-tick-driver, 2026-05-03):
    # every dispatch attempt by the layout-switch driver. Distinct from
    # ``hapax_compositor_layout_switch_total`` (applied-switches only) —
    # this proves the periodic driver is alive even when no actual
    # switch occurs (same-layout no-op, cooldown-blocked). Operators
    # query
    # ``rate(hapax_layout_switch_dispatched_total[5m]) > 0``
    # to confirm the driver thread has not silently died.
    global HAPAX_LAYOUT_SWITCH_DISPATCHED_TOTAL
    HAPAX_LAYOUT_SWITCH_DISPATCHED_TOTAL = Counter(
        "hapax_layout_switch_dispatched_total",
        "Layout-switch recommendations dispatched by the periodic driver, "
        "labelled by recommended layout and the trigger reason. Increments "
        "every tick regardless of whether the cooldown gate accepts the "
        "switch. Operators alert on rate=0 to detect a dead driver.",
        ["layout", "reason"],
        registry=REGISTRY,
    )

    # u4-micromove-advance-tick-consumer (cc-task u4, 2026-05-03):
    # the micromove consumer counter from ``micromove_consumer.py`` is
    # registered against the prometheus_client default registry. Re-
    # register it here on the compositor REGISTRY so the :9482 metrics
    # endpoint exposes it; the dashboard at
    # ``grafana/dashboards/director-moves.json`` queries this metric
    # by name. Best-effort; if the consumer module hasn't been imported
    # yet the increments stay on the default registry.
    try:
        from agents.studio_compositor import micromove_consumer as _u4_mod

        _existing = _u4_mod.hapax_micromove_advance_total
        # If already on REGISTRY (re-init path) skip.
        try:
            REGISTRY.unregister(_existing)
        except Exception:
            pass
        new_counter = Counter(
            "hapax_micromove_advance_total",
            "Number of micromove cycle advances per slot (re-registered on "
            "compositor REGISTRY for :9482 scrape).",
            ["slot"],
            registry=REGISTRY,
        )
        _u4_mod.hapax_micromove_advance_total = new_counter
    except Exception:
        log.debug(
            "u4 hapax_micromove_advance_total re-register on compositor REGISTRY failed",
            exc_info=True,
        )

    # u5-verb-prometheus-counter (cc-task u5, 2026-05-03):
    # same pattern — counter from ``semantic_verb_consumer.py`` defined
    # against the default registry; re-register on the compositor
    # REGISTRY for :9482 scrape.
    try:
        from agents.studio_compositor import semantic_verb_consumer as _u5_mod

        _existing = _u5_mod.hapax_semantic_verb_consumed_total
        try:
            REGISTRY.unregister(_existing)
        except Exception:
            pass
        new_counter = Counter(
            "hapax_semantic_verb_consumed_total",
            "Number of semantic-verb consumption attempts, by verb and outcome "
            "(re-registered on compositor REGISTRY for :9482 scrape).",
            ["verb", "outcome"],
            registry=REGISTRY,
        )
        _u5_mod.hapax_semantic_verb_consumed_total = new_counter
    except Exception:
        log.debug(
            "u5 hapax_semantic_verb_consumed_total re-register on compositor REGISTRY failed",
            exc_info=True,
        )

    # Task #129 Stage 3 — per-camera face-obscure counter. Labelled by
    # camera role and a ``has_faces`` flag so dashboards can both track
    # the raw call volume per camera and verify that the detector is
    # actually firing (``has_faces="true"`` rate should track expected
    # operator/guest presence). See
    # ``face_obscure_integration.obscure_frame_for_camera``.
    global HAPAX_FACE_OBSCURE_FRAME_TOTAL
    HAPAX_FACE_OBSCURE_FRAME_TOTAL = Counter(
        "hapax_face_obscure_frame_total",
        "Frames passed through the capture-time face obscure stage, "
        "labelled by camera role and whether any faces were obscured.",
        ["camera_role", "has_faces"],
        registry=REGISTRY,
    )
    global HAPAX_FACE_OBSCURE_ERRORS_TOTAL
    HAPAX_FACE_OBSCURE_ERRORS_TOTAL = Counter(
        # Beta audit F-AUDIT-1061-2 (2026-04-19): separate error counter from
        # the frame counter so Grafana can distinguish a quiet camera (no
        # faces) from a broken pipeline (exception) vs a disabled flag. The
        # fail-closed full-frame mask from F-AUDIT-1061-1 means every increment
        # here corresponds to a frame that WAS egressed as full-grey, never
        # raw.
        "hapax_face_obscure_errors_total",
        "Face-obscure pipeline exceptions, per camera role + exception class. "
        "Every increment corresponds to a fail-closed full-frame mask egressed.",
        ["camera_role", "exception_class"],
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
    # Phase 1 v4l2sink stall detection. Per
    # docs/research/2026-04-20-v4l2sink-stall-prevention.md §13.1.
    V4L2SINK_LAST_FRAME_AGE = Gauge(
        "studio_compositor_v4l2sink_last_frame_seconds_ago",
        "Seconds since the v4l2sink BUFFER probe last fired",
        registry=REGISTRY,
    )
    V4L2SINK_FRAMES_TOTAL = Counter(
        "studio_compositor_v4l2sink_frames_total",
        "Cumulative buffers crossing the v4l2sink sink pad",
        registry=REGISTRY,
    )
    SHMSINK_LAST_FRAME_AGE = Gauge(
        "studio_compositor_shmsink_last_frame_seconds_ago",
        (
            "Seconds since the compositor-side shmsink BUFFER probe last fired. "
            "This is render-to-SHM evidence only, not v4l2/OBS egress truth."
        ),
        registry=REGISTRY,
    )
    SHMSINK_FRAMES_TOTAL = Counter(
        "studio_compositor_shmsink_frames_total",
        (
            "Cumulative buffers crossing the compositor-side shmsink sink pad. "
            "This must not be used as proof that /dev/video42 or OBS received frames."
        ),
        registry=REGISTRY,
    )
    # Cc-task ``compositor-v4l2sink-graph-mutation-stall`` (2026-05-04).
    # Stall detection counters paired with the recovery counter below
    # so a Grafana panel can compute the fraction of stalls that
    # auto-recovered vs. escalated.
    V4L2SINK_STALL_TOTAL = Counter(
        "studio_compositor_v4l2sink_stall_total",
        "Cumulative v4l2sink stalls observed by the watchdog tick.",
        ["reason"],
        registry=REGISTRY,
    )
    V4L2SINK_RECOVERY_TOTAL = Counter(
        "studio_compositor_v4l2sink_recovery_total",
        (
            "Cumulative v4l2sink recovery attempts by outcome — ok / "
            "failed_no_sink / failed_state_change / failed_no_frame / "
            "escalated."
        ),
        ["outcome"],
        registry=REGISTRY,
    )
    V4L2SINK_FD_REOPENS_TOTAL = Counter(
        "hapax_compositor_v4l2_fd_reopens_total",
        "Cumulative v4l2 device fd reopen events (appsink+os.write recovery).",
        registry=REGISTRY,
    )
    V4L2SINK_WRITE_ERRORS_TOTAL = Counter(
        "hapax_compositor_v4l2_write_errors_total",
        "Cumulative os.write() failures to v4l2loopback device.",
        registry=REGISTRY,
    )
    COMP_RUNTIME_FEATURE_ACTIVE = Gauge(
        "studio_compositor_runtime_feature_active",
        (
            "1 when a compositor runtime feature or containment gate is active. "
            "Feature labels include force_cpu, cuda_aggregator, inline_fx, "
            "hero_effect, follow_mode, ward_modulator, direct_v4l2, and "
            "shmsink_bridge."
        ),
        ["feature"],
        registry=REGISTRY,
    )
    GEM_SUBSTRATE_ACTIVE = Gauge(
        "studio_compositor_gem_substrate_active",
        "1 when the GEM Gray-Scott substrate is constructed and renderable.",
        registry=REGISTRY,
    )
    GEM_SUBSTRATE_PAINT_TOTAL = Counter(
        "studio_compositor_gem_substrate_paint_total",
        "Cumulative successful GEM substrate paints beneath the mural text.",
        registry=REGISTRY,
    )
    GEM_SUBSTRATE_STEP_ERRORS_TOTAL = Counter(
        "studio_compositor_gem_substrate_step_errors_total",
        "Cumulative GEM substrate step/paint errors that skipped a substrate frame.",
        registry=REGISTRY,
    )
    GEM_SUBSTRATE_MAX_BRIGHTNESS = Gauge(
        "studio_compositor_gem_substrate_max_brightness",
        "Maximum brightness observed on the latest successful GEM substrate paint.",
        registry=REGISTRY,
    )
    COMP_RENDER_STAGE_FRAMES_TOTAL = Counter(
        "studio_compositor_render_stage_frames_total",
        (
            "Frames observed at named compositor render stages. Used to split "
            "no-output failures into aggregation, CUDA download/caps, FX, "
            "interpipe, and final v4l2 appsink layers."
        ),
        ["stage"],
        registry=REGISTRY,
    )
    COMP_RENDER_STAGE_LAST_FRAME_AGE = Gauge(
        "studio_compositor_render_stage_last_frame_seconds_ago",
        "Seconds since the named compositor render stage last observed a frame.",
        ["stage"],
        registry=REGISTRY,
    )
    # Phase 1 director liveness watchdog per
    # docs/research/2026-04-20-livestream-halt-investigation.md §6.
    DIRECTOR_LAST_INTENT_AGE = Gauge(
        "studio_compositor_director_last_intent_seconds_ago",
        "Seconds since the director last emitted a parsed LLM intent (excluding micromove fallbacks)",
        registry=REGISTRY,
    )
    DIRECTOR_INTENT_TOTAL = Counter(
        "studio_compositor_director_intent_total",
        "Cumulative parsed LLM intents emitted",
        registry=REGISTRY,
    )
    HAPAX_REFUSAL_GATE_REROLLS = Counter(
        "hapax_refusal_gate_rerolls_total",
        "Phase 5 RefusalGate per-emission outcomes (R-Tuning re-roll path).",
        ["surface", "outcome"],
        registry=REGISTRY,
    )
    for _outcome in (
        "accepted_first_pass",
        "accepted_after_reroll",
        "dropped_after_reroll",
    ):
        HAPAX_REFUSAL_GATE_REROLLS.labels(
            surface="director",
            outcome=_outcome,
        ).inc(0)
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

    # Drop #41 (frame budget forensics) C1: per-source frame-time histogram.
    # `BudgetTracker.record(source_id, elapsed_ms)` already collects this
    # data into a rolling window for cost-snapshot publishing, but the
    # window samples are only readable via `costs.json` snapshots. The
    # histogram exposes the same observations to Prometheus so Grafana
    # can answer "which cairo source is closest to starving the layout
    # budget" without scraping the snapshot file. Bucket boundaries match
    # the cairo source render budget (1-100 ms typical, 500-2000 ms tail
    # for outliers like sierpinski with YouTube frames). Labelled by
    # source_id so dashboards can split by per-source contribution.
    COMP_SOURCE_RENDER_DURATION_MS = Histogram(
        "studio_compositor_source_render_duration_ms",
        "Per-source CairoSourceRunner render time per frame, in milliseconds",
        ["source_id"],
        buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2000.0),
        registry=REGISTRY,
    )
    COMP_SOURCE_BACKEND_ERRORS_TOTAL = Counter(
        "studio_compositor_source_backend_errors_total",
        "Layout-declared source backend construction/registration failures; "
        "rising rate means a source can be absent from the rendered layout.",
        ["phase", "source_id", "backend", "exception_class"],
        registry=REGISTRY,
    )
    COMP_STOP_ERRORS_TOTAL = Counter(
        "studio_compositor_stop_errors_total",
        "Compositor teardown component stop exceptions; stop continues after incrementing.",
        ["component", "exception_class"],
        registry=REGISTRY,
    )

    # Drop #37 FX-1: passthrough-slot count. The `SlotPipeline` builds
    # `num_slots=24` fixed GL slots and assigns actual shaders to the
    # subset matching the current preset (typically 5-9 nodes). The
    # unassigned slots run PASSTHROUGH_SHADER which is a no-op but still
    # consumes GPU memory bandwidth and a draw call per frame. This
    # gauge exposes `num_slots - assigned_slots` so Grafana can show
    # how many slots are idle in each preset activation — the raw data
    # that decides whether drop #37 FX-3 (dynamic num_slots) is worth
    # shipping. Pairs with the existing
    # `compositor_glfeedback_recompile_total` counter (drop #5).
    COMP_FX_PASSTHROUGH_SLOTS = Gauge(
        "compositor_fx_passthrough_slots",
        "Number of GL slots running PASSTHROUGH_SHADER (unassigned) in the current SlotPipeline plan",
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

    global COMP_SCALED_BLIT_CACHE_ENTRIES
    COMP_SCALED_BLIT_CACHE_ENTRIES = Gauge(
        "studio_compositor_scaled_blit_cache_entries",
        "Current number of retained Cairo scaled-blit surfaces.",
        registry=REGISTRY,
    )
    global COMP_SCALED_BLIT_CACHE_BYTES
    COMP_SCALED_BLIT_CACHE_BYTES = Gauge(
        "studio_compositor_scaled_blit_cache_bytes",
        "Estimated retained bytes in the Cairo scaled-blit surface cache.",
        registry=REGISTRY,
    )
    global COMP_SCALED_BLIT_CACHE_EVICTIONS_TOTAL
    COMP_SCALED_BLIT_CACHE_EVICTIONS_TOTAL = Counter(
        "studio_compositor_scaled_blit_cache_evictions_total",
        "Scaled-blit cache evictions by reason.",
        ["reason"],
        registry=REGISTRY,
    )
    global COMP_V4L2_APPSINK_COPIED_BYTES_TOTAL
    COMP_V4L2_APPSINK_COPIED_BYTES_TOTAL = Counter(
        "studio_compositor_v4l2_appsink_copied_bytes_total",
        "Bytes copied from the final v4l2 appsink buffer into Python before os.write.",
        registry=REGISTRY,
    )
    global COMP_V4L2_APPSINK_COPIED_FRAMES_TOTAL
    COMP_V4L2_APPSINK_COPIED_FRAMES_TOTAL = Counter(
        "studio_compositor_v4l2_appsink_copied_frames_total",
        "Final v4l2 appsink frames copied into Python before os.write.",
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
    RTMP_SIDE_EFFECT_ERRORS_TOTAL = Counter(
        "studio_rtmp_side_effect_errors_total",
        "Non-fatal RTMP control side-effect failures after attach/detach decisions.",
        ["phase", "exception_class"],
        registry=REGISTRY,
    )
    RTMP_BITRATE_BPS = Gauge(
        "studio_rtmp_bitrate_bps",
        "Rolling 10-second average RTMP bitrate",
        ["endpoint"],
        registry=REGISTRY,
    )
    HAPAX_MOBILE_SUBSTREAM_FRAMES_TOTAL = Counter(
        "hapax_mobile_substream_frames_total",
        "Frames observed on the mobile 9:16 RTMP egress path",
        registry=REGISTRY,
    )
    HAPAX_MOBILE_SUBSTREAM_BITRATE_KBPS = Gauge(
        "hapax_mobile_substream_bitrate_kbps",
        "Configured mobile 9:16 RTMP encoder bitrate in kilobits per second",
        registry=REGISTRY,
    )
    HAPAX_BROADCAST_MODE = Gauge(
        "hapax_broadcast_mode",
        "Current compositor broadcast mode: 0=desktop, 1=mobile, 2=dual",
        registry=REGISTRY,
    )
    HAPAX_BROADCAST_MODE.set(2)
    HAPAX_MOBILE_CAIRO_RENDER_DURATION_MS = Histogram(
        "hapax_mobile_cairo_render_duration_ms",
        "Mobile overlay Cairo render duration in milliseconds",
        buckets=(1.0, 2.5, 5.0, 10.0, 16.0, 25.0, 33.0, 50.0, 100.0, 250.0),
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
    COMP_PROCESS_PID = Gauge(
        "studio_compositor_process_pid",
        "Operating-system PID of this compositor process.",
        registry=REGISTRY,
    )
    COMP_PROCESS_START_TIME = Gauge(
        "studio_compositor_process_start_time_seconds",
        (
            "Unix timestamp recorded when the compositor metrics server started. "
            "Pairs with process_pid so preflight/resource deltas can reject samples "
            "that span a process restart."
        ),
        registry=REGISTRY,
    )
    COMP_PROCESS_MEMORY_BYTES = Gauge(
        "studio_compositor_process_memory_bytes",
        (
            "Selected /proc/self/status memory fields in bytes. Fields include "
            "VmHWM, VmRSS, RssAnon, RssFile, RssShmem, and VmSwap."
        ),
        ["field"],
        registry=REGISTRY,
    )
    COMP_CGROUP_MEMORY_BYTES = Gauge(
        "studio_compositor_cgroup_memory_bytes",
        (
            "Selected cgroup v2 memory controller values for the compositor service "
            "in bytes. Unlimited memory.high/memory.max values are exported as -1."
        ),
        ["field"],
        registry=REGISTRY,
    )
    COMP_CGROUP_MEMORY_EVENTS = Gauge(
        "studio_compositor_cgroup_memory_events",
        (
            "Raw cgroup v2 memory.events counters for the compositor service. "
            "Values reset when systemd recreates the service cgroup."
        ),
        ["event"],
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

    # Task #157 — non-destructive overlay alpha clamp. Incremented once
    # per frame per source when a ``non_destructive=True`` assignment's
    # requested alpha exceeds the 0.6 clamp ceiling. A zero rate means
    # every informational ward is already authored below the ceiling;
    # a persistent rate means the clamp is actively defending camera
    # legibility from ward opacity drift. Labelled by source_id so
    # dashboards can attribute defence events per ward.
    global COMP_NONDESTRUCTIVE_CLAMPS_TOTAL
    COMP_NONDESTRUCTIVE_CLAMPS_TOTAL = Counter(
        "hapax_compositor_nondestructive_clamps_total",
        "Frames where a non_destructive assignment had its alpha clamped "
        "below the requested value, per source.",
        ["source"],
        registry=REGISTRY,
    )

    global HAPAX_FOLLOW_MODE_CUTS_TOTAL
    HAPAX_FOLLOW_MODE_CUTS_TOTAL = Counter(
        "hapax_follow_mode_cuts_total",
        "Hero-camera cuts driven by the follow-mode controller (no manual "
        "override present). Labelled by the previous and new hero role.",
        ["from_role", "to_role"],
        registry=REGISTRY,
    )

    # Task #122 — director-specific degraded hold counter. Increments
    # each time ``DirectorLoop._emit_degraded_silence_hold`` fires (i.e.
    # the LLM tick was skipped because DEGRADED mode was active). The
    # generic ``hapax_degraded_holds_total{surface="director"}`` label
    # covers the same ground, but keeping a dedicated counter lets the
    # Grafana live-change dashboard point at one clean line without
    # filtering by label.
    global DIRECTOR_DEGRADED_HOLDS_TOTAL
    DIRECTOR_DEGRADED_HOLDS_TOTAL = Counter(
        "hapax_director_degraded_holds_total",
        "Director ticks where DEGRADED mode caused the LLM call to be "
        "skipped in favor of a silence-hold fallback intent.",
        registry=REGISTRY,
    )

    # HOMAGE Phase 6 Layer 5 — ward↔FX bidirectional events.
    # ``direction`` ∈ {``ward``, ``fx``}. ``kind`` is the transition (ward
    # side) or FXEventKind (fx side). ``ward_id`` is populated for ward
    # publishes and empty for fx. ``preset_family`` is populated only on
    # fx ``preset_family_change`` events. Cardinality is bounded by the
    # small ward registry + 4 FXEventKinds + 5 preset families.
    global HAPAX_WARD_FX_EVENTS_TOTAL
    HAPAX_WARD_FX_EVENTS_TOTAL = Counter(
        "hapax_ward_fx_events_total",
        "Ward↔FX bidirectional coupling events published on the shared bus.",
        ["direction", "kind", "ward_id", "preset_family"],
        registry=REGISTRY,
    )
    global HAPAX_WARD_FX_LATENCY_SECONDS
    HAPAX_WARD_FX_LATENCY_SECONDS = Histogram(
        "hapax_ward_fx_latency_seconds",
        "Delta between ward↔FX event timestamp and the reactor's response "
        "handler completing its SHM writes.",
        ["direction"],
        buckets=(0.001, 0.002, 0.005, 0.010, 0.020, 0.050, 0.100, 0.200, 0.500, 1.0),
        registry=REGISTRY,
    )

    # Researcher audit (2026-05-03) halftone-monoculture root-cause #3:
    # state.py was swallowing graph/preset load failures (Pydantic
    # ValidationError + assorted shape errors) at DEBUG level, masking a
    # 64% load-fail rate that drove the chain back to atmospheric
    # defaults. Promoting the swallow to WARNING + a Prometheus counter
    # surfaces the failure rate in dashboards. Labels: ``preset`` (the
    # graph name when extractable, ``unknown`` otherwise) and ``reason``
    # (exception class). Cardinality is bounded by the preset registry
    # size × small set of common exception classes.
    global HAPAX_COMPOSITOR_PRESET_LOAD_FAILED_TOTAL
    HAPAX_COMPOSITOR_PRESET_LOAD_FAILED_TOTAL = Counter(
        "hapax_compositor_preset_load_failed_total",
        "Compositor graph/preset load failures (mutation file parse + load + activate path).",
        ["preset", "reason"],
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
_render_stage_last_frame_monotonic: dict[str, float] = {}
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
    if COMP_PROCESS_PID is not None:
        COMP_PROCESS_PID.set(os.getpid())
    if COMP_PROCESS_START_TIME is not None:
        COMP_PROCESS_START_TIME.set(time.time())

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


def set_broadcast_mode(mode: str) -> None:
    """Publish the broadcast-mode enum gauge."""

    if HAPAX_BROADCAST_MODE is None:
        return
    value = {"desktop": 0, "mobile": 1, "dual": 2}.get(mode, 2)
    HAPAX_BROADCAST_MODE.set(value)


def record_refusal_gate_reroll(*, surface: str, outcome: str) -> None:
    """Increment the Phase 5 RefusalGate outcome counter."""

    if HAPAX_REFUSAL_GATE_REROLLS is None:
        return
    HAPAX_REFUSAL_GATE_REROLLS.labels(surface=surface, outcome=outcome).inc()


def record_preset_load_failed(*, preset: str, reason: str) -> None:
    """Increment the compositor preset-load-failure counter.

    Called from the state-reader loop's graph-mutation / fx-request
    paths whenever ``EffectGraph(...)`` parsing or
    ``GraphRuntime.load_graph`` raises. ``preset`` is the graph name
    when extractable (or ``unknown``); ``reason`` is the exception
    class. Researcher audit 2026-05-03 promoted these from a silent
    DEBUG swallow to a loud WARNING + counter so the 64% load-fail
    rate becomes visible in dashboards.
    """

    if HAPAX_COMPOSITOR_PRESET_LOAD_FAILED_TOTAL is None:
        return
    HAPAX_COMPOSITOR_PRESET_LOAD_FAILED_TOTAL.labels(preset=preset, reason=reason).inc()


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
    # A+ Stage 1 (2026-04-17): pad probe hot path ran under the global
    # ``_lock`` at 180Hz (6 cameras × 30fps) and contended with the 1Hz
    # poll loop that also held _lock — measured cost: brio-operator
    # losing ~2fps sustained to lock contention. Python dict single-key
    # __getitem__/__setitem__ are atomic under the GIL; remove the lock
    # from the per-role dict reads/writes in the pad probe path. The
    # 1Hz poll can observe a fractionally stale interleaving between
    # _last_seq and _last_frame_monotonic — tolerable for a per-second
    # averager; no frame-accurate consistency requirement.
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


def set_audio_ducking_state(state: str) -> None:
    """Publish the AudioDuckingController state (CVS #145).

    One-hot: the matching label is set to 1 and all other known labels
    to 0. Unknown labels are accepted silently so callers can't crash
    the poll path if a new state is added.
    """
    if HAPAX_AUDIO_DUCKING_STATE is None:
        return
    for st in ("normal", "voice_active", "yt_active", "both_active"):
        HAPAX_AUDIO_DUCKING_STATE.labels(state=st).set(1 if st == state else 0)


def on_pipeline_restart(pipeline_name: str) -> None:
    if COMP_PIPELINE_RESTARTS_TOTAL is None:
        return
    COMP_PIPELINE_RESTARTS_TOTAL.labels(pipeline=pipeline_name).inc()


def set_runtime_feature_active(feature: str, active: bool) -> None:
    """Publish a compositor runtime feature/containment state.

    This is intentionally generic: live restoration needs one scrape-visible
    row for each switch that can make the surface merely contained instead of
    fully restored.
    """

    if COMP_RUNTIME_FEATURE_ACTIVE is None:
        return
    COMP_RUNTIME_FEATURE_ACTIVE.labels(feature=feature).set(1 if active else 0)


def set_gem_substrate_active(active: bool) -> None:
    if GEM_SUBSTRATE_ACTIVE is None:
        return
    GEM_SUBSTRATE_ACTIVE.set(1 if active else 0)


def record_gem_substrate_paint(max_brightness: float | None = None) -> None:
    set_gem_substrate_active(True)
    if GEM_SUBSTRATE_PAINT_TOTAL is not None:
        GEM_SUBSTRATE_PAINT_TOTAL.inc()
    if GEM_SUBSTRATE_MAX_BRIGHTNESS is not None and max_brightness is not None:
        GEM_SUBSTRATE_MAX_BRIGHTNESS.set(max(0.0, float(max_brightness)))


def record_gem_substrate_step_error() -> None:
    set_gem_substrate_active(False)
    if GEM_SUBSTRATE_STEP_ERRORS_TOTAL is None:
        return
    GEM_SUBSTRATE_STEP_ERRORS_TOTAL.inc()


def set_scaled_blit_cache_state(*, entries: int, bytes_used: int) -> None:
    if COMP_SCALED_BLIT_CACHE_ENTRIES is not None:
        COMP_SCALED_BLIT_CACHE_ENTRIES.set(max(0, entries))
    if COMP_SCALED_BLIT_CACHE_BYTES is not None:
        COMP_SCALED_BLIT_CACHE_BYTES.set(max(0, bytes_used))


def record_scaled_blit_cache_eviction(*, reason: str, count: int = 1) -> None:
    if COMP_SCALED_BLIT_CACHE_EVICTIONS_TOTAL is None or count <= 0:
        return
    COMP_SCALED_BLIT_CACHE_EVICTIONS_TOTAL.labels(reason=reason).inc(count)


def record_v4l2_appsink_copy(size_bytes: int) -> None:
    if size_bytes < 0:
        size_bytes = 0
    if COMP_V4L2_APPSINK_COPIED_BYTES_TOTAL is not None:
        COMP_V4L2_APPSINK_COPIED_BYTES_TOTAL.inc(size_bytes)
    if COMP_V4L2_APPSINK_COPIED_FRAMES_TOTAL is not None:
        COMP_V4L2_APPSINK_COPIED_FRAMES_TOTAL.inc()


def record_render_stage_frame(stage: str) -> None:
    """Record that a frame crossed a named compositor render stage."""

    with _lock:
        _render_stage_last_frame_monotonic[stage] = time.monotonic()
    if COMP_RENDER_STAGE_FRAMES_TOTAL is None:
        return
    COMP_RENDER_STAGE_FRAMES_TOTAL.labels(stage=stage).inc()


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
        _render_stage_last_frame_monotonic.clear()


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
            render_stage_ages = [
                (stage, now - last_mono if last_mono > 0 else float("inf"))
                for stage, last_mono in _render_stage_last_frame_monotonic.items()
            ]

        if CAM_LAST_FRAME_AGE is None:
            continue

        for role, age, model in ages:
            CAM_LAST_FRAME_AGE.labels(role=role, model=model).set(age)

        if COMP_RENDER_STAGE_LAST_FRAME_AGE is not None:
            for stage, age in render_stage_ages:
                COMP_RENDER_STAGE_LAST_FRAME_AGE.labels(stage=stage).set(age)

        if COMP_UPTIME is not None and boot > 0:
            COMP_UPTIME.set(now - boot)
        if COMP_WATCHDOG_LAST_FED is not None and wd_age >= 0:
            COMP_WATCHDOG_LAST_FED.set(wd_age)

        _update_memory_footprint()
        _update_gpu_vram()
        _mirror_reverie_pool_metrics()
        _mirror_imagination_shader_health()


def _parse_proc_status_memory_bytes(text: str) -> dict[str, int]:
    """Parse selected ``/proc/self/status`` memory fields into bytes."""

    parsed: dict[str, int] = {}
    for line in text.splitlines():
        key, sep, rest = line.partition(":")
        if sep != ":" or key not in _PROC_STATUS_MEMORY_FIELDS:
            continue
        parts = rest.split()
        if len(parts) < 2 or parts[1] != "kB":
            continue
        try:
            parsed[key] = int(parts[0]) * 1024
        except ValueError:
            continue
    return parsed


def _parse_cgroup_scalar_bytes(text: str) -> float:
    """Parse a cgroup memory scalar.

    cgroup v2 reports unlimited controls as the literal ``max``. Export
    those as ``-1`` rather than ``+Inf`` so JSON/preflight consumers do
    not have to special-case non-finite values.
    """

    stripped = text.strip()
    if stripped == "max":
        return -1.0
    return float(int(stripped))


def _parse_cgroup_events(text: str) -> dict[str, float]:
    """Parse cgroup v2 ``memory.events`` contents."""

    events: dict[str, float] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            events[parts[0]] = float(int(parts[1]))
        except ValueError:
            continue
    return events


def _self_cgroup_path() -> Path | None:
    """Return this process's cgroup v2 path under ``/sys/fs/cgroup``."""

    try:
        with open("/proc/self/cgroup", encoding="ascii") as fh:
            for line in fh:
                parts = line.strip().split(":", 2)
                if len(parts) == 3 and parts[0] == "0":
                    return Path("/sys/fs/cgroup") / parts[2].lstrip("/")
    except OSError:
        return None
    return None


def _update_memory_footprint() -> None:
    """Publish process and cgroup memory gauges for this compositor.

    Reads procfs/cgroupfs directly to avoid pulling psutil into the
    compositor. Swallows IO errors because the metrics poll loop must not
    crash on a transient filesystem race.
    """
    try:
        with open("/proc/self/status", encoding="ascii") as fh:
            memory_fields = _parse_proc_status_memory_bytes(fh.read())
    except (OSError, ValueError, IndexError):
        memory_fields = {}

    if COMP_MEMORY_FOOTPRINT is not None and "VmRSS" in memory_fields:
        COMP_MEMORY_FOOTPRINT.set(memory_fields["VmRSS"])
    if COMP_PROCESS_MEMORY_BYTES is not None:
        for field, value in memory_fields.items():
            COMP_PROCESS_MEMORY_BYTES.labels(field=field).set(value)

    cgroup_path = _self_cgroup_path()
    if cgroup_path is None:
        return
    if COMP_CGROUP_MEMORY_BYTES is not None:
        for field, filename in _CGROUP_MEMORY_FILES.items():
            try:
                value = _parse_cgroup_scalar_bytes((cgroup_path / filename).read_text())
            except (OSError, ValueError):
                continue
            COMP_CGROUP_MEMORY_BYTES.labels(field=field).set(value)
    if COMP_CGROUP_MEMORY_EVENTS is not None:
        try:
            events = _parse_cgroup_events((cgroup_path / "memory.events").read_text())
        except OSError:
            events = {}
        for event, value in events.items():
            COMP_CGROUP_MEMORY_EVENTS.labels(event=event).set(value)


def record_tts_client_timeout() -> None:
    """Called by DaimonionTtsClient on readall timeout (queue 023 item #32)."""
    if COMP_TTS_CLIENT_TIMEOUT_TOTAL is None:
        return
    COMP_TTS_CLIENT_TIMEOUT_TOTAL.inc()


def record_face_obscure_frame(camera_role: str, has_faces: bool) -> None:
    """Record a capture-time face-obscure call (task #129 Stage 3).

    Called from ``face_obscure_integration.obscure_frame_for_camera`` on every
    invocation, regardless of whether the feature flag is on — a disabled
    stage is still observable as ``has_faces="false"`` so Grafana can alert
    if the counter ever flat-lines across all cameras. No-op if
    prometheus_client is unavailable.
    """
    if HAPAX_FACE_OBSCURE_FRAME_TOTAL is None:
        return
    HAPAX_FACE_OBSCURE_FRAME_TOTAL.labels(
        camera_role=camera_role,
        has_faces="true" if has_faces else "false",
    ).inc()


def record_follow_mode_cut(from_role: str, to_role: str) -> None:
    """Task #136 — count a follow-mode-driven hero camera cut.

    Called from ``state.py``'s hero-override consumer when the
    fallback path (no manual override) applied the follow-mode
    recommendation. ``from_role`` may be ``""`` on the very first
    cut (before any hero was set); Grafana should treat that as a
    'cold-start' label rather than a missing value. No-op if
    prometheus_client is unavailable.
    """
    if HAPAX_FOLLOW_MODE_CUTS_TOTAL is None:
        return
    HAPAX_FOLLOW_MODE_CUTS_TOTAL.labels(
        from_role=from_role or "",
        to_role=to_role,
    ).inc()


def record_face_obscure_error(camera_role: str, exception_class: str) -> None:
    """Record a fail-closed face-obscure error (beta audit F-AUDIT-1061-2).

    Called from the exception handler in
    ``face_obscure_integration.obscure_frame_for_camera`` when the SCRFD/
    Kalman/OpenCV pipeline raises. Every increment corresponds to a fail-
    closed full-frame Gruvbox-dark mask egressed — NEVER a raw frame. Grafana
    should alert on non-zero rate: privacy-critical surfaces must not have
    a silent broken pipeline. No-op if prometheus_client is unavailable.
    """
    if HAPAX_FACE_OBSCURE_ERRORS_TOTAL is None:
        return
    HAPAX_FACE_OBSCURE_ERRORS_TOTAL.labels(
        camera_role=camera_role,
        exception_class=exception_class,
    ).inc()


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
