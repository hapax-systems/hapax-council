"""Tiered TTS abstraction — Voxtral backend via Mistral hosted API."""

from __future__ import annotations

import base64
import logging
import os

import numpy as np

log = logging.getLogger(__name__)

_TIER_MAP: dict[str, str] = {
    "conversation": "voxtral",
    "notification": "voxtral",
    "briefing": "voxtral",
    "proactive": "voxtral",
}

VOXTRAL_SAMPLE_RATE = 24000


def select_tier(use_case: str) -> str:
    """Select TTS tier for a given use case, defaulting to voxtral."""
    return _TIER_MAP.get(use_case, "voxtral")


def _audio_to_pcm_int16(audio: np.ndarray) -> bytes:
    """Convert float32 audio array to raw PCM int16 bytes."""
    # Clip to [-1, 1] then scale to int16 range
    audio = np.clip(audio, -1.0, 1.0)
    pcm = (audio * 32767).astype(np.int16)
    return pcm.tobytes()


def _decode_pcm_f32_b64(data: str) -> np.ndarray:
    """Decode base64-encoded float32 little-endian PCM into a numpy array."""
    raw = base64.b64decode(data)
    return np.frombuffer(raw, dtype="<f4")


class TTSManager:
    """Manages TTS synthesis via Mistral Voxtral API."""

    def __init__(
        self,
        voice_id: str = "gb_jane_neutral",
        ref_audio_path: str | None = None,
    ) -> None:
        self.voice_id = voice_id
        self.ref_audio_path = ref_audio_path
        self._ref_audio_b64: str | None = None
        self._client = None

        # Pre-encode reference audio if provided
        if ref_audio_path is not None:
            from pathlib import Path

            resolved = Path(ref_audio_path).expanduser()
            with open(resolved, "rb") as f:
                self._ref_audio_b64 = base64.b64encode(f.read()).decode("ascii")

    def _get_client(self):
        """Lazy-init Mistral client from MISTRAL_API_KEY env var."""
        if self._client is None:
            from mistralai.client.sdk import Mistral

            api_key = os.environ.get("MISTRAL_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "MISTRAL_API_KEY environment variable is not set. Set it to use Voxtral TTS."
                )
            self._client = Mistral(api_key=api_key)
        return self._client

    def preload(self) -> None:
        """Validate API key availability at startup."""
        api_key = os.environ.get("MISTRAL_API_KEY")
        if not api_key:
            raise RuntimeError(
                "MISTRAL_API_KEY environment variable is not set. Set it to use Voxtral TTS."
            )
        log.info("Voxtral TTS ready (voice_id=%s)", self.voice_id)

    def synthesize(self, text: str, use_case: str = "conversation") -> bytes:
        """Synthesize text to raw PCM int16 audio bytes using Voxtral."""
        tier = select_tier(use_case)
        log.debug("TTS tier=%s for use_case=%s", tier, use_case)
        return self._synthesize_voxtral(text)

    def _synthesize_voxtral(self, text: str) -> bytes:
        """Stream TTS from Mistral Voxtral API, returning PCM int16 bytes."""
        client = self._get_client()

        # Voxtral drops very short utterances (especially with ref_audio voice
        # cloning). Fall back to voice_id preset for texts under 3 words.
        use_ref = self._ref_audio_b64 is not None and len(text.split()) >= 3

        # Build request kwargs — voice_id and ref_audio are mutually exclusive
        kwargs: dict = {
            "model": "voxtral-mini-tts-2603",
            "input": text,
            "response_format": "pcm",
            "stream": True,
        }
        if use_ref:
            kwargs["ref_audio"] = self._ref_audio_b64
        else:
            kwargs["voice_id"] = self.voice_id

        chunks: list[bytes] = []
        with client.audio.speech.complete(**kwargs) as stream:
            for event in stream:
                if event.event == "speech.audio.delta":
                    audio_f32 = _decode_pcm_f32_b64(event.data.audio_data)
                    chunks.append(_audio_to_pcm_int16(audio_f32))
                elif event.event == "speech.audio.done":
                    break

        if not chunks:
            log.warning("Voxtral produced no audio for text: %r", text[:50])
            return b""

        return b"".join(chunks)
