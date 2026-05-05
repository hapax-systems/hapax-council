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
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("youtube-player")

V4L2_DEVICES = ["/dev/video50", "/dev/video51", "/dev/video52"]
LISTEN_PORT = 8055
DEVICE_ID = "aecd697f91434f7797836db631b36e3b"  # Pixel 10
SHM_DIR = Path("/dev/shm/hapax-compositor")

# Legacy compat
V4L2_DEVICE = V4L2_DEVICES[0]
lock = threading.Lock()


def _playback_rate() -> float:
    """Global playback rate for YouTube A/V. Default 0.5x for DMCA evasion.

    Rationale: broadcast streams that contain audio pitch/tempo-matched to
    the original commercial recording are DMCA-fingerprint matchable.
    Slowing to 0.5x shifts the spectral signature enough to evade the
    fingerprinter while keeping the music recognizable as Oudepode's
    curated aesthetic. Override via HAPAX_YOUTUBE_PLAYBACK_RATE.

    Range: (0.25, 2.0). Values outside are clamped.
    """
    raw = os.environ.get("HAPAX_YOUTUBE_PLAYBACK_RATE", "0.5").strip()
    try:
        rate = float(raw)
    except ValueError:
        log.warning("HAPAX_YOUTUBE_PLAYBACK_RATE=%r not parseable; using 0.5", raw)
        return 0.5
    if rate < 0.25:
        return 0.25
    if rate > 2.0:
        return 2.0
    return rate


