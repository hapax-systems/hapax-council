"""Raw HID input backend — physical keyboard/mouse via evdev.

Bypasses systemd-logind which is polluted by virtual input devices
(RustDesk UInput, mouce-library-fake-mouse). Reads directly from
physical device nodes, filtered by name.

Provides:
  - real_keyboard_active: bool (physical keystroke within 5s)
  - real_idle_seconds: float (seconds since last physical input)
"""

from __future__ import annotations

import logging
import select
import threading
import time

import evdev

from agents.hapax_daimonion.perception import PerceptionTier
from agents.hapax_daimonion.primitives import Behavior

log = logging.getLogger(__name__)
_ACTIVE_THRESHOLD_S = 5.0

_VIRTUAL_DEVICE_PATTERNS = ["UInput", "virtual", "fake-mouse", "ydotoold"]
_PHYSICAL_DEVICE_PATTERNS = ["Keychron", "Logitech USB Receiver", "Logitech MX"]


def _is_physical_input(device_name: str) -> bool:
    """Return True if the device name matches a known physical input device."""
    name_lower = device_name.lower()
    for pattern in _VIRTUAL_DEVICE_PATTERNS:
        if pattern.lower() in name_lower:
            return False
    return any(pattern.lower() in name_lower for pattern in _PHYSICAL_DEVICE_PATTERNS)


def _compute_idle(last_event_ts: float, now: float) -> tuple[bool, float]:
    """Return (active, idle_seconds) based on time since last event."""
    idle_s = now - last_event_ts
    active = idle_s < _ACTIVE_THRESHOLD_S
    return active, round(idle_s, 1)


class EvdevInputBackend:
    """Perception backend reading physical keyboard/mouse via evdev."""

    _WARMUP_S: float = 10.0

    def __init__(self) -> None:
        self._last_event_ts: float = 0.0
        self._start_ts: float = 0.0
        self._events_received: int = 0
        self._disabled: bool = False
        self._b_active: Behavior[bool] = Behavior(False)
        self._b_idle: Behavior[float] = Behavior(9999.0)
        self._devices: list[evdev.InputDevice] = []
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def name(self) -> str:
        return "evdev_input"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"real_keyboard_active", "real_idle_seconds"})

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.FAST

    def available(self) -> bool:
        """Check if any physical input devices are accessible."""
        try:
            devices = [evdev.InputDevice(p) for p in evdev.list_devices()]
            return any(_is_physical_input(d.name) for d in devices)
        except Exception:
            return False

    def start(self) -> None:
        """Open physical devices and start the monitor thread."""
        try:
            all_devices = [evdev.InputDevice(p) for p in evdev.list_devices()]
            self._devices = [d for d in all_devices if _is_physical_input(d.name)]
            if not self._devices:
                log.warning("EvdevInputBackend: no physical devices found")
                return
            log.info(
                "EvdevInputBackend started: %s",
                ", ".join(f"{d.name} ({d.path})" for d in self._devices),
            )
            self._stop_event.clear()
            self._start_ts = time.monotonic()
            self._thread = threading.Thread(
                target=self._monitor_loop, daemon=True, name="evdev-input"
            )
            self._thread.start()
        except Exception:
            log.warning("EvdevInputBackend: failed to start", exc_info=True)

    def stop(self) -> None:
        """Stop the monitor thread and close devices."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        for d in self._devices:
            try:
                d.close()
            except Exception:
                pass
        self._devices = []
        log.info("EvdevInputBackend stopped")

    def contribute(self, behaviors: dict[str, Behavior]) -> None:  # type: ignore[type-arg]
        """Write real_keyboard_active and real_idle_seconds into behaviors dict.

        During warmup (first 10s) or when disabled (no events ever received
        on KWin Wayland), do NOT write behaviors — let the logind-based
        InputActivityBackend handle keyboard detection instead.
        """
        if self._disabled:
            return

        now = time.monotonic()
        elapsed = now - self._start_ts if self._start_ts > 0 else 0.0

        if elapsed < self._WARMUP_S:
            return

        if self._events_received == 0:
            log.warning(
                "EvdevInputBackend: zero events after %.0fs warmup — "
                "disabling (KWin Wayland holds exclusive libinput access). "
                "Falling through to logind InputActivityBackend.",
                elapsed,
            )
            self._disabled = True
            return

        active, idle_s = _compute_idle(self._last_event_ts, now)
        self._b_active.update(active, now)
        self._b_idle.update(idle_s, now)
        behaviors["real_keyboard_active"] = self._b_active
        behaviors["real_idle_seconds"] = self._b_idle

    def _monitor_loop(self) -> None:
        """Poll physical devices for input events, update last-event timestamp."""
        fds = {d.fd: d for d in self._devices}
        while not self._stop_event.is_set():
            try:
                r, _, _ = select.select(list(fds.keys()), [], [], 0.5)
                for fd in r:
                    device = fds.get(fd)
                    if device is None:
                        continue
                    for _event in device.read():
                        self._last_event_ts = time.monotonic()
                        self._events_received += 1
            except Exception:
                if self._stop_event.is_set():
                    break
                time.sleep(0.5)
