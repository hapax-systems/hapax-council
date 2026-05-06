"""Audio output via PipeWire pw-cat subprocess.

Replaces PyAudio output which triggers assertion failures in
libportaudio.so under PipeWire (SIGABRT crash every few minutes).

Two interfaces:
- PwAudioOutput: persistent subprocess for high-frequency writes
  (conversation pipeline TTS playback)
- play_pcm(): one-shot blocking playback for infrequent use
  (chimes, samples, executor commands)
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Literal

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlaybackResult:
    """Structured outcome for one-shot ``pw-cat`` playback."""

    status: Literal["completed", "failed", "timeout", "spawn_failed"]
    returncode: int | None
    duration_s: float
    timeout_s: float
    target: str | None
    media_role: str
    error: str | None = None

    @property
    def completed(self) -> bool:
        return self.status == "completed"


def _pcm_duration_s(pcm: bytes, *, rate: int, channels: int) -> float:
    """Return raw int16 PCM duration in seconds."""
    if rate <= 0 or channels <= 0:
        return 0.0
    bytes_per_sample = 2
    n_samples = len(pcm) // (bytes_per_sample * channels)
    return n_samples / rate


def _playback_timeout_s(pcm: bytes, *, rate: int, channels: int) -> float:
    """Timeout long enough for the full audio plus process overhead."""
    duration_s = _pcm_duration_s(pcm, rate=rate, channels=channels)
    return duration_s + max(5.0, duration_s * 0.10)


class PwAudioOutput:
    """Persistent pw-cat playback subprocess, optionally per-target.

    Keeps a pw-cat --playback process alive per distinct PipeWire target
    sink and writes PCM to its stdin. Thread-safe. Auto-restarts any
    subprocess on death.

    The original constructor ``target`` defines the default sink — every
    ``write(pcm)`` with no per-call override flows there, preserving the
    legacy single-sink behavior callers already depend on. Callers that
    need per-utterance routing pass ``target=<sink>`` to ``write`` and
    the class spawns (and caches) a second subprocess dedicated to that
    sink. This is how CPAL's sidechat-private channel routes RIGHT
    without disturbing the livestream LEFT subprocess.
    """

    def __init__(
        self,
        sample_rate: int = 24000,
        channels: int = 1,
        target: str | None = None,
        media_role: str = "Assistant",
        idle_timeout_s: float | None = 60.0,
    ) -> None:
        self._rate = sample_rate
        self._channels = channels
        self._default_target = target
        self._default_media_role = media_role
        self._idle_timeout_s = idle_timeout_s
        # One subprocess per distinct (target, media_role) tuple.
        self._processes: dict[tuple[str | None, str], subprocess.Popen] = {}
        self._last_write_times: dict[tuple[str | None, str], float] = {}
        self._lock = threading.Lock()

        self._stop_event = threading.Event()
        if self._idle_timeout_s is not None and self._idle_timeout_s > 0:
            self._reaper_thread = threading.Thread(target=self._reaper_loop, daemon=True)
            self._reaper_thread.start()
        else:
            self._reaper_thread = None

    @property
    def default_target(self) -> str | None:
        """The target passed to ``__init__``. Used when ``write`` has no override."""
        return self._default_target

    @property
    def default_media_role(self) -> str:
        """The media_role passed to ``__init__``. Used when ``write`` has no override."""
        return self._default_media_role

    def _reaper_loop(self) -> None:
        """Daemon loop to kill pw-cat processes idle for > idle_timeout_s."""
        while not self._stop_event.is_set():
            self._stop_event.wait(5.0)
            if self._stop_event.is_set():
                break

            now = time.monotonic()
            with self._lock:
                # Need to use list() since we are modifying the dicts during iteration
                for key, last_write in list(self._last_write_times.items()):
                    if self._idle_timeout_s and (now - last_write) > self._idle_timeout_s:
                        proc = self._processes.pop(key, None)
                        self._last_write_times.pop(key, None)
                        if proc is not None:
                            try:
                                if proc.stdin:
                                    proc.stdin.close()
                            except Exception:
                                pass
                            try:
                                proc.terminate()
                                log.info(
                                    "Reaped idle pw-cat subprocess (target=%s, role=%s)",
                                    key[0],
                                    key[1],
                                )
                            except Exception:
                                pass

    def _ensure_process(self, target: str | None, media_role: str) -> subprocess.Popen | None:
        """Start or restart the pw-cat subprocess for ``(target, media_role)``.

        Must be called with ``self._lock`` held.
        """
        key = (target, media_role)
        existing = self._processes.get(key)
        if existing is not None and existing.poll() is None:
            return existing
        try:
            cmd = [
                "pw-cat",
                "--playback",
                "--raw",
                "--format",
                "s16",
                "--rate",
                str(self._rate),
                "--channels",
                str(self._channels),
                # ``--media-role`` selects the WirePlumber role-based
                # loopback the stream lands in. ``Assistant`` is the
                # legacy ducker hook (50-hapax-voice-duck.conf,
                # linking.role-based.duck-level=0.3). ``Broadcast`` is
                # the 2026-04-26 split that lets livestream-classified
                # clips route through their own loopback chain to
                # broadcast WHILE private clips stay on Assistant
                # (operator monitor). Without per-call role override,
                # both classifications share one role and wireplumber
                # has to pick a single target — see
                # ``feedback_l12_equals_livestream_invariant`` +
                # ``interpersonal_transparency`` tension.
                "--media-role",
                media_role,
            ]
            # 2026-05-05: Do NOT pass --target when media_role is
            # "Broadcast". WirePlumber's role-based loopback
            # (loopback.sink.role.broadcast) already has
            # preferred-target = hapax-voice-fx-capture. Passing
            # --target simultaneously creates a SECOND direct link to
            # the same node, and PipeWire's mixer sums both paths =
            # +6dB transient spike every time WirePlumber re-evaluates
            # routing policy. This was the root cause of the recurring
            # broadcast crackle.
            if target and media_role != "Broadcast":
                cmd.extend(["--target", target])
            cmd.append("-")
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._processes[key] = proc
            log.info(
                "pw-cat playback started (pid=%d, rate=%d, target=%s, role=%s)",
                proc.pid,
                self._rate,
                target or "<default>",
                media_role,
            )
            return proc
        except FileNotFoundError:
            log.error("pw-cat not found — install pipewire")
            return None
        except Exception as exc:
            log.warning(
                "Failed to start pw-cat playback (target=%s, role=%s): %s",
                target,
                media_role,
                exc,
            )
            return None

    def write(
        self,
        pcm: bytes,
        *,
        target: str | None = None,
        media_role: str | None = None,
    ) -> None:
        """Write PCM data to the playback stream. Thread-safe, blocking.

        Sleeps for the audio duration after writing so callers experience
        real-time pacing (matching PyAudio's blocking stream.write behavior).
        Without this, all sentences dump into pw-cat's pipe buffer at once
        and play back-to-back with no gaps.

        ``target`` overrides the constructor default for this call only.
        ``media_role`` overrides the constructor default for this call only.
        The subprocess for the resolved ``(target, media_role)`` tuple is
        spawned lazily and cached for subsequent writes to the same combo.
        Omit both (or pass ``None``) to keep the legacy single-sink
        single-role behavior.
        """
        # Calculate audio duration before acquiring lock
        duration_s = _pcm_duration_s(pcm, rate=self._rate, channels=self._channels)

        resolved_target = target if target is not None else self._default_target
        resolved_role = media_role if media_role is not None else self._default_media_role
        key = (resolved_target, resolved_role)

        with self._lock:
            proc = self._ensure_process(resolved_target, resolved_role)
            if proc is None or proc.stdin is None:
                return
            try:
                proc.stdin.write(pcm)
                proc.stdin.flush()
                self._last_write_times[key] = time.monotonic()
            except BrokenPipeError:
                log.warning(
                    "pw-cat playback pipe broken (target=%s, role=%s) — restarting",
                    resolved_target or "<default>",
                    resolved_role,
                )
                self._processes.pop(key, None)
                proc = self._ensure_process(resolved_target, resolved_role)
                if proc is not None and proc.stdin is not None:
                    try:
                        proc.stdin.write(pcm)
                        proc.stdin.flush()
                        self._last_write_times[key] = time.monotonic()
                    except Exception:
                        log.warning(
                            "pw-cat retry failed (target=%s, role=%s)",
                            resolved_target,
                            resolved_role,
                        )
                        return

        # Block for audio duration — paces sentence delivery
        if duration_s > 0:
            time.sleep(duration_s)

    def stop_stream(self) -> None:
        """No-op for API compatibility with PyAudio streams."""

    def close(self) -> None:
        """Terminate every pw-cat subprocess."""
        self._stop_event.set()
        with self._lock:
            for key, proc in list(self._processes.items()):
                try:
                    if proc.stdin is not None:
                        proc.stdin.close()
                except Exception:
                    pass
                try:
                    proc.terminate()
                    proc.wait(timeout=3)
                except Exception:
                    pass
                self._processes.pop(key, None)


def play_pcm(
    pcm: bytes,
    rate: int = 24000,
    channels: int = 1,
    target: str | None = None,
    media_role: str = "Assistant",
) -> PlaybackResult:
    """One-shot blocking PCM playback via pw-cat.

    Spawns a pw-cat process, writes all PCM, waits for completion.
    Use for infrequent playback (chimes, samples). For high-frequency
    writes, use PwAudioOutput instead.
    """
    duration_s = _pcm_duration_s(pcm, rate=rate, channels=channels)
    timeout_s = _playback_timeout_s(pcm, rate=rate, channels=channels)
    try:
        cmd = [
            "pw-cat",
            "--playback",
            "--raw",
            "--format",
            "s16",
            "--rate",
            str(rate),
            "--channels",
            str(channels),
            # See PwAudioOutput._ensure_process — same role-based
            # ducker dependency. play_pcm() handles chimes/samples,
            # which the operator hears alongside bed music; tagging
            # them as Assistant lets the duck fire for those too.
            # Callers pass ``media_role="Notification"`` for chime
            # playback, ``"Broadcast"`` for livestream samples.
            "--media-role",
            media_role,
        ]
        # See _ensure_process comment — same double-path prevention.
        if target and media_role != "Broadcast":
            cmd.extend(["--target", target])
        cmd.append("-")
        result = subprocess.run(
            cmd,
            input=pcm,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_s,
            check=False,
        )
        if result.returncode == 0:
            return PlaybackResult(
                status="completed",
                returncode=result.returncode,
                duration_s=duration_s,
                timeout_s=timeout_s,
                target=target,
                media_role=media_role,
            )
        return PlaybackResult(
            status="failed",
            returncode=result.returncode,
            duration_s=duration_s,
            timeout_s=timeout_s,
            target=target,
            media_role=media_role,
            error=f"pw-cat exited with returncode {result.returncode}",
        )
    except FileNotFoundError:
        log.error("pw-cat not found — install pipewire")
        return PlaybackResult(
            status="spawn_failed",
            returncode=None,
            duration_s=duration_s,
            timeout_s=timeout_s,
            target=target,
            media_role=media_role,
            error="pw-cat not found",
        )
    except subprocess.TimeoutExpired:
        log.warning("pw-cat playback timed out")
        return PlaybackResult(
            status="timeout",
            returncode=None,
            duration_s=duration_s,
            timeout_s=timeout_s,
            target=target,
            media_role=media_role,
            error=f"pw-cat playback timed out after {timeout_s:.3f}s",
        )
    except Exception as exc:
        log.warning("pw-cat playback failed: %s", exc)
        return PlaybackResult(
            status="failed",
            returncode=None,
            duration_s=duration_s,
            timeout_s=timeout_s,
            target=target,
            media_role=media_role,
            error=str(exc),
        )
