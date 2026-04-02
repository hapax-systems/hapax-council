# Continuous Perception Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace binary audio muting during system speech with three-layer echo discrimination so operator speech is always captured and classified.

**Architecture:** PipeWire webrtc AEC (Layer 1) + energy-ratio classifier (Layer 2) + adaptive VAD thresholds (Layer 3). Operator speech during system output classified as backchannel (→ grounding signal) or floor claim (→ yield). Application-level speexdsp EchoCanceller removed entirely.

**Tech Stack:** PipeWire `libspa-aec-webrtc`, Silero VAD (existing), faster-whisper (existing STT), Python dataclasses, `/dev/shm` for state.

**Spec:** `docs/superpowers/specs/2026-04-02-continuous-perception-design.md`

---

### Task 1: PipeWire webrtc AEC Configuration

**Files:**
- Create: `~/.config/pipewire/pipewire.conf.d/echo-cancel.conf`
- Modify: `agents/hapax_daimonion/audio_input.py:26` (verify source_name default)

- [ ] **Step 1: Create PipeWire echo-cancel config**

```
# ~/.config/pipewire/pipewire.conf.d/echo-cancel.conf
context.modules = [
    {
        name = libpipewire-module-echo-cancel
        args = {
            capture.props = {
                node.name = "echo_cancel_capture"
                node.description = "Echo Cancel Capture"
            }
            source.props = {
                node.name = "echo_cancel_source"
                node.description = "Echo Cancel Source"
            }
            playback.props = {
                node.name = "echo_cancel_playback"
                node.description = "Echo Cancel Playback"
            }
            sink.props = {
                node.name = "echo_cancel_sink"
                node.description = "Echo Cancel Sink"
            }
            library.name = aec/libspa-aec-webrtc
            aec.args = {
                webrtc.gain_controller = true
                webrtc.noise_suppression = true
                webrtc.extended_filter = true
            }
        }
    }
]
```

- [ ] **Step 2: Restart PipeWire and verify the echo-cancel node appears**

Run: `systemctl --user restart pipewire.service && sleep 2 && pw-cli ls Node | grep echo_cancel`
Expected: Four nodes appear: `echo_cancel_capture`, `echo_cancel_source`, `echo_cancel_playback`, `echo_cancel_sink`

- [ ] **Step 3: Verify ERLE — play test tone, measure attenuation**

Run:
```bash
# Terminal 1: record from echo-cancelled source
pw-record --target echo_cancel_source /tmp/aec_test.wav &
REC_PID=$!
# Terminal 2: play a test signal
pw-play --target echo_cancel_sink /usr/share/sounds/freedesktop/stereo/phone-incoming-call.oga
sleep 2
kill $REC_PID
# Check energy in recorded file — should be near-silence if AEC works
python3 -c "
import wave, struct, math
w = wave.open('/tmp/aec_test.wav')
frames = w.readframes(w.getnframes())
samples = struct.unpack(f'<{w.getnframes()}h', frames)
rms = math.sqrt(sum(s*s for s in samples) / len(samples))
print(f'RMS: {rms:.1f} (should be < 500 for good AEC, raw mic would be > 3000)')
"
```
Expected: RMS < 500 (30+ dB attenuation from raw signal)

- [ ] **Step 4: Verify audio_input.py targets the correct source**

Read `agents/hapax_daimonion/audio_input.py:26`. The default `source_name="echo_cancel_capture"` is correct — this is the virtual source created by PipeWire's module. No code change needed if default matches.

Verify the daemon's pw-cat targets it:
Run: `journalctl --user -u hapax-daimonion.service | grep "pw-cat started" | tail -1`
Expected: Contains `target=echo_cancel_capture` (not the raw Blue Yeti ALSA name)

Note: if pw-cat falls back to raw mic when `echo_cancel_capture` doesn't exist, it will now use the correct source after PipeWire restart. Restart daimonion after PipeWire restart to pick up the new node.

- [ ] **Step 5: Commit**

```bash
git add ~/.config/pipewire/pipewire.conf.d/echo-cancel.conf
git commit -m "infra: add PipeWire webrtc echo-cancel module config

Replaces application-level speexdsp AEC. webrtc module includes
nonlinear processing (NLP) for speaker distortion and room reverb."
```

Note: PipeWire config is outside the repo. Copy to `systemd/pipewire/echo-cancel.conf` in the repo and add a symlink or install script so it's tracked.

---

### Task 2: TTS Energy Tracker

**Files:**
- Create: `agents/hapax_daimonion/energy_classifier.py`
- Test: `tests/hapax_daimonion/test_energy_classifier.py`

- [ ] **Step 1: Write failing tests for TtsEnergyTracker**

