# Voice Audio Input Loop Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire continuous microphone audio into the hapax-voice daemon so wake word detection, VAD presence scoring, and Gemini Live streaming all function in real time.

**Architecture:** A new `AudioInputStream` class opens a PyAudio callback stream on the PipeWire echo-cancelled virtual source (`echo_cancel_capture`). An async distribution loop in `VoiceDaemon` fans each 30ms frame to WakeWordDetector, PresenceDetector, and (when active) GeminiLiveSession. The daemon degrades gracefully to visual-only mode if audio hardware is unavailable.

**Tech Stack:** PyAudio (already in pyproject.toml), asyncio, numpy, PipeWire/ALSA

**Design doc:** `docs/plans/2026-03-09-voice-audio-input-design.md`

---

## Task 1: AudioInputStream — Core Class

**Files:**
- Create: `agents/hapax_voice/audio_input.py`
- Test: `tests/hapax_voice/test_audio_input.py`

**Context:** This class wraps PyAudio in callback mode. The callback writes raw PCM frames to a thread-safe `queue.Queue`. The async `get_frame()` method pulls from the queue using `run_in_executor`. The class selects the echo-cancelled PipeWire source by name, falling back to the default input device.

**Step 1: Write the failing tests**

Create `tests/hapax_voice/test_audio_input.py`:

```python
"""Tests for AudioInputStream — PyAudio wrapper with device selection."""
from __future__ import annotations

import queue
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from agents.hapax_voice.audio_input import AudioInputStream


# --- Device selection ---

class TestDeviceSelection:
    """AudioInputStream finds the echo_cancel_capture device by name."""

    def test_finds_echo_cancel_device(self):
        """Selects the device whose name contains the source_name."""
        mock_pa = MagicMock()
        mock_pa.get_device_count.return_value = 3
        mock_pa.get_device_info_by_index.side_effect = [
            {"index": 0, "name": "Built-in Microphone", "maxInputChannels": 2},
            {"index": 1, "name": "echo_cancel_capture", "maxInputChannels": 1},
            {"index": 2, "name": "Monitor of Built-in Audio", "maxInputChannels": 2},
        ]
        with patch("agents.hapax_voice.audio_input.pyaudio.PyAudio", return_value=mock_pa):
            stream = AudioInputStream(source_name="echo_cancel_capture")
            assert stream._device_index == 1

    def test_falls_back_to_default_when_not_found(self):
        """Falls back to None (PyAudio default) when source not found."""
        mock_pa = MagicMock()
        mock_pa.get_device_count.return_value = 1
        mock_pa.get_device_info_by_index.side_effect = [
            {"index": 0, "name": "Built-in Microphone", "maxInputChannels": 2},
        ]
        with patch("agents.hapax_voice.audio_input.pyaudio.PyAudio", return_value=mock_pa):
            stream = AudioInputStream(source_name="echo_cancel_capture")
            assert stream._device_index is None

    def test_skips_output_only_devices(self):
        """Ignores devices with zero input channels."""
        mock_pa = MagicMock()
        mock_pa.get_device_count.return_value = 2
        mock_pa.get_device_info_by_index.side_effect = [
            {"index": 0, "name": "echo_cancel_capture", "maxInputChannels": 0},
            {"index": 1, "name": "echo_cancel_capture input", "maxInputChannels": 1},
        ]
        with patch("agents.hapax_voice.audio_input.pyaudio.PyAudio", return_value=mock_pa):
            stream = AudioInputStream(source_name="echo_cancel_capture")
            assert stream._device_index == 1


# --- Frame queue ---

class TestFrameQueue:
    """Callback writes frames to queue, get_frame() retrieves them."""

    def test_callback_enqueues_frame(self):
        """PyAudio callback writes audio data to internal queue."""
        mock_pa = MagicMock()
        mock_pa.get_device_count.return_value = 0
        with patch("agents.hapax_voice.audio_input.pyaudio.PyAudio", return_value=mock_pa):
            stream = AudioInputStream()
            audio_data = b"\x00" * 960
            # Simulate PyAudio callback
            result = stream._pyaudio_callback(audio_data, 480, {}, 0)
            assert result[1] == 0  # pyaudio.paContinue = 0
            assert stream._queue.get_nowait() == audio_data

    def test_callback_drops_frame_when_queue_full(self):
        """Callback drops frames when queue is full instead of blocking."""
        mock_pa = MagicMock()
        mock_pa.get_device_count.return_value = 0
        with patch("agents.hapax_voice.audio_input.pyaudio.PyAudio", return_value=mock_pa):
            stream = AudioInputStream()
            stream._queue = queue.Queue(maxsize=2)
            stream._queue.put(b"a")
            stream._queue.put(b"b")
            # Third frame should be dropped, not block
            result = stream._pyaudio_callback(b"c", 480, {}, 0)
            assert result[1] == 0  # still paContinue
            assert stream._queue.qsize() == 2

    @pytest.mark.asyncio
    async def test_get_frame_returns_bytes(self):
        """get_frame() returns bytes from the queue."""
        mock_pa = MagicMock()
        mock_pa.get_device_count.return_value = 0
        with patch("agents.hapax_voice.audio_input.pyaudio.PyAudio", return_value=mock_pa):
            stream = AudioInputStream()
            stream._queue.put(b"\x01" * 960)
            frame = await stream.get_frame(timeout=0.1)
            assert frame == b"\x01" * 960

    @pytest.mark.asyncio
    async def test_get_frame_returns_none_on_timeout(self):
        """get_frame() returns None when queue is empty after timeout."""
        mock_pa = MagicMock()
        mock_pa.get_device_count.return_value = 0
        with patch("agents.hapax_voice.audio_input.pyaudio.PyAudio", return_value=mock_pa):
            stream = AudioInputStream()
            frame = await stream.get_frame(timeout=0.01)
            assert frame is None


# --- Lifecycle ---

class TestLifecycle:
    """Start/stop manage the PyAudio stream."""

    def test_start_opens_stream(self):
        """start() opens a PyAudio input stream in callback mode."""
        mock_pa = MagicMock()
        mock_pa.get_device_count.return_value = 0
        mock_stream = MagicMock()
        mock_pa.open.return_value = mock_stream
        with patch("agents.hapax_voice.audio_input.pyaudio.PyAudio", return_value=mock_pa):
            stream = AudioInputStream()
            stream.start()
            mock_pa.open.assert_called_once()
            call_kwargs = mock_pa.open.call_args[1]
            assert call_kwargs["input"] is True
            assert call_kwargs["rate"] == 16000
            assert call_kwargs["channels"] == 1
            assert call_kwargs["stream_callback"] == stream._pyaudio_callback
            assert stream.is_active is True

    def test_stop_closes_stream(self):
        """stop() closes the stream and terminates PyAudio."""
        mock_pa = MagicMock()
        mock_pa.get_device_count.return_value = 0
        mock_stream = MagicMock()
        mock_pa.open.return_value = mock_stream
        with patch("agents.hapax_voice.audio_input.pyaudio.PyAudio", return_value=mock_pa):
            stream = AudioInputStream()
            stream.start()
            stream.stop()
            mock_stream.stop_stream.assert_called_once()
            mock_stream.close.assert_called_once()
            mock_pa.terminate.assert_called_once()
            assert stream.is_active is False

    def test_stop_idempotent(self):
        """stop() can be called multiple times without error."""
        mock_pa = MagicMock()
        mock_pa.get_device_count.return_value = 0
        with patch("agents.hapax_voice.audio_input.pyaudio.PyAudio", return_value=mock_pa):
            stream = AudioInputStream()
            stream.stop()  # Never started
            stream.stop()  # Again
            # No exception raised

    def test_start_failure_sets_inactive(self):
        """If PyAudio.open() raises, is_active remains False."""
        mock_pa = MagicMock()
        mock_pa.get_device_count.return_value = 0
        mock_pa.open.side_effect = OSError("No audio device")
        with patch("agents.hapax_voice.audio_input.pyaudio.PyAudio", return_value=mock_pa):
            stream = AudioInputStream()
            stream.start()  # Should not raise
            assert stream.is_active is False


# --- Frame size ---

class TestFrameSize:
    """Verify frame size calculations."""

    def test_frame_size_30ms_16khz(self):
        """30ms at 16kHz mono int16 = 480 samples = 960 bytes."""
        mock_pa = MagicMock()
        mock_pa.get_device_count.return_value = 0
        with patch("agents.hapax_voice.audio_input.pyaudio.PyAudio", return_value=mock_pa):
            stream = AudioInputStream(sample_rate=16000, frame_ms=30)
            assert stream.frame_samples == 480
            assert stream.frame_bytes == 960
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_audio_input.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.hapax_voice.audio_input'`

