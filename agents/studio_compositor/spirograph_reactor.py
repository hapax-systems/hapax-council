"""Spirograph reactor — multi-video PiP with daimonion react overlay.

Three YouTube videos orbit a glowing hypotrochoid path. A four-beat
rotation cycles: each video plays while stationary, then the daimonion
reacts via TTS with a Pango transcript and waveform visualization.
Completed videos explode in synthwave confetti.
"""

from __future__ import annotations

import colorsys
import json
import logging
import math
import random
import struct
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Synthwave confetti palette
CONFETTI_COLORS = [
    (1.0, 0.08, 0.58),  # neon pink
    (0.0, 1.0, 1.0),  # electric cyan
    (1.0, 0.0, 0.8),  # hot magenta
    (0.2, 1.0, 0.2),  # laser green
    (0.5, 0.0, 1.0),  # ultraviolet blue
    (1.0, 0.85, 0.0),  # synthwave gold
]

SHM_DIR = Path("/dev/shm/hapax-compositor")


# ---------------------------------------------------------------------------
# Spirograph path
# ---------------------------------------------------------------------------


class SpirographPath:
    """Hypotrochoid parametric curve with iridescent glow rendering."""

    NUM_POINTS = 1000
    R = 5.0
    r = 3.0
    d = 3.0

    def __init__(self, center_x: float = 960, center_y: float = 540, scale: float = 720) -> None:
        self.base_center_x = center_x
        self.center_x = center_x
        self.center_y = center_y
        self.scale = scale
        # Store normalized points (relative to center)
        self._raw_points = self._compute_raw_points()
        self.points = self._apply_center(self._raw_points)
        self._hue_offset = 0.0
        # Horizontal drift: same speed as node orbit (1/(90*30) per frame)
        # Oscillates across canvas width using sine wave
        self._drift_phase = 0.0
        self._drift_speed = 1.0 / (90 * 30)  # same as orbit speed
        self._drift_amplitude = 300.0  # pixels of horizontal travel from center

    def _compute_raw_points(self) -> list[tuple[float, float]]:
        """Compute points relative to (0, 0)."""
        pts: list[tuple[float, float]] = []
        R, r, d = self.R, self.r, self.d
        t_max = 2 * math.pi * r / math.gcd(int(R), int(r))
        for i in range(self.NUM_POINTS):
            t = t_max * i / self.NUM_POINTS
            x = (R - r) * math.cos(t) + d * math.cos((R - r) / r * t)
            y = (R - r) * math.sin(t) - d * math.sin((R - r) / r * t)
            pts.append((x * self.scale / (R + d), y * self.scale / (R + d)))
        return pts

    def _apply_center(self, raw: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return [(self.center_x + x, self.center_y + y) for x, y in raw]

    def tick(self) -> None:
        """Advance horizontal drift. Call once per frame."""
        self._drift_phase = (self._drift_phase + self._drift_speed) % 1.0
        self.center_x = (
            self.base_center_x + math.sin(self._drift_phase * 2 * math.pi) * self._drift_amplitude
        )
        self.points = self._apply_center(self._raw_points)

    def position_at(self, t: float) -> tuple[float, float]:
        """Position on path at normalized parameter t in [0, 1)."""
        idx = int(t * self.NUM_POINTS) % self.NUM_POINTS
        return self.points[idx]

    def draw(self, cr: Any) -> None:
        """Draw the spirograph as a faintly glowing iridescent thread."""
        self._hue_offset = (self._hue_offset + 0.002) % 1.0
        n = len(self.points)

        # Outer glow pass (wide, soft)
        cr.set_line_width(8.0)
        cr.move_to(*self.points[0])
        for i in range(1, n):
            cr.line_to(*self.points[i])
        cr.close_path()
        cr.set_source_rgba(0.5, 0.3, 1.0, 0.15)
        cr.stroke()

        # Per-segment iridescent color (the visible thread)
        cr.set_line_width(2.5)
        step = max(1, n // 500)
        for i in range(0, n - step, step):
            hue = (self._hue_offset + i / n) % 1.0
            r, g, b = colorsys.hsv_to_rgb(hue, 0.7, 1.0)
            cr.set_source_rgba(r, g, b, 0.55)
            cr.move_to(*self.points[i])
            cr.line_to(*self.points[(i + step) % n])
            cr.stroke()

        # Bright core line (thin, high alpha)
        cr.set_line_width(1.0)
        cr.move_to(*self.points[0])
        for i in range(1, n):
            cr.line_to(*self.points[i])
        cr.close_path()
        hue = self._hue_offset % 1.0
        r, g, b = colorsys.hsv_to_rgb(hue, 0.3, 1.0)
        cr.set_source_rgba(r, g, b, 0.7)
        cr.stroke()


# ---------------------------------------------------------------------------
# Confetti particles
# ---------------------------------------------------------------------------


class ConfettiParticle:
    """Synthwave confetti with gravity, spin, and fade."""

    __slots__ = (
        "x",
        "y",
        "vx",
        "vy",
        "color",
        "alpha",
        "w",
        "h",
        "angle",
        "spin",
        "born",
    )

    def __init__(self, x: float, y: float) -> None:
        a = random.uniform(0, 2 * math.pi)
        speed = random.uniform(4, 16)
        self.x = x
        self.y = y
        self.vx = math.cos(a) * speed
        self.vy = math.sin(a) * speed - random.uniform(2, 6)
        self.color = random.choice(CONFETTI_COLORS)
        self.alpha = 1.0
        self.w = random.uniform(3, 6)
        self.h = random.uniform(1.5, 3)
        self.angle = random.uniform(0, 2 * math.pi)
        self.spin = random.uniform(-0.3, 0.3)
        self.born = time.monotonic()

    @property
    def alive(self) -> bool:
        return self.alpha > 0.03

    def tick(self) -> bool:
        self.x += self.vx
        self.y += self.vy
        self.vy += 0.5
        self.vx *= 0.97
        self.vy *= 0.97
        self.angle += self.spin
        age = time.monotonic() - self.born
        self.alpha = max(0, 1.0 - age / 2.0)
        return self.alive

    def draw(self, cr: Any) -> None:
        cr.save()
        cr.translate(self.x, self.y)
        cr.rotate(self.angle)
        cr.rectangle(-self.w / 2, -self.h / 2, self.w, self.h)
        r, g, b = self.color
        cr.set_source_rgba(r, g, b, self.alpha)
        cr.fill()
        cr.restore()


# ---------------------------------------------------------------------------
# Video slot (frame capture + orbit + confetti)
# ---------------------------------------------------------------------------


class VideoSlot:
    """A video window that orbits the spirograph path."""

    WIDTH = 384
    HEIGHT = 216
    FRAME_SIZE = WIDTH * HEIGHT * 4  # BGRA
    ALPHA = 0.85

    def __init__(self, slot_id: int, device: str) -> None:
        self.slot_id = slot_id
        self.device = device
        self.orbit_t: float = slot_id / 3.0
        self.orbit_speed: float = 1.0 / (90 * 30)  # full orbit in 90s at 30fps
        self.is_active: bool = False
        self._surface = None
        self._surface_lock = threading.Lock()
        self._ffmpeg_proc = None
        self._reader_thread = None
        self._fx_name = ""
        self._fx_func = None
        self._title = ""
        self._channel = ""
        self._confetti: list[ConfettiParticle] = []
        self._finished = False
        self._capturing = False
        # Effect intensity pulse: slow logarithmic oscillation
        # trough=0.35 (moderately effected), peak=1.0 (fully effected)
        self._fx_phase = random.uniform(0, 1)  # desync between slots
        self._fx_pulse_speed = 1.0 / (45 * 30)  # full cycle in 45s at 30fps

    def start_capture(self) -> None:
        """Start polling JPEG snapshots from youtube-player HTTP API."""
        if self._capturing:
            return

        from agents.studio_compositor.fx_chain import PIP_EFFECTS

        self._fx_name, self._fx_func = random.choice(list(PIP_EFFECTS.items()))
        self._capturing = True
        self._reader_thread = threading.Thread(
            target=self._poll_snapshots,
            daemon=True,
            name=f"spirograph-video-{self.slot_id}",
        )
        self._reader_thread.start()
        log.info("VideoSlot %d snapshot polling started (effect=%s)", self.slot_id, self._fx_name)

    def stop_capture(self) -> None:
        self._capturing = False
        with self._surface_lock:
            self._surface = None

    def _poll_snapshots(self) -> None:
        """Poll JPEG snapshots written by youtube-player to /dev/shm.

        The youtube-player writes periodic snapshots to
        /dev/shm/hapax-compositor/yt-frame-{slot_id}.jpg
        We read them and convert to cairo surfaces at ~10fps.
        """
        import io

        import cairo

        snapshot_path = SHM_DIR / f"yt-frame-{self.slot_id}.jpg"
        log.info("VideoSlot %d polling %s", self.slot_id, snapshot_path)
        frame_count = 0
        last_mtime = 0.0
        self._last_good_frame_time = time.monotonic()
        while self._capturing:
            try:
                if snapshot_path.exists():
                    mtime = snapshot_path.stat().st_mtime
                    if mtime > last_mtime:
                        last_mtime = mtime
                        jpeg_data = snapshot_path.read_bytes()
                        if jpeg_data and len(jpeg_data) > 100:
                            from PIL import Image

                            img = Image.open(io.BytesIO(jpeg_data))
                            img = img.resize((self.WIDTH, self.HEIGHT))
                            img = img.convert("RGBA")
                            raw = img.tobytes("raw", "BGRa")
                            img.close()  # explicit close prevents FD leak
                            surface = cairo.ImageSurface.create_for_data(
                                bytearray(raw),
                                cairo.FORMAT_ARGB32,
                                self.WIDTH,
                                self.HEIGHT,
                            )
                            with self._surface_lock:
                                self._surface = surface
                            frame_count += 1
                            self._last_good_frame_time = time.monotonic()
                            if frame_count == 1:
                                log.info("VideoSlot %d: first frame received", self.slot_id)
                            elif frame_count % 100 == 0:
                                log.info("VideoSlot %d: %d frames", self.slot_id, frame_count)
            except Exception:
                pass
            time.sleep(0.1)  # ~10fps

        log.info("VideoSlot %d poller stopped (frames=%d)", self.slot_id, frame_count)

    def check_finished(self) -> bool:
        """Check if youtube-player reported this slot finished."""
        marker = SHM_DIR / f"yt-finished-{self.slot_id}"
        if marker.exists():
            try:
                marker.unlink()
            except OSError:
                pass
            self._finished = True
            return True
        return False

    def spawn_confetti(self, x: float, y: float) -> None:
        for _ in range(80):
            self._confetti.append(ConfettiParticle(x, y))

    @property
    def fx_intensity(self) -> float:
        """Current effect intensity: logarithmic pulse from 0.35 (trough) to 1.0 (peak)."""
        # Sine wave 0→1, then log-shaped: spend more time near trough, spike to peak
        raw = (math.sin(self._fx_phase * 2 * math.pi) + 1) / 2  # 0..1
        # Log shaping: x^0.4 spends more time near low values, sharp rise to peak
        shaped = raw**0.4
        return 0.35 + shaped * 0.65  # 0.35..1.0

    def tick(self, path: SpirographPath) -> tuple[float, float]:
        """Update orbit position and effect pulse. Returns (x, y) screen position."""
        if not self.is_active:
            self.orbit_t = (self.orbit_t + self.orbit_speed) % 1.0
        self._fx_phase = (self._fx_phase + self._fx_pulse_speed) % 1.0
        pos = path.position_at(self.orbit_t)
        self._confetti = [p for p in self._confetti if p.tick()]
        return pos

    _draw_count: int = 0

    def draw(self, cr: Any, x: float, y: float) -> None:
        """Draw video frame at position with effect."""
        with self._surface_lock:
            surface = self._surface

        left = x - self.WIDTH / 2
        top = y - self.HEIGHT / 2

        # Dark backing card (always visible, even without video surface)
        cr.set_source_rgba(0.03, 0.02, 0.05, 0.9)
        cr.rectangle(left - 3, top - 3, self.WIDTH + 6, self.HEIGHT + 6)
        cr.fill()

        # Border
        border_alpha = 0.7 if self.is_active else 0.3
        cr.set_source_rgba(0.7, 0.5, 1.0, border_alpha)
        cr.set_line_width(2.0 if self.is_active else 1.0)
        cr.rectangle(left - 3, top - 3, self.WIDTH + 6, self.HEIGHT + 6)
        cr.stroke()

        if surface is not None:
            cr.save()
            cr.translate(left, top)
            cr.set_source_surface(surface, 0, 0)
            cr.paint_with_alpha(self.ALPHA)
            # Effect layer modulated by logarithmic pulse
            if self._fx_func is not None:
                intensity = self.fx_intensity
                cr.push_group()
                self._fx_func(cr, self.WIDTH, self.HEIGHT)
                cr.pop_group_to_source()
                cr.paint_with_alpha(intensity)
            cr.restore()

        # Slot label
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.5)
        cr.select_font_face("JetBrains Mono")
        cr.set_font_size(11)
        cr.move_to(left + 4, top + self.HEIGHT - 4)
        label = self._title[:35] if self._title else f"Slot {self.slot_id}"
        cr.show_text(label)

        # Confetti
        for p in self._confetti:
            p.draw(cr)

    def update_metadata(self) -> None:
        attr_file = SHM_DIR / f"yt-attribution-{self.slot_id}.txt"
        if attr_file.exists():
            try:
                lines = attr_file.read_text().strip().split("\n")
                self._title = lines[0] if lines else ""
                self._channel = lines[1] if len(lines) > 1 else ""
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Reactor overlay (Pango box + waveform)
# ---------------------------------------------------------------------------


class ReactorOverlay:
    """Pango box for reactor transcript + waveform visualization.

    Gravitates toward the currently active (stationary) video slot
    at the same speed the other videos orbit the spirograph.
    """

    BOX_W = 500
    BOX_H = 250
    WAVE_H = 60
    # Offset from video center to reactor box position
    OFFSET_X = 0  # centered horizontally on the video
    OFFSET_Y = 240  # below the video

    def __init__(self) -> None:
        self._text: str = ""
        self._visible_chars: int = 0
        self._speaking: bool = False
        self._pcm_samples: list[float] = []
        self._border_pulse: float = 0.0
        self._header: str = "REACT"
        self._x: float = 960.0
        self._y: float = 750.0
        self._target_x: float = 960.0
        self._target_y: float = 750.0

    def set_target(self, x: float, y: float) -> None:
        """Set the position to gravitate toward (active video's position)."""
        self._target_x = x + self.OFFSET_X
        self._target_y = y + self.OFFSET_Y

    def _orbit_speed(self) -> float:
        """Same speed as video orbit: 1/(90*30) of full path per frame."""
        # Convert to pixels/frame: approximate as fraction of distance per frame
        # At orbit speed 1/(90*30), a full orbit takes 2700 frames
        # We want the reactor to traverse the same angular distance per frame
        # Use a simple approach: move a fixed fraction of remaining distance
        # that matches the orbit's apparent speed (~5-8 pixels/frame)
        return 0.02  # easing factor — arrives in ~50 frames (~1.7s)

    def set_header(self, header: str) -> None:
        self._header = header

    def set_text(self, text: str) -> None:
        self._text = text
        self._visible_chars = 0

    def set_speaking(self, speaking: bool) -> None:
        self._speaking = speaking
        if speaking:
            self._border_pulse = 1.0

    def feed_pcm(self, pcm_bytes: bytes) -> None:
        n = len(pcm_bytes) // 2
        if n == 0:
            return
        samples = struct.unpack(f"<{n}h", pcm_bytes[: n * 2])
        step = max(1, n // 100)
        self._pcm_samples = [samples[i] / 32768.0 for i in range(0, n, step)][:100]

    def tick(self) -> None:
        # Gravitate toward target (active video position)
        speed = self._orbit_speed()
        self._x += (self._target_x - self._x) * speed
        self._y += (self._target_y - self._y) * speed
        # Clamp to screen bounds
        self._x = max(10, min(1920 - self.BOX_W - 10, self._x))
        self._y = max(self.WAVE_H + 10, min(1080 - self.BOX_H - 10, self._y))
        # Text reveal + pulse decay
        if self._speaking and self._visible_chars < len(self._text):
            self._visible_chars = min(self._visible_chars + 2, len(self._text))
        self._border_pulse *= 0.95
        if not self._speaking:
            self._pcm_samples = []

    def draw(self, cr: Any) -> None:
        try:
            import gi

            gi.require_version("Pango", "1.0")
            gi.require_version("PangoCairo", "1.0")
        except Exception:
            return

        bx = self._x
        by = self._y
        wave_y = by - self.WAVE_H - 10

        # Waveform only — no box, no transcript, just the voice visualization
        if self._pcm_samples:
            cr.set_source_rgba(0.7, 0.5, 1.0, 0.8)
            cr.set_line_width(1.5)
            n = len(self._pcm_samples)
            mid_y = wave_y + self.WAVE_H / 2
            for i, s in enumerate(self._pcm_samples):
                px = bx + i * (self.BOX_W / n)
                py = mid_y + s * (self.WAVE_H / 2)
                if i == 0:
                    cr.move_to(px, py)
                else:
                    cr.line_to(px, py)
            cr.stroke()
        else:
            # Flat line when silent
            cr.set_source_rgba(0.7, 0.5, 1.0, 0.15)
            cr.set_line_width(1.0)
            mid_y = wave_y + self.WAVE_H / 2
            cr.move_to(bx, mid_y)
            cr.line_to(bx + self.BOX_W, mid_y)
            cr.stroke()


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------

DEVICES = ["/dev/video50", "/dev/video51", "/dev/video52"]
PLAYLIST_FILE = SHM_DIR / "playlist.json"
PLAYLIST_URL = "https://youtube.com/playlist?list=PL-4nvD1KwuH--sViEAFY2cHVmS6_B4CQ5"


def _load_playlist() -> list[dict]:
    """Load playlist from shm. Falls back to yt-dlp extraction."""
    try:
        if PLAYLIST_FILE.exists():
            return json.loads(PLAYLIST_FILE.read_text())
    except Exception:
        pass
    # Extract fresh
    try:
        import subprocess as _sp

        result = _sp.run(
            ["yt-dlp", "--dump-json", "--flat-playlist", "--no-warnings", PLAYLIST_URL],
            capture_output=True,
            text=True,
            timeout=60,
        )
        videos = []
        for line in result.stdout.strip().split("\n"):
            if line:
                try:
                    d = json.loads(line)
                    videos.append(
                        {
                            "id": d["id"],
                            "title": d.get("title", "?"),
                            "url": f"https://www.youtube.com/watch?v={d['id']}",
                        }
                    )
                except Exception:
                    pass
        if videos:
            PLAYLIST_FILE.write_text(json.dumps(videos))
            log.info("Extracted %d videos from playlist", len(videos))
        return videos
    except Exception:
        log.exception("Playlist extraction failed")
        return []


def _pick_random_videos(playlist: list[dict], n: int = 3) -> list[str]:
    """Pick n random video URLs from the playlist."""
    if not playlist:
        return []
    picks = random.sample(playlist, min(n, len(playlist)))
    return [v["url"] for v in picks]


class SpirographReactor:
    """Top-level orchestrator: spirograph, video slots, reactor overlay, director."""

    def __init__(self) -> None:
        self.path = SpirographPath()
        self.video_slots = [VideoSlot(i, DEVICES[i]) for i in range(3)]
        self.reactor_overlay = ReactorOverlay()
        self.director = None  # lazy init
        self._initialized = False
        self._init_lock = threading.Lock()

    def initialize(self) -> None:
        """Load initial videos and start capture + director. Call once.

        All heavy work (yt-dlp URL extraction, frame capture startup,
        director loop) runs in a deferred thread to avoid blocking
        the compositor's main GLib loop.
        """
        with self._init_lock:
            if self._initialized:
                return
            self._initialized = True

        def _deferred_init():
            # Load videos from playlist — skip slots that already have videos playing
            playlist = _load_playlist()
            urls = _pick_random_videos(playlist, 3)
            for i, url in enumerate(urls):
                try:
                    status_req = urllib.request.urlopen(
                        f"http://127.0.0.1:8055/slot/{i}/status", timeout=5
                    )
                    status = json.loads(status_req.read())
                    if status.get("playing"):
                        log.info("Slot %d already playing, skipping load", i)
                        continue
                except Exception:
                    pass
                try:
                    body = json.dumps({"url": url}).encode()
                    req = urllib.request.Request(
                        f"http://127.0.0.1:8055/slot/{i}/play",
                        body,
                        {"Content-Type": "application/json"},
                    )
                    urllib.request.urlopen(req, timeout=90)
                    log.info("Loaded slot %d: %s", i, url[:60])
                except Exception:
                    log.exception("Failed to load slot %d", i)

            # Wait for ffmpeg to start writing to v4l2 devices
            time.sleep(8)

            # NOW start frame capture (devices have data)
            for slot in self.video_slots:
                slot.start_capture()

            time.sleep(3)
            for slot in self.video_slots:
                slot.update_metadata()

            # Start director loop
            from agents.studio_compositor.director_loop import DirectorLoop

            self.director = DirectorLoop(self.video_slots, self.reactor_overlay)
            self.director.start()
            log.info("Spirograph reactor fully initialized")

        threading.Thread(target=_deferred_init, daemon=True, name="spiro-init").start()

    def tick(self) -> None:
        """Called every frame (30fps) from fx_tick_callback."""
        if not self._initialized:
            self.initialize()
            return

        # Drift the spirograph horizontally
        self.path.tick()

        for slot in self.video_slots:
            slot.tick(self.path)

        # Reactor gravitates toward the active (stationary) video
        for slot in self.video_slots:
            if slot.is_active:
                pos = self.path.position_at(slot.orbit_t)
                self.reactor_overlay.set_target(pos[0], pos[1])
                break

        self.reactor_overlay.tick()

    def draw(self, cr: Any) -> None:
        """Called every frame from _pip_draw."""
        # 1. Spirograph path (background)
        self.path.draw(cr)

        # 2. Video slots at orbital positions
        for slot in self.video_slots:
            pos = self.path.position_at(slot.orbit_t)
            slot.draw(cr, pos[0], pos[1])

        # 3. Reactor overlay (foreground)
        self.reactor_overlay.draw(cr)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rounded_rect(cr: Any, x: float, y: float, w: float, h: float, r: float) -> None:
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()
