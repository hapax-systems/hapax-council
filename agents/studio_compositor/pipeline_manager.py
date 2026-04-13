"""PipelineManager — orchestrates per-camera producer + fallback sub-pipelines.

See docs/superpowers/specs/2026-04-12-compositor-hot-swap-architecture-design.md

Owns 12 producer GstPipelines (6 cameras + 6 fallbacks) plus references to
the composite pipeline's interpipesrc consumer elements. Error-scoped hot
swap: a camera producer error tears down its own pipeline and swaps the
consumer's listen-to to the fallback sink name, without disturbing the
composite pipeline or any other camera.

This is Phase 2 of the camera 24/7 resilience epic. Phase 3 adds the full
state machine; here we ship a simple HEALTHY/OFFLINE tracker + fixed-delay
rebuild scheduler (5 s) as a placeholder.
"""

from __future__ import annotations

import heapq
import logging
import threading
import time
from typing import Any

from .camera_pipeline import CameraPipeline
from .fallback_pipeline import FallbackPipeline
from .models import CameraSpec

log = logging.getLogger(__name__)


_REBUILD_DELAY_S = 5.0


class PipelineManager:
    """Manages all camera producer + fallback sub-pipelines."""

    def __init__(
        self,
        *,
        specs: list[CameraSpec],
        gst: Any,
        glib: Any,
        fps: int,
        on_transition: Any = None,
    ) -> None:
        self._specs = list(specs)
        self._Gst = gst
        self._GLib = glib
        self._fps = fps
        self._on_transition = on_transition  # callable(role, from_state, to_state, reason)

        self._cameras: dict[str, CameraPipeline] = {}
        self._fallbacks: dict[str, FallbackPipeline] = {}
        self._interpipe_srcs: dict[str, Any] = {}
        self._status: dict[str, str] = {}
        self._lock = threading.RLock()

        self._supervisor_stop = threading.Event()
        self._supervisor_cv = threading.Condition(threading.Lock())
        self._reconnect_queue: list[tuple[float, str]] = []
        self._supervisor_thread: threading.Thread | None = None

    # ------------------------------------------------------------------ build

    def build(self) -> None:
        """Instantiate + start all producer + fallback pipelines."""
        with self._lock:
            for spec in self._specs:
                try:
                    fb = FallbackPipeline(spec, gst=self._Gst, fps=self._fps)
                    fb.build()
                    fb.start()
                    self._fallbacks[spec.role] = fb
                except Exception:
                    log.exception("fallback pipeline for %s: build failed", spec.role)

                try:
                    cam = CameraPipeline(
                        spec,
                        gst=self._Gst,
                        fps=self._fps,
                        on_error=self._handle_camera_error,
                    )
                    cam.build()
                    started = cam.start()
                    self._cameras[spec.role] = cam
                    self._status[spec.role] = "active" if started else "offline"
                    if not started:
                        self._schedule_reconnect(spec.role, _REBUILD_DELAY_S)
                except Exception:
                    log.exception("camera pipeline for %s: build failed", spec.role)
                    self._status[spec.role] = "offline"
                    self._schedule_reconnect(spec.role, _REBUILD_DELAY_S)

        self._start_supervisor()

    # ---------------------------------------------------------------- consumer

    def register_consumer(self, role: str, interpipe_src: Any) -> None:
        """Associate a composite-pipeline interpipesrc with a camera role."""
        with self._lock:
            self._interpipe_srcs[role] = interpipe_src
        # On (re-)registration, point at primary unless already offline.
        curr = self.status(role)
        if curr == "offline":
            self.swap_to_fallback(role)
        else:
            self.swap_to_primary(role)

    def get_consumer_element(self, role: str) -> Any:
        with self._lock:
            return self._interpipe_srcs.get(role)

    # --------------------------------------------------------------- hot swap

    def swap_to_fallback(self, role: str) -> None:
        with self._lock:
            src = self._interpipe_srcs.get(role)
            fb = self._fallbacks.get(role)
        if src is None or fb is None:
            return
        src.set_property("listen-to", fb.sink_name)
        log.info("swap_to_fallback: role=%s → %s", role, fb.sink_name)

    def swap_to_primary(self, role: str) -> None:
        with self._lock:
            src = self._interpipe_srcs.get(role)
            cam = self._cameras.get(role)
        if src is None or cam is None:
            return
        src.set_property("listen-to", cam.sink_name)
        log.info("swap_to_primary: role=%s → %s", role, cam.sink_name)

    # ------------------------------------------------------------- status api

    def status(self, role: str) -> str:
        with self._lock:
            return self._status.get(role, "unknown")

    def status_all(self) -> dict[str, str]:
        with self._lock:
            return dict(self._status)

    def get_last_frame_age(self, role: str) -> float:
        with self._lock:
            cam = self._cameras.get(role)
        return cam.last_frame_age_seconds if cam is not None else float("inf")

    def get_camera_spec(self, role: str) -> CameraSpec | None:
        for spec in self._specs:
            if spec.role == role:
                return spec
        return None

    # ------------------------------------------------------------- error path

    def _handle_camera_error(self, role: str, err_message: str) -> None:
        """Called from a CameraPipeline's bus watch thread on error."""
        log.warning("camera_error: role=%s message=%s", role, err_message)
        prev = self.status(role)
        with self._lock:
            self._status[role] = "offline"
        if prev != "offline" and self._on_transition is not None:
            try:
                self._on_transition(role, prev, "offline", f"pipeline error: {err_message}")
            except Exception:
                log.exception("on_transition callback raised for role=%s", role)
        # Swap on the main loop (thread-safe dispatch)
        self._GLib.idle_add(self._idle_swap_to_fallback, role)
        # Schedule a reconnect attempt
        self._schedule_reconnect(role, _REBUILD_DELAY_S)

    def _idle_swap_to_fallback(self, role: str) -> bool:
        self.swap_to_fallback(role)
        return False  # remove idle source

    def _idle_swap_to_primary(self, role: str) -> bool:
        self.swap_to_primary(role)
        return False

    # ------------------------------------------------------------- supervisor

    def _start_supervisor(self) -> None:
        if self._supervisor_thread is not None and self._supervisor_thread.is_alive():
            return
        self._supervisor_stop.clear()
        self._supervisor_thread = threading.Thread(
            target=self._supervisor_loop, daemon=True, name="camera-supervisor"
        )
        self._supervisor_thread.start()

    def _schedule_reconnect(self, role: str, delay_s: float) -> None:
        wake_at = time.monotonic() + delay_s
        with self._supervisor_cv:
            heapq.heappush(self._reconnect_queue, (wake_at, role))
            self._supervisor_cv.notify()

    def _supervisor_loop(self) -> None:
        while not self._supervisor_stop.is_set():
            with self._supervisor_cv:
                while not self._reconnect_queue and not self._supervisor_stop.is_set():
                    self._supervisor_cv.wait()
                if self._supervisor_stop.is_set():
                    return
                wake_at, role = self._reconnect_queue[0]
                now = time.monotonic()
                if wake_at > now:
                    self._supervisor_cv.wait(timeout=wake_at - now)
                    continue
                heapq.heappop(self._reconnect_queue)

            self._attempt_reconnect(role)

    def _attempt_reconnect(self, role: str) -> None:
        with self._lock:
            cam = self._cameras.get(role)
        if cam is None:
            return
        log.info("supervisor: attempting reconnect for role=%s", role)
        ok = cam.rebuild()
        if ok:
            prev = self.status(role)
            with self._lock:
                self._status[role] = "active"
            self._GLib.idle_add(self._idle_swap_to_primary, role)
            if self._on_transition is not None and prev != "active":
                try:
                    self._on_transition(role, prev, "active", "reconnect succeeded")
                except Exception:
                    log.exception("on_transition callback raised for role=%s", role)
            log.info("supervisor: reconnect succeeded for role=%s", role)
        else:
            log.warning("supervisor: reconnect failed for role=%s, rescheduling", role)
            self._schedule_reconnect(role, _REBUILD_DELAY_S)

    # ------------------------------------------------------------------ stop

    def stop(self) -> None:
        self._supervisor_stop.set()
        with self._supervisor_cv:
            self._supervisor_cv.notify_all()
        if self._supervisor_thread is not None:
            self._supervisor_thread.join(timeout=2.0)
        with self._lock:
            for cam in self._cameras.values():
                cam.teardown()
            for fb in self._fallbacks.values():
                fb.teardown()
            self._cameras.clear()
            self._fallbacks.clear()
            self._interpipe_srcs.clear()
