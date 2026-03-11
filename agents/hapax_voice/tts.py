"""Tiered TTS abstraction — Piper for short utterances, Kokoro for conversation."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

_TIER_MAP: dict[str, str] = {
    "conversation": "kokoro",
    "notification": "kokoro",
    "briefing": "kokoro",
    "proactive": "kokoro",
}

PIPER_MODEL_DIR = Path.home() / ".local" / "share" / "hapax-voice"
PIPER_MODEL_DEFAULT = PIPER_MODEL_DIR / "piper-voice.onnx"
PIPER_SAMPLE_RATE = 22050  # Piper default sample rate
KOKORO_SAMPLE_RATE = 24000


def select_tier(use_case: str) -> str:
    """Select TTS tier for a given use case, defaulting to kokoro."""
    return _TIER_MAP.get(use_case, "kokoro")


def _audio_to_pcm_int16(audio: np.ndarray) -> bytes:
    """Convert float32 audio array to raw PCM int16 bytes."""
    # Clip to [-1, 1] then scale to int16 range
    audio = np.clip(audio, -1.0, 1.0)
    pcm = (audio * 32767).astype(np.int16)
    return pcm.tobytes()


class TTSManager:
    """Manages TTS synthesis across Piper (fast) and Kokoro (expressive) tiers."""

    def __init__(
        self,
        kokoro_voice: str = "af_heart",
        piper_model_path: str | Path | None = None,
    ) -> None:
        self.kokoro_voice = kokoro_voice
        self.piper_model_path = Path(piper_model_path) if piper_model_path else PIPER_MODEL_DEFAULT
        self._piper_model = None
        self._kokoro_pipeline = None

    def synthesize(self, text: str, use_case: str = "conversation") -> bytes:
        """Synthesize text to raw PCM int16 audio bytes using the appropriate TTS tier."""
        tier = select_tier(use_case)
        log.debug("TTS tier=%s for use_case=%s", tier, use_case)
        if tier == "piper":
            return self._synthesize_piper(text)
        return self._synthesize_kokoro(text)

    def _load_piper(self) -> None:
        """Lazy-load the Piper ONNX voice model."""
        try:
            from piper import PiperVoice
        except ImportError:
            raise RuntimeError(
                "piper-tts is not installed. Install with: uv pip install piper-tts"
            ) from None

        model_path = self.piper_model_path
        if not model_path.exists():
            raise RuntimeError(
                f"Piper voice model not found at {model_path}. "
                f"Download a .onnx voice model to {PIPER_MODEL_DIR}/"
            )

        config_path = model_path.with_suffix(".onnx.json")
        log.info("Loading Piper model from %s", model_path)
        self._piper_model = PiperVoice.load(
            str(model_path),
            config_path=str(config_path) if config_path.exists() else None,
        )

    def _synthesize_piper(self, text: str) -> bytes:
        """Synthesize using Piper (lightweight, CPU-only, fast)."""
        if self._piper_model is None:
            self._load_piper()

        chunks: list[bytes] = []
        for audio_bytes in self._piper_model.synthesize_stream_raw(text):
            chunks.append(audio_bytes)

        if not chunks:
            log.warning("Piper produced no audio for text: %r", text[:50])
            return b""

        return b"".join(chunks)

    def _load_kokoro(self) -> None:
        """Lazy-load the Kokoro TTS pipeline."""
        try:
            import kokoro
        except ImportError:
            raise RuntimeError(
                "kokoro is not installed. Install with: uv pip install kokoro"
            ) from None

        log.info("Loading Kokoro pipeline (voice=%s)...", self.kokoro_voice)
        try:
            self._kokoro_pipeline = kokoro.KPipeline(lang_code="a")
        except Exception as exc:
            raise RuntimeError(f"Failed to initialize Kokoro pipeline: {exc}") from exc

    def _synthesize_kokoro(self, text: str) -> bytes:
        """Synthesize using Kokoro (expressive, GPU-accelerated)."""
        if self._kokoro_pipeline is None:
            self._load_kokoro()

        chunks: list[bytes] = []
        for _graphemes, _phonemes, audio_tensor in self._kokoro_pipeline(
            text, voice=self.kokoro_voice
        ):
            # audio_tensor is a torch tensor — convert to numpy float32 then to PCM int16
            audio_np = audio_tensor.cpu().numpy().astype(np.float32)
            if audio_np.ndim > 1:
                audio_np = audio_np.squeeze()
            chunks.append(_audio_to_pcm_int16(audio_np))

        if not chunks:
            log.warning("Kokoro produced no audio for text: %r", text[:50])
            return b""

        return b"".join(chunks)
