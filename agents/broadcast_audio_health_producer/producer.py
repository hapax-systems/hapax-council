"""Periodic broadcast audio health probe.

For each configured ``RouteSpec`` (sink + monitor source pair), the
producer injects a ~17.5 kHz marker tone into the sink, captures from
the monitor source, and runs FFT detection. Results land in a daily
JSONL evidence log under ``~/hapax-state/broadcast-audio-health/``
and increment a Prometheus counter ``hapax_broadcast_audio_health_
probes_total{route, outcome}`` so the operator can read live
audibility on the existing observability surfaces.

Subprocess shells (pw-cat for inject, parec for capture) are
parameterised so the test suite can swap them for stubs that return
synthetic PCM through delta's pure-logic detector.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Final

import numpy as np

from shared.audio_marker_probe_fft import (
    DEFAULT_MARKER_FREQ_HZ,
    DEFAULT_SAMPLE_RATE_HZ,
    MarkerDetection,
    detect_marker_in_capture,
    generate_marker_tone,
)
from shared.broadcast_audio_health_metrics import record_probe

log = logging.getLogger(__name__)


#: State directory under the operator's hapax-state tree. One JSONL
#: per UTC date keeps reads cheap and lets operators tail the live
#: file without scanning history. 7-day retention is enforced by
#: :func:`prune_old_files` at run-time.
DEFAULT_STATE_DIR: Final[Path] = Path.home() / "hapax-state" / "broadcast-audio-health"

#: Days of history to keep before pruning. Aligns with other Hapax
#: evidence stores (datacite-mirror, attribution).
RETENTION_DAYS: Final[int] = 7

#: Default capture duration. Sized to comfortably cover the parec
#: warmup window plus the full inject duration plus tail, with FFT
#: bin-width gain at this length.
DEFAULT_CAPTURE_DURATION_S: Final[float] = 3.0

#: parec startup latency before the stream actually delivers audio.
#: Measured ~1.5–2.0 s on PipeWire on this workstation. The capture
#: process is started, then the producer waits this long before
#: dispatching the inject, so the marker tone arrives inside the
#: capture window rather than ahead of it. Without this overlap the
#: serial inject→capture pattern misses the tone entirely (root cause
#: of the 2026-05-02 not_detected investigation).
CAPTURE_WARMUP_S: Final[float] = 1.5


class ProbeOutcome(StrEnum):
    """Bounded label set for the Prometheus counter.

    Cardinality is hard-bounded so the metric never explodes the
    label space. ``error`` covers any subprocess failure (pw-cat /
    parec missing, sink/source not present, capture short read);
    ``not_detected`` is a clean negative result (the route is
    silent); ``detected`` is a clean positive.
    """

    DETECTED = "detected"
    NOT_DETECTED = "not_detected"
    ERROR = "error"


@dataclass(frozen=True)
class RouteSpec:
    """One audio route to probe.

    ``name`` is the operator-visible label (``broadcast-l12``,
    ``private-yeti``, etc.) — also the ``route`` Prometheus label
    value, so keep it stable across deploys.

    ``sink_name`` is the PipeWire sink to inject into.

    ``monitor_source`` is the corresponding monitor source to
    capture from. By PipeWire convention this is usually
    ``<sink>.monitor`` but the producer accepts an arbitrary source
    so loopback / virtual-routing surfaces can probe end-to-end.

    ``inject_channels`` is the channel count the inject must declare
    to pw-cat. Defaults to 1 (mono, works for stereo sinks via
    upmix). Multi-channel sinks like the L-12 ``analog-surround-40``
    profile (4ch front-left/right + rear-left/right) need an
    explicit channel count or the mono inject does not appear on
    the sink monitor at all. The producer replicates the mono tone
    across all channels at inject time.
    """

    name: str
    sink_name: str
    monitor_source: str
    inject_channels: int = 1


@dataclass(frozen=True)
class ProbeResult:
    """One probe attempt's evidence row."""

    name: str
    sink_name: str
    monitor_source: str
    outcome: ProbeOutcome
    detection: MarkerDetection | None
    error: str | None
    timestamp_utc: str


# ── Subprocess shell types ──────────────────────────────────────────
#
# Tests inject stubs for these so detection runs against synthetic
# PCM without touching real PipeWire. Production wires them to
# :func:`_default_inject` / :func:`_default_capture`.

InjectFn = Callable[[str, np.ndarray, int], None]
CaptureFn = Callable[[str, float, int], np.ndarray]


