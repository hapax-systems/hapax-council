# Camera Recovery State Machine — Design (Camera Epic Phase 3)

**Filed:** 2026-04-12
**Status:** Formal design. Implementation in Phase 3 of the camera resilience epic.
**Epic:** `docs/superpowers/plans/2026-04-12-camera-247-resilience-epic.md`
**Depends on:** Phase 2 (`2026-04-12-compositor-hot-swap-architecture-design.md`) merged.

## Purpose

Formalize per-camera recovery into a five-state state machine with exponential backoff, pyudev-driven event integration, and udev-driven system-level reconfiguration. Replace Phase 2's stub fixed-delay reconnect with a proper circuit-breaker pattern that can distinguish transient USB stalls, hard disconnects, and permanently dead cameras, and escalate through appropriate recovery actions without generating kernel-log noise or exhausting systemd restart budgets.

The Phase 2 stub reconnects every 5 s unconditionally. That is adequate for the "USB stall cleared after one hub reset" case but wastes kernel time on hard failures and leaves the operator with no visible escalation when recovery is impossible.

## Requirements

- **R1.** State transitions are deterministic and testable in pure Python without GStreamer (the state machine is a pure-function object driven by discrete events).
- **R2.** Exponential backoff on reconnection attempts: 1 s, 2 s, 4 s, 8 s, 16 s, 32 s, 60 s ceiling. After 10 consecutive failures, enter `DEAD` state and stop trying automatically.
- **R3.** External events drive transitions: watchdog fire, pipeline error bus message, frame-flow observation, pyudev device add/remove, manual operator command.
- **R4.** Recovery attempts acquire an exclusive in-process lock per camera role so that two concurrent triggers do not stomp on each other.
- **R5.** On `add` events for a known camera VID/PID, udev re-runs the `v4l2-ctl` reconfiguration script before the compositor's pyudev handler attempts to bring the camera back into PLAYING. System-level configuration is always applied before software-level reconnection.
- **R6.** Every state transition produces a structured log event (role, from_state, to_state, reason, counter values) and a throttled ntfy notification.
- **R7.** `DEAD` state is operator-only-exit — the automatic loop never transitions out of `DEAD`. Operator uses a command-line tool or an affordance to manually re-arm.
- **R8.** The state machine is thread-safe. Events may be delivered from GStreamer streaming threads, the supervisor thread, the pyudev observer thread, or the GLib main loop thread.

## States

```
       ┌───────────┐  frame_flow_ok   ┌───────────┐
       │ RECOVERING├─────────────────▶│  HEALTHY  │
       └──────┬────┘                  └───┬───────┘
              ▲                           │
              │                           │ watchdog / bus_error / device_remove
              │ backoff_elapsed           ▼
              │                       ┌───────────┐
              │                       │ DEGRADED  │
              │                       └───┬───────┘
              │                           │ swap_completed
              │                           ▼
              │                       ┌───────────┐
              │                       │  OFFLINE  │
              │                       └───┬───────┘
              │                           │
              └───────────────────────────┘

                                          │ retry_budget_exhausted
                                          ▼
                                      ┌──────────┐
                                      │   DEAD   │ (operator-only exit)
                                      └──────────┘
```

Five states:

- **HEALTHY** — consumer is listening to `cam_<role>` and frames are flowing within the staleness window. Steady state.
- **DEGRADED** — a fault has been observed (watchdog fire or bus error). The manager has not yet swapped the consumer to the fallback. Transient state; duration typically < 100 ms.
- **OFFLINE** — the consumer has been swapped to `fb_<role>`. The fallback pipeline is driving the composite slot. Reconnection attempts occur on a backoff schedule.
- **RECOVERING** — an operator or pyudev event has triggered a reconnect attempt. The camera producer pipeline is being rebuilt from NULL → PLAYING. On success: back to HEALTHY, consumer swaps back to primary. On failure: back to OFFLINE with the failure counter incremented.
- **DEAD** — too many consecutive reconnect failures. Automatic recovery is abandoned. Operator intervention required.

## Events

