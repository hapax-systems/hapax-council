"""Lifecycle management: start and stop the compositor pipeline."""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
from typing import Any

from shared.control_signal import ControlSignal, publish_health

from .config import PERCEPTION_STATE_PATH
from .consent import log_consent_event

log = logging.getLogger(__name__)


def _startup_preset_name() -> str | None:
    raw = os.environ.get("HAPAX_COMPOSITOR_STARTUP_PRESET", "sierpinski_line_overlay").strip()
    if raw.lower() in {"", "0", "false", "no", "none", "off", "disabled"}:
        return None
    return raw


def apply_startup_preset(compositor: Any) -> str | None:
    preset_name = _startup_preset_name()
    if preset_name is None:
        log.info("Default startup preset disabled")
        return None
    from .effects import try_graph_preset

    if try_graph_preset(compositor, preset_name):
        compositor._current_preset_name = preset_name
        log.info("Default startup preset: %s", preset_name)
    else:
        log.warning("Default startup preset %s could not be activated", preset_name)
    return preset_name


def _log_feature_probes(compositor: Any) -> None:
    """Log one INFO line per optional subsystem probe (Phase 10 D3).

    Stable format: ``feature-probe: NAME=BOOL`` so `grep -e
    'feature-probe:' journalctl` gives a clean per-boot inventory.
    Each probe is isolated in its own try/except so any one probe
    failing still lets the rest report.
    """
    probes: list[tuple[str, bool]] = []

    try:
        from agents.studio_compositor import metrics as _comp_metrics

        probes.append(("prometheus_client", _comp_metrics.REGISTRY is not None))
    except Exception:
        probes.append(("prometheus_client", False))

    try:
        from agents.studio_compositor.budget import BudgetTracker

        tracker = getattr(compositor, "_budget_tracker", None)
        probes.append(("budget_tracker_active", isinstance(tracker, BudgetTracker)))
    except Exception:
        probes.append(("budget_tracker_active", False))

    try:
        from agents.studio_fx.gpu import has_cuda

        probes.append(("opencv_cuda", has_cuda()))
    except Exception:
        probes.append(("opencv_cuda", False))

    try:
        probes.append(("output_router", getattr(compositor, "output_router", None) is not None))
    except Exception:
        probes.append(("output_router", False))

    try:
        from agents.studio_compositor.cairo_sources import list_classes

        probes.append(
            ("research_marker_overlay_registered", "ResearchMarkerOverlay" in list_classes())
        )
    except Exception:
        probes.append(("research_marker_overlay_registered", False))

    for name, value in probes:
        log.info("feature-probe: %s=%s", name, str(value).lower())


def _record_watchdog_ping_metrics(compositor: Any) -> None:
    """Mirror every systemd WATCHDOG=1 ping into Prometheus gauges."""

    try:
        from . import metrics

        metrics.mark_watchdog_fed()
        if metrics.V4L2SINK_LAST_FRAME_AGE is not None:
            age = (
                time.monotonic() - compositor._v4l2_last_frame_monotonic
                if compositor._v4l2_last_frame_monotonic > 0
                else 9999.0
            )
            metrics.V4L2SINK_LAST_FRAME_AGE.set(age)
        if metrics.SHMSINK_LAST_FRAME_AGE is not None:
            age = (
                time.monotonic() - compositor._shmsink_last_frame_monotonic
                if compositor._shmsink_last_frame_monotonic > 0
                else 9999.0
            )
            metrics.SHMSINK_LAST_FRAME_AGE.set(age)
        if metrics.DIRECTOR_LAST_INTENT_AGE is not None:
            try:
                from .director_loop import director_intent_age

                metrics.DIRECTOR_LAST_INTENT_AGE.set(min(director_intent_age(), 9999.0))
            except Exception:
                pass
    except Exception:
        pass


