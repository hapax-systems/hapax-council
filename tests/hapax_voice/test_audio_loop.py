"""Tests for VoiceDaemon._audio_loop() — audio frame distribution.

Audio frames are 480 samples (30ms at 16kHz = 960 bytes).  Consumers need
exact chunk sizes:
- Wake word (Porcupine): exactly 512 samples = 1024 bytes
- Wake word (OWW): exactly 1280 samples = 2560 bytes
- Presence/VAD (Silero v5): exactly 512 samples = 1024 bytes
- Gemini Live: any size (each 30ms frame forwarded immediately)

Wake word runs on ALL audio (no VAD gating). VAD feeds presence detection only.
"""
from __future__ import annotations

import struct
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from agents.hapax_voice.__main__ import VoiceDaemon

_FRAME_SAMPLES = 480      # 30ms at 16kHz
_FRAME_BYTES = _FRAME_SAMPLES * 2  # 960 bytes
_WAKE_SAMPLES = 1280
_WAKE_BYTES = _WAKE_SAMPLES * 2    # 2560 bytes
_VAD_SAMPLES = 512
_VAD_BYTES = _VAD_SAMPLES * 2      # 1024 bytes

_FRAMES_FOR_WAKE = 3  # 3 × 480 = 1440 ≥ 1280 → 1 wake call
_FRAMES_FOR_VAD = 3   # 3 × 480 = 1440 ≥ 1024 → 1 VAD call


def _make_daemon() -> VoiceDaemon:
    """Create a VoiceDaemon with __init__ bypassed."""
    daemon = object.__new__(VoiceDaemon)
    daemon._running = True
    daemon.wake_word = MagicMock()
    daemon.wake_word.frame_length = _WAKE_SAMPLES
    daemon.presence = MagicMock()
    daemon.presence.process_audio_frame.return_value = 0.5
    daemon._gemini_session = None
    return daemon


def _make_frame(n_samples: int = _FRAME_SAMPLES) -> bytes:
    """Create a fake PCM frame (int16 samples)."""
    return struct.pack(f"<{n_samples}h", *([100] * n_samples))


def _make_flush_frames(n: int = _FRAMES_FOR_WAKE) -> list[bytes]:
    """Create enough frames to trigger at least one consumer flush."""
    return [_make_frame() for _ in range(n)]


def _wire_audio_input(daemon: VoiceDaemon, frames: list[bytes | None]) -> None:
    """Wire a mock _audio_input that yields frames then stops the loop."""
    audio_input = AsyncMock()
    call_count = 0

    async def get_frame_side_effect(timeout=1.0):
        nonlocal call_count
        call_count += 1
        if call_count <= len(frames):
            return frames[call_count - 1]
        daemon._running = False
        return None

    audio_input.get_frame = get_frame_side_effect
    daemon._audio_input = audio_input


# --- Distribution ---


class TestAudioLoopDistribution:
    """Frames are distributed to wake word, presence, and Gemini consumers."""

    @pytest.mark.asyncio
    async def test_wake_word_gets_exact_1280_samples(self):
        """Wake word receives exactly 1280-sample numpy array."""
        daemon = _make_daemon()
        frames = _make_flush_frames(3)  # 1440 samples total
        _wire_audio_input(daemon, frames)

        await daemon._audio_loop()

        daemon.wake_word.process_audio.assert_called_once()
        arr = daemon.wake_word.process_audio.call_args[0][0]
        assert arr.shape == (_WAKE_SAMPLES,)
        assert arr.dtype == np.int16

    @pytest.mark.asyncio
    async def test_vad_gets_exact_512_samples(self):
        """VAD receives exactly 512-sample chunks. 3 frames (1440) → 2 VAD calls."""
        daemon = _make_daemon()
        frames = _make_flush_frames(3)  # 1440 samples → 2 VAD chunks (2×512) + 416 left
        _wire_audio_input(daemon, frames)

        await daemon._audio_loop()

        assert daemon.presence.process_audio_frame.call_count == 2
        for call in daemon.presence.process_audio_frame.call_args_list:
            chunk = call[0][0]
            assert len(chunk) == _VAD_BYTES

    @pytest.mark.asyncio
    async def test_frame_sent_to_gemini_when_connected(self):
        """Each individual frame sent to Gemini immediately (no accumulation)."""
        daemon = _make_daemon()
        frame = _make_frame()
        _wire_audio_input(daemon, [frame])

        gemini = AsyncMock()
        gemini.is_connected = True
        daemon._gemini_session = gemini

        await daemon._audio_loop()

        gemini.send_audio.assert_awaited_once_with(frame)

    @pytest.mark.asyncio
    async def test_frame_not_sent_to_gemini_when_disconnected(self):
        """Frame NOT sent when is_connected=False."""
        daemon = _make_daemon()
        frame = _make_frame()
        _wire_audio_input(daemon, [frame])

        gemini = AsyncMock()
        gemini.is_connected = False
        daemon._gemini_session = gemini

        await daemon._audio_loop()

        gemini.send_audio.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_gemini_session_attribute(self):
        """Works when _gemini_session is None; wake_word/presence called after flush."""
        daemon = _make_daemon()
        frames = _make_flush_frames(3)
        _wire_audio_input(daemon, frames)
        daemon._gemini_session = None

        await daemon._audio_loop()

        daemon.wake_word.process_audio.assert_called_once()
        assert daemon.presence.process_audio_frame.call_count == 2  # 1440/512 = 2

    @pytest.mark.asyncio
    async def test_no_consumer_call_below_threshold(self):
        """Single 480-sample frame does NOT trigger wake word or presence."""
        daemon = _make_daemon()
        _wire_audio_input(daemon, [_make_frame()])

        await daemon._audio_loop()

        daemon.wake_word.process_audio.assert_not_called()
        daemon.presence.process_audio_frame.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_wake_chunks_from_many_frames(self):
        """6 frames (2880 samples) → 2 wake calls (2×1280) + 320 leftover."""
        daemon = _make_daemon()
        frames = _make_flush_frames(6)
        _wire_audio_input(daemon, frames)

        await daemon._audio_loop()

        assert daemon.wake_word.process_audio.call_count == 2
        for call in daemon.wake_word.process_audio.call_args_list:
            arr = call[0][0]
            assert arr.shape == (_WAKE_SAMPLES,)

    @pytest.mark.asyncio
    async def test_multiple_vad_chunks_from_many_frames(self):
        """6 frames (2880 samples) → 5 VAD calls (5×512=2560) + 320 leftover."""
        daemon = _make_daemon()
        frames = _make_flush_frames(6)  # 2880 samples
        _wire_audio_input(daemon, frames)

        await daemon._audio_loop()

        # 2880 / 512 = 5 full chunks + 160 leftover
        assert daemon.presence.process_audio_frame.call_count == 5

    @pytest.mark.asyncio
    async def test_wake_word_runs_regardless_of_vad_result(self):
        """Wake word processes ALL audio even when VAD reports silence."""
        daemon = _make_daemon()
        daemon.presence.process_audio_frame.return_value = 0.0  # "silence"
        frames = _make_flush_frames(3)
        _wire_audio_input(daemon, frames)

        await daemon._audio_loop()

        # Wake word still called — no VAD gating
        daemon.wake_word.process_audio.assert_called_once()
        # VAD still runs for presence detection
        assert daemon.presence.process_audio_frame.call_count == 2


