"""Director-moves quality assessment for segment observability.

Cc-task ``director-moves-segment-smoke`` (operator outcome 3 follow-up).
Composes with PR #2472 ``shared/segment_observability.py`` — the SegmentRecorder
context manager yields a ``SegmentEvent`` whose ``quality.director_moves``
field this module computes from a window of director-intent records.

Operator's 4-tier framing:

- **poor** — every record in the window carries the
  ``fallback.micromove.stale_intent`` synthetic marker; the surface ran on
  the director's deterministic-code micromove autopilot only.
- **acceptable** — mixed; the window has at least one non-fallback record
  but at least one record IS a fallback (stale_intent or another
  ``fallback.*`` marker).
- **good** — every record in the window is non-fallback (no
  ``synthetic_grounding_markers`` at the top level), but the per-impingement
  grounding may not be uniformly real, or the moves did not span multiple
  surfaces.
- **excellent** — every record is non-fallback AND every per-impingement
  ``grounding_provenance`` is real (no synthetic markers anywhere), AND the
  window's compositional_impingements span ≥2 distinct ``intent_family``
  values (composability across surfaces, per the operator's "multi-surface
  moves" prompt guidance in the unified director prompt).

The four tiers are computed deterministically from the JSONL records the
director already writes via ``_emit_intent_artifacts``; this module does
not need to look at the live director loop or run any LLM call. That keeps
the smoke test infrastructure-free.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from shared.segment_observability import QualityRating

__all__ = [
    "assess_director_moves_quality",
    "STALE_INTENT_MARKER_TOKEN",
]


# Substring that flags a record as a stale-intent micromove fallback. The
# director writes synthetic markers like ``"fallback.micromove.stale_intent"``
# (and other ``fallback.micromove.<reason>`` tokens) on the silence-hold /
# micromove paths. We match on the substring so any future fallback reason
# under the ``fallback.`` prefix still counts as a fallback.
STALE_INTENT_MARKER_TOKEN: str = "stale_intent"
_FALLBACK_PREFIX: str = "fallback."


def _is_stale_intent_record(record: dict[str, Any]) -> bool:
    markers = record.get("synthetic_grounding_markers") or []
    return any(STALE_INTENT_MARKER_TOKEN in (m or "") for m in markers)


def _is_fallback_record(record: dict[str, Any]) -> bool:
    """True when the top-level intent itself carries a fallback marker.

    Per ``shared.director_intent.is_synthetic_grounding_marker`` the
    ``fallback.*`` and ``inferred.*`` prefixes both signal the path is a
    deterministic-code fallback rather than a real LLM-emitted intent.
    """

    markers = record.get("synthetic_grounding_markers") or []
    for marker in markers:
        token = (marker or "").strip().lower()
        if token.startswith(_FALLBACK_PREFIX) or token.startswith("inferred."):
            return True
    return False


def _impingement_has_real_grounding(impingement: dict[str, Any]) -> bool:
    """True when the impingement carries non-empty grounding_provenance."""

    real = impingement.get("grounding_provenance") or []
    return any((entry or "").strip() for entry in real)


def _impingement_is_synthetic_only(impingement: dict[str, Any]) -> bool:
    """True when the impingement has only synthetic_grounding_markers, no real."""

    if _impingement_has_real_grounding(impingement):
        return False
    synth = impingement.get("synthetic_grounding_markers") or []
    return any((entry or "").strip() for entry in synth)


def _record_grounding_uniformly_real(record: dict[str, Any]) -> bool:
    """All impingements on a record must carry real grounding for excellent.

    A single synthetic-only impingement disqualifies the record from the
    "excellent" tier. Records with no impingements at all are treated as
    not-uniformly-real (the no-vacuum invariant should have populated a
    silence-hold; if it didn't, the LLM emitted nothing groundable).
    """

    impingements = record.get("compositional_impingements") or []
    if not impingements:
        return False
    for imp in impingements:
        if not _impingement_has_real_grounding(imp):
            return False
        if _impingement_is_synthetic_only(imp):
            return False
    return True


def _record_distinct_families(record: dict[str, Any]) -> set[str]:
    """Return the set of intent_family values across the record's impingements."""

    out: set[str] = set()
    for imp in record.get("compositional_impingements") or []:
        family = imp.get("intent_family")
        if family:
            out.add(family)
    return out


def assess_director_moves_quality(
    intent_records: Iterable[dict[str, Any]],
) -> QualityRating:
    """Assess director-moves quality across a window of intent records.

    Returns ``QualityRating.UNMEASURED`` for an empty window — the segment
    did not produce any director output to score, which is its own outcome
    and should not be silently coerced to one of the four ranked tiers.

    Args:
        intent_records: Iterable of dict-shaped records as written by
            ``_emit_intent_artifacts`` to ``director-intent.jsonl``. Each
            record should have ``synthetic_grounding_markers``, optional
            ``compositional_impingements`` (each with ``grounding_provenance``,
            ``synthetic_grounding_markers``, ``intent_family``), and the
            usual director-intent fields.

    Returns:
        ``QualityRating.{POOR, ACCEPTABLE, GOOD, EXCELLENT, UNMEASURED}``.
    """

    records = list(intent_records)
    if not records:
        return QualityRating.UNMEASURED

    is_stale = [_is_stale_intent_record(rec) for rec in records]
    is_fallback = [_is_fallback_record(rec) for rec in records]

    if all(is_stale):
        return QualityRating.POOR

    if any(is_fallback):
        return QualityRating.ACCEPTABLE

    # No fallback markers at all in the window. Promote to EXCELLENT only
    # when every record's impingements have real grounding and the window
    # spans ≥2 distinct intent_family values (multi-surface composability
    # per the unified prompt's "Multi-Surface Moves" guidance).
    all_real_grounding = all(_record_grounding_uniformly_real(rec) for rec in records)

    families: set[str] = set()
    for rec in records:
        families.update(_record_distinct_families(rec))

    if all_real_grounding and len(families) >= 2:
        return QualityRating.EXCELLENT
    return QualityRating.GOOD