Events are the only way to transition between states. They are first-class objects with a timestamp and a source.

| Event | Triggered by | Valid from | Transitions to |
|-------|-------------|------------|----------------|
| `FrameFlowObserved` | A frame arrived at the producer's interpipesink (observed via pad probe) | HEALTHY, RECOVERING | HEALTHY |
| `FrameFlowStale` | Pad probe observes no frames for `staleness_threshold_s` | HEALTHY | DEGRADED |
| `WatchdogFired` | `GST_MESSAGE_ERROR` from `watchdog_<role>` in producer bus | HEALTHY | DEGRADED |
| `PipelineError` | Any `GST_MESSAGE_ERROR` from producer bus | HEALTHY, DEGRADED, RECOVERING | DEGRADED, OFFLINE, OFFLINE |
| `SwapCompleted` | `PipelineManager.swap_to_fallback(role)` returned | DEGRADED | OFFLINE |
| `DeviceRemoved` | pyudev emits `video4linux remove` for this camera's dev path | any | OFFLINE |
| `DeviceAdded` | pyudev emits `video4linux add` with matching VID/PID/serial | OFFLINE | RECOVERING (reset backoff counter) |
| `BackoffElapsed` | Supervisor thread timer fires | OFFLINE | RECOVERING |
| `RecoverySucceeded` | Rebuild + swap_to_primary succeeded | RECOVERING | HEALTHY (reset counter) |
| `RecoveryFailed` | Rebuild failed | RECOVERING | OFFLINE (increment counter) |
| `RetryBudgetExhausted` | Counter exceeds `MAX_CONSECUTIVE_FAILURES` | RECOVERING | DEAD |
| `OperatorRearm` | CLI / affordance / test fixture | DEAD | OFFLINE (reset counter) |
| `OperatorForceReconnect` | CLI / affordance | HEALTHY, DEGRADED, OFFLINE | RECOVERING |

## Backoff math

Exponential backoff with a 60 s ceiling:

```
delay(n) = min(60, 2^n)    # n = 0-indexed consecutive failure count
```

| n | delay(n) | cumulative |
|---|----------|-----------|
| 0 | 1 s | 1 s |
| 1 | 2 s | 3 s |
| 2 | 4 s | 7 s |
| 3 | 8 s | 15 s |
| 4 | 16 s | 31 s |
| 5 | 32 s | 63 s |
| 6 | 60 s | 123 s |
| 7 | 60 s | 183 s |
| 8 | 60 s | 243 s |
| 9 | 60 s | 303 s |
| 10+ | DEAD | — |

Rationale:
- The first four attempts (1 + 2 + 4 + 8 = 15 s) cover transient USB stalls without spamming the kernel.
- The middle attempts (16 + 32 = 48 s) cover bus-level recoveries that need settling time.
- The 60 s ceiling prevents compounding delays from making recovery visibly slow.
- 10 consecutive failures with the 60 s ceiling means ~5 minutes of retries. Long enough to recover from every transient cause observed in production; short enough that operators notice.

`DeviceAdded` resets the counter to zero before transitioning to RECOVERING, because physical re-plug is strong evidence that the problem just changed and the old backoff state is no longer informative.

`RecoverySucceeded` also resets the counter.

## State machine implementation

`agents/studio_compositor/camera_state_machine.py` (new file).

