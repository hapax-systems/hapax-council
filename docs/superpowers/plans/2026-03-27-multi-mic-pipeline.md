# Multi-Mic Audio Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace PyAudio noise reference capture with pw-record multi-source capture, add enrollment quality validation, and benchmark TSE models for real-time viability.

**Architecture:** Three layers touching the voice pipeline. Layer 1 rewrites `multi_mic.py` capture internals (pw-record subprocesses, multi-source averaging). Layer 2 adds validation math to `enrollment.py`. Layer 3 creates a standalone benchmark script. Single PR.

**Tech Stack:** Python 3.12, numpy, PipeWire (pw-record, pactl), SpeechBrain, Asteroid, pyannote, ECAPA-TDNN

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `agents/hapax_voice/multi_mic.py` | Rewrite | pw-record capture, multi-source noise averaging |
| `agents/hapax_voice/enrollment.py` | Modify | Add validation phase + stability report |
| `agents/hapax_voice/config.py` | Modify | Add `noise_ref_room_patterns`, `noise_ref_structure_patterns` |
| `agents/hapax_voice/__main__.py` | Modify | Pass new config fields to NoiseReference |
| `agents/hapax_voice/tse_benchmark.py` | Create | Standalone TSE benchmark script |
| `tests/hapax_voice/test_multi_mic.py` | Create | Tests for multi-source averaging |
| `tests/hapax_voice/test_enrollment_validation.py` | Create | Tests for enrollment validation math |

---

### Task 1: Add config fields for noise reference patterns

**Files:**
- Modify: `agents/hapax_voice/config.py:69-70`

- [ ] **Step 1: Add noise reference config fields**

In `agents/hapax_voice/config.py`, after line 70 (`contact_mic_source: str = "Contact Microphone"`), add:

```python
    # Multi-mic noise reference patterns (substring match against PipeWire source names)
    noise_ref_room_patterns: list[str] = ["HD Pro Webcam C920", "Logitech BRIO"]
    noise_ref_structure_patterns: list[str] = ["Contact Microphone"]
```

- [ ] **Step 2: Verify config loads**

Run: `cd ~/projects/hapax-council && uv run python -c "from agents.hapax_voice.config import VoiceConfig; c = VoiceConfig(); print(c.noise_ref_room_patterns, c.noise_ref_structure_patterns)"`

Expected: `['HD Pro Webcam C920', 'Logitech BRIO'] ['Contact Microphone']`

- [ ] **Step 3: Commit**

```bash
git add agents/hapax_voice/config.py
git commit -m "feat(voice): add noise_ref_room_patterns and noise_ref_structure_patterns config"
```

---

### Task 2: Write tests for multi-source noise averaging

**Files:**
- Create: `tests/hapax_voice/test_multi_mic.py`

- [ ] **Step 1: Write test file**

Create `tests/hapax_voice/test_multi_mic.py`:

