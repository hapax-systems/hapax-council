"""Main StudioCompositor class -- thin orchestration shell."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from shared.compositor_model import (
    Assignment,
    Layout,
    SourceSchema,
    SurfaceGeometry,
    SurfaceSchema,
)

from .audio_capture import CompositorAudioCapture
from .config import CACHE_DIR, SNAPSHOT_DIR, STATUS_FILE
from .effects import init_graph_runtime
from .layout_loader import LayoutStore
from .layout_state import LayoutState
from .models import CompositorConfig, OverlayState, TileRect
from .overlay_zones import OverlayZoneManager
from .profiles import load_camera_profiles
from .source_registry import SourceRegistry

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Source-registry epic Phase D task 13 — Layout loader + hardcoded rescue
#
# ``load_layout_or_fallback`` reads the canonical baseline JSON from disk
# and returns the parsed ``Layout``; any failure (missing file, malformed
# JSON, schema violation) logs a WARNING and resolves to
# ``_FALLBACK_LAYOUT`` — a hardcoded mirror of ``config/compositor-layouts/
# default.json`` so the compositor always boots with a working source
# registry even if the on-disk config is absent or corrupted.
#
# Dormant in main: the function is a standalone helper with no caller
# yet. Task 14 will call it from ``StudioCompositor.start()`` and feed
# the result into ``LayoutState`` + ``SourceRegistry``.
# ---------------------------------------------------------------------------


_FALLBACK_LAYOUT = Layout(
    name="default",
    description=(
        "Hardcoded fallback layout — rescue path when default.json is missing "
        "or cannot be parsed. Structurally identical to "
        "config/compositor-layouts/default.json (Phase D task 12)."
    ),
    sources=[
        SourceSchema(
            id="token_pole",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "TokenPoleCairoSource",
                "natural_w": 300,
                "natural_h": 300,
            },
        ),
        SourceSchema(
            id="album",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "AlbumOverlayCairoSource",
                "natural_w": 400,
                "natural_h": 520,
            },
        ),
        SourceSchema(
            id="sierpinski",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "SierpinskiCairoSource",
                "natural_w": 640,
                "natural_h": 640,
            },
        ),
        SourceSchema(
            id="reverie",
            kind="external_rgba",
            backend="shm_rgba",
            params={
                "natural_w": 640,
                "natural_h": 360,
                "shm_path": "/dev/shm/hapax-sources/reverie.rgba",
            },
        ),
    ],
    surfaces=[
        SurfaceSchema(
            id="pip-ul",
            geometry=SurfaceGeometry(kind="rect", x=20, y=20, w=300, h=300),
            z_order=10,
        ),
        SurfaceSchema(
            id="pip-ur",
            geometry=SurfaceGeometry(kind="rect", x=1260, y=20, w=640, h=360),
            z_order=10,
        ),
        SurfaceSchema(
            id="pip-ll",
            geometry=SurfaceGeometry(kind="rect", x=20, y=540, w=400, h=520),
            z_order=10,
        ),
        SurfaceSchema(
            id="pip-lr",
            geometry=SurfaceGeometry(kind="rect", x=1260, y=420, w=640, h=640),
            z_order=10,
        ),
    ],
    assignments=[
        Assignment(source="token_pole", surface="pip-ul"),
        Assignment(source="reverie", surface="pip-ur"),
        Assignment(source="album", surface="pip-ll"),
    ],
)


def load_layout_or_fallback(path: Path) -> Layout:
    """Load a compositor Layout from JSON, falling back to the hardcoded rescue.

    Any failure mode — file missing, malformed JSON, pydantic validation
    error — logs a WARNING with the offending path and returns
    ``_FALLBACK_LAYOUT``. The compositor boots with a working source
    registry unconditionally.
    """
    target = Path(path)
    try:
        raw = json.loads(target.read_text())
    except FileNotFoundError:
        log.warning("compositor layout %s missing — using fallback", target)
        return _FALLBACK_LAYOUT
    except (OSError, json.JSONDecodeError) as exc:
        log.warning(
            "compositor layout %s could not be read (%s) — using fallback",
            target,
            exc,
        )
        return _FALLBACK_LAYOUT

    try:
        return Layout.model_validate(raw)
    except ValueError as exc:
        log.warning(
            "compositor layout %s failed schema validation (%s) — using fallback",
            target,
            exc,
        )
        return _FALLBACK_LAYOUT


_DEFAULT_LAYOUT_PATH = Path("config/compositor-layouts/default.json")


class StudioCompositor:
    """Manages the GStreamer compositing pipeline."""

    def __init__(
        self,
        config: CompositorConfig,
        *,
        layout_path: Path | None = None,
    ) -> None:
        self.config = config
        # Source-registry epic Phase D task 14 — Layout loader + registry.
        # Resolved relative to the repo root by default so tests and the
        # real entrypoint both see ``config/compositor-layouts/default.json``
        # without any extra wiring. ``load_layout_or_fallback`` handles the
        # missing-file path itself; this attribute only selects the target.
        self._layout_path: Path = (
            Path(layout_path) if layout_path is not None else _DEFAULT_LAYOUT_PATH
        )
        self.layout_state: LayoutState | None = None
        self.source_registry: SourceRegistry | None = None
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
        self._overlay_zone_manager = OverlayZoneManager()
        self._audio_capture = CompositorAudioCapture()

        self._graph_runtime = init_graph_runtime(self)

        # Phase 2c: LayoutStore — loads Source/Surface/Assignment layouts.
        # Currently advisory only — no rendering code consumes this yet.
        # Phase 3 will wire the active Layout into the executor.
        self._layout_store = LayoutStore()
        if "garage-door" in self._layout_store.list_available():
            self._layout_store.set_active("garage-door")

        from agents.effect_graph.visual_governance import AtmosphericSelector

        self._atmospheric_selector = AtmosphericSelector()
        self._idle_start: float | None = None
        self._current_preset_name: str | None = None

    def _on_graph_params_changed(self, node_id: str, params: dict) -> None:
        if hasattr(self, "_slot_pipeline") and self._slot_pipeline is not None:
            self._slot_pipeline.update_node_uniforms(node_id, params)

    def _on_graph_plan_changed(self, old_plan: Any, new_plan: Any) -> None:
        if hasattr(self, "_slot_pipeline") and self._slot_pipeline is not None:
            self._slot_pipeline.activate_plan(new_plan)
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
        self._notify_camera_transition(role, prev or "unknown", "offline")

    def _mark_camera_online(self, role: str) -> None:
        with self._camera_status_lock:
            prev = self._camera_status.get(role)
            if prev == "active":
                return
            self._camera_status[role] = "active"
        log.info("Camera %s marked active", role)
        self._write_status("running")
        self._notify_camera_transition(role, prev or "unknown", "active")

    def _notify_camera_transition(self, role: str, prev: str, curr: str) -> None:
        """Throttled ntfy on camera state transition. Uses /dev/shm tracker file
        to coalesce duplicate transitions within a 60s window."""
        try:
            from shared.notify import send_notification

            tracker = Path("/dev/shm/hapax-compositor") / f"last-ntfy-{role}.txt"
            tracker.parent.mkdir(parents=True, exist_ok=True)
            now = time.monotonic()
            last_payload = ""
            last_ts = 0.0
            if tracker.exists():
                try:
                    raw = tracker.read_text().strip().split("\n", 1)
                    last_ts = float(raw[0]) if raw else 0.0
                    last_payload = raw[1] if len(raw) > 1 else ""
                except (ValueError, IndexError, OSError):
                    pass
            if last_payload == curr and (now - last_ts) < 60.0:
                return
            tracker.write_text(f"{now}\n{curr}")
            priority = "high" if curr == "offline" else "default"
            tag = "rotating_light" if curr == "offline" else "white_check_mark"
            send_notification(
                title=f"Camera {role} → {curr}",
                message=f"Transitioned from {prev}",
                priority=priority,
                tags=[tag],
            )
        except Exception:
            log.exception("ntfy on camera transition failed (role=%s)", role)

    def _on_bus_message(self, bus: Any, message: Any) -> bool:
        Gst = self._Gst
        t = message.type
        if t == Gst.MessageType.EOS:
            log.info("Pipeline EOS")
            self.stop()
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            src_name = message.src.get_name() if message.src else "unknown"
            # Phase 5: scope RTMP bin errors to the bin and rebuild in place.
            # src-name filtering is reliable because every RTMP bin element is
            # named with the rtmp_ prefix in rtmp_output.py.
            if src_name.startswith("rtmp_"):
                log.error(
                    "RTMP bin error (element %s): %s (debug=%s)",
                    src_name,
                    err.message,
                    debug,
                )
                rtmp_bin = getattr(self, "_rtmp_bin", None)
                pipeline = self.pipeline
                if rtmp_bin is not None and pipeline is not None and self._GLib is not None:
                    self._GLib.idle_add(lambda: (rtmp_bin.rebuild_in_place(pipeline), False)[1])
                try:
                    from . import metrics

                    metrics.RTMP_ENCODER_ERRORS_TOTAL.labels(endpoint="youtube").inc()
                    metrics.RTMP_BIN_REBUILDS_TOTAL.labels(endpoint="youtube").inc()
                except Exception:
                    pass
                return True
            role = self._resolve_camera_role(message.src)
            if role is not None:
                log.error("Camera %s error (element %s): %s", role, src_name, err.message)
                self._mark_camera_offline(role)
            elif src_name.startswith("fx-v4l2"):
                log.warning("FX v4l2sink error (non-fatal): %s", err.message)
            elif src_name == "output" and "busy" in err.message:
                log.warning("v4l2sink format renegotiation failed (non-fatal): %s", err.message)
            elif src_name.startswith("fxsrc-"):
                # FX source branch error — non-fatal
                log.warning("FX source branch error (non-fatal): %s", err.message)
                try:
                    from .fx_chain import switch_fx_source

                    switch_fx_source(self, "live")
                except Exception:
                    log.exception("FX source fallback switch failed after error")
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

    def start_layout_only(self) -> None:
        """Phase D task 14 — load the Layout and populate SourceRegistry.

        This is the first phase of :meth:`start` and a standalone entry
        point for tests that want to exercise Layout wiring without
        touching GStreamer. Idempotent: calling twice is a no-op.

        On success, ``self.layout_state`` holds an in-memory authority
        over the current Layout and ``self.source_registry`` maps every
        Source from that Layout to a live backend. Per-source backend
        construction failures are logged and skipped — a broken cairo
        class or a missing shm path must never take down the compositor.
        """
        if self.layout_state is not None and self.source_registry is not None:
            return

        layout = load_layout_or_fallback(self._layout_path)
        state = LayoutState(layout)
        registry = SourceRegistry()
        for source in layout.sources:
            try:
                backend = registry.construct_backend(source)
            except Exception:
                log.exception(
                    "failed to construct backend for source %s (backend=%s)",
                    source.id,
                    source.backend,
                )
                continue
            try:
                registry.register(source.id, backend)
            except ValueError:
                log.exception(
                    "duplicate source_id %s in layout — dropping later registration",
                    source.id,
                )
        self.layout_state = state
        self.source_registry = registry
        log.info(
            "layout loaded: name=%s sources=%d registered=%d",
            layout.name,
            len(layout.sources),
            len(registry.ids()),
        )

    def start(self) -> None:
        """Build and start the pipeline."""
        self.start_layout_only()

        from .lifecycle import start_compositor

        start_compositor(self)

    def stop(self) -> None:
        """Stop the pipeline cleanly."""
        from .lifecycle import stop_compositor

        stop_compositor(self)

    def toggle_livestream(self, activate: bool, reason: str = "") -> tuple[bool, str]:
        """Attach or detach the RTMP output bin. Consent-gated by the
        unified semantic recruitment pipeline — this method should only be
        called from the affordance handler which runs after the consent
        check.

        Phase 5 of the camera 24/7 resilience epic (closes A7).
        """
        rtmp_bin = getattr(self, "_rtmp_bin", None)
        if rtmp_bin is None:
            return False, "rtmp bin not constructed (compositor not started?)"
        if self.pipeline is None:
            return False, "composite pipeline not built"

        if activate:
            if rtmp_bin.is_attached():
                return True, "already live"
            ok = rtmp_bin.build_and_attach(self.pipeline)
            if not ok:
                return False, "rtmp bin build_and_attach failed"
            try:
                from shared.notify import send_notification

                from . import metrics

                metrics.RTMP_CONNECTED.labels(endpoint="youtube").set(1)
                send_notification(
                    title="Livestream started",
                    message=f"Reason: {reason}",
                    priority="default",
                    tags=["rocket"],
                )
            except Exception:
                log.exception("rtmp attach side-effects raised (non-fatal)")
            return True, "rtmp bin attached"
        else:
            if not rtmp_bin.is_attached():
                return True, "already off"
            rtmp_bin.detach_and_teardown(self.pipeline)
            try:
                from shared.notify import send_notification

                from . import metrics

                metrics.RTMP_CONNECTED.labels(endpoint="youtube").set(0)
                send_notification(
                    title="Livestream stopped",
                    message=f"Reason: {reason}",
                    priority="default",
                    tags=["stop_sign"],
                )
            except Exception:
                log.exception("rtmp detach side-effects raised (non-fatal)")
            return True, "rtmp bin detached"
