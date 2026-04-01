"""Presynthesized signal cache for T1 production.

Holds PCM audio for backchannels, acknowledgments, and formulation
markers. Presynthesized at daemon startup via TTS. Signals are
categorized by type and selected randomly within category.

Replaces BridgeEngine's phrase cache with CPAL-aligned signal types.
"""

from __future__ import annotations

import logging
import random
import time

log = logging.getLogger(__name__)

# Signal categories and their phrases
BACKCHANNEL_PHRASES = ["Mm-hm.", "Yeah.", "Right.", "Okay.", "Sure."]
ACKNOWLEDGMENT_PHRASES = ["Got it.", "I hear you.", "Understood.", "Okay."]
FORMULATION_PHRASES = ["Let me think.", "One moment.", "Hmm."]

SIGNAL_CATEGORIES: dict[str, list[str]] = {
    "vocal_backchannel": BACKCHANNEL_PHRASES,
    "acknowledgment": ACKNOWLEDGMENT_PHRASES,
    "formulation_onset": FORMULATION_PHRASES,
}


class SignalCache:
    """Presynthesized audio cache for T1 signals.

    Call presynthesize() once at startup with a TTS manager.
    Then select() to get a random signal from a category.
    """

    def __init__(self) -> None:
        self._cache: dict[str, list[tuple[str, bytes]]] = {}
        self._ready = False

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def total_signals(self) -> int:
        return sum(len(entries) for entries in self._cache.values())

    def presynthesize(self, tts_manager: object) -> None:
        """Presynthesize all signals using the TTS manager.

        Args:
            tts_manager: Object with synthesize(text, use_case) -> bytes method.
        """
        synthesize = getattr(tts_manager, "synthesize", None)
        if synthesize is None:
            log.warning("TTS manager has no synthesize method, signal cache empty")
            return

        t0 = time.monotonic()
        total = 0
        failed = 0

        for category, phrases in SIGNAL_CATEGORIES.items():
            entries: list[tuple[str, bytes]] = []
            for phrase in phrases:
                try:
                    pcm = synthesize(phrase, "conversation")
                    if pcm:
                        entries.append((phrase, pcm))
                        total += 1
                    else:
                        failed += 1
                except Exception:
                    log.debug("Failed to presynthesize: %s", phrase, exc_info=True)
                    failed += 1
                time.sleep(0.2)  # avoid API rate limits
            self._cache[category] = entries

        elapsed = time.monotonic() - t0
        self._ready = total > 0
        log.info(
            "Signal cache: %d/%d presynthesized in %.1fs (%d failed)",
            total,
            total + failed,
            elapsed,
            failed,
        )

    def select(self, signal_type: str) -> tuple[str, bytes] | None:
        """Select a random signal from the given category.

        Args:
            signal_type: One of "vocal_backchannel", "acknowledgment", "formulation_onset".

        Returns:
            (phrase_text, pcm_bytes) or None if category empty or not presynthesized.
        """
        entries = self._cache.get(signal_type)
        if not entries:
            return None
        return random.choice(entries)

    def get_by_phrase(self, phrase: str) -> bytes | None:
        """Look up a specific phrase across all categories."""
        for entries in self._cache.values():
            for p, pcm in entries:
                if p == phrase:
                    return pcm
        return None