**Step 3: Write the implementation**

Create `agents/hapax_voice/audio_input.py`:

```python
"""Continuous audio input from PipeWire/ALSA via PyAudio callback stream."""
from __future__ import annotations

import asyncio
import logging
import queue

import pyaudio

log = logging.getLogger(__name__)

# PyAudio callback return value
_PA_CONTINUE = 0  # pyaudio.paContinue


class AudioInputStream:
    """Wraps a PyAudio input stream with async frame retrieval.

    Opens a callback-mode stream on a named PipeWire/ALSA source.
    Frames are buffered in a thread-safe queue and retrieved via
    the async get_frame() method.
    """

    def __init__(
        self,
        source_name: str = "echo_cancel_capture",
        sample_rate: int = 16000,
        frame_ms: int = 30,
        queue_maxsize: int = 100,
    ) -> None:
        self._source_name = source_name
        self._sample_rate = sample_rate
        self._frame_ms = frame_ms
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=queue_maxsize)
        self._stream: pyaudio.Stream | None = None
        self._active = False

        self._pa = pyaudio.PyAudio()
        self._device_index = self._find_device()

    @property
    def frame_samples(self) -> int:
        """Number of samples per frame."""
        return self._sample_rate * self._frame_ms // 1000

    @property
    def frame_bytes(self) -> int:
        """Number of bytes per frame (int16 = 2 bytes/sample)."""
        return self.frame_samples * 2

    @property
    def is_active(self) -> bool:
        """Whether the audio stream is currently running."""
        return self._active

    def _find_device(self) -> int | None:
        """Find the input device whose name contains source_name."""
        try:
            for i in range(self._pa.get_device_count()):
                info = self._pa.get_device_info_by_index(i)
                if (
                    self._source_name in info.get("name", "")
                    and info.get("maxInputChannels", 0) > 0
                ):
                    log.info("Audio input device: %s (index %d)", info["name"], i)
                    return i
        except Exception as exc:
            log.warning("Error enumerating audio devices: %s", exc)
        log.warning(
            "Audio source '%s' not found, using default input device",
            self._source_name,
        )
        return None

    def start(self) -> None:
        """Open the PyAudio stream. Logs warning on failure."""
        if self._active:
            return
        try:
            self._stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self._sample_rate,
                input=True,
                input_device_index=self._device_index,
                frames_per_buffer=self.frame_samples,
                stream_callback=self._pyaudio_callback,
            )
            self._active = True
            log.info("Audio input stream started (rate=%d, frame=%dms)", self._sample_rate, self._frame_ms)
        except Exception as exc:
            log.warning("Failed to open audio input stream: %s", exc)
            self._active = False

    def stop(self) -> None:
        """Close the stream and terminate PyAudio. Idempotent."""
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._active = False
        try:
            self._pa.terminate()
        except Exception:
            pass

    def _pyaudio_callback(
        self, in_data: bytes, frame_count: int, time_info: dict, status: int
    ) -> tuple[None, int]:
        """PyAudio callback — enqueue frame, never block."""
        try:
            self._queue.put_nowait(in_data)
        except queue.Full:
            pass  # Drop frame rather than block audio thread
        return (None, _PA_CONTINUE)

    async def get_frame(self, timeout: float = 1.0) -> bytes | None:
        """Retrieve the next audio frame asynchronously.

        Returns None if no frame is available within timeout.
        """
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                None, lambda: self._queue.get(timeout=timeout)
            )
        except queue.Empty:
            return None
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_audio_input.py -v`
Expected: All 12 tests PASS

