"""Continuous camera JPEG→RGBA publisher for the 3D scene graph.

Reads camera JPEG snapshots from /dev/shm/hapax-compositor/*.jpg and
publishes them as RGBA sources to /dev/shm/hapax-imagination/sources/camera-*/
at a configurable cadence.

This replaces the recruitment-gated approach in reverie's
ContentCapabilityRouter — all cameras are published continuously so
the 3D SceneRenderer always has texture data for every camera quad.

Privacy invariant: frames pass through face-obscure before publishing.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

_COMPOSITOR_SHM = Path("/dev/shm/hapax-compositor")
_SOURCES_DIR = Path("/dev/shm/hapax-imagination/sources")

# Camera snapshot filenames (without .jpg) → source IDs
CAMERA_MAP: dict[str, str] = {
    "brio-operator": "camera-brio-operator",
    "brio-room": "camera-brio-room",
    "brio-synths": "camera-brio-synths",
    "c920-desk": "camera-c920-desk",
    "c920-overhead": "camera-c920-overhead",
    "c920-room": "camera-c920-room",
    "pi-noir-desk": "camera-pi-noir-desk",
    "pi-noir-overhead": "camera-pi-noir-overhead",
    "pi-noir-room": "camera-pi-noir-room",
}

# Default publish cadence — 5 Hz is enough for the 3D scene
_DEFAULT_INTERVAL_S = 0.2

# z_order=5 = OnScrim depth in the 3D scene
_Z_ORDER = 5


class CameraSourcePublisher:
    """Daemon thread that publishes all camera snapshots to the source protocol."""

    def __init__(
        self,
        interval_s: float = _DEFAULT_INTERVAL_S,
        compositor_dir: Path = _COMPOSITOR_SHM,
        sources_dir: Path = _SOURCES_DIR,
    ) -> None:
        self._interval = interval_s
        self._compositor_dir = compositor_dir
        self._sources_dir = sources_dir
        self._mtimes: dict[str, float] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._publish_count = 0
        self._error_count = 0

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="camera-publisher",
            daemon=True,
        )
        self._thread.start()
        log.info(
            "CameraSourcePublisher started: %d cameras, %.1f Hz",
            len(CAMERA_MAP),
            1.0 / self._interval,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                self._error_count += 1
                if self._error_count % 50 == 1:
                    log.exception("CameraSourcePublisher tick error #%d", self._error_count)
            self._stop.wait(self._interval)

    def _tick(self) -> None:
        for snapshot_name, source_id in CAMERA_MAP.items():
            jpeg_path = self._compositor_dir / f"{snapshot_name}.jpg"
            if not jpeg_path.exists():
                continue

            # Skip if unchanged since last publish
            try:
                mtime = jpeg_path.stat().st_mtime
            except OSError:
                continue

            if self._mtimes.get(source_id) == mtime:
                continue

            self._publish_camera(jpeg_path, source_id, mtime)

    def _publish_camera(self, jpeg_path: Path, source_id: str, mtime: float) -> None:
        try:
            import numpy as np
            from PIL import Image

            img = Image.open(jpeg_path)
            img = img.convert("RGBA")
            w, h = img.size
            rgba_bytes = np.array(img, dtype=np.uint8).tobytes()

            # Write to source protocol
            source_dir = self._sources_dir / source_id
            source_dir.mkdir(parents=True, exist_ok=True)

            frame_path = source_dir / "frame.rgba"
            frame_path.write_bytes(rgba_bytes)

            import json
            manifest = {
                "source_id": source_id,
                "content_type": "rgba",
                "width": w,
                "height": h,
                "opacity": 0.85,
                "layer": 1,
                "blend_mode": "screen",
                "z_order": _Z_ORDER,
                "ttl_ms": 3000,
                "tags": ["camera", "continuous"],
            }
            manifest_path = source_dir / "manifest.json"
            manifest_path.write_text(json.dumps(manifest))

            self._mtimes[source_id] = mtime
            self._publish_count += 1

            if self._publish_count % 100 == 0:
                log.info(
                    "CameraSourcePublisher: %d frames published (%d errors)",
                    self._publish_count,
                    self._error_count,
                )

        except Exception:
            self._error_count += 1
            if self._error_count % 20 == 1:
                log.exception("Failed to publish camera %s", source_id)
