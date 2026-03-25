# Contact Microphone Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate a Cortado MKIII contact microphone into the hapax perception and audio pipeline via PipeWire routing, a FAST-tier perception backend, tap gesture dispatch, structure-borne noise reference, continuous FLAC recording, and audio processor extension.

**Architecture:** The Studio 24c right channel (`FR`) is extracted into a named PipeWire virtual source (`contact_mic`) via `libpipewire-module-loopback`. All consumers (perception backend, noise reference, recorder) connect to this source independently via PipeWire fan-out. No GPU, no ML, no new dependencies.

**Tech Stack:** PipeWire 1.x, WirePlumber 0.5+, PyAudio, NumPy, systemd user units, Python 3.12+

**Spec:** `docs/superpowers/specs/2026-03-25-contact-mic-integration.md`

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `~/.config/pipewire/pipewire.conf.d/10-contact-mic.conf` | PipeWire loopback: FR → mono virtual source |
| Create | `~/.config/wireplumber/wireplumber.conf.d/50-studio24c.conf` | ALSA tuning + no-suspend for Studio 24c |
| Create | `agents/hapax_voice/backends/contact_mic.py` | FAST-tier perception backend: RMS, onsets, activity, gestures |
| Create | `tests/hapax_voice/test_contact_mic_backend.py` | Unit tests for all DSP + gesture logic |
| Create | `systemd/units/contact-mic-recorder.service` | Continuous FLAC recording service |
| Create | `tests/test_audio_processor_contact_mic.py` | Unit tests for second directory + pattern param |
| Edit | `agents/hapax_voice/config.py:73` | Add `contact_mic_source` field |
| Edit | `agents/hapax_voice/__main__.py:2038` | Add `self._loop` assignment |
| Edit | `agents/hapax_voice/__main__.py:635` | Register ContactMicBackend |
| Edit | `agents/hapax_voice/__main__.py` (after backends) | Tap governance wiring |
| Edit | `agents/hapax_voice/__main__.py:316-320` | Update NoiseReference constructor |
| Edit | `agents/hapax_voice/multi_mic.py:45-50` | Add `structure_sources` parameter |
| Edit | `tests/hapax_voice/test_multi_mic_structure.py` (create) | Unit tests for structure subtraction |
| Edit | `agents/audio_processor.py:54,219,316,1571` | Add `CONTACT_MIC_RAW_DIR` constant, `source` field, `pattern` param, second dir scan |

---

## Task 1: PipeWire Routing Config

**Files:**
- Create: `~/.config/pipewire/pipewire.conf.d/10-contact-mic.conf`
- Create: `~/.config/wireplumber/wireplumber.conf.d/50-studio24c.conf`

- [ ] **Step 1: Write PipeWire loopback config**

```
# ~/.config/pipewire/pipewire.conf.d/10-contact-mic.conf
context.modules = [
    {
        name = libpipewire-module-loopback
        args = {
            node.description = "Contact Microphone (Cortado)"
            capture.props = {
                audio.position = [ FR ]
                stream.dont-remix = true
                node.target = "alsa_input.usb-PreSonus_Studio_24c_SC1E24390244-00.analog-stereo"
                node.passive = true
            }
            playback.props = {
                node.name = "contact_mic"
                node.description = "Contact Microphone (Cortado)"
                media.class = "Audio/Source"
                audio.position = [ MONO ]
            }
        }
    }
]
```

- [ ] **Step 2: Write WirePlumber ALSA rule**

```
# ~/.config/wireplumber/wireplumber.conf.d/50-studio24c.conf
monitor.alsa.rules = [
    {
        matches = [
            { node.name = "~alsa_input.usb-PreSonus_Studio_24c*" }
        ]
        actions = {
            update-props = {
                api.alsa.period-size = 128
                api.alsa.headroom = 0
                api.alsa.disable-batch = true
                session.suspend-timeout-seconds = 0
            }
        }
    }
]
```

- [ ] **Step 3: Restart PipeWire and verify**

Run: `systemctl --user restart pipewire.service && sleep 1 && pw-cli ls Node | grep contact_mic`
Expected: Node with `node.name = "contact_mic"` and `media.class = Audio/Source`

- [ ] **Step 4: Commit**

```bash
git add ~/.config/pipewire/pipewire.conf.d/10-contact-mic.conf ~/.config/wireplumber/wireplumber.conf.d/50-studio24c.conf
git commit -m "feat(voice): PipeWire routing for contact microphone

Loopback extracts right channel (FR) from Studio 24c into named
'contact_mic' virtual source. WirePlumber rule prevents device suspend."
```

---

## Task 2: ContactMicBackend — DSP Cache and Core Logic

**Files:**
- Create: `agents/hapax_voice/backends/contact_mic.py`
- Create: `tests/hapax_voice/test_contact_mic_backend.py`

- [ ] **Step 1: Write failing tests for the DSP cache**

File: `tests/hapax_voice/test_contact_mic_backend.py`

