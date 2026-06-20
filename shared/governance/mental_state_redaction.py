"""LRR Phase 6 §4.E — mental-state Qdrant read-side redaction.

Five Qdrant collections carry "mental-state" content that describes the
operator's internal affect, behavioral patterns, or concerns in ways that
are not broadcast-safe:

    operator-episodes     — narrative episodes of operator-system interaction
    operator-corrections  — records of operator correcting Hapax's inferences
    operator-patterns     — derived behavioral patterns
    profile-facts         — operator profile facts (dimensions, preferences)
    hapax-apperceptions   — shared-perception moments with internal reaction

When stream is publicly visible, a query path that surfaces these points
must substitute the sanitized ``mental_state_safe_summary`` payload field
instead of the raw narrative text. If that field is missing (pre-backfill
points), the gate returns a neutral placeholder.

This module ships the helper functions + constants. Callers that query
any of these collections at stream-visible render time must invoke
``redact_mental_state_if_public()`` on each returned payload.

Backfill of existing points (populating ``mental_state_safe_summary`` via
Gemini Flash, human-reviewed) is done by
``scripts/backfill-mental-state-safe-summary.py``.
"""

from __future__ import annotations

import re
from typing import Any

from shared.stream_mode import is_publicly_visible

# Collections whose points carry mental-state content per §3.4.E.
MENTAL_STATE_COLLECTIONS: frozenset[str] = frozenset(
    {
        "operator-episodes",
        "operator-corrections",
        "operator-patterns",
        "profile-facts",
        "hapax-apperceptions",
    }
)

# Payload fields considered "raw mental-state content". When the gate fires,
# the narrative content is stripped and substituted by the safe summary.
# Ordering matters — first match wins for primary-content identification.
MENTAL_STATE_CONTENT_FIELDS: tuple[str, ...] = (
    "episode_text",
    "correction_text",
    "pattern_description",
    "apperception_narrative",
    "fact_text",
    "narrative",
    "text",
)

# Payload field that holds the pre-computed broadcast-safe summary. When
# present, this is what surfaces on public streams in place of the raw
# content. Populated at write-time (for new points) or by the backfill
# script (for existing points).
SAFE_SUMMARY_FIELD = "mental_state_safe_summary"

# Placeholder returned when a mental-state point has no safe summary yet
# (pre-backfill points, or a backfill run skipped this point). Favours
# over-redaction: we'd rather surface an empty placeholder than leak raw
# content.
DEFAULT_REDACTION_PLACEHOLDER = "[redacted: mental-state content not broadcast-safe]"


def is_mental_state_collection(collection_name: str) -> bool:
    """True iff the collection is in the §4.E mental-state set."""
    return collection_name in MENTAL_STATE_COLLECTIONS


def get_safe_summary(payload: dict[str, Any]) -> str | None:
    """Return the safe summary from a payload, or None if absent/empty."""
    value = payload.get(SAFE_SUMMARY_FIELD)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def redact_mental_state_if_public(
    collection_name: str,
    payload: dict[str, Any],
    *,
    placeholder: str = DEFAULT_REDACTION_PLACEHOLDER,
) -> dict[str, Any]:
    """Return a copy of ``payload`` with raw mental-state fields redacted
    when ``is_publicly_visible()`` is True.

    Behavior:
      - collection not in MENTAL_STATE_COLLECTIONS → return payload unchanged
      - stream not publicly visible → return payload unchanged
      - publicly visible + safe summary present → replace all raw-content
        fields with the safe summary, keep other fields
      - publicly visible + safe summary missing → replace raw-content
        fields with the placeholder

    Always returns a *new* dict (the caller's original payload is
    untouched) so call sites can safely log or forward the untouched copy
    for observability.
    """
    if not is_mental_state_collection(collection_name):
        return dict(payload)
    if not is_publicly_visible():
        return dict(payload)

    redacted = dict(payload)
    safe = get_safe_summary(payload)
    substitute = safe if safe else placeholder

    for field in MENTAL_STATE_CONTENT_FIELDS:
        if field in redacted:
            redacted[field] = substitute

    # The safe summary field itself survives (it's derived-safe by definition).
    return redacted