def _hero_effect_target_for_prefx(compositor: Any) -> tuple[str, Any] | None:
    """Return the hero camera role and tile rect for the pre-FX effect."""
    try:
        from .layout import compute_tile_layout

        layout = compute_tile_layout(compositor.config.cameras)
        cameras = compositor.config.cameras
        for cam in cameras:
            if getattr(cam, "hero", False) and cam.role in layout:
                tile = layout[cam.role]
                if tile.w > 0 and tile.h > 0:
                    return cam.role, tile
    except Exception:
        log.debug("_hero_effect_target_for_prefx failed", exc_info=True)
    return None


def start_compositor(compositor: Any) -> None:
    """Build and start the pipeline."""
    from .fx_chain import fx_tick_callback
    from .pipeline import build_pipeline, init_gstreamer
    from .state import state_reader_loop

    compositor._GLib, compositor._Gst = init_gstreamer()
    GLib = compositor._GLib
    Gst = compositor._Gst

    # Phase 10 / delta metric-coverage-gaps D3 — announce every
    # optional subsystem that was probed at startup, so latent-
    # feature disables (CUDA, BudgetTracker, prometheus_client,
    # OpenCV-CUDA) are loud rather than silent. One line per probe,
    # stable key names for grep. Delta's drop #1 and drop #6 each
    # spent investigation cycles on features that were installed but
    # runtime-disabled; this probe log would have caught both on day 1.
    _log_feature_probes(compositor)

    # Phase A5 (homage-completion-plan §3.3) — probe HOMAGE-required
    # fonts at startup so a missing Px437 IBM VGA 8x16 becomes a loud
    # WARN rather than silently falling back to DejaVu Sans Mono on
    # every ward render.
    try:
        from agents.studio_compositor.text_render import warn_if_missing_homage_fonts

        warn_if_missing_homage_fonts()
    except Exception:
        log.exception("warn_if_missing_homage_fonts raised (non-fatal)")

    log.info("Building compositor pipeline with %d cameras", len(compositor.config.cameras))

    with compositor._camera_status_lock:
        for cam in compositor.config.cameras:
            compositor._camera_status[cam.role] = "starting"

    compositor.pipeline = build_pipeline(compositor)

    # Hero small overlay: PIP "raw monitor" inset of the hero camera's
    # snapshot, drawn on the post-FX cairooverlay. The _hero_small tile
    # rect is added by _balanced_layout when a hero camera exists.
    compositor._hero_small = None
    compositor._hero_effect_rotator = None
    small_rect = None
    try:
        from .hero_small_overlay import HeroSmallOverlay
        from .layout import compute_tile_layout

        layout = compute_tile_layout(compositor.config.cameras)
        small_rect = layout.get("_hero_small")
        heroes = [c for c in compositor.config.cameras if c.hero]
        if small_rect is not None and heroes:
            compositor._hero_small = HeroSmallOverlay(
                heroes[0].role,
                small_rect.x,
                small_rect.y,
                small_rect.w,
                small_rect.h,
            )
    except Exception:
        log.exception("HeroSmallOverlay init failed (non-fatal)")

    # Hero effect rotator (gap #15 stage-1 wiring): cycles spatial effects on
    # the hero camera tile. Instantiate, connect tile rect, register tick.
    # The rotator's _slot binding to a glfeedback pipeline element is deferred
    # — tick() is a no-op until set_slot() is called. Wiring it now means the
    # tile rect tracks layout changes and the tick is live the moment a slot
    # is bound, with no further lifecycle changes required.
    try:
        from .hero_effect_rotator import HeroEffectRotator

        compositor._hero_effect_rotator = HeroEffectRotator()
        if small_rect is not None:
            compositor._hero_effect_rotator.update_hero_tile(small_rect)
    except Exception:
        log.exception("HeroEffectRotator init failed (non-fatal)")

    # Hero pre-FX effect: software-based hero effect applied on the pre_fx
    # Cairo layer so it goes through the shader chain. Replaces the GL-pipeline
    # hero-effect-slot when HAPAX_COMPOSITOR_DISABLE_HERO_EFFECT=1.
    # Resolves hero tile position dynamically at draw time.
    compositor._hero_prefx_effect = None
    try:
        from .hero_prefx_effect import HeroPreFxEffect

        compositor._hero_prefx_effect = HeroPreFxEffect()
    except Exception:
        log.exception("HeroPreFxEffect init failed (non-fatal)")

    # Read initial consent state
    try:
        if PERCEPTION_STATE_PATH.exists():
            raw = PERCEPTION_STATE_PATH.read_text()
            initial = json.loads(raw)
            if time.time() - initial.get("timestamp", 0) < 10:
                if not initial.get("persistence_allowed", True):
                    compositor._consent_recording_allowed = False
                    for valve in compositor._recording_valves.values():
                        valve.set_property("drop", True)
                    if compositor._hls_valve is not None:
                        compositor._hls_valve.set_property("drop", True)
                    log.warning("Starting with recording BLOCKED (consent not available)")
    except Exception:
        log.debug("Failed to read initial consent state", exc_info=True)

    bus = compositor.pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", compositor._on_bus_message)

    compositor._write_status("starting")

    if hasattr(compositor, "_v4l2_output_pipeline"):
        compositor._v4l2_output_pipeline.start()
        log.info("V4l2OutputPipeline started (interpipeline isolation active)")
        import time as _time

        for _i in range(50):
            if compositor._v4l2_output_pipeline.is_alive(threshold_s=2.0):
                break
            _time.sleep(0.01)

    ret = compositor.pipeline.set_state(Gst.State.PLAYING)
    if ret == Gst.StateChangeReturn.FAILURE:
        log.error("Pipeline set_state(PLAYING) returned FAILURE — attempting recovery")
        with compositor._camera_status_lock:
            offline = [r for r, s in compositor._camera_status.items() if s != "offline"]
        for role in offline:
            compositor._mark_camera_offline(role)
        compositor._write_status("degraded")
        ret2 = compositor.pipeline.set_state(Gst.State.PLAYING)
        if ret2 == Gst.StateChangeReturn.FAILURE:
            compositor._write_status("error")
            raise RuntimeError("Failed to start pipeline after recovery attempt")

    try:
        from .shmsink_output_pipeline import is_bridge_enabled, is_v4l2_output_disabled

        if not is_v4l2_output_disabled() and hasattr(compositor, "_v4l2_output_pipeline"):
            grace_s = float(os.environ.get("HAPAX_COMPOSITOR_STARTUP_EGRESS_GRACE_S", "6.0"))
            deadline = time.monotonic() + max(0.5, grace_s)
            while time.monotonic() < deadline:
                if is_bridge_enabled():
                    if compositor.shmsink_frame_seen_within(2.0):
                        break
                elif compositor.v4l2_frame_seen_within(2.0):
                    break
                time.sleep(0.05)
            else:
                compositor._write_status("error")
                log.error(
                    "Pipeline started but no initial compositor egress frame arrived within %.1fs",
                    grace_s,
                )
                raise RuntimeError("No initial compositor egress frame after pipeline start")
    except RuntimeError:
        raise
    except Exception:
        log.exception("initial compositor egress gate failed unexpectedly")

    log.info("Pipeline started -- output on %s", compositor.config.output_device)

    with compositor._camera_status_lock:
        for role, status in compositor._camera_status.items():
            if status == "starting":
                compositor._camera_status[role] = "active"

    compositor._running = True
    compositor._audio_capture.start()
    compositor._sync_mobile_support_threads()

    # CVS #145 — instantiate + start the bidirectional audio ducking
    # controller. Even with ``HAPAX_AUDIO_DUCKING_ACTIVE`` off, the FSM
    # ticks and publishes ``hapax_audio_ducking_state{state=...}`` so
    # Grafana can observe the state trajectory without the PipeWire
    # gains being dispatched. Without this wiring the gauge is frozen
    # at startup value (normal=1, others=0) forever — an 8th E2E smoketest
    # flagged the missing runtime updates at :9482.
    try:
        from .audio_ducking import AudioDuckingController

        compositor._audio_ducking = AudioDuckingController()
        compositor._audio_ducking.start()
        log.info("AudioDuckingController started (CVS #145) — state gauge live")
    except Exception:
        log.exception("AudioDuckingController start failed (non-fatal)")

    # CVS #149: register backing-mix sources on the unified reactivity bus.
    # Feature-flagged OFF by default; registration happens regardless so
    # the bus observability surface is live, but consumers only read from
    # it when ``HAPAX_UNIFIED_REACTIVITY_ACTIVE`` is set.
    try:
        from agents.studio_compositor.reactivity_adapters import (
            register_default_sources,
        )

        register_default_sources(compositor._audio_capture)
    except Exception:
        log.debug("unified-reactivity: register_default_sources failed", exc_info=True)

    compositor._write_status("running")

    # Startup preset disabled: SlotDriftEngine owns all shader slots
    # exclusively. Preset plan activation (sierpinski_line_overlay) was
    # loading edge_detect/sierpinski_lines into slots 0-2 then getting
    # immediately overwritten by drift boot — creating a visible flash
    # and competing fragment set_property calls.
    # apply_startup_preset(compositor)
    log.info("Startup preset skipped — SlotDriftEngine is sole shader owner")
    log_consent_event(compositor, "pipeline_start", allowed=compositor._consent_recording_allowed)

    with compositor._camera_status_lock:
        cameras_active = sum(1 for s in compositor._camera_status.values() if s == "active")
    publish_health(
        ControlSignal(
            component="compositor",
            reference=1.0,
            perception=1.0 if cameras_active > 0 else 0.0,
        )
    )

    # Control law: no cameras → skip compositing
    _comp_errors = getattr(compositor, "_cl_errors", 0)
    _comp_ok = getattr(compositor, "_cl_ok", 0)
    _comp_deg = getattr(compositor, "_cl_degraded", False)
    if cameras_active == 0:
        _comp_errors += 1
        _comp_ok = 0
    else:
        _comp_errors = 0
        _comp_ok += 1

    if _comp_errors >= 3 and not _comp_deg:
        _comp_deg = True
        log.warning("Control law [compositor]: degrading — no cameras, skipping compositing")

    if _comp_ok >= 5 and _comp_deg:
        _comp_deg = False
        log.info("Control law [compositor]: recovered")

    compositor._cl_errors = _comp_errors
    compositor._cl_ok = _comp_ok
    compositor._cl_degraded = _comp_deg

    _register_purge_handler(compositor)

    compositor.loop = GLib.MainLoop()

    interval_ms = int(compositor.config.status_interval_s * 1000)
    compositor._status_timer_id = GLib.timeout_add(interval_ms, compositor._status_tick)
    compositor._broadcast_mode_timer_id = GLib.timeout_add(1000, compositor._broadcast_mode_tick)
    activity_router = getattr(compositor, "_activity_router", None)
    if activity_router is not None:
        cfg = getattr(activity_router, "_config", None)
        tick_hz = float(getattr(cfg, "tick_hz", 2.0))
        router_interval_ms = int(1000 / max(0.1, tick_hz))
        compositor._activity_router_timer_id = GLib.timeout_add(
            router_interval_ms,
            compositor._activity_router_tick,
        )
        log.info("ActivityRouter tick scheduled at %.2f Hz", tick_hz)

    GLib.timeout_add(33, lambda: fx_tick_callback(compositor))  # 30fps uniform updates

    # HOMAGE Phase 6 Layer 5 — instantiate the ward↔FX reactor and connect
    # it to the bus. Must run after fx_tick_callback registration so the
    # first tick that publishes audio-reactive FX events already has a
    # subscriber listening. Idempotent in testing (reset_bus_for_testing
    # drops subscribers between cases). Best-effort: a reactor failure
    # is non-fatal — the bus still publishes, just without consumers.
    try:
        from agents.studio_compositor.fx_chain_ward_reactor import WardFxReactor

        compositor._ward_fx_reactor = WardFxReactor()
        compositor._ward_fx_reactor.connect()
        log.info("ward↔FX bidirectional reactor connected")
    except Exception:
        log.warning("ward_fx_reactor connect failed", exc_info=True)

    # 3D compositor Phase 4 — continuous camera publisher.
    # Publishes all camera JPEG snapshots as RGBA to the source protocol
    # so the 3D SceneRenderer can display them as textured quads.
    # Independent of GStreamer pipeline state.
    try:
        from agents.studio_compositor.camera_publisher import CameraSourcePublisher

        compositor._camera_publisher = CameraSourcePublisher()
        compositor._camera_publisher.start()
    except Exception:
        log.warning("CameraSourcePublisher start failed", exc_info=True)

    # Phase 10 observability polish — publish BudgetTracker snapshots + the
    # degraded signal every second. Closes the dead-path finding from delta's
    # 2026-04-14 compositor frame budget forensics drop: prior to this timer
    # _PUBLISH_COSTS_FRESHNESS + _PUBLISH_DEGRADED_FRESHNESS stayed at
    # age_seconds=+Inf for the lifetime of the process.
    def _compositor_budget_publish_tick() -> bool:
        tracker = getattr(compositor, "_budget_tracker", None)
        if tracker is None:
            return compositor._running
        try:
            from pathlib import Path

            from agents.studio_compositor.budget import publish_costs
            from agents.studio_compositor.budget_signal import publish_degraded_signal

            publish_costs(tracker, Path("/dev/shm/hapax-compositor/costs.json"))
            publish_degraded_signal(tracker)
        except Exception:
            log.debug("compositor budget publish tick failed", exc_info=True)
        return compositor._running

    GLib.timeout_add(1000, _compositor_budget_publish_tick)

    # Hero effect rotator tick (gap #15 stage-1): drives the rotator's internal
    # rotation timer. Rotation interval is 45–90s (random), so a 5s tick is
    # plenty cheap and avoids burning the main loop on a no-op when no slot
    # is bound. tick() returns None and early-exits when _slot is None or no
    # effects are loaded; registering the timer now means the moment a future
    # PR binds a glfeedback element via set_slot(), rotation is live.
    def _hero_effect_rotator_tick() -> bool:
        rotator = getattr(compositor, "_hero_effect_rotator", None)
        if rotator is not None:
            try:
                rotator.tick()
            except Exception:
                log.debug("hero_effect_rotator.tick raised", exc_info=True)
        return compositor._running

    GLib.timeout_add(5000, _hero_effect_rotator_tick)

    # Phase 3: start the udev monitor so USB add/remove events drive the
    # per-camera state machine. Runs in-process via pyudev.glib bridged to
    # the GLib main loop.
    pm = getattr(compositor, "_pipeline_manager", None)
    if pm is not None:
        try:
            from .udev_monitor import UdevCameraMonitor

            compositor._udev_monitor = UdevCameraMonitor(pipeline_manager=pm)
            compositor._udev_monitor.start()
        except Exception:
            log.exception("udev camera monitor start failed (non-fatal)")

    # Phase 4: start the Prometheus metrics HTTP server on 127.0.0.1:9482
    # (bound 0.0.0.0 for docker bridge reachability). Scraped by the
    # workstation's Docker Prometheus container via host.docker.internal.
    try:
        from . import metrics

        metrics.start_metrics_server(port=9482, addr="0.0.0.0")
    except Exception:
        log.exception("metrics server start failed (non-fatal)")

    # sd_notify integration — see docs/superpowers/plans/2026-04-12-camera-247-resilience-epic.md § 1.6
    # Once the pipeline is PLAYING and at least one camera is active, signal
    # systemd Type=notify that we are READY. If no cameras ever came up,
    # systemd's start timeout will eventually fail the unit via normal means.
    try:
        from .__main__ import sd_notify_ready, sd_notify_status, sd_notify_watchdog

        sd_notify_ready()
        sd_notify_status(f"{cameras_active}/{len(compositor._camera_status)} cameras live")

        def _watchdog_tick() -> bool:
            # Conjoin two liveness gates: (1) at least one camera is
            # active (existing); (2) v4l2sink pushed a frame within the
            # last 20s (Phase 1 stall detection). Either silent for >20s
            # and the watchdog ping stops; systemd WatchdogSec=60s then
            # SIGABRTs the unit. Closes the same coverage gap that
            # allowed the 2026-04-14 78-min silent stall + 2026-04-20
            # stall — cameras stayed live but v4l2sink branch went
            # silent to OBS. Ref:
            # docs/research/2026-04-20-v4l2sink-stall-prevention.md §8.
            with compositor._camera_status_lock:
                any_active = any(s == "active" for s in compositor._camera_status.values())
            try:
                from .shmsink_output_pipeline import is_bridge_enabled, is_v4l2_output_disabled

                bridge_enabled = is_bridge_enabled()
                v4l2_output_disabled = is_v4l2_output_disabled()
            except Exception:
                bridge_enabled = False
                v4l2_output_disabled = False
            if v4l2_output_disabled:
                # Explicit incident containment: absence of OBS/v4l2 egress is
                # known and must not make the compositor self-kill. The
                # live-surface preflight still refuses to call this restored.
                v4l2_alive = True
            elif bridge_enabled:
                # The compositor watchdog may use render-to-SHM freshness for
                # the shmsink bridge path, but this is not v4l2/OBS egress
                # truth. The bridge sidecar and OBS-visible device are checked
                # by the live-surface preflight/guard.
                v4l2_alive = compositor.shmsink_frame_seen_within(45.0)
            else:
                v4l2_alive = compositor.v4l2_frame_seen_within(45.0)
            v4l2_pipe = getattr(compositor, "_v4l2_output_pipeline", None)
            if (
                not v4l2_output_disabled
                and not bridge_enabled
                and v4l2_pipe is not None
                and v4l2_pipe.last_frame_age_seconds >= 45.0
            ):
                v4l2_alive = False
            # Director liveness gate (Phase 1 per
            # docs/research/2026-04-20-livestream-halt-investigation.md §6).
            # 180s = 6 PERCEPTION_INTERVAL ticks. A single-tick LLM timeout
            # doesn't trigger (existing micromove fallback handles it);
            # sustained silence does. Recovers from TabbyAPI hangs, CUDA
            # context loss, LiteLLM gateway deadlock, _call_activity_llm
            # urlopen blocking past timeout, and any director-thread
            # deadlock — all classes of failure invisible to systemd.
            try:
                from .director_loop import director_intent_age

                director_alive = director_intent_age() < 180.0
            except Exception:
                director_alive = True  # fail-open if module not yet imported
            if any_active and v4l2_alive and director_alive and compositor._running:
                sd_notify_watchdog()
                _record_watchdog_ping_metrics(compositor)
            elif any_active and not v4l2_alive:
                # Direct GL chain death detection — if the GL output probe
                # hasn't fired for >30s, the GL chain is dead. Exit
                # immediately rather than waiting for gray tolerance.
                _GL_DEATH_THRESHOLD_S = 30.0
                gl_ts = getattr(compositor, "_gl_last_frame_monotonic", 0.0)
                if gl_ts > 0.0 and (time.monotonic() - gl_ts) > _GL_DEATH_THRESHOLD_S:
                    log.error(
                        "GL chain dead (no output for %.0fs) — exiting for restart",
                        time.monotonic() - gl_ts,
                    )
                    sd_notify_status("FATAL — GL chain dead, restarting")
                    import os

                    os._exit(1)

                if bridge_enabled:
                    log.error(
                        "shmsink bridge stalled — withholding watchdog ping for compositor restart"
                    )
                    sd_notify_status("FATAL — shmsink bridge stalled, withholding watchdog ping")
                    return compositor._running

                # v4l2sink stall recovery. Ping the watchdog while recovery
                # still has a bounded chance; once the recovery state declares
                # escalation, stop pinging and let systemd's watchdog restart.
                from .v4l2_stall_recovery import attempt_recovery, should_escalate

                stall_start = getattr(compositor, "_v4l2_stall_start", 0.0)
                now_mono = time.monotonic()
                if stall_start == 0.0:
                    compositor._v4l2_stall_start = now_mono
                    stall_start = now_mono

                recovered = attempt_recovery(compositor, compositor._v4l2_recovery_state)
                if recovered:
                    sd_notify_status("DEGRADED — v4l2sink stalled then recovered via sink reattach")
                    compositor._v4l2_stall_start = 0.0
                elif should_escalate(compositor._v4l2_recovery_state):
                    log.error(
                        "v4l2sink stall unrecoverable for %.0fs — withholding watchdog ping",
                        now_mono - stall_start,
                    )
                    sd_notify_status(
                        "FATAL — v4l2sink stall unrecoverable, withholding watchdog ping"
                    )
                    return compositor._running
                else:
                    sd_notify_status("DEGRADED — v4l2sink stalled, retrying recovery")
                    log.warning(
                        "v4l2sink stall (%.0fs elapsed) — keeping alive",
                        now_mono - stall_start,
                    )
                sd_notify_watchdog()
                _record_watchdog_ping_metrics(compositor)
            elif any_active and v4l2_alive and not director_alive:
                sd_notify_status("DEGRADED — director silent for >180s")
                sd_notify_watchdog()
                _record_watchdog_ping_metrics(compositor)
            return compositor._running  # keep firing while compositor is alive

        # 20s interval keeps us well under the 60s WatchdogSec.
        GLib.timeout_add(20 * 1000, _watchdog_tick)
    except Exception:
        log.exception("sd_notify wiring failed (non-fatal)")

    if compositor.config.overlay_enabled:
        compositor._state_reader_thread = threading.Thread(
            target=lambda: state_reader_loop(compositor), daemon=True, name="state-reader"
        )
        compositor._state_reader_thread.start()

    # u6-periodic-tick-driver (cc-task u6-periodic-tick-driver, 2026-05-03):
    # start the layout-tick daemon thread that periodically calls
    # apply_layout_switch with live state. Without this driver the
    # ``hapax_compositor_layout_active`` gauge stays pinned at
    # ``garage-door`` (the LayoutStore default) and the surface never
    # cycles. Env-flag ``HAPAX_LAYOUT_TICK_DISABLED=1`` disables. See
    # ``agents/studio_compositor/layout_tick_driver.py``.
    try:
        from .layout_tick_driver import start_layout_tick_driver

        start_layout_tick_driver(compositor)
    except Exception:
        log.exception("layout-tick driver startup failed (non-fatal)")

    # u4 micromove + u5 semantic-verb consumers (cc-tasks u4 + u5,
    # 2026-05-03): start daemon drivers that fire the substrates
    # shipped via PRs #2368/#2371 so their Prometheus counters
    # (``hapax_micromove_advance_total``, ``hapax_semantic_verb_consumed_total``)
    # actually move. Env-flags ``HAPAX_U4_MICROMOVE_DISABLED=1`` /
    # ``HAPAX_U5_VERB_DISABLED=1`` disable independently. See
    # ``agents/studio_compositor/u_series_drivers.py``.
    try:
        from .u_series_drivers import start_u_series_drivers

        start_u_series_drivers(compositor)
    except Exception:
        log.exception("u4/u5 drivers startup failed (non-fatal)")

    # FINDING-B remediation (alpha wiring audit 2026-04-19):
    # HomageChoreographer was defined but never instantiated — `grep -r` of
    # the agents/ and shared/ trees returns zero import/construction sites.
    # All 4 homage SHM publishers (active-artefact, pending-transitions,
    # substrate-package, voice-register) have been frozen at ~02:29Z
    # because no thread drives reconcile(). This cascades to FINDING-A
    # (ward_fx_events empty ward_id labels) and FINDING-K (10/11 homage
    # metrics empty). The ~30-line fix alpha prescribed:
    # instantiate + schedule reconcile() on a 1Hz GLib timeout, pass the
    # source registry so substrate declarations are honoured.
    try:
        from .homage.choreographer import Choreographer
        from .homage.rendering import active_package

        compositor._homage_choreographer = Choreographer(
            source_registry=getattr(compositor, "source_registry", None),
        )

        def _choreographer_tick() -> bool:
            if not compositor._running:
                return False  # stop firing on shutdown
            try:
                pkg = active_package()
                compositor._homage_choreographer.reconcile(pkg)
            except Exception:
                log.exception("homage choreographer reconcile failed")
            return True  # keep firing while compositor is alive

        # 1 Hz reconcile cadence matches the pre-existing SHM publisher
        # invariants other wards depend on (pending-transitions drain,
        # substrate broadcast, voice-register rotation, artefact cycle).
        GLib.timeout_add(1000, _choreographer_tick)
        log.info("Choreographer instantiated, reconcile scheduled at 1Hz")
    except Exception:
        log.exception("Choreographer wiring failed — FINDING-B unresolved")

    def _shutdown(signum: int, frame: Any) -> None:
        log.info("Signal %d received, shutting down", signum)
        compositor.stop()

    def _rebuild_v4l2_output(signum: int, frame: Any) -> None:
        v4l2_pipe = getattr(compositor, "_v4l2_output_pipeline", None)
        if v4l2_pipe is None:
            log.warning("SIGUSR1: no V4l2OutputPipeline to rebuild")
            return
        log.info("SIGUSR1: rebuilding V4l2OutputPipeline (external watchdog request)")
        GLib = compositor._GLib
        GLib.idle_add(lambda: v4l2_pipe.rebuild() or False)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGUSR1, _rebuild_v4l2_output)

    try:
        compositor.loop.run()
    except KeyboardInterrupt:
        compositor.stop()