```python
# tests/hapax_daimonion/test_energy_classifier.py
import struct
import time
from unittest.mock import patch

from agents.hapax_daimonion.energy_classifier import TtsEnergyTracker


def _make_pcm(amplitude: int = 10000, n_samples: int = 480) -> bytes:
    """Generate a mono int16 PCM frame at given amplitude."""
    return struct.pack(f"<{n_samples}h", *([amplitude] * n_samples))


def _silence(n_samples: int = 480) -> bytes:
    return b"\x00\x00" * n_samples


class TestTtsEnergyTracker:
    def test_inactive_when_no_tts(self):
        t = TtsEnergyTracker()
        assert not t.is_active()

    def test_active_after_record(self):
        t = TtsEnergyTracker()
        t.record(_make_pcm())
        assert t.is_active()

    def test_inactive_after_decay(self):
        t = TtsEnergyTracker(decay_s=0.1)
        t.record(_make_pcm())
        with patch("time.monotonic", return_value=time.monotonic() + 0.2):
            assert not t.is_active()

    def test_expected_energy_tracks_tts(self):
        t = TtsEnergyTracker()
        t.record(_make_pcm(amplitude=10000))
        energy = t.expected_energy()
        assert energy > 5000  # should be close to 10000 RMS

    def test_expected_energy_zero_when_inactive(self):
        t = TtsEnergyTracker()
        assert t.expected_energy() == 0.0

    def test_ring_buffer_bounded(self):
        t = TtsEnergyTracker(buffer_size=5)
        for _ in range(20):
            t.record(_make_pcm())
        # Internal buffer should not exceed buffer_size
        assert len(t._energy_ring) <= 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/hapax_daimonion/test_energy_classifier.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.hapax_daimonion.energy_classifier'`

- [ ] **Step 3: Implement TtsEnergyTracker**

```python
# agents/hapax_daimonion/energy_classifier.py
"""Energy-ratio echo classification for continuous perception.

Layer 2 of the three-layer echo discrimination stack:
  Layer 1: PipeWire webrtc AEC (hardware-level)
  Layer 2: Energy-ratio classifier (this module)
  Layer 3: Adaptive VAD thresholds (conversation_buffer.py)

Replaces feed_reference() — instead of feeding raw PCM to an echo
canceller, we record the energy envelope for frame classification.
"""

from __future__ import annotations

import math
import struct
import time
from collections import deque


def _rms_int16(pcm: bytes) -> float:
    """Compute RMS energy of int16 PCM."""
    n = len(pcm) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack(f"<{n}h", pcm)
    return math.sqrt(sum(s * s for s in samples) / n)


class TtsEnergyTracker:
    """Ring buffer of TTS output RMS energy for echo classification.

    Fed at each TTS write point (replaces feed_reference). The energy
    envelope is compared against mic input to distinguish residual echo
    from real operator speech.
    """

    def __init__(self, buffer_size: int = 100, decay_s: float = 1.5) -> None:
        self._energy_ring: deque[tuple[float, float]] = deque(maxlen=buffer_size)
        self._decay_s = decay_s
        self._last_record_at: float = 0.0

    def record(self, pcm: bytes) -> None:
        """Record RMS energy of a TTS PCM chunk."""
        rms = _rms_int16(pcm)
        now = time.monotonic()
        self._energy_ring.append((now, rms))
        self._last_record_at = now

    def is_active(self) -> bool:
        """True when system has spoken recently (within decay window)."""
        if self._last_record_at == 0.0:
            return False
        return (time.monotonic() - self._last_record_at) < self._decay_s

    def expected_energy(self) -> float:
        """Current expected echo energy level (RMS of recent TTS)."""
        if not self.is_active():
            return 0.0
        now = time.monotonic()
        recent = [e for t, e in self._energy_ring if now - t < self._decay_s]
        if not recent:
            return 0.0
        return sum(recent) / len(recent)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/hapax_daimonion/test_energy_classifier.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_daimonion/energy_classifier.py tests/hapax_daimonion/test_energy_classifier.py
git commit -m "feat(voice): add TtsEnergyTracker for echo classification (Layer 2)"
```

---

### Task 3: Energy-Ratio Frame Classifier

**Files:**
- Modify: `agents/hapax_daimonion/energy_classifier.py`
- Test: `tests/hapax_daimonion/test_energy_classifier.py` (append)

- [ ] **Step 1: Write failing tests for EnergyClassifier**

```python
# Append to tests/hapax_daimonion/test_energy_classifier.py

from agents.hapax_daimonion.energy_classifier import EnergyClassifier


class TestEnergyClassifier:
    def test_silence_when_not_speaking(self):
        tracker = TtsEnergyTracker()
        c = EnergyClassifier(tracker)
        result = c.classify(_silence(), system_speaking=False)
        assert result == "silent"

    def test_speech_when_not_speaking(self):
        tracker = TtsEnergyTracker()
        c = EnergyClassifier(tracker)
        result = c.classify(_make_pcm(amplitude=5000), system_speaking=False)
        assert result == "speech"

    def test_echo_when_mic_tracks_tts(self):
        tracker = TtsEnergyTracker()
        tracker.record(_make_pcm(amplitude=10000))
        c = EnergyClassifier(tracker)
        # Mic energy similar to TTS energy = residual echo
        result = c.classify(_make_pcm(amplitude=8000), system_speaking=True)
        assert result == "echo"

    def test_speech_when_mic_exceeds_tts(self):
        tracker = TtsEnergyTracker()
        tracker.record(_make_pcm(amplitude=2000))  # quiet TTS
        c = EnergyClassifier(tracker)
        # Mic energy much higher than expected echo = real speech
        result = c.classify(_make_pcm(amplitude=10000), system_speaking=True)
        assert result == "speech"

    def test_silent_frame_during_tts(self):
        tracker = TtsEnergyTracker()
        tracker.record(_make_pcm(amplitude=10000))
        c = EnergyClassifier(tracker)
        result = c.classify(_silence(), system_speaking=True)
        assert result == "silent"

    def test_not_speaking_always_speech_or_silent(self):
        """When system is not speaking, never classify as echo."""
        tracker = TtsEnergyTracker()
        tracker.record(_make_pcm(amplitude=10000))
        c = EnergyClassifier(tracker)
        result = c.classify(_make_pcm(amplitude=8000), system_speaking=False)
        assert result in ("speech", "silent")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/hapax_daimonion/test_energy_classifier.py::TestEnergyClassifier -v`