**Step 5: Commit**

```bash
cd ~/projects/ai-agents
git add agents/hapax_voice/audio_input.py tests/hapax_voice/test_audio_input.py
git commit -m "feat(voice): add AudioInputStream — PyAudio wrapper with device selection"
```

---

## Task 2: Audio Distribution Loop

**Files:**
- Modify: `agents/hapax_voice/__main__.py`
- Test: `tests/hapax_voice/test_audio_loop.py`

**Context:** The `VoiceDaemon` needs an `_audio_loop()` async method that reads frames from `AudioInputStream` and distributes them to wake word detection, VAD presence scoring, and (when connected) Gemini Live streaming. One consumer failing must not kill the loop.

**Step 1: Write the failing tests**

Create `tests/hapax_voice/test_audio_loop.py`:

```python
"""Tests for VoiceDaemon._audio_loop() frame distribution."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import numpy as np
import pytest


class TestAudioLoopDistribution:
    """_audio_loop distributes frames to all consumers."""

    @pytest.mark.asyncio
    async def test_frame_sent_to_wake_word(self):
        """Each frame is converted to numpy and passed to wake_word.process_audio()."""
        from agents.hapax_voice.__main__ import VoiceDaemon

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()
            daemon._running = True
            daemon.wake_word = MagicMock()
            daemon.presence = MagicMock()
            daemon._gemini_session = None
            daemon.event_log = MagicMock()

            audio_input = AsyncMock()
            frame = b"\x00\x01" * 480  # 960 bytes
            call_count = 0

            async def get_frame_side_effect(timeout=1.0):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return frame
                daemon._running = False
                return None

            audio_input.get_frame = get_frame_side_effect
            daemon._audio_input = audio_input

            await daemon._audio_loop()

            daemon.wake_word.process_audio.assert_called_once()
            arg = daemon.wake_word.process_audio.call_args[0][0]
            assert isinstance(arg, np.ndarray)
            assert arg.dtype == np.int16
            assert len(arg) == 480

    @pytest.mark.asyncio
    async def test_frame_sent_to_presence(self):
        """Each frame is passed as raw bytes to presence.process_audio_frame()."""
        from agents.hapax_voice.__main__ import VoiceDaemon

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()
            daemon._running = True
            daemon.wake_word = MagicMock()
            daemon.presence = MagicMock()
            daemon._gemini_session = None
            daemon.event_log = MagicMock()

            audio_input = AsyncMock()
            frame = b"\x00\x01" * 480
            call_count = 0

            async def get_frame_side_effect(timeout=1.0):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return frame
                daemon._running = False
                return None

            audio_input.get_frame = get_frame_side_effect
            daemon._audio_input = audio_input

            await daemon._audio_loop()

            daemon.presence.process_audio_frame.assert_called_once_with(frame)

    @pytest.mark.asyncio
    async def test_frame_sent_to_gemini_when_connected(self):
        """Frame sent to gemini_session.send_audio() when session is connected."""
        from agents.hapax_voice.__main__ import VoiceDaemon

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()
            daemon._running = True
            daemon.wake_word = MagicMock()
            daemon.presence = MagicMock()
            daemon._gemini_session = AsyncMock()
            daemon._gemini_session.is_connected = True
            daemon.event_log = MagicMock()

            audio_input = AsyncMock()
            frame = b"\x00\x01" * 480
            call_count = 0

            async def get_frame_side_effect(timeout=1.0):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return frame
                daemon._running = False
                return None

            audio_input.get_frame = get_frame_side_effect
            daemon._audio_input = audio_input

            await daemon._audio_loop()

            daemon._gemini_session.send_audio.assert_awaited_once_with(frame)

    @pytest.mark.asyncio
    async def test_frame_not_sent_to_gemini_when_disconnected(self):
        """Frame NOT sent to gemini_session when session is not connected."""
        from agents.hapax_voice.__main__ import VoiceDaemon

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()
            daemon._running = True
            daemon.wake_word = MagicMock()
            daemon.presence = MagicMock()
            daemon._gemini_session = AsyncMock()
            daemon._gemini_session.is_connected = False
            daemon.event_log = MagicMock()

            audio_input = AsyncMock()
            frame = b"\x00\x01" * 480
            call_count = 0

            async def get_frame_side_effect(timeout=1.0):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return frame
                daemon._running = False
                return None

            audio_input.get_frame = get_frame_side_effect
            daemon._audio_input = audio_input

            await daemon._audio_loop()

            daemon._gemini_session.send_audio.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_gemini_session_attribute(self):
        """Loop works when _gemini_session is None."""
        from agents.hapax_voice.__main__ import VoiceDaemon

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()
            daemon._running = True
            daemon.wake_word = MagicMock()
            daemon.presence = MagicMock()
            daemon._gemini_session = None
            daemon.event_log = MagicMock()

            audio_input = AsyncMock()
            frame = b"\x00\x01" * 480
            call_count = 0

            async def get_frame_side_effect(timeout=1.0):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return frame
                daemon._running = False
                return None

            audio_input.get_frame = get_frame_side_effect
            daemon._audio_input = audio_input

            await daemon._audio_loop()

            daemon.wake_word.process_audio.assert_called_once()
            daemon.presence.process_audio_frame.assert_called_once()


class TestAudioLoopErrorHandling:
    """One bad consumer must not kill the loop."""

    @pytest.mark.asyncio
    async def test_continues_after_wake_word_exception(self):
        """Loop continues distributing after wake_word.process_audio raises."""
        from agents.hapax_voice.__main__ import VoiceDaemon

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()
            daemon._running = True
            daemon.wake_word = MagicMock()
            daemon.wake_word.process_audio.side_effect = RuntimeError("model crashed")
            daemon.presence = MagicMock()
            daemon._gemini_session = None
            daemon.event_log = MagicMock()

            audio_input = AsyncMock()
            frames_returned = 0

            async def get_frame_side_effect(timeout=1.0):
                nonlocal frames_returned
                frames_returned += 1
                if frames_returned <= 2:
                    return b"\x00" * 960
                daemon._running = False
                return None

            audio_input.get_frame = get_frame_side_effect
            daemon._audio_input = audio_input

            await daemon._audio_loop()

            # Presence still got both frames despite wake_word crashing
            assert daemon.presence.process_audio_frame.call_count == 2

    @pytest.mark.asyncio
    async def test_continues_after_presence_exception(self):
        """Loop continues distributing after presence.process_audio_frame raises."""
        from agents.hapax_voice.__main__ import VoiceDaemon

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()
            daemon._running = True
            daemon.wake_word = MagicMock()
            daemon.presence = MagicMock()
            daemon.presence.process_audio_frame.side_effect = ValueError("bad frame")
            daemon._gemini_session = None
            daemon.event_log = MagicMock()

            audio_input = AsyncMock()
            frames_returned = 0

            async def get_frame_side_effect(timeout=1.0):
                nonlocal frames_returned
                frames_returned += 1
                if frames_returned <= 2:
                    return b"\x00" * 960
                daemon._running = False
                return None

            audio_input.get_frame = get_frame_side_effect
            daemon._audio_input = audio_input

            await daemon._audio_loop()

            # Wake word still got both frames despite presence crashing
            assert daemon.wake_word.process_audio.call_count == 2

    @pytest.mark.asyncio
    async def test_continues_after_gemini_exception(self):
        """Loop continues after gemini_session.send_audio raises."""
        from agents.hapax_voice.__main__ import VoiceDaemon

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()
            daemon._running = True
            daemon.wake_word = MagicMock()
            daemon.presence = MagicMock()
            daemon._gemini_session = AsyncMock()
            daemon._gemini_session.is_connected = True
            daemon._gemini_session.send_audio.side_effect = ConnectionError("ws died")
            daemon.event_log = MagicMock()

            audio_input = AsyncMock()
            frames_returned = 0

            async def get_frame_side_effect(timeout=1.0):
                nonlocal frames_returned
                frames_returned += 1
                if frames_returned <= 2:
                    return b"\x00" * 960
                daemon._running = False
                return None

            audio_input.get_frame = get_frame_side_effect
            daemon._audio_input = audio_input

            await daemon._audio_loop()

            # Other consumers still received frames
            assert daemon.wake_word.process_audio.call_count == 2
            assert daemon.presence.process_audio_frame.call_count == 2

    @pytest.mark.asyncio
    async def test_skips_none_frames(self):
        """get_frame() returning None (timeout) causes loop to continue."""
        from agents.hapax_voice.__main__ import VoiceDaemon

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()
            daemon._running = True
            daemon.wake_word = MagicMock()
            daemon.presence = MagicMock()
            daemon._gemini_session = None
            daemon.event_log = MagicMock()

            audio_input = AsyncMock()
            call_count = 0

            async def get_frame_side_effect(timeout=1.0):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return None  # timeout
                if call_count == 2:
                    return b"\x00" * 960
                daemon._running = False
                return None

            audio_input.get_frame = get_frame_side_effect
            daemon._audio_input = audio_input

            await daemon._audio_loop()

            # Only frame 2 was real — consumers called once
            daemon.wake_word.process_audio.assert_called_once()
            daemon.presence.process_audio_frame.assert_called_once()

    @pytest.mark.asyncio
    async def test_exits_when_not_running(self):
        """Loop exits cleanly when _running is set to False."""
        from agents.hapax_voice.__main__ import VoiceDaemon

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()
            daemon._running = False
            daemon.wake_word = MagicMock()
            daemon.presence = MagicMock()
            daemon._gemini_session = None
            daemon.event_log = MagicMock()
            daemon._audio_input = AsyncMock()

            await daemon._audio_loop()

            daemon.wake_word.process_audio.assert_not_called()
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_audio_loop.py -v`
Expected: FAIL with `AttributeError: 'VoiceDaemon' object has no attribute '_audio_loop'`

