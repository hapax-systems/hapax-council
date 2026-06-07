"""parecord-based monitor-port probes.

The source research §1 H1 calls out the **explicit** requirement to use
``parecord``, NOT ``pw-cat``, for monitor-port capture: pw-cat against
``support.null-audio-sink`` monitor ports has a known artefact that
produces near-silent reads regardless of real signal (verified
2026-05-02 in ``config/pipewire/hapax-broadcast-master.conf`` lines
86–96).

Each probe captures a short PCM window (default 2s) from a PipeWire
source. For legacy null sinks that means the sink's ``.monitor`` source;
for remap-source stages that already exist as sources, it means the
stage name itself. The decoded s16le bytes become a numpy ``int16``
array and then hand off to :mod:`agents.audio_signal_assertion.classifier`.

Discovery: callers that want dynamic stage selection can use
:func:`discover_broadcast_stages` which calls ``pactl list sinks short``
and filters for sinks named ``hapax-*broadcast*`` per the source
research's "discovery via ``pactl list sinks short | grep broadcast``"
pattern.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from threading import Condition, Lock, Thread
from typing import Final

import numpy as np

from agents.audio_health.classifier import (
    Classification,
    ClassifierConfig,
    ProbeMeasurement,
    classify,
    measure_pcm,
)

log = logging.getLogger(__name__)

PACTL_SHORT_CACHE_TTL_S: Final[float] = 10.0
_PACTL_SHORT_CACHE: dict[tuple[str, str], tuple[float, frozenset[str]]] = {}
_PACTL_SHORT_CACHE_LOCK = Lock()

# Monitor capture defaults — tuned for parecord raw output against the
# null-audio-sink monitor ports the broadcast chain uses.
DEFAULT_SAMPLE_RATE: Final[int] = 48000
DEFAULT_CHANNELS: Final[int] = 2
DEFAULT_DURATION_S: Final[float] = 2.0
DEFAULT_PERSISTENT_LATENCY_MSEC: Final[int] = 100
DEFAULT_PERSISTENT_BUFFER_S: Final[float] = 15.0

# Mandatory minimum stages — these are the load-bearing edges of the
# broadcast chain per the source research §1 H1 "Implementation"
# paragraph and the existing broadcast-audio-health LUFS probe.
DEFAULT_STAGES: Final[tuple[str, ...]] = (
    "hapax-broadcast-master",
    "hapax-broadcast-normalized",
    "hapax-obs-broadcast-remap",
)

# The final OBS-bound stage. Transitions to bad steady-states here
# trigger ntfy. Other stages emit metrics + are visible in the
# transition log but do not page on their own (they're mostly useful
# as upstream context for *where* the OBS-stage badness entered).
OBS_BOUND_STAGE: Final[str] = "hapax-obs-broadcast-remap"


class ProbeError(RuntimeError):
    """Raised when parecord fails or PCM decoding fails."""


@dataclass(frozen=True)
class ProbeConfig:
    """Immutable per-probe parameters."""

    duration_s: float = DEFAULT_DURATION_S
    sample_rate: int = DEFAULT_SAMPLE_RATE
    channels: int = DEFAULT_CHANNELS
    parecord_path: str = "parecord"
    pactl_path: str = "pactl"
    timeout_extra_s: float = 4.0


@dataclass(frozen=True)
class ProbeResult:
    """One probe's findings: stage + raw measurement + classification.

    ``samples_mono`` is the deliberately exposed decoded mono sample
    buffer for analyzers that need waveform access. Derived
    measurement fields stay on :class:`ProbeMeasurement`; callers must
    not attach raw samples to the measurement object dynamically.

    ``error`` is set (with measurement zeroed) when capture fails — the
    daemon treats failures as "unknown" rather than "bad" so a transient
    parecord glitch doesn't ntfy the operator. Persistent failures show
    up in the metrics (the gauge stays at the prior value, freshness
    decays) and via the absence of a recent successful probe in
    ``/dev/shm/hapax-audio/signal-flow.json``.
    """

    stage: str
    classification: Classification
    measurement: ProbeMeasurement
    captured_at: float
    duration_s: float
    sample_rate: int = DEFAULT_SAMPLE_RATE
    error: str | None = None
    samples_mono: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int16))

    def __post_init__(self) -> None:
        """Preserve legacy fixture construction that omitted raw samples."""

        if self.samples_mono.size == 0 and self.measurement.sample_count > 0:
            object.__setattr__(
                self,
                "samples_mono",
                np.zeros(self.measurement.sample_count, dtype=np.int16),
            )

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def samples_mono_float(self) -> np.ndarray:
        """Return mono samples as unit-normalized ``float64``.

        ``parecord`` capture decodes to raw int16 mono samples. M2/M3/M4
        analyzers operate on normalized floats, so this property is the
        explicit conversion point instead of hidden dynamic attributes
        on :class:`ProbeMeasurement`.
        """

        if np.issubdtype(self.samples_mono.dtype, np.integer):
            return self.samples_mono.astype(np.float64) / 32768.0
        return self.samples_mono.astype(np.float64, copy=False)


def discover_broadcast_stages(
    *,
    pactl_path: str = "pactl",
    timeout_s: float = 4.0,
    fallback: Sequence[str] = DEFAULT_STAGES,
) -> tuple[str, ...]:
    """Discover broadcast-named sinks via ``pactl list sinks short``.

    Per the source research §1 H1: "List discoverable via
    ``pactl list sinks short | grep broadcast`` if dynamic-discovery
    is desired." Returns the static :data:`DEFAULT_STAGES` tuple if
    pactl is missing, fails, or produces no broadcast-named sinks —
    callers always get a non-empty tuple to probe.

    Stages are returned in the order parecord will probe them: when
    pactl discovery succeeds, the static order from ``DEFAULT_STAGES``
    is preserved for the stages we know about, then any additional
    discovered broadcast sinks are appended in pactl order.
    """

    if shutil.which(pactl_path) is None:
        return tuple(fallback)

    try:
        result = subprocess.run(
            [pactl_path, "list", "sinks", "short"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return tuple(fallback)

    if result.returncode != 0:
        return tuple(fallback)

    discovered: list[str] = []
    for line in result.stdout.splitlines():
        # Format: <id>\t<name>\t<module>\t<format>\t<state>
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        name = parts[1].strip()
        if "broadcast" in name and name.startswith("hapax-"):
            discovered.append(name)

    if not discovered:
        return tuple(fallback)

    ordered: list[str] = []
    for stage in DEFAULT_STAGES:
        if stage in discovered:
            ordered.append(stage)
    for name in discovered:
        if name not in ordered:
            ordered.append(name)
    return tuple(ordered)


def _pactl_short_names(kind: str, config: ProbeConfig) -> set[str]:
    """Return PipeWire node names from ``pactl list short <kind>``."""

    if shutil.which(config.pactl_path) is None:
        return set()

    cache_key = (config.pactl_path, kind)
    now = time.monotonic()
    with _PACTL_SHORT_CACHE_LOCK:
        cached = _PACTL_SHORT_CACHE.get(cache_key)
        if cached is not None:
            cached_at, names = cached
            if now - cached_at <= PACTL_SHORT_CACHE_TTL_S:
                return set(names)

    try:
        result = subprocess.run(
            [config.pactl_path, "list", kind, "short"],
            capture_output=True,
            text=True,
            timeout=4.0,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return set()

    if result.returncode != 0:
        return set()

    names: set[str] = set()
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1].strip():
            names.add(parts[1].strip())
    with _PACTL_SHORT_CACHE_LOCK:
        _PACTL_SHORT_CACHE[cache_key] = (time.monotonic(), frozenset(names))
    return names


def resolve_parecord_target(target: str, config: ProbeConfig) -> str:
    """Resolve a logical audio stage to the actual ``parecord`` device.

    Historical broadcast stages were null sinks, so callers passed
    ``hapax-broadcast-master`` and the probe appended ``.monitor``. The
    current broadcast graph also contains remap-source stages named
    ``hapax-broadcast-master`` / ``hapax-obs-broadcast-remap`` directly
    in ``pactl list short sources``. Appending ``.monitor`` to those
    source names samples the wrong thing or silence. Prefer an exact
    source, use ``sink.monitor`` only for actual sinks, and preserve the
    old monitor fallback when discovery is unavailable.
    """

    sources = _pactl_short_names("sources", config)
    sinks = _pactl_short_names("sinks", config)

    if target in sources:
        return target

    if target.endswith(".monitor"):
        base = target.removesuffix(".monitor")
        if base in sources:
            return base
        if base in sinks or target in sources:
            return target
        return target

    if target in sinks:
        return f"{target}.monitor"

    return f"{target}.monitor"


def _capture_parecord(
    target: str,
    config: ProbeConfig,
) -> bytes:
    """Run parecord against a resolved source target, return raw s16le bytes.

    Uses ``parecord --device=<resolved-source> --raw --rate=...
    --channels=... --format=s16le``. The capture is bounded by both the
    ``--latency-msec`` ceiling (so the kernel buffer doesn't accumulate
    noise) AND a subprocess timeout that includes ``timeout_extra_s``
    headroom, so a hung parecord cannot stall the daemon's 30s probe
    cycle.
    """

    if shutil.which(config.parecord_path) is None:
        raise ProbeError(f"parecord binary not found at {config.parecord_path!r}")

    monitor_target = resolve_parecord_target(target, config)
    cmd = [
        config.parecord_path,
        f"--device={monitor_target}",
        "--raw",
        f"--rate={config.sample_rate}",
        f"--channels={config.channels}",
        "--format=s16le",
        f"--latency-msec={int(config.duration_s * 1000)}",
    ]

    timeout_total = config.duration_s + config.timeout_extra_s
    deadline = time.monotonic() + config.duration_s

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (FileNotFoundError, OSError) as exc:
        raise ProbeError(f"parecord spawn failed: {exc}") from exc

    captured = bytearray()
    try:
        # Read until the duration deadline elapses, then terminate the
        # parecord process. This avoids parecord buffering many seconds
        # of audio on its own — the operator's 30s probe cycle stays
        # honest.
        bytes_per_sample = 2 * config.channels  # s16le * channels
        target_bytes = int(config.duration_s * config.sample_rate * bytes_per_sample)
        while True:
            now = time.monotonic()
            if now >= deadline and len(captured) >= target_bytes:
                break
            if now > deadline + config.timeout_extra_s:
                break
            assert proc.stdout is not None
            chunk = proc.stdout.read(4096)
            if not chunk:
                # parecord hit EOF (e.g. monitor went away) — bail.
                break
            captured.extend(chunk)
            if len(captured) >= target_bytes * 2:
                # Bounded — never let parecord fill memory.
                break
    finally:
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

    rc = proc.returncode if proc.returncode is not None else 0
    # parecord returns non-zero when terminated by SIGTERM/SIGKILL; we
    # tolerate that since terminating it is how we bound the duration.
    # Real failures (target missing, bad format) come through on stderr
    # AND empty captured buffer.
    if not captured:
        stderr_tail = ""
        if proc.stderr is not None:
            try:
                stderr_tail = proc.stderr.read().decode("utf-8", errors="replace")[-500:]
            except OSError:
                stderr_tail = ""
        raise ProbeError(
            f"parecord captured 0 bytes from {monitor_target!r} "
            f"(rc={rc}, timeout={timeout_total}s, stderr={stderr_tail!r})"
        )

    return bytes(captured)


class PersistentParecordCapture:
    """Long-lived parecord reader for one PipeWire capture target.

    The audio-health daemons run continuously. Starting ``parecord`` for every
    stage on every tick attaches and detaches streams from live egress nodes,
    which is the dropout mechanism this task is removing. This class starts one
    capture process per target and drains it on a background thread into a
    bounded ring buffer; callers sample the latest window without reconnecting.
    """

    def __init__(
        self,
        target: str,
        config: ProbeConfig,
        *,
        max_buffer_s: float = DEFAULT_PERSISTENT_BUFFER_S,
    ) -> None:
        self.logical_target = target
        self.config = config
        self.monitor_target = resolve_parecord_target(target, config)
        self.bytes_per_frame = 2 * max(1, config.channels)
        min_buffer_s = max(config.duration_s * 2.0, config.duration_s + config.timeout_extra_s)
        buffer_s = max(max_buffer_s, min_buffer_s)
        self.max_buffer_bytes = max(
            4096,
            int(buffer_s * config.sample_rate * self.bytes_per_frame),
        )
        self._condition = Condition()
        self._buffer = bytearray()
        self._total_bytes = 0
        self._error: str | None = None
        self._proc: subprocess.Popen[bytes] | None = None
        self._thread: Thread | None = None

    def start(self) -> None:
        """Start the persistent parecord process if it is not already running."""

        with self._condition:
            if self._proc is not None and self._proc.poll() is None:
                return
            self._buffer.clear()
            self._total_bytes = 0
            self._error = None

        if shutil.which(self.config.parecord_path) is None:
            raise ProbeError(f"parecord binary not found at {self.config.parecord_path!r}")

        cmd = [
            self.config.parecord_path,
            f"--device={self.monitor_target}",
            "--raw",
            f"--rate={self.config.sample_rate}",
            f"--channels={self.config.channels}",
            "--format=s16le",
            f"--latency-msec={DEFAULT_PERSISTENT_LATENCY_MSEC}",
        ]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except (FileNotFoundError, OSError) as exc:
            raise ProbeError(f"parecord spawn failed: {exc}") from exc

        thread = Thread(target=self._read_loop, name=f"parecord:{self.monitor_target}", daemon=True)
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
                    self._total_bytes += len(chunk)
                    overflow = len(self._buffer) - self.max_buffer_bytes
                    if overflow > 0:
                        del self._buffer[:overflow]
                    self._condition.notify_all()
        except OSError as exc:
            with self._condition:
                self._error = f"parecord read failed from {self.monitor_target!r}: {exc}"
                self._condition.notify_all()
            return

        rc = proc.poll()
        with self._condition:
            if self._proc is proc and rc not in (None, 0):
                self._error = f"parecord exited for {self.monitor_target!r} rc={rc}"
            elif self._proc is proc:
                self._error = f"parecord ended for {self.monitor_target!r}"
            self._condition.notify_all()

    def read_window(self, duration_s: float | None = None) -> bytes:
        """Return the latest captured PCM window without reconnecting."""

        self.start()
        seconds = self.config.duration_s if duration_s is None else duration_s
        target_bytes = max(1, int(seconds * self.config.sample_rate * self.bytes_per_frame))
        deadline = time.monotonic() + seconds + self.config.timeout_extra_s

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

            error = self._error or "timed out waiting for persistent parecord data"
            raise ProbeError(error)

    def close(self) -> None:
        """Terminate the persistent capture process."""

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


def _decode_s16le_to_mono(
    raw: bytes,
    channels: int,
) -> np.ndarray:
    """Decode interleaved s16le bytes to a mono ``int16`` numpy array.

    Multi-channel inputs are downmixed by averaging across channels
    (truncated to int16) before measurement. Channel-mismatch silent
    failures (e.g. FL/FR vs RL/RR collapse from the source research's
    incident #1) show up as ``silent`` classifications rather than
    crashing the decoder.
    """

    samples = np.frombuffer(raw, dtype=np.int16)
    if channels <= 1 or samples.size == 0:
        return samples.copy()
    truncated = (samples.size // channels) * channels
    if truncated == 0:
        return np.zeros(0, dtype=np.int16)
    reshaped = samples[:truncated].reshape(-1, channels)
    # int32 mean-then-cast preserves headroom across channel sum.
    mono = reshaped.astype(np.int32).mean(axis=1)
    return mono.astype(np.int16)


def _error_result(
    stage: str,
    started: float,
    error: str,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> ProbeResult:
    empty = ProbeMeasurement(
        rms_dbfs=-120.0,
        peak_dbfs=-120.0,
        crest_factor=0.0,
        zero_crossing_rate=0.0,
        sample_count=0,
    )
    return ProbeResult(
        stage=stage,
        classification=Classification.MUSIC_VOICE,
        measurement=empty,
        samples_mono=np.zeros(0, dtype=np.int16),
        captured_at=started,
        duration_s=0.0,
        sample_rate=sample_rate,
        error=error,
    )


def _measure_raw_result(
    stage: str,
    raw: bytes,
    config: ProbeConfig,
    classifier_config: ClassifierConfig | None,
    *,
    started: float,
) -> ProbeResult:
    samples = _decode_s16le_to_mono(raw, config.channels)
    measurement = measure_pcm(samples)
    label = classify(measurement, classifier_config)
    duration = samples.size / config.sample_rate if config.sample_rate else config.duration_s
    return ProbeResult(
        stage=stage,
        classification=label,
        measurement=measurement,
        samples_mono=samples,
        captured_at=started,
        duration_s=float(duration),
        sample_rate=config.sample_rate,
        error=None,
    )


class PersistentProbeSet:
    """Persistent per-target probe pool for long-running audio-health daemons."""

    def __init__(
        self,
        *,
        config: ProbeConfig | None = None,
        classifier_config: ClassifierConfig | None = None,
        stream_factory: Callable[[str, ProbeConfig], PersistentParecordCapture] | None = None,
    ) -> None:
        self.config = config or ProbeConfig()
        self.classifier_config = classifier_config
        self._stream_factory = stream_factory or PersistentParecordCapture
        self._streams: dict[str, PersistentParecordCapture] = {}
        self._lock = Lock()

    def _stream_for(self, stage: str) -> PersistentParecordCapture:
        with self._lock:
            stream = self._streams.get(stage)
            if stream is None:
                stream = self._stream_factory(stage, self.config)
                self._streams[stage] = stream
            return stream

    def capture(self, stage: str, *, captured_at: float | None = None) -> ProbeResult:
        """Capture and classify the latest window from a persistent stream."""

        started = captured_at if captured_at is not None else time.time()
        try:
            raw = self._stream_for(stage).read_window(self.config.duration_s)
        except ProbeError as exc:
            log.debug("persistent probe %s failed: %s", stage, exc)
            return _error_result(stage, started, str(exc), sample_rate=self.config.sample_rate)
        return _measure_raw_result(
            stage,
            raw,
            self.config,
            self.classifier_config,
            started=started,
        )

    def close(self) -> None:
        with self._lock:
            streams = list(self._streams.values())
            self._streams.clear()
        for stream in streams:
            stream.close()

    def __enter__(self) -> PersistentProbeSet:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


def capture_and_measure(
    stage: str,
    *,
    config: ProbeConfig | None = None,
    classifier_config: ClassifierConfig | None = None,
    captured_at: float | None = None,
) -> ProbeResult:
    """Probe one stage end-to-end: capture → measure → classify.

    Capture failures (parecord missing, target absent, empty buffer)
    return a :class:`ProbeResult` with ``error`` set and a
    :data:`Classification.MUSIC_VOICE` placeholder so the daemon
    never alerts on probe failures alone (read-only constraint
    forbids false-positive ntfys).
    """

    cfg = config or ProbeConfig()
    started = captured_at if captured_at is not None else time.time()

    try:
        raw = _capture_parecord(stage, cfg)
    except ProbeError as exc:
        log.debug("probe %s failed: %s", stage, exc)
        return _error_result(stage, started, str(exc), sample_rate=cfg.sample_rate)

    return _measure_raw_result(
        stage=stage,
        raw=raw,
        config=cfg,
        classifier_config=classifier_config,
        started=started,
    )


__all__ = [
    "DEFAULT_DURATION_S",
    "DEFAULT_SAMPLE_RATE",
    "DEFAULT_STAGES",
    "OBS_BOUND_STAGE",
    "ProbeConfig",
    "ProbeError",
    "ProbeResult",
    "PersistentParecordCapture",
    "PersistentProbeSet",
    "capture_and_measure",
    "discover_broadcast_stages",
]