```python
"""Tests for ContactMicBackend — desk activity perception from contact mic.

All tests use synthetic PCM frames — no audio hardware or PipeWire needed.
"""

from __future__ import annotations

import struct
import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from agents.hapax_voice.backends.contact_mic import (
    ContactMicBackend,
    _ContactMicCache,
    _classify_activity,
    _compute_rms,
    _compute_spectral_centroid,
    _detect_onsets,
)
from agents.hapax_voice.primitives import Behavior


def _make_pcm_frame(freq_hz: float = 440.0, amplitude: float = 0.5, n_samples: int = 512) -> bytes:
    """Generate a pure sine tone as int16 PCM bytes."""
    t = np.arange(n_samples) / 16000.0
    samples = (amplitude * 32767 * np.sin(2 * np.pi * freq_hz * t)).astype(np.int16)
    return samples.tobytes()


def _make_silence(n_samples: int = 512) -> bytes:
    return b"\x00" * (n_samples * 2)


class TestComputeRms:
    def test_silence_is_zero(self):
        assert _compute_rms(_make_silence()) == pytest.approx(0.0, abs=1e-6)

    def test_loud_signal_high_rms(self):
        rms = _compute_rms(_make_pcm_frame(amplitude=0.9))
        assert rms > 0.5

    def test_quiet_signal_low_rms(self):
        rms = _compute_rms(_make_pcm_frame(amplitude=0.01))
        assert rms < 0.02


class TestSpectralCentroid:
    def test_low_freq_low_centroid(self):
        c_low = _compute_spectral_centroid(_make_pcm_frame(freq_hz=100.0))
        c_high = _compute_spectral_centroid(_make_pcm_frame(freq_hz=4000.0))
        assert c_low < c_high

    def test_silence_returns_zero(self):
        assert _compute_spectral_centroid(_make_silence()) == pytest.approx(0.0, abs=1.0)


class TestOnsetDetection:
    def test_no_onsets_in_silence(self):
        onsets = _detect_onsets([_make_silence()] * 10, threshold=0.01)
        assert len(onsets) == 0

    def test_detects_onset_after_silence(self):
        frames = [_make_silence()] * 5 + [_make_pcm_frame(amplitude=0.8)] * 3
        onsets = _detect_onsets(frames, threshold=0.01)
        assert len(onsets) >= 1

    def test_respects_min_interval(self):
        # Two loud frames back to back should be one onset, not two
        frames = [_make_silence()] * 3 + [_make_pcm_frame(amplitude=0.8)] * 2
        onsets = _detect_onsets(frames, threshold=0.01, min_interval_frames=3)
        assert len(onsets) == 1


class TestClassifyActivity:
    def test_idle_when_silent(self):
        assert _classify_activity(energy=0.0, onset_rate=0.0, centroid=0.0) == "idle"

    def test_typing_high_onset_low_energy(self):
        assert _classify_activity(energy=0.05, onset_rate=5.0, centroid=3000.0) == "typing"

    def test_tapping_moderate_onset_higher_energy(self):
        assert _classify_activity(energy=0.3, onset_rate=2.0, centroid=2000.0) == "tapping"

    def test_drumming_high_energy_low_centroid(self):
        assert _classify_activity(energy=0.6, onset_rate=4.0, centroid=500.0) == "drumming"


class TestContactMicCache:
    def test_initial_values(self):
        cache = _ContactMicCache()
        data = cache.read()
        assert data["desk_activity"] == "idle"
        assert data["desk_energy"] == 0.0
        assert data["desk_onset_rate"] == 0.0
        assert data["desk_tap_gesture"] == "none"

    def test_update_and_read(self):
        cache = _ContactMicCache()
        cache.update(
            desk_activity="typing",
            desk_energy=0.3,
            desk_onset_rate=5.0,
            desk_tap_gesture="none",
        )
        data = cache.read()
        assert data["desk_activity"] == "typing"
        assert data["desk_energy"] == 0.3

    def test_thread_safety(self):
        import threading

        cache = _ContactMicCache()
        errors: list[str] = []

        def writer():
            try:
                for _ in range(100):
                    cache.update("typing", 0.5, 3.0, "none")
            except Exception as e:
                errors.append(str(e))

        def reader():
            try:
                for _ in range(100):
                    cache.read()
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors


class TestGestureDetection:
    """Gesture pattern matching is tested via the cache's tap_gesture field.

    The gesture state machine runs inside the capture thread. We test the
    exported _classify_gesture() function directly.
    """

    def test_no_gesture_single_onset(self):
        from agents.hapax_voice.backends.contact_mic import _classify_gesture

        now = time.monotonic()
        assert _classify_gesture([now]) == "none"

    def test_double_tap(self):
        from agents.hapax_voice.backends.contact_mic import _classify_gesture

        now = time.monotonic()
        assert _classify_gesture([now, now + 0.15]) == "double_tap"

    def test_triple_tap(self):
        from agents.hapax_voice.backends.contact_mic import _classify_gesture

        now = time.monotonic()
        assert _classify_gesture([now, now + 0.12, now + 0.25]) == "triple_tap"

    def test_too_slow_is_no_gesture(self):
        from agents.hapax_voice.backends.contact_mic import _classify_gesture

        now = time.monotonic()
        # 500ms between taps — too slow for double tap
        assert _classify_gesture([now, now + 0.5]) == "none"


class TestContactMicBackendProtocol:
    def test_name(self):
        with patch("agents.hapax_voice.backends.contact_mic.pyaudio", None):
            backend = ContactMicBackend(source_name="Test Mic")
        assert backend.name == "contact_mic"

    def test_provides(self):
        with patch("agents.hapax_voice.backends.contact_mic.pyaudio", None):
            backend = ContactMicBackend(source_name="Test Mic")
        assert backend.provides == frozenset({
            "desk_activity", "desk_energy", "desk_onset_rate", "desk_tap_gesture",
        })

    def test_tier_is_fast(self):
        from agents.hapax_voice.perception import PerceptionTier

        with patch("agents.hapax_voice.backends.contact_mic.pyaudio", None):
            backend = ContactMicBackend(source_name="Test Mic")
        assert backend.tier == PerceptionTier.FAST

    def test_contribute_updates_behaviors(self):
        with patch("agents.hapax_voice.backends.contact_mic.pyaudio", None):
            backend = ContactMicBackend(source_name="Test Mic")
        behaviors: dict[str, Behavior] = {}
        backend.contribute(behaviors)
        assert "desk_activity" in behaviors
        assert "desk_energy" in behaviors
        assert "desk_onset_rate" in behaviors
        assert "desk_tap_gesture" in behaviors
        assert behaviors["desk_activity"].value == "idle"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_voice/test_contact_mic_backend.py -v 2>&1 | head -30`
