"""Main StudioCompositor class -- thin orchestration shell."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
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
from .output_router import OutputRouter
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
            id="stream_overlay",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "StreamOverlayCairoSource",
                "natural_w": 400,
                "natural_h": 200,
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
        # Continuous-Loop Research Cadence §3.4 — caption strip.
        SourceSchema(
            id="captions",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "CaptionsCairoSource",
                "natural_w": 1840,
                "natural_h": 110,
            },
        ),
        # Volitional-director epic Phase 4 legibility sources (PR #1017/§3.5).
        SourceSchema(
            id="activity_header",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "ActivityHeaderCairoSource",
                "natural_w": 800,
                "natural_h": 56,
            },
        ),
        SourceSchema(
            id="stance_indicator",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "StanceIndicatorCairoSource",
                "natural_w": 100,
                "natural_h": 40,
            },
        ),
        SourceSchema(
            id="chat_keyword_legend",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "ChatKeywordLegendCairoSource",
                "natural_w": 160,
                "natural_h": 400,
            },
        ),
        SourceSchema(
            id="grounding_provenance_ticker",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "GroundingProvenanceTickerCairoSource",
                "natural_w": 480,
                "natural_h": 40,
            },
        ),
        # Epic 2 Phase C (2026-04-17) — hothouse pressure surfaces.
        SourceSchema(
            id="impingement_cascade",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "ImpingementCascadeCairoSource",
                "natural_w": 480,
                "natural_h": 360,
            },
        ),
        SourceSchema(
            id="recruitment_candidate_panel",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "RecruitmentCandidatePanelCairoSource",
                "natural_w": 800,
                "natural_h": 60,
            },
        ),
        SourceSchema(
            id="thinking_indicator",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "ThinkingIndicatorCairoSource",
                "natural_w": 170,
                "natural_h": 44,
            },
        ),
        SourceSchema(
            id="pressure_gauge",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "PressureGaugeCairoSource",
                "natural_w": 300,
                "natural_h": 52,
            },
        ),
        SourceSchema(
            id="activity_variety_log",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "ActivityVarietyLogCairoSource",
                "natural_w": 400,
                "natural_h": 140,
            },
        ),
        # Epic 2 Phase D (2026-04-17) — operator-always-here indicator.
        SourceSchema(
            id="whos_here",
            kind="cairo",
            backend="cairo",
            params={
                "class_name": "WhosHereCairoSource",
                "natural_w": 230,
                "natural_h": 46,
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
            geometry=SurfaceGeometry(kind="rect", x=1500, y=860, w=400, h=200),
            z_order=10,
        ),
        # Continuous-Loop Research Cadence §3.4 — bottom caption strip.
        SurfaceSchema(
            id="captions_strip",
            geometry=SurfaceGeometry(kind="rect", x=40, y=930, w=1840, h=110),
            z_order=20,
        ),
        # LRR Phase 2 item 10 — video_out surfaces enumerated by
        # OutputRouter.from_layout() for the three current sinks.
        # Legacy hardcoded paths remain authoritative for sink
        # construction; full migration to router-driven sinks is a
        # Phase 10 polish item.
        SurfaceSchema(
            id="video_out_v4l2_loopback",
            geometry=SurfaceGeometry(kind="video_out", target="/dev/video42", render_target="main"),
            z_order=100,
        ),
        SurfaceSchema(
            id="video_out_rtmp_mediamtx",
            geometry=SurfaceGeometry(
                kind="video_out",
                target="rtmp://127.0.0.1:1935/studio",
                render_target="main",
            ),
            z_order=101,
        ),
        SurfaceSchema(
            id="video_out_hls_playlist",
            geometry=SurfaceGeometry(kind="video_out", target="hls://local", render_target="main"),
            z_order=102,
        ),
        # Volitional-director Phase 4 legibility surfaces.
        SurfaceSchema(
            id="activity-header-top",
            geometry=SurfaceGeometry(kind="rect", x=560, y=16, w=800, h=56),
            z_order=30,
        ),
        SurfaceSchema(
            id="stance-indicator-tr",
            geometry=SurfaceGeometry(kind="rect", x=1800, y=24, w=100, h=40),
            z_order=35,
        ),
        SurfaceSchema(
            id="chat-legend-right",
            geometry=SurfaceGeometry(kind="rect", x=1760, y=400, w=160, h=400),
            z_order=20,
        ),
        SurfaceSchema(
            id="grounding-ticker-bl",
            geometry=SurfaceGeometry(kind="rect", x=16, y=900, w=480, h=40),
            z_order=22,
        ),
        # Epic 2 Phase C (2026-04-17) — hothouse pressure surfaces.
        SurfaceSchema(
            id="impingement-cascade-midright",
            geometry=SurfaceGeometry(kind="rect", x=1260, y=400, w=480, h=360),
            z_order=24,
        ),
        SurfaceSchema(
            id="recruitment-candidate-top",
            geometry=SurfaceGeometry(kind="rect", x=560, y=80, w=800, h=60),
            z_order=24,
        ),
        SurfaceSchema(
            id="thinking-indicator-tr",
            geometry=SurfaceGeometry(kind="rect", x=1620, y=20, w=170, h=44),
            z_order=26,
        ),
        SurfaceSchema(
            id="pressure-gauge-ul",
            geometry=SurfaceGeometry(kind="rect", x=20, y=336, w=300, h=52),
            z_order=24,
        ),
        SurfaceSchema(
            id="activity-variety-log-mid",
            geometry=SurfaceGeometry(kind="rect", x=440, y=540, w=400, h=140),
            z_order=24,
        ),
        # Epic 2 Phase D — operator-always-here, top-center-right.
        SurfaceSchema(
            id="whos-here-tr",
            geometry=SurfaceGeometry(kind="rect", x=1460, y=20, w=150, h=46),
            z_order=26,
        ),
    ],
    assignments=[
        Assignment(source="token_pole", surface="pip-ul"),
        Assignment(source="reverie", surface="pip-ur"),
        Assignment(source="album", surface="pip-ll"),
        Assignment(source="stream_overlay", surface="pip-lr"),
        Assignment(source="captions", surface="captions_strip", opacity=0.92),
        # Volitional-director Phase 4 assignments.
        Assignment(source="activity_header", surface="activity-header-top"),
        Assignment(source="stance_indicator", surface="stance-indicator-tr"),
        Assignment(source="chat_keyword_legend", surface="chat-legend-right"),
        Assignment(source="grounding_provenance_ticker", surface="grounding-ticker-bl"),
        # Epic 2 Phase C hothouse assignments.
        Assignment(
            source="impingement_cascade",
            surface="impingement-cascade-midright",
            opacity=0.92,
        ),
        Assignment(
            source="recruitment_candidate_panel",
            surface="recruitment-candidate-top",
            opacity=0.92,
        ),
        Assignment(source="thinking_indicator", surface="thinking-indicator-tr", opacity=0.92),
        Assignment(source="pressure_gauge", surface="pressure-gauge-ul", opacity=0.92),
        Assignment(
            source="activity_variety_log",
            surface="activity-variety-log-mid",
            opacity=0.90,
        ),
        # Epic 2 Phase D assignment.
        Assignment(source="whos_here", surface="whos-here-tr", opacity=0.92),
    ],
)


def _notify_fallback(target: Path, reason: str) -> None:
    """Send a throttled ntfy when the compositor falls back to _FALLBACK_LAYOUT.

    Post-epic audit Phase 1 finding #6: AC-8 ("deleting default.json →
    fallback layout + ntfy") only had the fallback half wired.
    Non-fatal — notification failures must never mask the fallback
    itself. The notification path mirrors the camera-transition
    pattern in ``_notify_camera_transition`` but without the
    per-role throttle (layout fallback is rare enough that one
    notification per event is the right cadence).
    """
    try:
        from shared.notify import send_notification

        send_notification(
            title="Compositor layout fallback",
            body=(
                f"{target}: {reason}. Booting with hardcoded _FALLBACK_LAYOUT. "
                "Check the file or restore from git."
            ),
            tag="compositor-layout-fallback",
            priority="default",
        )
    except Exception:
        log.debug("fallback layout ntfy failed", exc_info=True)


def load_layout_or_fallback(path: Path) -> Layout:
    """Load a compositor Layout from JSON, falling back to the hardcoded rescue.

    Any failure mode — file missing, malformed JSON, pydantic validation
    error — logs a WARNING with the offending path, fires a one-shot
    ntfy via :func:`_notify_fallback`, and returns ``_FALLBACK_LAYOUT``.
    The compositor boots with a working source registry unconditionally.
    """
    target = Path(path)
    try:
        raw = json.loads(target.read_text())
    except FileNotFoundError:
        log.warning("compositor layout %s missing — using fallback", target)
        _notify_fallback(target, "file missing")
        return _FALLBACK_LAYOUT
    except (OSError, json.JSONDecodeError) as exc:
        log.warning(
            "compositor layout %s could not be read (%s) — using fallback",
            target,
            exc,
        )
        _notify_fallback(target, f"read error: {exc}")
        return _FALLBACK_LAYOUT

    try:
        return Layout.model_validate(raw)
    except ValueError as exc:
        log.warning(
            "compositor layout %s failed schema validation (%s) — using fallback",
            target,
            exc,
        )
        _notify_fallback(target, f"schema validation failed: {exc}")
        return _FALLBACK_LAYOUT


# Repo-root-anchored default layout path. Resolved from this file's
# location at import time rather than from the process CWD so the
# compositor can be invoked from any working directory without silently
# falling through to ``_FALLBACK_LAYOUT``. File layout: this file lives at
# ``agents/studio_compositor/compositor.py`` → ``parents[2]`` is the repo
# root → append ``config/compositor-layouts/default.json``.
_DEFAULT_LAYOUT_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "compositor-layouts" / "default.json"
)


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
        # ``_DEFAULT_LAYOUT_PATH`` is computed from ``__file__`` at import
        # time, so the default resolves to the repo's baseline layout JSON
        # regardless of the process CWD. ``load_layout_or_fallback`` still
        # handles the missing-file path itself for the rescue case.
        self._layout_path: Path = (
            Path(layout_path) if layout_path is not None else _DEFAULT_LAYOUT_PATH
        )
        self.layout_state: LayoutState | None = None
        self.source_registry: SourceRegistry | None = None
        self.output_router: OutputRouter | None = None
        self._layout_autosaver: Any = None
        self._layout_file_watcher: Any = None
        self._command_server: Any = None
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
        # Phase 10 observability polish — wire the Phase 7 BudgetTracker
        # that has sat dead since PR #752. One tracker shared across every
        # CairoSourceRunner in the process; lifecycle.start_compositor
        # schedules the GLib timer that publishes snapshots to
        # /dev/shm/hapax-compositor/costs.json and degraded.json.
        from agents.studio_compositor.budget import BudgetTracker

        self._budget_tracker = BudgetTracker()
        self._overlay_zone_manager = OverlayZoneManager(budget_tracker=self._budget_tracker)
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
            elif (
                src_name == "hls-sink"
                or src_name.startswith("splitmuxsink")
                or src_name.startswith("giostreamsink")
                or src_name.startswith("mpegtsmux")
                or "hls" in src_name.lower()
            ):
                # hls-sink and its internal children (splitmuxsink,
                # giostreamsink, mpegtsmux) all emit ERROR messages that
                # must be scoped non-fatal. The hlssink2 element wraps a
                # splitmuxsink which wraps a giostreamsink, and each
                # child posts errors under its own src_name — the
                # original scope check (drop #33) only caught
                # src_name == "hls-sink" and missed the children.
                # EMFILE errors from hls-sink write paths surface on
                # giostreamsink0 and must not escalate to self.stop().
                log.warning("HLS sink error (non-fatal): %s", err.message)
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
            # Drop #41 BT-5 / drop #52 FDL-2: publish process fd count so
            # future regressions in the camera-rebuild-thrash path become
            # scrape-visible before they hit the LimitNOFILE=65536
            # ceiling. os.listdir on /proc/self/fd is a cheap file count;
            # use a broad try/except because the directory can momentarily
            # vanish during heavy fd churn.
            try:
                from . import metrics as _metrics

                if _metrics.COMP_PROCESS_FD_COUNT is not None:
                    import os as _os

                    _metrics.COMP_PROCESS_FD_COUNT.set(len(_os.listdir("/proc/self/fd")))
            except Exception:
                log.debug("fd count gauge update failed", exc_info=True)
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

        # Populate the ward registry from this layout so per-ward property
        # dispatchers (`ward.size.<id>.*`, etc.) can validate against the
        # canonical catalog and operator tooling can list every addressable
        # ward. Atomic dict swap inside `populate_from_layout` keeps any
        # concurrent reader on a stable snapshot during the layout swap.
        try:
            from agents.studio_compositor.ward_registry import (
                clear_registry,
                populate_camera_pips,
                populate_from_layout,
                populate_overlay_zones,
                populate_youtube_slots,
            )

            # Clear first so a future layout swap can't leave stale ward
            # IDs from a prior layout sitting alongside the current ones.
            # Today there's no swap path (the if-guard above short-circuits
            # if layout_state already exists), but the explicit reset
            # documents the assumption.
            clear_registry()
            populate_from_layout(layout)
            populate_overlay_zones(["main", "research", "lyrics"])
            populate_youtube_slots(slot_count=3)
            populate_camera_pips(
                [
                    "c920-overhead",
                    "c920-desk",
                    "c920-room",
                    "brio-operator",
                    "brio-synths",
                    "brio-room",
                ]
            )
        except Exception:
            log.exception("ward_registry bootstrap failed; continuing without registry")

        for source in layout.sources:
            try:
                backend = registry.construct_backend(source, budget_tracker=self._budget_tracker)
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

        # Drop #41 BT-1 fix: start every registered backend that exposes
        # a start() method. Previously this was missing, leaving
        # layout-declared Cairo sources (token_pole, album,
        # stream_overlay, reverie) constructed-but-dormant — their
        # background render threads never ran and pip_draw_from_layout
        # silently skipped them. See SourceRegistry.start_all docstring
        # for the full analysis.
        registry.start_all()

        # LRR Phase 2 item 10b: populate CairoSourceRegistry from the
        # zone catalog at `config/compositor-zones.yaml`. This is the
        # NEW zone-binding registry (distinct from SourceRegistry which
        # handles surface backend binding). Failures are logged but
        # never raised — a missing or malformed zone catalog must not
        # take down the compositor. HSEA Phase 1 will consume the
        # populated registry via `CairoSourceRegistry.get_for_zone()`.
        try:
            from agents.studio_compositor.cairo_source_registry import load_zone_defaults

            zones_path = Path(__file__).resolve().parents[2] / "config" / "compositor-zones.yaml"
            registered, skipped = load_zone_defaults(zones_path)
            log.info(
                "cairo_source_registry populated: registered=%d skipped=%d",
                registered,
                skipped,
            )
        except Exception:
            log.exception(
                "cairo_source_registry population failed — "
                "HSEA Phase 1 zone lookups will return empty results"
            )

        # Phase 10 carry-over from Phase 2 item 10: attach the router
        # that enumerates video_out surfaces. Pure data plumbing —
        # the legacy hardcoded sink construction in ``pipeline.py`` is
        # still authoritative at runtime. Downstream consumers (e.g.
        # future router-driven sink building, or diagnostics) read from
        # ``self.output_router.bindings()``. Log the discovered
        # bindings so the operator can confirm each video_out surface
        # is visible to the new router plumbing.
        self.output_router = OutputRouter.from_layout(layout)
        for binding in self.output_router:
            log.info(
                "output router binding: surface=%s render_target=%s sink_kind=%s sink_path=%s",
                binding.surface_id,
                binding.render_target,
                binding.sink_kind,
                binding.sink_path,
            )

        log.info(
            "layout loaded: name=%s sources=%d registered=%d bindings=%d",
            layout.name,
            len(layout.sources),
            len(registry.ids()),
            len(self.output_router),
        )

        # Post-epic audit finding #1: LayoutAutoSaver + LayoutFileWatcher
        # exist in layout_persistence.py but were never instantiated by
        # StudioCompositor, leaving AC-5 ("file-watch reload within ≤2s")
        # unwired. Start both here so runtime layout edits round-trip
        # through the in-memory state.
        try:
            from agents.studio_compositor.layout_persistence import (
                LayoutAutoSaver,
                LayoutFileWatcher,
            )

            self._layout_autosaver = LayoutAutoSaver(state, self._layout_path)
            self._layout_autosaver.start()
            self._layout_file_watcher = LayoutFileWatcher(state, self._layout_path)
            self._layout_file_watcher.start()
            log.info(
                "layout persistence threads started: autosave + file-watch on %s",
                self._layout_path,
            )
        except Exception:
            log.exception(
                "failed to start layout persistence threads — "
                "compositor continues without auto-save or hot-reload"
            )

        # Delta post-epic retirement handoff item #5: start the compositor
        # command server so runtime layout mutations from window.__logos /
        # MCP / voice can round-trip through the in-memory LayoutState.
        # The ``flush_callback`` hooks ``compositor.layout.save`` to the
        # autosaver's immediate-flush path. ``reload_callback`` stays None —
        # the ``LayoutFileWatcher`` polling loop already picks up external
        # edits within ≤2 s, so a manual reload nudge isn't needed yet.
        try:
            import os

            from agents.studio_compositor.command_server import CommandServer

            runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
            command_sock = Path(runtime_dir) / "hapax-compositor-commands.sock"
            flush_cb: Callable[[], None] | None = None
            if self._layout_autosaver is not None:
                flush_cb = self._layout_autosaver.flush_now
            self._command_server = CommandServer(
                state,
                command_sock,
                flush_callback=flush_cb,
                reload_callback=None,
            )
            self._command_server.start()
        except Exception:
            log.exception(
                "failed to start compositor command server — "
                "runtime layout mutation via window.__logos / MCP is unavailable"
            )

    def start(self) -> None:
        """Build and start the pipeline."""
        self.start_layout_only()

        from .lifecycle import start_compositor

        start_compositor(self)

    def stop(self) -> None:
        """Stop the pipeline cleanly."""
        if self._command_server is not None:
            try:
                self._command_server.stop()
            except Exception:
                log.exception("CommandServer.stop failed")
            self._command_server = None
        if self._layout_file_watcher is not None:
            try:
                self._layout_file_watcher.stop()
            except Exception:
                log.exception("LayoutFileWatcher.stop failed")
            self._layout_file_watcher = None
        if self._layout_autosaver is not None:
            try:
                self._layout_autosaver.stop()
            except Exception:
                log.exception("LayoutAutoSaver.stop failed")
            self._layout_autosaver = None

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
