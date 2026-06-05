"""Egress loopback witness producer.

Captures int16 PCM from the broadcast egress source via ``parec``,
computes RMS / peak / silence_ratio over a fixed window, and writes a
fresh :class:`~shared.broadcast_audio_health.EgressLoopbackWitness`
JSON atomically (tmp+rename) to
``/dev/shm/hapax-broadcast/egress-loopback.json``.

Pure-stdlib audio path (subprocess + struct/array): the project's
"bare implementation" pattern from the receive-only rails. No PyAudio,
no librosa — just ``parec`` and ``array.array`` for byte→sample
conversion. ``math.sqrt`` for RMS, ``math.log10`` for dBFS.

The producer is safe to restart at any time. Writes go through
:func:`write_witness_atomic` which atomically renames a tmp file in
the same directory, so the witness file is never observed in a
half-written state by the evaluator.

On parec failure (sink missing, exit non-zero, short read) the producer
still writes a witness with the ``error`` field populated — the
evaluator treats producer-reported errors as blocking conditions, so
the operator surfaces a structured cause rather than file-staleness.
"""

from __future__ import annotations

import array
import logging
import math
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Condition, Thread
from typing import Final

from shared.broadcast_audio_health import (
    DEFAULT_EGRESS_LOOPBACK_WITNESS,
    EgressLoopbackQuality,
    EgressLoopbackWitness,
)

log = logging.getLogger(__name__)


#: The broadcast egress source the producer probes. Matches the OBS
#: binding requirement documented in
#: ``config/pipewire/hapax-broadcast-master.conf``: "OBS audio source
#: MUST bind to ``hapax-broadcast-normalized``". Probing the same
#: source the broadcast actually consumes is the only way to witness
#: that egress is live — probing further upstream would miss
#: limiter / chain breakage.
DEFAULT_BROADCAST_SOURCE: Final[str] = "hapax-broadcast-normalized"

#: Sampling window length. The evaluator's ``loopback_max_age_s`` is
#: 60s by default; a 5s window gives plenty of bin-width signal for
#: RMS/silence detection while leaving 12x freshness headroom.
DEFAULT_WINDOW_SECONDS: Final[float] = 5.0

#: Tick interval between witness writes. 1s is well under the
#: evaluator's 60s freshness threshold and keeps state-machine
#: latency tight when the broadcast actually drops.
DEFAULT_TICK_SECONDS: Final[float] = 1.0

#: Capture sample rate. Matches the live broadcast PipeWire graph.
DEFAULT_SAMPLE_RATE_HZ: Final[int] = 48000

DEFAULT_CHANNELS: Final[int] = 2
DEFAULT_PERSISTENT_LATENCY_MSEC: Final[int] = 100
DEFAULT_PERSISTENT_BUFFER_S: Final[float] = 15.0

#: Silence floor in dBFS. Samples below this contribute to the
#: silence_ratio numerator. -60 dBFS is well below typical room
#: noise yet above the int16 quantisation floor (~-90 dBFS), so a
#: signal-free monitor (digital silence + quant noise) reads ratio≈1.
SILENCE_FLOOR_DBFS: Final[float] = -60.0

#: Subprocess timeout for parec — generous so a slow PipeWire warmup
#: does not error-out the witness write.
PAREC_TIMEOUT_S: Final[float] = 10.0

#: Default witness path. Re-exported from
#: :mod:`shared.broadcast_audio_health` so the evaluator and producer
#: agree on a single location.
DEFAULT_WITNESS_PATH: Final[Path] = DEFAULT_EGRESS_LOOPBACK_WITNESS


@dataclass(frozen=True)
class LoopbackSample:
    """One window's worth of computed metrics."""

    rms_dbfs: float
    peak_dbfs: float
    silence_ratio: float
    crest_factor_db: float | None
    zero_crossing_rate_hz: float
    quality: EgressLoopbackQuality
    quality_reasons: tuple[str, ...]


# Subprocess shell type: tests inject stubs that return synthetic mono
# PCM bytes so the suite never touches real PipeWire.
CaptureFn = Callable[[str, float, int], bytes]