```python
from __future__ import annotations

import enum
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

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
    def __init__(
        self,
        role: str,
        *,
        on_schedule_reconnect: Callable[[float], None],
        on_swap_to_fallback: Callable[[], None],
        on_swap_to_primary: Callable[[], None],
        on_rebuild: Callable[[], bool],
        on_notify_transition: Callable[[CameraState, CameraState, str], None],
    ) -> None:
        self._role = role
        self._state = CameraState.HEALTHY
        self._consecutive_failures = 0
        self._lock = threading.RLock()
        self._last_transition_monotonic = time.monotonic()
        self._on_schedule_reconnect = on_schedule_reconnect
        self._on_swap_to_fallback = on_swap_to_fallback
        self._on_swap_to_primary = on_swap_to_primary
        self._on_rebuild = on_rebuild
        self._on_notify_transition = on_notify_transition

    @property
    def state(self) -> CameraState:
        with self._lock:
            return self._state

    @property
    def consecutive_failures(self) -> int:
        with self._lock:
            return self._consecutive_failures

    def dispatch(self, event: Event) -> None:
        with self._lock:
            old_state = self._state
            new_state = self._transition(event)
            if new_state is not None and new_state != old_state:
                self._state = new_state
                self._last_transition_monotonic = time.monotonic()
                self._on_notify_transition(old_state, new_state, event.reason)
                log.info(
                    "camera state: role=%s %s→%s reason=%r failures=%d",
                    self._role,
                    old_state.value,
                    new_state.value,
                    event.reason,
                    self._consecutive_failures,
                )
                self._perform_side_effects(old_state, new_state, event)

    def _transition(self, event: Event) -> Optional[CameraState]:
        """Pure-function state transition. Returns new state or None (ignored)."""
        s = self._state
        e = event.kind

        if s == CameraState.HEALTHY:
            if e in (EventKind.WATCHDOG_FIRED, EventKind.FRAME_FLOW_STALE, EventKind.PIPELINE_ERROR):
                return CameraState.DEGRADED
            if e == EventKind.DEVICE_REMOVED:
                return CameraState.OFFLINE
            if e == EventKind.OPERATOR_FORCE_RECONNECT:
                self._consecutive_failures = 0
                return CameraState.RECOVERING
            if e == EventKind.FRAME_FLOW_OBSERVED:
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
                self._consecutive_failures = 0
                return CameraState.HEALTHY
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

    def _perform_side_effects(
        self, old: CameraState, new: CameraState, event: Event
    ) -> None:
        """Execute the effect of a transition. Caller holds _lock."""
        if new == CameraState.DEGRADED:
            self._on_swap_to_fallback()
        elif new == CameraState.OFFLINE and old != CameraState.DEAD:
            delay = self._compute_backoff()
            self._on_schedule_reconnect(delay)
        elif new == CameraState.RECOVERING:
            pass  # supervisor thread drives rebuild asynchronously
        elif new == CameraState.HEALTHY and old != CameraState.HEALTHY:
            self._on_swap_to_primary()

    def _compute_backoff(self) -> float:
        n = self._consecutive_failures
        return min(BACKOFF_CEILING_S, float(2 ** n))
```

Pure Python, no GStreamer dependencies inside the state machine. All external interactions go through injected callbacks. Directly testable with mock callbacks.

## Side effects (execution outside the state machine)

The state machine does not perform I/O beyond logging. Its callbacks do. Each callback is implemented in `PipelineManager` or a thin helper:

- **`on_schedule_reconnect(delay_s)`** — adds an entry to the supervisor thread's priority queue at `now + delay_s`. The supervisor wakes at the scheduled time, calls `on_rebuild()` for the role, dispatches `RECOVERY_SUCCEEDED` or `RECOVERY_FAILED` back to the state machine.
- **`on_swap_to_fallback()`** — schedules `PipelineManager.swap_to_fallback(role)` via `GLib.idle_add`. The idle callback dispatches `SwapCompleted` after the `set_property` call returns.
- **`on_swap_to_primary()`** — schedules `PipelineManager.swap_to_primary(role)` via `GLib.idle_add`. No return event; the next frame observation generates `FRAME_FLOW_OBSERVED` naturally.
- **`on_rebuild()`** — called on the supervisor thread; runs `CameraPipeline.rebuild()` synchronously, returns True/False.
- **`on_notify_transition(old, new, reason)`** — throttled ntfy (one per distinct transition within a 60 s window, to avoid flapping spam). Also writes a telemetry span.

The supervisor thread owns a min-heap of `(wake_time, role)` tuples. It sleeps until the next wake and processes all due entries. Empty heap blocks on a condition variable that scheduling signals.

## pyudev integration

`agents/studio_compositor/udev_monitor.py` (new file).