Expected: `ModuleNotFoundError` or `ImportError` — module doesn't exist yet

- [ ] **Step 3: Write ContactMicBackend implementation**

File: `agents/hapax_voice/backends/contact_mic.py`

```python
"""Contact microphone perception backend.

Captures structure-borne vibration from a Cortado MKIII contact mic via
PipeWire (through a named 'contact_mic' virtual source). Computes desk
activity metrics and tap gesture detection — all CPU DSP, no ML.

The capture loop runs in a daemon thread. contribute() reads from a
thread-safe cache in <1ms (FAST tier).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque

import numpy as np

from agents.hapax_voice.perception import PerceptionTier
from agents.hapax_voice.primitives import Behavior

log = logging.getLogger(__name__)

try:
    import pyaudio
except ImportError:
    pyaudio = None  # type: ignore[assignment]

# ── DSP constants ─────────────────────────────────────────────────────────────

_FFT_SIZE = 512
_SAMPLE_RATE = 16000
_FRAME_SAMPLES = _FFT_SIZE
_FRAME_BYTES = _FRAME_SAMPLES * 2  # int16

_RMS_SMOOTHING = 0.3  # exponential smoothing alpha
_ONSET_THRESHOLD = 0.03  # normalized RMS threshold for onset
_ONSET_MIN_INTERVAL_S = 0.08  # 80ms minimum between onsets
_GESTURE_WINDOW_S = 0.5  # max time window for gesture classification
_GESTURE_TIMEOUT_S = 0.3  # wait after last onset before classifying
_DOUBLE_TAP_MIN_IOI = 0.08  # min inter-onset interval for double tap
_DOUBLE_TAP_MAX_IOI = 0.25  # max inter-onset interval for double tap

_IDLE_THRESHOLD = 0.005  # energy below this = idle
_TYPING_MIN_ONSET_RATE = 3.0  # onsets/sec
_TAPPING_MIN_ONSET_RATE = 1.0
_DRUMMING_MIN_ENERGY = 0.3
_DRUMMING_MAX_CENTROID = 1500.0  # Hz — low centroid = resonant low-end


# ── Pure DSP functions ────────────────────────────────────────────────────────


def _compute_rms(frame: bytes) -> float:
    """RMS energy of a PCM int16 frame, normalized to 0.0-1.0."""
    samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
    if len(samples) == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples**2)))


def _compute_spectral_centroid(frame: bytes) -> float:
    """Spectral centroid in Hz from a PCM int16 frame."""
    samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
    if len(samples) < _FFT_SIZE:
        return 0.0
    window = np.hanning(_FFT_SIZE)
    spec = np.abs(np.fft.rfft(samples[:_FFT_SIZE] * window))
    total = spec.sum()
    if total < 1e-10:
        return 0.0
    freqs = np.fft.rfftfreq(_FFT_SIZE, d=1.0 / _SAMPLE_RATE)
    return float(np.sum(freqs * spec) / total)


def _detect_onsets(
    frames: list[bytes],
    threshold: float = _ONSET_THRESHOLD,
    min_interval_frames: int = 3,
) -> list[int]:
    """Detect onset frame indices from a list of PCM frames."""
    onsets: list[int] = []
    prev_energy = 0.0
    last_onset = -min_interval_frames - 1

    for i, frame in enumerate(frames):
        energy = _compute_rms(frame)
        if energy > threshold and prev_energy <= threshold and (i - last_onset) >= min_interval_frames:
            onsets.append(i)
            last_onset = i
        prev_energy = energy

    return onsets


def _classify_activity(energy: float, onset_rate: float, centroid: float) -> str:
    """Classify desk activity from DSP metrics."""
    if energy < _IDLE_THRESHOLD:
        return "idle"
    if energy >= _DRUMMING_MIN_ENERGY and centroid < _DRUMMING_MAX_CENTROID:
        return "drumming"
    if onset_rate >= _TYPING_MIN_ONSET_RATE and energy < _DRUMMING_MIN_ENERGY:
        return "typing"
    if onset_rate >= _TAPPING_MIN_ONSET_RATE:
        return "tapping"
    return "idle"


def _classify_gesture(onset_times: list[float]) -> str:
    """Classify a burst of onset timestamps into a gesture.

    Args:
        onset_times: Monotonic timestamps of onsets within gesture window.

    Returns:
        "none", "double_tap", or "triple_tap"
    """
    n = len(onset_times)
    if n < 2:
        return "none"

    if n == 2:
        ioi = onset_times[1] - onset_times[0]
        if _DOUBLE_TAP_MIN_IOI <= ioi <= _DOUBLE_TAP_MAX_IOI:
            return "double_tap"
        return "none"

    if n >= 3:
        span = onset_times[-1] - onset_times[0]
        if span <= _GESTURE_WINDOW_S:
            return "triple_tap"

    return "none"


# ── Thread-safe cache ─────────────────────────────────────────────────────────


class _ContactMicCache:
    """Thread-safe cache for contact mic DSP results."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._desk_activity: str = "idle"
        self._desk_energy: float = 0.0
        self._desk_onset_rate: float = 0.0
        self._desk_tap_gesture: str = "none"
        self._updated_at: float = 0.0

    def update(
        self,
        desk_activity: str,
        desk_energy: float,
        desk_onset_rate: float,
        desk_tap_gesture: str,
    ) -> None:
        with self._lock:
            self._desk_activity = desk_activity
            self._desk_energy = desk_energy
            self._desk_onset_rate = desk_onset_rate
            self._desk_tap_gesture = desk_tap_gesture
            self._updated_at = time.monotonic()

    def read(self) -> dict[str, str | float]:
        with self._lock:
            return {
                "desk_activity": self._desk_activity,
                "desk_energy": self._desk_energy,
                "desk_onset_rate": self._desk_onset_rate,
                "desk_tap_gesture": self._desk_tap_gesture,
                "updated_at": self._updated_at,
            }


# ── Backend ───────────────────────────────────────────────────────────────────


class ContactMicBackend:
    """FAST-tier perception backend for contact microphone desk sensing.

    A daemon thread captures audio from the contact mic PipeWire source
    and computes RMS energy, onset rate, activity classification, and
    tap gesture detection. contribute() reads the cache in <1ms.

    Device matching uses PyAudio device name substring matching against
    PipeWire's node.description (not node.name).
    """

    def __init__(self, source_name: str = "Contact Microphone") -> None:
        self._source_name = source_name
        self._cache = _ContactMicCache()
        self._running = False
        self._thread: threading.Thread | None = None

        # Behaviors (created once, updated in contribute)
        self._b_activity: Behavior[str] = Behavior("idle")
        self._b_energy: Behavior[float] = Behavior(0.0)
        self._b_onset_rate: Behavior[float] = Behavior(0.0)
        self._b_gesture: Behavior[str] = Behavior("none")

    @property
    def name(self) -> str:
        return "contact_mic"

    @property
    def provides(self) -> frozenset[str]:
        return frozenset({"desk_activity", "desk_energy", "desk_onset_rate", "desk_tap_gesture"})

    @property
    def tier(self) -> PerceptionTier:
        return PerceptionTier.FAST

    def available(self) -> bool:
        if pyaudio is None:
            return False
        try:
            pa = pyaudio.PyAudio()
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                if self._source_name in str(info.get("name", "")):
                    pa.terminate()
                    return True
            pa.terminate()
        except Exception:
            pass
        return False

    def start(self) -> None:
        if pyaudio is None:
            log.info("ContactMicBackend: pyaudio not available")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop,
            daemon=True,
            name="contact-mic-capture",
        )
        self._thread.start()
        log.info("ContactMicBackend started (source=%s)", self._source_name)

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        log.info("ContactMicBackend stopped")

    def contribute(self, behaviors: dict[str, Behavior]) -> None:
        now = time.monotonic()
        data = self._cache.read()

        self._b_activity.update(data["desk_activity"], now)
        self._b_energy.update(float(data["desk_energy"]), now)
        self._b_onset_rate.update(float(data["desk_onset_rate"]), now)
        self._b_gesture.update(data["desk_tap_gesture"], now)

        behaviors["desk_activity"] = self._b_activity
        behaviors["desk_energy"] = self._b_energy
        behaviors["desk_onset_rate"] = self._b_onset_rate
        behaviors["desk_tap_gesture"] = self._b_gesture

    def _capture_loop(self) -> None:
        """Background thread: capture audio, compute DSP, update cache."""
        try:
            pa = pyaudio.PyAudio()
            device_idx = None
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                if self._source_name in str(info.get("name", "")):
                    device_idx = i
                    break

            if device_idx is None:
                log.warning("Contact mic source not found: %s", self._source_name)
                pa.terminate()
                return

            stream = pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=_SAMPLE_RATE,
                input=True,
                input_device_index=device_idx,
                frames_per_buffer=_FRAME_SAMPLES,
            )

            log.info("Contact mic capturing from device %d", device_idx)

            # State for onset detection and gesture classification
            smoothed_energy = 0.0
            prev_energy = 0.0
            onset_times: deque[float] = deque(maxlen=20)
            gesture_onset_burst: list[float] = []
            last_onset_time = 0.0
            last_gesture_check = time.monotonic()
            frame_count = 0

            while self._running:
                try:
                    data = stream.read(_FRAME_SAMPLES, exception_on_overflow=False)
                    now = time.monotonic()
                    frame_count += 1

                    # RMS energy with exponential smoothing
                    raw_energy = _compute_rms(data)
                    smoothed_energy = _RMS_SMOOTHING * raw_energy + (1 - _RMS_SMOOTHING) * smoothed_energy

                    # Onset detection
                    if (
                        raw_energy > _ONSET_THRESHOLD
                        and prev_energy <= _ONSET_THRESHOLD
                        and (now - last_onset_time) >= _ONSET_MIN_INTERVAL_S
                    ):
                        onset_times.append(now)
                        gesture_onset_burst.append(now)
                        last_onset_time = now
                        last_gesture_check = now

                    prev_energy = raw_energy

                    # Onset rate: count onsets in last 1 second
                    cutoff = now - 1.0
                    recent_onsets = [t for t in onset_times if t > cutoff]
                    onset_rate = float(len(recent_onsets))

                    # Spectral centroid (every 4th frame to save CPU)
                    centroid = 0.0
                    if frame_count % 4 == 0:
                        centroid = _compute_spectral_centroid(data)

                    # Activity classification
                    activity = _classify_activity(smoothed_energy, onset_rate, centroid)

                    # Gesture classification (after timeout)
                    gesture = "none"
                    if gesture_onset_burst and (now - last_gesture_check) >= _GESTURE_TIMEOUT_S:
                        gesture = _classify_gesture(gesture_onset_burst)
                        gesture_onset_burst.clear()

                    self._cache.update(activity, smoothed_energy, onset_rate, gesture)

                except Exception:
                    time.sleep(0.1)

            stream.stop_stream()
            stream.close()
            pa.terminate()

        except Exception:
            log.debug("Contact mic capture failed", exc_info=True)
```