class VideoSlot:
    """Independent video playback slot with v4l2 output + JPEG snapshots."""

    def __init__(self, slot_id: int) -> None:
        self.slot_id = slot_id
        self.device = V4L2_DEVICES[slot_id] if slot_id < len(V4L2_DEVICES) else V4L2_DEVICES[0]
        self.process: subprocess.Popen | None = None
        self.url: str = ""
        self.title: str = ""
        self.channel: str = ""
        self.lock = threading.Lock()

    def play(self, youtube_url: str) -> None:
        self.stop()
        try:
            video_url, audio_url, title, channel = extract_urls(youtube_url)
        except Exception as e:
            log.error("Slot %d URL extraction failed: %s", self.slot_id, e)
            self._signal_finished(rc=-1)
            return

        log.info("Slot %d playing: %s by %s", self.slot_id, title, channel)
        self.url = youtube_url
        self.title = title
        self.channel = channel

        attr_file = SHM_DIR / f"yt-attribution-{self.slot_id}.txt"
        try:
            attr_file.write_text(f"{title}\n{channel}\n{youtube_url}")
        except OSError:
            pass

        snapshot_path = SHM_DIR / f"yt-frame-{self.slot_id}.jpg"
        rate = _playback_rate()
        # PTS multiplier slows video (rate=0.5 → setpts=2.000*PTS).
        # atempo slows audio; ffmpeg's atempo filter supports 0.5..100.0
        # natively so no chaining needed for the DMCA-evasion preset.
        video_pts = f"setpts={1.0 / rate:.3f}*PTS"
        audio_tempo = f"atempo={rate:.3f}"
        log.info(
            "Slot %d playback rate %.3fx (video %s, audio %s)",
            self.slot_id,
            rate,
            video_pts,
            audio_tempo,
        )
        # 2026-04-17 CPU audit: only slot 0's v4l2 device is consumed by
        # the compositor (fx_chain.py:448 binds /dev/video50 as the live
        # YouTube source). Slots 1 and 2 write to /dev/video51 and
        # /dev/video52 but have no reader — the YUV422 conversion +
        # scale=960:540 was pure waste. Keep the v4l2 output for slot 0,
        # skip it for the other slots. JPEG snapshots (used by the
        # Sierpinski triangle) + pulse audio remain for every slot.
        emit_v4l2 = self.slot_id == 0
        cmd: list[str] = [
            "ffmpeg",
            "-y",
            "-reconnect",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_delay_max",
            "5",
            "-i",
            video_url,
            "-i",
            audio_url,
        ]
        if emit_v4l2:
            cmd += [
                # Output 1 (slot 0 only): v4l2loopback for the live YouTube
                # source. 960x540 keeps aspect + 2x headroom for the PiP
                # the compositor blits into (<=640x640 on the Sierpinski
                # triangle corners), avoiding the wasted 1080p upscale+
                # downscale round-trip.
                "-map",
                "0:v",
                "-vf",
                f"{video_pts},scale=960:540",
                "-pix_fmt",
                "yuyv422",
                "-f",
                "v4l2",
                self.device,
            ]
        cmd += [
            # Output (all slots): JPEG snapshots for the Sierpinski
            # reactor. Each slot's triangle corner polls yt-frame-{id}.jpg.
            "-map",
            "0:v",
            "-vf",
            f"{video_pts},scale=384:216",
            "-update",
            "1",
            "-r",
            "10",
            str(snapshot_path),
            # Output (all slots): audio to PipeWire, tempo-shifted for
            # DMCA evasion. Each slot ends up on its own pulse stream so
            # the voice mixer can crossfade.
            #
            # `-device hapax-yt-loudnorm` routes the stream into the
            # sc4 + hard_limiter loudnorm filter-chain sink before it
            # hits the L-12/broadcast chain. Without this, pulse picks
            # the default sink (role-multimedia) and the YT bed bypasses
            # software normalisation entirely — the gap surfaced in the
            # 2026-04-21 per-source normalisation audit.
            "-map",
            "1:a",
            "-af",
            audio_tempo,
            "-f",
            "pulse",
            # Route through hapax-yt-loudnorm rather than the default sink.
            # WirePlumber role-based fallback sends Multimedia content to
            # hapax-pc-loudnorm (operator monitor) and bypasses both the
            # loudnorm and the voice-over ducker — see
            # config/pipewire/hapax-yt-loudnorm.conf + hapax-voice-over-ytube-duck.conf
            # for the intended chain.
            "-device",
            "hapax-yt-loudnorm",
            "-ac",
            "2",
            f"youtube-audio-{self.slot_id}",
        ]
        self.process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        log.info(
            "Slot %d ffmpeg started (PID %d), snapshots → %s",
            self.slot_id,
            self.process.pid,
            snapshot_path,
        )
        # Drain stderr to prevent buffer overflow stall (critical for 24/7)
        threading.Thread(
            target=self._drain_stderr,
            daemon=True,
            name=f"ffmpeg-stderr-{self.slot_id}",
        ).start()
        # Watchdog: restart ffmpeg if snapshots go stale
        threading.Thread(
            target=self._snapshot_watchdog,
            args=(snapshot_path,),
            daemon=True,
            name=f"snapshot-watchdog-{self.slot_id}",
        ).start()

    def _drain_stderr(self) -> None:
        """Drain ffmpeg stderr to prevent buffer overflow stall."""
        proc = self.process
        if proc is None or proc.stderr is None:
            return
        while proc.poll() is None:
            try:
                proc.stderr.readline()
            except Exception:
                break

    def _snapshot_watchdog(self, snapshot_path) -> None:
        """Restart ffmpeg if JPEG snapshots go stale (>30s old)."""
        while self.process is not None and self.process.poll() is None:
            time.sleep(15)
            try:
                if snapshot_path.exists():
                    age = time.time() - snapshot_path.stat().st_mtime
                    if age > 30 and self.url:
                        log.warning(
                            "Slot %d: snapshot stale %.0fs, restarting ffmpeg",
                            self.slot_id,
                            age,
                        )
                        with self.lock:
                            self.play(self.url)
                        return  # new watchdog starts in new play()
            except Exception:
                pass

    def _signal_finished(self, rc: int) -> None:
        """Write yt-finished-N marker so the director loop re-dispatches.

        Used when URL extraction fails before ffmpeg even starts — without this
        the slot sits idle forever because ``auto_advance_loop`` only notices
        ffmpeg-level exits. The director's ``VideoSlotStub.check_finished`` will
        read (and unlink) the marker, triggering ``_reload_slot_from_playlist``
        which picks a different random entry from the playlist.
        """
        marker = SHM_DIR / f"yt-finished-{self.slot_id}"
        try:
            marker.write_text(str(rc))
        except OSError:
            log.debug("Slot %d: failed to write finished marker", self.slot_id)

    def stop(self) -> None:
        for f in [
            SHM_DIR / f"yt-attribution-{self.slot_id}.txt",
            SHM_DIR / f"yt-frame-{self.slot_id}.jpg",
        ]:
            f.unlink(missing_ok=True)
        if self.process is not None:
            try:
                self.process.send_signal(signal.SIGTERM)
                self.process.wait(timeout=3)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
            self.url = ""
            self.title = ""
            self.channel = ""

    def is_playing(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def is_finished(self) -> bool:
        return self.process is not None and self.process.poll() is not None

    def get_status(self) -> dict:
        running = self.process is not None and self.process.poll() is None
        return {
            "slot": self.slot_id,
            "playing": running,
            "url": self.url,
            "title": self.title,
            "channel": self.channel,
            "finished": self.is_finished(),
        }


_N_SLOTS = int(os.environ.get("YOUTUBE_PLAYER_SLOTS", "3"))
slots: list[VideoSlot] = [VideoSlot(i) for i in range(_N_SLOTS)]

# Legacy compat
current_process = None
current_url = ""
current_title = ""
current_channel: str = ""
queue: deque[dict] = deque()


def get_all_slots_status() -> list[dict]:
    return [s.get_status() for s in slots]


def extract_urls(youtube_url: str) -> tuple[str, str, str, str]:
    """Extract direct video URL, audio URL, title, and channel via yt-dlp.

    Each yt-dlp subprocess gets 45s. The previous 15s ceiling caused 2026-04-12
    16:19/16:20 slot stalls where metadata or -g extraction legitimately needed
    more time; on TimeoutExpired the slot was wedged until service restart.
    """
    log.info("Extracting URLs for: %s", youtube_url)
    # Get metadata (title + channel) — use --print for both to get deterministic output order
    meta_proc = subprocess.run(
        ["yt-dlp", "--print", "%(title)s", "--print", "%(channel)s", youtube_url],
        capture_output=True,
        text=True,
        timeout=45,
    )
    lines = meta_proc.stdout.strip().split("\n")
    title = lines[0] if lines else "Unknown"
    channel = lines[1] if len(lines) > 1 else "Unknown"

    # Get video URL
    video_proc = subprocess.run(
        [
            "yt-dlp",
            "-f",
            "bestvideo[height<=1080][ext=mp4]/bestvideo[height<=1080]",
            "-g",
            youtube_url,
        ],
        capture_output=True,
        text=True,
        timeout=45,
    )
    video_url = video_proc.stdout.strip()

    # Get audio URL
    audio_proc = subprocess.run(
        ["yt-dlp", "-f", "bestaudio[ext=m4a]/bestaudio", "-g", youtube_url],
        capture_output=True,
        text=True,
        timeout=45,
    )
    audio_url = audio_proc.stdout.strip()

    if not video_url or not audio_url:
        raise RuntimeError(
            f"Failed to extract URLs: video={bool(video_url)}, audio={bool(audio_url)}"
        )

    return video_url, audio_url, title, channel


ATTRIBUTION_FILE = Path("/dev/shm/hapax-compositor/yt-attribution.txt")
ATTRIBUTION_LOG = Path(
    os.path.expanduser("~/Documents/Personal/30-areas/legomena-live/attribution-log.md")
)
current_channel: str = ""


# --- YouTube Data API description updater ---
class LivestreamDescriptionUpdater:
    """Updates YouTube livestream description with attribution links.

    Reads OAuth2 credentials from `pass show google/youtube-token`.
    Automatically refreshes access tokens when expired.
    """

    TOKEN_URI = "https://oauth2.googleapis.com/token"
    API_BASE = "https://www.googleapis.com/youtube/v3"

    def __init__(self) -> None:
        self._credentials: dict | None = None
        self._access_token: str = ""
        self._broadcast_id: str = ""
        self._video_id: str = ""
        self._base_description: str = ""
        self._enabled = False
        self._load_credentials()

    def _load_credentials(self) -> None:
        try:
            result = subprocess.run(
                ["pass", "show", "google/token"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                log.info(
                    "YouTube API: no credentials in google/token (re-run Google OAuth consent)"
                )
                return
            self._credentials = json.loads(result.stdout.strip())
            scopes = self._credentials.get("scopes", [])
            if "https://www.googleapis.com/auth/youtube.force-ssl" not in scopes:
                log.info(
                    "YouTube API: token missing youtube.force-ssl scope — re-run OAuth consent"
                )
                return
            self._access_token = self._credentials.get("token", "")
            self._enabled = True
            log.info("YouTube API: credentials loaded, description updates enabled")
        except Exception as e:
            log.info("YouTube API: credentials unavailable (%s)", e)

    def _refresh_token(self) -> bool:
        if not self._credentials:
            return False
        data = urllib.parse.urlencode(
            {
                "client_id": self._credentials["client_id"],
                "client_secret": self._credentials["client_secret"],
                "refresh_token": self._credentials["refresh_token"],
                "grant_type": "refresh_token",
            }
        ).encode()
        try:
            req = urllib.request.Request(
                self.TOKEN_URI,
                data,
                {"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp = urllib.request.urlopen(req, timeout=10)
            tokens = json.loads(resp.read())
            self._access_token = tokens["access_token"]
            return True
        except Exception as e:
            log.warning("YouTube API: token refresh failed: %s", e)
            return False

    def _api_get(self, path: str, params: dict) -> dict | None:
        qs = urllib.parse.urlencode(params)
        url = f"{self.API_BASE}/{path}?{qs}"
        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                    },
                )
                resp = urllib.request.urlopen(req, timeout=10)
                return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                if e.code == 401 and attempt == 0:
                    self._refresh_token()
                    continue
                log.warning("YouTube API GET %s: %s", path, e)
                return None
            except Exception as e:
                log.warning("YouTube API GET %s: %s", path, e)
                return None
        return None

    def _api_put(self, path: str, params: dict, body: dict) -> dict | None:
        qs = urllib.parse.urlencode(params)
        url = f"{self.API_BASE}/{path}?{qs}"
        data = json.dumps(body).encode()
        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    url,
                    data,
                    method="PUT",
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "Content-Type": "application/json",
                    },
                )
                resp = urllib.request.urlopen(req, timeout=10)
                return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                if e.code == 401 and attempt == 0:
                    self._refresh_token()
                    continue
                log.warning("YouTube API PUT %s: %s", path, e)
                return None
            except Exception as e:
                log.warning("YouTube API PUT %s: %s", path, e)
                return None
        return None

    def _find_active_broadcast(self) -> bool:
        """Find the currently active livestream broadcast."""
        data = self._api_get(
            "liveBroadcasts",
            {
                "broadcastStatus": "active",
                "part": "snippet",
                "mine": "true",
            },
        )
        if not data or not data.get("items"):
            # Try upcoming (stream may be in preview)
            data = self._api_get(
                "liveBroadcasts",
                {
                    "broadcastStatus": "upcoming",
                    "part": "snippet",
                    "mine": "true",
                },
            )
        if not data or not data.get("items"):
            log.debug("YouTube API: no active/upcoming broadcast found")
            return False
        broadcast = data["items"][0]
        self._broadcast_id = broadcast["id"]
        # The video ID for a broadcast is the same as the broadcast ID
        self._video_id = broadcast["id"]
        self._base_description = broadcast["snippet"].get("description", "")
        log.info("YouTube API: found broadcast %s", self._broadcast_id)
        return True

    def update_description(self) -> None:
        """Update the livestream description with current attribution log."""
        if not self._enabled:
            return
        if not self._video_id and not self._find_active_broadcast():
            return

        # Read attribution log
        try:
            if not ATTRIBUTION_LOG.exists():
                return
            attribution_text = ATTRIBUTION_LOG.read_text().strip()
            if not attribution_text:
                return
        except OSError:
            return

        # Build description: base + attribution section
        separator = "\n\n---\n\n"
        attr_section = "🎵 React content played during this stream:\n" + attribution_text

        # Check if we already have an attribution section
        if "React content played during this stream:" in self._base_description:
            # Replace existing section
            parts = self._base_description.split("React content played during this stream:")
            new_desc = parts[0].rstrip() + separator + attr_section
        else:
            new_desc = self._base_description + separator + attr_section

        # Get current video snippet to preserve required fields
        video_data = self._api_get(
            "videos",
            {
                "id": self._video_id,
                "part": "snippet",
            },
        )
        if not video_data or not video_data.get("items"):
            # Broadcast may have ended, try to find new one
            self._video_id = ""
            return

        snippet = video_data["items"][0]["snippet"]
        snippet["description"] = new_desc
        # categoryId is required for update
        if "categoryId" not in snippet:
            snippet["categoryId"] = "20"  # Gaming (closest to creative coding)

        result = self._api_put(
            "videos",
            {"part": "snippet"},
            {
                "id": self._video_id,
                "snippet": snippet,
            },
        )
        if result:
            log.info(
                "YouTube API: description updated with %d attribution entries",
                attribution_text.count("\n") + 1,
            )


_yt_updater: LivestreamDescriptionUpdater | None = None


def play_video(youtube_url: str) -> None:
    """Start ffmpeg decoding video to v4l2loopback + audio to PipeWire."""
    global current_process, current_url, current_title, current_channel

    stop_current()

    try:
        video_url, audio_url, title, channel = extract_urls(youtube_url)
    except Exception as e:
        log.error("URL extraction failed: %s", e)
        return

    log.info("Playing: %s by %s", title, channel)
    current_url = youtube_url
    current_title = title
    current_channel = channel

    # Write attribution for Pango overlay
    try:
        ATTRIBUTION_FILE.write_text(f"{title}\n{channel}\n{youtube_url}")
    except OSError:
        pass

    # Append to persistent attribution log (for livestream description)
    try:
        ATTRIBUTION_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(ATTRIBUTION_LOG, "a") as f:
            from datetime import datetime

            f.write(
                f"- [{title}]({youtube_url}) — {channel} ({datetime.now().strftime('%H:%M')})\n"
            )
    except OSError:
        pass

    # Update livestream description with attribution (non-blocking)
    if _yt_updater:
        threading.Thread(target=_yt_updater.update_description, daemon=True).start()

    # ffmpeg: video → v4l2loopback, audio → PipeWire
    cmd = [
        "ffmpeg",
        "-y",
        "-reconnect",
        "1",
        "-reconnect_streamed",
        "1",
        "-reconnect_delay_max",
        "5",
        "-i",
        video_url,
        "-i",
        audio_url,
        "-map",
        "0:v",
        "-vf",
        "scale=1920:1080",
        "-pix_fmt",
        "yuyv422",
        "-f",
        "v4l2",
        V4L2_DEVICE,
        "-map",
        "1:a",
        "-f",
        "pulse",
        # Route through hapax-yt-loudnorm rather than the default sink
        # (see slotted pipeline above for the rationale).
        "-device",
        "hapax-yt-loudnorm",
        "-ac",
        "2",
        "youtube-audio",
    ]

    current_process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    log.info("ffmpeg started (PID %d)", current_process.pid)
    # YouTubeOverlay PiP detects playing state via HTTP poll — no fx-source.txt needed


def stop_current() -> None:
    """Stop the currently playing video."""
    global current_process, current_url, current_title, current_channel
    ATTRIBUTION_FILE.unlink(missing_ok=True)
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
        current_channel = ""
        log.info("Playback stopped")


def skip_to_next() -> None:
    """Skip to next in queue."""
    stop_current()
    if queue:
        item = queue.popleft()
        play_video(item["url"])
    else:
        log.info("Queue empty")


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
        "playing": running,
        "url": current_url,
        "title": current_title,
        "channel": current_channel,
        "queue_length": len(queue),
        "queue": [q["url"] for q in queue],
    }


