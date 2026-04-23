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
# Explicit default sink: the music-mastering-style loudness normalizer
# (config/pipewire/hapax-music-loudnorm.conf). Earlier revision pointed
# at hapax-pc-loudnorm, which is tuned for diverse PC audio (browser,
# games, notifications) and pumped audibly on music drum transients
# (operator observation 2026-04-23 on UNKNOWNTRON: "big pumping").
#
# hapax-music-loudnorm uses gentle, transient-preserving compression:
# threshold -6 dB, ratio 1.5:1, attack 30ms, release 800ms — preserves
# the mastered dynamics of the source. Both sinks land on the same
# L-12 USB return downstream; the only difference is the dynamics
# treatment.
#
# Per the 2026-04-23 directive, EVERY broadcast-bound music source
# enters the normalization path — this sink IS the music path.
# Override via HAPAX_MUSIC_PLAYER_SINK env when off-broadcast
# monitoring is required.
DEFAULT_SINK = "hapax-music-loudnorm"


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

    def __init__(
        self,
        config: PlayerConfig | None = None,
        *,
        programmer: object | None = None,
    ) -> None:
        self.config = config or PlayerConfig.from_env()
        self._last_mtime: float = 0.0
        self._current_proc: subprocess.Popen[bytes] | None = None
        self._current_yt: subprocess.Popen[bytes] | None = None
        self._current_ffmpeg: subprocess.Popen[bytes] | None = None
        self._stop = False
        # Programmer drives continuous-play. None disables auto-next
        # (Phase 4a behavior). Typed as `object` to keep player.py
        # importable when the programmer module is partially deployed;
        # runtime duck-types via getattr.
        self._programmer = programmer
        # Programming-silence latch: when True, do NOT auto-recruit
        # next track. Set by reading `{"stop": true}` from selection
        # file; cleared when a non-stop selection arrives.
        self._silenced = False
        # Track which selection-mtime came from our own auto-recruit
        # write so we can distinguish that from external overrides
        # (chat / Hapax cue / operator command) when recording plays.
        self._auto_written_mtime: float = 0.0

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

    def _current_proc_alive(self) -> bool:
        """True when the current playback chain is still producing audio.

        We probe pw-cat (the final stage); if it's gone, the track has
        ended (or upstream pipeline died). Used for continuous-play
        auto-recruitment.
        """
        if self._current_proc is None:
            return False
        try:
            return self._current_proc.poll() is None
        except OSError:
            return False

    def _maybe_auto_recruit(self) -> None:
        """When the current track has ended and we're not silenced,
        ask the programmer for the next track and write it.

        No-op when:
        - No programmer configured (Phase 4a behavior preserved).
        - Operator/Hapax wrote `{"stop": true}` and we're silenced.
        - A track is still playing.
        """
        if self._programmer is None:
            return
        if self._silenced:
            return
        if self._current_proc_alive():
            return
        select = getattr(self._programmer, "select_next", None)
        if select is None:
            return
        try:
            track = select()
        except Exception:
            log.warning("programmer.select_next() raised", exc_info=True)
            return
        if track is None:
            log.debug("programmer returned no track; idle")
            return
        log.info(
            "auto-recruiting next track: %s — %s (source=%s)",
            track.title,
            track.artist,
            track.source,
        )
        write_selection(
            self.config.selection_path,
            track.path,
            title=track.title,
            artist=track.artist,
            source=track.source,
        )
        # Mark this write as ours so the next tick recognizes it as
        # programmer-authored rather than external.
        try:
            self._auto_written_mtime = self.config.selection_path.stat().st_mtime
        except OSError:
            self._auto_written_mtime = 0.0

    def tick(self) -> None:
        """One poll: check selection, start playback if it changed.

        Order matters:

        1. Read current selection mtime. If it changed, an external
           write happened (chat / Hapax cue / operator command) — process
           that FIRST so we don't clobber it with auto-recruit.
        2. If no external change AND no track playing AND not silenced,
           ask the programmer for the next track. The programmer's write
           changes mtime, which the next tick picks up as a normal
           selection change.

        Continuous-play (Phase 4b): when an auto-recruit-eligible state
        is detected, the programmer writes selection.json; the SAME tick
        below sees the new mtime and dispatches playback.
        """
        path = self.config.selection_path
        try:
            current_mtime = path.stat().st_mtime if path.exists() else 0.0
        except OSError:
            current_mtime = 0.0

        # Only auto-recruit when nothing has changed since last tick.
        # External writes always take precedence.
        if current_mtime == self._last_mtime:
            self._maybe_auto_recruit()
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
        # Stop signal: `{"stop": true}` halts auto-recruitment until a
        # non-stop selection arrives. Operator/Hapax uses this for
        # programming-silence segments.
        if selection.get("stop") is True:
            log.info("stop signal received; entering silence")
            self._silenced = True
            self._kill_current()
            try:
                write_attribution(self.config.attribution_path, "")
            except OSError:
                log.debug("attribution clear failed", exc_info=True)
            return
        # Non-stop selection — leave silence (if any).
        self._silenced = False
        # Distinguish programmer-authored writes from external overrides.
        # When auto-recruit just wrote, this mtime equals _auto_written_mtime
        # and we record by="programmer". Otherwise (chat / Hapax cue /
        # operator), record by="external" so the rotation budget honors it.
        by = "programmer" if mtime == self._auto_written_mtime else "external"
        # Programmer.record_play observes the upcoming play so cap math
        # advances even for external overrides.
        if self._programmer is not None:
            record = getattr(self._programmer, "record_play", None)
            if record is not None:
                try:
                    record(
                        path=str(selection.get("path", "")),
                        title=selection.get("title"),
                        artist=selection.get("artist"),
                        source=str(selection.get("source") or "local"),
                        by=by,
                    )
                except Exception:
                    log.warning("programmer.record_play() raised", exc_info=True)
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
