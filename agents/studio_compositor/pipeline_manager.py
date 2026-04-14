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

from . import metrics
from .camera_pipeline import CameraPipeline
from .camera_state_machine import (
    STALENESS_THRESHOLD_S,
    CameraState,
    CameraStateMachine,
    Event,
    EventKind,
)
from .fallback_pipeline import FallbackPipeline
from .models import CameraSpec

log = logging.getLogger(__name__)


_REBUILD_DELAY_S = 5.0

# Livestream-performance-map W5 NEW (silent-failure class): how often
# the frame-flow watchdog wakes to verify each HEALTHY camera is still
# delivering frames at the pad probe.
_FRAME_FLOW_TICK_S = 1.0
# Post-recovery grace window: after RECOVERY_SUCCEEDED dispatches and
# the FSM lands back in HEALTHY, give the rebuilt pipeline this many
# seconds to start producing frames before the watchdog can mark it
# stale. CameraPipeline state transition to PLAYING is async — the
# first buffer typically arrives within a frame or two but a tight
# threshold creates a false-fire window. Five seconds is generous.
_FRAME_FLOW_GRACE_S = 5.0


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
        self._state_machines: dict[str, CameraStateMachine] = {}
        self._lock = threading.RLock()

        self._supervisor_stop = threading.Event()
        self._supervisor_cv = threading.Condition(threading.Lock())
        self._reconnect_queue: list[tuple[float, str]] = []
        self._supervisor_thread: threading.Thread | None = None

        # W5 NEW frame-flow watchdog state.
        self._frame_flow_stop = threading.Event()
        self._frame_flow_thread: threading.Thread | None = None
        self._last_recovery_at: dict[str, float] = {}

    # ------------------------------------------------------------------ build

    def build(self) -> None:
        """Instantiate + start all producer + fallback pipelines and
        per-camera state machines."""
        with self._lock:
            for spec in self._specs:
                # Phase 4: register metrics labels before anything else so
                # CAM_FRAMES_TOTAL{role=...} appears in scrapes immediately.
                model = getattr(spec, "camera_class", None) or "unknown"
                metrics.register_camera(spec.role, model)

                try:
                    fb = FallbackPipeline(spec, gst=self._Gst, fps=self._fps)
                    fb.build()
                    fb.start()
                    self._fallbacks[spec.role] = fb
                except Exception:
                    log.exception("fallback pipeline for %s: build failed", spec.role)

                # Phase 3: construct the state machine before the camera
                # pipeline so error callbacks route through the FSM.
                self._state_machines[spec.role] = self._make_state_machine(spec.role)

                # Delta 2026-04-14-brio-operator-startup-stall-reproducible:
                # prime ``_last_recovery_at[role]`` at build time so the
                # frame-flow watchdog's ``_FRAME_FLOW_GRACE_S`` (5 s)
                # window ALSO covers cold-start first-frame latency, not
                # just post-recovery latency. Without this prime, the
                # first camera (typically brio-operator) takes the
                # grace-bypass branch in ``_frame_flow_tick_once``
                # (``recovered_at is not None and …``) and fires
                # ``FRAME_FLOW_STALE`` ~1 s after ``swap_to_primary``
                # because its first frame hasn't arrived yet. Measured:
                # ~3.3 s of lost data per compositor restart on
                # brio-operator, reproducible across 4/4 cold starts
                # sampled 2026-04-14. ``time.monotonic()`` matches the
                # watchdog's own clock.
                self._last_recovery_at[spec.role] = time.monotonic()

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
                        # Force the FSM into OFFLINE via a synthetic error event
                        sm = self._state_machines[spec.role]
                        sm.dispatch(
                            Event(
                                EventKind.PIPELINE_ERROR,
                                reason="start failed at build",
                                source="build",
                            )
                        )
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
            sm = self._state_machines.get(role)
        if src is None or fb is None:
            return
        src.set_property("listen-to", fb.sink_name)
        metrics.on_swap(role, to_fallback=True)
        log.info("swap_to_fallback: role=%s → %s", role, fb.sink_name)
        # W5 NEW: dispatch SWAP_COMPLETED back into the FSM so DEGRADED
        # advances to OFFLINE and the supervisor schedules a rebuild.
        # Without this, DEGRADED is a sink — there's no other dispatcher
        # of SWAP_COMPLETED in the system. Only fire when the FSM is
        # actually waiting on it (DEGRADED), otherwise this is a no-op
        # at registration-time swaps.
        if sm is not None and sm.state == CameraState.DEGRADED:
            sm.dispatch(
                Event(
                    EventKind.SWAP_COMPLETED,
                    reason="fallback active",
                    source="pipeline_manager",
                )
            )

    def swap_to_primary(self, role: str) -> None:
        with self._lock:
            src = self._interpipe_srcs.get(role)
            cam = self._cameras.get(role)
        if src is None or cam is None:
            return
        src.set_property("listen-to", cam.sink_name)
        metrics.on_swap(role, to_fallback=False)
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
        sm = self._state_machines.get(role)
        if sm is not None:
            sm.dispatch(
                Event(
                    EventKind.PIPELINE_ERROR,
                    reason=err_message,
                    source="bus",
                )
            )
            return

        # Legacy path — only if no state machine is installed (shouldn't happen)
        prev = self.status(role)
        with self._lock:
            self._status[role] = "offline"
        if prev != "offline" and self._on_transition is not None:
            try:
                self._on_transition(role, prev, "offline", f"pipeline error: {err_message}")
            except Exception:
                log.exception("on_transition callback raised for role=%s", role)
        self._GLib.idle_add(self._idle_swap_to_fallback, role)
        self._schedule_reconnect(role, _REBUILD_DELAY_S)

    def on_device_added(self, role: str, dev_node: str) -> None:
        """Called from UdevCameraMonitor on a video4linux add event."""
        sm = self._state_machines.get(role)
        if sm is None:
            return
        sm.dispatch(
            Event(
                EventKind.DEVICE_ADDED,
                reason=f"udev add: {dev_node}",
                source="udev",
            )
        )

    def on_device_removed(self, role: str, reason: str) -> None:
        """Called from UdevCameraMonitor on a video4linux/usb remove event."""
        sm = self._state_machines.get(role)
        if sm is None:
            return
        sm.dispatch(
            Event(
                EventKind.DEVICE_REMOVED,
                reason=reason,
                source="udev",
            )
        )

    def role_for_device_node(self, dev_node: str) -> str | None:
        """Map /dev/videoN or /dev/v4l/by-id/... to a camera role."""
        for spec in self._specs:
            if spec.device == dev_node:
                return spec.role
            # Match the by-id path to the kernel device node via readlink
            try:
                from pathlib import Path

                if (
                    Path(spec.device).exists()
                    and Path(spec.device).resolve() == Path(dev_node).resolve()
                ):
                    return spec.role
            except Exception:
                pass
        return None

    def role_for_serial(self, serial: str) -> str | None:
        """Map a USB serial to a camera role by substring in the by-id path."""
        for spec in self._specs:
            if serial and serial in spec.device:
                return spec.role
        return None

    def _make_state_machine(self, role: str) -> CameraStateMachine:
        """Construct a state machine for a given camera role with callbacks
        wired to the pipeline manager's side-effect surface."""

        def _schedule(delay: float) -> None:
            self._schedule_reconnect(role, delay)

        def _swap_fb() -> None:
            self._GLib.idle_add(self._idle_swap_to_fallback, role)

        def _swap_primary() -> None:
            self._GLib.idle_add(self._idle_swap_to_primary, role)

        def _notify(old: CameraState, new: CameraState, reason: str) -> None:
            # Phase 4: update Prometheus state + transition metrics first
            metrics.on_state_transition(role, old.value, new.value)

            # Map CameraState to the compositor's existing active/offline
            # convention so callers that touch compositor._camera_status
            # (director loop, overlays, health monitor) keep working without
            # a separate change.
            legacy_old = "active" if old == CameraState.HEALTHY else "offline"
            legacy_new = "active" if new == CameraState.HEALTHY else "offline"
            with self._lock:
                self._status[role] = legacy_new
            if self._on_transition is not None and legacy_old != legacy_new:
                try:
                    self._on_transition(role, legacy_old, legacy_new, reason)
                except Exception:
                    log.exception("on_transition callback raised for role=%s", role)

        return CameraStateMachine(
            role=role,
            on_schedule_reconnect=_schedule,
            on_swap_to_fallback=_swap_fb,
            on_swap_to_primary=_swap_primary,
            on_notify_transition=_notify,
        )

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
        self._start_frame_flow_watchdog()

    def _start_frame_flow_watchdog(self) -> None:
        if self._frame_flow_thread is not None and self._frame_flow_thread.is_alive():
            return
        self._frame_flow_stop.clear()
        self._frame_flow_thread = threading.Thread(
            target=self._frame_flow_loop, daemon=True, name="camera-frame-flow-watchdog"
        )
        self._frame_flow_thread.start()

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

    def _frame_flow_loop(self) -> None:
        """Periodic per-camera frame-flow staleness check.

        For every HEALTHY camera, dispatch FRAME_FLOW_STALE if the
        pad-probe-observed last_frame_age has exceeded the threshold,
        unless the camera is still in its post-recovery grace window.
        """
        while not self._frame_flow_stop.wait(_FRAME_FLOW_TICK_S):
            try:
                self._frame_flow_tick_once()
            except Exception:
                log.exception("frame-flow watchdog tick raised")

    def _frame_flow_tick_once(self) -> None:
        """Single sweep over all cameras. Public for tests."""
        now = time.monotonic()
        with self._lock:
            roles = list(self._state_machines.keys())
            recovery_snapshot = dict(self._last_recovery_at)

        for role in roles:
            sm = self._state_machines.get(role)
            if sm is None or sm.state != CameraState.HEALTHY:
                continue
            recovered_at = recovery_snapshot.get(role)
            if recovered_at is not None and (now - recovered_at) < _FRAME_FLOW_GRACE_S:
                continue
            age = self.get_last_frame_age(role)
            if age <= STALENESS_THRESHOLD_S:
                continue
            log.warning(
                "frame-flow watchdog: role=%s last_frame_age=%.2fs > %.2fs — dispatching FRAME_FLOW_STALE",
                role,
                age,
                STALENESS_THRESHOLD_S,
            )
            metrics.on_frame_flow_stale(role)
            sm.dispatch(
                Event(
                    EventKind.FRAME_FLOW_STALE,
                    reason=f"pad-probe age {age:.2f}s",
                    source="watchdog",
                )
            )

    def _attempt_reconnect(self, role: str) -> None:
        with self._lock:
            cam = self._cameras.get(role)
            sm = self._state_machines.get(role)
        if cam is None:
            return
        log.info("supervisor: attempting reconnect for role=%s", role)

        # Phase 3: dispatch BACKOFF_ELAPSED which transitions OFFLINE → RECOVERING
        if sm is not None:
            sm.dispatch(
                Event(
                    EventKind.BACKOFF_ELAPSED,
                    reason="supervisor timer",
                    source="supervisor",
                )
            )

        ok = cam.rebuild()
        metrics.on_reconnect_result(role, ok)
        metrics.on_pipeline_restart(f"cam_{role}")
        if sm is not None:
            sm.dispatch(
                Event(
                    EventKind.RECOVERY_SUCCEEDED if ok else EventKind.RECOVERY_FAILED,
                    reason="rebuild ok" if ok else "rebuild failed",
                    source="supervisor",
                )
            )
            metrics.on_consecutive_failures_changed(role, sm.consecutive_failures)
            if ok:
                # W5 NEW: timestamp the recovery so the frame-flow
                # watchdog gives the rebuilt pipeline a grace window
                # before checking pad-probe staleness.
                with self._lock:
                    self._last_recovery_at[role] = time.monotonic()
            # The state machine schedules its own next retry via its
            # on_schedule_reconnect callback on failure; no need to
            # schedule again here.
            return

        # Legacy path if no state machine is present
        if ok:
            with self._lock:
                self._status[role] = "active"
            self._GLib.idle_add(self._idle_swap_to_primary, role)
        else:
            log.warning("supervisor: reconnect failed for role=%s, rescheduling", role)
            self._schedule_reconnect(role, _REBUILD_DELAY_S)

    # ------------------------------------------------------------------ stop

    def stop(self) -> None:
        self._supervisor_stop.set()
        with self._supervisor_cv:
            self._supervisor_cv.notify_all()
        self._frame_flow_stop.set()
        if self._supervisor_thread is not None:
            self._supervisor_thread.join(timeout=2.0)
        if self._frame_flow_thread is not None:
            self._frame_flow_thread.join(timeout=2.0)
        with self._lock:
            for cam in self._cameras.values():
                cam.teardown()
            for fb in self._fallbacks.values():
                fb.teardown()
            self._cameras.clear()
            self._fallbacks.clear()
            self._interpipe_srcs.clear()
