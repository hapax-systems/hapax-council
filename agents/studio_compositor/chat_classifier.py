"""LRR Phase 9 item 1 — heuristic chat classifier.

Dispatches chat messages into 7 tiers (T0-T6) using regex + deny-list
+ character-class rules. Intended as the fast-path first stage of a
three-tier classifier hierarchy (heuristic → small model → Hermes 3);
this module ships only the heuristic layer. The small-model and
Hermes 3 fallbacks are Phase 9 v2 / Phase 5 work.

Tier taxonomy (from Bundle 9 §2.2):

    T0  suspicious_injection   — jailbreak patterns, "ignore previous"
    T1  harassment             — hate, slurs, targeted abuse
    T2  spam                   — copypasta, link spam, emote spam
    T3  parasocial_demand      — "notice me" / "love you Hapax"
    T4  structural_signal      — normal on-topic chat
    T5  research_relevant      — references current claim/paper/beat
    T6  high_value             — citation / correction / novel finding

The heuristic layer intentionally biases toward **false negatives on T6**
(miss a high-value message and it degrades to T4/T5) and **false positives
on T0/T1** (accidentally flag a benign message as suspicious and drop it).
Per the Bundle 9 threat model, false-positive drops are recoverable; false-
negative injection passes are not.

Constitutional constraints:
- No per-author persistent state. The author handle is accepted as input
  for rate-limit counters that live in the caller, but this module never
  stores it. Compliant with axiom ``interpersonal_transparency``.
- No sentiment scoring. See Bundle 9 §2.6 for the rationale.
- Case-insensitive matching for most rules; character-class checks are
  Unicode-aware to avoid trivial evasion via full-width or mixed-script.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import IntEnum
from typing import Final

__all__ = [
    "ChatTier",
    "Classification",
    "classify_chat_message",
    "HEURISTIC_CLASSIFIER_VERSION",
]

HEURISTIC_CLASSIFIER_VERSION: Final = "2026-04-14-v1"


class ChatTier(IntEnum):
    """7-tier classification per Bundle 9 §2.2."""

    T0_SUSPICIOUS_INJECTION = 0
    T1_HARASSMENT = 1
    T2_SPAM = 2
    T3_PARASOCIAL_DEMAND = 3
    T4_STRUCTURAL_SIGNAL = 4
    T5_RESEARCH_RELEVANT = 5
    T6_HIGH_VALUE = 6

    @property
    def label(self) -> str:
        return {
            ChatTier.T0_SUSPICIOUS_INJECTION: "suspicious_injection",
            ChatTier.T1_HARASSMENT: "harassment",
            ChatTier.T2_SPAM: "spam",
            ChatTier.T3_PARASOCIAL_DEMAND: "parasocial_demand",
            ChatTier.T4_STRUCTURAL_SIGNAL: "structural_signal",
            ChatTier.T5_RESEARCH_RELEVANT: "research_relevant",
            ChatTier.T6_HIGH_VALUE: "high_value",
        }[self]

    @property
    def is_drop(self) -> bool:
        """Tiers T0-T3 are dropped from the Hapax prompt pathway."""
        return self <= ChatTier.T3_PARASOCIAL_DEMAND


@dataclass(frozen=True)
class Classification:
    """Result of classifying a single chat message.

    The ``reason`` field is a short machine-readable tag indicating which
    heuristic rule fired. ``confidence`` is a crude [0.0, 1.0] score used
    by the caller to decide whether to escalate to the small-model tier.
    """

    tier: ChatTier
    reason: str
    confidence: float
    classifier_version: str = HEURISTIC_CLASSIFIER_VERSION


# ---------------------------------------------------------------------------
# Rule fragments — regex + deny lists
# ---------------------------------------------------------------------------


_INJECTION_PATTERNS: Final = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions|prompts|rules)",
        r"disregard\s+(?:all\s+)?(?:previous|prior|above)",
        r"forget\s+(?:everything|all|your)\s+(?:instructions|rules|training)",
        r"you\s+are\s+now\s+(?:dan|developer\s+mode|a\s+new\s+ai)",
        r"(?:jailbreak|jail[-\s]*break|DAN\s+mode)",
        r"pretend\s+(?:you|to\s+be)\s+(?:have\s+no|don'?t\s+have)\s+(?:rules|restrictions)",
        r"act\s+as\s+(?:if|though)\s+you\s+(?:have\s+no|don'?t\s+have)",
        r"(?:system|admin|root)\s+(?:prompt|access|mode)",
        r"output\s+your\s+(?:system\s+prompt|instructions|rules)",
        r"reveal\s+(?:your|the)\s+(?:system\s+prompt|initial\s+prompt|persona)",
        r"what\s+(?:are|were)\s+(?:your\s+)?(?:initial|original)\s+instructions",
        r"```\s*system\b",
        r"<\s*/?\s*(?:system|instruction|prompt)\s*>",
    )
)
"""T0 suspicious_injection regex. Each pattern is a known jailbreak motif."""


# Deny-list is intentionally small + public. Operator can extend the caller
# later; keeping the shipped list minimal avoids shipping a slur dictionary
# in the repo. Callers should inject their own production deny-list.
_HARASSMENT_PATTERN: Final = re.compile(
    r"\b(?:kys|kill\s+yourself|go\s+(?:die|kms))\b",
    re.IGNORECASE,
)
"""Core T1 harassment signals. Minimal public set; extend via caller config."""


_DOXX_PII_PATTERN: Final = re.compile(
    r"\b(?:address|phone\s+number|ssn|social\s+security|home\s+address|real\s+name)\b",
    re.IGNORECASE,
)
_DOXX_SUBJECT_PATTERN: Final = re.compile(
    r"\b(?:operator|hapax|ryan|broadcaster)\b",
    re.IGNORECASE,
)
"""Crude doxxing attempt detector — triggers when a message contains BOTH
a PII keyword and an operator-identifying term in any order."""


_LINK_PATTERN: Final = re.compile(
    r"(?:https?://|www\.|\b[\w.-]+\.(?:com|io|gg|xyz|tv|me|ly)/\S*)",
    re.IGNORECASE,
)
"""T2 spam — any link is classified as spam by default. Whitelisting
is the caller's job; the heuristic layer does not attempt URL reputation."""


