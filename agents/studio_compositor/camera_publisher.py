"""Continuous camera JPEG→RGBA publisher for the 3D scene graph.

Reads camera JPEG snapshots from /dev/shm/hapax-compositor/*.jpg and
publishes them as RGBA sources to /dev/shm/hapax-imagination/sources/camera-*/
at a configurable cadence.

This replaces the recruitment-gated approach in reverie's
ContentCapabilityRouter — all cameras are published continuously so
the 3D SceneRenderer always has texture data for every camera quad.

Privacy invariant: frames pass through face-obscure before publishing.

3D mode: When HAPAX_3D_COMPOSITOR=1, reads directly from the frame_cache
(NV12 pad probe data) instead of JPEG snapshots, since the composite
pipeline (which writes the JPEGs) is not running.
"""

from __future__ import annotations

import json
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


def _default_interval_s() -> float:
    """Return camera source-publisher cadence.

    The 3D scene reads these RGBA sources as visible tiles. A 10 Hz bridge
    made live cameras look stale; the incident baseline is full 30 Hz unless
    an operator/resource policy explicitly lowers it.
    """

    raw_interval = os.environ.get("HAPAX_CAMERA_SOURCE_PUBLISH_INTERVAL_S")
    if raw_interval is not None:
        try:
            return max(0.001, float(raw_interval))
        except ValueError:
            log.warning(
                "Invalid HAPAX_CAMERA_SOURCE_PUBLISH_INTERVAL_S=%r; using 30 Hz",
                raw_interval,
            )
    raw_fps = os.environ.get("HAPAX_CAMERA_SOURCE_PUBLISH_FPS", "30")
    try:
        fps = float(raw_fps)
    except ValueError:
        log.warning("Invalid HAPAX_CAMERA_SOURCE_PUBLISH_FPS=%r; using 30", raw_fps)
        fps = 30.0
    return 1.0 / max(1.0, fps)


_DEFAULT_INTERVAL_S = _default_interval_s()

# z_order=5 = OnScrim depth in the 3D scene
_Z_ORDER = 5