```python
"""Tests for multi-mic noise reference subtraction."""

from __future__ import annotations

import numpy as np
import pytest


def _make_pcm_frame(freq_hz: float = 440.0, sample_rate: int = 16000, n_samples: int = 512) -> bytes:
    """Generate a pure-tone PCM int16 frame."""
    t = np.arange(n_samples) / sample_rate
    samples = (np.sin(2 * np.pi * freq_hz * t) * 16000).astype(np.int16)
    return samples.tobytes()


class TestApplySubtraction:
    """Test the static spectral subtraction math."""

    def test_subtraction_reduces_magnitude(self):
        from agents.hapax_voice.multi_mic import NoiseReference

        mag = np.array([10.0, 20.0, 30.0])
        noise = np.array([5.0, 10.0, 15.0])
        result = NoiseReference._apply_subtraction(mag, noise, alpha=1.0, beta=0.01)
        expected = np.maximum(mag - noise, 0.01 * mag)
        np.testing.assert_array_almost_equal(result, expected)

    def test_subtraction_floors_at_beta(self):
        from agents.hapax_voice.multi_mic import NoiseReference

        mag = np.array([10.0, 10.0])
        noise = np.array([100.0, 100.0])  # noise >> signal
        result = NoiseReference._apply_subtraction(mag, noise, alpha=1.5, beta=0.01)
        expected = 0.01 * mag  # floored
        np.testing.assert_array_almost_equal(result, expected)

    def test_subtraction_none_noise_is_passthrough(self):
        from agents.hapax_voice.multi_mic import NoiseReference

        mag = np.array([10.0, 20.0])
        result = NoiseReference._apply_subtraction(mag, None, alpha=1.5, beta=0.01)
        np.testing.assert_array_equal(result, mag)

    def test_subtraction_mismatched_length_is_passthrough(self):
        from agents.hapax_voice.multi_mic import NoiseReference

        mag = np.array([10.0, 20.0])
        noise = np.array([5.0])  # wrong length
        result = NoiseReference._apply_subtraction(mag, noise, alpha=1.5, beta=0.01)
        np.testing.assert_array_equal(result, mag)


class TestMultiSourceAveraging:
    """Test that multiple room estimates are averaged correctly."""

    def test_averaged_noise_estimate_from_multiple_sources(self):
        from agents.hapax_voice.multi_mic import NoiseReference

        ref = NoiseReference(room_sources=[], structure_sources=[], sample_rate=16000)

        # Simulate two room sources with different noise profiles
        est_a = np.array([10.0, 20.0, 30.0])
        est_b = np.array([20.0, 10.0, 40.0])
        ref._room_estimates["c920-1"] = est_a
        ref._room_estimates["c920-2"] = est_b

        avg = ref._averaged_room_estimate()
        expected = (est_a + est_b) / 2.0
        np.testing.assert_array_almost_equal(avg, expected)

    def test_averaged_noise_estimate_single_source(self):
        from agents.hapax_voice.multi_mic import NoiseReference

        ref = NoiseReference(room_sources=[], structure_sources=[], sample_rate=16000)
        est = np.array([10.0, 20.0])
        ref._room_estimates["c920-1"] = est

        avg = ref._averaged_room_estimate()
        np.testing.assert_array_equal(avg, est)

    def test_averaged_noise_estimate_empty(self):
        from agents.hapax_voice.multi_mic import NoiseReference

        ref = NoiseReference(room_sources=[], structure_sources=[], sample_rate=16000)
        assert ref._averaged_room_estimate() is None

    def test_subtract_uses_averaged_room_estimate(self):
        from agents.hapax_voice.multi_mic import NoiseReference

        ref = NoiseReference(room_sources=[], structure_sources=[], sample_rate=16000)

        # Set up two room estimates with known noise at all frequencies
        fft_size = 512
        n_bins = fft_size // 2 + 1
        ref._room_estimates["c920-1"] = np.ones(n_bins) * 5.0
        ref._room_estimates["c920-2"] = np.ones(n_bins) * 15.0
        # Average should be 10.0

        # Generate a tone frame and process it
        frame = _make_pcm_frame(440.0, 16000, fft_size)
        result = ref.subtract(frame)

        # Result should differ from input (noise was subtracted)
        assert result != frame

    def test_subtract_passthrough_when_no_estimates(self):
        from agents.hapax_voice.multi_mic import NoiseReference

        ref = NoiseReference(room_sources=[], structure_sources=[], sample_rate=16000)
        frame = _make_pcm_frame(440.0, 16000, 512)
        result = ref.subtract(frame)
        assert result == frame


class TestSourceDiscovery:
    """Test PipeWire source enumeration."""

    def test_discover_sources_matches_patterns(self):
        from agents.hapax_voice.multi_mic import discover_pipewire_sources

        # Mock pactl output
        pactl_output = (
            "99\talsa_input.usb-046d_HD_Pro_Webcam_C920_86B6B75F-02.analog-stereo\tPipeWire\n"
            "123\talsa_input.usb-046d_HD_Pro_Webcam_C920_7B88C71F-02.analog-stereo\tPipeWire\n"
            "124\talsa_input.usb-046d_Logitech_BRIO_9726C031-03.analog-stereo\tPipeWire\n"
            "130\talsa_output.pci-0000_0c_00.4.iec958-stereo.monitor\tPipeWire\n"
        )
        patterns = ["HD Pro Webcam C920", "Logitech BRIO"]
        sources = discover_pipewire_sources(patterns, _pactl_output=pactl_output)

        assert len(sources) == 3
        assert all("C920" in s or "BRIO" in s for s in sources)

    def test_discover_sources_no_matches(self):
        from agents.hapax_voice.multi_mic import discover_pipewire_sources

        pactl_output = "130\talsa_output.pci-0000_0c_00.4.iec958-stereo.monitor\tPipeWire\n"
        sources = discover_pipewire_sources(["HD Pro Webcam C920"], _pactl_output=pactl_output)
        assert sources == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/projects/hapax-council && uv run pytest tests/hapax_voice/test_multi_mic.py -v 2>&1 | tail -20`

Expected: FAIL — `_room_estimates`, `_averaged_room_estimate`, and `discover_pipewire_sources` don't exist yet.

- [ ] **Step 3: Commit**

```bash
git add tests/hapax_voice/test_multi_mic.py
git commit -m "test(voice): add multi-mic noise averaging tests (red)"
```

---

### Task 3: Rewrite multi_mic.py with pw-record and multi-source averaging

**Files:**
- Rewrite: `agents/hapax_voice/multi_mic.py`

- [ ] **Step 1: Rewrite multi_mic.py**

Replace the entire contents of `agents/hapax_voice/multi_mic.py` with:

```python
"""Multi-microphone noise reference subtraction.

Uses C920 webcam mics and BRIO as ambient noise reference channels. The Yeti
captures operator voice + room noise. The reference mics capture mostly room
noise (they're farther from the operator). Subtracting the reference signal
from the Yeti reduces echo, ambient, and speaker bleed-through.

Optionally uses a contact microphone (e.g. Cortado MkIII) for
structure-borne noise reference — desk vibrations, keyboard impacts,
mechanical rumble. Structure-borne subtraction runs first (alpha=1.0,
conservative) then airborne subtraction (alpha=1.5, aggressive).

This is spectral subtraction, not beamforming — no array geometry
needed. Works with arbitrary mic placement.

Capture uses pw-record subprocesses (one per source) instead of PyAudio,
eliminating the pactl default-source conflict and supporting all available
PipeWire sources by name.

Usage:
    sources = discover_pipewire_sources(["HD Pro Webcam C920", "Logitech BRIO"])
    ref = NoiseReference(
        room_sources=sources,
        structure_sources=["Contact Microphone"],
    )
    ref.start()
    # ... in audio loop:
    cleaned = ref.subtract(yeti_frame)
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time

import numpy as np

log = logging.getLogger(__name__)

# Spectral subtraction parameters
_FFT_SIZE = 512
_HOP_SIZE = 256
_SMOOTHING = 0.7  # noise estimate smoothing (0=no smoothing, 1=never update)

# Airborne subtraction (room mics — aggressive, removes ambient + echo)
_AIRBORNE_ALPHA = 1.5  # oversubtraction factor
_AIRBORNE_BETA = 0.01  # spectral floor

# Structure-borne subtraction (contact mic — conservative, removes desk/keyboard rumble)
_STRUCTURE_ALPHA = 1.0  # less aggressive (contact mic signal is already clean)
_STRUCTURE_BETA = 0.02  # slightly higher floor (preserve transient detail)

_FRAME_BYTES = _FFT_SIZE * 2  # int16 = 2 bytes per sample


def discover_pipewire_sources(
    patterns: list[str],
    *,
    _pactl_output: str | None = None,
) -> list[str]:
    """Enumerate PipeWire sources matching any of the given substring patterns.

    Returns a list of full PipeWire source names (e.g.
    "alsa_input.usb-046d_HD_Pro_Webcam_C920_86B6B75F-02.analog-stereo").

    Args:
        patterns: Substrings to match against source names.
        _pactl_output: Override for testing (skip subprocess call).
    """
    if _pactl_output is None:
        try:
            result = subprocess.run(
                ["pactl", "list", "sources", "short"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            _pactl_output = result.stdout
        except Exception:
            log.warning("Failed to enumerate PipeWire sources via pactl")
            return []

    matched: list[str] = []
    for line in _pactl_output.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        source_name = parts[1]
        for pattern in patterns:
            if pattern in source_name:
                matched.append(source_name)
                break
    return matched


class NoiseReference:
    """Captures room noise from reference mics and subtracts from primary mic.

    Each reference source is captured via a pw-record subprocess writing
    raw PCM s16le mono to stdout. One daemon thread per source reads frames
    and updates the noise estimate with STFT + exponential smoothing.

    Multiple room sources are averaged into a single airborne noise estimate.
    """

    def __init__(
        self,
        room_sources: list[str] | None = None,
        structure_sources: list[str] | None = None,
        sample_rate: int = 16000,
    ) -> None:
        self._room_sources = room_sources or []
        self._structure_sources = structure_sources or []
        self._sample_rate = sample_rate
        self._running = False
        self._threads: list[threading.Thread] = []
        self._processes: list[subprocess.Popen] = []

        # Per-source airborne noise estimates (averaged in subtract())
        self._room_estimates: dict[str, np.ndarray] = {}
        self._room_lock = threading.Lock()

        # Structure-borne noise estimate (single contact mic)
        self._structure_noise_estimate: np.ndarray | None = None
        self._structure_lock = threading.Lock()

    def start(self) -> None:
        """Start capturing from reference microphones via pw-record."""
        if not self._room_sources and not self._structure_sources:
            log.info("No reference sources configured — noise subtraction disabled")
            return

        if not shutil.which("pw-record"):
            log.warning("pw-record not found — noise subtraction disabled")
            return

        self._running = True
        for source in self._room_sources:
            t = threading.Thread(
                target=self._capture_loop,
                args=(source,),
                kwargs={"is_structure": False},
                daemon=True,
                name=f"noise-ref-{source[:30]}",
            )
            t.start()
            self._threads.append(t)
        for source in self._structure_sources:
            t = threading.Thread(
                target=self._capture_loop,
                args=(source,),
                kwargs={"is_structure": True},
                daemon=True,
                name=f"struct-ref-{source[:30]}",
            )
            t.start()
            self._threads.append(t)
        log.info(
            "Noise reference started with %d room + %d structure source(s)",
            len(self._room_sources),
            len(self._structure_sources),
        )

    def stop(self) -> None:
        """Stop all capture threads and terminate pw-record subprocesses."""
        self._running = False
        for proc in self._processes:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._processes.clear()
        for t in self._threads:
            t.join(timeout=2)
        self._threads.clear()

    def _averaged_room_estimate(self) -> np.ndarray | None:
        """Average all per-source room noise estimates into one spectrum."""
        with self._room_lock:
            estimates = list(self._room_estimates.values())
        if not estimates:
            return None
        return np.mean(estimates, axis=0)

    @staticmethod
    def _apply_subtraction(
        mag: np.ndarray,
        noise_mag: np.ndarray | None,
        alpha: float,
        beta: float,
    ) -> np.ndarray:
        """Spectral subtraction: mag - alpha*noise, floored at beta*mag."""
        if noise_mag is not None and len(noise_mag) == len(mag):
            return np.maximum(mag - alpha * noise_mag, beta * mag)
        return mag

    def subtract(self, frame: bytes) -> bytes:
        """Apply spectral subtraction to a primary mic frame.

        Structure-borne subtraction runs first (conservative), then airborne
        subtraction (aggressive). This order prevents structure rumble from
        being misattributed to airborne noise.

        Args:
            frame: Raw PCM int16 mono audio frame from the Yeti.

        Returns:
            Cleaned PCM int16 mono audio frame.
        """
        room_est = self._averaged_room_estimate()
        with self._structure_lock:
            structure_est = self._structure_noise_estimate

        if room_est is None and structure_est is None:
            return frame  # no reference data yet — pass through

        # Convert to float
        samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        if len(samples) < _FFT_SIZE:
            return frame

        # STFT of input
        window = np.hanning(_FFT_SIZE)
        spec = np.fft.rfft(samples[:_FFT_SIZE] * window)
        mag = np.abs(spec)
        phase = np.angle(spec)

        # 1. Structure-borne subtraction (contact mic — conservative)
        mag = self._apply_subtraction(mag, structure_est, _STRUCTURE_ALPHA, _STRUCTURE_BETA)

        # 2. Airborne subtraction (room mics — aggressive, averaged)
        mag = self._apply_subtraction(mag, room_est, _AIRBORNE_ALPHA, _AIRBORNE_BETA)

        # Reconstruct
        clean_spec = mag * np.exp(1j * phase)
        clean_samples = np.fft.irfft(clean_spec)[: len(samples)]

        # Convert back to int16
        clean_int16 = np.clip(clean_samples, -32768, 32767).astype(np.int16)
        return clean_int16.tobytes()

    def _capture_loop(self, source: str, *, is_structure: bool = False) -> None:
        """Continuously capture from a reference mic via pw-record.

        Starts a pw-record subprocess targeting the named PipeWire source.
        Reads raw PCM s16le mono frames from stdout and updates the noise
        estimate with STFT + exponential smoothing.

        On subprocess death, waits 2s and restarts.

        Args:
            source: Full PipeWire source name (e.g. "alsa_input.usb-...").
            is_structure: If True, updates structure-borne estimate.
        """
        kind = "structure" if is_structure else "room"

        while self._running:
            try:
                proc = subprocess.Popen(
                    [
                        "pw-record",
                        "--target", source,
                        "--format", "s16",
                        "--rate", str(self._sample_rate),
                        "--channels", "1",
                        "-",  # stdout
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                self._processes.append(proc)
                log.info(
                    "Noise reference capturing from %s source: %s (pid %d)",
                    kind,
                    source,
                    proc.pid,
                )

                while self._running and proc.poll() is None:
                    data = proc.stdout.read(_FRAME_BYTES)
                    if not data or len(data) < _FRAME_BYTES:
                        break

                    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                    window = np.hanning(_FFT_SIZE)
                    spec = np.fft.rfft(samples * window)
                    mag = np.abs(spec)

                    if is_structure:
                        with self._structure_lock:
                            if self._structure_noise_estimate is None:
                                self._structure_noise_estimate = mag
                            else:
                                self._structure_noise_estimate = (
                                    _SMOOTHING * self._structure_noise_estimate
                                    + (1 - _SMOOTHING) * mag
                                )
                    else:
                        with self._room_lock:
                            if source not in self._room_estimates:
                                self._room_estimates[source] = mag
                            else:
                                self._room_estimates[source] = (
                                    _SMOOTHING * self._room_estimates[source]
                                    + (1 - _SMOOTHING) * mag
                                )

                # Cleanup
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    pass
                if proc in self._processes:
                    self._processes.remove(proc)

            except Exception:
                log.debug(
                    "Noise reference capture failed for %s (%s)", source, kind, exc_info=True
                )

            # Restart delay (unless we're stopping)
            if self._running:
                log.warning("Noise reference %s source %s died, restarting in 2s", kind, source)
                time.sleep(2)
```

