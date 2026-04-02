"""Content capability handlers — recruited representations for the visual surface.

Each handler writes content to /dev/shm/hapax-imagination/sources/ using
the ContentSourceManager protocol. Only called when the AffordancePipeline
recruits the corresponding affordance.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("reverie.content")

DEFAULT_SOURCES = Path("/dev/shm/hapax-imagination/sources")
DEFAULT_COMPOSITOR = Path("/dev/shm/hapax-compositor")

CAMERA_MAP: dict[str, str] = {
    "content.overhead_perspective": "c920-overhead",
    "content.desk_perspective": "c920-desk",
    "content.operator_perspective": "brio-operator",
}


class ContentCapabilityRouter:
    """Routes recruited content affordances to concrete handlers."""

    def __init__(
        self,
        sources_dir: Path = DEFAULT_SOURCES,
        compositor_dir: Path = DEFAULT_COMPOSITOR,
    ) -> None:
        self._sources = sources_dir
        self._compositor = compositor_dir

    def camera_for_affordance(self, affordance_name: str) -> str | None:
        """Return the compositor camera name for a perception affordance, or None."""
        return CAMERA_MAP.get(affordance_name)

    def activate_camera(self, affordance_name: str, level: float) -> bool:
        """Capture a camera frame and write it to the sources protocol.

        Returns True if frame was written, False if camera unavailable.
        """
        cam_name = self.camera_for_affordance(affordance_name)
        if cam_name is None:
            return False

        jpeg_path = self._compositor / f"{cam_name}.jpg"
        if not jpeg_path.exists():
            return False

        source_id = f"camera-{cam_name}"
        source_dir = self._sources / source_id
        source_dir.mkdir(parents=True, exist_ok=True)

        manifest_path = source_dir / "manifest.json"
        if manifest_path.exists():
            try:
                if jpeg_path.stat().st_mtime <= manifest_path.stat().st_mtime:
                    return True
            except OSError:
                pass

        try:
            from PIL import Image

            img = Image.open(jpeg_path).convert("RGBA")
            rgba_data = img.tobytes("raw", "RGBA")
            width, height = img.width, img.height
        except Exception:
            log.debug("Failed to convert %s", jpeg_path, exc_info=True)
            return False

        tmp_frame = source_dir / "frame.tmp"
        tmp_frame.write_bytes(rgba_data)
        tmp_frame.rename(source_dir / "frame.rgba")

        manifest = {
            "source_id": source_id,
            "content_type": "rgba",
            "width": width,
            "height": height,
            "opacity": level,
            "layer": 1,
            "blend_mode": "screen",
            "z_order": 5,
            "ttl_ms": 3000,
            "tags": ["perception", "recruited"],
        }
        tmp = source_dir / "manifest.tmp"
        tmp.write_text(json.dumps(manifest))
        tmp.rename(manifest_path)
        return True

    def activate_content(self, affordance_name: str, narrative: str, level: float) -> bool:
        """Activate a slow content capability (text, knowledge query).

        Returns True if activation was dispatched. Resolution is asynchronous.
        """
        log.info(
            "Content recruitment: %s at %.2f (narrative: %s)",
            affordance_name,
            level,
            narrative[:50],
        )
        return False