```python
import pyudev
from pyudev.glib import MonitorObserver


class UdevCameraMonitor:
    """
    Bridges kernel USB / video4linux events to the per-camera state machine.
    Runs inside the compositor process via pyudev.glib.MonitorObserver.
    """

    def __init__(self, *, pipeline_manager: "PipelineManager") -> None:
        self._pm = pipeline_manager
        self._context = pyudev.Context()
        self._video_monitor = pyudev.Monitor.from_netlink(self._context)
        self._video_monitor.filter_by(subsystem="video4linux")
        self._video_observer = MonitorObserver(self._video_monitor)
        self._video_observer.connect("device-event", self._on_video_event)

        self._usb_monitor = pyudev.Monitor.from_netlink(self._context)
        self._usb_monitor.filter_by(subsystem="usb")
        self._usb_observer = MonitorObserver(self._usb_monitor)
        self._usb_observer.connect("device-event", self._on_usb_event)

    def start(self) -> None:
        self._video_monitor.start()
        self._usb_monitor.start()

    def _on_video_event(self, observer, device: pyudev.Device) -> None:
        action = device.action
        dev_node = device.device_node
        if not dev_node:
            return
        role = self._pm.role_for_device_node(dev_node)
        if role is None:
            return
        if action == "add":
            self._pm.on_udev_device_added(role, dev_node)
        elif action == "remove":
            self._pm.on_udev_device_removed(role, dev_node)

    def _on_usb_event(self, observer, device: pyudev.Device) -> None:
        if device.action != "remove":
            return
        vid = device.get("ID_VENDOR_ID")
        pid = device.get("ID_PRODUCT_ID")
        if vid == "046d" and pid in ("085e", "08e5"):
            serial = device.get("ID_SERIAL_SHORT")
            role = self._pm.role_for_serial(serial) if serial else None
            if role:
                self._pm.on_udev_device_removed(role, f"usb serial {serial}")
```

`pyudev.glib.MonitorObserver` is the native GLib integration — it runs on the GLib main loop and emits signals without spawning its own thread. The observer's `device-event` signal fires on the main loop thread, so dispatching events into the state machine is free of cross-thread concerns. The state machine is thread-safe via its internal lock.

## Udev rule for system-level reconfiguration