# --- Auto-advance thread ---
MAX_URL_RETRY = 2


_YT_AUDIO_STATE_FILE = SHM_DIR / "yt-audio-state.json"
_yt_audio_last_written: bool | None = None


def _active_slot_id() -> int:
    """Slot whose audio should be audible. Defaults to 0.

    Bridge policy — wiring-audit smoking gun #3: SlotAudioControl's
    mute_all_except only fires at compositor startup, so ffmpeg
    reconnects come up at unity volume and produce cacophony across
    slots 0/1/2. Until alpha's systematic fix lands (re-apply mute on
    sink-input-added events, or director-nominated slot via SHM), hold
    slot 0 audible and mute 1/2 at every ffmpeg spawn/reconnect. Operator
    can override via ``HAPAX_YT_ACTIVE_SLOT`` env var.
    """
    raw = os.environ.get("HAPAX_YT_ACTIVE_SLOT", "0").strip()
    try:
        value = int(raw)
    except ValueError:
        return 0
    return value if value in (0, 1, 2) else 0


def _apply_slot_mute_policy() -> None:
    """Mute all non-active YT sink-inputs via wpctl (idempotent).

    Discovers PipeWire node IDs for youtube-audio-{0,1,2}, sets the
    active slot to unmuted 1.0 and the others to muted 0.0. Safe to
    call on every tick — wpctl set-volume/set-mute are idempotent and
    ~10ms per call.
    """
    try:
        result = subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=5)
        nodes = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return
    active = _active_slot_id()
    for node in nodes:
        if node.get("type") != "PipeWire:Interface:Node":
            continue
        props = node.get("info", {}).get("props", {})
        media_name = props.get("media.name", "")
        if not media_name.startswith("youtube-audio-"):
            continue
        try:
            slot_id = int(media_name.rsplit("-", 1)[-1])
        except ValueError:
            continue
        is_active = slot_id == active
        vol = "1.0" if is_active else "0.0"
        mute = "0" if is_active else "1"
        try:
            subprocess.run(
                ["wpctl", "set-volume", str(node["id"]), vol],
                timeout=2,
                capture_output=True,
            )
            subprocess.run(
                ["wpctl", "set-mute", str(node["id"]), mute],
                timeout=2,
                capture_output=True,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass


def _publish_yt_audio_active(active: bool) -> None:
    """Atomically publish the YouTube/React audio-activity state.

    Mirror of ``agents.studio_compositor.audio_ducking.set_yt_audio_active``
    — duplicated inline to avoid the agents/ import path under system
    Python.

    The AudioDuckingController watches this file to flip its
    ``yt_active`` gauge and drive voice-vs-music ducking.

    **Task #183 fix (2026-04-20)**: writes on EVERY tick, not just on
    state-change. Previously the file was written only on edge
    transitions, so consumers couldn't use mtime as a liveness signal
    — a dead producer left the last boolean stale forever. Writing
    every tick (idempotent tmp+rename) keeps mtime fresh so downstream
    readers can staleness-check the producer.
    """
    global _yt_audio_last_written
    try:
        _YT_AUDIO_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _YT_AUDIO_STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"yt_audio_active": bool(active)}))
        tmp.replace(_YT_AUDIO_STATE_FILE)
        _yt_audio_last_written = bool(active)
    except OSError as exc:
        log.debug("yt-audio-state write failed: %s", exc)


