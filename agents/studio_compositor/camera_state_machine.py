"""Per-camera recovery state machine with exponential backoff.

Phase 3 of the camera 24/7 resilience epic.

See docs/superpowers/specs/2026-04-12-camera-recovery-state-machine-design.md

Pure-Python FSM — no GStreamer imports. All external side effects (rebuild,
hot-swap, ntfy, metrics, reconnect scheduling) go through injected callbacks
so the state machine is directly testable without mocking GStreamer.
"""

from __future__ import annotations

import enum
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


class CameraState(enum.Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    RECOVERING = "recovering"
    DEAD = "dead"


class EventKind(enum.Enum):
    FRAME_FLOW_OBSERVED = "frame_flow_observed"
    FRAME_FLOW_STALE = "frame_flow_stale"
    WATCHDOG_FIRED = "watchdog_fired"
    PIPELINE_ERROR = "pipeline_error"
    SWAP_COMPLETED = "swap_completed"
    DEVICE_REMOVED = "device_removed"
    DEVICE_ADDED = "device_added"
    BACKOFF_ELAPSED = "backoff_elapsed"
    RECOVERY_SUCCEEDED = "recovery_succeeded"
    RECOVERY_FAILED = "recovery_failed"
    OPERATOR_REARM = "operator_rearm"
    OPERATOR_FORCE_RECONNECT = "operator_force_reconnect"


@dataclass
class Event:
    kind: EventKind
    timestamp: float = field(default_factory=time.monotonic)
    reason: str = ""
    source: str = ""  # "watchdog", "bus", "udev", "operator", "supervisor"


MAX_CONSECUTIVE_FAILURES = 10
BACKOFF_CEILING_S = 60.0
STALENESS_THRESHOLD_S = 2.0


class CameraStateMachine:
    """Per-camera recovery FSM.

    States: HEALTHY -> DEGRADED -> OFFLINE -> RECOVERING -> HEALTHY
            with escalation to DEAD after MAX_CONSECUTIVE_FAILURES.

    Exponential backoff: delay(n) = min(60, 2^n). The failure counter
    increments on any failure path (RECOVERY_FAILED, mid-stream
    PIPELINE_ERROR / FRAME_FLOW_STALE / WATCHDOG_FIRED) and resets only
    on operator action (OPERATOR_FORCE_RECONNECT, DEVICE_ADDED,
    OPERATOR_REARM) or sustained frame flow (FRAME_FLOW_OBSERVED while
    HEALTHY). RECOVERY_SUCCEEDED alone does NOT reset — GStreamer can
    reach PLAYING then fail on the first buffer (e.g., USB isoc
    bandwidth exhaustion), in which case the reconnect loop would
    otherwise run forever at 1 Hz without ever escalating to DEAD.
    """

    def __init__(
        self,
        role: str,
        *,
        on_schedule_reconnect: Callable[[float], None] | None = None,
        on_swap_to_fallback: Callable[[], None] | None = None,
        on_swap_to_primary: Callable[[], None] | None = None,
        on_notify_transition: Callable[[CameraState, CameraState, str], None] | None = None,
    ) -> None:
        self._role = role
        self._state = CameraState.HEALTHY
        self._consecutive_failures = 0
        self._lock = threading.RLock()
        self._last_transition_monotonic = time.monotonic()
        self._on_schedule_reconnect = on_schedule_reconnect
        self._on_swap_to_fallback = on_swap_to_fallback
        self._on_swap_to_primary = on_swap_to_primary
        self._on_notify_transition = on_notify_transition

    @property
    def role(self) -> str:
        return self._role

    @property
    def state(self) -> CameraState:
        with self._lock:
            return self._state

    @property
    def consecutive_failures(self) -> int:
        with self._lock:
            return self._consecutive_failures

    def dispatch(self, event: Event) -> None:
        """Dispatch an event. Thread-safe. Runs side-effect callbacks on
        transition (outside the critical section where practical)."""
        with self._lock:
            old_state = self._state
            new_state = self._transition(event)
            if new_state is None or new_state == old_state:
                return
            self._state = new_state
            self._last_transition_monotonic = time.monotonic()
            log.info(
                "camera state: role=%s %s→%s reason=%r failures=%d",
                self._role,
                old_state.value,
                new_state.value,
                event.reason,
                self._consecutive_failures,
            )
            transition_from = old_state
            transition_to = new_state
            reason = event.reason

        # Run side effects outside the lock
        self._perform_side_effects(transition_from, transition_to)
        if self._on_notify_transition is not None:
            try:
                self._on_notify_transition(transition_from, transition_to, reason)
            except Exception:
                log.exception("on_notify_transition raised for role=%s", self._role)

    def _transition(self, event: Event) -> CameraState | None:
        """Pure transition logic. Caller holds _lock."""
        s = self._state
        e = event.kind

        if s == CameraState.HEALTHY:
            if e in (
                EventKind.WATCHDOG_FIRED,
                EventKind.FRAME_FLOW_STALE,
                EventKind.PIPELINE_ERROR,
            ):
                # Mid-stream failure: pipeline reached PLAYING but can't
                # hold the stream (e.g., USB isoc bandwidth rejection on
                # first buffer). Count toward the DEAD budget so
                # exponential backoff escalates.
                self._consecutive_failures += 1
                if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    return CameraState.DEAD
                return CameraState.DEGRADED
            if e == EventKind.DEVICE_REMOVED:
                return CameraState.OFFLINE
            if e == EventKind.OPERATOR_FORCE_RECONNECT:
                self._consecutive_failures = 0
                return CameraState.RECOVERING
            if e == EventKind.FRAME_FLOW_OBSERVED:
                # Sustained-success signal from the frame-flow watchdog
                # (post grace window). This — not RECOVERY_SUCCEEDED — is
                # what resets the failure counter.
                self._consecutive_failures = 0
                return CameraState.HEALTHY
            return None

        if s == CameraState.DEGRADED:
            if e == EventKind.SWAP_COMPLETED:
                return CameraState.OFFLINE
            if e == EventKind.DEVICE_REMOVED:
                return CameraState.OFFLINE
            if e == EventKind.PIPELINE_ERROR:
                return CameraState.OFFLINE
            return None

        if s == CameraState.OFFLINE:
            if e == EventKind.BACKOFF_ELAPSED:
                return CameraState.RECOVERING
            if e == EventKind.DEVICE_ADDED:
                self._consecutive_failures = 0
                return CameraState.RECOVERING
            if e == EventKind.OPERATOR_FORCE_RECONNECT:
                self._consecutive_failures = 0
                return CameraState.RECOVERING
            return None

        if s == CameraState.RECOVERING:
            if e == EventKind.RECOVERY_SUCCEEDED:
                # Pipeline reached PLAYING but no frames are guaranteed yet.
                # Stay RECOVERING; promotion back to HEALTHY happens only
                # after the frame-flow watchdog observes post-rebuild buffers.
                return CameraState.RECOVERING
            if e == EventKind.FRAME_FLOW_OBSERVED:
                self._consecutive_failures = 0
                return CameraState.HEALTHY
            if e == EventKind.FRAME_FLOW_STALE:
                self._consecutive_failures += 1
                if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    return CameraState.DEAD
                return CameraState.OFFLINE
            if e == EventKind.RECOVERY_FAILED:
                self._consecutive_failures += 1
                if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    return CameraState.DEAD
                return CameraState.OFFLINE
            if e == EventKind.DEVICE_REMOVED:
                return CameraState.OFFLINE
            if e == EventKind.PIPELINE_ERROR:
                self._consecutive_failures += 1
                if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    return CameraState.DEAD
                return CameraState.OFFLINE
            return None

        if s == CameraState.DEAD:
            if e == EventKind.OPERATOR_REARM:
                self._consecutive_failures = 0
                return CameraState.OFFLINE
            return None

        return None

    def _perform_side_effects(self, old: CameraState, new: CameraState) -> None:
        """Execute the effect of a transition. Outside the lock to avoid
        reentrance risk in callbacks."""
        if new == CameraState.DEGRADED:
            if self._on_swap_to_fallback is not None:
                try:
                    self._on_swap_to_fallback()
                except Exception:
                    log.exception("on_swap_to_fallback raised for role=%s", self._role)

        elif new == CameraState.OFFLINE and old != CameraState.DEAD:
            delay = self._compute_backoff()
            if self._on_schedule_reconnect is not None:
                try:
                    self._on_schedule_reconnect(delay)
                except Exception:
                    log.exception("on_schedule_reconnect raised for role=%s", self._role)

        elif new == CameraState.RECOVERING:
            # Supervisor thread drives the rebuild; state machine doesn't
            # need to do anything synchronous here.
            pass

        elif new == CameraState.HEALTHY and old != CameraState.HEALTHY:
            if self._on_swap_to_primary is not None:
                try:
                    self._on_swap_to_primary()
                except Exception:
                    log.exception("on_swap_to_primary raised for role=%s", self._role)

    def _compute_backoff(self) -> float:
        """Exponential backoff with 60s ceiling. delay(n) = min(60, 2^n)."""
        n = self._consecutive_failures
        if n >= 6:
            return BACKOFF_CEILING_S
        return float(2**n)
