"""parecord-based monitor-port probes.

The source research §1 H1 calls out the **explicit** requirement to use
``parecord``, NOT ``pw-cat``, for monitor-port capture: pw-cat against
``support.null-audio-sink`` monitor ports has a known artefact that
produces near-silent reads regardless of real signal (verified
2026-05-02 in ``config/pipewire/hapax-broadcast-master.conf`` lines
86–96).

Each probe captures a short PCM window (default 2s) from a target
sink's ``.monitor`` device, decodes the s16le bytes into a numpy
``int16`` array, and hands off to :mod:`agents.audio_signal_assertion.classifier`.

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
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np

from agents.audio_signal_assertion.classifier import (
    Classification,
    ClassifierConfig,
    ProbeMeasurement,
    classify,
    measure_pcm,
)

log = logging.getLogger(__name__)

# Monitor capture defaults — tuned for parecord raw output against the
# null-audio-sink monitor ports the broadcast chain uses.
DEFAULT_SAMPLE_RATE: Final[int] = 48000
DEFAULT_CHANNELS: Final[int] = 2
DEFAULT_DURATION_S: Final[float] = 2.0

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
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


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


def _capture_parecord(
    target: str,
    config: ProbeConfig,
) -> bytes:
    """Run parecord against a monitor target, return raw s16le bytes.

    Uses ``parecord --device=<target>.monitor --raw --rate=...
    --channels=... --format=s16le`` per the source research's
    explicit guidance. The capture is bounded by both the
    ``--latency-msec`` ceiling (so the kernel buffer doesn't accumulate
    noise) AND a subprocess timeout that includes ``timeout_extra_s``
    headroom, so a hung parecord cannot stall the daemon's 30s probe
    cycle.
    """

    if shutil.which(config.parecord_path) is None:
        raise ProbeError(f"parecord binary not found at {config.parecord_path!r}")

    monitor_target = target if target.endswith(".monitor") else f"{target}.monitor"
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
            captured_at=started,
            duration_s=0.0,
            error=str(exc),
        )

    samples = _decode_s16le_to_mono(raw, cfg.channels)
    measurement = measure_pcm(samples)
    label = classify(measurement, classifier_config)
    duration = samples.size / cfg.sample_rate if cfg.sample_rate else cfg.duration_s
    return ProbeResult(
        stage=stage,
        classification=label,
        measurement=measurement,
        captured_at=started,
        duration_s=float(duration),
        error=None,
    )


__all__ = [
    "DEFAULT_DURATION_S",
    "DEFAULT_SAMPLE_RATE",
    "DEFAULT_STAGES",
    "OBS_BOUND_STAGE",
    "ProbeConfig",
    "ProbeError",
    "ProbeResult",
    "capture_and_measure",
    "discover_broadcast_stages",
]