# --- Error handling ---


class TestAudioLoopErrorHandling:
    """One consumer failing must not kill the loop or other consumers."""

    @pytest.mark.asyncio
    async def test_continues_after_wake_word_exception(self):
        """Presence still gets frames after wake_word.process_audio raises."""
        daemon = _make_daemon()
        frames = _make_flush_frames(6)  # enough for multiple flushes
        _wire_audio_input(daemon, frames)

        daemon.wake_word.process_audio.side_effect = RuntimeError("boom")

        await daemon._audio_loop()

        assert daemon.presence.process_audio_frame.call_count > 0

    @pytest.mark.asyncio
    async def test_continues_after_presence_exception(self):
        """Wake word still processes audio after presence raises."""
        daemon = _make_daemon()
        frames = _make_flush_frames(6)
        _wire_audio_input(daemon, frames)

        daemon.presence.process_audio_frame.side_effect = RuntimeError("boom")

        await daemon._audio_loop()

        # Presence was attempted (and raised)
        assert daemon.presence.process_audio_frame.call_count > 0
        # Wake word still runs (independent of VAD)
        assert daemon.wake_word.process_audio.call_count > 0

    @pytest.mark.asyncio
    async def test_continues_after_gemini_exception(self):
        """Other consumers still get frames after gemini send_audio raises."""
        daemon = _make_daemon()
        frames = _make_flush_frames(6)
        _wire_audio_input(daemon, frames)

        gemini = AsyncMock()
        gemini.is_connected = True
        gemini.send_audio.side_effect = RuntimeError("network error")
        daemon._gemini_session = gemini

        await daemon._audio_loop()

        assert daemon.wake_word.process_audio.call_count > 0
        assert daemon.presence.process_audio_frame.call_count > 0

    @pytest.mark.asyncio
    async def test_skips_none_frames(self):
        """get_frame() returning None doesn't contribute to accumulation."""
        daemon = _make_daemon()
        frames = [None] + _make_flush_frames(3)
        _wire_audio_input(daemon, frames)

        await daemon._audio_loop()

        daemon.wake_word.process_audio.assert_called_once()
        assert daemon.presence.process_audio_frame.call_count == 2  # 1440/512 = 2

    @pytest.mark.asyncio
    async def test_exits_when_not_running(self):
        """Loop exits immediately when _running is False."""
        daemon = _make_daemon()
        daemon._running = False
        daemon._audio_input = AsyncMock()

        await daemon._audio_loop()

        daemon._audio_input.get_frame.assert_not_called()


# --- Stream recovery ---


class TestAudioLoopRecovery:
    """Audio loop recovers from stream death."""

    @pytest.mark.asyncio
    async def test_reopens_after_stream_death(self):
        """If get_frame raises OSError, loop waits 5s and retries."""
        daemon = _make_daemon()
        daemon.event_log = MagicMock()

        mock_audio = MagicMock()
        call_count = 0

        recovery_frames = _make_flush_frames(3)

        async def get_frame_side_effect(timeout=1.0):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("Stream died")
            frame_idx = call_count - 2
            if frame_idx < len(recovery_frames):
                return recovery_frames[frame_idx]
            daemon._running = False
            return None

        mock_audio.get_frame = get_frame_side_effect
        mock_audio.is_active = True
        daemon._audio_input = mock_audio

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await daemon._audio_loop()

        mock_audio.stop.assert_called()
        mock_sleep.assert_any_call(5.0)
        mock_audio.start.assert_called()
        daemon.wake_word.process_audio.assert_called_once()
