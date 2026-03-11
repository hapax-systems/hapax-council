"""Custom Pipecat TTS service wrapping the existing Kokoro/Piper TTSManager."""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator

from pipecat.frames.frames import (
    Frame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.services.tts_service import TTSService

from agents.hapax_voice.tts import KOKORO_SAMPLE_RATE, TTSManager

log = logging.getLogger(__name__)


class KokoroTTSService(TTSService):
    """Pipecat TTS service that delegates synthesis to the existing TTSManager.

    Wraps Kokoro (expressive, GPU) and Piper (fast, CPU) backends behind
    the Pipecat TTSService interface so they integrate into a Pipecat pipeline.
    Kokoro outputs 24 kHz audio; Piper outputs 22.05 kHz. The pipeline output
    transport resamples as needed.
    """

    def __init__(
        self,
        *,
        kokoro_voice: str = "af_heart",
        tts_manager: TTSManager | None = None,
        **kwargs,
    ) -> None:
        """Initialize the Kokoro TTS service.

        Args:
            kokoro_voice: Kokoro voice ID for expressive synthesis.
            tts_manager: Optional pre-configured TTSManager instance.
                If None, a new one is created with the given voice.
            **kwargs: Additional arguments passed to Pipecat TTSService.
        """
        super().__init__(sample_rate=KOKORO_SAMPLE_RATE, **kwargs)
        self._tts_manager = tts_manager or TTSManager(kokoro_voice=kokoro_voice)

    def can_generate_metrics(self) -> bool:
        return True

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        """Synthesize text to audio frames using the TTSManager.

        Args:
            text: The text to synthesize.
            context_id: Unique identifier for this TTS context.

        Yields:
            TTSStartedFrame, TTSAudioRawFrame(s), TTSStoppedFrame.
        """
        log.debug("KokoroTTSService.run_tts: text=%r context_id=%s", text[:50], context_id)

        yield TTSStartedFrame()

        await self.start_ttfb_metrics()

        try:
            # TTSManager.synthesize is synchronous (GPU compute) — run in thread
            pcm_bytes = await asyncio.to_thread(
                self._tts_manager.synthesize, text, "conversation"
            )
        except Exception:
            log.exception("TTS synthesis failed")
            yield TTSStoppedFrame()
            return

        await self.stop_ttfb_metrics()

        if pcm_bytes:
            # Yield audio in chunks to allow interruption
            chunk_size = KOKORO_SAMPLE_RATE * 2  # 1 second of int16 audio
            for offset in range(0, len(pcm_bytes), chunk_size):
                chunk = pcm_bytes[offset : offset + chunk_size]
                yield TTSAudioRawFrame(
                    audio=chunk,
                    sample_rate=KOKORO_SAMPLE_RATE,
                    num_channels=1,
                )

        yield TTSStoppedFrame()
