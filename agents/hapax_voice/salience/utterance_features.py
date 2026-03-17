"""Fast utterance feature extraction — all regex/keyword, no model call.

Extracts conversational features in <1ms for routing signal composition.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ── Dialog act patterns (first-word classification) ─────────────────

_BACKCHANNEL = re.compile(
    r"^(yeah|yep|yup|uh[- ]?huh|mm[- ]?hmm|right|okay|ok|sure|cool|got\s+it|nice)[\.,!]?$",
    re.I,
)
_ACKNOWLEDGMENT = re.compile(
    r"^(thanks?(\s+you)?|thank\s+you|great|awesome|perfect|good|fine|alright)[\.,!]?$",
    re.I,
)
_YES_NO_Q = re.compile(
    r"^(is|are|was|were|do|does|did|can|could|will|would|should|have|has|had)\b",
    re.I,
)
_WH_Q = re.compile(r"^(what|where|when|who|whom|which|whose|why|how)\b", re.I)
_META_Q = re.compile(
    r"\b(explain|elaborate|why|how\s+does|think\s+(harder|more|about|through))\b",
    re.I,
)
_COMMAND = re.compile(
    r"^(search|find|check|look\s+up|open|launch|switch|close|run|play|stop|pause|set|show|tell)\b",
    re.I,
)

# ── Pre-sequence patterns ───────────────────────────────────────────

_PRE_SEQUENCE = re.compile(
    r"\b(can\s+i\s+ask|i\s+need\s+help|i\s+have\s+a\s+question|i\s+want\s+to\s+(talk|ask|discuss)"
    r"|let\s+me\s+ask|quick\s+question|real\s+quick|so\s+listen|hey\s+so)\b",
    re.I,
)

# ── Hedge and filler lexicons ───────────────────────────────────────

_HEDGES = frozenset(
    {
        "maybe",
        "perhaps",
        "possibly",
        "probably",
        "sort of",
        "kind of",
        "kinda",
        "sorta",
        "i think",
        "i guess",
        "i suppose",
        "i feel like",
        "it seems",
        "might",
        "could be",
        "not sure",
        "i don't know",
        "basically",
        "essentially",
        "actually",
        "technically",
        "apparently",
        "presumably",
        "arguably",
        "roughly",
        "approximately",
        "somewhat",
        "fairly",
        "rather",
        "relatively",
        "a bit",
        "a little",
    }
)

_FILLERS = frozenset(
    {
        "um",
        "uh",
        "er",
        "ah",
        "like",
        "you know",
        "i mean",
        "well",
        "so",
        "anyway",
        "anyways",
        "right",
    }
)

# ── Escalation phrases ─────────────────────────────────────────────

_EXPLICIT_ESCALATION = re.compile(
    r"\b(explain|elaborate|why|how\s+does|think\s+(harder|more|about|through)"
    r"|be\s+more\s+(precise|specific|detailed)|what\s+do\s+you\s+think"
    r"|your\s+opinion|analyze|compare)\b",
    re.I,
)


@dataclass(frozen=True, slots=True)
class UtteranceFeatures:
    """Extracted conversational features — all computed without LLM."""

    dialog_act: str  # backchannel, acknowledgment, yes_no_q, wh_q, meta_q, command, statement
    is_phatic: bool  # pure social function, no information content
    is_pre_sequence: bool  # signals upcoming complex turn
    hedge_count: int
    filler_count: int
    word_count: int
    has_explicit_escalation: bool  # "explain", "think harder", etc.
    topic_continuity: float  # 0.0-1.0 keyword overlap with recent turns


def extract(transcript: str, recent_turns: list[str] | None = None) -> UtteranceFeatures:
    """Extract utterance features in <1ms. All regex/keyword, no model call."""
    text = transcript.strip()
    lower = text.lower()
    words = text.split()
    word_count = len(words)

    # Dialog act classification
    dialog_act = "statement"
    is_phatic = False

    if _BACKCHANNEL.match(text):
        dialog_act = "backchannel"
        is_phatic = True
    elif _ACKNOWLEDGMENT.match(text):
        dialog_act = "acknowledgment"
        is_phatic = True
    elif text.endswith("?"):
        if _META_Q.search(text):
            dialog_act = "meta_question"
        elif _WH_Q.match(text):
            dialog_act = "wh_question"
        elif _YES_NO_Q.match(text):
            dialog_act = "yes_no_question"
        else:
            dialog_act = "open_question"
    elif _COMMAND.match(text):
        dialog_act = "command"
    elif _META_Q.search(text):
        dialog_act = "meta_question"

    # Short closers/dismissals are phatic
    if word_count <= 4 and lower in (
        "bye",
        "later",
        "see you",
        "goodnight",
        "good night",
        "never mind",
        "nah",
        "nope",
        "forget it",
    ):
        is_phatic = True

    # Pre-sequence detection
    is_pre_sequence = bool(_PRE_SEQUENCE.search(text))

    # Hedge and filler counting
    hedge_count = sum(1 for h in _HEDGES if h in lower)
    filler_count = sum(1 for f in _FILLERS if f in lower)

    # Explicit escalation
    has_explicit_escalation = bool(_EXPLICIT_ESCALATION.search(text))

    # Topic continuity with recent turns
    topic_continuity = 0.0
    if recent_turns:
        curr_sig = {w.lower() for w in words if len(w) >= 4}
        if curr_sig:
            overlaps = []
            for turn in recent_turns[-3:]:
                prev_sig = {w.lower() for w in turn.split() if len(w) >= 4}
                if prev_sig:
                    overlap = len(curr_sig & prev_sig) / max(len(curr_sig | prev_sig), 1)
                    overlaps.append(overlap)
            if overlaps:
                topic_continuity = max(overlaps)

    return UtteranceFeatures(
        dialog_act=dialog_act,
        is_phatic=is_phatic,
        is_pre_sequence=is_pre_sequence,
        hedge_count=hedge_count,
        filler_count=filler_count,
        word_count=word_count,
        has_explicit_escalation=has_explicit_escalation,
        topic_continuity=topic_continuity,
    )
