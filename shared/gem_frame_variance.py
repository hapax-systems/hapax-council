"""Rolling variance scorer for gem-frame texts.

The cc-task acceptance bar for outcome 1 (vocal) is:

    "TTS content varies (no repetition >2 within 10 utterances)"

Translating that to a quality rating that fits the
:class:`~shared.segment_observability.QualityRating` axis means
collapsing pairwise *similarity* across a window of frames into a
single mean similarity, then mapping the inverse to a rating:

    variance = 1 - mean(pairwise_similarity)

We score similarity with **character-bigram Jaccard distance** rather
than embedding cosine. Two reasons:

1. Tests run without LiteLLM / Qdrant / GPU; a pure-string scorer
   means the variance bar is reproducible offline.
2. The repetition mode the cc-task targets is *surface-level* —
   "Hapax keeps saying 'the doom of...' over and over". Character
   n-grams catch that more reliably than semantic embedding (which
   would happily call two paraphrases of the same sentence
   "different").

A future revision could swap in cosine over ``shared.config.embed``
for the semantic-paraphrase case; the public API
(:func:`score_variance`) keeps the swap transparent.

Rating thresholds — pinned by parametrized tests so changes are
explicit:

    EXCELLENT — variance > 0.7  (highly varied)
    GOOD      — variance in (0.5, 0.7]
    ACCEPTABLE — variance in (0.3, 0.5]
    POOR      — variance ≤ 0.3 OR fewer than 2 frames to compare
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from shared.segment_observability import QualityRating

log = logging.getLogger(__name__)

# Pinned by tests; see module docstring for rationale.
EXCELLENT_FLOOR: float = 0.7
GOOD_FLOOR: float = 0.5
ACCEPTABLE_FLOOR: float = 0.3

# Below this many frames, variance is undefined — we bias to POOR
# rather than UNMEASURED because "no emissions" is a real failure
# mode the operator should see, not invisible.
MIN_FRAMES_FOR_RATING: int = 2

_BIGRAM_PAD: str = "  "


@dataclass(frozen=True)
class VarianceReport:
    """Variance metrics + rating for a frame window."""

    rating: QualityRating
    variance: float
    mean_similarity: float
    n_frames: int
    n_unique: int
    note: str


def _bigrams(text: str) -> set[str]:
    """Return the character-bigram set for ``text``.

    Pads with two spaces front + back so single-character or empty
    inputs still produce a 2-element comparison surface (avoids the
    pairwise loop hitting an empty Jaccard).
    """
    padded = _BIGRAM_PAD + (text or "") + _BIGRAM_PAD
    if len(padded) < 2:
        return set()
    return {padded[i : i + 2] for i in range(len(padded) - 1)}


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    """Standard Jaccard similarity in [0.0, 1.0]; 1.0 on equal-empty.

    Two empty sets are *trivially equal*, which would mean POOR
    variance — reasonable when the inputs are both blank. The
    pre-filter in the scorer already drops blanks, so this branch is
    defense-in-depth.
    """
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = a & b
    union = a | b
    return len(inter) / len(union)


def _rate_variance(variance: float, n_frames: int) -> QualityRating:
    """Map a variance score to a :class:`QualityRating`."""
    if n_frames < MIN_FRAMES_FOR_RATING:
        return QualityRating.POOR
    if variance > EXCELLENT_FLOOR:
        return QualityRating.EXCELLENT
    if variance > GOOD_FLOOR:
        return QualityRating.GOOD
    if variance > ACCEPTABLE_FLOOR:
        return QualityRating.ACCEPTABLE
    return QualityRating.POOR


def score_variance(texts: Sequence[str]) -> VarianceReport:
    """Compute variance + rating over an ordered list of frame texts.

    Parameters
    ----------
    texts
        Ordered emission texts (most-recent last is conventional but
        not required — the metric is order-invariant).

    Returns
    -------
    VarianceReport
        ``rating`` is the operator-facing quality bucket; ``variance``,
        ``mean_similarity``, ``n_frames``, ``n_unique`` are the raw
        metrics the report leans on. ``note`` is a one-line operator
        summary suitable for ``SegmentEvent.quality.notes``.
    """
    cleaned = [t.strip() for t in texts if isinstance(t, str) and t.strip()]
    n = len(cleaned)
    n_unique = len(set(cleaned))

    if n < MIN_FRAMES_FOR_RATING:
        return VarianceReport(
            rating=QualityRating.POOR,
            variance=0.0,
            mean_similarity=1.0,
            n_frames=n,
            n_unique=n_unique,
            note=f"only {n} renderable frame(s) — too few to score variance",
        )

    bigram_sets = [_bigrams(t) for t in cleaned]
    pair_count = 0
    sim_sum = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            sim_sum += _jaccard_similarity(bigram_sets[i], bigram_sets[j])
            pair_count += 1
    mean_sim = sim_sum / pair_count if pair_count else 0.0
    variance = max(0.0, 1.0 - mean_sim)
    rating = _rate_variance(variance, n)

    note = (
        f"variance={variance:.3f} mean_similarity={mean_sim:.3f} n_frames={n} n_unique={n_unique}"
    )
    return VarianceReport(
        rating=rating,
        variance=variance,
        mean_similarity=mean_sim,
        n_frames=n,
        n_unique=n_unique,
        note=note,
    )


def _query_camera_salience_for_visual_variance() -> dict[str, Any] | None:
    """Query the broker for the variance projection's salience context.

    Mirrors the inline pattern used by ``director_loop`` and
    ``affordance_pipeline``. Fails closed (returns ``None``) so a
    broker outage never affects the variance score itself.
    """
    try:
        from shared.camera_salience_singleton import broker as _camera_broker

        bundle = _camera_broker().query(
            consumer="visual_variance",
            decision_context="gem_frame_variance_projection",
            candidate_action="score_recent_emissions",
        )
        if bundle is None:
            return None
        return bundle.to_wcs_projection_payload()
    except Exception:
        log.debug("camera salience visual_variance query failed", exc_info=True)
        return None


def project_variance_with_camera_salience(texts: Sequence[str]) -> dict[str, Any]:
    """Score variance and attach the camera-salience WCS projection.

    Returns a dict with two keys:

      * ``variance_report`` — the standard :class:`VarianceReport`.
      * ``camera_salience`` — broker WCS projection (``None`` when the
        broker is unavailable).

    The salience projection is *used* as the second key of the
    returned variance projection; downstream consumers (smoke harness,
    SegmentEvent emitter) can correlate variance bucket with which
    apertures were salient at score time.
    """
    report = score_variance(texts)
    salience = _query_camera_salience_for_visual_variance()
    return {"variance_report": report, "camera_salience": salience}


__all__ = [
    "ACCEPTABLE_FLOOR",
    "EXCELLENT_FLOOR",
    "GOOD_FLOOR",
    "MIN_FRAMES_FOR_RATING",
    "VarianceReport",
    "project_variance_with_camera_salience",
    "score_variance",
]