- [ ] **Step 2: Run tests**

Run: `cd ~/projects/hapax-council && uv run pytest tests/hapax_voice/test_multi_mic.py -v`

Expected: All tests PASS.

- [ ] **Step 3: Run ruff**

Run: `cd ~/projects/hapax-council && uv run ruff check agents/hapax_voice/multi_mic.py && uv run ruff format --check agents/hapax_voice/multi_mic.py`

Expected: Clean.

- [ ] **Step 4: Commit**

```bash
git add agents/hapax_voice/multi_mic.py
git commit -m "feat(voice): rewrite multi_mic.py with pw-record and multi-source averaging"
```

---

### Task 4: Wire new config into __main__.py

**Files:**
- Modify: `agents/hapax_voice/__main__.py:317-328`

- [ ] **Step 1: Update NoiseReference initialization**

In `agents/hapax_voice/__main__.py`, replace lines 317-328:

```python
        # Multi-mic noise reference (C920 webcam mics as ambient reference)
        from agents.hapax_voice.multi_mic import NoiseReference

        self._noise_reference = NoiseReference(
            room_sources=[
                "HD Pro Webcam C920",  # any C920 mic — airborne noise reference
            ],
            structure_sources=[
                self.cfg.contact_mic_source,  # Cortado contact mic — structure-borne reference
            ],
        )
        self._noise_reference.start()
```

