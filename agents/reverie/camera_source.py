"""Camera source writer — publishes camera frames to the content source protocol.

Reads JPEG frames from the compositor's shm output, converts to RGBA,
and writes to /dev/shm/hapax-imagination/sources/camera-{name}/.
The Reverie ContentSourceManager picks them up for compositing.

Run as a coroutine inside the Reverie daemon tick loop.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("reverie.camera_source")

COMPOSITOR_DIR = Path("/dev/shm/hapax-compositor")
SOURCES_DIR = Path("/dev/shm/hapax-imagination/sources")

# Camera names to publish (subset of available cameras)
CAMERA_SOURCES = {
    "c920-overhead": {"z_order": 5, "opacity": 0.4, "tags": ["perception", "spatial"]},
    "c920-desk": {"z_order": 6, "opacity": 0.3, "tags": ["perception", "operator"]},
    "brio-operator": {"z_order": 7, "opacity": 0.3, "tags": ["perception", "operator"]},
}


def update_camera_sources() -> int:
    """Update camera source directories from compositor JPEG frames.

    Returns number of sources updated. Call from Reverie daemon tick.
    """
    updated = 0
    for cam_name, config in CAMERA_SOURCES.items():
        jpeg_path = COMPOSITOR_DIR / f"{cam_name}.jpg"
        if not jpeg_path.exists():
            continue

        source_id = f"camera-{cam_name}"
        source_dir = SOURCES_DIR / source_id
        source_dir.mkdir(parents=True, exist_ok=True)

        # Check if JPEG is newer than our last write
        manifest_path = source_dir / "manifest.json"
        if manifest_path.exists():
            try:
                jpeg_mtime = jpeg_path.stat().st_mtime
                manifest_mtime = manifest_path.stat().st_mtime
                if jpeg_mtime <= manifest_mtime:
                    continue  # no new frame
            except OSError:
                pass

        # Convert JPEG to RGBA
        try:
            from PIL import Image

            img = Image.open(jpeg_path).convert("RGBA")
            rgba_data = img.tobytes("raw", "RGBA")
            width, height = img.width, img.height
        except Exception:
            log.debug("Failed to convert %s", jpeg_path, exc_info=True)
            continue

        # Write frame
        tmp_frame = source_dir / "frame.tmp"
        tmp_frame.write_bytes(rgba_data)
        tmp_frame.rename(source_dir / "frame.rgba")

        # Write manifest
        manifest = {
            "source_id": source_id,
            "content_type": "rgba",
            "width": width,
            "height": height,
            "opacity": config["opacity"],
            "layer": 1,
            "blend_mode": "screen",
            "z_order": config["z_order"],
            "ttl_ms": 0,
            "tags": config["tags"],
        }

        tmp = source_dir / "manifest.tmp"
        tmp.write_text(json.dumps(manifest))
        tmp.rename(manifest_path)
        updated += 1

    return updated