def _default_inject(sink_name: str, samples: np.ndarray, sample_rate: int) -> None:
    """Pipe int16 PCM to ``pw-cat -p --raw --target <sink>``.

    ``samples`` may be 1D mono or 2D ``(T, C)``. For 2D input the
    samples are flattened in interleaved (C order) layout and pw-cat
    is told the matching channel count.

    The ``--raw`` (``-a``) flag bypasses libsndfile, which would otherwise
    try to interpret stdin as a recognised audio container (WAV/AIFF/FLAC)
    and fail with "Format not recognised". With ``--raw`` pw-cat treats
    the input as bare PCM matching the declared rate/channels/format.
    """
    if samples.ndim == 1:
        channels = 1
        payload = samples
    elif samples.ndim == 2:
        channels = samples.shape[1]
        payload = np.ascontiguousarray(samples)  # interleaved by C-order layout
    else:
        raise ValueError(f"samples must be 1D mono or 2D (T,C); got shape {samples.shape}")
    cmd = [
        "pw-cat",
        "-p",
        "--raw",
        "--rate",
        str(sample_rate),
        "--channels",
        str(channels),
        "--format",
        "s16",
        "--target",
        sink_name,
        "-",
    ]
    # ``timeout`` is a fail-fast cap, not a budget. On a healthy sink
    # pw-cat returns in ~tone_duration_s + ~0.2 s graphical overhead
    # (≤1.5 s for the typical 1 s tone). The 15 s ceiling exists so a
    # contended sink (e.g. L-12 USB sink-input scheduling stalling
    # under filter-chain contention — root cause of the 2026-05-03
    # livestream-dropout investigation) does NOT block the probe
    # forever and pile pw-cat subprocesses across 60 s timer fires.
    # Aligned with the capture-thread join timeout below so the probe
    # surfaces contention as one ``error`` outcome per cycle rather
    # than half-failing with the inject hung past the join window.
    completed = subprocess.run(  # noqa: S603 — args are an explicit list
        cmd,
        input=payload.tobytes(),
        capture_output=True,
        timeout=15,
        check=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"pw-cat exited {completed.returncode}: {completed.stderr!r}")


