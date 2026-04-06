#!/usr/bin/env python3
"""YouTube player daemon for the studio compositor.

Receives YouTube URLs (via KDE Connect share, HTTP API, or CLI),
decodes video to v4l2loopback (/dev/video50) and audio to PipeWire.
The compositor reads /dev/video50 as an FX source.

Control:
  - KDE Connect: share a YouTube URL from phone → auto-plays
  - HTTP API: POST /play {url}, POST /pause, POST /skip, GET /status
  - CLI: youtube-player play <url>, youtube-player pause, youtube-player skip

Audio goes to PipeWire mixer → picked up by compositor audio capture
for reactivity (kick detection, sidechain compression, etc).
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("youtube-player")

V4L2_DEVICE = "/dev/video50"
LISTEN_PORT = 8055
DEVICE_ID = "aecd697f91434f7797836db631b36e3b"  # Pixel 10

# --- State ---
current_process: subprocess.Popen | None = None
current_url: str = ""
current_title: str = ""
queue: deque[dict] = deque()
paused = False
lock = threading.Lock()


def extract_urls(youtube_url: str) -> tuple[str, str, str]:
    """Extract direct video URL, audio URL, and title via yt-dlp."""
    log.info("Extracting URLs for: %s", youtube_url)
    # Get title
    title_proc = subprocess.run(
        ["yt-dlp", "--get-title", youtube_url],
        capture_output=True, text=True, timeout=15,
    )
    title = title_proc.stdout.strip() or "Unknown"

    # Get video URL
    video_proc = subprocess.run(
        ["yt-dlp", "-f", "bestvideo[height<=1080][ext=mp4]/bestvideo[height<=1080]",
         "-g", youtube_url],
        capture_output=True, text=True, timeout=15,
    )
    video_url = video_proc.stdout.strip()

    # Get audio URL
    audio_proc = subprocess.run(
        ["yt-dlp", "-f", "bestaudio[ext=m4a]/bestaudio", "-g", youtube_url],
        capture_output=True, text=True, timeout=15,
    )
    audio_url = audio_proc.stdout.strip()

    if not video_url or not audio_url:
        raise RuntimeError(f"Failed to extract URLs: video={bool(video_url)}, audio={bool(audio_url)}")

    return video_url, audio_url, title


def play_video(youtube_url: str) -> None:
    """Start ffmpeg decoding video to v4l2loopback + audio to PipeWire."""
    global current_process, current_url, current_title, paused

    stop_current()

    try:
        video_url, audio_url, title = extract_urls(youtube_url)
    except Exception as e:
        log.error("URL extraction failed: %s", e)
        return

    log.info("Playing: %s", title)
    current_url = youtube_url
    current_title = title
    paused = False

    # ffmpeg: video → v4l2loopback, audio → PipeWire
    cmd = [
        "ffmpeg", "-y",
        "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
        "-i", video_url,
        "-i", audio_url,
        "-map", "0:v", "-vf", "scale=1920:1080",
        "-pix_fmt", "yuyv422", "-f", "v4l2", V4L2_DEVICE,
        "-map", "1:a", "-f", "pulse", "-ac", "2", "youtube-audio",
    ]

    current_process = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    log.info("ffmpeg started (PID %d)", current_process.pid)

    # Notify compositor to switch source
    try:
        Path("/dev/shm/hapax-compositor/fx-source.txt").write_text("youtube")
    except OSError:
        pass


def stop_current() -> None:
    """Stop the currently playing video."""
    global current_process, current_url, current_title, paused
    if current_process is not None:
        try:
            current_process.send_signal(signal.SIGTERM)
            current_process.wait(timeout=3)
        except Exception:
            try:
                current_process.kill()
            except Exception:
                pass
        current_process = None
        current_url = ""
        current_title = ""
        paused = False
        log.info("Playback stopped")


def toggle_pause() -> bool:
    """Pause/resume ffmpeg via SIGSTOP/SIGCONT."""
    global paused
    if current_process is None:
        return False
    if paused:
        current_process.send_signal(signal.SIGCONT)
        paused = False
        log.info("Resumed")
    else:
        current_process.send_signal(signal.SIGSTOP)
        paused = True
        log.info("Paused")
    return paused


def skip_to_next() -> None:
    """Skip to next in queue."""
    stop_current()
    if queue:
        item = queue.popleft()
        play_video(item["url"])
    else:
        log.info("Queue empty")
        try:
            Path("/dev/shm/hapax-compositor/fx-source.txt").write_text("live")
        except OSError:
            pass


def add_to_queue(url: str) -> None:
    """Add URL to queue. If nothing playing, start immediately."""
    queue.append({"url": url})
    log.info("Queued: %s (%d in queue)", url, len(queue))
    if current_process is None or current_process.poll() is not None:
        skip_to_next()


def get_status() -> dict:
    """Current player status."""
    running = current_process is not None and current_process.poll() is None
    return {
        "playing": running and not paused,
        "paused": paused,
        "url": current_url,
        "title": current_title,
        "queue_length": len(queue),
        "queue": [q["url"] for q in queue],
    }


# --- Auto-advance thread ---
def auto_advance_loop() -> None:
    """Watch for ffmpeg exit and advance to next in queue."""
    while True:
        time.sleep(1)
        with lock:
            if current_process is not None and current_process.poll() is not None:
                log.info("Video ended (exit %d)", current_process.returncode)
                current_process = None  # noqa: F841 — cleared for skip_to_next
                skip_to_next()


# --- HTTP API ---
class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress default logging

    def _json(self, data: dict, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self) -> None:
        if self.path == "/status":
            self._json(get_status())
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len)) if content_len > 0 else {}

        if self.path == "/play":
            url = body.get("url", "")
            if not url:
                self._json({"error": "url required"}, 400)
                return
            with lock:
                add_to_queue(url)
            self._json({"status": "queued", "url": url})

        elif self.path == "/pause":
            with lock:
                is_paused = toggle_pause()
            self._json({"paused": is_paused})

        elif self.path == "/skip":
            with lock:
                skip_to_next()
            self._json({"status": "skipped"})

        elif self.path == "/stop":
            with lock:
                stop_current()
            try:
                Path("/dev/shm/hapax-compositor/fx-source.txt").write_text("live")
            except OSError:
                pass
            self._json({"status": "stopped"})

        else:
            self._json({"error": "not found"}, 404)


# --- KDE Connect D-Bus listener ---
def kde_connect_listener() -> None:
    """Listen for shared URLs from KDE Connect via D-Bus."""
    try:
        import dbus
        from dbus.mainloop.glib import DBusGMainLoop
        from gi.repository import GLib

        DBusGMainLoop(set_as_default=True)
        bus = dbus.SessionBus()

        def on_share_received(url: str) -> None:
            log.info("KDE Connect share received: %s", url)
            if "youtube.com" in url or "youtu.be" in url:
                with lock:
                    add_to_queue(url)
            else:
                log.info("Ignoring non-YouTube URL: %s", url)

        bus.add_signal_receiver(
            on_share_received,
            signal_name="shareReceived",
            dbus_interface="org.kde.kdeconnect.device.share",
            path=f"/modules/kdeconnect/devices/{DEVICE_ID}/share",
        )

        log.info("KDE Connect listener active (device: %s)", DEVICE_ID)
        loop = GLib.MainLoop()
        loop.run()
    except ImportError:
        log.warning("python-dbus not available — KDE Connect listener disabled")
    except Exception:
        log.exception("KDE Connect listener failed")


# --- CLI ---
def cli_main() -> None:
    """CLI interface: youtube-player play <url> / pause / skip / stop / status"""
    import urllib.request

    if len(sys.argv) < 2:
        print("Usage: youtube-player <play URL|pause|skip|stop|status>")
        sys.exit(1)

    cmd = sys.argv[1]
    base = f"http://127.0.0.1:{LISTEN_PORT}"

    if cmd == "play" and len(sys.argv) > 2:
        data = json.dumps({"url": sys.argv[2]}).encode()
        req = urllib.request.Request(f"{base}/play", data, {"Content-Type": "application/json"})
        print(urllib.request.urlopen(req).read().decode())
    elif cmd in ("pause", "skip", "stop"):
        req = urllib.request.Request(f"{base}/{cmd}", b"", {"Content-Type": "application/json"})
        print(urllib.request.urlopen(req).read().decode())
    elif cmd == "status":
        print(urllib.request.urlopen(f"{base}/status").read().decode())
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


# --- Main ---
def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in ("play", "pause", "skip", "stop", "status"):
        cli_main()
        return

    log.info("YouTube player daemon starting on :%d", LISTEN_PORT)
    log.info("v4l2 output: %s", V4L2_DEVICE)

    # Auto-advance thread
    threading.Thread(target=auto_advance_loop, daemon=True).start()

    # KDE Connect listener
    threading.Thread(target=kde_connect_listener, daemon=True).start()

    # HTTP API
    server = HTTPServer(("127.0.0.1", LISTEN_PORT), Handler)
    log.info("HTTP API ready — POST /play, /pause, /skip, /stop | GET /status")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        stop_current()
        log.info("Shutting down")


if __name__ == "__main__":
    main()
