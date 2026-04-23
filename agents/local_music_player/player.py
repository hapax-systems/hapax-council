"""Local music player daemon — watches selection, plays via pw-cat.

Selection JSON shape (written by `hapax-music-play <n>` CLI or any future
chat-handler / director path):

  {
    "ts": 1714082345.123,
    "path": "/abs/path/to/track.flac"        # local file
                  | "https://soundcloud.com/...",  # URL — yt-dlp pipes through
    "title": "Direct Drive",                       # optional, for splattribution
    "artist": "Dusty Decks",                       # optional
    "source": "operator-owned" | "epidemic" | "soundcloud-oudepode" | "local"
  }

Daemon behaviour:
- Inotify-style poll on the selection file mtime (1s tick — operator
  selection latency is human-scale; no need for inotify deps).
- On change: stop any currently-playing pw-cat, start new playback.
- Local file → ``pw-cat --playback --target <sink> <path>``.
- URL → ``yt-dlp -o - <url> | ffmpeg -f s16le -ar 44100 -ac 2 - | pw-cat --playback --target <sink> --raw …``.
- Sink default: ``hapax-pc-loudnorm`` (operator's loudness-normalizing
  PipeWire filter chain). Per the 2026-04-23 directive, every broadcast-
  bound music source MUST enter the normalization path. Override via
  ``HAPAX_MUSIC_PLAYER_SINK`` env when off-broadcast monitoring is
  required.
- Splattribution: write ``{title} - {artist}`` to
  ``/dev/shm/hapax-compositor/music-attribution.txt`` so the existing
  album_overlay ward picks it up.
- Mark-played: update the LocalMusicRepo via ``mark_played()`` so the
  recency cooldown advances.

Read-only on the broadcast graph: never modifies PipeWire links.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess  # noqa: S404 — pw-cat / yt-dlp are the only audio I/O paths
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from shared.music_repo import DEFAULT_REPO_PATH, LocalMusicRepo

log = logging.getLogger("local_music_player")

DEFAULT_SELECTION_PATH = Path("/dev/shm/hapax-compositor/music-selection.json")
DEFAULT_ATTRIBUTION_PATH = Path("/dev/shm/hapax-compositor/music-attribution.txt")
DEFAULT_POLL_S = 1.0
# Explicit default sink: the operator's loudness-normalizing PipeWire
# filter chain. Per the 2026-04-23 directive, EVERY broadcast-bound music
# source must enter the normalization path. We default to this sink by
# name so the routing is observable + auditable rather than implicit
# in pactl's get-default-sink (which can drift if user-default changes).
# Override via HAPAX_MUSIC_PLAYER_SINK env when off-broadcast monitoring
# is required.
DEFAULT_SINK = "hapax-pc-loudnorm"


# ── Config ──────────────────────────────────────────────────────────────────


@dataclass
class PlayerConfig:
    selection_path: Path = DEFAULT_SELECTION_PATH
    attribution_path: Path = DEFAULT_ATTRIBUTION_PATH
    repo_path: Path = DEFAULT_REPO_PATH
    sc_repo_path: Path = Path.home() / "hapax-state" / "music-repo" / "soundcloud.jsonl"
    poll_s: float = DEFAULT_POLL_S
    sink: str = DEFAULT_SINK

    @classmethod
    def from_env(cls) -> PlayerConfig:
        return cls(
            selection_path=Path(
                os.environ.get("HAPAX_MUSIC_PLAYER_SELECTION_PATH", str(DEFAULT_SELECTION_PATH))
            ),
            attribution_path=Path(
                os.environ.get("HAPAX_MUSIC_PLAYER_ATTRIBUTION_PATH", str(DEFAULT_ATTRIBUTION_PATH))
            ),
            poll_s=float(os.environ.get("HAPAX_MUSIC_PLAYER_POLL_S", DEFAULT_POLL_S)),
            sink=os.environ.get("HAPAX_MUSIC_PLAYER_SINK") or DEFAULT_SINK,
        )


# ── Pure helpers ────────────────────────────────────────────────────────────


def is_url(path: str) -> bool:
    """True when the path is an HTTP(S) URL — needs yt-dlp extraction."""
    return path.startswith(("http://", "https://"))


def format_attribution(title: str | None, artist: str | None) -> str:
    """Splattribution string for ``music-attribution.txt``.

    Empty parts collapse cleanly: missing artist + title gives empty
    string (which the album_overlay treats as no-op).
    """
    title = (title or "").strip()
    artist = (artist or "").strip()
    if title and artist:
        return f"{title} — {artist}"
    return title or artist


def write_attribution(path: Path, text: str) -> None:
    """Atomic write so the album_overlay never reads a partial line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_selection(
    path: Path,
    track_path: str,
    *,
    title: str | None = None,
    artist: str | None = None,
    source: str | None = None,
    when: float | None = None,
) -> None:
    """Write the selection JSON the player daemon watches.

    Used by the ``hapax-music-play`` CLI and any future chat-handler /
    director path.
    """
    payload = {
        "ts": when if when is not None else time.time(),
        "path": track_path,
        "title": title,
        "artist": artist,
        "source": source,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)