Expected: FAIL — `ImportError: cannot import name 'EnergyClassifier'`

- [ ] **Step 3: Implement EnergyClassifier**

Append to `agents/hapax_daimonion/energy_classifier.py`:

```python
# Silence threshold: below this RMS, frame is silent regardless
_SILENCE_THRESHOLD = 300.0

# Echo ratio: if mic_rms / expected_tts_rms < this, it's likely echo
# (mic energy is "explained by" the known playback signal)
_ECHO_RATIO_CEILING = 1.5

# Speech floor: mic must exceed this RMS to be considered speech during TTS
_SPEECH_FLOOR_DURING_TTS = 1000.0


class EnergyClassifier:
    """Per-frame classification: speech vs residual echo vs silence.

    During system speech, compares mic frame energy against the known
    TTS energy envelope. High correlation = residual echo. Low
    correlation with high energy = real operator speech.
    """

    def __init__(self, tracker: TtsEnergyTracker) -> None:
        self._tracker = tracker

    def classify(self, mic_frame: bytes, *, system_speaking: bool) -> str:
        """Classify a single mic frame.

        Returns:
            "speech" — real operator speech (pass to VAD/buffer)
            "echo"   — residual echo of system output (suppress)
            "silent"  — below energy threshold (pass through, VAD handles)
        """
        mic_rms = _rms_int16(mic_frame)

        if mic_rms < _SILENCE_THRESHOLD:
            return "silent"

        if not system_speaking:
            return "speech"

        expected = self._tracker.expected_energy()
        if expected < _SILENCE_THRESHOLD:
            # Tracker has no recent TTS energy — can't be echo
            return "speech"

        # During system speech: compare mic energy against expected echo level.
        # AEC already attenuated ~30dB, so residual echo is much lower than
        # the original TTS. If mic energy is close to or below expected
        # residual level, it's echo. If much higher, it's real speech.
        ratio = mic_rms / expected
        if ratio < _ECHO_RATIO_CEILING and mic_rms < _SPEECH_FLOOR_DURING_TTS:
            return "echo"

        return "speech"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/hapax_daimonion/test_energy_classifier.py -v`
Expected: All 12 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_daimonion/energy_classifier.py tests/hapax_daimonion/test_energy_classifier.py
git commit -m "feat(voice): add EnergyClassifier — echo vs speech discrimination (Layer 2)"
```

---

### Task 4: Speech-During-Production Classifier

**Files:**
- Create: `agents/hapax_daimonion/speech_classifier.py`
- Test: `tests/hapax_daimonion/test_speech_classifier.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/hapax_daimonion/test_speech_classifier.py
from unittest.mock import AsyncMock

import pytest

from agents.hapax_daimonion.speech_classifier import (
    BackchannelSignal,
    DuringProductionClassifier,
    FloorClaim,
)


def _fake_frames(duration_s: float = 0.5) -> list[bytes]:
    """Generate fake speech frames for given duration."""
    n_frames = int(duration_s / 0.03)  # 30ms per frame
    return [b"\x00\x01" * 480] * n_frames