- [ ] **Step 4: Run tests**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_voice/test_contact_mic_backend.py -v`
Expected: All tests pass

- [ ] **Step 5: Lint**

Run: `cd /home/hapax/projects/hapax-council && uv run ruff check agents/hapax_voice/backends/contact_mic.py tests/hapax_voice/test_contact_mic_backend.py && uv run ruff format --check agents/hapax_voice/backends/contact_mic.py tests/hapax_voice/test_contact_mic_backend.py`
Expected: No errors. Fix any issues.

- [ ] **Step 6: Commit**

```bash
git add agents/hapax_voice/backends/contact_mic.py tests/hapax_voice/test_contact_mic_backend.py
git commit -m "feat(voice): ContactMicBackend — desk activity perception from contact mic

FAST-tier backend with RMS energy, onset detection, activity classification
(idle/typing/tapping/drumming), spectral centroid, and tap gesture detection.
All CPU DSP, no ML. Thread-safe cache pattern from StudioIngestionBackend."
```

---

## Task 3: Register Backend + Config

**Files:**
- Modify: `agents/hapax_voice/config.py:73`
- Modify: `agents/hapax_voice/__main__.py:635` (after InputActivityBackend registration)

- [ ] **Step 1: Add config field**

In `agents/hapax_voice/config.py`, after line 67 (after `audio_input_source` in the `# Audio hardware` section), add:

