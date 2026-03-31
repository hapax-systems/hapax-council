"""Custom Pipecat TTS service wrapping the Voxtral TTSManager."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator

from pipecat.frames.frames import (
    Frame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.services.tts_service import TTSService

from agents.hapax_daimonion.tts import VOXTRAL_SAMPLE_RATE, TTSManager

log = logging.getLogger(__name__)


class VoxtralTTSService(TTSService):
    """Pipecat TTS service that delegates synthesis to Voxtral via TTSManager.

    Voxtral outputs 24 kHz mono PCM, streamed and chunked for interruption
    support in the Pipecat pipeline.
    """

    def __init__(
        self,
        *,
        voice_id: str = "gb_jane_neutral",
        ref_audio_path: str | None = None,
        tts_manager: TTSManager | None = None,
        **kwargs,
    ) -> None:
        super().__init__(sample_rate=VOXTRAL_SAMPLE_RATE, **kwargs)
        self._tts_manager = tts_manager or TTSManager(
            voice_id=voice_id, ref_audio_path=ref_audio_path
        )

    def can_generate_metrics(self) -> bool:
        return True

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        """Synthesize text to audio frames using Voxtral.

        Yields:
            TTSStartedFrame, TTSAudioRawFrame(s), TTSStoppedFrame.
        """
        log.debug("VoxtralTTSService.run_tts: text=%r context_id=%s", text[:50], context_id)

        yield TTSStartedFrame()
        await self.start_ttfb_metrics()

        try:
            pcm_bytes = await asyncio.to_thread(self._tts_manager.synthesize, text, "conversation")
        except Exception:
            log.exception("TTS synthesis failed")
            yield TTSStoppedFrame()
            return

        await self.stop_ttfb_metrics()

        if pcm_bytes:
            chunk_size = VOXTRAL_SAMPLE_RATE * 2  # 1 second of int16 audio
            for offset in range(0, len(pcm_bytes), chunk_size):
                chunk = pcm_bytes[offset : offset + chunk_size]
                yield TTSAudioRawFrame(
                    audio=chunk,
                    sample_rate=VOXTRAL_SAMPLE_RATE,
                    num_channels=1,
                )

        yield TTSStoppedFrame()