def auto_advance_loop() -> None:
    """Watch for ffmpeg exits across all slots."""
    retry_counts: dict[int, int] = {i: 0 for i in range(len(slots))}
    while True:
        time.sleep(1)
        # Publish yt_audio_active state on every tick so
        # AudioDuckingController sees the truth. The publisher is
        # change-gated internally so this is cheap.
        any_playing = any(s.process is not None and s.process.poll() is None for s in slots)
        _publish_yt_audio_active(any_playing)
        # Bridge fix for wiring-audit smoking gun #3: re-apply slot mute
        # policy every tick so ffmpeg reconnects don't leave non-active
        # slots at unity volume. wpctl set-volume is idempotent.
        if any_playing:
            _apply_slot_mute_policy()
        for slot in slots:
            with slot.lock:
                if slot.process is not None and slot.process.poll() is not None:
                    rc = slot.process.returncode
                    url = slot.url
                    log.info("Slot %d ended (exit %d)", slot.slot_id, rc)
                    if rc != 0 and url and retry_counts[slot.slot_id] < MAX_URL_RETRY:
                        retry_counts[slot.slot_id] += 1
                        log.info(
                            "Slot %d retry %d/%d",
                            slot.slot_id,
                            retry_counts[slot.slot_id],
                            MAX_URL_RETRY,
                        )
                        slot.play(url)
                    else:
                        retry_counts[slot.slot_id] = 0
                        marker = SHM_DIR / f"yt-finished-{slot.slot_id}"
                        try:
                            marker.write_text(str(rc))
                        except OSError:
                            pass
                        slot.process = None
                        log.info("Slot %d finished", slot.slot_id)


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
            self._json(slots[0].get_status())
        elif self.path == "/slots":
            self._json(get_all_slots_status())
        elif self.path.startswith("/slot/") and self.path.endswith("/status"):
            try:
                slot_id = int(self.path.split("/")[2])
                if 0 <= slot_id < len(slots):
                    self._json(slots[slot_id].get_status())
                else:
                    self._json({"error": "invalid slot"}, 400)
            except (ValueError, IndexError):
                self._json({"error": "invalid slot"}, 400)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len)) if content_len > 0 else {}

        # Per-slot endpoints
        if self.path.startswith("/slot/"):
            parts = self.path.strip("/").split("/")
            if len(parts) >= 3:
                try:
                    slot_id = int(parts[1])
                except ValueError:
                    self._json({"error": "invalid slot"}, 400)
                    return
                action = parts[2]
                if not (0 <= slot_id < len(slots)):
                    self._json({"error": "invalid slot"}, 400)
                    return
                slot = slots[slot_id]
                if action == "play":
                    url = body.get("url", "")
                    if not url:
                        self._json({"error": "url required"}, 400)
                        return
                    with slot.lock:
                        slot.play(url)
                    self._json({"status": "playing", "slot": slot_id})
                elif action == "stop":
                    with slot.lock:
                        slot.stop()
                    self._json({"status": "stopped", "slot": slot_id})
                else:
                    self._json({"error": "unknown action"}, 404)
                return

        # Legacy endpoints → slot 0
        if self.path == "/play":
            url = body.get("url", "")
            if not url:
                self._json({"error": "url required"}, 400)
                return
            with slots[0].lock:
                slots[0].play(url)
            self._json({"status": "playing", "url": url})
        elif self.path == "/skip":
            self._json({"status": "use /slot/N/stop"})
        elif self.path == "/stop":
            with slots[0].lock:
                slots[0].stop()
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

    global _yt_updater

    log.info("YouTube player daemon starting on :%d", LISTEN_PORT)
    log.info("v4l2 output: %s", V4L2_DEVICE)

    # YouTube livestream description updater
    _yt_updater = LivestreamDescriptionUpdater()

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
