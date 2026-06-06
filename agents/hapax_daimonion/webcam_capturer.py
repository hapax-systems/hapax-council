"""Webcam frame capture via ffmpeg V4L2."""

from __future__ import annotations

import base64
import logging
import os
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from agents.hapax_daimonion.screen_models import CameraConfig

log = logging.getLogger(__name__)

SCREWM_IR_BRIO_RESERVATION_MARKERS = {
    "/dev/v4l/by-id/usb-046d_Logitech_BRIO_5342C819-video-index0": (
        Path("/dev/shm/hapax-compositor/quake-live-ir-brio-operator.raw.json"),
        Path("/dev/shm/hapax-compositor/quake-live-ir-brio-operator.json"),
    ),
    "/dev/v4l/by-id/usb-046d_Logitech_BRIO_43B0576A-video-index0": (
        Path("/dev/shm/hapax-compositor/quake-live-ir-brio-room.raw.json"),
        Path("/dev/shm/hapax-compositor/quake-live-ir-brio-room.json"),
    ),
    "/dev/v4l/by-id/usb-046d_Logitech_BRIO_9726C031-video-index0": (
        Path("/dev/shm/hapax-compositor/quake-live-ir-brio-synths.raw.json"),
        Path("/dev/shm/hapax-compositor/quake-live-ir-brio-synths.json"),
    ),
}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"", "0", "false", "no", "off"}


class WebcamCapturer:
    """Captures frames from one or more webcams by role.

    Uses ffmpeg to grab a single frame from a V4L2 device. Each role
    (operator, hardware, ir) has independent cooldown tracking.
    """

    def __init__(
        self,
        cameras: list[CameraConfig] | None = None,
        cooldown_s: float = 5.0,
        *,
        respect_screwm_ir_reservations: bool | None = None,
        screwm_ir_reservation_markers: Mapping[str, Sequence[Path | str]] | None = None,
    ) -> None:
        self._cameras: dict[str, CameraConfig] = {}
        for cam in cameras or []:
            self._cameras[cam.role] = cam
        self._cooldown_s = cooldown_s
        self._last_capture_time: dict[str, float] = {role: 0.0 for role in self._cameras}
        self._respect_screwm_ir_reservations = (
            _env_bool("HAPAX_DAIMONION_RESPECT_SCREWM_IR_BRIO_RESERVATIONS", True)
            if respect_screwm_ir_reservations is None
            else respect_screwm_ir_reservations
        )
        markers = (
            SCREWM_IR_BRIO_RESERVATION_MARKERS
            if screwm_ir_reservation_markers is None
            else screwm_ir_reservation_markers
        )
        self._screwm_ir_reservation_markers = {
            device: tuple(Path(marker) for marker in device_markers)
            for device, device_markers in markers.items()
        }

    def has_camera(self, role: str) -> bool:
        """Check whether a camera with the given role is configured."""
        return role in self._cameras

    def reset_cooldown(self, role: str) -> None:
        """Reset cooldown for a specific camera role."""
        self._last_capture_time[role] = 0.0

    def capture(self, role: str) -> str | None:
        """Capture a frame from the camera with the given role.

        Returns base64-encoded JPEG, or None on failure/cooldown.
        """
        cam = self._cameras.get(role)
        if cam is None:
            return None

        now = time.monotonic()
        if (now - self._last_capture_time.get(role, 0.0)) < self._cooldown_s:
            return None

        if not Path(cam.device).exists():
            log.debug("Camera device not found: %s (%s)", cam.device, role)
            return None

        if self._is_reserved_for_screwm_ir(cam):
            return None

        try:
            result = self._do_capture(cam)
            if result is not None:
                self._last_capture_time[role] = time.monotonic()
            return result
        except Exception as exc:
            log.warning("Webcam capture failed for %s: %s", role, exc)
            return None

    def _is_reserved_for_screwm_ir(self, cam: CameraConfig) -> bool:
        """Return true when Screwm IR owns the matching local BRIO sensor."""
        if not self._respect_screwm_ir_reservations:
            return False

        markers = self._markers_for_device(cam.device)
        if not markers:
            return False

        active_marker = next((marker for marker in markers if marker.exists()), None)
        if active_marker is None:
            return False

        log.debug(
            "Skipping webcam capture for %s: %s reserved by Screwm IR marker %s",
            cam.role,
            cam.device,
            active_marker,
        )
        return True

    def _markers_for_device(self, device: str) -> tuple[Path, ...] | None:
        return self._screwm_ir_reservation_markers.get(device)

    def _do_capture(self, cam: CameraConfig) -> str | None:
        """Execute ffmpeg capture and return base64-encoded image."""
        tmpdir = tempfile.mkdtemp(prefix="webcam-")
        outpath = os.path.join(tmpdir, "frame.jpg")

        try:
            cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "v4l2",
                "-input_format",
                cam.input_format,
                "-video_size",
                f"{cam.width}x{cam.height}",
            ]
            if cam.pixel_format:
                cmd.extend(["-pix_fmt", cam.pixel_format])
            cmd.extend(
                [
                    "-i",
                    cam.device,
                    "-frames:v",
                    "1",
                    "-update",
                    "1",
                    outpath,
                ]
            )

            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=10,
            )

            if proc.returncode != 0:
                log.debug(
                    "ffmpeg failed for %s: %s",
                    cam.role,
                    proc.stderr[-200:] if proc.stderr else "",
                )
                return None

            path = Path(outpath)
            if not path.exists():
                log.debug("No output file from ffmpeg for %s", cam.role)
                return None

            image_data = path.read_bytes()
            return base64.b64encode(image_data).decode("ascii")
        finally:
            import shutil

            shutil.rmtree(tmpdir, ignore_errors=True)