_COPYPASTA_MIN_LENGTH: Final = 200
"""Messages longer than this threshold are treated as potential copypasta."""


_ALL_CAPS_MIN_LENGTH: Final = 15
_ALL_CAPS_RATIO_THRESHOLD: Final = 0.85


_PARASOCIAL_PATTERNS: Final = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(?:notice\s+me|say\s+(?:my|hi\s+to)\s+(?:name|me))",
        r"\b(?:love\s+you\s+hapax|hapax\s+(?:i\s+love|love))",
        r"\b(?:marry\s+me|be\s+my\s+(?:gf|bf|friend))",
        r"\b(?:follow\s+me\s+back)",
    )
)
"""T3 parasocial demand regex."""


_RESEARCH_KEYWORD_PATTERN: Final = re.compile(
    r"\b(?:paper|citation|doi:|arxiv|study|experiment|hypothesis|"
    r"claim|evidence|methodology|replication|control\s+group|"
    r"statistical\s+significance|correlation|causation|p-value|"
    r"grounding|posterior|prior|bayes|confound)\b",
    re.IGNORECASE,
)
"""T5 research_relevant trigger keywords. Presence of any term bumps
the tier to T5 unless a higher-priority rule already fired."""


_HIGH_VALUE_PATTERNS: Final = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"(?:doi:\s*10\.|arxiv\s*[:/]?\s*\d{4}\.\d{4,5})",
        r"\b(?:correction|clarification|erratum)\b.*?\b(?:your|the)\b",
        r"\bcite[sd]?\s+(?:as|in)\b",
        r"(?:reference|source|paper)\s*[:=]\s*https?://",
    )
)
"""T6 high_value signals — citations, corrections, explicit references."""


# ---------------------------------------------------------------------------
# Public classifier entry point
# ---------------------------------------------------------------------------