def _is_3d_mode() -> bool:
    return os.environ.get("HAPAX_3D_COMPOSITOR") == "1"


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
        self._mtimes: dict[str, float | int] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._publish_count = 0
        self._error_count = 0
        self._3d_mode = _is_3d_mode()

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
        mode = "3D/frame_cache" if self._3d_mode else "JPEG/snapshot"
        log.info(
            "CameraSourcePublisher started: %d cameras, %.1f Hz, mode=%s",
            len(CAMERA_MAP),
            1.0 / self._interval,
            mode,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if self._3d_mode:
                    self._tick_3d()
                else:
                    self._tick()
            except Exception:
                self._error_count += 1
                if self._error_count % 50 == 1:
                    log.exception("CameraSourcePublisher tick error #%d", self._error_count)
            self._stop.wait(self._interval)

    def _tick(self) -> None:
        """Normal mode: read JPEG snapshots from compositor SHM."""
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

            self._publish_camera_jpeg(jpeg_path, source_id, mtime)

    def _tick_3d(self) -> None:
        """3D mode: read NV12 frames from frame_cache, convert to RGBA."""
        try:
            from . import frame_cache
        except ImportError:
            return

        for snapshot_name, source_id in CAMERA_MAP.items():
            # Map snapshot_name to camera role (they match)
            role = snapshot_name
            cached = frame_cache.get(role)
            if cached is None:
                continue

            # The byte-object id can be reused by CPython after the prior frame
            # drops out of scope, so use the explicit frame-cache sequence.
            cache_id = cached.sequence
            if self._mtimes.get(source_id) == cache_id:
                continue

            self._publish_camera_nv12(cached, source_id, cache_id)

    def _publish_camera_jpeg(self, jpeg_path: Path, source_id: str, mtime: float) -> None:
        try:
            import numpy as np
            from PIL import Image

            img = Image.open(jpeg_path)
            img = img.convert("RGBA")
            w, h = img.size
            rgba_bytes = np.array(img, dtype=np.uint8).tobytes()

            self._write_source(source_id, rgba_bytes, w, h)
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

    def _publish_camera_nv12(
        self, cached: frame_cache.CachedFrame, source_id: str, cache_id: int
    ) -> None:
        try:
            w, h = cached.width, cached.height
            data = cached.data

            # NV12 → RGBA conversion. Prefer OpenCV's native implementation;
            # the old all-NumPy path was correct but serialized the 3D source
            # publisher down to roughly 1-3 Hz per camera under the full rig.
            # NV12: Y plane (w*h) + UV interleaved plane (w*h/2)
            y_size = w * h
            uv_size = w * h // 2

            if len(data) < y_size + uv_size:
                return

            rgba = self._nv12_to_rgba(data, w, h)
            rgba_bytes = rgba.tobytes()

            self._write_source(
                source_id,
                rgba_bytes,
                w,
                h,
                frame_sequence=cache_id,
            )
            self._mtimes[source_id] = cache_id
            self._publish_count += 1

            if self._publish_count % 100 == 0:
                log.info(
                    "CameraSourcePublisher (3D): %d frames published (%d errors)",
                    self._publish_count,
                    self._error_count,
                )

        except Exception:
            self._error_count += 1
            if self._error_count % 20 == 1:
                log.exception("Failed to publish camera %s (3D/NV12)", source_id)

    @staticmethod
    def _nv12_to_rgba(data: bytes, w: int, h: int) -> np.ndarray:
        import numpy as np

        try:
            import cv2

            nv12 = np.frombuffer(data, dtype=np.uint8, count=w * h * 3 // 2).reshape(h * 3 // 2, w)
            return cv2.cvtColor(nv12, cv2.COLOR_YUV2RGBA_NV12)
        except Exception:
            y_size = w * h
            uv_size = w * h // 2
            y = np.frombuffer(data, dtype=np.uint8, count=y_size).reshape(h, w).astype(np.float32)
            uv = np.frombuffer(data, dtype=np.uint8, offset=y_size, count=uv_size).reshape(
                h // 2, w
            )

            # Upsample UV to full resolution
            u = uv[:, 0::2].astype(np.float32)
            v = uv[:, 1::2].astype(np.float32)
            u = np.repeat(np.repeat(u, 2, axis=0), 2, axis=1)[:h, :w]
            v = np.repeat(np.repeat(v, 2, axis=0), 2, axis=1)[:h, :w]

            # YUV→RGB (BT.601)
            r = np.clip(y + 1.402 * (v - 128), 0, 255).astype(np.uint8)
            g = np.clip(y - 0.344136 * (u - 128) - 0.714136 * (v - 128), 0, 255).astype(np.uint8)
            b = np.clip(y + 1.772 * (u - 128), 0, 255).astype(np.uint8)
            a = np.full_like(r, 255)

            return np.stack([r, g, b, a], axis=-1)

    def _write_source(
        self,
        source_id: str,
        rgba_bytes: bytes,
        w: int,
        h: int,
        *,
        frame_sequence: int | None = None,
    ) -> None:
        source_dir = self._sources_dir / source_id
        source_dir.mkdir(parents=True, exist_ok=True)

        frame_path = source_dir / "frame.rgba"
        tmp_frame_path = source_dir / "frame.rgba.tmp"
        tmp_frame_path.write_bytes(rgba_bytes)
        tmp_frame_path.replace(frame_path)

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
            "frame_sequence": frame_sequence,
            "published_at_monotonic": time.monotonic(),
        }
        manifest_path = source_dir / "manifest.json"
        tmp_manifest_path = source_dir / "manifest.json.tmp"
        tmp_manifest_path.write_text(json.dumps(manifest))
        tmp_manifest_path.replace(manifest_path)