def stop_compositor(compositor: Any) -> None:
    """Stop the pipeline cleanly."""
    if not compositor._running:
        return
    log_consent_event(compositor, "pipeline_stop", allowed=compositor._consent_recording_allowed)
    compositor._running = False
    log.info("Stopping compositor pipeline")

    GLib = compositor._GLib
    Gst = compositor._Gst

    if compositor._status_timer_id is not None and GLib is not None:
        GLib.source_remove(compositor._status_timer_id)
        compositor._status_timer_id = None
    if getattr(compositor, "_broadcast_mode_timer_id", None) is not None and GLib is not None:
        GLib.source_remove(compositor._broadcast_mode_timer_id)
        compositor._broadcast_mode_timer_id = None
    if getattr(compositor, "_activity_router_timer_id", None) is not None and GLib is not None:
        GLib.source_remove(compositor._activity_router_timer_id)
        compositor._activity_router_timer_id = None
    activity_router = getattr(compositor, "_activity_router", None)
    if activity_router is not None:
        try:
            activity_router.stop()
        except Exception:
            log.exception("activity router stop failed")

    try:
        compositor._stop_mobile_support_threads()
    except Exception:
        log.exception("mobile support thread shutdown failed")

    if compositor.pipeline and Gst is not None:
        compositor.pipeline.set_state(Gst.State.NULL)

    # --- ALPHA PHASE 2: tear down per-camera producer + fallback pipelines ---
    # Phase 3 extension: stop the udev monitor first so no more events flow
    # through the state machine after we start tearing it down.
    udev_mon = getattr(compositor, "_udev_monitor", None)
    if udev_mon is not None:
        try:
            udev_mon.stop()
        except Exception:
            log.exception("UdevCameraMonitor stop raised during shutdown")

    pm = getattr(compositor, "_pipeline_manager", None)
    if pm is not None:
        try:
            pm.stop()
        except Exception:
            log.exception("PipelineManager stop raised during shutdown")
    # --- END ALPHA PHASE 2 ---

    if compositor.loop and compositor.loop.is_running():
        compositor.loop.quit()

    compositor._audio_capture.stop()

    # CVS #145 — tear down the bidirectional ducker thread.
    ducker = getattr(compositor, "_audio_ducking", None)
    if ducker is not None:
        try:
            ducker.stop()
        except Exception:
            log.exception("AudioDuckingController stop raised during shutdown")

    compositor._write_status("stopped")


def _register_purge_handler(compositor: Any) -> None:
    """Register video recording purge handler with RevocationPropagator."""
    try:
        import agents._revocation as _rev_mod
        from agents._revocation import RevocationPropagator

        from .consent import purge_video_recordings

        for attr in dir(_rev_mod):
            obj = getattr(_rev_mod, attr, None)
            if isinstance(obj, RevocationPropagator):
                obj.register_handler(
                    "video_recordings",
                    lambda contract_id: purge_video_recordings(compositor, contract_id),
                )
                log.info("Registered video recording purge handler")
                break
    except Exception:
        log.debug("RevocationPropagator not available — video purge disabled")
