"""Audio energy perception backend — RMS energy and onset detection.

Captures audio from a specific PipeWire node via ``pw-record`` subprocess,
computes RMS energy and onset detection in a background reader thread,
and writes source-qualified Behaviors on each ``contribute()`` call.

Supports source parameterization: ``AudioEnergyBackend("monitor_mix", target="42")``
writes to ``audio_energy_rms:monitor_mix`` instead of ``audio_energy_rms``.

When no ``target`` is provided, operates as a stub (``available() → False``).
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
import time

import numpy as np

from agents.hapax_voice.perception import PerceptionTier
from agents.hapax_voice.primitives import Behavior
from agents.hapax_voice.source_naming import qualify, validate_source_id

log = logging.getLogger(__name__)

_BASE_NAMES = ("audio_energy_rms", "audio_onset")

# Audio capture parameters
SAMPLE_RATE = 48000
CHANNELS = 1
CHUNK_SAMPLES = 2048  # ~43ms at 48kHz
CHUNK_BYTES = CHUNK_SAMPLES * 4  # float32 = 4 bytes per sample

# Analysis parameters
EMA_ALPHA = 0.2  # ~250ms effective response time
RUNNING_MAX_WINDOW_S = 10.0  # adaptive normalization window
ONSET_THRESHOLD = 0.3  # spectral flux threshold for onset detection


def discover_node(target: str) -> int | None:
    """Find a PipeWire node by ID, name, or description substring.

    Runs ``pw-dump``, parses JSON, returns numeric node ID or None.

    Args:
        target: A numeric node ID, a node.name, or a substring to match
                against node.description.
    """
    try:
        result = subprocess.run(
            ["pw-dump"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        objects = json.loads(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None

    # Try numeric ID first
    try:
        node_id = int(target)
        for obj in objects:
            if obj.get("id") == node_id and obj.get("type") == "PipeWire:Interface:Node":
                return node_id
    except ValueError:
        pass

    # Search by node.name or node.description
    for obj in objects:
        if obj.get("type") != "PipeWire:Interface:Node":
            continue
        props = obj.get("info", {}).get("props", {})
        node_name = props.get("node.name", "")
        node_desc = props.get("node.description", "")
        if target == node_name or target in node_desc:
            return obj.get("id")

    return None


class _AudioReader:
    """Background thread that reads pw-record stdout and computes audio features.

    Thread-safe: ``contribute()`` reads from attributes that the reader
    thread writes. Python's GIL makes float/bool assignment atomic for
    CPython scalar types.
    """

    def __init__(self, node_id: int) -> None:
        self._node_id = node_id
        self._process: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._running = False

        # Latest computed values (read by contribute, written by reader thread)
        self.rms: float = 0.0
        self.onset: bool = False
        self.last_update: float = 0.0

        # Internal state (reader thread only)
        self._smoothed_rms: float = 0.0
        self._running_max: float = 1e-6  # avoid div-by-zero
        self._max_history: list[tuple[float, float]] = []  # (time, rms) pairs
        self._prev_magnitude: np.ndarray | None = None

    def start(self) -> None:
        """Launch pw-record subprocess and reader thread."""
        self._running = True
        self._process = subprocess.Popen(
            [
                "pw-record",
                "--target",
                str(self._node_id),
                "--format",
                "f32",
                "--rate",
                str(SAMPLE_RATE),
                "--channels",
                str(CHANNELS),
                "-",  # stdout
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._thread = threading.Thread(
            target=self._read_loop,
            name=f"audio-reader-{self._node_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Terminate subprocess and join reader thread."""
        self._running = False
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=2)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _read_loop(self) -> None:
        """Continuously read chunks from pw-record and compute features."""
        assert self._process is not None
        assert self._process.stdout is not None
        try:
            while self._running:
                data = self._process.stdout.read(CHUNK_BYTES)
                if not data or len(data) < CHUNK_BYTES:
                    if self._running:
                        log.warning("pw-record EOF or short read for node %d", self._node_id)
                    break
                self._process_chunk(data)
        except Exception:
            if self._running:
                log.exception("Audio reader error for node %d", self._node_id)

    def _process_chunk(self, data: bytes) -> None:
        """Compute RMS and onset from a raw float32 PCM chunk."""
        now = time.monotonic()
        samples = np.frombuffer(data, dtype=np.float32)

        # Raw RMS
        raw_rms = float(np.sqrt(np.mean(samples**2)))

        # EMA smoothing
        self._smoothed_rms = EMA_ALPHA * raw_rms + (1 - EMA_ALPHA) * self._smoothed_rms

        # Update running max (adaptive normalization over last 10s)
        self._max_history.append((now, raw_rms))
        cutoff = now - RUNNING_MAX_WINDOW_S
        self._max_history = [(t, v) for t, v in self._max_history if t >= cutoff]
        window_max = max(v for _, v in self._max_history) if self._max_history else 1e-6
        self._running_max = max(window_max, 1e-6)

        # Normalize to 0.0-1.0
        normalized = min(self._smoothed_rms / self._running_max, 1.0)

        # Onset detection via spectral flux
        magnitude = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
        onset = False
        if self._prev_magnitude is not None:
            flux = float(np.sum(np.maximum(magnitude - self._prev_magnitude, 0.0)))
            # Normalize flux by spectrum size for threshold stability
            flux /= len(magnitude)
            onset = flux > ONSET_THRESHOLD
        self._prev_magnitude = magnitude

        # Publish (atomic under GIL for scalar types)
        self.rms = normalized
        self.onset = onset
        self.last_update = now


