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

    def __init__(
        self, sample_rate: int = 24000, channels: int = 1, target: str | None = None
    ) -> None:
        self._rate = sample_rate
        self._channels = channels
        self._default_target = target
        # One subprocess per distinct target. ``None`` keys the "no --target"
        # invocation, which pw-cat routes via the system default sink.
        self._processes: dict[str | None, subprocess.Popen] = {}
        self._lock = threading.Lock()

    @property
    def default_target(self) -> str | None:
        """The target passed to ``__init__``. Used when ``write`` has no override."""
        return self._default_target

    def _ensure_process(self, target: str | None) -> subprocess.Popen | None:
        """Start or restart the pw-cat subprocess for ``target``.

        Must be called with ``self._lock`` held.
        """
        existing = self._processes.get(target)
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
            self._processes[target] = proc
            log.info(
                "pw-cat playback started (pid=%d, rate=%d, target=%s)",
                proc.pid,
                self._rate,
                target or "<default>",
            )
            return proc
        except FileNotFoundError:
            log.error("pw-cat not found — install pipewire")
            return None
        except Exception as exc:
            log.warning("Failed to start pw-cat playback (target=%s): %s", target, exc)
            return None

    def write(self, pcm: bytes, *, target: str | None = None) -> None:
        """Write PCM data to the playback stream. Thread-safe, blocking.

        Sleeps for the audio duration after writing so callers experience
        real-time pacing (matching PyAudio's blocking stream.write behavior).
        Without this, all sentences dump into pw-cat's pipe buffer at once
        and play back-to-back with no gaps.

        ``target`` overrides the constructor default for this call only.
        The subprocess for the resolved target is spawned lazily and cached
        for subsequent writes to the same sink. Omit (or pass ``None``) to
        keep the legacy single-sink behavior.
        """
        # Calculate audio duration before acquiring lock
        bytes_per_sample = 2  # int16
        n_samples = len(pcm) // (bytes_per_sample * self._channels)
        duration_s = n_samples / self._rate if self._rate > 0 else 0.0

        resolved_target = target if target is not None else self._default_target

        with self._lock:
            proc = self._ensure_process(resolved_target)
            if proc is None or proc.stdin is None:
                return
            try:
                proc.stdin.write(pcm)
                proc.stdin.flush()
            except BrokenPipeError:
                log.warning(
                    "pw-cat playback pipe broken (target=%s) — restarting",
                    resolved_target or "<default>",
                )
                self._processes.pop(resolved_target, None)
                proc = self._ensure_process(resolved_target)
                if proc is not None and proc.stdin is not None:
                    try:
                        proc.stdin.write(pcm)
                        proc.stdin.flush()
                    except Exception:
                        log.warning("pw-cat retry failed (target=%s)", resolved_target)
                        return

        # Block for audio duration — paces sentence delivery
        if duration_s > 0:
            time.sleep(duration_s)

    def stop_stream(self) -> None:
        """No-op for API compatibility with PyAudio streams."""

    def close(self) -> None:
        """Terminate every pw-cat subprocess."""
        with self._lock:
            for target, proc in list(self._processes.items()):
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
                self._processes.pop(target, None)


def play_pcm(pcm: bytes, rate: int = 24000, channels: int = 1, target: str | None = None) -> None:
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
