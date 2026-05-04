"""Director-moves quality assessment for segment observability.

Cc-task ``director-moves-segment-smoke`` (PR #2477) shipped the first cut.
Cc-task ``director-moves-grounding-trace-coverage`` (this PR) refines the
thresholds to the operator's ratio-based grading so a long observation
window can score on coverage rather than presence/absence:

- **excellent** — 0% fallback markers; every record in the window grounds
  in real perceptual evidence and the per-impingement grounding is
  uniformly real (every impingement carries non-empty
  ``grounding_provenance`` AND no ``synthetic_grounding_markers``).
- **good** — fallback ratio < 10%; LLM compliance is high but the window
  carries some inferred / fallback markers OR the impingement-level
  grounding is mixed real / synthetic.
- **acceptable** — fallback ratio < 30%; the LLM is producing real intents
  most ticks but the deterministic fallback is firing more than once in ten.
- **poor** — fallback ratio ≥ 30% OR the stale-intent micromove dominates
  the fallback set (≥ 50% of the records are stale_intent specifically).
  Either signal means the surface has effectively run on autopilot for
  the window — a Grafana panel watching the
  ``hapax_director_move_grounding_total`` counter would see the same
  pattern.

The four tiers are computed deterministically from the JSONL records the
director already writes via ``_emit_intent_artifacts``; this module does
not need to look at the live director loop or run any LLM call. That keeps
the smoke test infrastructure-free.

Tier transitions favour the higher-impact rating: a window that satisfies
both "≥ 30% fallback" AND "stale_intent dominant" is reported as POOR
once. UNMEASURED is reserved for windows that emitted nothing, which is
its own outcome and should not be silently coerced into a ranked tier.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from shared.segment_observability import QualityRating

__all__ = [
    "assess_director_moves_quality",
    "STALE_INTENT_MARKER_TOKEN",
    "FALLBACK_RATIO_GOOD_MAX",
    "FALLBACK_RATIO_ACCEPTABLE_MAX",
    "STALE_INTENT_DOMINANCE_MIN",
]


# Substring that flags a record as a stale-intent micromove fallback. The
# director writes synthetic markers like ``"fallback.micromove.stale_intent"``
# (and other ``fallback.micromove.<reason>`` tokens) on the silence-hold /
# micromove paths. We match on the substring so any future fallback reason
# under the ``fallback.`` prefix still counts as a fallback.
STALE_INTENT_MARKER_TOKEN: str = "stale_intent"
_FALLBACK_PREFIX: str = "fallback."

# Ratio thresholds (cc-task ``director-moves-grounding-trace-coverage``).
# Strict less-than: a fallback rate that exactly hits the threshold falls
# to the next-lower tier. The boundaries are deliberately tight because the
# director already writes one record per tick and the operator wants the
# surface to feel actively driven, not autopiloted.
FALLBACK_RATIO_GOOD_MAX: float = 0.10
FALLBACK_RATIO_ACCEPTABLE_MAX: float = 0.30

# When stale_intent records reach this fraction of the window, the segment
# is poor regardless of the overall fallback ratio. The director's
# ``_maybe_emit_stale_intent_micromove`` fires every 15s without an LLM
# tick, so a window dominated by stale_intent is the surface running on
# autopilot — the operator's "frequently empty grounding_provenance" tier.
STALE_INTENT_DOMINANCE_MIN: float = 0.50


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


def _impingement_uniformly_real(impingement: dict[str, Any]) -> bool:
    """True when the impingement has real grounding AND no synthetic markers.

    EXCELLENT requires uniform purity at the impingement level — a record
    whose top-level grounding is real but whose impingement still carries
    a synthetic marker is GOOD, not EXCELLENT.
    """

    if not _impingement_has_real_grounding(impingement):
        return False
    synth = impingement.get("synthetic_grounding_markers") or []
    return not any((entry or "").strip() for entry in synth)


def _record_grounding_uniformly_real(record: dict[str, Any]) -> bool:
    """All impingements on a record must carry real grounding for EXCELLENT.

    A single synthetic-only impingement disqualifies the record from
    ``excellent``. Records with no impingements at all are treated as
    not-uniformly-real (the no-vacuum invariant should have populated a
    silence-hold; if it didn't, the LLM emitted nothing groundable).
    """

    impingements = record.get("compositional_impingements") or []
    if not impingements:
        return False
    return all(_impingement_uniformly_real(imp) for imp in impingements)


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
    total = len(records)
    if total == 0:
        return QualityRating.UNMEASURED

    fallback_count = sum(1 for rec in records if _is_fallback_record(rec))
    stale_count = sum(1 for rec in records if _is_stale_intent_record(rec))

    fallback_ratio = fallback_count / total
    stale_ratio = stale_count / total

    if fallback_ratio >= FALLBACK_RATIO_ACCEPTABLE_MAX or stale_ratio >= STALE_INTENT_DOMINANCE_MIN:
        return QualityRating.POOR

    if fallback_count == 0:
        # Promote to EXCELLENT only when every record's impingements are
        # uniformly real-grounded. Anything less is GOOD — the LLM is
        # complying but the per-impingement grounding still has gaps.
        if all(_record_grounding_uniformly_real(rec) for rec in records):
            return QualityRating.EXCELLENT
        return QualityRating.GOOD

    if fallback_ratio < FALLBACK_RATIO_GOOD_MAX:
        return QualityRating.GOOD

    return QualityRating.ACCEPTABLE
