"""Per-utterance model routing — right intelligence for the moment.

Routes each utterance to the cheapest model tier that can handle it
well. Latency is the primary cost: a 100ms local response beats a
1400ms cloud response for "thanks". But governance-critical turns
(consent, guests) always get the most capable model available.

Tiers (ascending latency + intelligence):
  CANNED  — no LLM at all, pre-synthesized response (~0ms)
  LOCAL   — gemma3:4b via Ollama on RTX 3090 (~300ms TTFT)
  FAST    — gemini-flash via LiteLLM (~500-1400ms TTFT, tools)
  STRONG  — claude-sonnet via LiteLLM (~800-2000ms TTFT)
  CAPABLE — claude-opus via LiteLLM (~1500-3000ms TTFT)

LOCAL handles greetings and simple multi-turn conversation on-device.
STRONG uses natural dysfluency fillers ("um", "so", "let's see")
that signal a normal thinking cadence.

The operator is always willing to wait for CAPABLE if the situation
warrants it — the bridge phrase system tells them it's thinking.
Never downgrade CAPABLE to save latency.

Design principles:
  - Deterministic classification (regex + state, no LLM to classify)
  - Escalation is cheap, demotion is risky — when in doubt, go up
  - Consent/guest context always overrides to CAPABLE (governance)
  - Activity mode shapes brevity expectations, not intelligence
  - Conversation depth naturally escalates tier
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import IntEnum

log = logging.getLogger(__name__)


class ModelTier(IntEnum):
    """Model tiers ordered by latency (low→high) and capability (low→high)."""

    CANNED = 0
    LOCAL = 1  # gemma3:4b — greetings, simple multi-turn
    FAST = 2  # gemini-flash — tools, general conversation
    STRONG = 3  # claude-sonnet — ramping complexity
    CAPABLE = 4  # claude-opus — full intelligence


# LiteLLM route names for each tier
TIER_ROUTES: dict[ModelTier, str] = {
    ModelTier.CANNED: "",  # no LLM call
    ModelTier.LOCAL: "local-fast",
    ModelTier.FAST: "gemini-flash",
    ModelTier.STRONG: "claude-sonnet",
    ModelTier.CAPABLE: "claude-opus",
}


@dataclass
class RoutingDecision:
    tier: ModelTier
    model: str  # LiteLLM route name
    reason: str
    canned_response: str  # non-empty only for CANNED tier


# ── Phatic / canned response patterns ────────────────────────────────

# These skip the LLM entirely. Response is played from pre-synth cache.
# Mapped as (pattern, list of responses cycled by turn count).
_CANNED_PATTERNS: list[tuple[re.Pattern[str], list[str]]] = [
    # Closers
    (re.compile(r"^(thanks?(\s+you)?|thank\s+you\.?)$", re.I), ["Anytime.", "You got it."]),
    (re.compile(r"^(bye|later|see\s+you|good\s*night)\.?$", re.I), ["See you.", "Later."]),
    # Acknowledgments
    (re.compile(r"^(ok(ay)?|got\s+it|sure|right|yep|yeah|cool)\.?$", re.I), ["Cool.", "Great."]),
    # Dismissals
    (
        re.compile(r"^(never\s*mind|nah|no|nope|forget\s+it)\.?$", re.I),
        ["No worries.", "Sure thing."],
    ),
]

# First-turn greetings — always canned, no LLM adds value here.
_GREETING_CANNED: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(r"^(you\s+there|are\s+you\s+(there|here|awake|up))\??\.?$", re.I), ["Yep, right here.", "Yeah, what's up?"]),
    (re.compile(r"^(hey|hello|hi|yo|morning|evening)[\.,!]?$", re.I), ["Hey.", "Hey, what's up?"]),
    (re.compile(r"^what'?s\s+up\??$", re.I), ["Not much. What do you need?", "Hey. What's going on?"]),
    (re.compile(r"^(how\s+are\s+you|how'?s\s+it\s+going)\??$", re.I), ["Doing well. What's up?", "Good. You?"]),
]

# ── Escalation triggers ──────────────────────────────────────────────

# Phrases that push the tier up (user wants more from the model)
_ESCALATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(explain|elaborate|why|how\s+does|think\s+(harder|more|about|through))\b", re.I),
    re.compile(r"\b(actually|wait|no\s+i\s+mean|be\s+more\s+(precise|specific|detailed))\b", re.I),
    re.compile(r"\b(what\s+do\s+you\s+think|your\s+opinion|analyze|compare)\b", re.I),
]

# ── Tool-requiring patterns ──────────────────────────────────────────

# These need tool-calling capability (FAST minimum)
_TOOL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(search|look\s+up|find|check)\b", re.I),
    re.compile(r"\b(calendar|schedule|meeting|event)\b", re.I),
    re.compile(r"\b(email|mail|message|sms|text)\b", re.I),
    re.compile(r"\b(weather|time|date|timer)\b", re.I),
    re.compile(r"\b(status|health|docker|gpu|vram|service)\b", re.I),
    re.compile(r"\b(notification|briefing|digest)\b", re.I),
    re.compile(r"\b(open|launch|switch|close)\s+(app|window|workspace)\b", re.I),
]

# ── Simple / local-suitable patterns ─────────────────────────────────

# Short, conversational, no tools needed — local model handles fine
_LOCAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^(hey|hello|hi|yo|morning|evening|what'?s\s+up)\b", re.I),
    re.compile(r"^(you\s+there|are\s+you\s+(there|here|awake|up))\b", re.I),
    re.compile(r"^(how\s+are\s+you|how'?s\s+it\s+going)\b", re.I),
    re.compile(r"^(just\s+checking|checking\s+in|quick\s+check)\b", re.I),
    re.compile(r"^(that'?s?\s+(all|it|good|fine|great|enough))\b", re.I),
    re.compile(r"^(nothing|not\s+much|all\s+good)\b", re.I),
]


def route(
    transcript: str,
    *,
    turn_count: int = 0,
    activity_mode: str = "idle",
    consent_phase: str = "none",
    guest_mode: bool = False,
    face_count: int = 0,
    elaboration_requested: bool = False,
    has_tools: bool = True,
) -> RoutingDecision:
    """Classify an utterance to a model tier.

    Pure function — no side effects, no async, no I/O. Fast enough
    to call inline before every LLM request (~0.01ms).
    """
    text = transcript.strip()
    words = len(text.split())

    # ── Layer 1: Governance overrides (non-negotiable) ───────────

    # Consent-critical: guests present or consent flow active.
    # Bad model output here is a governance violation, not a UX issue.
    if consent_phase in ("pending", "active", "refused"):
        return RoutingDecision(
            tier=ModelTier.CAPABLE,
            model=TIER_ROUTES[ModelTier.CAPABLE],
            reason=f"consent_{consent_phase}",
            canned_response="",
        )

    if guest_mode or face_count > 1:
        return RoutingDecision(
            tier=ModelTier.CAPABLE,
            model=TIER_ROUTES[ModelTier.CAPABLE],
            reason="guest_or_multiface",
            canned_response="",
        )

    # ── Layer 2: Canned responses (zero latency) ────────────────

    # First-turn greetings — formulaic, no LLM adds value.
    if turn_count <= 1 and words <= 6:
        for pattern, responses in _GREETING_CANNED:
            if pattern.match(text):
                response = responses[turn_count % len(responses)]
                return RoutingDecision(
                    tier=ModelTier.CANNED,
                    model="",
                    reason="greeting",
                    canned_response=response,
                )

    # Later-turn phatic — acknowledgments, closers, dismissals.
    if words <= 4 and turn_count > 1:
        for pattern, responses in _CANNED_PATTERNS:
            if pattern.match(text):
                response = responses[turn_count % len(responses)]
                return RoutingDecision(
                    tier=ModelTier.CANNED,
                    model="",
                    reason="phatic",
                    canned_response=response,
                )

    # ── Layer 3: Escalation signals (push tier up) ──────────────

    # Hard escalation → CAPABLE (Opus)
    hard_escalated = False
    if elaboration_requested:
        hard_escalated = True
    if any(p.search(text) for p in _ESCALATION_PATTERNS):
        hard_escalated = True

    # Soft escalation → STRONG (Sonnet) — complexity is ramping
    soft_escalated = False
    # Longer utterances suggest the operator is thinking harder
    if words >= 10:
        soft_escalated = True
    # Multi-sentence input
    if any(c in text for c in ".?!") and words >= 8:
        soft_escalated = True
    # Deep conversation (turn 4+ with substance, not just phatic)
    if turn_count >= 4 and words >= 5:
        soft_escalated = True

    # Very deep → hard escalate
    if turn_count >= 6 and words >= 4:
        hard_escalated = True

    # ── Layer 4: Tool detection (FAST minimum) ──────────────────

    needs_tools = has_tools and any(p.search(text) for p in _TOOL_PATTERNS)

    # Deictic references (screen injection) need vision-capable model
    if any(
        kw in text.lower()
        for kw in ("what's that", "what is that", "look at", "on my screen", "on the screen")
    ):
        needs_tools = True

    # ── Layer 5: Local-suitable classification ──────────────────

    # Short, simple utterances during focused work → local is ideal
    local_suitable = False
    if words <= 6 and any(p.match(text) for p in _LOCAL_PATTERNS):
        local_suitable = True
    # Coding/production mode + short utterance → local (speed > intelligence)
    if activity_mode in ("coding", "production") and words <= 8 and not needs_tools:
        local_suitable = True

    # ── Compose final tier ──────────────────────────────────────

    if hard_escalated:
        tier = ModelTier.CAPABLE
    elif needs_tools and soft_escalated:
        tier = ModelTier.STRONG
    elif needs_tools:
        tier = ModelTier.FAST
    elif local_suitable and not soft_escalated:
        tier = ModelTier.LOCAL
    elif soft_escalated:
        tier = ModelTier.STRONG
    elif turn_count >= 2 and not needs_tools and words <= 8:
        # Multi-turn simple conversation — stay on-device
        tier = ModelTier.LOCAL
    else:
        tier = ModelTier.FAST

    return RoutingDecision(
        tier=tier,
        model=TIER_ROUTES[tier],
        reason=_reason(
            tier, needs_tools, local_suitable, soft_escalated, hard_escalated, activity_mode
        ),
        canned_response="",
    )


def _reason(
    tier: ModelTier,
    needs_tools: bool,
    local_suitable: bool,
    soft_escalated: bool,
    hard_escalated: bool,
    activity_mode: str,
) -> str:
    parts = []
    if needs_tools:
        parts.append("tools")
    if local_suitable:
        parts.append("simple")
    if hard_escalated:
        parts.append("hard_escalated")
    elif soft_escalated:
        parts.append("ramping")
    if activity_mode in ("coding", "production"):
        parts.append(activity_mode)
    return "+".join(parts) if parts else "default"
