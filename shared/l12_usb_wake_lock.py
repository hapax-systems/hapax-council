"""L-12 USB wake-lock witness — prevents and detects USB auto-suspend.

Reads the L-12's sysfs power policy and ALSA capture status to detect:
- runtime power policy set to 'auto' (must be 'on')
- autosuspend_delay_ms not -1 (must be -1 / disabled)
- ALSA capture stream in XRUN or suspended state
- device missing from /proc/asound/cards entirely

The witness is intentionally read-only — it does not write to sysfs.
Recovery is owned by udev rules and the operator.

Cc-task: audio-egress-integrity-l12-wake-lock-20260521
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# L-12 USB identifiers
L12_USB_VENDOR_ID = "1686"
L12_USB_PRODUCT_ID = "03d5"
L12_USB_SERIAL_PREFIX = "8253"

USB_DEVICES_ROOT = Path("/sys/bus/usb/devices")
PROC_ASOUND = Path("/proc/asound")

L12_ALSA_CARD_RE = re.compile(r"^\s*(\d+)\s+\[.*?(?:Zoom|L-12|ZOOM|L12)", re.IGNORECASE)


class WakeLockStatus(StrEnum):
    """Overall wake-lock health."""

    LOCKED = "locked"  # power/control=on, autosuspend=-1, capture active
    UNLOCKED = "unlocked"  # power/control=auto or autosuspend not -1
    SUSPENDED = "suspended"  # ALSA capture in XRUN or suspended state
    MISSING = "missing"  # L-12 not found in sysfs or ALSA


class CaptureStreamState(StrEnum):
    RUNNING = "running"
    PREPARED = "prepared"
    SETUP = "setup"
    XRUN = "xrun"
    SUSPENDED = "suspended"
    CLOSED = "closed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class UsbPowerState:
    """Snapshot of a USB device's sysfs power attributes."""

    sysfs_path: str | None = None
    power_control: str | None = None  # "on" or "auto"
    autosuspend_delay_ms: int | None = None  # -1 = disabled
    runtime_status: str | None = None  # "active", "suspended", "unsupported"


@dataclass(frozen=True)
class AlsaCaptureState:
    """Snapshot of ALSA capture stream state for one card."""

    card_number: int | None = None
    hw_params_present: bool = False
    stream_state: CaptureStreamState = CaptureStreamState.UNKNOWN
    sample_rate: int | None = None
    xrun_count: int = 0


@dataclass(frozen=True)
class L12WakeLockReport:
    """Full wake-lock witness report."""

    status: WakeLockStatus
    checked_at: str
    usb_power: UsbPowerState
    alsa_capture: AlsaCaptureState
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "checked_at": self.checked_at,
            "usb_power": {
                "sysfs_path": self.usb_power.sysfs_path,
                "power_control": self.usb_power.power_control,
                "autosuspend_delay_ms": self.usb_power.autosuspend_delay_ms,
                "runtime_status": self.usb_power.runtime_status,
            },
            "alsa_capture": {
                "card_number": self.alsa_capture.card_number,
                "hw_params_present": self.alsa_capture.hw_params_present,
                "stream_state": self.alsa_capture.stream_state.value,
                "sample_rate": self.alsa_capture.sample_rate,
                "xrun_count": self.alsa_capture.xrun_count,
            },
            "reasons": self.reasons,
        }


def _read_sysfs(path: Path) -> str | None:
    """Read a single sysfs attribute file, stripping whitespace."""
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, PermissionError):
        return None


def _find_l12_usb_device(*, usb_root: Path = USB_DEVICES_ROOT) -> Path | None:
    """Find the L-12's sysfs device directory by vendor/product ID."""
    if not usb_root.is_dir():
        return None
    try:
        for dev_dir in usb_root.iterdir():
            if not dev_dir.is_dir():
                continue
            vendor = _read_sysfs(dev_dir / "idVendor")
            product = _read_sysfs(dev_dir / "idProduct")
            if vendor == L12_USB_VENDOR_ID and product == L12_USB_PRODUCT_ID:
                return dev_dir
    except OSError:
        pass
    return None


def read_usb_power_state(*, usb_root: Path = USB_DEVICES_ROOT) -> UsbPowerState:
    """Read the L-12's USB power policy from sysfs."""
    dev_dir = _find_l12_usb_device(usb_root=usb_root)
    if dev_dir is None:
        return UsbPowerState()

    power_dir = dev_dir / "power"
    power_control = _read_sysfs(power_dir / "control")
    autosuspend_raw = _read_sysfs(power_dir / "autosuspend_delay_ms")
    runtime_status = _read_sysfs(power_dir / "runtime_status")

    autosuspend_ms: int | None = None
    if autosuspend_raw is not None:
        try:
            autosuspend_ms = int(autosuspend_raw)
        except ValueError:
            pass

    return UsbPowerState(
        sysfs_path=str(dev_dir),
        power_control=power_control,
        autosuspend_delay_ms=autosuspend_ms,
        runtime_status=runtime_status,
    )


def _detect_l12_card_number(*, proc_asound: Path = PROC_ASOUND) -> int | None:
    """Find the L-12's ALSA card number from /proc/asound/cards."""
    cards_file = proc_asound / "cards"
    try:
        text = cards_file.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        m = L12_ALSA_CARD_RE.search(line)
        if m:
            return int(m.group(1))
    return None