```python
    # Contact microphone (desk vibration sensing via PipeWire)
    contact_mic_source: str = "Contact Microphone"
```

- [ ] **Step 2: Register backend in __main__.py**

In `agents/hapax_voice/__main__.py`, after the InputActivityBackend registration block (after line 635), add:

```python
        # Contact microphone backend (desk vibration via Cortado)
        try:
            from agents.hapax_voice.backends.contact_mic import ContactMicBackend

            self.perception.register_backend(
                ContactMicBackend(source_name=self.cfg.contact_mic_source)
            )
        except Exception:
            log.info("ContactMicBackend not available, skipping")
```

- [ ] **Step 3: Lint**

Run: `cd /home/hapax/projects/hapax-council && uv run ruff check agents/hapax_voice/config.py agents/hapax_voice/__main__.py && uv run ruff format --check agents/hapax_voice/config.py agents/hapax_voice/__main__.py`

- [ ] **Step 4: Commit**

```bash
git add agents/hapax_voice/config.py agents/hapax_voice/__main__.py
git commit -m "feat(voice): register ContactMicBackend in perception engine

Adds contact_mic_source config field and backend registration following
the standard try/except pattern. Degrades gracefully if mic unavailable."
```

---

## Task 4: Tap Gesture Dispatch (async wiring)

**Files:**
- Modify: `agents/hapax_voice/__main__.py:2038` (add `self._loop`)
- Modify: `agents/hapax_voice/__main__.py` (tap governance after backend registration)

- [ ] **Step 1: Store event loop on daemon**

In `agents/hapax_voice/__main__.py`, at the top of `_run_inner()` (line 2040, after the log.info call), add:

```python
        self._loop = asyncio.get_running_loop()
```

Also add `import asyncio` at the top of the file if not already present.

- [ ] **Step 2: Add tap governance wiring**

In `agents/hapax_voice/__main__.py`, add a new method after `_register_perception_backends()` (after line 697):

```python
    def _setup_tap_governance(self) -> None:
        """Wire tap gesture dispatch — double-tap toggles session, triple-tap scans."""
        self._prev_tap_gesture = "none"

    def _check_tap_gesture(self) -> None:
        """Called from perception tick. Checks for gesture transitions."""
        gesture_behavior = self.perception.behaviors.get("desk_tap_gesture")
        if gesture_behavior is None:
            return

        gesture = gesture_behavior.value
        if gesture != "none" and gesture != self._prev_tap_gesture:
            cmd = {"double_tap": "toggle", "triple_tap": "scan"}.get(gesture)
            if cmd is not None:
                log.info("Tap gesture detected: %s → hotkey %s", gesture, cmd)
                asyncio.run_coroutine_threadsafe(self._handle_hotkey(cmd), self._loop)
        self._prev_tap_gesture = gesture
```

- [ ] **Step 3: Wire _setup_tap_governance and _check_tap_gesture**

Call `self._setup_tap_governance()` in `__init__` at line 210, immediately after `self._register_perception_backends()`:

```python
        self._register_perception_backends()
        self._setup_tap_governance()
```

Add `self._check_tap_gesture()` at line 1853, immediately after the perception tick in the main perception loop:

```python
                state = self.perception.tick()
                self._check_tap_gesture()
```

- [ ] **Step 4: Lint and verify**

Run: `cd /home/hapax/projects/hapax-council && uv run ruff check agents/hapax_voice/__main__.py && uv run ruff format --check agents/hapax_voice/__main__.py`

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_voice/__main__.py
git commit -m "feat(voice): tap gesture dispatch via contact mic

Double-tap toggles voice session, triple-tap triggers ambient scan.
Dispatched via asyncio.run_coroutine_threadsafe through _handle_hotkey,
respecting governor veto and consent checks."
```

---

## Task 5: Structure-Borne Noise Reference

**Files:**
- Modify: `agents/hapax_voice/multi_mic.py:45-50`
- Create: `tests/hapax_voice/test_multi_mic_structure.py`
- Modify: `agents/hapax_voice/__main__.py:316-320`

- [ ] **Step 1: Write failing tests**

File: `tests/hapax_voice/test_multi_mic_structure.py`

```python
"""Tests for structure-borne noise reference extension to NoiseReference."""

from __future__ import annotations

import numpy as np
import pytest

from agents.hapax_voice.multi_mic import NoiseReference