def redact_query_result(
    collection_name: str,
    points: list[dict[str, Any]],
    *,
    placeholder: str = DEFAULT_REDACTION_PLACEHOLDER,
) -> list[dict[str, Any]]:
    """Apply :func:`redact_mental_state_if_public` to every point's payload.

    Input shape matches Qdrant ``ScoredPoint`` dicts: each element should
    have a ``payload`` field (a dict). Points missing a payload pass through
    unchanged.
    """
    result: list[dict[str, Any]] = []
    for pt in points:
        if not isinstance(pt, dict):
            result.append(pt)
            continue
        payload = pt.get("payload")
        if not isinstance(payload, dict):
            result.append(pt)
            continue
        redacted = redact_mental_state_if_public(collection_name, payload, placeholder=placeholder)
        new_pt = dict(pt)
        new_pt["payload"] = redacted
        result.append(new_pt)
    return result


# ---------------------------------------------------------------------------
# Content-class detector (cross-boundary egress)
#
# The redactor above is collection-scoped (Qdrant read-side) and is a no-op for
# arbitrary free text — so operator affect embedded in an HKP concept title /
# description (which is not one of the five collections nor a named field) would
# cross a trust boundary unredacted. This detector inspects *content* for the
# operator-mental-state class so the cross-boundary egress scan
# (publication_allowlist.cross_boundary_pii_blockers) can fail closed on it. It
# is a conservative content gate (favours over-detection → operator review), NOT
# a clinical classifier; it does not replace the collection-scoped redactor.

# Self-referent tokens: the ratified non-formal referents (shared.operator_referent
# REFERENTS — The Operator / Oudepode / OTO) plus generic "operator" and
# first-person markers, so operator affect is caught in third person ("the
# operator is overwhelmed") and first person ("I'm exhausted lately").
_SELF_REFERENT_RE = re.compile(
    r"\b(?:operator|oudepode|oto|i|i'?m|i\s+am|my|me|myself|mine)\b",
    re.IGNORECASE,
)

# Mental-/emotional-/cognitive-state vocabulary (stems, boundary-anchored so
# "danger" does not match "anger"). Deliberately excludes bare "feel"/opinion
# verbs to avoid flagging judgements ("I feel this is correct").
_AFFECT_STEMS: tuple[str, ...] = (
    "anxi",  # anxious, anxiety, anxieties
    "stress",
    "distress",
    "overwhelm",
    "burnout",
    "burned out",
    "burnt out",
    "burn-out",
    "exhaust",  # exhausted, exhaustion
    "fatigue",
    "depress",  # depressed, depression
    "despair",
    "hopeless",
    "helpless",
    "panic",
    "dread",
    "afraid",
    "fearful",
    "scared",
    "worr",  # worry, worried, worries, worrying
    "lonely",
    "loneliness",
    "ashamed",
    "shame",
    "guilt",  # guilt, guilty
    "frustrat",  # frustrated, frustration
    "anger",
    "angry",
    "enraged",
    "elated",
    "excited",
    "ecstatic",
    "demoraliz",
    "demotivat",
    "miserable",
    "misery",
    "agitated",
    "restless",
    "grief",
    "grieving",
    "mournful",
    "mood",
    "morale",
    "well-being",
    "wellbeing",
    "mental state",
    "emotional state",
    "cognitive state",
    "psychological state",
    "mental health",
    "emotional health",
    "mentally",
    "emotionally",
    "overwrought",
    "demoralised",
)
_AFFECT_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(stem) for stem in _AFFECT_STEMS) + r")",
    re.IGNORECASE,
)

# Standalone phrases that are the mental-state content class regardless of a
# nearby self-referent (the phrase itself names operator-internal state).
_STANDALONE_AFFECT_RE = re.compile(
    r"\b(?:operator['’]s?\s+(?:mood|morale|burnout|anxiety|stress|"
    r"mental\s+state|emotional\s+state|well-?being|mental\s+health))\b",
    re.IGNORECASE,
)

_AFFECT_PROXIMITY_WINDOW = 80


def operator_mental_state_present(text: str, *, window: int = _AFFECT_PROXIMITY_WINDOW) -> bool:
    """Heuristic content-class detector for operator mental/emotional/cognitive
    state in free text.

    Returns True when the text names operator-internal affect — either a
    standalone operator-affect phrase, or a self-referent token within
    ``window`` characters of an affect/mental-state term. Conservative
    (over-detects) by design: the cross-boundary egress gate must fail closed on
    operator affect, and a false positive only forces operator review. Requiring
    self-referent proximity keeps domain/feature uses ("anxiety detection
    feature") from tripping the gate.
    """
    if not text:
        return False
    if _STANDALONE_AFFECT_RE.search(text):
        return True
    referent_positions = [m.start() for m in _SELF_REFERENT_RE.finditer(text)]
    if not referent_positions:
        return False
    for affect in _AFFECT_RE.finditer(text):
        pos = affect.start()
        if any(abs(pos - ref) <= window for ref in referent_positions):
            return True
    return False