# ── pw-cat / yt-dlp invocation ──────────────────────────────────────────────


def _build_local_pwcat(path: str, *, sink: str) -> list[str]:
    return ["pw-cat", "--playback", "--target", sink, path]


def _build_url_pipeline(url: str, *, sink: str) -> tuple[list[str], list[str], list[str]]:
    """Returns (yt-dlp cmd, ffmpeg cmd, pw-cat cmd). Three-stage pipe.

    Earlier revision used yt-dlp ``-x --audio-format wav`` and fed the
    WAV bytes directly to pw-cat in --raw mode. pw-cat in --raw mode
    treats input as raw PCM and choked on the WAV header. Without
    --raw, pw-cat uses sndfile which requires a seekable file and
    rejects stdin entirely.

    Fix: yt-dlp pulls the original container (no -x conversion);
    ffmpeg decodes + downmixes to s16le 44.1k stereo raw PCM; pw-cat
    plays the raw stream into the requested sink. All three stages
    are pipeable — no intermediate temp files, latency stays low.
    """
    yt = ["yt-dlp", "--no-playlist", "--quiet", "-o", "-", url]
    ffmpeg = [
        "ffmpeg",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-f",
        "s16le",
        "-ar",
        "44100",
        "-ac",
        "2",
        "pipe:1",
    ]
    pw = ["pw-cat", "--playback", "--target", sink]
    pw.extend(["--format", "s16", "--rate", "44100", "--channels", "2", "--raw", "-"])
    return yt, ffmpeg, pw


# ── Daemon ──────────────────────────────────────────────────────────────────


