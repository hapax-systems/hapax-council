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
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from shared.broadcast_audio_health import (
    DEFAULT_EGRESS_LOOPBACK_WITNESS,
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

#: Capture sample rate. parec's default for unspecified rate; matches
#: PipeWire's default sink graph and avoids resample overhead.
DEFAULT_SAMPLE_RATE_HZ: Final[int] = 48000

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


# Subprocess shell type: tests inject stubs that return synthetic PCM
# bytes so the suite never touches real PipeWire.
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


def compute_loopback_metrics(
    pcm_bytes: bytes,
    *,
    silence_floor_dbfs: float = SILENCE_FLOOR_DBFS,
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
        return LoopbackSample(rms_dbfs=-120.0, peak_dbfs=-120.0, silence_ratio=1.0)

    samples = array.array("h")  # signed short, native endian on Linux x86_64
    # array.frombytes requires len % itemsize == 0 — pad/truncate the
    # last partial sample if parec returned an odd byte count.
    usable = len(pcm_bytes) - (len(pcm_bytes) % 2)
    samples.frombytes(pcm_bytes[:usable])
    if not samples:
        return LoopbackSample(rms_dbfs=-120.0, peak_dbfs=-120.0, silence_ratio=1.0)

    full_scale = 32767.0
    silence_threshold_amp = full_scale * (10.0 ** (silence_floor_dbfs / 20.0))

    sum_sq = 0.0
    peak_amp = 0
    silent_count = 0
    for s in samples:
        sum_sq += float(s) * float(s)
        a = abs(s)
        if a > peak_amp:
            peak_amp = a
        if a < silence_threshold_amp:
            silent_count += 1

    n = len(samples)
    rms_amp = math.sqrt(sum_sq / n)

    rms_dbfs = _safe_dbfs(rms_amp, full_scale)
    peak_dbfs = _safe_dbfs(float(peak_amp), full_scale)
    silence_ratio = silent_count / n
    return LoopbackSample(
        rms_dbfs=rms_dbfs,
        peak_dbfs=peak_dbfs,
        silence_ratio=silence_ratio,
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
        self._capture = capture or _default_capture
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleep = sleeper or time.sleep

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

        sample = compute_loopback_metrics(pcm)
        witness = EgressLoopbackWitness(
            checked_at=ts,
            rms_dbfs=sample.rms_dbfs,
            peak_dbfs=sample.peak_dbfs,
            silence_ratio=sample.silence_ratio,
            window_seconds=self.window_seconds,
            target_sink=self.source,
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
        "witness_path": Path(
            os.environ.get("HAPAX_LOOPBACK_WITNESS_PATH", str(DEFAULT_WITNESS_PATH))
        ),
    }
