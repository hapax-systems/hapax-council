"""pyudev.glib bridge — routes kernel USB/video4linux events into the
CameraStateMachine via PipelineManager.

Phase 3 of the camera 24/7 resilience epic.

See docs/superpowers/specs/2026-04-12-camera-recovery-state-machine-design.md
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .pipeline_manager import PipelineManager


class UdevCameraMonitor:
    """Subscribes to video4linux + usb subsystems and dispatches events to
    the pipeline manager. Runs inside the compositor process via the GLib
    main loop thread (no dedicated worker thread — pyudev.glib integrates
    natively with GLib)."""

    def __init__(self, *, pipeline_manager: PipelineManager) -> None:
        self._pm = pipeline_manager
        self._started = False
        self._video_monitor: Any = None
        self._usb_monitor: Any = None
        self._video_observer: Any = None
        self._usb_observer: Any = None

    def start(self) -> bool:
        """Start monitoring. Safe no-op if pyudev is unavailable."""
        if self._started:
            return True
        try:
            import pyudev
            from pyudev.glib import MonitorObserver
        except ImportError:
            log.warning("pyudev not available — udev camera monitor disabled")
            return False

        try:
            context = pyudev.Context()

            self._video_monitor = pyudev.Monitor.from_netlink(context)
            self._video_monitor.filter_by(subsystem="video4linux")
            self._video_observer = MonitorObserver(self._video_monitor)
            self._video_observer.connect("device-event", self._on_video_event)
            self._video_monitor.start()

            self._usb_monitor = pyudev.Monitor.from_netlink(context)
            self._usb_monitor.filter_by(subsystem="usb")
            self._usb_observer = MonitorObserver(self._usb_monitor)
            self._usb_observer.connect("device-event", self._on_usb_event)
            self._usb_monitor.start()

            self._started = True
            log.info("udev camera monitor started (video4linux + usb subsystems)")
            return True
        except Exception:
            log.exception("udev camera monitor start failed")
            return False

    def stop(self) -> None:
        """Stop monitoring. pyudev Monitor has no explicit close — we drop
        references and the GLib MainContext stops dispatching."""
        self._video_monitor = None
        self._usb_monitor = None
        self._video_observer = None
        self._usb_observer = None
        self._started = False

    def _on_video_event(self, _observer: Any, device: Any) -> None:
        """Handle a video4linux add/remove event."""
        try:
            action = device.action
            dev_node = device.device_node
            if not dev_node:
                return
            role = self._pm.role_for_device_node(dev_node)
            if role is None:
                return
            if action == "add":
                log.info("udev video add: role=%s node=%s", role, dev_node)
                self._pm.on_device_added(role, dev_node)
            elif action == "remove":
                log.info("udev video remove: role=%s node=%s", role, dev_node)
                self._pm.on_device_removed(role, dev_node)
        except Exception:
            log.exception("udev video event handler raised")

    def _on_usb_event(self, _observer: Any, device: Any) -> None:
        """Handle a USB remove event for known camera VID/PIDs. Video4linux
        add/remove events are the primary trigger; the USB subsystem is a
        secondary signal for bus-level disconnects where the video4linux
        event may lag or not fire."""
        try:
            if device.action != "remove":
                return
            vid = device.get("ID_VENDOR_ID")
            pid = device.get("ID_PRODUCT_ID")
            if vid != "046d":
                return
            if pid not in ("085e", "08e5"):
                return
            serial = device.get("ID_SERIAL_SHORT")
            if not serial:
                return
            role = self._pm.role_for_serial(serial)
            if role is None:
                return
            log.info("udev usb remove: role=%s vid=%s pid=%s serial=%s", role, vid, pid, serial)
            self._pm.on_device_removed(role, f"usb:{vid}:{pid}:{serial}")
        except Exception:
            log.exception("udev usb event handler raised")
