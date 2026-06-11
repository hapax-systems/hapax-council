"""Resident STT — faster-whisper model loaded once, kept in VRAM.

No per-session model loading. The WhisperModel stays resident for
the daemon's entire lifetime and is reused across all utterances.
Transcription runs in a thread pool executor to avoid blocking
the async event loop.
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

log = logging.getLogger(__name__)

# Dedicated executors, one per lane (separate from default to avoid
# starvation). Final and speculative transcription get their own
# single-thread executors so a speculative decode backlog can never queue
# ahead of the utterance-final transcription (the audit's 35.5s pipeline
# outlier was exactly that queueing). Residual wait: WhisperModel defaults
# to num_workers=1, so a final decode may still wait for ONE in-flight
# speculative decode inside CTranslate2 — bounded sub-second at beam 2,
# unlike the old unbounded executor backlog (which included inline Praat).
# Prosody runs on its own executor so it never extends the hot path.
_stt_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt-final")
_speculative_stt_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt-spec")
_prosody_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="prosody")


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
            _speculative: If True, log at DEBUG not INFO and run on the
                speculative executor so partials never queue ahead of
                final transcription

        Returns:
            Transcribed text, or empty string on failure.
        """
        if self._model is None:
            return ""

        loop = asyncio.get_running_loop()
        executor = _speculative_stt_executor if _speculative else _stt_executor
        return await loop.run_in_executor(
            executor,
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

            t0 = time.monotonic()
            segments, info = self._model.transcribe(
                audio,
                language="en",  # skip language detection (saves ~50ms)
                # Hot-path lean decode (audit SS7-P0): beam 2 instead of 5,
                # no word timestamps — both cut decode latency; word-level
                # alignment fed only prosody, which now runs off this path.
                beam_size=2,
                vad_filter=False,  # we already did VAD
                # Whisper treats initial_prompt as "preceding transcript" and
                # conditions on its style/vocabulary. Realistic example sentences
                # with "Hapax" bias the decoder toward the word — keyword lists
                # don't work well. Covers both pronunciations (HAY-paks, HA-packs).
                initial_prompt=(
                    "Hey Hapax, what's going on? "
                    "Hapax, can you check that for me? "
                    "Thanks Hapax. "
                    "Hey Hapax, what do you think about this? "
                    "Hapax, tell me about the studio session."
                ),
            )

            # Decode happens lazily during segment iteration — time it.
            text_parts: list[str] = [seg.text for seg in segments]
            decode_ms = (time.monotonic() - t0) * 1000.0

            text = " ".join(text_parts).strip()
            if text:
                _level = log.debug if speculative else log.info
                _level(
                    'STT: "%s" (%.1fs audio, %.0fms decode, lang=%s)',
                    text,
                    len(audio) / sample_rate,
                    decode_ms,
                    info.language,
                )

                if not speculative:
                    # Fire-and-forget on the prosody executor — Praat
                    # analysis must not extend the transcription hot path.
                    _prosody_executor.submit(self._extract_prosody, audio, sample_rate, None)

            return text

        except Exception:
            log.exception("STT transcription failed")
            return ""

    @staticmethod
    def _extract_prosody(
        audio: np.ndarray, sample_rate: int, word_timestamps: list[dict] | None
    ) -> None:
        """Extract and publish prosodic features (best-effort, never blocks).

        Runs on the dedicated prosody executor. Without word timestamps the
        speaking-rate feature is unavailable; pitch/energy/HNR survive.
        """
        try:
            from shared.prosody import extract_prosody, write_prosody

            features = extract_prosody(audio, sample_rate, word_timestamps)
            write_prosody(features)
        except Exception:
            log.debug("Prosody extraction failed (non-fatal)", exc_info=True)