def _default_capture(source: str, duration_s: float, sample_rate: int) -> bytes:
    """Capture ``duration_s`` seconds of int16 mono PCM via ``parec``.

    Returns the raw little-endian int16 byte buffer. Raises
    :class:`subprocess.CalledProcessError` on non-zero exit and
    :class:`RuntimeError` on short read (partial capture).

    Uses ``--device`` (not ``--monitor-of``) so the source name can be
    a virtual / loopback / remap source, not just a sink monitor.
    """
    n_samples = int(round(sample_rate * duration_s))
    n_bytes = n_samples * 2 * 2  # int16 = 2 bytes/sample, 2 channels
    cmd = [
        "parec",
        "--device",
        source,
        "--rate",
        str(sample_rate),
        "--channels",
        "2",
        "--format",
        "s16le",
        "--raw",
    ]
    proc = subprocess.Popen(  # noqa: S603 — args are an explicit list
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        assert proc.stdout is not None
        deadline = time.monotonic() + PAREC_TIMEOUT_S
        chunks: list[bytes] = []
        bytes_read = 0
        while bytes_read < n_bytes:
            remaining = n_bytes - bytes_read
            chunk = proc.stdout.read(remaining)
            if not chunk:
                break
            chunks.append(chunk)
            bytes_read += len(chunk)
            if time.monotonic() > deadline:
                break
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
    buf = b"".join(chunks)
    if len(buf) < n_bytes:
        # Drain stderr for a useful error message.
        err = b""
        if proc.stderr is not None:
            try:
                err = proc.stderr.read() or b""
            except Exception:  # noqa: BLE001 — best-effort drain
                pass
        raise RuntimeError(
            f"parec short read: got {len(buf)} of {n_bytes} bytes "
            f"(rc={proc.returncode}, stderr={err.decode(errors='replace')!r})"
        )
    # Downmix stereo to mono in software: average L+R per sample.
    # This avoids forcing PipeWire to inject a channelmix matrix,
    # which can transiently apply +6dB gain on stereo nodes.
    stereo = array.array("h")
    stereo.frombytes(buf[: len(buf) - (len(buf) % 4)])
    mono_buf = array.array(
        "h", [(stereo[i] + stereo[i + 1]) // 2 for i in range(0, len(stereo), 2)]
    )
    return mono_buf.tobytes()


class PersistentParecCapture:
    """Long-lived ``parec`` reader for the broadcast egress witness.

    The witness producer is itself a live-egress monitor, so it must not
    reconnect once per tick. This reader keeps one PipeWire stream attached,
    drains it into a bounded rolling buffer, and serves the latest window to
    the producer without causing repeated graph renegotiation.
    """

    def __init__(
        self,
        *,
        source: str,
        sample_rate: int = DEFAULT_SAMPLE_RATE_HZ,
        channels: int = DEFAULT_CHANNELS,
        max_buffer_s: float = DEFAULT_PERSISTENT_BUFFER_S,
        parec_path: str = "parec",
    ) -> None:
        if not source:
            raise ValueError("source must be non-empty")
        if sample_rate <= 0:
            raise ValueError("sample_rate must be > 0")
        if channels <= 0:
            raise ValueError("channels must be > 0")
        self.source = source
        self.sample_rate = sample_rate
        self.channels = channels
        self.parec_path = parec_path
        self.bytes_per_frame = 2 * channels
        raw_max_buffer_bytes = int(max_buffer_s * sample_rate * self.bytes_per_frame)
        self.max_buffer_bytes = max(
            4096,
            raw_max_buffer_bytes - (raw_max_buffer_bytes % self.bytes_per_frame),
        )
        self._condition = Condition()
        self._buffer = bytearray()
        self._error: str | None = None
        self._proc: subprocess.Popen[bytes] | None = None
        self._thread: Thread | None = None

    def capture(self, source: str, duration_s: float, sample_rate: int) -> bytes:
        """Return the latest mono PCM window from the persistent stream."""

        if source != self.source:
            raise ValueError(f"capture source changed from {self.source!r} to {source!r}")
        if sample_rate != self.sample_rate:
            raise ValueError(
                f"capture sample_rate changed from {self.sample_rate} to {sample_rate}"
            )
        if duration_s <= 0.0:
            raise ValueError(f"duration_s must be > 0; got {duration_s}")
        raw = self._read_window(duration_s)
        return _downmix_s16le_stereo_to_mono(raw, channels=self.channels)

    def start(self) -> None:
        """Start ``parec`` once, or restart it after an EOF/error."""

        with self._condition:
            if self._proc is not None and self._proc.poll() is None:
                return
            self._buffer.clear()
            self._error = None

        if shutil.which(self.parec_path) is None:
            raise FileNotFoundError(self.parec_path)

        cmd = [
            self.parec_path,
            "--device",
            self.source,
            "--rate",
            str(self.sample_rate),
            "--channels",
            str(self.channels),
            "--format",
            "s16le",
            "--latency-msec",
            str(DEFAULT_PERSISTENT_LATENCY_MSEC),
            "--raw",
        ]
        try:
            proc = subprocess.Popen(  # noqa: S603 - args are an explicit list
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except (FileNotFoundError, OSError) as exc:
            raise RuntimeError(f"parec spawn failed: {exc}") from exc

        thread = Thread(target=self._read_loop, name=f"parec:{self.source}", daemon=True)
        with self._condition:
            self._proc = proc
            self._thread = thread
        thread.start()

    def _read_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return

        try:
            while True:
                chunk = proc.stdout.read(8192)
                if not chunk:
                    break
                with self._condition:
                    self._buffer.extend(chunk)
                    overflow = len(self._buffer) - self.max_buffer_bytes
                    if overflow > 0:
                        del self._buffer[:overflow]
                    self._condition.notify_all()
        except OSError as exc:
            with self._condition:
                self._error = f"parec read failed from {self.source!r}: {exc}"
                self._condition.notify_all()
            return

        rc = proc.poll()
        with self._condition:
            if self._proc is proc and rc not in (None, 0):
                self._error = f"parec exited for {self.source!r} rc={rc}"
            elif self._proc is proc:
                self._error = f"parec ended for {self.source!r}"
            self._condition.notify_all()

    def _read_window(self, duration_s: float) -> bytes:
        self.start()
        raw_target_bytes = int(duration_s * self.sample_rate * self.bytes_per_frame)
        target_bytes = max(
            self.bytes_per_frame,
            raw_target_bytes - (raw_target_bytes % self.bytes_per_frame),
        )
        deadline = time.monotonic() + min(PAREC_TIMEOUT_S, duration_s + PAREC_TIMEOUT_S)

        with self._condition:
            while len(self._buffer) < target_bytes and self._error is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=min(0.1, remaining))

            if len(self._buffer) >= target_bytes:
                return bytes(self._buffer[-target_bytes:])

            if self._buffer:
                return bytes(self._buffer)

            error = self._error or "timed out waiting for persistent parec data"
            raise RuntimeError(error)

    def close(self) -> None:
        """Terminate the persistent ``parec`` child."""

        proc = self._proc
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
        except OSError:
            pass
        with self._condition:
            if self._proc is proc:
                self._proc = None
            self._condition.notify_all()


def _downmix_s16le_stereo_to_mono(raw: bytes, *, channels: int = DEFAULT_CHANNELS) -> bytes:
    """Downmix interleaved signed-16 PCM to mono signed-16 PCM."""

    samples = array.array("h")
    usable = len(raw) - (len(raw) % (2 * channels))
    samples.frombytes(raw[:usable])
    if channels <= 1:
        return samples.tobytes()
    mono = array.array(
        "h",
        [
            sum(samples[i + offset] for offset in range(channels)) // channels
            for i in range(0, len(samples), channels)
        ],
    )
    return mono.tobytes()


def compute_loopback_metrics(
    pcm_bytes: bytes,
    *,
    silence_floor_dbfs: float = SILENCE_FLOOR_DBFS,
    sample_rate: int = DEFAULT_SAMPLE_RATE_HZ,
) -> LoopbackSample:
    """Compute RMS dBFS / peak dBFS / silence_ratio from int16 PCM bytes.

    Pure stdlib: :class:`array.array` for byte unpacking, :mod:`math`
    for log/sqrt. No numpy dependency — keeps the producer's import
    cheap and matches the project's bare-implementation pattern for
    the receive-only audio rails.

    Conventions:
      - dBFS reference is full-scale int16 (32767). Digital silence
        returns ``-inf`` for RMS and peak; we clamp to -120 dBFS so
        the witness JSON stays finite.
      - silence_ratio counts samples whose absolute amplitude is
        below the silence_floor_dbfs threshold, divided by the total
        sample count. Empty/silent input returns 1.0.
      - peak is sample-wise abs max (not RMS-of-bin), per the
        evaluator's intuitive "loudest momentary sample" semantic.
    """
    if not pcm_bytes:
        return LoopbackSample(
            rms_dbfs=-120.0,
            peak_dbfs=-120.0,
            silence_ratio=1.0,
            crest_factor_db=None,
            zero_crossing_rate_hz=0.0,
            quality=EgressLoopbackQuality.UNKNOWN,
            quality_reasons=("empty PCM buffer",),
        )

    samples = array.array("h")  # signed short, native endian on Linux x86_64
    # array.frombytes requires len % itemsize == 0 — pad/truncate the
    # last partial sample if parec returned an odd byte count.
    usable = len(pcm_bytes) - (len(pcm_bytes) % 2)
    samples.frombytes(pcm_bytes[:usable])
    if not samples:
        return LoopbackSample(
            rms_dbfs=-120.0,
            peak_dbfs=-120.0,
            silence_ratio=1.0,
            crest_factor_db=None,
            zero_crossing_rate_hz=0.0,
            quality=EgressLoopbackQuality.UNKNOWN,
            quality_reasons=("no complete int16 samples",),
        )

    full_scale = 32767.0
    silence_threshold_amp = full_scale * (10.0 ** (silence_floor_dbfs / 20.0))

    sum_sq = 0.0
    peak_amp = 0
    silent_count = 0
    zero_crossings = 0
    last_sign = 0
    for s in samples:
        sum_sq += float(s) * float(s)
        a = abs(s)
        if a > peak_amp:
            peak_amp = a
        if a < silence_threshold_amp:
            silent_count += 1
        sign = 1 if s > 0 else -1 if s < 0 else 0
        if sign and last_sign and sign != last_sign:
            zero_crossings += 1
        if sign:
            last_sign = sign

    n = len(samples)
    rms_amp = math.sqrt(sum_sq / n)

    rms_dbfs = _safe_dbfs(rms_amp, full_scale)
    peak_dbfs = _safe_dbfs(float(peak_amp), full_scale)
    silence_ratio = silent_count / n
    crest_factor_db = peak_dbfs - rms_dbfs if peak_dbfs > -120.0 and rms_dbfs > -120.0 else None
    duration_s = n / sample_rate if sample_rate > 0 else 0.0
    zero_crossing_rate_hz = zero_crossings / duration_s if duration_s > 0.0 else 0.0
    quality, quality_reasons = classify_loopback_quality(
        rms_dbfs=rms_dbfs,
        peak_dbfs=peak_dbfs,
        silence_ratio=silence_ratio,
        crest_factor_db=crest_factor_db,
        zero_crossing_rate_hz=zero_crossing_rate_hz,
        silence_floor_dbfs=silence_floor_dbfs,
    )
    return LoopbackSample(
        rms_dbfs=rms_dbfs,
        peak_dbfs=peak_dbfs,
        silence_ratio=silence_ratio,
        crest_factor_db=crest_factor_db,
        zero_crossing_rate_hz=zero_crossing_rate_hz,
        quality=quality,
        quality_reasons=tuple(quality_reasons),
    )


def classify_loopback_quality(
    *,
    rms_dbfs: float,
    peak_dbfs: float,
    silence_ratio: float,
    crest_factor_db: float | None,
    zero_crossing_rate_hz: float,
    silence_floor_dbfs: float = SILENCE_FLOOR_DBFS,
) -> tuple[EgressLoopbackQuality, list[str]]:
    """Classify the captured egress window beyond link presence.

    RMS and silence ratio catch no-programme states. The added crest/ZCR
    checks catch the corrupt-capture class behind garbled OBS egress: lots of
    zero crossings with crushed dynamics, or near-full-scale flat clipping.
    """

    if rms_dbfs <= silence_floor_dbfs or silence_ratio >= 0.98:
        return (
            EgressLoopbackQuality.SILENCE,
            [f"rms {rms_dbfs:.1f} dBFS / silence_ratio {silence_ratio:.2f} indicates silence"],
        )

    reasons: list[str] = []
    if crest_factor_db is not None:
        if zero_crossing_rate_hz >= 8000.0 and crest_factor_db <= 4.0:
            reasons.append(
                f"high zero-crossing rate {zero_crossing_rate_hz:.0f} Hz "
                f"with low crest factor {crest_factor_db:.1f} dB"
            )
        if peak_dbfs >= -0.5 and crest_factor_db <= 3.0:
            reasons.append(
                f"near-full-scale peak {peak_dbfs:.1f} dBFS "
                f"with crushed crest factor {crest_factor_db:.1f} dB"
            )

    if reasons:
        return EgressLoopbackQuality.GARBLED, reasons

    return (
        EgressLoopbackQuality.NORMAL,
        [
            f"normal programme window: rms={rms_dbfs:.1f} dBFS, "
            f"peak={peak_dbfs:.1f} dBFS, zcr={zero_crossing_rate_hz:.0f} Hz"
        ],
    )


def _safe_dbfs(amp: float, full_scale: float) -> float:
    """20·log10(amp/full_scale), clamped to [-120, 0] dBFS."""
    if amp <= 0.0:
        return -120.0
    db = 20.0 * math.log10(amp / full_scale)
    if db < -120.0:
        return -120.0
    if db > 0.0:
        return 0.0
    return db


def write_witness_atomic(
    witness: EgressLoopbackWitness,
    path: Path,
) -> None:
    """Write witness JSON atomically (tmp file in same dir + rename).

    Atomic semantics rely on POSIX rename: the evaluator either reads
    the previous version or the new version, never a half-written
    file. The tmp file lives in the same directory so the rename is
    cross-link-safe.

    Creates the parent directory if missing — ``/dev/shm/hapax-broadcast``
    is a tmpfs path that may not exist on a fresh boot.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = witness.model_dump_json()
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


class EgressLoopbackProducer:
    """One-shot or looping witness producer.

    Construct with the source name + window length. Call
    :meth:`tick_once` per timer fire to capture, compute, and write a
    single witness. Call :meth:`run_forever` for a self-paced loop
    (1s tick by default).
    """

    def __init__(
        self,
        *,
        source: str = DEFAULT_BROADCAST_SOURCE,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        tick_seconds: float = DEFAULT_TICK_SECONDS,
        sample_rate: int = DEFAULT_SAMPLE_RATE_HZ,
        witness_path: Path = DEFAULT_WITNESS_PATH,
        capture: CaptureFn | None = None,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        if window_seconds <= 0.0:
            raise ValueError(f"window_seconds must be > 0; got {window_seconds}")
        if tick_seconds <= 0.0:
            raise ValueError(f"tick_seconds must be > 0; got {tick_seconds}")
        if not source:
            raise ValueError("source must be a non-empty PipeWire source name")
        self.source = source
        self.window_seconds = window_seconds
        self.tick_seconds = tick_seconds
        self.sample_rate = sample_rate
        self.witness_path = witness_path
        self._persistent_capture: PersistentParecCapture | None = None
        if capture is None:
            self._persistent_capture = PersistentParecCapture(
                source=source,
                sample_rate=sample_rate,
                max_buffer_s=max(DEFAULT_PERSISTENT_BUFFER_S, window_seconds * 3.0),
            )
            self._capture = self._persistent_capture.capture
        else:
            self._capture = capture
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleep = sleeper or time.sleep

    def close(self) -> None:
        """Close the persistent capture child when this producer owns one."""

        if self._persistent_capture is not None:
            self._persistent_capture.close()

    def tick_once(self) -> EgressLoopbackWitness:
        """Capture one window, compute metrics, write the witness, return it.

        On capture failure, writes a witness with the ``error`` field
        set to a structured ``parec_failed:<reason>`` token and
        zeroed metrics. The evaluator surfaces ``producer_error`` so
        the operator sees a real cause rather than a file-staleness
        cascade.
        """
        ts = self._clock().isoformat()
        try:
            pcm = self._capture(self.source, self.window_seconds, self.sample_rate)
        except FileNotFoundError as exc:
            # parec binary missing — distinct error class from sink missing.
            err = f"parec_missing:{exc!s}"
            log.error("egress loopback producer: %s", err)
            witness = _error_witness(
                checked_at=ts,
                window_seconds=self.window_seconds,
                target_sink=self.source,
                error=err,
            )
            write_witness_atomic(witness, self.witness_path)
            return witness
        except subprocess.CalledProcessError as exc:
            err = f"parec_failed:exit_{exc.returncode}"
            log.warning("egress loopback producer: %s", err)
            witness = _error_witness(
                checked_at=ts,
                window_seconds=self.window_seconds,
                target_sink=self.source,
                error=err,
            )
            write_witness_atomic(witness, self.witness_path)
            return witness
        except Exception as exc:  # noqa: BLE001 — surface as producer error
            err = f"capture_failed:{type(exc).__name__}:{exc!s}"
            log.warning("egress loopback producer: %s", err)
            witness = _error_witness(
                checked_at=ts,
                window_seconds=self.window_seconds,
                target_sink=self.source,
                error=err,
            )
            write_witness_atomic(witness, self.witness_path)
            return witness

        sample = compute_loopback_metrics(pcm, sample_rate=self.sample_rate)
        witness = EgressLoopbackWitness(
            checked_at=ts,
            rms_dbfs=sample.rms_dbfs,
            peak_dbfs=sample.peak_dbfs,
            silence_ratio=sample.silence_ratio,
            window_seconds=self.window_seconds,
            target_sink=self.source,
            quality=sample.quality,
            crest_factor_db=sample.crest_factor_db,
            zero_crossing_rate_hz=sample.zero_crossing_rate_hz,
            quality_reasons=list(sample.quality_reasons),
            error=None,
        )
        write_witness_atomic(witness, self.witness_path)
        return witness

    def run_forever(self) -> None:
        """Tick forever at the configured cadence.

        Sleeps the residual between (tick_seconds - window_seconds) so
        the witness write rate matches the configured tick. If the
        capture itself takes longer than the tick (slow PipeWire),
        next tick fires immediately with no sleep.
        """
        log.info(
            "egress loopback producer started: source=%s window=%.1fs tick=%.1fs path=%s",
            self.source,
            self.window_seconds,
            self.tick_seconds,
            self.witness_path,
        )
        while True:
            t_start = time.monotonic()
            try:
                self.tick_once()
            except Exception:  # noqa: BLE001 — never let the loop crash
                log.exception("egress loopback producer: unexpected tick failure")
            elapsed = time.monotonic() - t_start
            residual = self.tick_seconds - elapsed
            if residual > 0:
                self._sleep(residual)


def _error_witness(
    *,
    checked_at: str,
    window_seconds: float,
    target_sink: str,
    error: str,
) -> EgressLoopbackWitness:
    """Construct an error witness with finite zeroed metrics.

    Uses -120 dBFS sentinels (matching :func:`compute_loopback_metrics`'s
    digital-silence clamp) so the JSON values stay numeric and the
    evaluator's silence_ratio threshold check (which fires before
    error inspection) does not produce a misleading ``silent`` block
    when ``producer_error`` is the truer root cause. The evaluator
    short-circuits on ``error`` first.
    """
    return EgressLoopbackWitness(
        checked_at=checked_at,
        rms_dbfs=-120.0,
        peak_dbfs=-120.0,
        silence_ratio=1.0,
        window_seconds=window_seconds,
        target_sink=target_sink,
        quality=EgressLoopbackQuality.UNKNOWN,
        crest_factor_db=None,
        zero_crossing_rate_hz=0.0,
        quality_reasons=[error],
        error=error,
    )


def load_config_from_env() -> dict[str, object]:
    """Read producer config from environment, with sensible defaults.

    Env vars (all optional):
      - ``HAPAX_LOOPBACK_SOURCE`` — PipeWire source name
        (default: ``hapax-broadcast-normalized``).
      - ``HAPAX_LOOPBACK_WINDOW_S`` — capture window in seconds
        (default: 5.0).
      - ``HAPAX_LOOPBACK_TICK_S`` — tick interval in seconds
        (default: 1.0).
      - ``HAPAX_LOOPBACK_SAMPLE_RATE_HZ`` — capture rate in Hz
        (default: 48000, native broadcast graph rate).
      - ``HAPAX_LOOPBACK_WITNESS_PATH`` — output JSON path (default:
        ``/dev/shm/hapax-broadcast/egress-loopback.json``).

    The systemd unit can override any of these via ``Environment=``
    lines. Bare-string parsing (no YAML / TOML loader) keeps the
    daemon import small.
    """
    return {
        "source": os.environ.get("HAPAX_LOOPBACK_SOURCE", DEFAULT_BROADCAST_SOURCE),
        "window_seconds": float(os.environ.get("HAPAX_LOOPBACK_WINDOW_S", DEFAULT_WINDOW_SECONDS)),
        "tick_seconds": float(os.environ.get("HAPAX_LOOPBACK_TICK_S", DEFAULT_TICK_SECONDS)),
        "sample_rate": int(os.environ.get("HAPAX_LOOPBACK_SAMPLE_RATE_HZ", DEFAULT_SAMPLE_RATE_HZ)),
        "witness_path": Path(
            os.environ.get("HAPAX_LOOPBACK_WITNESS_PATH", str(DEFAULT_WITNESS_PATH))
        ),
    }
