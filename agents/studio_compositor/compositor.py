"""Main StudioCompositor class -- thin orchestration shell."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from .config import CACHE_DIR, SNAPSHOT_DIR, STATUS_FILE
from .effects import init_graph_runtime
from .models import CompositorConfig, OverlayState, TileRect
from .profiles import load_camera_profiles

log = logging.getLogger(__name__)


class StudioCompositor:
    """Manages the GStreamer compositing pipeline."""

    def __init__(self, config: CompositorConfig) -> None:
        self.config = config
        self.pipeline: Any = None
        self.loop: Any = None
        self._running = False
        self._camera_status: dict[str, str] = {}
        self._camera_status_lock = threading.Lock()
        self._recording_status: dict[str, str] = {}
        self._recording_status_lock = threading.Lock()
        self._element_to_role: dict[str, str] = {}
        self._status_timer_id: int | None = None
        self._overlay_state = OverlayState()
        self._overlay_canvas_size: tuple[int, int] = (config.output_width, config.output_height)
        self._tile_layout: dict[str, TileRect] = {}
        self._state_reader_thread: threading.Thread | None = None
        self._GLib: Any = None
        self._Gst: Any = None
        self._active_profile_name: str = ""
        self._camera_profiles = load_camera_profiles(config.camera_profiles)
        self._status_dir_exists = False
        self._recording_valves: dict[str, Any] = {}
        self._recording_muxes: dict[str, Any] = {}
        self._hls_valve: Any = None
        self._consent_recording_allowed: bool = True
        self._overlay_cache_surface: Any = None
        self._overlay_cache_timestamp: float = 0.0
        self._overlay_cache_cam_hash: str = ""
        self._vl_state: dict | None = None
        self._vl_state_lock = threading.Lock()
        self._vl_state_timestamp: float = 0.0
        self._vl_zone_opacities: dict[str, float] = {}
        self._vl_cache_surface: Any = None
        self._vl_cache_timestamp: float = 0.0
        self._VL_LAST_FRAME_TIME: float = 0.0

        self._graph_runtime = init_graph_runtime(self)

        from agents.effect_graph.visual_governance import AtmosphericSelector

        self._atmospheric_selector = AtmosphericSelector()
        self._idle_start: float | None = None
        self._current_preset_name: str | None = None

    def _on_graph_params_changed(self, node_id: str, params: dict) -> None:
        if hasattr(self, "_slot_pipeline") and self._slot_pipeline is not None:
            self._slot_pipeline.update_node_uniforms(node_id, params)

    def _on_graph_plan_changed(self, old_plan: Any, new_plan: Any) -> None:
        if (
            old_plan is not None
            and hasattr(self, "_fx_crossfade")
            and self._fx_crossfade is not None
        ):
            self._fx_crossfade.set_property("trigger", True)
        if hasattr(self, "_slot_pipeline") and self._slot_pipeline is not None:
            self._slot_pipeline.activate_plan(new_plan)
            self._fx_graph_mode = True
            log.info("Slot pipeline activated: %s", new_plan.name if new_plan else "none")

    def _resolve_camera_role(self, element: Any) -> str | None:
        if element is None:
            return None
        name = element.get_name()
        if name in self._element_to_role:
            return self._element_to_role[name]
        for _elem_prefix, role in self._element_to_role.items():
            role_suffix = role.replace("-", "_")
            if role_suffix in name:
                return role
        return None

    def _mark_camera_offline(self, role: str) -> None:
        with self._camera_status_lock:
            prev = self._camera_status.get(role)
            if prev == "offline":
                return
            self._camera_status[role] = "offline"
        log.warning("Camera %s marked offline", role)
        self._write_status("running")

    def _on_bus_message(self, bus: Any, message: Any) -> bool:
        Gst = self._Gst
        t = message.type
        if t == Gst.MessageType.EOS:
            log.info("Pipeline EOS")
            self.stop()
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            src_name = message.src.get_name() if message.src else "unknown"
            role = self._resolve_camera_role(message.src)
            if role is not None:
                log.error("Camera %s error (element %s): %s", role, src_name, err.message)
                self._mark_camera_offline(role)
            elif src_name.startswith("fx-v4l2"):
                log.warning("FX v4l2sink error (non-fatal): %s", err.message)
            else:
                log.error("Pipeline error from %s: %s (debug: %s)", src_name, err.message, debug)
                self.stop()
        elif t == Gst.MessageType.WARNING:
            err, debug = message.parse_warning()
            log.warning("Pipeline warning: %s (debug: %s)", err.message, debug)
        elif t == Gst.MessageType.STATE_CHANGED:
            if message.src == self.pipeline:
                old, new, _ = message.parse_state_changed()
                log.debug("Pipeline state: %s -> %s", old.value_nick, new.value_nick)
        return True

    def _write_status(self, state: str) -> None:
        if not self._status_dir_exists:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            self._status_dir_exists = True
        with self._camera_status_lock:
            cameras = dict(self._camera_status)
        with self._recording_status_lock:
            recording_cameras = dict(self._recording_status)
        with self._overlay_state._lock:
            guest_present = self._overlay_state._data.guest_present
            consent_phase = self._overlay_state._data.consent_phase
        active_count = sum(1 for s in cameras.values() if s == "active")
        hls_url = (
            str(Path(self.config.hls.output_dir) / "stream.m3u8") if self.config.hls.enabled else ""
        )
        status = {
            "state": state,
            "pid": os.getpid(),
            "cameras": cameras,
            "active_cameras": active_count,
            "total_cameras": len(cameras),
            "output_device": self.config.output_device,
            "resolution": f"{self.config.output_width}x{self.config.output_height}",
            "recording_enabled": self.config.recording.enabled,
            "recording_cameras": recording_cameras,
            "hls_enabled": self.config.hls.enabled,
            "hls_url": hls_url,
            "camera_profile": self._active_profile_name,
            "consent_recording_allowed": self._consent_recording_allowed,
            "guest_present": guest_present,
            "consent_phase": consent_phase,
            "timestamp": time.time(),
        }
        tmp = STATUS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(status, indent=2))
        tmp.rename(STATUS_FILE)
        try:
            consent_file = SNAPSHOT_DIR / "consent-state.txt"
            consent_file.write_text("allowed" if self._consent_recording_allowed else "blocked")
        except OSError:
            pass

    def _status_tick(self) -> bool:
        if self._running:
            self._write_status("running")
        return self._running

    def start(self) -> None:
        """Build and start the pipeline."""
        from .lifecycle import start_compositor

        start_compositor(self)

    def stop(self) -> None:
        """Stop the pipeline cleanly."""
        from .lifecycle import stop_compositor

        stop_compositor(self)
