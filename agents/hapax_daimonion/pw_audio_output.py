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

log = logging.getLogger(__name__)


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

    # Idle subprocesses are reaped after this many seconds without a
    # write. A persistent pw-cat that's connected to PipeWire but not
    # being fed will accumulate one xrun per quantum cycle (the audio
    # graph asks for samples and gets none from the empty stdin pipe).
    # In aggregate across many roles/targets these starved streams
    # apply real-time scheduling pressure to OTHER nodes on the graph,
    # observable as periodic dropouts on USB capture/playback paths
    # (the L-12 USB output was the canary on 2026-04-27 — three TTS
    # playback streams accumulated 100k–240k xrun errors each over
    # ~25 minutes of intermittent activity, peaking under load avg 14+
    # while studio-compositor was at 250-380% CPU). Re-spawn cost on
    # the next write is ~50ms — acceptable trade vs. continuous xrun
    # accumulation. Set to ``0`` to disable the reaper (legacy behavior).
    DEFAULT_IDLE_TIMEOUT_S: float = 60.0

    # How often the background thread wakes to check idle subprocesses.
    # Cheap because it just walks ``self._processes`` under the lock.
    _REAPER_TICK_S: float = 15.0

    def __init__(
        self,
        sample_rate: int = 24000,
        channels: int = 1,
        target: str | None = None,
        media_role: str = "Assistant",
        idle_timeout_s: float | None = None,
    ) -> None:
        self._rate = sample_rate
        self._channels = channels
        self._default_target = target
        self._default_media_role = media_role
        self._idle_timeout_s = (
            idle_timeout_s if idle_timeout_s is not None else self.DEFAULT_IDLE_TIMEOUT_S
        )
        # One subprocess per distinct (target, media_role) tuple. ``None``
        # in the target slot keys the "no --target" invocation, which
        # pw-cat routes via the system default sink. The media_role is
        # part of the cache key so private (role=Assistant) and broadcast
        # (role=Broadcast) clips can route through different role-based
        # loopback chains simultaneously without sharing a subprocess.
        self._processes: dict[tuple[str | None, str], subprocess.Popen] = {}
        # Last-write timestamp per ``(target, media_role)`` key. The
        # reaper terminates any subprocess whose key has been idle for
        # longer than ``self._idle_timeout_s``.
        self._last_write_at: dict[tuple[str | None, str], float] = {}
        self._lock = threading.Lock()
        self._reaper_stop = threading.Event()
        if self._idle_timeout_s > 0:
            self._reaper_thread: threading.Thread | None = threading.Thread(
                target=self._reaper_loop,
                name="pw-audio-reaper",
                daemon=True,
            )
            self._reaper_thread.start()
        else:
            self._reaper_thread = None

    def _reaper_loop(self) -> None:
        """Background reaper — terminate idle pw-cat subprocesses.

        Idle is defined as no ``write()`` for ``self._idle_timeout_s``
        seconds. The next write to that ``(target, media_role)`` key
        re-spawns the subprocess via ``_ensure_process``.
        """
        while not self._reaper_stop.wait(self._REAPER_TICK_S):
            self._reap_idle()

    def _reap_idle(self) -> None:
        """Terminate subprocesses idle longer than ``self._idle_timeout_s``."""
        now = time.monotonic()
        with self._lock:
            stale_keys = [
                key
                for key in list(self._processes)
                if now - self._last_write_at.get(key, now) > self._idle_timeout_s
            ]
            for key in stale_keys:
                proc = self._processes.pop(key, None)
                self._last_write_at.pop(key, None)
                if proc is None:
                    continue
                try:
                    if proc.stdin is not None:
                        proc.stdin.close()
                except Exception:
                    pass
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                log.info(
                    "pw-cat playback reaped (idle > %.0fs, target=%s, role=%s)",
                    self._idle_timeout_s,
                    key[0] or "<default>",
                    key[1],
                )

    @property
    def default_target(self) -> str | None:
        """The target passed to ``__init__``. Used when ``write`` has no override."""
        return self._default_target

    @property
    def default_media_role(self) -> str:
        """The media_role passed to ``__init__``. Used when ``write`` has no override."""
        return self._default_media_role

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
            if target:
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
        bytes_per_sample = 2  # int16
        n_samples = len(pcm) // (bytes_per_sample * self._channels)
        duration_s = n_samples / self._rate if self._rate > 0 else 0.0

        resolved_target = target if target is not None else self._default_target
        resolved_role = media_role if media_role is not None else self._default_media_role
        key = (resolved_target, resolved_role)

        with self._lock:
            proc = self._ensure_process(resolved_target, resolved_role)
            if proc is None or proc.stdin is None:
                return
            self._last_write_at[key] = time.monotonic()
            try:
                proc.stdin.write(pcm)
                proc.stdin.flush()
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
        self._reaper_stop.set()
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
            self._last_write_at.clear()


def play_pcm(
    pcm: bytes,
    rate: int = 24000,
    channels: int = 1,
    target: str | None = None,
    media_role: str = "Assistant",
) -> None:
    """One-shot blocking PCM playback via pw-cat.

    Spawns a pw-cat process, writes all PCM, waits for completion.
    Use for infrequent playback (chimes, samples). For high-frequency
    writes, use PwAudioOutput instead.
    """
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
        if target:
            cmd.extend(["--target", target])
        cmd.append("-")
        subprocess.run(
            cmd,
            input=pcm,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
    except FileNotFoundError:
        log.error("pw-cat not found — install pipewire")
    except subprocess.TimeoutExpired:
        log.warning("pw-cat playback timed out")
    except Exception as exc:
        log.warning("pw-cat playback failed: %s", exc)
