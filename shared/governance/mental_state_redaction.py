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
