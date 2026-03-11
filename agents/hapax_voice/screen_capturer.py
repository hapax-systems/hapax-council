"""Screen capture via grim with downscaling."""
from __future__ import annotations

import base64
import logging
import subprocess
import tempfile
import time
from pathlib import Path

log = logging.getLogger(__name__)

DOWNSCALE_RESOLUTION = "1280x720"


class ScreenCapturer:
    """Captures the screen, downscales, and returns base64-encoded PNG.

    Uses grim for capture, ImageMagick for downscaling.
    Ephemeral: temp files are deleted after encoding.
    Fail-open: returns None on any failure.
    """

    def __init__(self, cooldown_s: float = 10.0) -> None:
        self.cooldown_s = cooldown_s
        self._last_capture_time: float = 0.0

    def reset_cooldown(self) -> None:
        """Reset the capture cooldown, allowing an immediate capture."""
        self._last_capture_time = 0.0

    def capture(self) -> str | None:
        """Capture screen and return base64 PNG, or None on failure/cooldown."""
        now = time.monotonic()
        if (now - self._last_capture_time) < self.cooldown_s:
            log.debug("Capture cooldown active, skipping")
            return None

        try:
            return self._do_capture()
        except Exception as exc:
            log.warning("Screen capture failed: %s", exc)
            return None
        finally:
            self._last_capture_time = time.monotonic()

    def _do_capture(self) -> str | None:
        """Execute the capture pipeline."""
        with tempfile.TemporaryDirectory(prefix="hapax-screen-") as tmpdir:
            raw_path = Path(tmpdir) / "capture.png"
            scaled_path = Path(tmpdir) / "scaled.png"

            # Capture with grim
            result = subprocess.run(
                ["grim", str(raw_path)],
                capture_output=True,
                timeout=10,
            )
            if result.returncode != 0:
                log.warning("grim failed (rc=%d)", result.returncode)
                return None

            if not raw_path.exists():
                log.warning("No screenshot file found after capture")
                return None

            # Downscale with ImageMagick
            subprocess.run(
                ["convert", str(raw_path), "-resize", DOWNSCALE_RESOLUTION, str(scaled_path)],
                capture_output=True,
                timeout=10,
            )

            # Use scaled if available, fall back to raw
            read_path = scaled_path if scaled_path.exists() else raw_path
            image_data = read_path.read_bytes()
            return base64.b64encode(image_data).decode("ascii")
