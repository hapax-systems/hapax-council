"""v4l2sink stall auto-recovery (cc-task ``compositor-v4l2sink-graph-mutation-stall``).

The compositor's existing watchdog (``lifecycle.py::_watchdog_tick``) detects
v4l2sink stalls via ``compositor.v4l2_frame_seen_within(20.0)``: when the
sink hasn't pushed a buffer for >20 s, the tick withholds the systemd
``WATCHDOG=1`` ping. systemd's ``WatchdogSec=60s`` then SIGABRTs the unit.

Per the cc-task constraint **DO NOT suppress the watchdog**, this module
adds a recovery layer between detection and giving up: when the stall is
first observed, the watchdog tick calls :func:`attempt_recovery`, which
cycles the v4l2sink element ``PLAYING → NULL → PLAYING`` to force the
v4l2loopback fd to re-open. If recovery succeeds (a buffer crosses the
sink within :data:`_RECOVERY_PROBE_WINDOW_S`) the next tick resumes the
watchdog ping. If it fails, the recovery counter increments and the tick
withholds the ping as before — preserving the existing
"ping → systemd → SIGABRT" semantics for the unrecoverable case.

The ``StallRecoveryState`` instance lives on the compositor and tracks
consecutive failed recovery attempts; after :data:`_MAX_CONSECUTIVE_FAILURES`
the recovery layer escalates and the watchdog withholds the ping
unconditionally — i.e., the watchdog still has authority to kill the unit
when the stall is genuinely unrecoverable.

Three suspected root-cause classes (from the cc-task brief — recorded inline
here so the recovery module is its own RCA artifact):

1. **GStreamer pipeline state-change deadlock** during graph-mutation. A
   re-link of effect-chain elements while the pipeline is in PLAYING can
   deadlock when ``set_state(PAUSED)`` is invoked on a downstream element
   from inside an upstream ``pad_added`` callback. Trap and Datamosh both
   swap a high-fanout effect node so this is the front-runner.

2. **NVENC encoder reset latency** when v4l2sink upstream re-negotiates
   caps. NVENC SDK ``init`` blocks 15-30 s on cold start; two graph-
   mutations within the watchdog window can stack the latency.

3. **v4l2loopback driver stall** on consumer (OBS) disconnect/reconnect.
   v4l2loopback 0.13.x had outstanding ``select()/poll()`` semantics fixes
   for dropped readers; the device can wedge when writes queue without a
   draining reader.

Sink-only state cycling addresses (3) directly (it forces the device fd
to close + re-open) and partially addresses (1) by isolating the v4l2sink
subgraph from the upstream effect chain. Class (2) is not addressed by
this recovery — if the encoder is wedged, sink reattach won't help; the
watchdog SIGABRT is the only correct outcome.

Spec: `docs/research/2026-04-20-v4l2sink-stall-prevention.md` (Phase 1
detector). This module is Phase 2 (recovery).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

# Recovery window — after a recovery attempt completes, wait this many
# seconds for a buffer to cross the v4l2sink. Matches the watchdog's
# stall threshold (20 s) so a successful recovery is observably the same
# liveness signal the watchdog already uses.
_RECOVERY_PROBE_WINDOW_S: float = 6.0

# State-change timeout for each ``set_state`` call. Under GPU load
# (cudacompositor + 6 cameras + glfeedback), the v4l2sink may need
# more than 5s to complete state transitions — the upstream elements
# hold buffers that prevent the sink from reaching NULL synchronously.
# 10s gives enough headroom for the GPU to flush without timing out.
_STATE_CHANGE_TIMEOUT_S: float = 10.0

# Consecutive failed recoveries before the recovery layer escalates and
# stops attempting (lets the watchdog withhold ping → systemd SIGABRT).
# Three attempts is a Goldilocks number: enough to clear a transient
# v4l2loopback wedge, not so many that we stall in a recovery loop while
# OBS sees a black broadcast.
_MAX_CONSECUTIVE_FAILURES: int = 3

# Cool-down between recovery attempts. Without this, two ticks in
# rapid succession could fire two recovery attempts before the first
# completed its state cycle. 8 s ≈ one watchdog-tick interval (the tick
# fires every 20 s; 8 s is well inside the window so the cool-down
# never blocks a legitimate next-tick recovery, but does block a
# pathological double-fire from inside one tick).
_RECOVERY_COOLDOWN_S: float = 8.0


@dataclass
class StallRecoveryState:
    """Per-compositor recovery bookkeeping.

    Held under :attr:`lock`; instances should be created once at compositor
    construction and shared between the watchdog tick and any future
    callers that want to read the recovery counters for observability.
    """

    consecutive_failures: int = 0
    last_attempt_monotonic: float = 0.0
    total_attempts: int = 0
    total_successes: int = 0
    total_escalations: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> dict[str, Any]:
        """Thread-safe snapshot of the recovery counters for tests/observability."""

        with self.lock:
            return {
                "consecutive_failures": self.consecutive_failures,
                "last_attempt_monotonic": self.last_attempt_monotonic,
                "total_attempts": self.total_attempts,
                "total_successes": self.total_successes,
                "total_escalations": self.total_escalations,
            }


def _emit_metric(metric_name: str, label_value: str | None = None) -> None:
    """Emit a Prometheus counter increment, fail-open on missing metric.

    The watchdog tick must never break on a missing-metric edge case.
    Recovery telemetry is best-effort.
    """

    try:
        from agents.studio_compositor import metrics as _m

        counter = getattr(_m, metric_name, None)
        if counter is None:
            return
        if label_value is not None:
            counter.labels(label_value).inc()
        else:
            counter.inc()
    except Exception:
        log.debug("v4l2 stall metric emit failed for %s", metric_name, exc_info=True)


def _resolve_v4l2sink(compositor: Any) -> Any | None:
    """Look up the v4l2sink element on the compositor's pipeline.

    The element is named ``"output"`` per ``pipeline.py`` (line 201
    ``Gst.ElementFactory.make("v4l2sink", "output")``). Returns None if
    the pipeline is missing, the element is missing, or the lookup
    raises — the caller treats all three as "cannot recover, escalate".
    """

    pipeline = getattr(compositor, "pipeline", None)
    if pipeline is None:
        log.warning("v4l2 stall recovery: compositor has no pipeline attribute")
        return None
    try:
        sink = pipeline.get_by_name("output")
    except Exception:
        log.warning("v4l2 stall recovery: pipeline.get_by_name failed", exc_info=True)
        return None
    if sink is None:
        log.warning("v4l2 stall recovery: v4l2sink 'output' not found on pipeline")
    return sink


def _cycle_sink_state(sink: Any) -> bool:
    """Cycle the sink ``PLAYING → NULL → PLAYING`` with bounded waits.

    Each ``set_state`` is followed by a bounded ``get_state`` wait so a
    deadlock on the state transition is observable as a timeout rather
    than a wedge. Returns True if both transitions returned ``SUCCESS``,
    False otherwise (failure / async / timeout).
    """

    try:
        # Late Gst import so this module is importable in CI harnesses
        # that lack the gst-python typelibs.
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
    except Exception:
        log.warning("v4l2 stall recovery: Gst import failed", exc_info=True)
        return False

    timeout_ns = int(_STATE_CHANGE_TIMEOUT_S * Gst.SECOND)

    # PLAYING → NULL: closes the v4l2 fd, releases all buffers, drops
    # any caps negotiation state. v4l2loopback sees the fd close and
    # resets its consumer-disconnect state machine.
    try:
        ret = sink.set_state(Gst.State.NULL)
    except Exception:
        log.warning("v4l2 stall recovery: set_state(NULL) raised", exc_info=True)
        return False
    if ret == Gst.StateChangeReturn.FAILURE:
        log.warning("v4l2 stall recovery: set_state(NULL) returned FAILURE")
        return False
    state_ret, _state, _pending = sink.get_state(timeout_ns)
    if state_ret != Gst.StateChangeReturn.SUCCESS:
        log.warning("v4l2 stall recovery: get_state after NULL = %s", state_ret)
        return False

    # NULL → PLAYING: re-opens the v4l2 fd, re-negotiates caps, and
    # rejoins the pipeline state. Any pending CAPS event from upstream
    # is replayed by the surviving caps-dedup probe (see pipeline.py
    # _caps_dedup_probe — the probe stays installed across this cycle
    # because it's bound to the static sink pad which the element
    # retains across state changes).
    try:
        ret = sink.set_state(Gst.State.PLAYING)
    except Exception:
        log.warning("v4l2 stall recovery: set_state(PLAYING) raised", exc_info=True)
        return False
    if ret == Gst.StateChangeReturn.FAILURE:
        log.warning("v4l2 stall recovery: set_state(PLAYING) returned FAILURE")
        return False
    state_ret, _state, _pending = sink.get_state(timeout_ns)
    if state_ret != Gst.StateChangeReturn.SUCCESS:
        log.warning("v4l2 stall recovery: get_state after PLAYING = %s", state_ret)
        return False
    return True


def _wait_for_frame(compositor: Any, *, window_s: float = _RECOVERY_PROBE_WINDOW_S) -> bool:
    """Poll ``v4l2_frame_seen_within`` until a frame lands or window elapses."""

    deadline = time.monotonic() + window_s
    while time.monotonic() < deadline:
        try:
            if compositor.v4l2_frame_seen_within(2.0):
                return True
        except Exception:
            log.debug("v4l2_frame_seen_within probe raised", exc_info=True)
            return False
        time.sleep(0.25)
    return False


def attempt_recovery(
    compositor: Any,
    state: StallRecoveryState,
    *,
    now: float | None = None,
) -> bool:
    """Try to recover the stalled v4l2sink. Returns True on success.

    Flow:

    1. Cool-down check — at least :data:`_RECOVERY_COOLDOWN_S` seconds
       must have elapsed since the last attempt. If not, return False
       without escalating (the consecutive_failures count is unchanged
       so a legitimate next-tick attempt still counts).
    2. Resolve the v4l2sink element. Missing pipeline / missing element
       → escalation path immediately.
    3. Cycle ``PLAYING → NULL → PLAYING`` with bounded state-change
       timeouts.
    4. Wait up to :data:`_RECOVERY_PROBE_WINDOW_S` for a buffer to cross
       the sink probe — same liveness signal the watchdog already uses.
    5. Update counters, emit Prometheus telemetry, return outcome.

    The caller (lifecycle ``_watchdog_tick``) consults
    :func:`should_escalate` to decide whether to withhold the ping.
    """

    ts = time.monotonic() if now is None else now
    with state.lock:
        if (
            state.last_attempt_monotonic > 0.0
            and (ts - state.last_attempt_monotonic) < _RECOVERY_COOLDOWN_S
        ):
            return False
        state.last_attempt_monotonic = ts
        state.total_attempts += 1

    log.warning(
        "v4l2 stall recovery: attempting sink reattach "
        "(consecutive_failures=%d, total_attempts=%d)",
        state.consecutive_failures,
        state.total_attempts,
    )
    _emit_metric("V4L2SINK_STALL_TOTAL", "detected")

    sink = _resolve_v4l2sink(compositor)
    if sink is None:
        with state.lock:
            state.consecutive_failures += 1
        _emit_metric("V4L2SINK_RECOVERY_TOTAL", "failed_no_sink")
        return False

    cycled = _cycle_sink_state(sink)
    if not cycled:
        with state.lock:
            state.consecutive_failures += 1
        _emit_metric("V4L2SINK_RECOVERY_TOTAL", "failed_state_change")
        return False

    if not _wait_for_frame(compositor):
        with state.lock:
            state.consecutive_failures += 1
        _emit_metric("V4L2SINK_RECOVERY_TOTAL", "failed_no_frame")
        log.warning(
            "v4l2 stall recovery: state cycle succeeded but no frame "
            "within %.1fs — recovery failed (consecutive=%d)",
            _RECOVERY_PROBE_WINDOW_S,
            state.consecutive_failures + 0,
        )
        return False

    with state.lock:
        state.consecutive_failures = 0
        state.total_successes += 1
    _emit_metric("V4L2SINK_RECOVERY_TOTAL", "ok")
    log.info(
        "v4l2 stall recovery: sink reattach succeeded (total_successes=%d)",
        state.total_successes,
    )
    return True


def should_escalate(state: StallRecoveryState) -> bool:
    """True iff consecutive failures hit the escalation threshold.

    The lifecycle watchdog calls this *after* :func:`attempt_recovery`
    returns False; if it returns True, the watchdog withholds the ping
    so systemd's WatchdogSec=60s will SIGABRT the unit. The original
    "v4l2sink stall detected — withholding watchdog ping" semantics is
    preserved for the unrecoverable case.
    """

    with state.lock:
        if state.consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
            state.total_escalations += 1
            _emit_metric("V4L2SINK_RECOVERY_TOTAL", "escalated")
            log.error(
                "v4l2 stall recovery: %d consecutive failures — escalating "
                "(let systemd watchdog SIGABRT the unit)",
                state.consecutive_failures,
            )
            return True
        return False


__all__ = [
    "StallRecoveryState",
    "attempt_recovery",
    "should_escalate",
]