class TestDuringProductionClassifier:
    @pytest.mark.asyncio
    async def test_backchannel_from_transcript(self):
        stt = AsyncMock(return_value="yeah")
        c = DuringProductionClassifier(stt=stt)
        result = await c.classify(_fake_frames(0.5))
        assert isinstance(result, BackchannelSignal)
        assert result.transcript == "yeah"

    @pytest.mark.asyncio
    async def test_floor_claim_from_transcript(self):
        stt = AsyncMock(return_value="actually I wanted to ask about the drift items")
        c = DuringProductionClassifier(stt=stt)
        result = await c.classify(_fake_frames(2.0))
        assert isinstance(result, FloorClaim)
        assert "drift" in result.transcript

    @pytest.mark.asyncio
    async def test_fallback_short_duration_is_backchannel(self):
        stt = AsyncMock(side_effect=TimeoutError)
        c = DuringProductionClassifier(stt=stt)
        result = await c.classify(_fake_frames(0.4))
        assert isinstance(result, BackchannelSignal)

    @pytest.mark.asyncio
    async def test_fallback_long_duration_is_floor_claim(self):
        stt = AsyncMock(side_effect=TimeoutError)
        c = DuringProductionClassifier(stt=stt)
        result = await c.classify(_fake_frames(1.5))
        assert isinstance(result, FloorClaim)

    @pytest.mark.asyncio
    async def test_empty_transcript_is_backchannel(self):
        stt = AsyncMock(return_value="")
        c = DuringProductionClassifier(stt=stt)
        result = await c.classify(_fake_frames(0.3))
        assert isinstance(result, BackchannelSignal)

    @pytest.mark.asyncio
    async def test_phatic_variations(self):
        c = DuringProductionClassifier(stt=AsyncMock())
        for token in ["mm-hm", "uh-huh", "okay", "right", "sure", "got it", "I see", "go on"]:
            c._stt.return_value = token
            result = await c.classify(_fake_frames(0.5))
            assert isinstance(result, BackchannelSignal), f"'{token}' should be backchannel"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/hapax_daimonion/test_speech_classifier.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement DuringProductionClassifier**

```python
# agents/hapax_daimonion/speech_classifier.py
"""Classify operator speech detected during system output.

Primary: speculative STT → phatic token match → backchannel vs substantive.
Fallback: duration < 1s → backchannel, >= 1s → floor claim.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

FRAME_SAMPLES = 480
SAMPLE_RATE = 16000
_FRAME_DURATION_S = FRAME_SAMPLES / SAMPLE_RATE  # 0.03s

# Phatic tokens that signal backchannel, not floor claim.
# Lowercase, stripped of punctuation.
PHATIC_TOKENS: frozenset[str] = frozenset({
    "yeah", "yep", "yup", "yes",
    "mm-hm", "mm", "mhm", "mmhm", "uh-huh", "uh huh",
    "right", "okay", "ok", "sure",
    "got it", "i see", "go on",
    "hmm", "hm", "ah",
})

_FLOOR_CLAIM_DURATION_S = 1.0
_STT_TIMEOUT_S = 2.0


@dataclass
class BackchannelSignal:
    """Operator backchannel during system speech — grounding evidence."""

    transcript: str
    confidence: float = 1.0


@dataclass
class FloorClaim:
    """Operator claiming the floor — Hapax should yield."""

    utterance_bytes: bytes
    transcript: str


def _is_phatic(text: str) -> bool:
    """Check if transcript matches a known phatic/backchannel token."""
    normalized = text.lower().strip().rstrip(".,!?")
    return normalized in PHATIC_TOKENS


class DuringProductionClassifier:
    """Classify operator speech detected during system output.

    Primary path: run STT on speech frames, match against phatic token set.
    Fallback: if STT fails or times out, use duration heuristic.
    """

    def __init__(self, stt: object) -> None:
        self._stt = stt

    async def classify(
        self, speech_frames: list[bytes]
    ) -> BackchannelSignal | FloorClaim:
        """Classify accumulated speech frames from during production.

        Returns BackchannelSignal (grounding) or FloorClaim (yield).
        """
        duration_s = len(speech_frames) * _FRAME_DURATION_S
        utterance_bytes = b"".join(speech_frames)

        # Try STT classification (primary)
        try:
            transcript = await asyncio.wait_for(
                self._stt(utterance_bytes), timeout=_STT_TIMEOUT_S
            )
            transcript = (transcript or "").strip()

            if not transcript or _is_phatic(transcript):
                log.info(
                    "Backchannel (STT): %r (%.1fs)",
                    transcript or "(empty)", duration_s,
                )
                return BackchannelSignal(transcript=transcript)

            log.info(
                "Floor claim (STT): %r (%.1fs)",
                transcript[:60], duration_s,
            )
            return FloorClaim(utterance_bytes=utterance_bytes, transcript=transcript)

        except (TimeoutError, Exception):
            # Fallback: duration-based classification
            log.info(
                "STT failed/timeout — fallback to duration (%.1fs)", duration_s,
            )

        if duration_s < _FLOOR_CLAIM_DURATION_S:
            return BackchannelSignal(transcript="", confidence=0.5)
        return FloorClaim(utterance_bytes=utterance_bytes, transcript="")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/hapax_daimonion/test_speech_classifier.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_daimonion/speech_classifier.py tests/hapax_daimonion/test_speech_classifier.py
git commit -m "feat(voice): add DuringProductionClassifier — backchannel vs floor claim"
```

---

### Task 5: Remove Application-Level EchoCanceller

**Files:**
- Delete: `agents/hapax_daimonion/echo_canceller.py`
- Modify: `agents/hapax_daimonion/init_audio.py` — remove EchoCanceller init
- Modify: `agents/hapax_daimonion/run_loops.py:45-47` — remove echo_canceller.process()
- Modify: `agents/hapax_daimonion/cpal/runner.py` — remove echo_canceller param and all feed_reference calls
- Modify: `agents/hapax_daimonion/conversation_pipeline.py` — remove echo_canceller param and all feed_reference calls, replace _write_audio with energy tracker
- Modify: `agents/hapax_daimonion/pipeline_start.py` — remove echo_canceller wiring
- Modify: `agents/hapax_daimonion/run_inner.py:55` — remove echo_canceller kwarg
- Modify: `agents/hapax_daimonion/config.py` — remove aec_enabled, aec_tail_ms

