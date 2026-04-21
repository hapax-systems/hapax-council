"""Content capability handlers — recruited representations for the visual surface.

Each handler writes content to /dev/shm/hapax-imagination/sources/ using
the ContentSourceManager protocol. Only called when the AffordancePipeline
recruits the corresponding affordance.

**Privacy invariant (2026-04-20 incident):** any camera frame that enters
reverie's content_layer MUST pass through the face-obscure pipeline first.
Reverie is treated with the same anonymity discipline as other HOMAGE-ward
surfaces and the livestream egress tee. Camera frames loaded here are
fail-closed to a full-frame Gruvbox mask on detector failure. An operator
emergency kill switch (``HAPAX_REVERIE_DISABLE_CAMERAS=1``) disables the
camera path entirely so reverie can run without any identified imagery.
"""

from __future__ import annotations

import json
import logging
import os
from collections import deque
from pathlib import Path

log = logging.getLogger("reverie.content")

DEFAULT_SOURCES = Path("/dev/shm/hapax-imagination/sources")
DEFAULT_COMPOSITOR = Path("/dev/shm/hapax-compositor")


def _cameras_disabled() -> bool:
    """Emergency kill switch for camera→reverie. Env = '1' disables entirely."""
    return os.environ.get("HAPAX_REVERIE_DISABLE_CAMERAS", "") == "1"


CAMERA_MAP: dict[str, str] = {
    "content.overhead_perspective": "c920-overhead",
    "content.desk_perspective": "c920-desk",
    "content.operator_perspective": "brio-operator",
    "space.overhead_perspective": "c920-overhead",
    "space.desk_perspective": "c920-desk",
    "space.operator_perspective": "brio-operator",
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
        self._recent_ids: deque[str] = deque(maxlen=10)

    def camera_for_affordance(self, affordance_name: str) -> str | None:
        """Return the compositor camera name for a perception affordance, or None."""
        return CAMERA_MAP.get(affordance_name)

    def activate_camera(self, affordance_name: str, level: float) -> bool:
        """Capture a camera frame and write it to the sources protocol.

        **Privacy invariant**: the frame is run through the face-obscure
        pipeline (agents.studio_compositor.face_obscure_integration) before
        being written into reverie's source directory. The pipeline is
        fail-closed — any detector failure returns a full-frame Gruvbox
        mask, not the raw frame.

        Returns True if frame was written, False if camera unavailable,
        kill-switch active, or obscure pipeline returned a block.
        """
        if _cameras_disabled():
            log.debug("Camera source %s skipped — HAPAX_REVERIE_DISABLE_CAMERAS=1", affordance_name)
            return False

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
            import numpy as np
            from PIL import Image

            from agents.studio_compositor.face_obscure_integration import (
                obscure_frame_for_camera,
            )

            img = Image.open(jpeg_path).convert("RGB")
            # face_obscure_integration expects a BGR uint8 numpy array
            # (V4L2/GStreamer capture convention). Convert PIL RGB → BGR.
            rgb = np.asarray(img, dtype=np.uint8)
            bgr = rgb[:, :, ::-1].copy()
            obscured_bgr = obscure_frame_for_camera(bgr, camera_role=cam_name)
            # Convert back to RGBA for reverie's content_layer protocol.
            obscured_rgb = obscured_bgr[:, :, ::-1]
            alpha = np.full((obscured_rgb.shape[0], obscured_rgb.shape[1], 1), 255, dtype=np.uint8)
            rgba_arr = np.concatenate([obscured_rgb, alpha], axis=2)
            rgba_data = rgba_arr.tobytes()
            width = obscured_rgb.shape[1]
            height = obscured_rgb.shape[0]
        except Exception:
            # Fail-CLOSED: any failure in the obscure pipeline or conversion
            # means we drop the frame entirely rather than leak a raw one.
            # The face_obscure_integration helper itself fails closed to a
            # mask; reaching this outer except means the conversion or
            # import broke, which still must not produce a leak.
            log.exception("Face-obscure pipeline failed for %s — dropping frame", cam_name)
            return False

        tmp_frame = source_dir / "frame.tmp"
        tmp_frame.write_bytes(rgba_data)
        tmp_frame.rename(source_dir / "frame.rgba")

        manifest = {
            "source_id": source_id,
            "content_type": "rgba",
            "width": width,
            "height": height,
            "opacity": level,  # recruitment score IS expression intensity
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

    def activate_youtube(self, slot_id: int, level: float) -> bool:
        """Phase 2 of yt-content-reverie-sierpinski-separation (2026-04-21).

        Mark a YT slot as the featured slot at a scene cut-point. Writes
        ``/dev/shm/hapax-compositor/featured-yt-slot`` (atomic tmp+rename)
        with ``{"slot_id": int, "level": float, "ts": float}``. The studio
        compositor's Sierpinski renderer reads this file each tick and
        elevates the named slot's opacity in the triangular composition.

        Validates ``slot_id`` is a non-negative integer; level is clamped
        into ``[0.0, 1.0]``. Out-of-range or unparseable slot_id is rejected
        with a debug log, not raised, because director recruitment is
        best-effort: a malformed impingement must NOT crash the mixer.

        Returns True iff the file was written; False on validation failure.
        """
        import time as _time

        try:
            slot_int = int(slot_id)
        except (TypeError, ValueError):
            log.debug("activate_youtube: rejecting non-integer slot_id %r", slot_id)
            return False
        if slot_int < 0:
            log.debug("activate_youtube: rejecting negative slot_id %d", slot_int)
            return False
        clamped_level = max(0.0, min(1.0, float(level)))

        target = self._compositor / "featured-yt-slot"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "slot_id": slot_int,
                "level": clamped_level,
                "ts": _time.time(),
            }
            tmp = target.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload))
            tmp.replace(target)
            log.info("YT featured: slot=%d level=%.2f", slot_int, clamped_level)
            return True
        except OSError:
            log.warning("activate_youtube: write to %s failed", target, exc_info=True)
            return False

    def activate_content(self, affordance_name: str, narrative: str, level: float) -> bool:
        """Activate a content capability — dispatches to the appropriate resolver.

        Returns True if content was produced. FAST resolvers run inline;
        SLOW resolvers (Qdrant queries) may take 50-200ms but still run
        synchronously within the mixer tick.
        """
        from agents.reverie._content_resolvers import CONTENT_RESOLVERS

        resolver = CONTENT_RESOLVERS.get(affordance_name)
        if resolver is None:
            log.debug("No resolver for content affordance: %s", affordance_name)
            return False

        try:
            result = resolver(
                narrative, level, sources_dir=self._sources, recent_ids=self._recent_ids
            )
            if result:
                log.info(
                    "Content resolved: %s at %.2f (narrative: %s)",
                    affordance_name,
                    level,
                    narrative[:50],
                )
            return result
        except Exception:
            log.warning("Content resolver failed: %s", affordance_name, exc_info=True)
            return False
