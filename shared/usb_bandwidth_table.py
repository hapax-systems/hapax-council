"""USB device bandwidth lookup table.

Static profile of bandwidth requirements (in Mbps) for known studio USB
devices on this host. Used by ``scripts/hapax-usb-bandwidth-preflight``
to estimate per-controller utilisation without parsing debugfs (which
requires root and the ``debugfs`` mount, and which the research drop
flagged as out-of-scope for the first pass — see
``/tmp/usb-hardening-research-2026-05-02.md`` §3.4).

Numbers are conservative high-speed isochronous reservations as actually
observed on this workstation, sourced from §3.2 of the research drop and
the live device list in ``config/audio-topology.yaml``. They are NOT
theoretical maximums — a BRIO at 1080p YUYV would burn ~370 Mbps, but
the studio runs all 6 cameras at 720p MJPEG (per the studio camera
inventory memory ``project_720p_commitment``) so the published value
reflects the committed configuration.

When the preflight encounters a ``(vid, pid)`` tuple not in this table,
it falls back to ``DEFAULT_UNKNOWN_MBPS`` and tags the device as
``unknown``. That falls cleanly out of the saturation calculation but
makes the operator aware that a static-table miss happened, which is
the cue to add a new row here.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class UsbDeviceProfile(BaseModel):
    """Static bandwidth profile for a single USB device.

    Bandwidth values are conservative high-speed isochronous reservations
    in megabits per second. ``device_class`` is freeform — used only for
    operator-facing output.
    """

    vid: str = Field(description="USB vendor ID, lowercase hex without 0x")
    pid: str = Field(description="USB product ID, lowercase hex without 0x")
    name: str = Field(description="Operator-facing device label")
    device_class: str = Field(description="UAC2 / UVC / HID / etc.")
    bandwidth_mbps: float = Field(
        description="Conservative high-speed isochronous reservation",
        gt=0,
    )
    notes: str = Field(default="", description="Operator-facing context note")

    @property
    def key(self) -> tuple[str, str]:
        return (self.vid.lower(), self.pid.lower())


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# When we cannot identify a device from the static table, assume a small
# but non-zero footprint so it shows up in the headroom calculation.
# Tuned conservatively: a generic HID is well under 1 Mbps, a generic
# audio class device starts at ~3 Mbps. 2 is a defensible mid-point that
# does not over-attribute saturation pressure to unknown peripherals.
DEFAULT_UNKNOWN_MBPS: float = 2.0


# Bus capacities. xHCI advertises these per the USB-IF spec; the values
# below are **raw** signal rates. The 80% USB-IF reservation rule for
# isochronous transfers is applied at headroom-computation time, not in
# this table.
USB_2_0_HIGH_SPEED_MBPS: float = 480.0
USB_3_0_SUPERSPEED_MBPS: float = 5_000.0
USB_3_1_SUPERSPEED_PLUS_MBPS: float = 10_000.0
USB_3_2_SUPERSPEED_PLUS_2X_MBPS: float = 20_000.0


# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------

# Keyed (vid, pid). Both fields lowercase hex without ``0x``.
# Order is documentation: kept grouped by device family for human readability.
_PROFILES: tuple[UsbDeviceProfile, ...] = (
    # --- Logitech webcams -------------------------------------------------
    UsbDeviceProfile(
        vid="046d",
        pid="085e",
        name="Logitech BRIO 4K",
        device_class="UVC video",
        bandwidth_mbps=15.0,
        notes="MJPEG 720p30 — studio commitment per project_720p_commitment",
    ),
    UsbDeviceProfile(
        vid="046d",
        pid="08e5",
        name="Logitech C920 PRO HD",
        device_class="UVC video",
        bandwidth_mbps=10.0,
        notes="MJPEG 720p30 in studio configuration",
    ),
    UsbDeviceProfile(
        vid="046d",
        pid="082d",
        name="Logitech C920",
        device_class="UVC video",
        bandwidth_mbps=10.0,
        notes="MJPEG 720p30 in studio configuration",
    ),
    UsbDeviceProfile(
        vid="046d",
        pid="086d",
        name="Logitech C920e",
        device_class="UVC video",
        bandwidth_mbps=10.0,
        notes="MJPEG 720p30 in studio configuration",
    ),
    # --- USB audio interfaces --------------------------------------------
    UsbDeviceProfile(
        vid="b58e",
        pid="9e84",
        name="Blue Yeti microphone",
        device_class="UAC2 audio (2ch in / 2ch out)",
        bandwidth_mbps=3.0,
        notes="48 kHz / 16-bit isochronous",
    ),
    UsbDeviceProfile(
        vid="1686",
        pid="03d5",
        name="ZOOM LiveTrak L-12",
        device_class="UAC2 audio (14ch in / 4ch out)",
        bandwidth_mbps=12.0,
        notes="48 kHz / 16-bit; 14-channel multitrack — needs dedicated chain",
    ),
    UsbDeviceProfile(
        vid="1fc9",
        pid="0104",
        name="Torso Electronics S-4",
        device_class="UAC2 audio + MIDI (10ch I/O)",
        bandwidth_mbps=8.0,
        notes="48 kHz / 24-bit multichannel",
    ),
    UsbDeviceProfile(
        vid="16c0",
        pid="048a",
        name="Dirtywave M8",
        device_class="UAC1 audio + USB serial",
        bandwidth_mbps=3.0,
        notes="44.1 kHz / 16-bit + serial",
    ),
    UsbDeviceProfile(
        vid="2886",
        pid="001a",
        name="ReSpeaker XVF3800 USB 4-Mic Array",
        device_class="UAC2 audio (4ch in / 2ch out) + vendor control",
        bandwidth_mbps=10.0,
        notes="48 kHz multichannel capture plus stereo AEC reference; Seeed firmware",
    ),
    UsbDeviceProfile(
        vid="20b1",
        pid="4f00",
        name="XMOS XVF3800 Voice Processor",
        device_class="UAC2 audio (4ch in / 2ch out) + vendor control",
        bandwidth_mbps=10.0,
        notes="48 kHz XMOS reference firmware",
    ),
    UsbDeviceProfile(
        vid="20b1",
        pid="4f01",
        name="XMOS XVF3800 Voice Processor",
        device_class="UAC2 audio (4ch in / 2ch out) + vendor control",
        bandwidth_mbps=10.0,
        notes="16 kHz XMOS reference firmware",
    ),
    # --- MIDI-only devices ------------------------------------------------
    UsbDeviceProfile(
        vid="381a",
        pid="1003",
        name="Erica Synths MIDI Dispatch",
        device_class="USB-MIDI",
        bandwidth_mbps=0.5,
        notes="MIDI bulk traffic only",
    ),
    # --- Bluetooth / radio ------------------------------------------------
    UsbDeviceProfile(
        vid="13d3",
        pid="3602",
        name="MediaTek MT7921 Bluetooth",
        device_class="Bluetooth radio",
        bandwidth_mbps=1.0,
        notes="HCI bulk + audio profile A2DP at peak",
    ),
)


_PROFILES_BY_KEY: dict[tuple[str, str], UsbDeviceProfile] = {
    profile.key: profile for profile in _PROFILES
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def lookup(vid: str, pid: str) -> UsbDeviceProfile | None:
    """Return the static profile for ``(vid, pid)`` or None if unknown."""

    return _PROFILES_BY_KEY.get((vid.lower(), pid.lower()))


def synthesise_unknown(vid: str, pid: str) -> UsbDeviceProfile:
    """Return a generic profile for an unknown device id pair.

    The synthesised profile uses ``DEFAULT_UNKNOWN_MBPS`` and labels the
    device as ``unknown`` so the preflight output makes the gap visible.
    """

    return UsbDeviceProfile(
        vid=vid.lower(),
        pid=pid.lower(),
        name=f"unknown ({vid}:{pid})",
        device_class="unknown",
        bandwidth_mbps=DEFAULT_UNKNOWN_MBPS,
        notes="No static profile — using default estimate",
    )


def all_profiles() -> tuple[UsbDeviceProfile, ...]:
    """Return every known device profile in declaration order."""

    return _PROFILES


def capacity_for_speed(speed_mbps: float) -> float:
    """Map a sysfs ``speed`` value to its nominal bus capacity.

    The kernel reports per-device negotiated speed in Mbps via
    ``/sys/bus/usb/devices/<dev>/speed``. xHCI bandwidth budgets are
    per-bus, where the bus capacity is the highest speed the controller
    advertises. We translate the per-device speed back to the bus capacity
    by snapping to the next standard rate.
    """

    if speed_mbps >= USB_3_2_SUPERSPEED_PLUS_2X_MBPS:
        return USB_3_2_SUPERSPEED_PLUS_2X_MBPS
    if speed_mbps >= USB_3_1_SUPERSPEED_PLUS_MBPS:
        return USB_3_1_SUPERSPEED_PLUS_MBPS
    if speed_mbps >= USB_3_0_SUPERSPEED_MBPS:
        return USB_3_0_SUPERSPEED_MBPS
    return USB_2_0_HIGH_SPEED_MBPS


__all__ = [
    "DEFAULT_UNKNOWN_MBPS",
    "USB_2_0_HIGH_SPEED_MBPS",
    "USB_3_0_SUPERSPEED_MBPS",
    "USB_3_1_SUPERSPEED_PLUS_MBPS",
    "USB_3_2_SUPERSPEED_PLUS_2X_MBPS",
    "UsbDeviceProfile",
    "all_profiles",
    "capacity_for_speed",
    "lookup",
    "synthesise_unknown",
]
