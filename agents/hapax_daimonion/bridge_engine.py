"""Compositional bridge phrase engine — contextual pre-synthesized gap fillers.

Replaces the flat bridge arrays in conversation_pipeline.py with a
layered selection system that adapts phrases to conversational context.

Design: ~50 phrases total, deterministic selection (no randomness),
pre-synthesized at daemon startup for zero-latency playback.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from enum import StrEnum

log = logging.getLogger(__name__)


class ResponseType(StrEnum):
    ACKNOWLEDGING = "acknowledging"
    THINKING = "thinking"
    TOOL_RUNNING = "tool-running"
    RECOVERING = "recovering"
    CONTINUING = "continuing"


class ActivityMode(StrEnum):
    IDLE = "idle"
    CODING = "coding"
    PRODUCTION = "production"
    MEETING = "meeting"


class ConsentPhase(StrEnum):
    NONE = "none"
    PENDING = "pending"
    ACTIVE = "active"


class TimeOfDay(StrEnum):
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    LATE_NIGHT = "late_night"


@dataclass(frozen=True)
class BridgeContext:
    """All dimensions that influence bridge phrase selection."""

    turn_position: int = 0
    activity_mode: str = "idle"
    consent_phase: str = "no_guest"
    time_of_day: str = ""
    response_type: str = "thinking"
    guest_context: bool = False
    session_id: str = ""
    model_tier: str = ""  # "CANNED", "LOCAL", "FAST", "CAPABLE"
    activation_score: float = -1.0  # -1 = not set (legacy path), 0.0-1.0 = salience


# ── Phrase pools by response_type ────────────────────────────────────

_PHRASE_POOLS: dict[str, list[str]] = {
    "acknowledging": [
        "Hey.",
        "Yep.",
        "Mm-hmm.",
        "Yeah.",
        "Got it.",
        "Sure.",
        "Right.",
    ],
    "thinking": [
        "Let me think.",
        "One sec.",
        "Hmm.",
        "On it.",
        "Checking.",
        "Thinking.",
        "Let me check.",
        "Give me a moment.",
    ],
    "ramping": [
        "Um, let's see.",
        "So.",
        "Hmm, okay.",
        "Right, so.",
        "Uh, yeah.",
        "Let me see.",
        "Okay so.",
    ],
    "deep-thinking": [
        "Let me think about that.",
        "Give me a moment on this one.",
        "That's a good question, let me think.",
        "Thinking on that.",
    ],
    "tool-running": [
        "Running that now.",
        "Pulling that up.",
        "Let me look.",
    ],
    "recovering": [
        "Let me try again.",
        "Bear with me.",
    ],
    "continuing": [
        "Also.",
        "And.",
        "Oh, one more thing.",
    ],
}

# Formal-only pool for consent_pending
_FORMAL_POOL: list[str] = [
    "One moment, please.",
    "Just a moment.",
]

# Canned responses for phatic exchanges (model_router.py CANNED tier)
_CANNED_RESPONSES: list[str] = [
    "Anytime.",
    "You got it.",
    "See you.",
    "Later.",
    "Cool.",
    "Great.",
    "No worries.",
    "Sure thing.",
    "Yep, right here.",
    "Yeah, what's up?",
    "Hey.",
    "Hey, what's up?",
    "Not much. What do you need?",
    "Hey. What's going on?",
    "Doing well. What's up?",
    "Good. You?",
]

ALL_PHRASES: list[str] = []
for pool in _PHRASE_POOLS.values():
    ALL_PHRASES.extend(pool)
ALL_PHRASES.extend(_FORMAL_POOL)
ALL_PHRASES.extend(_CANNED_RESPONSES)
# Deduplicate preserving order
_seen: set[str] = set()
ALL_PHRASES = [p for p in ALL_PHRASES if not (p in _seen or _seen.add(p))]  # type: ignore[func-returns-value]


def _current_time_of_day() -> str:
    """Classify current hour into time-of-day bucket."""
    hour = time.localtime().tm_hour
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 23:
        return "evening"
    return "late_night"


def _deterministic_index(response_type: str, turn_count: int, session_id: str) -> int:
    """Deterministic hash-based index — varies per session, no randomness."""
    key = f"{response_type}:{turn_count}:{session_id}"
    digest = hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()
    return int(digest[:8], 16)


class BridgeEngine:
    """Selects and caches pre-synthesized bridge phrases."""

    def __init__(self) -> None:
        self._cache: dict[str, bytes] = {}

    def presynthesize_all(self, tts_manager: object) -> None:
        """Pre-synthesize all bridge phrases at startup.

        Sequential — avoids API request contention.
        ~25 phrases. Runs during startup alongside other init.
        """
        synthesize = getattr(tts_manager, "synthesize", None)
        if synthesize is None:
            log.warning("TTS manager has no synthesize method, skipping presynthesis")
            return

        t0 = time.monotonic()
        for phrase in ALL_PHRASES:
            try:
                pcm = synthesize(phrase, "conversation")
                if pcm:
                    self._cache[phrase] = pcm
            except Exception:
                log.debug("Failed to presynthesize: %s", phrase, exc_info=True)
            time.sleep(0.01)  # brief yield between local Kokoro synth calls

        elapsed = time.monotonic() - t0
        log.info(
            "Pre-synthesized %d/%d bridge phrases in %.1fs",
            len(self._cache),
            len(ALL_PHRASES),
            elapsed,
        )

    def select(self, ctx: BridgeContext) -> tuple[str, bytes | None]:
        """Select a bridge phrase for the given context.

        Returns (phrase_text, cached_pcm_or_None). Returns ("", None) if
        the context vetoes all bridges (e.g. meeting mode).
        """
        # Layer 1: Hard constraints (veto)
        if ctx.activity_mode == "meeting":
            return ("", None)

        if ctx.consent_phase == "pending":
            pool = _FORMAL_POOL
            idx = _deterministic_index("formal", ctx.turn_position, ctx.session_id)
            phrase = pool[idx % len(pool)]
            return (phrase, self._cache.get(phrase))

        # Layer 2: Base pool — activation-driven when available, else tier-based
        response_type = ctx.response_type

        if ctx.activation_score >= 0:
            # Activation-driven bridge selection (salience router path)
            if ctx.activation_score < 0.3:
                response_type = "acknowledging"  # low activation: short, casual
            elif ctx.activation_score < 0.6:
                response_type = "thinking"  # medium: standard
            elif ctx.activation_score < 0.8:
                response_type = "ramping"  # high: natural dysfluency
            else:
                response_type = "deep-thinking"  # very high: intentional
        else:
            # Legacy tier-based selection
            # STRONG tier: natural dysfluency — complexity ramping up
            if ctx.model_tier == "STRONG" and ctx.turn_position > 1:
                response_type = "ramping"
            # CAPABLE tier: signal that the wait is intentional
            elif ctx.model_tier == "CAPABLE" and ctx.turn_position > 1:
                response_type = "deep-thinking"

        # Layer 3: Turn position filter
        if ctx.turn_position <= 1:
            response_type = "acknowledging"
        elif ctx.turn_position > 8:
            # Late turns: minimal bridges
            response_type = "thinking"

        pool = _PHRASE_POOLS.get(response_type, _PHRASE_POOLS["thinking"])

        # Layer 4: Time-of-day modulation
        tod = ctx.time_of_day or _current_time_of_day()
        if tod == "late_night":
            # Filter to shorter/softer phrases (≤ 3 words)
            soft = [p for p in pool if len(p.split()) <= 3]
            if soft:
                pool = soft

        # Layer 5: Activity mode filter
        if ctx.activity_mode in ("coding", "production"):
            short = [p for p in pool if len(p.split()) <= 3]
            if short:
                pool = short

        # Deterministic selection
        idx = _deterministic_index(response_type, ctx.turn_position, ctx.session_id)
        phrase = pool[idx % len(pool)]

        return (phrase, self._cache.get(phrase))

    @property
    def cache_size_bytes(self) -> int:
        return sum(len(v) for v in self._cache.values())
