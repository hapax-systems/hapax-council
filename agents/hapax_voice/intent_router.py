"""Intent router for backend selection (local vs Gemini)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Patterns that indicate system/management intents routed to local backend
_SYSTEM_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bbriefing\b", re.IGNORECASE), "briefing"),
    (re.compile(r"\bdigest\b", re.IGNORECASE), "digest"),
    (re.compile(r"\bcalendar\b", re.IGNORECASE), "calendar"),
    (re.compile(r"\bschedule\b", re.IGNORECASE), "schedule"),
    (re.compile(r"\bmeeting\s*prep\b", re.IGNORECASE), "meeting_prep"),
    (re.compile(r"\b1[:\-]1\b", re.IGNORECASE), "one_on_one"),
    (re.compile(r"\bsystem\s*(status|health|check)\b", re.IGNORECASE), "system_status"),
    (re.compile(r"\bnotification\b", re.IGNORECASE), "notification"),
    (re.compile(r"\bhealth\b", re.IGNORECASE), "health"),
    (re.compile(r"\bvram\b", re.IGNORECASE), "vram"),
    (re.compile(r"\bgpu\b", re.IGNORECASE), "gpu"),
    (re.compile(r"\bdocker\b", re.IGNORECASE), "docker"),
    (re.compile(r"\bcontainer\b", re.IGNORECASE), "container"),
    (re.compile(r"\btimer\b", re.IGNORECASE), "timer"),
    (re.compile(r"\bservice\b", re.IGNORECASE), "service"),
    (re.compile(r"\brun\s+agent\b", re.IGNORECASE), "run_agent"),
    (re.compile(r"\bsearch\s+(docs|documents|notes|rag)\b", re.IGNORECASE), "search_docs"),
]

# Prefix indicating direct address to Hapax
_HAPAX_PREFIX = re.compile(r"^(hey\s+)?hapax\b[,:]?\s*", re.IGNORECASE)


@dataclass
class IntentResult:
    """Result of intent classification."""

    backend: str  # "gemini" or "local"
    matched_pattern: str  # name of matched pattern, empty if none


def classify_intent(text: str, guest_mode: bool = False) -> IntentResult:
    """Classify user intent to determine backend routing.

    Guest mode always routes to Gemini. System patterns route to local.
    Hapax prefix without a system pattern still routes local.
    Default is Gemini for general conversation.
    """
    if guest_mode:
        return IntentResult(backend="gemini", matched_pattern="")

    # Strip hapax prefix for pattern matching
    stripped = _HAPAX_PREFIX.sub("", text)
    had_prefix = stripped != text

    # Check system patterns
    for pattern, name in _SYSTEM_PATTERNS:
        if pattern.search(stripped):
            log.debug("Intent matched pattern %s", name)
            return IntentResult(backend="local", matched_pattern=name)

    # Hapax prefix without system pattern still routes local
    if had_prefix:
        return IntentResult(backend="local", matched_pattern="hapax_direct")

    # Default: general conversation via Gemini
    return IntentResult(backend="gemini", matched_pattern="")
