"""Lifecycle management: start and stop the compositor pipeline."""

from __future__ import annotations

import json
import logging
import signal
import threading
import time
from typing import Any

from shared.control_signal import ControlSignal, publish_health

from .config import PERCEPTION_STATE_PATH
from .consent import log_consent_event

log = logging.getLogger(__name__)


def start_compositor(compositor: Any) -> None:
    """Build and start the pipeline."""
    from .fx_chain import fx_tick_callback
    from .pipeline import build_pipeline, init_gstreamer
    from .state import state_reader_loop

    compositor._GLib, compositor._Gst = init_gstreamer()
    GLib = compositor._GLib
    Gst = compositor._Gst

    log.info("Building compositor pipeline with %d cameras", len(compositor.config.cameras))

    with compositor._camera_status_lock:
        for cam in compositor.config.cameras:
            compositor._camera_status[cam.role] = "starting"

    compositor.pipeline = build_pipeline(compositor)

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

    log.info("Pipeline started -- output on %s", compositor.config.output_device)

    with compositor._camera_status_lock:
        for role, status in compositor._camera_status.items():
            if status == "starting":
                compositor._camera_status[role] = "active"

    compositor._running = True
    compositor._write_status("running")
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

    _register_purge_handler(compositor)

    compositor.loop = GLib.MainLoop()

    interval_ms = int(compositor.config.status_interval_s * 1000)
    compositor._status_timer_id = GLib.timeout_add(interval_ms, compositor._status_tick)

    if hasattr(compositor, "_slot_pipeline"):
        GLib.timeout_add(33, lambda: fx_tick_callback(compositor))

    if compositor.config.overlay_enabled:
        compositor._state_reader_thread = threading.Thread(
            target=lambda: state_reader_loop(compositor), daemon=True, name="state-reader"
        )
        compositor._state_reader_thread.start()

    def _shutdown(signum: int, frame: Any) -> None:
        log.info("Signal %d received, shutting down", signum)
        compositor.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

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

    if compositor.pipeline and Gst is not None:
        compositor.pipeline.set_state(Gst.State.NULL)

    if compositor.loop and compositor.loop.is_running():
        compositor.loop.quit()

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