With:

```python
        # Multi-mic noise reference (pw-record capture from all matching sources)
        from agents.hapax_voice.multi_mic import NoiseReference, discover_pipewire_sources

        _room_sources = discover_pipewire_sources(self.cfg.noise_ref_room_patterns)
        _structure_sources = discover_pipewire_sources(self.cfg.noise_ref_structure_patterns)
        log.info(
            "Noise reference sources: %d room (%s), %d structure (%s)",
            len(_room_sources),
            _room_sources,
            len(_structure_sources),
            _structure_sources,
        )
        self._noise_reference = NoiseReference(
            room_sources=_room_sources,
            structure_sources=_structure_sources,
        )
        self._noise_reference.start()
```

- [ ] **Step 2: Verify import works**

Run: `cd ~/projects/hapax-council && uv run python -c "from agents.hapax_voice.multi_mic import NoiseReference, discover_pipewire_sources; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add agents/hapax_voice/__main__.py
git commit -m "feat(voice): wire multi-source discovery into daemon startup"
```

---

### Task 5: Write tests for enrollment validation

**Files:**
- Create: `tests/hapax_voice/test_enrollment_validation.py`

- [ ] **Step 1: Write test file**

Create `tests/hapax_voice/test_enrollment_validation.py`:

```python
"""Tests for enrollment quality validation math."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np


def _random_unit_vector(dim: int = 512, rng: np.random.Generator | None = None) -> np.ndarray:
    """Generate a random unit vector."""
    if rng is None:
        rng = np.random.default_rng(42)
    v = rng.standard_normal(dim)
    return v / np.linalg.norm(v)


def _similar_vectors(base: np.ndarray, n: int, noise_scale: float = 0.1) -> list[np.ndarray]:
    """Generate n vectors similar to base with controlled noise."""
    rng = np.random.default_rng(42)
    vectors = []
    for _ in range(n):
        noisy = base + rng.standard_normal(base.shape) * noise_scale
        noisy = noisy / np.linalg.norm(noisy)
        vectors.append(noisy)
    return vectors


class TestPairwiseSimilarity:
    def test_identical_vectors_have_similarity_one(self):
        from agents.hapax_voice.enrollment import compute_pairwise_similarity

        v = _random_unit_vector()
        embeddings = [v, v, v]
        stats = compute_pairwise_similarity(embeddings)
        assert abs(stats["mean"] - 1.0) < 0.001
        assert abs(stats["stddev"]) < 0.001

    def test_orthogonal_vectors_have_low_similarity(self):
        from agents.hapax_voice.enrollment import compute_pairwise_similarity

        dim = 512
        e1 = np.zeros(dim)
        e1[0] = 1.0
        e2 = np.zeros(dim)
        e2[1] = 1.0
        e3 = np.zeros(dim)
        e3[2] = 1.0
        stats = compute_pairwise_similarity([e1, e2, e3])
        assert stats["mean"] < 0.01
        assert stats["min"] < 0.01

    def test_similar_vectors_have_high_mean(self):
        from agents.hapax_voice.enrollment import compute_pairwise_similarity

        base = _random_unit_vector()
        embeddings = _similar_vectors(base, 10, noise_scale=0.1)
        stats = compute_pairwise_similarity(embeddings)
        assert stats["mean"] > 0.7
        assert stats["stddev"] < 0.15

    def test_returns_correct_keys(self):
        from agents.hapax_voice.enrollment import compute_pairwise_similarity

        base = _random_unit_vector()
        embeddings = _similar_vectors(base, 5, noise_scale=0.1)
        stats = compute_pairwise_similarity(embeddings)
        assert set(stats.keys()) == {"min", "max", "mean", "stddev"}

    def test_two_embeddings(self):
        from agents.hapax_voice.enrollment import compute_pairwise_similarity

        base = _random_unit_vector()
        embeddings = _similar_vectors(base, 2, noise_scale=0.1)
        stats = compute_pairwise_similarity(embeddings)
        assert abs(stats["min"] - stats["max"]) < 0.001
        assert abs(stats["stddev"]) < 0.001


class TestOutlierDetection:
    def test_no_outliers_in_clean_set(self):
        from agents.hapax_voice.enrollment import detect_outliers

        base = _random_unit_vector()
        embeddings = _similar_vectors(base, 10, noise_scale=0.1)
        outliers = detect_outliers(embeddings, threshold=0.50)
        assert outliers == []

    def test_detects_orthogonal_outlier(self):
        from agents.hapax_voice.enrollment import detect_outliers

        base = _random_unit_vector(dim=512, rng=np.random.default_rng(42))
        good = _similar_vectors(base, 9, noise_scale=0.1)

        outlier = np.zeros(512)
        outlier[0] = 1.0
        embeddings = good + [outlier]

        outliers = detect_outliers(embeddings, threshold=0.50)
        assert 9 in outliers


class TestThresholdTest:
    def test_all_above_threshold(self):
        from agents.hapax_voice.enrollment import threshold_test

        base = _random_unit_vector()
        embeddings = _similar_vectors(base, 10, noise_scale=0.1)
        avg = np.mean(embeddings, axis=0)
        avg = avg / np.linalg.norm(avg)
        result = threshold_test(embeddings, avg, accept_threshold=0.60)
        assert result["samples_below_threshold"] == 0
        assert result["min_similarity_to_average"] > 0.60

    def test_returns_correct_keys(self):
        from agents.hapax_voice.enrollment import threshold_test

        base = _random_unit_vector()
        embeddings = _similar_vectors(base, 5, noise_scale=0.1)
        avg = np.mean(embeddings, axis=0)
        avg = avg / np.linalg.norm(avg)
        result = threshold_test(embeddings, avg, accept_threshold=0.60)
        assert set(result.keys()) == {
            "accept_threshold",
            "samples_below_threshold",
            "min_similarity_to_average",
        }


class TestStabilityReport:
    def test_report_written_to_json(self):
        from agents.hapax_voice.enrollment import write_stability_report

        base = _random_unit_vector()
        embeddings = _similar_vectors(base, 10, noise_scale=0.1)
        avg = np.mean(embeddings, axis=0)
        avg = avg / np.linalg.norm(avg)

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "enrollment_report.json"
            write_stability_report(embeddings, avg, report_path, dropped_count=1)

            assert report_path.exists()
            report = json.loads(report_path.read_text())
            assert report["sample_count"] == 10
            assert report["dropped_samples"] == 1
            assert "pairwise_similarity" in report
            assert "threshold_test" in report
            assert "embedding_shape" in report
            assert "timestamp" in report
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/projects/hapax-council && uv run pytest tests/hapax_voice/test_enrollment_validation.py -v 2>&1 | tail -20`

