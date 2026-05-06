"""Local music player daemon — watches selection, plays via pw-cat.

Selection JSON shape (written by `hapax-music-play <n>` CLI or any future
chat-handler / director path):

  {
    "ts": 1714082345.123,
    "path": "/abs/path/to/track.flac"        # local file
                  | "https://soundcloud.com/...",  # URL — yt-dlp pipes through
    "title": "Direct Drive",                       # optional, for splattribution
    "artist": "Dusty Decks",                       # optional
    "source": "operator-owned" | "found-sound" | "soundcloud-oudepode" | "local"
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
from typing import Any

from shared.affordance import ContentRisk
from shared.content_source_provenance_egress import (
    EgressGateDecision,
    EgressManifestGate,
    audio_asset_from_music_manifest,
    build_broadcast_manifest,
    write_broadcast_manifest,
)
from shared.music.provenance import (
    MusicManifestAsset,
    MusicProvenance,
    MusicTrackProvenance,
    classify_music_provenance,
    is_broadcast_safe,
    manifest_asset_from_provenance,
)
from shared.music_repo import DEFAULT_REPO_PATH, LocalMusicRepo
from shared.music_sources import (
    SOURCE_FOUND_SOUND,
    SOURCE_WWII_NEWSCLIP,
    is_decommissioned_broadcast_selection,
    normalize_source,
)

log = logging.getLogger("local_music_player")

DEFAULT_SELECTION_PATH = Path("/dev/shm/hapax-compositor/music-selection.json")
DEFAULT_ATTRIBUTION_PATH = Path("/dev/shm/hapax-compositor/music-attribution.txt")
DEFAULT_PROVENANCE_PATH = Path("/dev/shm/hapax-compositor/music-provenance.json")
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

# MPC Live III chain: hapax-music-loudnorm-playback (FL/FR) →
# MPC USB IN 1/2 (AUX0/AUX1). The continuous audio reconciler owns
# these links, but the music player also applies them at startup and
# track boundaries so a mid-session PipeWire restart does not leave
# music flowing into a dead loudnorm output while the reconciler catches up.
_MPC_OUTPUT = "alsa_output.usb-Akai_Professional_MPC_LIVE_III_B-00.multichannel-output"
_LOUDNORM_MPC_LINKS: tuple[tuple[str, str], ...] = (
    ("hapax-music-loudnorm-playback:output_FL", f"{_MPC_OUTPUT}:playback_AUX0"),
    ("hapax-music-loudnorm-playback:output_FR", f"{_MPC_OUTPUT}:playback_AUX1"),
)


# ── Config ──────────────────────────────────────────────────────────────────


@dataclass
class PlayerConfig:
    selection_path: Path = DEFAULT_SELECTION_PATH
    attribution_path: Path = DEFAULT_ATTRIBUTION_PATH
    provenance_path: Path = DEFAULT_PROVENANCE_PATH
    repo_path: Path = DEFAULT_REPO_PATH
    sc_repo_path: Path = Path.home() / "hapax-state" / "music-repo" / "soundcloud.jsonl"
    interstitial_repo_path: Path = (
        Path.home() / "hapax-state" / "music-repo" / "interstitials.jsonl"
    )
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
            provenance_path=Path(
                os.environ.get("HAPAX_MUSIC_PLAYER_PROVENANCE_PATH", str(DEFAULT_PROVENANCE_PATH))
            ),
            repo_path=Path(os.environ.get("HAPAX_MUSIC_PLAYER_REPO_PATH", str(DEFAULT_REPO_PATH))),
            sc_repo_path=Path(
                os.environ.get(
                    "HAPAX_MUSIC_PLAYER_SC_REPO_PATH",
                    str(Path.home() / "hapax-state" / "music-repo" / "soundcloud.jsonl"),
                )
            ),
            interstitial_repo_path=Path(
                os.environ.get(
                    "HAPAX_MUSIC_PLAYER_INTERSTITIAL_REPO_PATH",
                    str(Path.home() / "hapax-state" / "music-repo" / "interstitials.jsonl"),
                )
            ),
            poll_s=float(os.environ.get("HAPAX_MUSIC_PLAYER_POLL_S", DEFAULT_POLL_S)),
            sink=os.environ.get("HAPAX_MUSIC_PLAYER_SINK") or DEFAULT_SINK,
        )


# ── Pure helpers ────────────────────────────────────────────────────────────


def is_url(path: str) -> bool:
    """True when the path is an HTTP(S) URL — needs yt-dlp extraction."""
    return path.startswith(("http://", "https://"))


def format_attribution(
    title: str | None,
    artist: str | None,
    *,
    music_provenance: MusicProvenance | None = None,
) -> str:
    """Splattribution string for ``music-attribution.txt``.

    Empty parts collapse cleanly: missing artist + title gives empty
    string (which the album_overlay treats as no-op).
    """
    title = (title or "").strip()
    artist = (artist or "").strip()
    provenance_line = f"Provenance: {music_provenance}" if music_provenance else ""
    if title and artist:
        base = f"{title} — {artist}"
    else:
        base = title or artist
    if base and provenance_line:
        return f"{base}\n{provenance_line}"
    return base or provenance_line


def write_attribution(path: Path, text: str) -> None:
    """Atomic write so the album_overlay never reads a partial line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_music_provenance(path: Path, asset: MusicManifestAsset) -> None:
    """Atomic write of the current music asset for manifest consumers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(asset.model_dump_json(), encoding="utf-8")
    tmp.replace(path)


def write_selection(
    path: Path,
    track_path: str,
    *,
    title: str | None = None,
    artist: str | None = None,
    source: str | None = None,
    music_provenance: MusicProvenance | None = None,
    music_license: str | None = None,
    provenance_token: str | None = None,
    content_risk: ContentRisk | None = None,
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
        "music_provenance": music_provenance,
        "music_license": music_license,
        "provenance_token": provenance_token,
        "content_risk": content_risk,
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
        "48000",
        "-ac",
        "2",
        "pipe:1",
    ]
    pw = ["pw-cat", "--playback", "--target", sink]
    pw.extend(["--format", "s16", "--rate", "48000", "--channels", "2", "--raw", "-"])
    return yt, ffmpeg, pw


def _spawn_process(cmd: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
    return subprocess.Popen(cmd, **kwargs)  # noqa: S603 — fixed argv built above


def _ensure_loudnorm_mpc_links() -> None:
    """Idempotently create the loudnorm-playback → MPC USB link pair.

    The MPC Live III is the first-class content bus. If PipeWire restarts,
    the reconciler recreates these links continuously; the player applies
    the same desired edges as a fast local recovery path before playback.

    `pw-link` is idempotent: it returns success on a duplicate link
    request and we explicitly tolerate the "File exists" / "already
    linked" error class. Missing-port errors (the chain hasn't
    instantiated yet) are logged and skipped — the player will keep
    going; if the next track restart finds the chain healthy the
    link will succeed then.
    """
    for src, dst in _LOUDNORM_MPC_LINKS:
        try:
            result = subprocess.run(  # noqa: S603 — fixed argv
                ["pw-link", src, dst],  # noqa: S607 — pw-link from PATH
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning("pw-link %s -> %s failed to invoke: %s", src, dst, exc)
            continue
        if result.returncode == 0:
            log.info("ensured pipewire link: %s -> %s", src, dst)
            continue
        stderr = (result.stderr or "").strip().lower()
        if "file exists" in stderr or "already" in stderr:
            log.debug("pipewire link already present: %s -> %s", src, dst)
            continue
        # Missing ports (chain not yet instantiated) is the common
        # failure: the loudnorm/duck filter-chains live in pipewire
        # and may load lazily. Log + continue so the player still
        # boots; subsequent tick may see the chain alive.
        log.warning(
            "pw-link %s -> %s returned %s: %s",
            src,
            dst,
            result.returncode,
            stderr or "(no stderr)",
        )


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
        self._egress_gate = EgressManifestGate(producer_id="local_music_player")

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
            payload = json.loads(text)
        except (OSError, json.JSONDecodeError):
            log.debug("Failed to read selection at %s", path, exc_info=True)
            return None
        if not isinstance(payload, dict):
            return None
        nested = payload.get("selection")
        if isinstance(nested, dict) and "path" not in payload:
            merged = dict(nested)
            if "source" in payload and "source" not in merged:
                merged["selection_source"] = payload["source"]
            return merged
        return payload

    def _start_playback(self, selection: dict) -> None:
        track_path = selection.get("path")
        if not track_path or not isinstance(track_path, str):
            log.warning("selection missing/empty path; skipping")
            return
        title = selection.get("title")
        artist = selection.get("artist")
        source = selection.get("source")

        if is_decommissioned_broadcast_selection(track_path, source):
            log.warning("blocked decommissioned livestream music source: %s", track_path)
            try:
                write_attribution(self.config.attribution_path, "")
            except OSError:
                log.debug("attribution clear failed", exc_info=True)
            return

        manifest_asset = self._resolve_manifest_asset(selection)
        try:
            write_music_provenance(self.config.provenance_path, manifest_asset)
            decision = self._publish_and_gate_music_asset(manifest_asset)
        except OSError:
            log.warning("music provenance write failed; skipping track")
            try:
                write_attribution(self.config.attribution_path, "")
            except OSError:
                log.debug("attribution clear failed", exc_info=True)
            return

        if decision.kill_switch_fired:
            log.warning(
                "egress manifest gate fired; skipping track: %s",
                track_path,
            )
            try:
                write_attribution(self.config.attribution_path, "")
            except OSError:
                log.debug("attribution clear failed", exc_info=True)
            return

        if not manifest_asset.broadcast_safe:
            log.warning(
                "selection missing/unsafe music provenance; skipping track: %s",
                track_path,
            )
            try:
                write_attribution(self.config.attribution_path, "")
            except OSError:
                log.debug("attribution clear failed", exc_info=True)
            return

        # Splattribution write happens FIRST so the overlay updates even
        # if pw-cat fails to start. Empty string is a valid (no-op) value.
        try:
            write_attribution(
                self.config.attribution_path,
                format_attribution(
                    title,
                    artist,
                    music_provenance=manifest_asset.music_provenance,
                ),
            )
        except OSError:
            log.warning("attribution write failed", exc_info=True)

        sink = self.config.sink
        # Self-heal the music loudnorm → MPC link before each track.
        # Cheap and idempotent; catches a PipeWire restart mid-session
        # before the continuous reconciler's next tick.
        if sink == DEFAULT_SINK:
            _ensure_loudnorm_mpc_links()
        try:
            if is_url(track_path):
                yt_cmd, ffmpeg_cmd, pw_cmd = _build_url_pipeline(track_path, sink=sink)
                log.info(
                    "playing URL via yt-dlp → ffmpeg → pw-cat (sink=%s): %s",
                    sink,
                    track_path,
                )
                self._current_yt = _spawn_process(
                    yt_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
                )
                self._current_ffmpeg = _spawn_process(
                    ffmpeg_cmd,
                    stdin=self._current_yt.stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                self._current_proc = _spawn_process(
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
                self._current_proc = _spawn_process(cmd, stderr=subprocess.DEVNULL)
        except FileNotFoundError as exc:
            log.warning("playback tool missing (%s); skipping", exc)
            self._kill_current()
            return

        # Mark-played in the repo (best-effort; doesn't block playback).
        try:
            self._mark_played(track_path, source=source)
        except Exception:
            log.debug("mark_played failed for %s", track_path, exc_info=True)

    def _mark_played(self, track_path: str, *, source: str | None = None) -> None:
        # Local repo for filesystem paths, SC repo for URLs.
        source_norm = normalize_source(source)
        if is_url(track_path):
            repo_path = self.config.sc_repo_path
        elif source_norm in {SOURCE_FOUND_SOUND, SOURCE_WWII_NEWSCLIP}:
            repo_path = self.config.interstitial_repo_path
        else:
            repo_path = self.config.repo_path
        repo = LocalMusicRepo(path=repo_path)
        repo.load()
        repo.mark_played(track_path)

    def _repo_path_for_track(self, track_path: str, *, source: str | None = None) -> Path:
        source_norm = normalize_source(source)
        if is_url(track_path):
            return self.config.sc_repo_path
        if source_norm in {SOURCE_FOUND_SOUND, SOURCE_WWII_NEWSCLIP}:
            return self.config.interstitial_repo_path
        return self.config.repo_path

    def _lookup_track(self, track_path: str, *, source: str | None = None) -> object | None:
        repo = LocalMusicRepo(path=self._repo_path_for_track(track_path, source=source))
        repo.load()
        return next((track for track in repo.all_tracks() if track.path == track_path), None)

    def _resolve_manifest_asset(self, selection: dict) -> MusicManifestAsset:
        track_path = str(selection.get("path") or "")
        source = selection.get("source")
        source_str = str(source) if source is not None else None
        explicit_provenance = selection.get("music_provenance")
        explicit_token = selection.get("provenance_token")
        if explicit_provenance and explicit_token:
            content_risk = _content_risk_value(selection.get("content_risk")) or "tier_4_risky"
            provenance = str(explicit_provenance)
            record = MusicTrackProvenance(
                track_id=track_path,
                provenance=provenance,  # type: ignore[arg-type]
                license=selection.get("music_license"),
                source=source_str,
            )
            asset = manifest_asset_from_provenance(
                record,
                content_risk=content_risk,
                broadcast_safe=True,
                source=source_str,
            )
            return asset.model_copy(update={"token": str(explicit_token)})

        track = self._lookup_track(track_path, source=source_str)
        if track is not None:
            to_manifest = getattr(track, "to_manifest_asset", None)
            if callable(to_manifest):
                return to_manifest()

        music_provenance, music_license = classify_music_provenance(
            source=source_str,
            track_id=track_path,
            license=str(selection.get("music_license") or ""),
        )
        content_risk = _content_risk_value(selection.get("content_risk")) or "tier_4_risky"
        record = MusicTrackProvenance(
            track_id=track_path,
            provenance=music_provenance,
            license=music_license,
            source=source_str or "selection",
        )
        return manifest_asset_from_provenance(
            record,
            content_risk=content_risk,
            broadcast_safe=is_broadcast_safe(music_provenance),
            source=source_str or "selection",
        )

    def _publish_and_gate_music_asset(self, asset: MusicManifestAsset) -> EgressGateDecision:
        manifest = build_broadcast_manifest(
            audio_assets=(audio_asset_from_music_manifest(asset),),
        )
        write_broadcast_manifest(manifest, self._egress_gate.manifest_path)
        decision = self._egress_gate.tick(manifest)
        if decision is None:
            raise OSError("egress manifest gate did not return a decision")
        return decision

    def _enforce_egress_gate(self) -> bool:
        """Apply the latest broadcast manifest gate; return True when it fired."""

        try:
            decision = self._egress_gate.tick()
        except OSError:
            log.debug("egress manifest gate tick failed", exc_info=True)
            return False
        if decision is None or not decision.kill_switch_fired:
            return False
        self._kill_current()
        try:
            write_attribution(self.config.attribution_path, "")
        except OSError:
            log.debug("attribution clear failed", exc_info=True)
        return True

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
            music_provenance=track.music_provenance,
            music_license=track.music_license,
            provenance_token=track.provenance_token,
            content_risk=track.content_risk,
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
        if self._current_proc_alive() and self._enforce_egress_gate():
            return
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
        if is_decommissioned_broadcast_selection(
            str(selection.get("path") or ""), str(selection.get("source") or "")
        ):
            log.warning("selection uses decommissioned livestream music source; entering silence")
            self._silenced = True
            self._kill_current()
            try:
                write_attribution(self.config.attribution_path, "")
            except OSError:
                log.debug("attribution clear failed", exc_info=True)
            return
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
        # Self-heal the music loudnorm → MPC link. Safe to call repeatedly
        # (idempotent at the pw-link layer).
        if self.config.sink == DEFAULT_SINK:
            _ensure_loudnorm_mpc_links()
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


def _content_risk_value(raw: object) -> ContentRisk | None:
    allowed: set[str] = {
        "tier_0_owned",
        "tier_1_platform_cleared",
        "tier_2_provenance_known",
        "tier_3_uncertain",
        "tier_4_risky",
    }
    if raw is None:
        return None
    key = str(raw).strip().lower().replace("-", "_")
    if key in allowed:
        return key  # type: ignore[return-value]
    return None


if __name__ == "__main__":  # pragma: no cover — exercised via __main__.py
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    sys.exit(LocalMusicPlayer().run())
