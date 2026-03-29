"""Webcam frame capture via ffmpeg V4L2."""

from __future__ import annotations

import base64
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path

from agents.hapax_daimonion.screen_models import CameraConfig

log = logging.getLogger(__name__)


class WebcamCapturer:
    """Captures frames from one or more webcams by role.

    Uses ffmpeg to grab a single frame from a V4L2 device. Each role
    (operator, hardware, ir) has independent cooldown tracking.
    """

    def __init__(
        self,
        cameras: list[CameraConfig] | None = None,
        cooldown_s: float = 5.0,
    ) -> None:
        self._cameras: dict[str, CameraConfig] = {}
        for cam in cameras or []:
            self._cameras[cam.role] = cam
        self._cooldown_s = cooldown_s
        self._last_capture_time: dict[str, float] = {role: 0.0 for role in self._cameras}

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

        try:
            result = self._do_capture(cam)
            if result is not None:
                self._last_capture_time[role] = time.monotonic()
            return result
        except Exception as exc:
            log.warning("Webcam capture failed for %s: %s", role, exc)
            return None

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
