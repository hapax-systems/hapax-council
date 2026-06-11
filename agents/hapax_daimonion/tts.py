"""Tiered TTS abstraction — backend selected via ``HAPAX_TTS_BACKEND``.

Backend selection is versioned code: ``HAPAX_TTS_BACKEND`` (``chatterbox`` |
``kokoro``, read at :class:`TTSManager` construction) picks the primary
engine; the systemd drop-in that sets it lives at
``systemd/units/hapax-daimonion.service.d/tts-backend.conf``. Invalid or
unset values resolve to ``chatterbox``, which itself falls back to Kokoro
when the model cannot load or a synthesis call fails. The engine that
actually produced the most recent PCM is exposed as
:attr:`TTSManager.last_synthesis_backend` for the voice-output witness.

Every TTS call passes through :func:`shared.speech_safety.censor` before
synthesis — this is the canonical fail-closed slur gate. The voice is
raw material for S-4 self-modulation; voice identity lives in the S-4's
transformation, not in the TTS model's output.

Chatterbox (classic ``ChatterboxTTS``, 350M, GPU): voice cloned from
non-human reference audio (processed Kokoro output with shifted formants).
Paralinguistic tags ([whisper], [breath], [gasp]) used as timbral
variation points for S-4 granular processing, not as emotions. The Turbo
class swap rides the torch>=2.9+cu128 keystone (Phase 1 of
CASE-VOICE-FOUNDATION-20260610); until then sm_120 cards have no kernels
and Chatterbox fails to load.

Kokoro 82M (CPU): selectable primary or automatic fallback.
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

TTS_BACKEND_ENV = "HAPAX_TTS_BACKEND"
VALID_TTS_BACKENDS: tuple[str, ...] = ("chatterbox", "kokoro")
_DEFAULT_TTS_BACKEND = "chatterbox"

_VOICE_SAMPLE_PATH = Path(__file__).resolve().parent.parent.parent / "profiles" / "voice-sample.wav"
_CHATTERBOX_DEVICE = os.environ.get("HAPAX_CHATTERBOX_DEVICE", "cuda:0")
_CHATTERBOX_EXAGGERATION = 0.50
_CHATTERBOX_CFG_WEIGHT = 0.3
_INTERVIEW_EXAGGERATION = 0.20
_INTERVIEW_CFG_WEIGHT = 0.50


# Expressiveness gained from arc open (0.0) to arc peak (1.0). Small + bounded
# so delivery stays natural — this is a continuous controller of prosody, not a
# per-beat preset table.
_ARC_EXAGGERATION_GAIN = 0.15


def select_tier(use_case: str) -> str:
    return _TIER_MAP.get(use_case, "chatterbox")


def resolve_backend_from_env() -> str:
    """Resolve the primary TTS backend from ``HAPAX_TTS_BACKEND``.

    Unset/empty resolves to the default; an invalid value warns with the
    valid choices and resolves to the default rather than dying silently.
    """
    raw = os.environ.get(TTS_BACKEND_ENV, "").strip().lower()
    if not raw:
        return _DEFAULT_TTS_BACKEND
    if raw in VALID_TTS_BACKENDS:
        return raw
    log.warning(
        "%s=%r is not a valid TTS backend (valid: %s) — using %r",
        TTS_BACKEND_ENV,
        raw,
        ", ".join(VALID_TTS_BACKENDS),
        _DEFAULT_TTS_BACKEND,
    )
    return _DEFAULT_TTS_BACKEND


def _arc_prosody(
    arc_position: float | None,
    *,
    base_exag: float,
    base_cfg: float,
) -> tuple[float, float]:
    """Modulate (exaggeration, cfg_weight) by position in the segment arc.

    ``arc_position`` is the clause's fractional position in the segment arc
    (0.0 = open, 1.0 = peak/close); ``None`` leaves prosody at the base.
    Expressiveness rises smoothly toward the peak, bounded to the valid
    ``[0, 1]`` exaggeration range so the rise can never distort delivery.
    """
    if arc_position is None:
        return base_exag, base_cfg
    position = max(0.0, min(1.0, arc_position))
    exag = max(0.0, min(1.0, base_exag + _ARC_EXAGGERATION_GAIN * position))
    return exag, base_cfg


class TTSManager:
    """Manages TTS synthesis — primary backend from ``HAPAX_TTS_BACKEND``."""

    def __init__(self, voice_id: str = "af_heart") -> None:
        self._voice_id = voice_id
        self._chatterbox_model = None
        self._kokoro_pipeline = None
        self._backend = resolve_backend_from_env()
        self._last_synthesis_backend: str | None = None

    @property
    def backend(self) -> str:
        """Configured primary backend (may demote to kokoro at preload)."""
        return self._backend

    @property
    def last_synthesis_backend(self) -> str | None:
        """Engine that produced the most recent PCM — fallback-aware.

        ``None`` until the first synthesis completes. This is the witness
        truth: with the chatterbox backend a per-call failure falls back to
        Kokoro, so the configured backend alone cannot say which engine
        actually spoke.
        """
        return self._last_synthesis_backend

    def preload(self) -> None:
        if self._backend == "kokoro":
            self._get_kokoro()
            log.info("Kokoro TTS ready (voice=%s, selected primary)", self._voice_id)
            return
        try:
            self._get_chatterbox()
            self._backend = "chatterbox"
            log.info("Chatterbox TTS ready (device=%s)", _CHATTERBOX_DEVICE)
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

            self._kokoro_pipeline = KPipeline(lang_code="a", device="cpu")
        return self._kokoro_pipeline

    def synthesize(
        self,
        text: str,
        use_case: str = "conversation",
        *,
        speed: float = 1.0,
        interview_mode: bool = False,
        role: str | None = None,
        arc_position: float | None = None,
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

        if self._backend == "chatterbox":
            try:
                return self._synthesize_chatterbox(
                    lexicon.text,
                    interview_mode=interview_mode,
                    role=role,
                    arc_position=arc_position,
                )
            except Exception:
                log.warning("Chatterbox synthesis failed, falling back to Kokoro", exc_info=True)
                return self._synthesize_kokoro(lexicon.text, speed=speed)
        return self._synthesize_kokoro(lexicon.text, speed=speed)

    def _synthesize_chatterbox(
        self,
        text: str,
        *,
        interview_mode: bool = False,
        role: str | None = None,
        arc_position: float | None = None,
    ) -> bytes:
        model = self._get_chatterbox()
        voice_path = str(_VOICE_SAMPLE_PATH) if _VOICE_SAMPLE_PATH.exists() else None
        # Interview / dialogic roles deliver with restraint; everything else
        # uses the default base. Arc position then modulates expressiveness
        # continuously around that base.
        restrained = interview_mode or role == "interview"
        base_exag = _INTERVIEW_EXAGGERATION if restrained else _CHATTERBOX_EXAGGERATION
        base_cfg = _INTERVIEW_CFG_WEIGHT if restrained else _CHATTERBOX_CFG_WEIGHT
        exag, cfg = _arc_prosody(arc_position, base_exag=base_exag, base_cfg=base_cfg)
        wav = model.generate(
            text,
            audio_prompt_path=voice_path,
            exaggeration=exag,
            cfg_weight=cfg,
        )
        self._last_synthesis_backend = "chatterbox"
        audio = wav.squeeze().cpu().numpy().astype(np.float32)
        pcm = (audio * 32768).clip(-32768, 32767).astype(np.int16)
        if pcm.size == 0:
            log.warning("Chatterbox produced no audio for: %r", text[:50])
            return b""
        return pcm.tobytes()

    def _synthesize_kokoro(self, text: str, *, speed: float = 1.0) -> bytes:
        pipeline = self._get_kokoro()
        self._last_synthesis_backend = "kokoro"
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