def _make_pcm(freq_hz: float = 200.0, amplitude: float = 0.3, n_samples: int = 512) -> bytes:
    t = np.arange(n_samples) / 16000.0
    samples = (amplitude * 32767 * np.sin(2 * np.pi * freq_hz * t)).astype(np.int16)
    return samples.tobytes()


def _make_silence(n_samples: int = 512) -> bytes:
    return b"\x00" * (n_samples * 2)


class TestStructureSources:
    def test_accepts_structure_sources_param(self):
        ref = NoiseReference(structure_sources=["Test Device"])
        assert ref._structure_sources == ["Test Device"]

    def test_default_structure_sources_empty(self):
        ref = NoiseReference()
        assert ref._structure_sources == []

    def test_subtract_passthrough_without_estimates(self):
        ref = NoiseReference(structure_sources=["Test Device"])
        frame = _make_pcm()
        result = ref.subtract(frame)
        assert result == frame  # no estimate yet, pass through

    def test_structure_subtraction_reduces_energy(self):
        """Manual test: inject a structure noise estimate and verify subtraction."""
        ref = NoiseReference(structure_sources=["Test Device"])

        # Manually set structure noise estimate (simulates capture thread)
        window = np.hanning(512)
        noise_frame = np.frombuffer(_make_pcm(200.0, 0.3), dtype=np.int16).astype(np.float32)
        spec = np.fft.rfft(noise_frame * window)
        ref._structure_noise_estimate = np.abs(spec)

        # Input frame with the same frequency — should be reduced
        input_frame = _make_pcm(200.0, 0.5)
        result = ref.subtract(input_frame)

        # Result should have less energy than input
        input_energy = np.sqrt(np.mean(np.frombuffer(input_frame, dtype=np.int16).astype(np.float32) ** 2))
        result_energy = np.sqrt(np.mean(np.frombuffer(result, dtype=np.int16).astype(np.float32) ** 2))
        assert result_energy < input_energy
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_voice/test_multi_mic_structure.py -v 2>&1 | head -20`
Expected: Fail — `structure_sources` parameter not accepted

- [ ] **Step 3: Extend NoiseReference**

In `agents/hapax_voice/multi_mic.py`, modify `__init__` (line 45-50):

```python
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

        # Noise estimates (magnitude spectra, updated continuously)
        self._noise_estimate: np.ndarray | None = None  # airborne (room)
        self._structure_noise_estimate: np.ndarray | None = None  # structure-borne
        self._lock = threading.Lock()
        self._structure_lock = threading.Lock()

        # Ring buffer of recent reference frames for averaging
        self._ref_frames: deque[np.ndarray] = deque(maxlen=20)
```

Modify `start()` (line 62-78) to also start structure source threads:

```python
    def start(self) -> None:
        """Start capturing from reference microphones."""
        if not self._room_sources and not self._structure_sources:
            log.info("No reference sources configured — noise subtraction disabled")
            return

        self._running = True
        for source in self._room_sources:
            t = threading.Thread(
                target=self._capture_loop,
                args=(source, False),
                daemon=True,
                name=f"noise-ref-{source[:20]}",
            )
            t.start()
            self._threads.append(t)
        for source in self._structure_sources:
            t = threading.Thread(
                target=self._capture_loop,
                args=(source, True),
                daemon=True,
                name=f"struct-ref-{source[:20]}",
            )
            t.start()
            self._threads.append(t)
        log.info(
            "Noise reference started: %d room, %d structure source(s)",
            len(self._room_sources),
            len(self._structure_sources),
        )
```

Modify `subtract()` (line 86-125) to apply structure subtraction first:

```python
    def subtract(self, frame: bytes) -> bytes:
        """Apply spectral subtraction to a primary mic frame.

        Structure-borne subtraction (gentle) first, then airborne (aggressive).
        """
        # Structure-borne subtraction (alpha=1.0, beta=0.02)
        with self._structure_lock:
            struct_est = self._structure_noise_estimate

        if struct_est is not None:
            frame = self._apply_subtraction(frame, struct_est, alpha=1.0, beta=0.02)

        # Airborne subtraction (alpha=1.5, beta=0.01)
        with self._lock:
            room_est = self._noise_estimate

        if room_est is not None:
            frame = self._apply_subtraction(frame, room_est, alpha=_ALPHA, beta=_BETA)

        return frame

    def _apply_subtraction(
        self, frame: bytes, noise_mag: np.ndarray, alpha: float, beta: float
    ) -> bytes:
        """Apply spectral subtraction with given parameters."""
        samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        if len(samples) < _FFT_SIZE:
            return frame

        window = np.hanning(_FFT_SIZE)
        spec = np.fft.rfft(samples[:_FFT_SIZE] * window)
        mag = np.abs(spec)
        phase = np.angle(spec)

        if len(noise_mag) == len(mag):
            clean_mag = np.maximum(mag - alpha * noise_mag, beta * mag)
        else:
            clean_mag = mag

        clean_spec = clean_mag * np.exp(1j * phase)
        clean_samples = np.fft.irfft(clean_spec)[: len(samples)]
        clean_int16 = np.clip(clean_samples, -32768, 32767).astype(np.int16)
        return clean_int16.tobytes()
```

Modify `_capture_loop` to accept an `is_structure` flag and update the correct estimate:

```python
    def _capture_loop(self, source: str, is_structure: bool = False) -> None:
        """Continuously capture from a reference mic and update noise estimate."""
        # ... (same device discovery and stream open as before) ...

        lock = self._structure_lock if is_structure else self._lock
        label = "structure" if is_structure else "room"

        while self._running:
            try:
                data = stream.read(_FFT_SIZE, exception_on_overflow=False)
                samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                window = np.hanning(_FFT_SIZE)
                spec = np.fft.rfft(samples * window)
                mag = np.abs(spec)

                with lock:
                    if is_structure:
                        if self._structure_noise_estimate is None:
                            self._structure_noise_estimate = mag
                        else:
                            self._structure_noise_estimate = (
                                _SMOOTHING * self._structure_noise_estimate
                                + (1 - _SMOOTHING) * mag
                            )
                    else:
                        if self._noise_estimate is None:
                            self._noise_estimate = mag
                        else:
                            self._noise_estimate = (
                                _SMOOTHING * self._noise_estimate + (1 - _SMOOTHING) * mag
                            )
            except Exception:
                time.sleep(0.1)
