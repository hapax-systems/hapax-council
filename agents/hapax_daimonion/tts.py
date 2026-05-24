"""Tiered TTS abstraction — Chatterbox Turbo primary, Kokoro fallback.

Every TTS call passes through :func:`shared.speech_safety.censor` before
synthesis — this is the canonical fail-closed slur gate. The voice is
raw material for S-4 self-modulation; voice identity lives in the S-4's
transformation, not in the TTS model's output.

Chatterbox Turbo (350M, GPU): primary backend. Voice cloned from
non-human reference audio (processed Kokoro output with shifted formants).
Paralinguistic tags ([whisper], [breath], [gasp]) used as timbral
variation points for S-4 granular processing, not as emotions.

Kokoro 82M (CPU): fallback if Chatterbox fails to load.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import numpy as np

from shared.speech_lexicon import apply_lexicon as _speech_lexicon_apply
from shared.speech_safety import censor as _speech_safety_censor

log = logging.getLogger(__name__)

_TIER_MAP: dict[str, str] = {
    "conversation": "chatterbox",
    "notification": "chatterbox",
    "briefing": "chatterbox",
    "proactive": "chatterbox",
}

TTS_SAMPLE_RATE = 24000
_VOICE_SAMPLE_PATH = Path(__file__).resolve().parent.parent.parent / "profiles" / "voice-sample.wav"
_CHATTERBOX_DEVICE = os.environ.get("HAPAX_CHATTERBOX_DEVICE", "cuda:0")
_CHATTERBOX_EXAGGERATION = 0.50
_CHATTERBOX_CFG_WEIGHT = 0.3
_INTERVIEW_EXAGGERATION = 0.20
_INTERVIEW_CFG_WEIGHT = 0.50


def select_tier(use_case: str) -> str:
    return _TIER_MAP.get(use_case, "chatterbox")


class TTSManager:
    """Manages TTS synthesis — Chatterbox Turbo primary, Kokoro fallback."""

    def __init__(self, voice_id: str = "af_heart") -> None:
        self._voice_id = voice_id
        self._chatterbox_model = None
        self._kokoro_pipeline = None
        self._backend = os.environ.get("HAPAX_TTS_BACKEND", "chatterbox")
        self._remote_host = os.environ.get("HAPAX_TTS_REMOTE_HOST")
        self._remote_port = int(os.environ.get("HAPAX_TTS_REMOTE_PORT", "9851"))

    def preload(self) -> None:
        if self._remote_host:
            self._backend = "remote"
            log.info("TTS remote mode: %s:%d", self._remote_host, self._remote_port)
            return
        if self._backend == "kokoro":
            self._get_kokoro()
            log.info("Kokoro TTS ready (voice=%s, GPU primary)", self._voice_id)
            return
        try:
            self._get_chatterbox()
            self._backend = "chatterbox"
            log.info("Chatterbox Turbo TTS ready (device=%s)", _CHATTERBOX_DEVICE)
        except Exception:
            log.warning("Chatterbox failed to load, falling back to Kokoro", exc_info=True)
            self._get_kokoro()
            self._backend = "kokoro"
            log.info("Kokoro TTS ready (voice=%s, fallback)", self._voice_id)

    def _get_chatterbox(self):
        if self._chatterbox_model is None:
            from chatterbox.tts import ChatterboxTTS

            self._chatterbox_model = ChatterboxTTS.from_pretrained(device=_CHATTERBOX_DEVICE)
        return self._chatterbox_model

    def _get_kokoro(self):
        if self._kokoro_pipeline is None:
            from kokoro import KPipeline

            self._kokoro_pipeline = KPipeline(lang_code="a")
        return self._kokoro_pipeline

    def synthesize(
        self,
        text: str,
        use_case: str = "conversation",
        *,
        speed: float = 1.0,
        interview_mode: bool = False,
    ) -> bytes:
        if not text or not text.strip():
            return b""
        redaction = _speech_safety_censor(text)
        if redaction.was_modified:
            log.warning(
                "TTS safety gate redacted %d token(s) [%s]",
                redaction.hit_count,
                use_case,
            )
        lexicon = _speech_lexicon_apply(redaction.text)

        if self._backend == "remote":
            try:
                return self._synthesize_remote(lexicon.text, use_case)
            except Exception:
                log.warning("Remote TTS failed, falling back to Kokoro", exc_info=True)
                return self._synthesize_kokoro(lexicon.text, speed=speed)
        if self._backend == "chatterbox":
            try:
                return self._synthesize_chatterbox(lexicon.text, interview_mode=interview_mode)
            except Exception:
                log.warning("Chatterbox synthesis failed, falling back to Kokoro", exc_info=True)
                return self._synthesize_kokoro(lexicon.text, speed=speed)
        return self._synthesize_kokoro(lexicon.text, speed=speed)

    def _synthesize_chatterbox(self, text: str, *, interview_mode: bool = False) -> bytes:
        model = self._get_chatterbox()
        voice_path = str(_VOICE_SAMPLE_PATH) if _VOICE_SAMPLE_PATH.exists() else None
        exag = _INTERVIEW_EXAGGERATION if interview_mode else _CHATTERBOX_EXAGGERATION
        cfg = _INTERVIEW_CFG_WEIGHT if interview_mode else _CHATTERBOX_CFG_WEIGHT
        wav = model.generate(
            text,
            audio_prompt_path=voice_path,
            exaggeration=exag,
            cfg_weight=cfg,
        )
        audio = wav.squeeze().cpu().numpy().astype(np.float32)
        pcm = (audio * 32768).clip(-32768, 32767).astype(np.int16)
        if pcm.size == 0:
            log.warning("Chatterbox produced no audio for: %r", text[:50])
            return b""
        return pcm.tobytes()

    def _synthesize_remote(self, text: str, use_case: str = "conversation") -> bytes:
        import json
        import socket

        request = json.dumps({"text": text, "use_case": use_case}) + "\n"
        sock = socket.create_connection((self._remote_host, self._remote_port), timeout=60)
        try:
            sock.sendall(request.encode())
            buf = b""
            while b"\n" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    raise RuntimeError("Remote TTS connection closed before header")
                buf += chunk
            header_line, remainder = buf.split(b"\n", 1)
            header = json.loads(header_line)
            if header.get("status") != "ok":
                raise RuntimeError(f"Remote TTS error: {header.get('error', 'unknown')}")
            pcm_len = header["pcm_len"]
            pcm = remainder
            while len(pcm) < pcm_len:
                chunk = sock.recv(min(65536, pcm_len - len(pcm)))
                if not chunk:
                    break
                pcm += chunk
            log.info(
                "Remote TTS: %d bytes from %s:%d", len(pcm), self._remote_host, self._remote_port
            )
            return pcm
        finally:
            sock.close()

    def _synthesize_kokoro(self, text: str, *, speed: float = 1.0) -> bytes:
        pipeline = self._get_kokoro()
        chunks: list[bytes] = []
        for _graphemes, _phonemes, audio in pipeline(text, voice=self._voice_id, speed=speed):
            if audio is not None:
                if hasattr(audio, "numpy"):
                    audio = audio.numpy()
                audio = np.asarray(audio, dtype=np.float32)
                pcm = (audio * 32768).clip(-32768, 32767).astype(np.int16)
                chunks.append(pcm.tobytes())
        if not chunks:
            log.warning("Kokoro produced no audio for: %r", text[:50])
            return b""
        return b"".join(chunks)