**Step 3: Implement _audio_loop in VoiceDaemon**

Add this method to the `VoiceDaemon` class in `agents/hapax_voice/__main__.py`, after the existing `_on_wake_word` method:

```python
    async def _audio_loop(self) -> None:
        """Distribute audio frames to wake word, VAD, and Gemini consumers."""
        import numpy as np

        while self._running:
            frame = await self._audio_input.get_frame(timeout=1.0)
            if frame is None:
                continue

            # Wake word detector: expects numpy int16 array
            try:
                audio_np = np.frombuffer(frame, dtype=np.int16)
                self.wake_word.process_audio(audio_np)
            except Exception as exc:
                log.debug("Wake word consumer error: %s", exc)

            # Presence detector: expects raw PCM bytes
            try:
                self.presence.process_audio_frame(frame)
            except Exception as exc:
                log.debug("Presence consumer error: %s", exc)

            # Gemini Live: expects raw PCM bytes, only when connected
            if self._gemini_session is not None and self._gemini_session.is_connected:
                try:
                    await self._gemini_session.send_audio(frame)
                except Exception as exc:
                    log.debug("Gemini audio consumer error: %s", exc)
```

Also add `import numpy as np` at the top of the file if not already present (but prefer the lazy import inside the method to avoid import-time dependency on numpy for tests).

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_audio_loop.py -v`
Expected: All 10 tests PASS

**Step 5: Commit**

```bash
cd ~/projects/ai-agents
git add agents/hapax_voice/__main__.py tests/hapax_voice/test_audio_loop.py
git commit -m "feat(voice): add audio distribution loop — frames to wake word, VAD, Gemini"
```

---

## Task 3: Config Addition

**Files:**
- Modify: `agents/hapax_voice/config.py`
- Test: `tests/hapax_voice/test_config_audio.py`

**Context:** The `VoiceConfig` Pydantic model needs a new field `audio_input_source` so the PipeWire source name is configurable. Default: `"echo_cancel_capture"`.

**Step 1: Write the failing test**

Create `tests/hapax_voice/test_config_audio.py`:

```python
"""Tests for audio_input_source config field."""
from agents.hapax_voice.config import VoiceConfig


