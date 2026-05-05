"""Tests for VoiceDaemon._audio_loop() — audio frame distribution.

Audio frames are 480 samples (30ms at 16kHz = 960 bytes).  Consumers need
exact chunk sizes:
- Presence/VAD (Silero v5): exactly 512 samples = 1024 bytes
- Gemini Live: any size (each 30ms frame forwarded immediately)

Engagement classifier runs on VAD confidence after presence processing.
"""

from __future__ import annotations

import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_daimonion.__main__ import VoiceDaemon

_FRAME_SAMPLES = 480  # 30ms at 16kHz
_FRAME_BYTES = _FRAME_SAMPLES * 2  # 960 bytes
_VAD_SAMPLES = 512
_VAD_BYTES = _VAD_SAMPLES * 2  # 1024 bytes

_FRAMES_FOR_VAD = 3  # 3 × 480 = 1440 ≥ 1024 → 1 VAD call


def _make_daemon() -> VoiceDaemon:
    """Create a VoiceDaemon with __init__ bypassed."""
    daemon = object.__new__(VoiceDaemon)
    daemon._running = True
    daemon._engagement = MagicMock()
    daemon._engagement._debounce_s = 2.0
    daemon.session = MagicMock()
    daemon.session.is_active = False
    daemon.perception = MagicMock()
    daemon.perception.behaviors = {}
    daemon.presence = MagicMock()
    daemon.presence.process_audio_frame.return_value = 0.5
    daemon.presence._latest_vad_confidence = 0.5
    daemon._gemini_session = None
    daemon._echo_canceller = None
    daemon._noise_reference = None
    daemon._audio_preprocessor = None
    daemon._conversation_buffer = MagicMock()
    daemon._conversation_buffer.is_active = False
    return daemon


def _make_frame(n_samples: int = _FRAME_SAMPLES) -> bytes:
    """Create a fake PCM frame (int16 samples)."""
    return struct.pack(f"<{n_samples}h", *([100] * n_samples))


def _make_flush_frames(n: int = _FRAMES_FOR_VAD) -> list[bytes]:
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
    """Frames are distributed to presence/VAD and Gemini consumers."""

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
        """Works when _gemini_session is None; presence called after flush."""
        daemon = _make_daemon()
        frames = _make_flush_frames(3)
        _wire_audio_input(daemon, frames)
        daemon._gemini_session = None

        await daemon._audio_loop()

        assert daemon.presence.process_audio_frame.call_count == 2  # 1440/512 = 2

    @pytest.mark.asyncio
    async def test_no_consumer_call_below_threshold(self):
        """Single 480-sample frame does NOT trigger presence."""
        daemon = _make_daemon()
        _wire_audio_input(daemon, [_make_frame()])

        await daemon._audio_loop()

        daemon.presence.process_audio_frame.assert_not_called()

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
    async def test_buffer_always_receives_audio_vad_and_engagement_signal(self):
        """Buffer receives audio/VAD before non-gating engagement modulation.

        Impingement-native architecture: every operator utterance flows
        through the buffer to STT → salience router. Engagement can still
        boost gain after VAD/presence evidence, but it never gates capture.
        """
        daemon = _make_daemon()
        daemon.presence._latest_vad_confidence = 0.5
        ps_behavior = MagicMock()
        ps_behavior.value = "PRESENT"
        daemon.perception.behaviors = {"presence_state": ps_behavior}
        frames = _make_flush_frames(3)
        _wire_audio_input(daemon, frames)

        await daemon._audio_loop()

        # Buffer always receives feed_audio (once per frame)
        assert daemon._conversation_buffer.feed_audio.call_count == 3
        # Buffer always receives update_vad (once per VAD chunk)
        assert daemon._conversation_buffer.update_vad.call_count == 2
        daemon._engagement.on_speech_detected.assert_called()

    @pytest.mark.asyncio
    async def test_operator_vad_publishes_voice_pitch_sample(self):
        """Operator VAD chunks publish numeric voice-pitch calibration samples."""
        daemon = _make_daemon()
        daemon.presence._latest_vad_confidence = 0.5
        daemon.session.is_active = False
        frames = _make_flush_frames(3)
        _wire_audio_input(daemon, frames)

        with patch(
            "agents.hapax_daimonion.run_loops.publish_operator_voice_pitch_sample"
        ) as publish:
            await daemon._audio_loop()

        publish.assert_called()
        assert publish.call_args.kwargs["sample_rate_hz"] == 16000

    @pytest.mark.asyncio
    async def test_guest_vad_does_not_publish_voice_pitch_sample(self):
        """Active non-operator session speech must not train operator pitch."""
        daemon = _make_daemon()
        daemon.presence._latest_vad_confidence = 0.5
        daemon.session.is_active = True
        daemon.session.speaker = "guest"
        frames = _make_flush_frames(3)
        _wire_audio_input(daemon, frames)

        with patch(
            "agents.hapax_daimonion.run_loops.publish_operator_voice_pitch_sample"
        ) as publish:
            await daemon._audio_loop()

        publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_consent_guest_phase_does_not_publish_voice_pitch_sample(self):
        """Guest-present consent posture suppresses operator pitch learning."""
        daemon = _make_daemon()
        daemon.presence._latest_vad_confidence = 0.5
        daemon.session.is_active = False
        daemon.consent_tracker = SimpleNamespace(phase=SimpleNamespace(value="guest_detected"))
        frames = _make_flush_frames(3)
        _wire_audio_input(daemon, frames)

        with patch(
            "agents.hapax_daimonion.run_loops.publish_operator_voice_pitch_sample"
        ) as publish:
            await daemon._audio_loop()

        publish.assert_not_called()


# --- Error handling ---


class TestAudioLoopErrorHandling:
    """One consumer failing must not kill the loop or other consumers."""

    @pytest.mark.asyncio
    async def test_continues_after_presence_exception(self):
        """Loop continues after presence raises."""
        daemon = _make_daemon()
        frames = _make_flush_frames(6)
        _wire_audio_input(daemon, frames)

        daemon.presence.process_audio_frame.side_effect = RuntimeError("boom")

        await daemon._audio_loop()

        # Presence was attempted (and raised)
        assert daemon.presence.process_audio_frame.call_count > 0

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

        assert daemon.presence.process_audio_frame.call_count > 0

    @pytest.mark.asyncio
    async def test_skips_none_frames(self):
        """get_frame() returning None doesn't contribute to accumulation."""
        daemon = _make_daemon()
        frames = [None] + _make_flush_frames(3)
        _wire_audio_input(daemon, frames)

        await daemon._audio_loop()

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