def _parse_capture_state(status_text: str) -> CaptureStreamState:
    """Parse ALSA capture stream state from /proc/asound/cardN/pcm0c/sub0/status."""
    for line in status_text.splitlines():
        line_lower = line.strip().lower()
        if line_lower.startswith("state:"):
            raw_state = line_lower.split(":", 1)[1].strip()
            try:
                return CaptureStreamState(raw_state.upper())
            except ValueError:
                # Try case-insensitive match
                for member in CaptureStreamState:
                    if member.value.lower() == raw_state.lower():
                        return member
                return CaptureStreamState.UNKNOWN
    return CaptureStreamState.UNKNOWN


def _parse_sample_rate(hw_params_text: str) -> int | None:
    """Extract sample rate from /proc/asound/cardN/pcm0c/sub0/hw_params."""
    for line in hw_params_text.splitlines():
        if line.strip().startswith("rate:"):
            parts = line.split(":", 1)[1].strip().split()
            if parts:
                try:
                    return int(parts[0])
                except ValueError:
                    pass
    return None


def _parse_xrun_count(status_text: str) -> int:
    """Extract xrun count from ALSA status."""
    for line in status_text.splitlines():
        if "xrun" in line.lower():
            m = re.search(r"(\d+)", line)
            if m:
                return int(m.group(1))
    return 0


def read_alsa_capture_state(
    *,
    proc_asound: Path = PROC_ASOUND,
) -> AlsaCaptureState:
    """Read ALSA capture state for the L-12."""
    card = _detect_l12_card_number(proc_asound=proc_asound)
    if card is None:
        return AlsaCaptureState()

    card_dir = proc_asound / f"card{card}"
    hw_params_path = card_dir / "pcm0c" / "sub0" / "hw_params"
    status_path = card_dir / "pcm0c" / "sub0" / "status"

    hw_params_present = False
    sample_rate: int | None = None
    try:
        hw_text = hw_params_path.read_text(encoding="utf-8")
        hw_params_present = hw_text.strip() != "closed" and bool(hw_text.strip())
        if hw_params_present:
            sample_rate = _parse_sample_rate(hw_text)
    except OSError:
        pass

    stream_state = CaptureStreamState.UNKNOWN
    xrun_count = 0
    try:
        status_text = status_path.read_text(encoding="utf-8")
        stream_state = _parse_capture_state(status_text)
        xrun_count = _parse_xrun_count(status_text)
    except OSError:
        pass

    return AlsaCaptureState(
        card_number=card,
        hw_params_present=hw_params_present,
        stream_state=stream_state,
        sample_rate=sample_rate,
        xrun_count=xrun_count,
    )


def check_l12_wake_lock(
    *,
    usb_root: Path = USB_DEVICES_ROOT,
    proc_asound: Path = PROC_ASOUND,
) -> L12WakeLockReport:
    """Full wake-lock witness check.

    Returns a report with status:
    - LOCKED: power/control=on, autosuspend=-1, capture healthy
    - UNLOCKED: power policy allows auto-suspend
    - SUSPENDED: ALSA capture in XRUN or suspended state
    - MISSING: device not found
    """
    checked_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    usb_power = read_usb_power_state(usb_root=usb_root)
    alsa_capture = read_alsa_capture_state(proc_asound=proc_asound)

    reasons: list[str] = []

    # Device missing?
    if usb_power.sysfs_path is None and alsa_capture.card_number is None:
        return L12WakeLockReport(
            status=WakeLockStatus.MISSING,
            checked_at=checked_at,
            usb_power=usb_power,
            alsa_capture=alsa_capture,
            reasons=["L-12 not found in sysfs or ALSA"],
        )

    # Check USB power policy
    if usb_power.power_control == "auto":
        reasons.append(f"power/control is 'auto' (must be 'on') at {usb_power.sysfs_path}")

    if usb_power.autosuspend_delay_ms is not None and usb_power.autosuspend_delay_ms >= 0:
        reasons.append(f"autosuspend_delay_ms is {usb_power.autosuspend_delay_ms} (must be -1)")

    if usb_power.runtime_status == "suspended":
        reasons.append("USB runtime_status is 'suspended'")

    # Check ALSA capture state
    if alsa_capture.stream_state == CaptureStreamState.XRUN:
        reasons.append("ALSA capture is in XRUN state")

    if alsa_capture.stream_state == CaptureStreamState.SUSPENDED:
        reasons.append("ALSA capture stream is SUSPENDED")

    # Determine overall status
    if usb_power.runtime_status == "suspended" or alsa_capture.stream_state in (
        CaptureStreamState.XRUN,
        CaptureStreamState.SUSPENDED,
    ):
        status = WakeLockStatus.SUSPENDED
    elif reasons:
        status = WakeLockStatus.UNLOCKED
    else:
        status = WakeLockStatus.LOCKED

    return L12WakeLockReport(
        status=status,
        checked_at=checked_at,
        usb_power=usb_power,
        alsa_capture=alsa_capture,
        reasons=reasons,
    )


__all__ = [
    "AlsaCaptureState",
    "CaptureStreamState",
    "L12WakeLockReport",
    "UsbPowerState",
    "WakeLockStatus",
    "check_l12_wake_lock",
    "read_alsa_capture_state",
    "read_usb_power_state",
]