def test_default_audio_input_source():
    """Default audio_input_source is echo_cancel_capture."""
    cfg = VoiceConfig()
    assert cfg.audio_input_source == "echo_cancel_capture"


def test_custom_audio_input_source():
    """audio_input_source can be overridden."""
    cfg = VoiceConfig(audio_input_source="my_custom_mic")
    assert cfg.audio_input_source == "my_custom_mic"
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_config_audio.py -v`
Expected: FAIL with `ValidationError` (field not in model)

**Step 3: Add the field to VoiceConfig**

In `agents/hapax_voice/config.py`, add to the `VoiceConfig` class fields:

```python
    audio_input_source: str = "echo_cancel_capture"
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_config_audio.py -v`
Expected: All 2 tests PASS

**Step 5: Commit**

```bash
cd ~/projects/ai-agents
git add agents/hapax_voice/config.py tests/hapax_voice/test_config_audio.py
git commit -m "feat(voice): add audio_input_source config field"
```

---

## Task 4: Daemon Wiring — Init and Lifecycle

**Files:**
- Modify: `agents/hapax_voice/__main__.py`
- Test: `tests/hapax_voice/test_daemon_audio_wiring.py`

**Context:** Wire `AudioInputStream` into `VoiceDaemon.__init__()`, start it in `run()`, add `_audio_loop()` as a background task, and stop it in the `finally` block. If PyAudio can't open the stream, the daemon continues in visual-only mode.

**Step 1: Write the failing tests**

Create `tests/hapax_voice/test_daemon_audio_wiring.py`:

```python
"""Tests for audio input wiring in VoiceDaemon lifecycle."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestDaemonAudioInit:
    """AudioInputStream is created in __init__ with config source name."""

    def test_audio_input_created(self):
        """VoiceDaemon creates AudioInputStream with configured source."""
        with patch("agents.hapax_voice.__main__.AudioInputStream") as MockAIS:
            mock_cfg = MagicMock()
            mock_cfg.audio_input_source = "test_source"
            mock_cfg.silence_timeout_s = 30
            mock_cfg.presence_window_minutes = 5
            mock_cfg.presence_vad_threshold = 0.4
            mock_cfg.backend = "local"
            mock_cfg.llm_model = "claude-sonnet"
            mock_cfg.gemini_model = "gemini-flash"
            mock_cfg.local_stt_model = "model"
            mock_cfg.kokoro_voice = "af_heart"
            mock_cfg.workspace_monitor_enabled = False
            mock_cfg.workspace_poll_interval_s = 2.0
            mock_cfg.workspace_capture_cooldown_s = 10.0
            mock_cfg.proactive_min_confidence = 0.8
            mock_cfg.proactive_cooldown_s = 300.0
            mock_cfg.recapture_idle_s = 60.0
            mock_cfg.analyzer_model = "gemini-flash"
            mock_cfg.cameras = []
            mock_cfg.webcam_cooldown_s = 30.0
            mock_cfg.face_interval_s = 8.0
            mock_cfg.face_min_confidence = 0.3
            mock_cfg.hotkey_socket = "/tmp/hapax-voice.sock"
            mock_cfg.event_log_enabled = True
            mock_cfg.event_log_dir = "/tmp/test-events"
            mock_cfg.event_log_retention_days = 14
            mock_cfg.ntfy_topic = ""
            mock_cfg.ambient_classification = False

            with patch("agents.hapax_voice.__main__.load_config", return_value=mock_cfg):
                with patch("agents.hapax_voice.__main__.WakeWordDetector"):
                    with patch("agents.hapax_voice.__main__.TTSManager"):
                        with patch("agents.hapax_voice.__main__.WorkspaceMonitor"):
                            with patch("agents.hapax_voice.__main__.HotkeyServer"):
                                from agents.hapax_voice.__main__ import VoiceDaemon
                                daemon = VoiceDaemon()

            MockAIS.assert_called_once_with(source_name="test_source")


class TestDaemonAudioLifecycle:
    """Audio stream starts/stops with daemon lifecycle."""

    @pytest.mark.asyncio
    async def test_audio_started_event_emitted(self):
        """audio_input_started event emitted when stream opens successfully."""
        from agents.hapax_voice.__main__ import VoiceDaemon

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()
            daemon._running = False  # Exit main loop immediately
            daemon._background_tasks = []
            daemon._pipeline_task = None
            daemon.event_log = MagicMock()
            daemon.tracer = MagicMock()
            daemon.hotkey = AsyncMock()
            daemon.wake_word = MagicMock()
            daemon.session = MagicMock()
            daemon.session.is_active = False
            daemon.notifications = MagicMock()
            daemon.workspace_monitor = MagicMock()
            daemon.workspace_monitor.run = AsyncMock()
            daemon.workspace_monitor.latest_analysis = None
            daemon.gate = MagicMock()
            daemon.presence = MagicMock()
            daemon.cfg = MagicMock()
            daemon.cfg.ntfy_topic = ""
            daemon.tts = MagicMock()

            mock_audio = MagicMock()
            mock_audio.is_active = True  # Stream opened successfully
            daemon._audio_input = mock_audio

            await daemon.run()

            mock_audio.start.assert_called_once()
            daemon.event_log.emit.assert_any_call("audio_input_started")

    @pytest.mark.asyncio
    async def test_audio_failed_event_on_stream_failure(self):
        """audio_input_failed event emitted when stream cannot open."""
        from agents.hapax_voice.__main__ import VoiceDaemon

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()
            daemon._running = False
            daemon._background_tasks = []
            daemon._pipeline_task = None
            daemon.event_log = MagicMock()
            daemon.tracer = MagicMock()
            daemon.hotkey = AsyncMock()
            daemon.wake_word = MagicMock()
            daemon.session = MagicMock()
            daemon.session.is_active = False
            daemon.notifications = MagicMock()
            daemon.workspace_monitor = MagicMock()
            daemon.workspace_monitor.run = AsyncMock()
            daemon.workspace_monitor.latest_analysis = None
            daemon.gate = MagicMock()
            daemon.presence = MagicMock()
            daemon.cfg = MagicMock()
            daemon.cfg.ntfy_topic = ""
            daemon.tts = MagicMock()

            mock_audio = MagicMock()
            mock_audio.is_active = False  # Stream failed to open
            daemon._audio_input = mock_audio

            await daemon.run()

            mock_audio.start.assert_called_once()
            daemon.event_log.emit.assert_any_call(
                "audio_input_failed",
                error="Stream not active after start",
            )

    @pytest.mark.asyncio
    async def test_audio_stopped_on_shutdown(self):
        """audio_input.stop() called in finally block."""
        from agents.hapax_voice.__main__ import VoiceDaemon

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()
            daemon._running = False
            daemon._background_tasks = []
            daemon._pipeline_task = None
            daemon.event_log = MagicMock()
            daemon.tracer = MagicMock()
            daemon.hotkey = AsyncMock()
            daemon.wake_word = MagicMock()
            daemon.session = MagicMock()
            daemon.session.is_active = False
            daemon.notifications = MagicMock()
            daemon.workspace_monitor = MagicMock()
            daemon.workspace_monitor.run = AsyncMock()
            daemon.workspace_monitor.latest_analysis = None
            daemon.gate = MagicMock()
            daemon.presence = MagicMock()
            daemon.cfg = MagicMock()
            daemon.cfg.ntfy_topic = ""
            daemon.tts = MagicMock()

            mock_audio = MagicMock()
            mock_audio.is_active = True
            daemon._audio_input = mock_audio

            await daemon.run()

            mock_audio.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_audio_loop_added_as_background_task(self):
        """_audio_loop() is added to background tasks when stream is active."""
        from agents.hapax_voice.__main__ import VoiceDaemon

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()
            daemon._running = False
            daemon._background_tasks = []
            daemon._pipeline_task = None
            daemon.event_log = MagicMock()
            daemon.tracer = MagicMock()
            daemon.hotkey = AsyncMock()
            daemon.wake_word = MagicMock()
            daemon.session = MagicMock()
            daemon.session.is_active = False
            daemon.notifications = MagicMock()
            daemon.workspace_monitor = MagicMock()
            daemon.workspace_monitor.run = AsyncMock()
            daemon.workspace_monitor.latest_analysis = None
            daemon.gate = MagicMock()
            daemon.presence = MagicMock()
            daemon.cfg = MagicMock()
            daemon.cfg.ntfy_topic = ""
            daemon.tts = MagicMock()

            mock_audio = MagicMock()
            mock_audio.is_active = True
            daemon._audio_input = mock_audio
            daemon._audio_loop = AsyncMock()

            await daemon.run()

            # Verify _audio_loop was scheduled as a background task
            # The background tasks list should contain a task for _audio_loop
            task_names = [str(t) for t in daemon._background_tasks]
            # Since we mocked _audio_loop, check it was called via create_task
            assert any("_audio_loop" in str(t) for t in daemon._background_tasks)
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_daemon_audio_wiring.py -v`
Expected: FAIL — `AudioInputStream` not imported, not created in `__init__`, not wired in `run()`

**Step 3: Wire AudioInputStream into VoiceDaemon**

In `agents/hapax_voice/__main__.py`:

1. **Add import at top:**
```python
from agents.hapax_voice.audio_input import AudioInputStream
```

2. **Add to `__init__()`, after `self.wake_word = WakeWordDetector()` line:**
```python
        self._audio_input = AudioInputStream(source_name=self.cfg.audio_input_source)
```

3. **In `run()`, after `self.wake_word.load()` and before the background tasks block, add:**
```python
        # Start audio input
        self._audio_input.start()
        if self._audio_input.is_active:
            self.event_log.emit("audio_input_started")
        else:
            self.event_log.emit("audio_input_failed", error="Stream not active after start")
```

4. **In `run()`, in the background tasks block, add (only if audio is active):**
```python
        if self._audio_input.is_active:
            self._background_tasks.append(asyncio.create_task(self._audio_loop()))
```

5. **In `run()`, in the `finally` block, before `self.event_log.close()`, add:**
```python
            self._audio_input.stop()
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_daemon_audio_wiring.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
cd ~/projects/ai-agents
git add agents/hapax_voice/__main__.py tests/hapax_voice/test_daemon_audio_wiring.py
git commit -m "feat(voice): wire AudioInputStream into daemon lifecycle"
```

---

## Task 5: Stream Recovery

**Files:**
- Modify: `agents/hapax_voice/__main__.py` (the `_audio_loop` method)
- Modify: `tests/hapax_voice/test_audio_loop.py`

**Context:** If `AudioInputStream` dies (stream error), the audio loop should log a warning and attempt to reopen after a 5-second delay, rather than crashing the loop entirely.

**Step 1: Write the failing test**

Add to `tests/hapax_voice/test_audio_loop.py`:

```python
class TestAudioLoopRecovery:
    """Audio loop recovers from stream death."""

    @pytest.mark.asyncio
    async def test_reopens_after_stream_death(self):
        """If get_frame raises OSError, loop waits 5s and retries."""
        from agents.hapax_voice.__main__ import VoiceDaemon

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()
            daemon._running = True
            daemon.wake_word = MagicMock()
            daemon.presence = MagicMock()
            daemon._gemini_session = None
            daemon.event_log = MagicMock()

            mock_audio = MagicMock()
            call_count = 0

            async def get_frame_side_effect(timeout=1.0):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise OSError("Stream died")
                if call_count == 2:
                    return b"\x00" * 960
                daemon._running = False
                return None

            mock_audio.get_frame = get_frame_side_effect
            mock_audio.is_active = True
            daemon._audio_input = mock_audio

            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await daemon._audio_loop()

            # Verify recovery sleep was called with 5.0
            mock_sleep.assert_any_call(5.0)
            # Verify stream was restarted
            mock_audio.stop.assert_called()
            mock_audio.start.assert_called()
```

**Step 2: Run tests to verify it fails**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_audio_loop.py::TestAudioLoopRecovery -v`
Expected: FAIL — `_audio_loop` doesn't handle OSError from `get_frame`

**Step 3: Update _audio_loop with recovery**

Replace the `_audio_loop` method in `agents/hapax_voice/__main__.py`:

```python
    async def _audio_loop(self) -> None:
        """Distribute audio frames to wake word, VAD, and Gemini consumers."""
        import numpy as np

        while self._running:
            try:
                frame = await self._audio_input.get_frame(timeout=1.0)
            except Exception as exc:
                log.warning("Audio stream error: %s — attempting recovery", exc)
                self._audio_input.stop()
                await asyncio.sleep(5.0)
                self._audio_input.start()
                continue

            if frame is None:
                continue

            # Wake word detector: expects numpy int16 array
            try:
                audio_np = np.frombuffer(frame, dtype=np.int16)
                self.wake_word.process_audio(audio_np)
            except Exception as exc:
                log.debug("Wake word consumer error: %s", exc)

            # Presence detector: expects raw PCM bytes
            try:
                self.presence.process_audio_frame(frame)
            except Exception as exc:
                log.debug("Presence consumer error: %s", exc)

            # Gemini Live: expects raw PCM bytes, only when connected
            if self._gemini_session is not None and self._gemini_session.is_connected:
                try:
                    await self._gemini_session.send_audio(frame)
                except Exception as exc:
                    log.debug("Gemini audio consumer error: %s", exc)
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_audio_loop.py -v`
Expected: All 11 tests PASS

**Step 5: Commit**

```bash
cd ~/projects/ai-agents
git add agents/hapax_voice/__main__.py tests/hapax_voice/test_audio_loop.py
git commit -m "feat(voice): add stream recovery to audio distribution loop"
```

---

## Task 6: Hardware Integration Tests

**Files:**
- Create: `tests/hapax_voice/test_audio_hardware.py`

**Context:** These tests run against real hardware (PyAudio + PipeWire). They are marked with `@pytest.mark.hardware` and skipped automatically by the conftest when hardware isn't available.

**Step 1: Write the tests**

Create `tests/hapax_voice/test_audio_hardware.py`:

```python
"""Hardware integration tests for AudioInputStream.

