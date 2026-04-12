"""Sierpinski content loader — writes YouTube video frames to the wgpu content slot manifest.

Replaces SpirographReactor. Polls yt-frame-{0,1,2}.jpg snapshots from the youtube-player
daemon and writes them to the content slot manifest that the Rust ContentTextureManager
polls every 500ms.

The Sierpinski triangle shader (sierpinski_content.wgsl) handles the triangle-region
masking and compositing on the GPU side. This loader is the data pipeline.
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

CONTENT_DIR = Path("/dev/shm/hapax-imagination/content")
ACTIVE_DIR = CONTENT_DIR / "active"
YT_FRAME_DIR = Path("/dev/shm/hapax-compositor")
MANIFEST_PATH = ACTIVE_DIR / "slots.json"


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
    """Loads YouTube video frames into the wgpu content slot pipeline."""

    def __init__(self) -> None:
        self._running = False
        self._thread: threading.Thread | None = None
        self._active_slot = 0
        self.video_slots = [VideoSlotStub(i) for i in range(3)]

    def start(self) -> None:
        """Start the frame polling thread and deferred director initialization."""
        self._running = True
        ACTIVE_DIR.mkdir(parents=True, exist_ok=True)
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
            if any((YT_FRAME_DIR / f"yt-frame-{i}.jpg").exists() for i in range(3)):
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
        """Poll YouTube frame snapshots and write content slot manifest."""
        while self._running:
            try:
                self._update_manifest()
            except Exception:
                log.debug("Manifest update failed", exc_info=True)
            time.sleep(0.4)  # Slightly faster than Rust's 500ms poll

    def _update_manifest(self) -> None:
        """Write slots.json manifest pointing at current YouTube frame JPEGs."""
        slots = []
        for slot_id in range(3):
            frame_path = YT_FRAME_DIR / f"yt-frame-{slot_id}.jpg"
            if not frame_path.exists():
                continue
            # Active slot gets full salience, others reduced
            salience = 0.9 if slot_id == self._active_slot else 0.3
            # Copy frame to content active dir for Rust to load
            dest = ACTIVE_DIR / f"slot_{slot_id}.jpg"
            try:
                shutil.copy2(str(frame_path), str(dest))
            except OSError:
                continue
            slots.append(
                {
                    "index": slot_id,
                    "path": str(dest),
                    "kind": "camera_frame",
                    "salience": salience,
                }
            )

        manifest = {
            "fragment_id": "sierpinski-yt",
            "slots": slots,
            "continuation": True,
            "material": "void",
        }
        tmp = MANIFEST_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(manifest))
        tmp.rename(MANIFEST_PATH)
