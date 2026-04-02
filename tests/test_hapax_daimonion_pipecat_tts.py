"""Tests for the custom Pipecat TTS service wrapping TTSManager."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

try:
    from pipecat.frames.frames import TTSAudioRawFrame, TTSStartedFrame, TTSStoppedFrame

    from agents.hapax_daimonion.pipecat_tts import KokoroTTSService
    from agents.hapax_daimonion.tts import TTS_SAMPLE_RATE
except (TypeError, ImportError) as _err:
    pytest.skip(f"pipecat import failed: {_err}", allow_module_level=True)


@pytest.fixture
def mock_tts_manager() -> MagicMock:
    mgr = MagicMock()
    mgr.synthesize.return_value = b"\x00\x01" * 100  # 200 bytes
    return mgr


class TestKokoroTTSServiceInit:
    def test_default_sample_rate(self) -> None:
        with patch("agents.hapax_daimonion.pipecat_tts.TTSManager"):
            svc = KokoroTTSService()
        assert svc._init_sample_rate == TTS_SAMPLE_RATE

    def test_custom_voice(self) -> None:
        mgr = MagicMock()
        svc = KokoroTTSService(voice_id="bf_emma", tts_manager=mgr)
        assert svc._tts_manager is mgr

    def test_uses_provided_tts_manager(self, mock_tts_manager: MagicMock) -> None:
        svc = KokoroTTSService(tts_manager=mock_tts_manager)
        assert svc._tts_manager is mock_tts_manager


class TestKokoroTTSServiceRunTTS:
    @pytest.mark.asyncio
    async def test_yields_started_audio_stopped(self, mock_tts_manager: MagicMock) -> None:
        svc = KokoroTTSService(tts_manager=mock_tts_manager)

        frames = []
        async for frame in svc.run_tts("hello world", "ctx-1"):
            frames.append(frame)

        # Should have: TTSStartedFrame, TTSAudioRawFrame(s), TTSStoppedFrame
        assert isinstance(frames[0], TTSStartedFrame)
        assert isinstance(frames[-1], TTSStoppedFrame)

        audio_frames = [f for f in frames if isinstance(f, TTSAudioRawFrame)]
        assert len(audio_frames) >= 1
        assert audio_frames[0].sample_rate == TTS_SAMPLE_RATE
        assert audio_frames[0].num_channels == 1

    @pytest.mark.asyncio
    async def test_empty_audio_yields_no_audio_frames(self) -> None:
        mgr = MagicMock()
        mgr.synthesize.return_value = b""

        svc = KokoroTTSService(tts_manager=mgr)

        frames = []
        async for frame in svc.run_tts("", "ctx-2"):
            frames.append(frame)

        # Should have TTSStartedFrame and TTSStoppedFrame only
        assert isinstance(frames[0], TTSStartedFrame)
        assert isinstance(frames[-1], TTSStoppedFrame)
        audio_frames = [f for f in frames if isinstance(f, TTSAudioRawFrame)]
        assert len(audio_frames) == 0

    @pytest.mark.asyncio
    async def test_synthesis_error_yields_stopped(self) -> None:
        mgr = MagicMock()
        mgr.synthesize.side_effect = RuntimeError("GPU OOM")

        svc = KokoroTTSService(tts_manager=mgr)

        frames = []
        async for frame in svc.run_tts("fail", "ctx-3"):
            frames.append(frame)

        assert isinstance(frames[0], TTSStartedFrame)
        assert isinstance(frames[-1], TTSStoppedFrame)
        audio_frames = [f for f in frames if isinstance(f, TTSAudioRawFrame)]
        assert len(audio_frames) == 0

    @pytest.mark.asyncio
    async def test_large_audio_chunked(self) -> None:
        """Audio larger than 1 second should be split into chunks."""
        mgr = MagicMock()
        # 3 seconds of audio at 24kHz, 16-bit mono = 3 * 24000 * 2 = 144000 bytes
        mgr.synthesize.return_value = b"\x00" * (TTS_SAMPLE_RATE * 2 * 3)

        svc = KokoroTTSService(tts_manager=mgr)

        frames = []
        async for frame in svc.run_tts("long text", "ctx-4"):
            frames.append(frame)

        audio_frames = [f for f in frames if isinstance(f, TTSAudioRawFrame)]
        assert len(audio_frames) == 3  # 3 one-second chunks

    @pytest.mark.asyncio
    async def test_can_generate_metrics(self) -> None:
        svc = KokoroTTSService(tts_manager=MagicMock())
        assert svc.can_generate_metrics() is True