def classify_chat_message(text: str) -> Classification:
    """Classify a single chat message into one of the 7 tiers.

    Evaluation order is strictly by priority: T0 > T1 > T2 > T3 > T6 > T5 > T4.
    T6 is evaluated BEFORE T5 because a message with both a research keyword
    and a DOI/arxiv link is high-value, not merely research-relevant.

    Args:
        text: raw chat message body. Author handle and timestamp are NOT
            accepted by the classifier — rate limits + logging are the
            caller's responsibility. This enforces the no-persistent-state
            rule at the API boundary.

    Returns:
        A :class:`Classification` naming the tier, the rule that fired,
        and a crude confidence score. The caller uses ``confidence`` to
        decide whether to escalate to a model-based classifier.
    """
    if text is None or not isinstance(text, str):
        return Classification(tier=ChatTier.T2_SPAM, reason="empty_or_non_string", confidence=0.95)

    normalized = unicodedata.normalize("NFKC", text).strip()
    if not normalized:
        return Classification(tier=ChatTier.T2_SPAM, reason="empty", confidence=0.95)

    # Priority 1: T0 suspicious_injection — these patterns are specific
    # enough that false positives on benign chat are rare.
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(normalized):
            return Classification(
                tier=ChatTier.T0_SUSPICIOUS_INJECTION,
                reason="injection_pattern",
                confidence=0.90,
            )

    # Priority 2: T1 harassment — minimal public set; caller extends.
    if _HARASSMENT_PATTERN.search(normalized):
        return Classification(
            tier=ChatTier.T1_HARASSMENT, reason="harassment_core", confidence=0.88
        )
    if _DOXX_PII_PATTERN.search(normalized) and _DOXX_SUBJECT_PATTERN.search(normalized):
        return Classification(tier=ChatTier.T1_HARASSMENT, reason="doxx_attempt", confidence=0.70)

    # Priority 3: T2 spam — links, copypasta length, all-caps ratio.
    if _LINK_PATTERN.search(normalized):
        return Classification(tier=ChatTier.T2_SPAM, reason="link", confidence=0.75)
    if len(normalized) >= _COPYPASTA_MIN_LENGTH:
        return Classification(tier=ChatTier.T2_SPAM, reason="copypasta_length", confidence=0.60)
    if _is_all_caps_excessive(normalized):
        return Classification(tier=ChatTier.T2_SPAM, reason="all_caps", confidence=0.65)

    # Priority 4: T3 parasocial demand.
    for pattern in _PARASOCIAL_PATTERNS:
        if pattern.search(normalized):
            return Classification(
                tier=ChatTier.T3_PARASOCIAL_DEMAND,
                reason="parasocial_pattern",
                confidence=0.80,
            )

    # Priority 5: T6 high_value — evaluated before T5 because explicit
    # citations/corrections subsume "generic research keyword" matches.
    for pattern in _HIGH_VALUE_PATTERNS:
        if pattern.search(normalized):
            return Classification(
                tier=ChatTier.T6_HIGH_VALUE, reason="citation_or_correction", confidence=0.80
            )

    # Priority 6: T5 research_relevant.
    if _RESEARCH_KEYWORD_PATTERN.search(normalized):
        return Classification(
            tier=ChatTier.T5_RESEARCH_RELEVANT, reason="research_keyword", confidence=0.70
        )

    # Default: T4 structural_signal — normal on-topic chat.
    return Classification(
        tier=ChatTier.T4_STRUCTURAL_SIGNAL, reason="default_structural", confidence=0.50
    )


def _is_all_caps_excessive(text: str) -> bool:
    """Return True if the message is long and mostly upper-case letters.

    Short all-caps messages (e.g. "YES!") are common and legitimate.
    Only flag long messages where the caps ratio is high.
    """
    if len(text) < _ALL_CAPS_MIN_LENGTH:
        return False
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    upper_count = sum(1 for c in letters if c.isupper())
    return (upper_count / len(letters)) >= _ALL_CAPS_RATIO_THRESHOLD
