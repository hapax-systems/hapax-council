"""Device state perception backend — USB, Bluetooth, network device monitoring.

EVENT tier: USB devices are monitored via pyudev kernel netlink events.
Bluetooth BLE scanning runs every 30s. Network ARP table polled every 30s.

All CPU-only, zero VRAM.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time

from agents.hapax_daimonion.perception import PerceptionTier
from agents.hapax_daimonion.primitives import Behavior

log = logging.getLogger(__name__)

_BLE_SCAN_INTERVAL = 30.0
_NET_SCAN_INTERVAL = 30.0


class _DeviceCache:
    """Thread-safe cache for device state."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._usb_devices: str = ""
        self._bluetooth_nearby: str = ""
        self._network_devices: str = ""
        self._updated_at: float = 0.0

    def update(
        self,
        *,
        usb_devices: str | None = None,
        bluetooth_nearby: str | None = None,
        network_devices: str | None = None,
    ) -> None:
        with self._lock:
            if usb_devices is not None:
                self._usb_devices = usb_devices
            if bluetooth_nearby is not None:
                self._bluetooth_nearby = bluetooth_nearby
            if network_devices is not None:
                self._network_devices = network_devices
            self._updated_at = time.monotonic()

    def read(self) -> dict:
        with self._lock:
            return {
                "usb_devices": self._usb_devices,
                "bluetooth_nearby": self._bluetooth_nearby,
                "network_devices": self._network_devices,
                "updated_at": self._updated_at,
            }


def _scan_usb_devices() -> str:
    """Get current USB device summary via pyudev."""
    try:
        import pyudev

        ctx = pyudev.Context()
        devices: list[str] = []
        for dev in ctx.list_devices(subsystem="usb", DEVTYPE="usb_device"):
            vendor = dev.get("ID_VENDOR_FROM_DATABASE", dev.get("ID_VENDOR", ""))
            model = dev.get("ID_MODEL_FROM_DATABASE", dev.get("ID_MODEL", ""))
            if vendor or model:
                devices.append(f"{vendor} {model}".strip())
        return ", ".join(sorted(set(devices)))
    except Exception as exc:
        log.debug("USB scan failed: %s", exc)
        return ""


def _scan_ble_devices() -> str:
    """Scan for nearby BLE devices via bleak."""
    try:
        import asyncio

        from bleak import BleakScanner

        async def _scan() -> list[str]:
            devices = await BleakScanner.discover(timeout=5.0)
            names: list[str] = []
            for d in devices:
                name = d.name or d.address
                names.append(name)
            return names

        # Run in a new event loop since we're on a background thread
        loop = asyncio.new_event_loop()
        try:
            names = loop.run_until_complete(_scan())
        finally:
            loop.close()

        return ", ".join(sorted(set(names)))
    except Exception as exc:
        log.debug("BLE scan failed: %s", exc)
        return ""


def _scan_network_devices() -> str:
    """Get network neighbors via ARP table."""
    try:
        result = subprocess.run(
            ["ip", "neigh", "show"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            return ""
        devices: list[str] = []
        for line in result.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 1 and parts[0] not in ("", "Incomplete"):
                ip = parts[0]
                state = parts[-1] if parts else ""
                if state in ("REACHABLE", "STALE", "DELAY"):
                    devices.append(ip)
        return ", ".join(sorted(devices))
    except Exception as exc:
        log.debug("Network scan failed: %s", exc)
        return ""


class DeviceStateBackend:
    """PerceptionBackend providing USB, Bluetooth, and network device state.

    Provides:
      - usb_devices: str (comma-separated USB device names)
      - bluetooth_nearby: str (comma-separated BLE device names)
      - network_devices: str (comma-separated IP addresses from ARP)
    """

    def __init__(self) -> None:
        self._cache = _DeviceCache()
        self._threads: list[threading.Thread] = []
        self._stop_event = threading.Event()

        self._b_usb: Behavior[str] = Behavior("")
        self._b_bluetooth: Behavior[str] = Behavior("")
        self._b_network: Behavior[str] = Behavior("")

    @property
    def name(self) -> str:
        return "device_state"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"usb_devices", "bluetooth_nearby", "network_devices"})

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.EVENT

    def available(self) -> bool:
        try:
            import pyudev  # noqa: F401

            return True
        except ImportError:
            return False

    def start(self) -> None:
        self._stop_event.clear()

        # USB monitor thread (event-driven via pyudev)
        usb_thread = threading.Thread(
            target=self._usb_monitor_loop,
            name="device-usb-monitor",
            daemon=True,
        )
        usb_thread.start()
        self._threads.append(usb_thread)

        # BLE + network scanner thread (periodic)
        scan_thread = threading.Thread(
            target=self._scan_loop,
            name="device-scan",
            daemon=True,
        )
        scan_thread.start()
        self._threads.append(scan_thread)

        log.info("Device state backend started")

    def stop(self) -> None:
        self._stop_event.set()
        for t in self._threads:
            t.join(timeout=10.0)
        self._threads.clear()
        log.info("Device state backend stopped")

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        now = time.monotonic()
        cached = self._cache.read()

        self._b_usb.update(cached["usb_devices"], now)
        self._b_bluetooth.update(cached["bluetooth_nearby"], now)
        self._b_network.update(cached["network_devices"], now)

        behaviors["usb_devices"] = self._b_usb
        behaviors["bluetooth_nearby"] = self._b_bluetooth
        behaviors["network_devices"] = self._b_network

    def _usb_monitor_loop(self) -> None:
        """Monitor USB device events via pyudev netlink."""
        try:
            import pyudev

            ctx = pyudev.Context()
            monitor = pyudev.Monitor.from_netlink(ctx)
            monitor.filter_by(subsystem="usb", device_type="usb_device")
            monitor.start()

            # Initial scan
            self._cache.update(usb_devices=_scan_usb_devices())

            while not self._stop_event.is_set():
                # Poll with timeout so we can check stop_event
                device = monitor.poll(timeout=2.0)
                if device is not None:
                    log.debug("USB event: %s %s", device.action, device.get("ID_MODEL", ""))
                    self._cache.update(usb_devices=_scan_usb_devices())
        except Exception:
            log.exception("USB monitor loop failed")

    def _scan_loop(self) -> None:
        """Periodic BLE + network scanning."""
        while not self._stop_event.is_set():
            # BLE scanning disabled — bleak's D-Bus usage destabilizes
            # dbus-broker, causing Chrome and other D-Bus clients to crash.
            # Re-enable when bleak/dbus-broker compatibility improves.
            # try:
            #     ble = _scan_ble_devices()
            #     self._cache.update(bluetooth_nearby=ble)
            # except Exception:
            #     log.debug("BLE scan failed", exc_info=True)

            try:
                net = _scan_network_devices()
                self._cache.update(network_devices=net)
            except Exception:
                log.debug("Network scan failed", exc_info=True)

            self._stop_event.wait(_BLE_SCAN_INTERVAL)