def _default_capture(monitor_source: str, duration_s: float, sample_rate: int) -> np.ndarray:
    """Capture int16 PCM from ``parec`` for ``duration_s`` seconds."""
    n_samples = int(round(sample_rate * duration_s))
    nbytes = n_samples * 2  # int16 = 2 bytes/sample
    cmd = [
        "parec",
        "--device",
        monitor_source,
        "--rate",
        str(sample_rate),
        "--channels",
        "1",
        "--format",
        "s16le",
        "--raw",
    ]
    proc = subprocess.Popen(  # noqa: S603 — args are an explicit list
        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    try:
        assert proc.stdout is not None
        buf = proc.stdout.read(nbytes)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
    if len(buf) < nbytes:
        raise RuntimeError(f"parec short read: got {len(buf)} of {nbytes} bytes")
    return np.frombuffer(buf, dtype=np.int16)


class BroadcastAudioHealthProducer:
    """Run one probe cycle across all configured routes.

    Construct with the route list + an optional state-dir override
    (mainly for tests). Call :meth:`run_once` per timer fire — it
    iterates the routes, emits one evidence row per route, and
    increments the Prometheus counter accordingly.
    """

    def __init__(
        self,
        routes: list[RouteSpec],
        state_dir: Path | None = None,
        *,
        marker_freq_hz: float = DEFAULT_MARKER_FREQ_HZ,
        sample_rate: int = DEFAULT_SAMPLE_RATE_HZ,
        capture_duration_s: float = DEFAULT_CAPTURE_DURATION_S,
        inject: InjectFn | None = None,
        capture: CaptureFn | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not routes:
            raise ValueError("routes must be non-empty")
        self.routes = routes
        self.state_dir = state_dir or DEFAULT_STATE_DIR
        self.marker_freq_hz = marker_freq_hz
        self.sample_rate = sample_rate
        self.capture_duration_s = capture_duration_s
        self._inject = inject or _default_inject
        self._capture = capture or _default_capture
        self._clock = clock or (lambda: datetime.now(UTC))

    def _probe_route(self, route: RouteSpec) -> ProbeResult:
        ts = self._clock().isoformat()
        try:
            # Inject duration is shorter than capture: tone fits inside
            # the warmup-shifted capture window with tail headroom for
            # FFT bin resolution.
            tone_duration_s = max(self.capture_duration_s - CAPTURE_WARMUP_S - 0.5, 0.5)
            mono_tone = generate_marker_tone(
                self.marker_freq_hz,
                duration_s=tone_duration_s,
                sample_rate=self.sample_rate,
            )
            tone = self._shape_for_channels(mono_tone, route.inject_channels)

            # Start capture FIRST (parec has ~1.5–2.0 s startup latency
            # before the stream actually delivers audio). Inject runs in
            # parallel after CAPTURE_WARMUP_S so the marker arrives
            # inside the parec read window, not before.
            captured_holder: dict[str, np.ndarray] = {}
            error_holder: dict[str, BaseException] = {}

            def _capture_thread() -> None:
                try:
                    captured_holder["data"] = self._capture(
                        route.monitor_source, self.capture_duration_s, self.sample_rate
                    )
                except BaseException as e:  # noqa: BLE001 — propagate via holder
                    error_holder["e"] = e

            cap_thread = threading.Thread(target=_capture_thread, daemon=True)
            cap_thread.start()
            time.sleep(CAPTURE_WARMUP_S)
            self._inject(route.sink_name, tone, self.sample_rate)
            # Headroom of 15 s above the configured capture window
            # absorbs transient parec startup jitter on contended ALSA
            # monitor sources without piling probe runs. Aligned with
            # the pw-cat inject ceiling in :func:`_default_inject`.
            cap_thread.join(timeout=self.capture_duration_s + 15.0)
            if cap_thread.is_alive():
                raise RuntimeError(
                    f"capture thread for {route.name} did not finish within "
                    f"{self.capture_duration_s + 15.0}s"
                )
            if "e" in error_holder:
                raise error_holder["e"]
            captured = captured_holder["data"]
        except Exception as exc:
            log.warning("probe failed for %s: %s", route.name, exc)
            return ProbeResult(
                name=route.name,
                sink_name=route.sink_name,
                monitor_source=route.monitor_source,
                outcome=ProbeOutcome.ERROR,
                detection=None,
                error=str(exc),
                timestamp_utc=ts,
            )

        detection = detect_marker_in_capture(
            captured,
            self.marker_freq_hz,
            sample_rate=self.sample_rate,
        )
        outcome = ProbeOutcome.DETECTED if detection.detected else ProbeOutcome.NOT_DETECTED
        return ProbeResult(
            name=route.name,
            sink_name=route.sink_name,
            monitor_source=route.monitor_source,
            outcome=outcome,
            detection=detection,
            error=None,
            timestamp_utc=ts,
        )

    @staticmethod
    def _shape_for_channels(mono: np.ndarray, channels: int) -> np.ndarray:
        """Replicate a mono tone across ``channels`` for multi-channel sinks.

        Returns a 2D ``(T, C)`` array when ``channels > 1`` so
        :func:`_default_inject` interleaves samples in C order. Mono
        passthrough returns the input unchanged.
        """
        if channels < 1:
            raise ValueError(f"channels must be >= 1; got {channels}")
        if channels == 1:
            return mono
        return np.tile(mono.reshape(-1, 1), (1, channels))

    def _emit(self, result: ProbeResult) -> None:
        record_probe(result.name, result.outcome.value)
        self._append_jsonl(result)

    def _append_jsonl(self, result: ProbeResult) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        date = self._clock().strftime("%Y-%m-%d")
        path = self.state_dir / f"{date}.jsonl"
        row: dict[str, object] = {
            "ts": result.timestamp_utc,
            "route": result.name,
            "sink": result.sink_name,
            "source": result.monitor_source,
            "outcome": result.outcome.value,
        }
        if result.detection is not None:
            row["snr_db"] = result.detection.snr_db
            row["peak_freq_hz"] = result.detection.peak_freq_hz
            row["target_freq_hz"] = result.detection.target_freq_hz
            row["failure_reason"] = result.detection.failure_reason
        if result.error is not None:
            row["error"] = result.error
        with path.open("a") as fh:
            fh.write(json.dumps(row) + "\n")

    def prune_old_files(self) -> int:
        """Delete JSONL files older than :data:`RETENTION_DAYS` days. Return count."""
        if not self.state_dir.exists():
            return 0
        now = self._clock()
        removed = 0
        for path in self.state_dir.glob("*.jsonl"):
            try:
                date = datetime.strptime(path.stem, "%Y-%m-%d").replace(tzinfo=UTC)
            except ValueError:
                continue
            age_days = (now - date).days
            if age_days > RETENTION_DAYS:
                path.unlink()
                removed += 1
        return removed

    def run_once(self) -> list[ProbeResult]:
        """Probe every configured route, emit evidence, return results."""
        results = [self._probe_route(r) for r in self.routes]
        for r in results:
            self._emit(r)
        self.prune_old_files()
        return results


def load_routes_from_env() -> list[RouteSpec]:
    """Load routes from the BROADCAST_AUDIO_HEALTH_ROUTES env var.

    Format: comma-separated entries ``name:sink:monitor_source[:channels]``.
    The optional 4th ``channels`` field declares how many channels
    the inject should send to a multi-channel sink (default 1).
    Used by the systemd unit so configuration is declarative without
    a YAML loader dep.
    """
    raw = os.environ.get("BROADCAST_AUDIO_HEALTH_ROUTES", "").strip()
    if not raw:
        return []
    routes: list[RouteSpec] = []
    for entry in raw.split(","):
        parts = entry.strip().split(":")
        if len(parts) == 3:
            routes.append(RouteSpec(name=parts[0], sink_name=parts[1], monitor_source=parts[2]))
        elif len(parts) == 4:
            try:
                channels = int(parts[3])
            except ValueError as e:
                raise ValueError(
                    f"invalid channels in route entry {entry!r}; want integer >= 1"
                ) from e
            routes.append(
                RouteSpec(
                    name=parts[0],
                    sink_name=parts[1],
                    monitor_source=parts[2],
                    inject_channels=channels,
                )
            )
        else:
            raise ValueError(
                f"invalid route entry {entry!r}; want name:sink:monitor_source[:channels]"
            )
    return routes