`systemd/udev/70-studio-cameras.rules` (extended from Phase 1's autosuspend-only version):

```udev
# Phase 1: disable USB autosuspend for studio cameras.
ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="046d", ATTR{idProduct}=="085e", ATTR{power/control}="on"
ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="046d", ATTR{idProduct}=="08e5", ATTR{power/control}="on"

# Phase 3: on add of a video4linux device node backed by a studio camera,
# re-run the v4l2-ctl reconfiguration via a systemd template unit.
ACTION=="add", SUBSYSTEM=="video4linux", ENV{ID_V4L_CAPABILITIES}==":capture:", \
    ATTRS{idVendor}=="046d", ATTRS{idProduct}=="085e", \
    TAG+="systemd", \
    ENV{SYSTEMD_USER_WANTS}="studio-camera-reconfigure@%k.service"

ACTION=="add", SUBSYSTEM=="video4linux", ENV{ID_V4L_CAPABILITIES}==":capture:", \
    ATTRS{idVendor}=="046d", ATTRS{idProduct}=="08e5", \
    TAG+="systemd", \
    ENV{SYSTEMD_USER_WANTS}="studio-camera-reconfigure@%k.service"
```

- `ENV{ID_V4L_CAPABILITIES}==":capture:"` filters to capture-capable nodes (each BRIO creates multiple `/dev/videoN` nodes; only the capture one matters).
- `TAG+="systemd"` tells systemd this udev event maps to a `.device` unit.
- `ENV{SYSTEMD_USER_WANTS}="studio-camera-reconfigure@%k.service"` — kernel device name (e.g., `video0`) is templated into the unit name (`studio-camera-reconfigure@video0.service`).

### Template unit

`systemd/units/studio-camera-reconfigure@.service` (new). Uses `%h` (systemd unit specifier for the user's home directory) and `%i` (instance name from the template); no literal path prefixes.

```ini
[Unit]
Description=Reconfigure studio camera %i after USB re-enumeration
BindsTo=dev-%i.device
After=dev-%i.device

[Service]
Type=oneshot
ExecStart=%h/projects/hapax-council/systemd/units/studio-camera-reconfigure.sh %i
```

`%h` resolves to the invoking user's home directory; `%i` is the template instance.

`studio-camera-reconfigure.sh` (new, in `systemd/units/`):

```bash
#!/usr/bin/env bash
# Reconfigure a studio camera device after USB re-enumeration.
# Argument: kernel device name (e.g., "video0")
set -euo pipefail

DEV="/dev/$1"
if [[ ! -e "$DEV" ]]; then
    logger -t studio-camera-reconfigure "device $DEV does not exist; aborting"
    exit 0
fi

CARD=$(v4l2-ctl --device "$DEV" --info 2>/dev/null | awk -F: '/Card type/ {print $2}' | xargs)

case "$CARD" in
    *BRIO*)
        v4l2-ctl --device "$DEV" \
            --set-ctrl=brightness=128 \
            --set-ctrl=contrast=128 \
            --set-ctrl=saturation=128 \
            --set-ctrl=gain=80 \
            --set-ctrl=sharpness=128 \
            --set-ctrl=focus_automatic_continuous=0 \
            --set-ctrl=focus_absolute=0 \
            >> "$XDG_RUNTIME_DIR/studio-camera-reconfigure.log" 2>&1
        ;;
    *C920*)
        v4l2-ctl --device "$DEV" \
            --set-ctrl=gain=140 \
            --set-ctrl=sharpness=110 \
            --set-ctrl=focus_automatic_continuous=0 \
            >> "$XDG_RUNTIME_DIR/studio-camera-reconfigure.log" 2>&1
        ;;
    *)
        logger -t studio-camera-reconfigure "unknown card: $CARD"
        exit 0
        ;;
esac

logger -t studio-camera-reconfigure "reconfigured $DEV ($CARD)"
```

The compositor's pyudev monitor sees the `add` event shortly after the systemd template unit's `ExecStart` runs (udev dispatches events in parallel; the script is fast enough that the pyudev event arrives after or roughly concurrent with the v4l2-ctl calls). The pyudev handler then dispatches `DeviceAdded` to the state machine, which transitions to RECOVERING and triggers `on_rebuild()` on the supervisor thread. The supervisor thread's rebuild opens the device node with v4l2 settings already applied.

If the systemd unit races behind the pyudev handler (unlikely but possible), the camera reaches PLAYING without v4l2-ctl settings applied. Next `RecoveryFailed` → exponential backoff → next `BackoffElapsed` → next rebuild attempt, by which time the unit has finished. Eventual consistency.

## Thread safety

Threads that may dispatch events:

- **GLib main loop thread** — pyudev MonitorObserver signals, bus watch handlers, GLib idle callbacks scheduled from elsewhere.
- **Supervisor thread** — `BackoffElapsed`, `RecoverySucceeded`, `RecoveryFailed`.
- **Producer streaming thread (×6)** — pad probe on interpipesink emits `FrameFlowObserved` and (via a timer) `FrameFlowStale`.
- **Operator command path** (UDS or CLI) — `OperatorRearm`, `OperatorForceReconnect`.

All dispatch via `CameraStateMachine.dispatch(event)` which takes the internal lock. Callback execution is always scheduled (not run synchronously with the lock held). Rebuild is executed on the supervisor thread, not inside a state transition.

## Edge cases

1. **`DeviceRemoved` while in RECOVERING.** The recovery attempt is still in flight. The state machine transitions immediately to OFFLINE. When the supervisor thread completes, it dispatches `RecoverySucceeded`/`RecoveryFailed`. The state machine's `_transition` for either from OFFLINE returns None (ignored). The OFFLINE backoff restarts from the scheduling at entry to OFFLINE.
2. **`DeviceAdded` while in RECOVERING.** Already recovering; dispatch returns None (ignored).
3. **`DeviceAdded` while in HEALTHY.** Already healthy; dispatch returns None.
4. **Rapid watchdog fires on a healthy camera.** First fire: HEALTHY → DEGRADED → schedule swap. Second fire before swap completes: DEGRADED stays DEGRADED. Swap completes: DEGRADED → OFFLINE.
5. **Clock skew / monotonic drift.** All timestamps use `time.monotonic()`, immune to system clock adjustments. Backoff delays are measured against `time.monotonic()` in the supervisor thread.
6. **Operator rearm while not in DEAD.** Dispatch returns None. Log as "ignored: not in DEAD state."
7. **`RetryBudgetExhausted` while in RECOVERING.** Transition to DEAD. High-priority ntfy. Structured telemetry event. The slot stays on fallback indefinitely until operator rearm.
8. **`OperatorForceReconnect` while in DEAD.** Dispatch returns None (force-reconnect is not valid from DEAD). Operator must `OperatorRearm` first.

## Observability

Every transition produces:

- Structured log line: `camera state: role=brio_operator HEALTHY→DEGRADED reason='watchdog fired' failures=0`
- Prometheus metric bump: `studio_camera_transitions_total{role, from, to}` counter
- Telemetry span via `shared.telemetry.hapax_event`: `{role, from, to, reason, failures, source}`
- Throttled ntfy notification per (role, to_state) tuple within a 60 s window
- `studio_camera_state{role, state}` gauge: 1 for new state, 0 for old state

The state machine also exposes `state` as a property for the Prometheus exporter's 1 s poll.

## Operator CLI

`scripts/studio-camera-ctl` (new, optional — deferrable to Phase 6).

```
studio-camera-ctl status                # print all camera states
studio-camera-ctl rearm <role>          # DEAD → OFFLINE
studio-camera-ctl reconnect <role>      # force immediate reconnect
studio-camera-ctl swap <role> fallback  # manual swap to fallback
studio-camera-ctl swap <role> primary   # manual swap to primary
```

Talks to the compositor over a new UDS at `$XDG_RUNTIME_DIR/studio-compositor.sock`. This socket is only for camera-state commands; it does not overlap with delta's eventual `$XDG_RUNTIME_DIR/hapax-compositor.sock` for Layout mutations (different socket, different command surface).

## Test strategy

Unit tests (pure Python, fast, no GStreamer):

```python
def test_healthy_stays_on_frame_flow():
    sm = make_sm()
    sm.dispatch(Event(EventKind.FRAME_FLOW_OBSERVED))
    assert sm.state == CameraState.HEALTHY

def test_watchdog_fires_transitions_to_degraded():
    sm = make_sm()
    sm.dispatch(Event(EventKind.WATCHDOG_FIRED, reason="timeout"))
    assert sm.state == CameraState.DEGRADED

def test_swap_completes_to_offline():
    sm = make_sm(start=CameraState.DEGRADED)
    sm.dispatch(Event(EventKind.SWAP_COMPLETED))
    assert sm.state == CameraState.OFFLINE

def test_backoff_exponent():
    sm = make_sm(start=CameraState.OFFLINE)
    assert sm._compute_backoff() == 1.0  # n=0
    sm._consecutive_failures = 3
    assert sm._compute_backoff() == 8.0
    sm._consecutive_failures = 9
    assert sm._compute_backoff() == 60.0  # ceiling

def test_retry_budget_exhaustion():
    sm = make_sm(start=CameraState.RECOVERING)
    for i in range(10):
        sm._consecutive_failures = i
        sm.dispatch(Event(EventKind.RECOVERY_FAILED))
        if i < 9:
            assert sm.state == CameraState.OFFLINE
    assert sm.state == CameraState.DEAD

def test_operator_rearm_from_dead():
    sm = make_sm(start=CameraState.DEAD)
    sm.dispatch(Event(EventKind.OPERATOR_REARM))
    assert sm.state == CameraState.OFFLINE
    assert sm.consecutive_failures == 0

def test_device_added_resets_backoff():
    sm = make_sm(start=CameraState.OFFLINE, consecutive_failures=5)
    sm.dispatch(Event(EventKind.DEVICE_ADDED))
    assert sm.state == CameraState.RECOVERING
    assert sm.consecutive_failures == 0

def test_operator_force_reconnect_ignored_from_dead():
    sm = make_sm(start=CameraState.DEAD)
    sm.dispatch(Event(EventKind.OPERATOR_FORCE_RECONNECT))
    assert sm.state == CameraState.DEAD

def test_concurrent_dispatch_no_drift():
    sm = make_sm()
    import threading
    def worker():
        for _ in range(1000):
            sm.dispatch(Event(EventKind.FRAME_FLOW_OBSERVED))
    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert sm.state == CameraState.HEALTHY
```

Integration tests (manual, gated `@pytest.mark.camera`):

- Real USB disconnect via cable pull — observe the full transition chain HEALTHY → DEGRADED → OFFLINE → (RECOVERING ⇄ OFFLINE)* → HEALTHY or DEAD depending on duration.
- `USBDEVFS_RESET` simulation via `scripts/studio-simulate-usb-disconnect.sh` — same observation in software-only form.
- Fake device-add event via a test pyudev monitor — verify the state machine receives `DeviceAdded` and transitions.

## Acceptance criteria

- CameraStateMachine implemented as pure Python, fully unit-tested without GStreamer.
- UdevCameraMonitor subscribes to `video4linux` and `usb` subsystems and dispatches events.
- `70-studio-cameras.rules` extended with add-triggered reconfiguration.
- `studio-camera-reconfigure@.service` template unit installed and working.
- Physically unplug/replug on a real camera transitions HEALTHY → DEGRADED → OFFLINE → RECOVERING → HEALTHY with log output at each step.
- 10 consecutive failed recoveries escalate to DEAD with a high-priority ntfy.
- Operator rearm from DEAD (via CLI or test fixture) restores auto-recovery.
- Existing tests continue to pass.

## Risks

1. **udev `TAG+="systemd"` pattern does not reliably trigger user-scope services on Arch.** Mitigation: the primary recovery path is the pyudev-in-compositor handler; the systemd template unit is a belt-and-suspenders path for v4l2-ctl reapplication. If the trigger is unreliable, recovery still works (settings just aren't re-applied until the next reconfigure). Acceptable.
2. **pyudev thread safety with GLib main loop.** Mitigation: `pyudev.glib.MonitorObserver` is designed for GLib; emits signals on the main loop thread.
3. **Exponential backoff interacts with clustered transient hub stalls.** Mitigation: `DeviceAdded` resets the counter on physical re-plug.
4. **State machine race under concurrent dispatch.** Mitigation: internal RLock; all transitions and side-effect scheduling are atomic. Unit test covers.
5. **Prometheus state gauge write conflicts.** Mitigation: `prometheus_client` is internally thread-safe.

## Open questions

1. **Should `DEAD` be bounded by a maximum time?** E.g., after 1 hour, automatically rearm. Design says no — operator-only exit. Reconsider if operators miss dead cameras.
2. **Should `DEGRADED` have a timeout?** If `SwapCompleted` never arrives (supervisor dead), the state machine stays DEGRADED. Safety timeout of 5 s is easy to add but adds complexity.
3. **Should rapid watchdog fires be deduplicated at dispatch?** They are idempotent but wasteful. Low priority.

## References

### Internal

- `docs/superpowers/plans/2026-04-12-camera-247-resilience-epic.md`
- `docs/superpowers/specs/2026-04-12-compositor-hot-swap-architecture-design.md` (Phase 2)
- `agents/studio_compositor/state.py` — current `try_reconnect_camera` (replaced in Phase 3)

### External

- [pyudev.glib API docs](https://pyudev.readthedocs.io/en/latest/api/pyudev.glib.html)
- [systemd.device(5)](https://www.freedesktop.org/software/systemd/man/latest/systemd.device.html)
- [systemd user-scope WANTS pattern](https://www.linux.com/training-tutorials/systemd-services-reacting-change/)
- [Python threading.RLock](https://docs.python.org/3/library/threading.html#rlock-objects)