- [ ] **Step 1: Delete echo_canceller.py**

Run: `git rm agents/hapax_daimonion/echo_canceller.py`

- [ ] **Step 2: Remove EchoCanceller from init_audio.py**

In `agents/hapax_daimonion/init_audio.py`, replace lines 17-24:

```python
# OLD:
    daemon._echo_canceller = None
    if daemon.cfg.aec_enabled:
        try:
            from agents.hapax_daimonion.echo_canceller import EchoCanceller
            daemon._echo_canceller = EchoCanceller(frame_size=480, tail_ms=daemon.cfg.aec_tail_ms)
        except Exception:
            log.warning("Echo canceller init failed", exc_info=True)
```

Replace with:

```python
    # Energy tracker for Layer 2 echo classification (replaces speexdsp AEC)
    from agents.hapax_daimonion.energy_classifier import EnergyClassifier, TtsEnergyTracker

    daemon._tts_energy_tracker = TtsEnergyTracker()
    daemon._energy_classifier = EnergyClassifier(daemon._tts_energy_tracker)
```

- [ ] **Step 3: Remove echo_canceller.process() from run_loops.py**

In `agents/hapax_daimonion/run_loops.py`, remove lines 45-47:

```python
# DELETE these lines:
        if daemon._echo_canceller is not None:
            frame = daemon._echo_canceller.process(frame)
```

Add energy classification before conversation buffer feed (after noise subtraction, before buffer feed at line 55):

```python
        # Layer 2: energy-ratio classification during system speech
        if daemon._energy_classifier is not None and daemon._conversation_buffer.is_speaking:
            _class = daemon._energy_classifier.classify(
                frame, system_speaking=True,
            )
            if _class == "echo":
                # Don't feed echo frames to conversation buffer
                # (still feed to VAD buffer for presence detection)
                _vad_buf.extend(frame)
                continue
```

Note: the `continue` skips conversation buffer feed AND the VAD-to-buffer update, but still feeds presence. Adjust the loop structure: move VAD buffer extend above the classification, and only skip the conversation buffer feed.

Actually, restructure the section after noise subtraction:

```python
        if daemon._noise_reference is not None:
            frame = daemon._noise_reference.subtract(frame)
        if daemon._audio_preprocessor is not None:
            frame = daemon._audio_preprocessor.process(frame)

        _vad_buf.extend(frame)

        # Layer 2: skip echo frames for conversation buffer only
        _is_echo = False
        if (
            daemon._energy_classifier is not None
            and daemon._conversation_buffer.is_speaking
        ):
            _is_echo = daemon._energy_classifier.classify(
                frame, system_speaking=True,
            ) == "echo"

        if daemon._conversation_buffer.is_active and not _is_echo:
            daemon._conversation_buffer.feed_audio(frame)
```

- [ ] **Step 4: Remove echo_canceller from CPAL runner**

In `agents/hapax_daimonion/cpal/runner.py`:

Remove `echo_canceller` parameter from `__init__` (line 58) and `self._echo_canceller = echo_canceller` (line 85).

In `_process_utterance` T1 section (~line 379-380), remove:
```python
                        if self._echo_canceller:
                            self._echo_canceller.feed_reference(pcm)
```

In `_execute_backchannel` (~line 420-421), remove:
```python
                if self._echo_canceller:
                    self._echo_canceller.feed_reference(pcm)
```

In `_execute_composed` (~line 436-437), remove:
```python
                    if self._echo_canceller:
                        self._echo_canceller.feed_reference(pcm)
```

Add `tts_energy_tracker` parameter to `__init__`:
```python
        tts_energy_tracker: object | None = None,
```
Store as `self._tts_energy_tracker = tts_energy_tracker`.

After each `audio_output.write(pcm)` in T1/backchannel production, add:
```python
                        if self._tts_energy_tracker:
                            self._tts_energy_tracker.record(pcm)
```

- [ ] **Step 5: Remove echo_canceller from conversation_pipeline.py**

Remove `echo_canceller` parameter from `__init__` (~line 83) and `self._echo_canceller = echo_canceller` (~line 106).

Add `tts_energy_tracker` parameter:
```python
        tts_energy_tracker=None,
```
Store as `self._tts_energy_tracker = tts_energy_tracker`.

Replace `_write_audio` static method:

```python
    @staticmethod
    def _write_audio(audio_output, tts_energy_tracker, pcm: bytes) -> None:
        """Write PCM to audio output and record energy for echo classification."""
        try:
            if tts_energy_tracker:
                tts_energy_tracker.record(pcm)
            audio_output.write(pcm)
        except Exception:
            pass
```

Update the call site in `_speak_sentence` (~line 1700-1708):

```python
                ao = self._audio_output
                tracker = self._tts_energy_tracker
                loop.run_in_executor(
                    _audio_executor,
                    self._write_audio,
                    ao,
                    tracker,
                    pcm,
                )
```

