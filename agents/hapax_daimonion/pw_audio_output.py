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
    """Persistent pw-cat playback subprocess.

    Keeps a single pw-cat --playback process alive and writes PCM
    to its stdin. Thread-safe. Auto-restarts on subprocess death.
    """

    def __init__(
        self, sample_rate: int = 24000, channels: int = 1, target: str | None = None
    ) -> None:
        self._rate = sample_rate
        self._channels = channels
        self._target = target
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def _ensure_process(self) -> subprocess.Popen | None:
        """Start or restart the pw-cat subprocess."""
        if self._process is not None and self._process.poll() is None:
            return self._process
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
            if self._target:
                cmd.extend(["--target", self._target])
            cmd.append("-")
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log.info("pw-cat playback started (pid=%d, rate=%d)", self._process.pid, self._rate)
            return self._process
        except FileNotFoundError:
            log.error("pw-cat not found — install pipewire")
            return None
        except Exception as exc:
            log.warning("Failed to start pw-cat playback: %s", exc)
            return None

    def write(self, pcm: bytes) -> None:
        """Write PCM data to the playback stream. Thread-safe, blocking.

        Sleeps for the audio duration after writing so callers experience
        real-time pacing (matching PyAudio's blocking stream.write behavior).
        Without this, all sentences dump into pw-cat's pipe buffer at once
        and play back-to-back with no gaps.
        """
        # Calculate audio duration before acquiring lock
        bytes_per_sample = 2  # int16
        n_samples = len(pcm) // (bytes_per_sample * self._channels)
        duration_s = n_samples / self._rate if self._rate > 0 else 0.0

        with self._lock:
            proc = self._ensure_process()
            if proc is None or proc.stdin is None:
                return
            try:
                proc.stdin.write(pcm)
                proc.stdin.flush()
            except BrokenPipeError:
                log.warning("pw-cat playback pipe broken — restarting")
                self._process = None
                proc = self._ensure_process()
                if proc is not None and proc.stdin is not None:
                    try:
                        proc.stdin.write(pcm)
                        proc.stdin.flush()
                    except Exception:
                        log.warning("pw-cat retry failed")
                        return

        # Block for audio duration — paces sentence delivery
        if duration_s > 0:
            time.sleep(duration_s)

    def stop_stream(self) -> None:
        """No-op for API compatibility with PyAudio streams."""

    def close(self) -> None:
        """Terminate the pw-cat subprocess."""
        with self._lock:
            if self._process is not None:
                try:
                    self._process.stdin.close()
                except Exception:
                    pass
                try:
                    self._process.terminate()
                    self._process.wait(timeout=3)
                except Exception:
                    pass
                self._process = None


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
