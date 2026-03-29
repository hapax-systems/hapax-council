"""Speculative partial STT — transcribe growing audio buffer during speech.

During OPERATOR_SPEAKING, periodically transcribes the accumulated speech
frames to get early partial transcripts. These partials feed the salience
router for pre-routing, so the system knows which model tier to use before
the operator finishes speaking.

Key behaviors:
- Gates on interval (1.2s between calls) and minimum speech (1.0s)
- Uses the shared ResidentSTT (single-threaded executor — serializes with final STT)
- Sets _pending flag during call so cognitive loop skips if already in-flight
- Returns None if skipped, else partial transcript
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.hapax_daimonion.resident_stt import ResidentSTT

log = logging.getLogger(__name__)


class SpeculativeTranscriber:
    """Speculative partial transcription during operator speech."""

    def __init__(self, stt: ResidentSTT, interval_s: float = 1.2) -> None:
        self._stt = stt
        self._interval_s = interval_s
        self._last_speculate_at: float = 0.0
        self._pending = False
        self._last_partial: str = ""

    async def maybe_speculate(self, speech_frames: list[bytes], speech_s: float) -> str | None:
        """Attempt speculative transcription if interval and minimum speech are met.

        Returns partial transcript or None if skipped.
        """
        if self._pending:
            return None

        if speech_s < 1.0:
            return None

        now = time.monotonic()
        if now - self._last_speculate_at < self._interval_s:
            return None

        if not speech_frames:
            return None

        self._pending = True
        self._last_speculate_at = now
        try:
            audio = b"".join(speech_frames)
            # Use _transcribe_quiet to avoid INFO logging for speculative calls
            transcript = await self._stt.transcribe(audio, _speculative=True)
            transcript = transcript.strip()
            if transcript and transcript != self._last_partial:
                self._last_partial = transcript
                log.debug(
                    "Speculative STT (%.1fs speech): '%s'",
                    speech_s,
                    transcript[:80],
                )
                return transcript
            return None
        except Exception:
            log.debug("Speculative STT failed", exc_info=True)
            return None
        finally:
            self._pending = False

    def reset(self) -> None:
        """Reset state for new speech segment."""
        self._last_speculate_at = 0.0
        self._pending = False
        self._last_partial = ""