Remove all other `feed_reference()` calls (lines 697, 1241, 1362) and replace with `self._tts_energy_tracker.record(pcm)` where TTS PCM is written.

- [ ] **Step 6: Update pipeline_start.py wiring**

In `pipeline_start.py`, replace `echo_canceller=daemon._echo_canceller` with `tts_energy_tracker=daemon._tts_energy_tracker` in the `ConversationPipeline()` constructor call (~line 146).

In `run_inner.py`, replace `echo_canceller=getattr(daemon, "_echo_canceller", None)` with `tts_energy_tracker=getattr(daemon, "_tts_energy_tracker", None)` (~line 55).

Update CPAL runner wiring in `pipeline_start.py` (~line 183 area) to pass `tts_energy_tracker`.

- [ ] **Step 7: Remove config fields**

In `agents/hapax_daimonion/config.py`, remove:
```python
    aec_enabled: bool = True
    aec_tail_ms: int = 500
```

- [ ] **Step 8: Run tests**

Run: `uv run pytest tests/hapax_daimonion/ -q`
Expected: All pass. Some tests that mock echo_canceller may need updating — fix any import errors.

- [ ] **Step 9: Lint**

Run: `uv run ruff check agents/hapax_daimonion/ --fix`
Expected: Clean (unused imports from echo_canceller removed)

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "refactor(voice): remove speexdsp EchoCanceller, wire TtsEnergyTracker

PipeWire webrtc AEC handles echo cancellation at the audio server
level. Application-level speexdsp removed. TtsEnergyTracker records
TTS energy envelope for Layer 2 classification."
```

---

### Task 6: Remove Buffer Audio Gates — Enable Continuous Perception

**Files:**
- Modify: `agents/hapax_daimonion/conversation_buffer.py`
- Modify: `tests/hapax_daimonion/test_conversation_buffer.py`

- [ ] **Step 1: Write tests for new adaptive VAD behavior**

```python
# Append to tests/hapax_daimonion/test_conversation_buffer.py

class TestAdaptiveVad:
    """Tests for continuous perception — no _speaking gate."""

    def test_vad_updates_during_speaking(self):
        """VAD must process during system speech (was gated before)."""
        buf = ConversationBuffer()
        buf.activate()
        buf.set_speaking(True)
        # Feed high-confidence VAD during system speech
        for _ in range(10):
            buf.update_vad(0.9)
        # speech_active should be True — adaptive threshold is 0.8, we sent 0.9
        assert buf.speech_active

    def test_vad_requires_higher_threshold_during_speaking(self):
        """During system speech, VAD threshold rises to 0.8."""
        buf = ConversationBuffer()
        buf.activate()
        buf.set_speaking(True)
        # 0.5 exceeds normal threshold but not adaptive 0.8
        for _ in range(10):
            buf.update_vad(0.5)
        assert not buf.speech_active

    def test_frames_accumulated_during_speaking(self):
        """Audio frames must accumulate during system speech."""
        buf = ConversationBuffer()
        buf.activate()
        buf.set_speaking(True)
        # Trigger speech first
        for _ in range(10):
            buf.update_vad(0.9)
        # Feed frames
        for _ in range(5):
            buf.feed_audio(b"\x01\x00" * 480)
        assert len(buf._speech_frames) >= 5

    def test_no_cooldown_exists(self):
        """Cooldown mechanism must be removed entirely."""
        buf = ConversationBuffer()
        assert not hasattr(buf, "in_cooldown") or not buf.in_cooldown
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/hapax_daimonion/test_conversation_buffer.py::TestAdaptiveVad -v`
Expected: FAIL — `test_vad_updates_during_speaking` fails because `_speaking` gate returns early

- [ ] **Step 3: Rewrite conversation_buffer.py gates**

Replace the `feed_audio` method:

```python
    def feed_audio(self, frame: bytes) -> None:
        if not self._active:
            return
        self._pre_roll.append(frame)

        # Always accumulate speech frames when speech is active.
        # Echo discrimination is handled upstream (PipeWire AEC + energy classifier).
        if self._speech_active:
            self._speech_frames.append(frame)
            if len(self._speech_frames) >= self._max_frames:
                self._emit_utterance()
```

Replace the `update_vad` method:

```python
    def update_vad(self, probability: float) -> None:
        if not self._active:
            return

        # Adaptive threshold: higher during system speech to filter
        # residual echo that passes through PipeWire AEC + energy classifier.
        if self._speaking:
            start_threshold = 0.8  # raised from 0.15
            consecutive_required = 7  # ~210ms sustained (raised from 3)
        else:
            start_threshold = SPEECH_START_PROB  # 0.15
            consecutive_required = SPEECH_START_CONSECUTIVE  # 3

        if probability >= start_threshold:
            self._consecutive_speech += 1
            self._consecutive_silence = 0
            if not self._speech_active and self._consecutive_speech >= consecutive_required:
                self._speech_active = True
                self._speech_start_time = time.monotonic()
                self._speech_frames = list(self._pre_roll) + self._speech_frames
        elif probability < SPEECH_END_PROB:
            self._consecutive_silence += 1
            self._consecutive_speech = 0
            if self._speech_active:
                speech_duration = time.monotonic() - self._speech_start_time
                if speech_duration > 3.0:
                    threshold = SPEECH_END_LONG
                elif speech_duration < 1.0:
                    threshold = SPEECH_END_SHORT
                else:
                    threshold = SPEECH_END_DEFAULT
                if self._consecutive_silence >= threshold:
                    self._emit_utterance()
