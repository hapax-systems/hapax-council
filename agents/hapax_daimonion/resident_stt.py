"""Resident STT — Parakeet TDT via ONNX, loaded once, kept in memory.

Non-autoregressive transducer architecture: cannot hallucinate on silence,
cannot invent plausible-but-wrong phrases. Replaces Whisper which had
structural hallucination issues (autoregressive decoder).

Transcription runs in a thread pool executor to avoid blocking the async
event loop.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import wave
from concurrent.futures import ThreadPoolExecutor

import numpy as np

log = logging.getLogger(__name__)

_stt_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")

_DEFAULT_MODEL = "nemo-parakeet-tdt-0.6b-v3"


class ResidentSTT:
    """Parakeet TDT model loaded once, transcribes on demand.

    Usage:
        stt = ResidentSTT(model="nemo-parakeet-tdt-0.6b-v3")
        stt.load()
        transcript = await stt.transcribe(pcm_bytes)
    """

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
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
        """Load the Parakeet model. Call once at daemon startup."""
        try:
            import onnx_asr

            log.info("Loading Parakeet model %s on %s...", self._model_name, self._device)
            self._model = onnx_asr.load_model(self._model_name)
            log.info("Parakeet model loaded: %s", self._model_name)
        except Exception:
            log.exception("Failed to load Parakeet model - STT unavailable")

    async def transcribe(
        self,
        audio_bytes: bytes,
        sample_rate: int = 16000,
        language: str = "en",
        _speculative: bool = False,
    ) -> str:
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
        try:
            audio = np.frombuffer(audio_bytes, dtype=np.int16)

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as f:
                with wave.open(f.name, "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(sample_rate)
                    w.writeframes(audio.tobytes())

                text = self._model.recognize(f.name)

            if isinstance(text, str):
                text = text.strip()
            else:
                text = str(text).strip()

            if text:
                _level = log.debug if speculative else log.info
                _level(
                    "STT: \"%s\" (%.1fs audio)",
                    text,
                    len(audio) / sample_rate,
                )

            return text

        except Exception:
            log.exception("STT transcription failed")
            return ""

    @staticmethod
    def _extract_prosody(
        audio: np.ndarray, sample_rate: int, word_timestamps: list[dict]
    ) -> None:
        try:
            from shared.prosody import extract_prosody, write_prosody

            features = extract_prosody(audio, sample_rate, word_timestamps)
            write_prosody(features)
        except Exception:
            log.debug("Prosody extraction failed (non-fatal)", exc_info=True)