Expected: FAIL — `compute_pairwise_similarity`, `detect_outliers`, `threshold_test`, `write_stability_report` don't exist yet.

- [ ] **Step 3: Commit**

```bash
git add tests/hapax_voice/test_enrollment_validation.py
git commit -m "test(voice): add enrollment validation tests (red)"
```

---

### Task 6: Add validation functions to enrollment.py

**Files:**
- Modify: `agents/hapax_voice/enrollment.py`

- [ ] **Step 1: Add imports**

In `agents/hapax_voice/enrollment.py`, after the existing imports (after line 22 `import numpy as np`), add:

```python
import json
from datetime import datetime, timezone
```

- [ ] **Step 2: Add validation functions**

After the `SAMPLE_DURATION_S = 5` line (line 31), add:

```python

ENROLLMENT_REPORT_PATH = ENROLLMENT_DIR / "enrollment_report.json"


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors."""
    dot = float(np.dot(a, b))
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def compute_pairwise_similarity(embeddings: list[np.ndarray]) -> dict[str, float]:
    """Compute pairwise cosine similarity statistics across all sample pairs.

    Returns dict with keys: min, max, mean, stddev.
    """
    n = len(embeddings)
    sims: list[float] = []
    for i in range(n):
        for j in range(i + 1, n):
            sims.append(_cosine_similarity(embeddings[i], embeddings[j]))
    if not sims:
        return {"min": 0.0, "max": 0.0, "mean": 0.0, "stddev": 0.0}
    arr = np.array(sims)
    return {
        "min": float(arr.min()),
        "max": float(arr.max()),
        "mean": float(arr.mean()),
        "stddev": float(arr.std()),
    }


def detect_outliers(embeddings: list[np.ndarray], threshold: float = 0.50) -> list[int]:
    """Find samples whose mean pairwise similarity to all others is below threshold.

    Returns list of indices of outlier samples.
    """
    n = len(embeddings)
    outliers: list[int] = []
    for i in range(n):
        sims = [
            _cosine_similarity(embeddings[i], embeddings[j])
            for j in range(n)
            if i != j
        ]
        if sims and np.mean(sims) < threshold:
            outliers.append(i)
    return outliers


def threshold_test(
    embeddings: list[np.ndarray],
    averaged: np.ndarray,
    accept_threshold: float = 0.60,
) -> dict[str, float | int]:
    """Test each sample's similarity to the averaged embedding against the accept threshold.

    Returns dict with keys: accept_threshold, samples_below_threshold, min_similarity_to_average.
    """
    sims = [_cosine_similarity(emb, averaged) for emb in embeddings]
    below = sum(1 for s in sims if s < accept_threshold)
    return {
        "accept_threshold": accept_threshold,
        "samples_below_threshold": below,
        "min_similarity_to_average": float(min(sims)) if sims else 0.0,
    }


def write_stability_report(
    embeddings: list[np.ndarray],
    averaged: np.ndarray,
    report_path: Path | None = None,
    dropped_count: int = 0,
) -> dict:
    """Compute and save enrollment stability report.

    Returns the report dict. Also saves to JSON at report_path.
    """
    path = report_path or ENROLLMENT_REPORT_PATH
    pairwise = compute_pairwise_similarity(embeddings)
    thresh = threshold_test(embeddings, averaged)

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sample_count": len(embeddings),
        "dropped_samples": dropped_count,
        "pairwise_similarity": pairwise,
        "threshold_test": thresh,
        "embedding_shape": list(averaged.shape),
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2))
    return report
```