Run with: pytest tests/hapax_voice/test_audio_hardware.py -v -m hardware
Requires: PipeWire running, echo_cancel_capture source available.
"""
from __future__ import annotations

import asyncio

import pytest

from agents.hapax_voice.audio_input import AudioInputStream


@pytest.mark.hardware
class TestRealAudioStream:
    """Tests against real PipeWire audio hardware."""

    def test_opens_echo_cancel_source(self):
        """Real PyAudio stream opens on echo_cancel_capture."""
        stream = AudioInputStream(source_name="echo_cancel_capture")
        try:
            stream.start()
            assert stream.is_active
            assert stream._device_index is not None
        finally:
            stream.stop()

    @pytest.mark.asyncio
    async def test_frames_are_correct_size(self):
        """Frames from real stream are 960 bytes (30ms @ 16kHz int16)."""
        stream = AudioInputStream(source_name="echo_cancel_capture")
        try:
            stream.start()
            assert stream.is_active
            frame = await stream.get_frame(timeout=2.0)
            assert frame is not None
            assert len(frame) == 960
        finally:
            stream.stop()

    @pytest.mark.asyncio
    async def test_stream_survives_five_seconds(self):
        """Stream produces frames continuously for 5 seconds without crash."""
        stream = AudioInputStream(source_name="echo_cancel_capture")
        try:
            stream.start()
            assert stream.is_active
            frame_count = 0
            end_time = asyncio.get_event_loop().time() + 5.0
            while asyncio.get_event_loop().time() < end_time:
                frame = await stream.get_frame(timeout=0.1)
                if frame is not None:
                    frame_count += 1
            # At 33 frames/sec for 5 seconds, expect ~165 frames
            assert frame_count > 100, f"Only got {frame_count} frames in 5s"
            assert stream.is_active
        finally:
            stream.stop()

    @pytest.mark.asyncio
    async def test_frames_are_non_zero(self):
        """At least some frames contain non-zero audio data."""
        stream = AudioInputStream(source_name="echo_cancel_capture")
        try:
            stream.start()
            assert stream.is_active
            non_zero = 0
            for _ in range(50):
                frame = await stream.get_frame(timeout=0.5)
                if frame is not None and any(b != 0 for b in frame):
                    non_zero += 1
            # Even in silence, dither/noise should produce some non-zero frames
            assert non_zero > 0, "All 50 frames were pure zeros"
        finally:
            stream.stop()

    def test_default_device_fallback(self):
        """Falls back to default device when bogus source name given."""
        stream = AudioInputStream(source_name="nonexistent_device_xyz")
        try:
            stream.start()
            # May or may not be active depending on whether a default device exists
            # The important thing is it doesn't crash
        finally:
            stream.stop()
```

**Step 2: Run tests (hardware-specific)**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_audio_hardware.py -v -m hardware`
Expected: PASS if PipeWire is running with echo_cancel_capture; SKIP otherwise (conftest auto-skip)

**Step 3: Commit**

```bash
cd ~/projects/ai-agents
git add tests/hapax_voice/test_audio_hardware.py
git commit -m "test(voice): add hardware integration tests for audio input stream"
```

---

## Task 7: Full Integration Smoke Test

**Files:**
- Modify: `tests/hapax_voice/test_cross_component_integration.py`

**Context:** Add an integration test that verifies the full audio pipeline mock: `AudioInputStream` → `_audio_loop` → wake word fires → session opens → event emitted. This is a cross-component test with everything mocked except the control flow.

**Step 1: Write the test**

Add to `tests/hapax_voice/test_cross_component_integration.py`:

```python
class TestAudioPipelineIntegration:
    """End-to-end audio pipeline: input → distribution → wake word → session."""

    @pytest.mark.asyncio
    async def test_audio_to_wake_word_to_session(self):
        """Audio frame triggers wake word which opens a session."""
        from agents.hapax_voice.__main__ import VoiceDaemon

        with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
            daemon = VoiceDaemon()
            daemon._running = True
            daemon.event_log = MagicMock()
            daemon.presence = MagicMock()
            daemon._gemini_session = None
            daemon.session = MagicMock()
            daemon.session.is_active = False
            daemon.session.session_id = "test123"

            # Wake word detector that triggers on any audio
            wake_word = MagicMock()
            wake_word_callback = None

            def capture_callback(cb):
                nonlocal wake_word_callback
                wake_word_callback = cb

            type(wake_word).on_wake_word = PropertyMock(fset=capture_callback)
            daemon.wake_word = wake_word

            # Re-set the callback to our test function
            session_opened = False

            def on_wake():
                nonlocal session_opened
                session_opened = True
                daemon.session.open(trigger="wake_word")
                daemon._running = False

            # Simulate wake word triggering on process_audio
            def process_with_trigger(audio):
                if on_wake:
                    on_wake()

            daemon.wake_word.process_audio = process_with_trigger

            # Audio input returns one frame then stops
            audio_input = AsyncMock()
            call_count = 0

            async def get_frame_side_effect(timeout=1.0):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return b"\x00\x01" * 480
                return None

            audio_input.get_frame = get_frame_side_effect
            daemon._audio_input = audio_input

            await daemon._audio_loop()

            assert session_opened
            daemon.session.open.assert_called_once_with(trigger="wake_word")
```

**Step 2: Run tests to verify they pass**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_cross_component_integration.py::TestAudioPipelineIntegration -v`
Expected: PASS (uses the _audio_loop implemented in Task 2)

**Step 3: Commit**

```bash
cd ~/projects/ai-agents
git add tests/hapax_voice/test_cross_component_integration.py
git commit -m "test(voice): add audio pipeline integration test — input to wake word to session"
```

---

## Task 8: Run Full Test Suite and Verify

**Files:** None (verification only)

**Step 1: Run all hapax_voice tests (excluding hardware)**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/ -v --ignore=tests/hapax_voice/test_audio_hardware.py -x`
Expected: All tests PASS (existing 247 tests + new tests from Tasks 1-7)

**Step 2: Run hardware tests separately (if hardware available)**

Run: `cd ~/projects/ai-agents && uv run pytest tests/hapax_voice/test_audio_hardware.py -v -m hardware`
Expected: PASS or SKIP

**Step 3: Verify daemon starts with audio input**

Run: `cd ~/projects/ai-agents && timeout 10 .venv/bin/python -m agents.hapax_voice 2>&1 | head -30`
Expected: Should see `Audio input stream started` or `Failed to open audio input stream` in output — either is valid, the important thing is it doesn't crash.

---

Plan complete and saved to `docs/plans/2026-03-09-voice-audio-input.md`. Two execution options:

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

Which approach?