class AudioEnergyBackend:
    """PerceptionBackend for audio energy analysis via PipeWire.

    Provides:
      - audio_energy_rms: float (0.0-1.0, EMA-smoothed, adaptively normalized)
      - audio_onset: bool (True on transient onset detection via spectral flux)

    When ``source_id`` is provided, all behavior names are source-qualified.
    When ``target`` is provided, captures from the specified PipeWire node.
    Without ``target``, operates as a stub (``available() → False``).
    """

    def __init__(self, source_id: str | None = None, target: str | None = None) -> None:
        if source_id is not None:
            validate_source_id(source_id)
        self._source_id = source_id
        self._target = target
        self._reader: _AudioReader | None = None
        self._node_id: int | None = None

        # Internal Behaviors for contribute()
        self._b_rms: Behavior[float] = Behavior(0.0)
        self._b_onset: Behavior[bool] = Behavior(False)

    @property
    def name(self) -> str:
        if self._source_id:
            return f"audio_energy:{self._source_id}"
        return "audio_energy"

    @property
    def provides(self) -> frozenset[str]:
        if self._source_id:
            return frozenset(qualify(b, self._source_id) for b in _BASE_NAMES)
        return frozenset(_BASE_NAMES)

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.FAST

    def available(self) -> bool:
        """Check if pw-record exists and the target node is discoverable."""
        if self._target is None:
            return False
        if shutil.which("pw-record") is None:
            return False
        node_id = discover_node(self._target)
        if node_id is None:
            return False
        self._node_id = node_id
        return True

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        """Read latest values from the reader thread and write to Behaviors."""
        if self._reader is None:
            return
        now = self._reader.last_update
        if now <= 0:
            return  # no data yet

        self._b_rms.update(self._reader.rms, now)
        self._b_onset.update(self._reader.onset, now)

        # Write to shared behaviors dict
        if self._source_id:
            behaviors[qualify("audio_energy_rms", self._source_id)] = self._b_rms
            behaviors[qualify("audio_onset", self._source_id)] = self._b_onset
        else:
            behaviors["audio_energy_rms"] = self._b_rms
            behaviors["audio_onset"] = self._b_onset

    def start(self) -> None:
        if self._node_id is None:
            log.warning("AudioEnergy backend %s: no node ID, cannot start", self.name)
            return
        self._reader = _AudioReader(self._node_id)
        self._reader.start()
        log.info("AudioEnergy backend started: %s (node %d)", self.name, self._node_id)

    def stop(self) -> None:
        if self._reader is not None:
            self._reader.stop()
            self._reader = None
        log.info("AudioEnergy backend stopped: %s", self.name)