```

- [ ] **Step 4: Run tests**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_voice/test_multi_mic_structure.py -v`
Expected: All pass

- [ ] **Step 5: Update NoiseReference constructor call in __main__.py**

In `agents/hapax_voice/__main__.py:316-320`, change:

```python
        self._noise_reference = NoiseReference(
            room_sources=[
                "HD Pro Webcam C920",  # any C920 mic — room noise reference
            ],
        )
```

to:

```python
        self._noise_reference = NoiseReference(
            room_sources=[
                "HD Pro Webcam C920",  # any C920 mic — airborne noise reference
            ],
            structure_sources=[
                "Contact Microphone",  # Cortado contact mic — structure-borne reference
            ],
        )
```

- [ ] **Step 6: Lint**

Run: `cd /home/hapax/projects/hapax-council && uv run ruff check agents/hapax_voice/multi_mic.py agents/hapax_voice/__main__.py tests/hapax_voice/test_multi_mic_structure.py && uv run ruff format --check agents/hapax_voice/multi_mic.py agents/hapax_voice/__main__.py tests/hapax_voice/test_multi_mic_structure.py`

- [ ] **Step 7: Commit**

```bash
git add agents/hapax_voice/multi_mic.py agents/hapax_voice/__main__.py tests/hapax_voice/test_multi_mic_structure.py
git commit -m "feat(voice): structure-borne noise reference via contact mic

Extends NoiseReference with structure_sources parameter for Cortado contact
mic. Sequential subtraction: structure-borne (alpha=1.0) first, then
airborne (alpha=1.5). Separate noise estimates and locks per source type."
```

---

## Task 6: Recording Service

**Files:**
- Create: `systemd/units/contact-mic-recorder.service`

- [ ] **Step 1: Write systemd unit**

File: `systemd/units/contact-mic-recorder.service`

```ini
[Unit]
Description=Contact microphone continuous recording (Cortado via PipeWire)
After=pipewire.service pipewire-pulse.service
Requires=pipewire-pulse.service

[Service]
Type=simple
ExecStartPre=/usr/bin/mkdir -p %h/audio-recording/contact-mic
ExecStart=/bin/bash -c 'exec /usr/bin/pw-record \
    --target contact_mic --format s16 --rate 48000 --channels 1 - | \
    /usr/bin/ffmpeg -nostdin -f s16le -ar 48000 -ac 1 -i pipe: \
    -c:a flac -f segment -segment_time 900 -strftime 1 \
    %h/audio-recording/contact-mic/contact-rec-%%Y%%m%%d-%%H%%M%%S.flac'
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=contact-mic-recorder

[Install]
WantedBy=default.target
```

- [ ] **Step 2: Enable and start**

Run: `systemctl --user daemon-reload && systemctl --user enable --now contact-mic-recorder.service && sleep 3 && systemctl --user status contact-mic-recorder.service`
Expected: Active (running)

- [ ] **Step 3: Verify recording output**

Run: `ls -la ~/audio-recording/contact-mic/ | head -5`
Expected: `contact-rec-*.flac` file appearing (may take up to 15 minutes for first segment)

- [ ] **Step 4: Commit**

```bash
git add systemd/units/contact-mic-recorder.service
git commit -m "feat(studio): contact mic continuous FLAC recording service

Mirrors audio-recorder.service for the Cortado contact mic via PipeWire
contact_mic virtual source. 15-minute FLAC segments to ~/audio-recording/contact-mic/."
```

---

## Task 7: Audio Processor Extension

**Files:**
- Modify: `shared/config.py:74`
- Modify: `agents/audio_processor.py:54,219,316,1571`
- Create: `tests/test_audio_processor_contact_mic.py`

- [ ] **Step 1: Write failing tests**

File: `tests/test_audio_processor_contact_mic.py`

```python
"""Tests for audio processor contact mic extension."""

from __future__ import annotations

from pathlib import Path

import pytest


class TestFindUnprocessedFilesPattern:
    def test_default_pattern_matches_rec_files(self, tmp_path: Path):
        from agents.audio_processor import _find_unprocessed_files, AudioProcessorState

        (tmp_path / "rec-20260325-120000.flac").write_bytes(b"\x00" * 100)
        (tmp_path / "contact-rec-20260325-120000.flac").write_bytes(b"\x00" * 100)

        state = AudioProcessorState()
        files = _find_unprocessed_files(tmp_path, state)
        names = [f.name for f in files]
        assert "rec-20260325-120000.flac" in names
        assert "contact-rec-20260325-120000.flac" not in names

    def test_contact_pattern_matches_contact_files(self, tmp_path: Path):
        from agents.audio_processor import _find_unprocessed_files, AudioProcessorState

        (tmp_path / "rec-20260325-120000.flac").write_bytes(b"\x00" * 100)
        (tmp_path / "contact-rec-20260325-120000.flac").write_bytes(b"\x00" * 100)

        state = AudioProcessorState()
        files = _find_unprocessed_files(tmp_path, state, pattern="contact-rec-*.flac")
        names = [f.name for f in files]
        assert "contact-rec-20260325-120000.flac" in names
        assert "rec-20260325-120000.flac" not in names

    def test_skips_already_processed(self, tmp_path: Path):
        from agents.audio_processor import (
            _find_unprocessed_files,
            AudioProcessorState,
            ProcessedFileInfo,
        )

        (tmp_path / "contact-rec-20260325-120000.flac").write_bytes(b"\x00" * 100)

        state = AudioProcessorState()
        state.processed_files["contact-rec-20260325-120000.flac"] = ProcessedFileInfo(
            filename="contact-rec-20260325-120000.flac"
        )
        files = _find_unprocessed_files(tmp_path, state, pattern="contact-rec-*.flac")
        assert len(files) == 0


class TestProcessedFileInfoSource:
    def test_source_field_defaults_to_yeti(self):
        from agents.audio_processor import ProcessedFileInfo

        info = ProcessedFileInfo(filename="rec-20260325-120000.flac")
        assert info.source == "yeti"

    def test_source_field_accepts_contact_mic(self):
        from agents.audio_processor import ProcessedFileInfo

        info = ProcessedFileInfo(filename="test.flac", source="contact_mic")
        assert info.source == "contact_mic"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/test_audio_processor_contact_mic.py -v 2>&1 | head -20`