- [ ] **Step 3: Add validation phase to main()**

In the `main()` function, replace lines 210-229 (from `if not embeddings:` to the final print block) with:

```python
    if not embeddings:
        print("ERROR: No embeddings extracted. Check pyannote/HF_TOKEN.")
        sys.exit(1)

    # Validation phase
    print()
    print("── Validation ──────────────────────────────────────")

    # Outlier detection
    outlier_indices = detect_outliers(embeddings, threshold=0.50)
    dropped_count = 0
    if outlier_indices:
        print(f"  Outliers detected at sample indices: {outlier_indices}")
        for idx in sorted(outlier_indices, reverse=True):
            resp = input(f"  Drop sample {idx + 1}? [y/N] ").strip().lower()
            if resp == "y":
                embeddings.pop(idx)
                dropped_count += 1
                print(f"  Dropped sample {idx + 1}")
    else:
        print("  No outliers detected")

    if not embeddings:
        print("ERROR: All samples dropped. Re-run enrollment.")
        sys.exit(1)

    # Average embeddings
    avg_embedding = np.mean(embeddings, axis=0)

    # Normalize
    norm = np.linalg.norm(avg_embedding)
    if norm > 0:
        avg_embedding = avg_embedding / norm

    # Stability report
    report = write_stability_report(embeddings, avg_embedding, dropped_count=dropped_count)
    pairwise = report["pairwise_similarity"]
    thresh = report["threshold_test"]

    print(
        f"  Pairwise similarity: mean={pairwise['mean']:.3f} "
        f"stddev={pairwise['stddev']:.3f} "
        f"[{pairwise['min']:.3f}, {pairwise['max']:.3f}]"
    )

    if pairwise["mean"] < 0.70:
        print("  WARNING: Mean pairwise similarity < 0.70 — enrollment may be noisy")
    if pairwise["stddev"] > 0.10:
        print("  WARNING: High variance — samples may be inconsistent")

    if thresh["samples_below_threshold"] > 0:
        print(
            f"  WARNING: {thresh['samples_below_threshold']} sample(s) below "
            f"accept threshold ({thresh['accept_threshold']})"
        )
        print(f"  Min similarity to average: {thresh['min_similarity_to_average']:.3f}")
    else:
        print(f"  All samples above accept threshold ({thresh['accept_threshold']})")

    print(f"  Report saved: {ENROLLMENT_REPORT_PATH}")
    print()

    # Save
    np.save(SPEAKER_EMBEDDING_PATH, avg_embedding)
    print("═══════════════════════════════════════════════════")
    print(f"  Speaker embedding saved: {SPEAKER_EMBEDDING_PATH}")
    print(f"    Averaged from {len(embeddings)} samples ({dropped_count} dropped)")
    print(f"    Shape: {avg_embedding.shape}")
    print(f"  Face embedding: {FACE_EMBEDDING_PATH}")
    print("═══════════════════════════════════════════════════")
```

- [ ] **Step 4: Run tests**

Run: `cd ~/projects/hapax-council && uv run pytest tests/hapax_voice/test_enrollment_validation.py -v`

Expected: All tests PASS.

- [ ] **Step 5: Run ruff**

Run: `cd ~/projects/hapax-council && uv run ruff check agents/hapax_voice/enrollment.py && uv run ruff format --check agents/hapax_voice/enrollment.py`

Expected: Clean.

- [ ] **Step 6: Commit**

```bash
git add agents/hapax_voice/enrollment.py
git commit -m "feat(voice): add enrollment quality validation with pairwise similarity and outlier detection"
```

---

### Task 7: Create TSE benchmark script

**Files:**
- Create: `agents/hapax_voice/tse_benchmark.py`

- [ ] **Step 1: Write benchmark script**

Create `agents/hapax_voice/tse_benchmark.py`. The script should:

1. Define dataclasses `BenchmarkResult` (model, device, frame_size_samples, latency_p50/p95/p99_ms, vram_delta_mb, error) and `BenchmarkReport` (results list, go_recommendation bool, recommended_model, recommended_device, notes list).

2. Helper functions:
   - `_get_vram_used_mb()` — calls `nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits`
   - `_get_vram_free_mb()` — calls `nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits`
   - `_make_test_mixture(n_samples, sample_rate=16000)` — synthetic tone + noise as float32
   - `_measure_latency(fn, n_runs=100)` — 3 warmup runs then 100 timed, returns (p50, p95, p99) in ms

3. Benchmark functions (each returns `BenchmarkResult`, catching all exceptions):
   - `benchmark_speechbrain_sepformer(device)` — loads `speechbrain/sepformer-wsj02mix`, downsamples 16k->8k for input, runs `separate_batch` on 500ms chunk
   - `benchmark_asteroid_convtasnet(device)` — loads `JorisCos/ConvTasNet_Libri2Mix_sepclean_16k` via `asteroid.models.ConvTasNet.from_pretrained`, runs on 500ms 16kHz chunk
   - `benchmark_ecapa_tdnn(device)` — loads `speechbrain/spkrec-ecapa-voxceleb` via `EncoderClassifier.from_hparams`, runs `encode_batch` on 500ms chunk