```

Simplify `set_speaking`:

```python
    def set_speaking(self, speaking: bool) -> None:
        """Track system speech state for adaptive VAD thresholds.

        No longer gates audio — perception is continuous.
        """
        self._speaking = speaking
        if speaking:
            self._speaking_started_at = time.monotonic()
```

Remove `in_cooldown` property, `POST_TTS_COOLDOWN_S` constant, `_speaking_ended_at` field, `_dynamic_cooldown_s` computation.

Remove the cooldown import/constant at the top of the file. Update module docstring to reflect the new architecture.

- [ ] **Step 4: Run all buffer tests**

Run: `uv run pytest tests/hapax_daimonion/test_conversation_buffer.py -v`
Expected: All pass (some existing tests may need threshold adjustments if they relied on the speaking gate)

- [ ] **Step 5: Commit**

```bash
git add agents/hapax_daimonion/conversation_buffer.py tests/hapax_daimonion/test_conversation_buffer.py
git commit -m "feat(voice): remove audio gates — continuous perception during system speech

Buffer no longer goes deaf during TTS. Adaptive VAD thresholds (0.8
during system speech, 0.15 during silence) replace binary muting.
Cooldown mechanism removed entirely."
```

---

### Task 7: Wire Classification Into CPAL Runner

**Files:**
- Modify: `agents/hapax_daimonion/cpal/runner.py`
- Modify: `agents/hapax_daimonion/pipeline_start.py` (wiring)

- [ ] **Step 1: Add speech_classifier parameter to CpalRunner**

Add to `__init__`:
```python
        speech_classifier: object | None = None,
```
Store as `self._speech_classifier = speech_classifier`.

Add tracking state:
```python
        self._during_production_frames: list[bytes] = []
        self._during_production_speech_start: float = 0.0
```

- [ ] **Step 2: Replace utterance dispatch logic in _tick()**

Replace the utterance dispatch section (lines 211-223):

```python
        # 4. Check for utterances — route based on production state
        if self._production.is_producing:
            # During production: accumulate speech for classification
            utterance = self._perception.get_utterance()
            if utterance is not None and self._speech_classifier is not None:
                asyncio.create_task(self._classify_during_production(utterance))
            elif utterance is not None:
                # No classifier — fall back to drain (legacy)
                log.debug("CPAL: utterance during production drained (no classifier)")
        else:
            # Not producing: normal utterance dispatch
            utterance = self._queued_utterance or self._perception.get_utterance()
            self._queued_utterance = None
            if utterance is not None and self._processing_utterance:
                log.info("CPAL: utterance arrived during processing — queued for next tick")
                self._queued_utterance = utterance
            elif utterance is not None:
                asyncio.create_task(self._process_utterance(utterance))
```

- [ ] **Step 3: Implement _classify_during_production()**

Add method to CpalRunner:

```python
    async def _classify_during_production(self, utterance: bytes) -> None:
        """Classify operator speech detected during system output.

        Routes to grounding ledger (backchannel) or yields production (floor claim).
        """
        from agents.hapax_daimonion.speech_classifier import BackchannelSignal, FloorClaim

        try:
            result = await self._speech_classifier.classify(
                [utterance],  # already concatenated bytes, wrap in list
            )

            if isinstance(result, BackchannelSignal):
                # Feed to grounding ledger as acceptance evidence
                if self._grounding._ledger is not None:
                    self._grounding._ledger.record_acceptance(
                        acceptance_type="ACCEPT", concern_overlap=0.5,
                    )
                self._evaluator.gain_controller.apply(
                    GainUpdate(delta=0.02, source="operator_backchannel"),
                )
                log.info("CPAL: backchannel during production: %r", result.transcript)

            elif isinstance(result, FloorClaim):
                # Yield production, queue utterance for T3
                self._production.yield_to_operator()
                if self._pipeline and hasattr(self._pipeline, "buffer"):
                    self._pipeline.buffer.set_speaking(False)
                self._queued_utterance = result.utterance_bytes
                log.info("CPAL: floor claim during production: %r", result.transcript[:60])

        except Exception:
            log.debug("During-production classification failed", exc_info=True)
```

- [ ] **Step 4: Replace binary barge-in detection (line 261-266)**

Replace:
```python
        # 8. Barge-in detection
        if self._production.is_producing and signals.speech_active and signals.vad_confidence > 0.9:
            self._production.interrupt()
            if self._pipeline and hasattr(self._pipeline, "buffer") and self._pipeline.buffer:
                self._pipeline.buffer.set_speaking(False)
            log.info("CPAL barge-in: operator interrupted production")