Expected: Fail — `pattern` parameter not accepted, `source` field not on model

- [ ] **Step 3: Add module-level constant**

In `agents/audio_processor.py`, after line 54 (`RAW_DIR = Path.home() / ...`), add:

```python
CONTACT_MIC_RAW_DIR = Path.home() / "audio-recording" / "contact-mic"
```

Note: Do NOT add a constant to `shared/config.py` — `audio_processor.py` uses its own module-level `Path.home()` constants (line 54-56), so follow the existing pattern.

- [ ] **Step 4: Add `source` field to ProcessedFileInfo**

In `agents/audio_processor.py:233` (after `error: str = ""`), add:

```python
    source: str = "yeti"  # "yeti" or "contact_mic"
```

- [ ] **Step 5: Add `pattern` parameter to `_find_unprocessed_files`**

In `agents/audio_processor.py:316`, change:

```python
def _find_unprocessed_files(raw_dir: Path, state: AudioProcessorState) -> list[Path]:
    """Find raw FLAC files that haven't been processed yet."""
    return sorted(
        f
        for f in raw_dir.glob("rec-*.flac")
        if f.name not in state.processed_files and f.stat().st_size > 0
    )
```

to:

```python
def _find_unprocessed_files(
    raw_dir: Path, state: AudioProcessorState, pattern: str = "rec-*.flac"
) -> list[Path]:
    """Find raw FLAC files that haven't been processed yet."""
    return sorted(
        f
        for f in raw_dir.glob(pattern)
        if f.name not in state.processed_files and f.stat().st_size > 0
    )
```

- [ ] **Step 6: Add second directory scan to `_process_new_files`**

In `agents/audio_processor.py`, in `_process_new_files()` (line 1571), after the existing processing block and before the return statement, add:

```python
    # Process contact mic files (separate directory, different source tag)
    if CONTACT_MIC_RAW_DIR.exists():
        contact_files = _find_unprocessed_files(
            CONTACT_MIC_RAW_DIR, state, pattern="contact-rec-*.flac"
        )
        if contact_files:
            # Same safety: skip most recent file
            if len(contact_files) > 1:
                contact_files = contact_files[:-1]
            elif time.time() - contact_files[0].stat().st_mtime < 60:
                contact_files = []

            for f in contact_files:
                info = _process_file(f, state)
                if info is None:
                    skipped += 1
                else:
                    info = info.model_copy(update={"source": "contact_mic"})
                    state.processed_files[f.name] = info
                    processed += 1
                    if not info.error:
                        _archive_file(f, info)
```

- [ ] **Step 7: Run tests**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/test_audio_processor_contact_mic.py -v`
Expected: All pass

- [ ] **Step 8: Run existing audio processor tests**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/test_audio_processor*.py -v`
Expected: All pass (backward compatible — default pattern is unchanged)

- [ ] **Step 9: Lint**

Run: `cd /home/hapax/projects/hapax-council && uv run ruff check agents/audio_processor.py tests/test_audio_processor_contact_mic.py && uv run ruff format --check agents/audio_processor.py tests/test_audio_processor_contact_mic.py`

- [ ] **Step 10: Commit**

```bash
git add agents/audio_processor.py tests/test_audio_processor_contact_mic.py
git commit -m "feat(audio): extend audio processor for contact mic recordings

Adds CONTACT_MIC_RAW_DIR constant, pattern parameter to _find_unprocessed_files,
source field to ProcessedFileInfo, and second directory scan for contact-rec-*.flac
files in ~/audio-recording/contact-mic/."
```

---

## Task 8: Full Test Suite + PR

- [ ] **Step 1: Run full test suite**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/hapax_voice/test_contact_mic_backend.py tests/hapax_voice/test_multi_mic_structure.py tests/test_audio_processor_contact_mic.py -v`
Expected: All pass

- [ ] **Step 2: Run ruff across all changed files**

Run: `cd /home/hapax/projects/hapax-council && uv run ruff check agents/hapax_voice/backends/contact_mic.py agents/hapax_voice/multi_mic.py agents/hapax_voice/__main__.py agents/hapax_voice/config.py agents/audio_processor.py && uv run ruff format --check agents/hapax_voice/backends/contact_mic.py agents/hapax_voice/multi_mic.py agents/hapax_voice/__main__.py agents/hapax_voice/config.py agents/audio_processor.py`

- [ ] **Step 3: Run pyright type check**

Run: `cd /home/hapax/projects/hapax-council && uv run pyright agents/hapax_voice/backends/contact_mic.py agents/hapax_voice/multi_mic.py`

- [ ] **Step 4: Create PR**

Push branch and create PR with summary of all 6 components.
