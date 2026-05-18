"""Conversation pipeline helper functions — text processing, thread rendering, routing.

Extracted from conversation_pipeline.py for decomposition.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Emoji pattern: matches most emoji ranges
_EMOJI_RE = re.compile(
    "["
    "\U0001f600-\U0001f64f"  # emoticons
    "\U0001f300-\U0001f5ff"  # symbols & pictographs
    "\U0001f680-\U0001f6ff"  # transport & map
    "\U0001f1e0-\U0001f1ff"  # flags
    "\U00002702-\U000027b0"  # dingbats
    "\U0000fe00-\U0000fe0f"  # variation selectors
    "\U0001f900-\U0001f9ff"  # supplemental symbols
    "\U0001fa00-\U0001fa6f"  # chess symbols
    "\U0001fa70-\U0001faff"  # symbols extended-A
    "\U00002600-\U000026ff"  # misc symbols
    "\U0000200d"  # zero width joiner
    "\U0000231a-\U0000231b"  # watch/hourglass
    "\U00002934-\U00002935"  # arrows
    "\U000025aa-\U000025ab"  # squares
    "\U000025fb-\U000025fe"  # squares
    "\U00002b05-\U00002b07"  # arrows
    "\U00002b1b-\U00002b1c"  # squares
    "\U00002b50\U00002b55"  # star/circle
    "\U00003030\U0000303d"  # wavy dash
    "\U00003297\U00003299"  # ideographs
    "]+",
    flags=re.UNICODE,
)

_GREETING_PREFIX_RE = re.compile(
    r"^(?:hey|hi|hello|yo)\s+hapax[,;:\s]*",
    flags=re.IGNORECASE,
)


def _strip_emoji(text: str) -> str:
    """Remove emoji from text, preserving surrounding words."""
    return _EMOJI_RE.sub("", text).strip()


@dataclass
class ThreadEntry:
    """Structured thread entry preserving conceptual pacts (Brennan & Clark 1996).

    Stores verbatim operator text to maintain lexical entrainment.
    Acceptance signal enables grounding state tracking (Traum 1994).
    """

    turn: int
    user_text: str  # verbatim post-greeting-strip, max 100 chars
    response_summary: str  # first clause of response, max 60 chars
    acceptance: str = "IGNORE"  # ACCEPT/CLARIFY/REJECT/IGNORE
    grounding_state: str = "pending"  # grounded/in-repair/ungrounded/pending
    is_repair: bool = False
    is_seeded: bool = False
    principal_id: str = "operator"  # who made this utterance (Says monad, AD-7)

    @staticmethod
    def acceptance_to_grounding(acceptance: str) -> str:
        """Map acceptance label to grounding state (Tier 1: acceptance-as-proxy)."""
        return {
            "ACCEPT": "grounded",
            "CLARIFY": "in-repair",
            "REJECT": "ungrounded",
            "IGNORE": "ungrounded",
        }.get(acceptance, "pending")


def _extract_substance(text: str) -> str:
    """Strip greeting prefixes, return verbatim text (max 100 chars)."""
    stripped = _GREETING_PREFIX_RE.sub("", text).strip()
    if not stripped:
        stripped = text
    return stripped[:100]


def _extract_response_clause(text: str) -> str:
    """Extract first clause of system response for thread compression."""
    return text.split(",")[0].split(".")[0][:60]


# Abbreviated acceptance labels for older thread tiers
_ACCEPTANCE_SHORT = {"ACCEPT": "OK", "CLARIFY": "?", "REJECT": "NO", "IGNORE": "-"}


def _render_thread(entries: list[ThreadEntry]) -> str:
    """Render thread entries with tiered compression.

    Recent 3: full user text in quotes + response + acceptance (~20 tokens)
    Middle 4: user referring expression + topic + abbrev acceptance (~10 tokens)
    Oldest 3: topic keyword + acceptance (~8 tokens)
    """
    n = len(entries)
    lines: list[str] = []
    for i, e in enumerate(entries):
        age = n - 1 - i
        prefix = "REPAIR:" if e.is_repair else ""
        seeded = "[PRIOR] " if e.is_seeded else ""

        if age < 3:
            lines.append(
                f'- {seeded}T{e.turn} "{e.user_text}" | {prefix}{e.response_summary} | {e.acceptance}'
            )
        elif age < 7:
            short_user = e.user_text[:40]
            short_accept = _ACCEPTANCE_SHORT.get(e.acceptance, e.acceptance)
            lines.append(
                f"- {seeded}T{e.turn} {short_user} | {prefix}{e.response_summary[:30]} | {short_accept}"
            )
        else:
            topic = " ".join(w for w in e.user_text.split()[:3] if len(w) >= 3)
            short_accept = _ACCEPTANCE_SHORT.get(e.acceptance, e.acceptance)
            lines.append(f"- {seeded}T{e.turn} {topic} | {short_accept}")

    return "\n".join(lines)


def _lcs_word_length(a: list[str], b: list[str]) -> int:
    """Longest common subsequence length between two word lists."""
    m, n = len(a), len(b)
    if m == 0 or n == 0:
        return 0
    prev = [0] * (n + 1)
    curr = [0] * (n + 1)
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(prev[j], curr[j - 1])
        prev, curr = curr, [0] * (n + 1)
    return prev[n]


# ── Response length / density constants ──────────────────────────────────────

# Clause boundary pattern for TTS chunking
_CLAUSE_END = re.compile(r"(?<=[.!?;:])\s+|(?<=\n)|(?<=,)\s+|(?<=\u2014)\s*")
_MIN_CLAUSE_WORDS = 2
_MIN_FIRST_CLAUSE_WORDS = 3
_MAX_ACCUMULATION_S = 0.3

_TIER_MAX_TOKENS: dict[str, int] = {
    "CANNED": 0,
    "LOCAL": 80,
    "FAST": 150,
    "STRONG": 4096,
    "CAPABLE": 4096,
}
# 4096 accommodates Opus 4 extended thinking (~1500-2000 reasoning tokens)
# plus actual response. Effort calibration controls spoken output length —
# max_tokens is just the ceiling to prevent finish_reason=length.
_MAX_RESPONSE_TOKENS = 4096
_MAX_SPOKEN_WORDS = 35

_DENSITY_WORD_LIMITS: dict[str, int] = {
    "presenting": 15,
    "focused": 20,
    "ambient": 35,
    "receptive": 50,
}
_MAX_TURNS = 20
_PROGRAMME_MAX_TURNS: dict[str, int] = {
    "interview": 120,
    "lecture": 60,
    "tutorial": 40,
}
_SILENCE_TIMEOUT_S = 30.0

_VLS_PATH = "/dev/shm/hapax-compositor/visual-layer-state.json"


def _density_word_limit() -> int:
    """Read display density from visual layer state and return word limit.

    Validates the JSON root is a mapping before calling ``.get`` — the
    ``except (FileNotFoundError, json.JSONDecodeError, OSError)`` clause
    does not catch AttributeError, so a writer producing valid JSON
    whose root is null, a list, a string, or a number previously raised
    AttributeError out of voice-model word-limit selection. Same
    corruption-class as the other recent SHM-read fixes.
    """
    try:
        vls = json.loads(Path(_VLS_PATH).read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        density = "ambient"
    else:
        density = vls.get("display_density", "ambient") if isinstance(vls, dict) else "ambient"
    return _DENSITY_WORD_LIMITS.get(density, _MAX_SPOKEN_WORDS)


def _stimmung_downgrade(model: str, tier: object) -> tuple[str, object]:
    """Apply stimmung-aware downgrade to voice model selection.

    Reads live stimmung from /dev/shm. Under resource/cost pressure or
    critical stance, downgrades the selected model to a cheaper tier.
    """
    from agents.hapax_daimonion.model_router import TIER_ROUTES, ModelTier

    try:
        raw = json.loads(Path("/dev/shm/hapax-stimmung/state.json").read_text(encoding="utf-8"))
    except Exception:
        return model, tier
    if not isinstance(raw, dict):
        return model, tier

    stance = raw.get("overall_stance", "nominal")
    # raw.get("resource_pressure") could be None, a list, etc. — coerce
    # to {} for the chained .get() to keep working without an
    # AttributeError on the inner read.
    resource_pressure = raw.get("resource_pressure")
    resource = resource_pressure.get("value", 0.0) if isinstance(resource_pressure, dict) else 0.0
    cost_pressure = raw.get("llm_cost_pressure")
    cost = cost_pressure.get("value", 0.0) if isinstance(cost_pressure, dict) else 0.0

    if stance == "critical":
        health_value = raw.get("health")
        health = health_value.get("value", 0.0) if isinstance(health_value, dict) else 0.0
        if health >= 0.85 or resource >= 0.85:
            log.info("Stimmung critical (health/resource) -> voice downgrade to LOCAL")
            return TIER_ROUTES[ModelTier.LOCAL], ModelTier.LOCAL
        if tier.value > ModelTier.LOCAL.value:
            new_tier = ModelTier(tier.value - 1)
            log.info("Stimmung critical (cost) -> voice %s -> %s", tier.name, new_tier.name)
            return TIER_ROUTES[new_tier], new_tier
        return model, tier

    if resource > 0.7 and tier.value > ModelTier.LOCAL.value:
        new_tier = ModelTier(tier.value - 1)
        log.info(
            "Stimmung resource pressure %.2f -> voice %s -> %s",
            resource,
            tier.name,
            new_tier.name,
        )
        return TIER_ROUTES[new_tier], new_tier

    if cost > 0.6 and tier.value >= ModelTier.STRONG.value:
        new_tier = ModelTier(tier.value - 1)
        log.info(
            "Stimmung cost pressure %.2f -> voice %s -> %s",
            cost,
            tier.name,
            new_tier.name,
        )
        return TIER_ROUTES[new_tier], new_tier

    return model, tier
