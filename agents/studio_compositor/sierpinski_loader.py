"""Sierpinski content loader — publishes YouTube video frames via the unified source protocol.

Replaces the legacy ContentTextureManager/slots.json path. Polls
``yt-frame-{N}.jpg`` snapshots from the youtube-player daemon and
injects them into the wgpu content source protocol
(``/dev/shm/hapax-imagination/sources/yt-slot-{N}/``) via
``content_injector``.

The Sierpinski triangle shader (``sierpinski_content.wgsl``) handles
the triangle-region masking and compositing on the GPU side. This
loader is the data pipeline.

Active slot opacity is higher (0.9) than inactive slots (0.3). Slot
ordering via ``z_order`` so the active slot sorts highest and the
shader binds it first.

Slot count history: the loader originally spoke three slots
(0, 1, 2) on the assumption of multi-video playback. The
``youtube-player`` daemon ships serving slot 0 only; slots 1+ have
been returning HTTP 400 ``{"error": "invalid slot"}`` on every cold
start since then, and no multi-video workflow ever materialised.
2026-04-23: operator decision to match reality — slot count pulled
to 1. Re-expanding later is a one-number change (``VIDEO_SLOT_COUNT``)
plus aligned changes on the youtube-player side.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

YT_FRAME_DIR = Path("/dev/shm/hapax-compositor")

# Number of video slots the loader manages. 2026-04-23: reduced from
# 3 to 1 to match the live youtube-player configuration. Re-expand by
# bumping this AND updating the player's slot count in parallel.
VIDEO_SLOT_COUNT: int = 1


class VideoSlotStub:
    """Minimal stub matching the fields DirectorLoop reads from video slots."""

    def __init__(self, slot_id: int) -> None:
        self.slot_id = slot_id
        self._title = ""
        self._channel = ""
        self.is_active = False

    def check_finished(self) -> bool:
        """Check if youtube-player reports this slot finished."""
        marker = YT_FRAME_DIR / f"yt-finished-{self.slot_id}"
        if marker.exists():
            marker.unlink(missing_ok=True)
            return True
        return False

    def update_metadata(self) -> None:
        """Fetch title/channel from youtube-player API."""
        try:
            import urllib.request

            resp = urllib.request.urlopen(
                f"http://127.0.0.1:8055/slot/{self.slot_id}/status", timeout=2
            )
            import json as _json

            data = _json.loads(resp.read())
            self._title = data.get("title", "")
            self._channel = data.get("channel", "")
        except Exception:
            pass


class SierpinskiLoader:
    """Publishes YouTube video frames to the wgpu content source protocol.

    Each slot (0, 1, 2) becomes a named source at /dev/shm/hapax-imagination/sources/
    yt-slot-{N}/. Sources are refreshed every 0.4s. Active slot gets higher opacity
    and z_order so the shader binds it prominently.
    """

    def __init__(self) -> None:
        self._running = False
        self._thread: threading.Thread | None = None
        self._active_slot = 0
        self.video_slots = [VideoSlotStub(i) for i in range(VIDEO_SLOT_COUNT)]

    def start(self) -> None:
        """Start the frame polling thread and deferred director initialization."""
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="sierpinski-loader"
        )
        self._thread.start()
        # Start director loop after a delay (youtube-player needs time to start ffmpeg)
        threading.Thread(
            target=self._start_director, daemon=True, name="sierpinski-director-init"
        ).start()
        log.info("SierpinskiLoader started")

    def _start_director(self) -> None:
        """Deferred director loop startup — waits for YouTube frames to appear."""
        # Wait for at least one YouTube frame to exist
        for _ in range(30):
            if any((YT_FRAME_DIR / f"yt-frame-{i}.jpg").exists() for i in range(VIDEO_SLOT_COUNT)):
                break
            time.sleep(1)
        try:
            # Update slot metadata from youtube-player before starting director
            for slot in self.video_slots:
                slot.update_metadata()

            from agents.studio_compositor.director_loop import DirectorLoop

            self._director = DirectorLoop(video_slots=self.video_slots, reactor_overlay=self)
            self._director.start()
            log.info("DirectorLoop started via SierpinskiLoader")
        except Exception:
            log.exception("DirectorLoop startup failed")

        # Phase 5c: twitch (4s deterministic) + structural (150s LLM) directors
        # run alongside narrative. Enable via env flags so operator can disable
        # if either introduces an issue during rehearsal. Defaults ON for
        # post-epic behavior.
        if os.environ.get("HAPAX_TWITCH_DIRECTOR_ENABLED", "1").lower() not in {
            "0",
            "false",
            "off",
            "no",
        }:
            try:
                from agents.studio_compositor.twitch_director import TwitchDirector

                self._twitch_director = TwitchDirector()
                self._twitch_director.start()
                log.info("TwitchDirector started (4s cadence)")
            except Exception:
                log.exception("TwitchDirector startup failed")
        if os.environ.get("HAPAX_STRUCTURAL_DIRECTOR_ENABLED", "1").lower() not in {
            "0",
            "false",
            "off",
            "no",
        }:
            try:
                from agents.studio_compositor.structural_director import StructuralDirector

                self._structural_director = StructuralDirector()
                self._structural_director.start()
                log.info("StructuralDirector started (150s cadence)")
            except Exception:
                log.exception("StructuralDirector startup failed")

    def stop(self) -> None:
        self._running = False

    def set_active_slot(self, slot_id: int) -> None:
        """Called by director loop when active slot changes."""
        self._active_slot = slot_id

    # --- ReactorOverlay compatibility (director loop calls these) ---

    def set_header(self, header: str) -> None:
        pass

    def set_text(self, text: str) -> None:
        pass

    def set_speaking(self, speaking: bool) -> None:
        pass

    def feed_pcm(self, pcm_bytes: bytes) -> None:
        pass

    def _poll_loop(self) -> None:
        """Poll YouTube frame snapshots and publish them as content sources."""
        from agents.reverie.content_injector import inject_jpeg, remove_source

        while self._running:
            try:
                self._publish_sources(inject_jpeg, remove_source)
            except Exception:
                log.debug("Source publish failed", exc_info=True)
            time.sleep(0.4)

    def _publish_sources(self, inject_jpeg, remove_source) -> None:
        """Publish each YouTube slot as a source via content_injector.

        Active slot gets opacity 0.9 and z_order 5 (highest among YT slots).
        Inactive slots get opacity 0.3 and z_order 2-4.
        Slots with missing yt-frame files get their source removed.
        """
        for slot_id in range(VIDEO_SLOT_COUNT):
            frame_path = YT_FRAME_DIR / f"yt-frame-{slot_id}.jpg"
            source_id = f"yt-slot-{slot_id}"
            if not frame_path.exists():
                # Clean up stale source when the video is gone
                remove_source(source_id)
                continue
            is_active = slot_id == self._active_slot
            opacity = 0.9 if is_active else 0.3
            # Active slot z_order = 5, inactive slots 2-4 in slot_id order
            z_order = 5 if is_active else (2 + slot_id)
            inject_jpeg(
                source_id=source_id,
                jpeg_path=frame_path,
                opacity=opacity,
                z_order=z_order,
                blend_mode="over",
                tags=["youtube", "sierpinski"],
            )
