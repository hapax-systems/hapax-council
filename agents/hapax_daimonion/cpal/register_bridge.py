"""CPAL voice-register bridge -- HOMAGE Phase 7.

The choreographer writes the active HOMAGE package's ``voice_register_default``
to ``/dev/shm/hapax-compositor/homage-voice-register.json`` on every package
swap (including the consent-safe fallback). CPAL reads it here before each
TTS emission so tonal register tracks the visual lineage without either side
having to import the other's types.

Behaviour contract (spec §4.8, task brief task #113):

* Missing file → fall through to ``DEFAULT_REGISTER`` (``CONVERSING``).
* Stale file (>``_STALE_AFTER_S``) → fall through to ``DEFAULT_REGISTER``.
  A stale file means the choreographer stopped updating the register (dead
  compositor, or a rollback wipe); we refuse to honour a frozen value.
* Fresh file with a known register value → return that register.
* Fresh file with an unknown / malformed payload → fall through to
  ``DEFAULT_REGISTER``. Fail-open: we never raise from the bridge because
  CPAL's TTS path must not be gated by a corrupt SHM file.

A 250ms in-process cache prevents the CPAL tick (~150ms) from polling the
filesystem every emission; the cache is short enough that a fresh package
swap lands within one CPAL frame.

The register flows one way: choreographer → SHM → CPAL. CPAL never writes
this file. The consumer reads; the producer writes. See spec §4.8 and
``docs/superpowers/specs/2026-04-18-homage-framework-design.md``.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from shared.voice_register import DEFAULT_REGISTER, VoiceRegister

log = logging.getLogger(__name__)

REGISTER_FILE: Path = Path("/dev/shm/hapax-compositor/homage-voice-register.json")
"""Canonical SHM path. Co-located with other /dev/shm/hapax-compositor/
state files so a single wipe restores defaults on both sides of the wire."""

_STALE_AFTER_S: float = 2.0
"""Register file is considered stale after this many seconds. Matches the
CPAL tick granularity (150ms) × ~13 — long enough to absorb IO hiccups,
short enough that a frozen file can never override a live conversation."""

_CACHE_TTL_S: float = 0.25
"""In-process cache window. Short enough that a package swap within the
choreographer's tick (1s+) lands before the next TTS emission."""


class VoiceRegisterBridge:
    """Reads the HOMAGE-published voice register file.

    Stateless except for a tiny read-cache. Construct once per CPAL runner
    (or use the module-level ``_default_bridge`` via ``current_register()``
    for callers that don't care about injection).
    """

    def __init__(
        self,
        *,
        register_file: Path = REGISTER_FILE,
        stale_after_s: float = _STALE_AFTER_S,
        cache_ttl_s: float = _CACHE_TTL_S,
    ) -> None:
        self._register_file = register_file
        self._stale_after_s = stale_after_s
        self._cache_ttl_s = cache_ttl_s
        self._cached_register: VoiceRegister = DEFAULT_REGISTER
        self._cached_at_monotonic: float = -float("inf")

    def current_register(self, *, now: float | None = None) -> VoiceRegister:
        """Return the active voice register, honouring cache + staleness.

        ``now`` is injectable for tests; production callers omit it.
        """
        clock = time.monotonic() if now is None else now
        if (clock - self._cached_at_monotonic) < self._cache_ttl_s:
            return self._cached_register
        register = self._read_register()
        self._cached_register = register
        self._cached_at_monotonic = clock
        return register

    def _read_register(self) -> VoiceRegister:
        """Single-shot read bypassing the cache. Used by the cache wrapper."""
        path = self._register_file
        try:
            if not path.exists():
                return DEFAULT_REGISTER
            # Staleness uses wall-clock mtime because the producer (the
            # choreographer) writes on one clock and the consumer (CPAL)
            # reads on another; monotonic clocks aren't shareable across
            # processes. The absolute drift is small enough that a 2-second
            # window tolerates any realistic clock skew.
            mtime = path.stat().st_mtime
            if (time.time() - mtime) > self._stale_after_s:
                return DEFAULT_REGISTER
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.debug("voice-register file unreadable; falling back", exc_info=True)
            return DEFAULT_REGISTER

        raw = payload.get("register") if isinstance(payload, dict) else None
        if not isinstance(raw, str):
            return DEFAULT_REGISTER
        try:
            return VoiceRegister(raw)
        except ValueError:
            log.debug("voice-register value %r not in enum; falling back", raw)
            return DEFAULT_REGISTER


_default_bridge = VoiceRegisterBridge()


def current_register() -> VoiceRegister:
    """Module-level convenience reader. Uses a singleton bridge."""
    return _default_bridge.current_register()


def textmode_prompt_prefix() -> str:
    """Style directive prepended to TTS text when register is TEXTMODE.

    Kept short because it is prepended verbatim to the prompt the LLM sees
    (``generate_spontaneous_speech``) or, for direct TTS emission, passed
    into the persona framing. Phrased as an instruction, not a content
    prefix — the TTS layer strips it; the LLM layer consumes it.
    """
    return (
        "Speak clipped, IRC-style. Short phrases. Lowercase OK. "
        "No hedging, no apology, no preamble. Terminal-terse."
    )


def ambient_prompt_prefix() -> str:
    """Style directive prepended to TTS text when register is AMBIENT.

    The AMBIENT register is a density-modulated observation voice —
    sparse, factual, no engagement. It reports system state without
    narrating or interpreting. TTS speed is modulated externally via
    DENSITY_SPEED_MAP; this prefix governs *content* framing only.
    """
    return (
        "Observation register. Terse factual state reports only. "
        "No commentary, no hedging, no engagement with the operator. "
        "Report what is happening in the system — metrics, transitions, states. "
        "Never address anyone. Never narrate your own process."
    )


def frame_text_for_register(text: str, register: VoiceRegister) -> str:
    """Prepend register-appropriate framing to LLM-bound prompt text.

    CPAL calls this before handing spontaneous-speech prompts to the
    pipeline. ``ANNOUNCING`` and ``CONVERSING`` fall through unchanged —
    the default persona already frames those registers. ``TEXTMODE``
    needs an explicit shim because the BitchX lineage refuses the hedging
    that the default persona favours. ``AMBIENT`` uses a sparse observation
    voice driven by visual-layer density.
    """
    if register == VoiceRegister.TEXTMODE:
        return f"{textmode_prompt_prefix()}\n\n{text}"
    if register == VoiceRegister.AMBIENT:
        return f"{ambient_prompt_prefix()}\n\n{text}"
    return text


__all__ = [
    "REGISTER_FILE",
    "VoiceRegisterBridge",
    "ambient_prompt_prefix",
    "current_register",
    "frame_text_for_register",
    "textmode_prompt_prefix",
]
