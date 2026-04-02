"""Tiered TTS abstraction — Kokoro 82M backend (local, non-autoregressive)."""

from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)

_TIER_MAP: dict[str, str] = {
    "conversation": "kokoro",
    "notification": "kokoro",
    "briefing": "kokoro",
    "proactive": "kokoro",
}

TTS_SAMPLE_RATE = 24000


def select_tier(use_case: str) -> str:
    """Select TTS tier for a given use case, defaulting to kokoro."""
    return _TIER_MAP.get(use_case, "kokoro")


class TTSManager:
    """Manages TTS synthesis via Kokoro 82M (local, non-autoregressive)."""

    def __init__(self, voice_id: str = "af_heart") -> None:
        self._voice_id = voice_id
        self._pipeline = None  # lazy init

    def preload(self) -> None:
        """Eagerly load Kokoro pipeline."""
        self._get_pipeline()
        log.info("Kokoro TTS ready (voice=%s)", self._voice_id)

    def _get_pipeline(self):
        """Lazy-init Kokoro pipeline."""
        if self._pipeline is None:
            from kokoro import KPipeline

            self._pipeline = KPipeline(lang_code="a")  # American English
        return self._pipeline

    def synthesize(self, text: str, use_case: str = "conversation") -> bytes:
        """Synthesize text to raw PCM int16 24kHz mono bytes."""
        if not text or not text.strip():
            return b""
        tier = select_tier(use_case)
        log.debug("TTS tier=%s for use_case=%s", tier, use_case)
        return self._synthesize_kokoro(text)

    def _synthesize_kokoro(self, text: str) -> bytes:
        """Synthesize via Kokoro, returning PCM int16 bytes."""
        pipeline = self._get_pipeline()
        chunks: list[bytes] = []
        for _graphemes, _phonemes, audio in pipeline(text, voice=self._voice_id):
            if audio is not None:
                # audio is a float32 tensor/array in [-1, 1]
                # Convert torch tensor to numpy if needed
                if hasattr(audio, "numpy"):
                    audio = audio.numpy()
                audio = np.asarray(audio, dtype=np.float32)
                pcm = (audio * 32768).clip(-32768, 32767).astype(np.int16)
                chunks.append(pcm.tobytes())
        if not chunks:
            log.warning("Kokoro produced no audio for text: %r", text[:50])
            return b""
        return b"".join(chunks)
