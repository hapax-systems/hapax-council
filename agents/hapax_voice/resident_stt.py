"""Resident STT — faster-whisper model loaded once, kept in VRAM.

No per-session model loading. The WhisperModel stays resident for
the daemon's entire lifetime and is reused across all utterances.
Transcription runs in a thread pool executor to avoid blocking
the async event loop.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

import numpy as np

log = logging.getLogger(__name__)

# Dedicated executor for STT (separate from default to avoid starvation)
_stt_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")


class ResidentSTT:
    """Whisper model loaded once, transcribes on demand.

    Usage:
        stt = ResidentSTT(model="distil-large-v3")
        stt.load()  # call once at startup

        transcript = await stt.transcribe(pcm_bytes)
    """

    def __init__(
        self,
        model: str = "distil-large-v3",
        device: str = "cuda",
        compute_type: str = "float16",
    ) -> None:
        self._model_name = model
        self._device = device
        self._compute_type = compute_type
        self._model = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        """Load the Whisper model into VRAM. Call once at daemon startup."""
        try:
            from faster_whisper import WhisperModel

            log.info(
                "Loading Whisper model %s on %s (%s)...",
                self._model_name,
                self._device,
                self._compute_type,
            )
            self._model = WhisperModel(
                self._model_name,
                device=self._device,
                compute_type=self._compute_type,
            )
            log.info("Whisper model loaded: %s", self._model_name)
        except Exception:
            log.exception("Failed to load Whisper model — STT unavailable")

    async def transcribe(
        self,
        audio_bytes: bytes,
        sample_rate: int = 16000,
        language: str = "en",
        _speculative: bool = False,
    ) -> str:
        """Transcribe PCM audio bytes. Runs in thread pool.

        Args:
            audio_bytes: Raw PCM int16 mono bytes
            sample_rate: Sample rate (default 16000)
            language: Language code (default "en")
            _speculative: If True, log at DEBUG not INFO (speculative partials)

        Returns:
            Transcribed text, or empty string on failure.
        """
        if self._model is None:
            return ""

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _stt_executor,
            self._transcribe_sync,
            audio_bytes,
            sample_rate,
            language,
            _speculative,
        )

    def _transcribe_sync(
        self,
        audio_bytes: bytes,
        sample_rate: int,
        language: str,
        speculative: bool = False,
    ) -> str:
        """Synchronous transcription (runs in executor thread)."""
        try:
            audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

            segments, info = self._model.transcribe(
                audio,
                language="en",  # skip language detection (saves ~50ms)
                beam_size=1,  # greedy for speed
                vad_filter=False,  # we already did VAD
                without_timestamps=True,
                initial_prompt="Hapax, hey Hapax, voice assistant, studio, coding",
            )

            text = " ".join(seg.text for seg in segments).strip()
            if text:
                _level = log.debug if speculative else log.info
                _level(
                    'STT: "%s" (%.1fs audio, lang=%s)',
                    text,
                    len(audio) / sample_rate,
                    info.language,
                )
            return text

        except Exception:
            log.exception("STT transcription failed")
            return ""