```

With:
```python
        # 8. Barge-in is now handled by _classify_during_production (step 4 above).
        # No binary threshold — speech during production flows through the classifier.
```

- [ ] **Step 5: Wire in pipeline_start.py**

In the CPAL runner construction, add:
```python
    from agents.hapax_daimonion.speech_classifier import DuringProductionClassifier

    async def _stt_for_classifier(audio: bytes) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, daemon._resident_stt.transcribe_sync, audio)

    daemon._speech_classifier = DuringProductionClassifier(stt=_stt_for_classifier)
```

Pass to CpalRunner:
```python
    speech_classifier=daemon._speech_classifier,
```

- [ ] **Step 6: Run all tests**

Run: `uv run pytest tests/hapax_daimonion/ -q`
Expected: All pass

- [ ] **Step 7: Lint**

Run: `uv run ruff check agents/hapax_daimonion/ --fix`

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(voice): wire speech classifier into CPAL — backchannel/floor-claim routing

Operator speech during system output classified via speculative STT:
backchannel → grounding ledger, floor claim → yield production.
Replaces binary 0.9-threshold barge-in."
```

---

### Task 8: Integration Test + Live Verification

**Files:**
- No new files — system-level verification

- [ ] **Step 1: Restart PipeWire + daimonion**

```bash
systemctl --user restart pipewire.service
sleep 3
systemctl --user restart hapax-daimonion.service
sleep 15
```

- [ ] **Step 2: Verify PipeWire AEC node exists**

Run: `pw-cli ls Node | grep echo_cancel`
Expected: `echo_cancel_capture`, `echo_cancel_source` appear

- [ ] **Step 3: Verify daimonion uses echo_cancel_capture**

Run: `journalctl --user -u hapax-daimonion.service --since "30 seconds ago" | grep "pw-cat started"`
Expected: `target=echo_cancel_capture`

- [ ] **Step 4: Verify no EchoCanceller references in logs**

Run: `journalctl --user -u hapax-daimonion.service --since "1 minute ago" | grep -i "echo.*canceller\|speexdsp"`
Expected: No matches

- [ ] **Step 5: Verify Langfuse scoring works**

Speak a sentence. Check:
Run: `journalctl --user -u hapax-daimonion.service --since "1 minute ago" | grep "LLM full response"`
Expected: Full response with `reason=stop`, not truncated

- [ ] **Step 6: Verify no echo loop**

After system speaks, wait in silence. Check:
Run: `journalctl --user -u hapax-daimonion.service --since "30 seconds ago" | grep "Echo rejected\|transcript="`
Expected: No false echo transcripts triggering T3

- [ ] **Step 7: Test backchannel during system speech**

While system is speaking, say "mm-hm" or "yeah". Check:
Run: `journalctl --user -u hapax-daimonion.service --since "30 seconds ago" | grep "backchannel"`
Expected: `CPAL: backchannel during production: "yeah"` or similar

- [ ] **Step 8: Test floor claim during system speech**

While system is speaking, say a full sentence. Check:
Run: `journalctl --user -u hapax-daimonion.service --since "30 seconds ago" | grep "floor claim"`
Expected: `CPAL: floor claim during production:` + system yields and processes your utterance

- [ ] **Step 9: Commit integration verification notes**

```bash
git commit --allow-empty -m "verify: continuous perception integration test passed

PipeWire webrtc AEC active, energy classifier operational,
adaptive VAD thresholds working, backchannel/floor-claim
classification functional."
```

---

### Task 9: Cleanup and Documentation

**Files:**
- Modify: `agents/hapax_daimonion/conversation_buffer.py` (docstring)
- Modify: CLAUDE.md voice section if needed

- [ ] **Step 1: Update conversation_buffer.py module docstring**

Replace the module docstring to reflect the new architecture:

```python
"""Conversation buffer — continuous audio accumulation for STT.

Third consumer in _audio_loop(). Accumulates raw PCM frames during
detected speech and delivers complete utterances when silence is
detected. Runs inline — no extra task, no mic ownership.

Pre-roll: captures 1500ms of audio before speech onset so word
beginnings aren't clipped.

Echo handling: three-layer stack.
  Layer 1: PipeWire webrtc AEC (echo cancellation at audio server level)
  Layer 2: Energy-ratio classifier in audio_loop (residual echo discrimination)
  Layer 3: Adaptive VAD thresholds (0.8 during system speech, 0.15 otherwise)

The buffer NEVER goes deaf. Perception is continuous per CPAL spec §7.4.
Operator speech during system output is classified (backchannel vs floor
claim) by the CPAL runner, not dropped.
"""
```

- [ ] **Step 2: Track PipeWire config in repo**

```bash
mkdir -p systemd/pipewire
cp ~/.config/pipewire/pipewire.conf.d/echo-cancel.conf systemd/pipewire/echo-cancel.conf
```

- [ ] **Step 3: Final lint + test**

Run: `uv run ruff check agents/hapax_daimonion/ && uv run pytest tests/hapax_daimonion/ -q`
Expected: All clean, all pass

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs: update buffer docstring + track PipeWire echo-cancel config"
```