4. `main()`:
   - Check VRAM, skip GPU if <4GB free
   - Run all 3 benchmarks on cpu + optionally cuda
   - Find best separation model (p95 < 500ms) + best identification model
   - Combined p95 < 500ms = GO, else NO-GO
   - Save report to `~/.local/share/hapax-voice/tse_benchmark_report.json`
   - Print summary

5. `if __name__ == "__main__": main()`

The full implementation is in the spec at `docs/superpowers/specs/2026-03-27-multi-mic-pipeline-design.md`. Refer to the Layer 3 section for the exact two-stage architecture (blind separation + ECAPA-TDNN channel identification).

- [ ] **Step 2: Verify script is syntactically valid**

Run: `cd ~/projects/hapax-council && uv run python -c "import agents.hapax_voice.tse_benchmark; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Run ruff**

Run: `cd ~/projects/hapax-council && uv run ruff check agents/hapax_voice/tse_benchmark.py && uv run ruff format --check agents/hapax_voice/tse_benchmark.py`

Expected: Clean.

- [ ] **Step 4: Commit**

```bash
git add agents/hapax_voice/tse_benchmark.py
git commit -m "feat(voice): add TSE benchmark script (SepFormer + ConvTasNet + ECAPA-TDNN)"
```

---

### Task 8: Commit hook fix

**Files:**
- Modified: `hooks/scripts/work-resolution-gate.sh` (already patched)

- [ ] **Step 1: Verify hook syntax**

Run: `cd ~/projects/hapax-council && bash -n hooks/scripts/work-resolution-gate.sh && echo "syntax OK"`

Expected: `syntax OK`

- [ ] **Step 2: Commit hook fix**

```bash
git add hooks/scripts/work-resolution-gate.sh
git commit -m "fix(hooks): scope work-resolution-gate to current worktree branches only

Other worktrees' branches were showing up in refs/heads/ and blocking
edits. Now filters out branches checked out in other worktrees via
git worktree list."
```

---

### Task 9: Run full test suite and lint

- [ ] **Step 1: Run new tests**

Run: `cd ~/projects/hapax-council && uv run pytest tests/hapax_voice/test_multi_mic.py tests/hapax_voice/test_enrollment_validation.py -v`

Expected: All tests PASS.

- [ ] **Step 2: Run ruff on all changed files**

Run: `cd ~/projects/hapax-council && uv run ruff check agents/hapax_voice/multi_mic.py agents/hapax_voice/enrollment.py agents/hapax_voice/config.py agents/hapax_voice/tse_benchmark.py && uv run ruff format --check agents/hapax_voice/multi_mic.py agents/hapax_voice/enrollment.py agents/hapax_voice/config.py agents/hapax_voice/tse_benchmark.py`

Expected: Clean.

- [ ] **Step 3: Run pyright on changed files**

Run: `cd ~/projects/hapax-council && uv run pyright agents/hapax_voice/multi_mic.py agents/hapax_voice/enrollment.py agents/hapax_voice/config.py`

Expected: No errors (warnings OK).

---

### Task 10: Create feature branch and PR

- [ ] **Step 1: Create feature branch and push**

```bash
cd ~/projects/hapax-council
git checkout -b feat/multi-mic-pipeline
git push -u origin feat/multi-mic-pipeline
```

- [ ] **Step 2: Create PR**

```bash
gh pr create --title "feat(voice): multi-mic pipeline + enrollment validation + TSE benchmark" --body "$(cat <<'PREOF'
## Summary

Queue item #013 — three-layer enhancement to the hapax-voice audio pipeline:

- **Layer 1:** Replace PyAudio noise reference capture with pw-record subprocesses. Captures from ALL available C920s + BRIO (was only first C920). Eliminates pactl default-source conflict. Multi-source noise estimates averaged before spectral subtraction.
- **Layer 2:** Add enrollment quality validation — pairwise similarity matrix, outlier detection, threshold testing, stability report saved as JSON.
- **Layer 3:** TSE benchmark script evaluating SpeechBrain SepFormer (8kHz) and Asteroid ConvTasNet (16kHz) for blind source separation + ECAPA-TDNN for channel identification. Produces go/no-go recommendation.
- **Hook fix:** work-resolution-gate now scopes to current worktree branches only (was blocking alpha for beta's PRs).

## Test plan

- [ ] `uv run pytest tests/hapax_voice/test_multi_mic.py tests/hapax_voice/test_enrollment_validation.py -v`
- [ ] Restart hapax-voice daemon, verify logs show all C920s + BRIO captured
- [ ] Run `uv run python -m agents.hapax_voice.tse_benchmark` and review report
- [ ] Run enrollment interactively when operator is available
PREOF
)"
```

- [ ] **Step 3: Monitor CI, fix failures, merge when green**