class LocalMusicPlayer:
    """Daemon that watches selection.json + plays the selected track."""

    def __init__(self, config: PlayerConfig | None = None) -> None:
        self.config = config or PlayerConfig.from_env()
        self._last_mtime: float = 0.0
        self._current_proc: subprocess.Popen[bytes] | None = None
        self._current_yt: subprocess.Popen[bytes] | None = None
        self._current_ffmpeg: subprocess.Popen[bytes] | None = None
        self._stop = False

    def stop(self) -> None:
        """Stop any in-flight playback and exit the loop."""
        self._stop = True
        self._kill_current()

    def _kill_current(self) -> None:
        for proc in (self._current_proc, self._current_ffmpeg, self._current_yt):
            if proc is None:
                continue
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    proc.kill()
                except OSError:
                    pass
        self._current_proc = None
        self._current_ffmpeg = None
        self._current_yt = None

    def _read_selection(self) -> dict | None:
        path = self.config.selection_path
        if not path.is_file():
            return None
        try:
            text = path.read_text(encoding="utf-8")
            return json.loads(text)
        except (OSError, json.JSONDecodeError):
            log.debug("Failed to read selection at %s", path, exc_info=True)
            return None

    def _start_playback(self, selection: dict) -> None:
        track_path = selection.get("path")
        if not track_path or not isinstance(track_path, str):
            log.warning("selection missing/empty path; skipping")
            return
        title = selection.get("title")
        artist = selection.get("artist")

        # Splattribution write happens FIRST so the overlay updates even
        # if pw-cat fails to start. Empty string is a valid (no-op) value.
        try:
            write_attribution(self.config.attribution_path, format_attribution(title, artist))
        except OSError:
            log.warning("attribution write failed", exc_info=True)

        sink = self.config.sink
        try:
            if is_url(track_path):
                yt_cmd, ffmpeg_cmd, pw_cmd = _build_url_pipeline(track_path, sink=sink)
                log.info(
                    "playing URL via yt-dlp → ffmpeg → pw-cat (sink=%s): %s",
                    sink,
                    track_path,
                )
                self._current_yt = subprocess.Popen(  # noqa: S603 — fixed argv
                    yt_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
                )
                self._current_ffmpeg = subprocess.Popen(  # noqa: S603
                    ffmpeg_cmd,
                    stdin=self._current_yt.stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                self._current_proc = subprocess.Popen(  # noqa: S603
                    pw_cmd,
                    stdin=self._current_ffmpeg.stdout,
                    stderr=subprocess.DEVNULL,
                )
                # Allow upstream stages to receive SIGPIPE if a downstream stage exits.
                if self._current_yt.stdout is not None:
                    self._current_yt.stdout.close()
                if self._current_ffmpeg.stdout is not None:
                    self._current_ffmpeg.stdout.close()
            else:
                cmd = _build_local_pwcat(track_path, sink=sink)
                log.info("playing local file via pw-cat (sink=%s): %s", sink, track_path)
                self._current_proc = subprocess.Popen(  # noqa: S603
                    cmd, stderr=subprocess.DEVNULL
                )
        except FileNotFoundError as exc:
            log.warning("playback tool missing (%s); skipping", exc)
            self._kill_current()
            return

        # Mark-played in the repo (best-effort; doesn't block playback).
        try:
            self._mark_played(track_path)
        except Exception:
            log.debug("mark_played failed for %s", track_path, exc_info=True)

    def _mark_played(self, track_path: str) -> None:
        # Local repo for filesystem paths, SC repo for URLs.
        repo_path = self.config.sc_repo_path if is_url(track_path) else self.config.repo_path
        repo = LocalMusicRepo(path=repo_path)
        repo.load()
        repo.mark_played(track_path)

    def tick(self) -> None:
        """One poll: check selection, start playback if it changed."""
        path = self.config.selection_path
        try:
            mtime = path.stat().st_mtime if path.exists() else 0.0
        except OSError:
            mtime = 0.0
        if mtime == 0.0 or mtime == self._last_mtime:
            return
        self._last_mtime = mtime
        selection = self._read_selection()
        if selection is None:
            return
        self._kill_current()
        self._start_playback(selection)

    def run(self) -> int:
        log.info(
            "music player starting: selection=%s sink=%s poll=%.1fs",
            self.config.selection_path,
            self.config.sink,
            self.config.poll_s,
        )
        signal.signal(signal.SIGTERM, lambda *_: self.stop())
        signal.signal(signal.SIGINT, lambda *_: self.stop())
        while not self._stop:
            try:
                self.tick()
            except Exception:
                log.warning("tick failed", exc_info=True)
            for _ in range(int(self.config.poll_s * 10)):
                if self._stop:
                    break
                time.sleep(0.1)
        self._kill_current()
        return 0


if __name__ == "__main__":  # pragma: no cover — exercised via __main__.py
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    sys.exit(LocalMusicPlayer().run())
