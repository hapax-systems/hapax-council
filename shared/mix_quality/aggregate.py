"""MixQuality aggregate + sub-score types (Phase 0 skeleton).

Six independent sub-scores collapse to a single 0..1 ``mix_quality``
gauge via ``min()``. Pass band: ≥0.7 is operator-comfortable, 0.5–0.7
is warning territory, <0.5 recommends intervention or fallback to a
safe preset.

Why ``min()`` not weighted mean: the operator's invariant is "mix is
ALWAYS good", so ONE bad sub-score sinks the aggregate. Once we have
data on which sub-score predicts subjective "this sounds bad", we can
replace with a weighted geometric mean. v0 is conservative.

Sub-scores (all independent):

| Name | Gauge | Unit | Pass band |
|---|---|---|---|
| loudness | hapax_mix_loudness_lufs | LUFS | -16..-14 |
| source_balance | hapax_mix_source_balance | 0..1 | ≥0.7 |
| speech_clarity | hapax_mix_speech_clarity | 0..1 | ≥0.8 |
| intentionality | hapax_mix_intentionality_coverage | 0..1 | ≥0.95 |
| dynamic_range | hapax_mix_dynamic_range_db | dB | 7..14 |
| av_coherence | hapax_mix_av_coherence | 0..1 | ≥0.6 |

Phase 0 (this file): types + aggregate. Each sub-score's concrete
meter ships as a follow-up per design doc §6:

- Phase 1: loudness (pyloudnorm EBU R128)
- Phase 2: source_balance + speech_clarity
- Phase 3: intentionality (needs source-attribution registry)
- Phase 4: dynamic_range + av_coherence
- Phase 5: director_loop gating + Logos panel
- Phase 6: pre-live gate integration

Reference: docs/research/2026-04-20-mixquality-skeleton-design.md §3
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Pass bands — the design doc §2 table as constants. Consumers displaying
# the sub-score in the UI use these for the "green/yellow/red" colouring.
LOUDNESS_TARGET_LUFS: float = -15.0
LOUDNESS_TOLERANCE_LUFS: float = 1.0  # pass band ±tolerance around target
SOURCE_BALANCE_MIN: float = 0.7
SPEECH_CLARITY_MIN: float = 0.8
INTENTIONALITY_MIN: float = 0.95
DYNAMIC_RANGE_MIN_DB: float = 7.0
DYNAMIC_RANGE_MAX_DB: float = 14.0
AV_COHERENCE_MIN: float = 0.6

# Operator-warning thresholds on the aggregate.
AGGREGATE_WARNING_THRESHOLD: float = 0.7
AGGREGATE_INTERVENTION_THRESHOLD: float = 0.5


@dataclass(frozen=True)
class SubScore:
    """One of the six sub-scores plus its observability metadata.

    ``value=None`` means "meter not yet implemented / no data this
    tick" — the aggregate skips ``None`` scores so a partially-wired
    MixQuality still produces a valid aggregate (per design §4:
    'a partially-implemented set still produces a valid MixQuality').

    ``normalised`` is the 0..1 version the aggregate consumes — each
    meter translates its native unit (LUFS, dB, ratio) to this band.
    For meters already in 0..1, normalised == value.
    """

    name: str
    value: float | None = None
    normalised: float | None = None
    unit: str = ""
    pass_band: str = ""


@dataclass(frozen=True)
class MixQuality:
    """Snapshot of the six sub-scores + the aggregate at one tick.

    Consumers pattern-match on ``name`` to read individual sub-scores
    from ``.sub_scores``. Missing meters appear with ``value=None`` so
    UIs can show "—" rather than a spurious zero.
    """

    aggregate: float | None
    sub_scores: list[SubScore] = field(default_factory=list)
    window_s: float = 1.0

    def sub(self, name: str) -> SubScore | None:
        for s in self.sub_scores:
            if s.name == name:
                return s
        return None


def _loudness_to_band(lufs: float | None) -> float | None:
    """Map EBU R128 LUFS reading to a 0..1 pass-band score.

    Within tolerance → 1.0; beyond tolerance → linearly falls off to
    0.0 over a 6 dB span from the tolerance edge. 6 dB is "obviously
    too loud / too soft" by broadcast convention.
    """
    if lufs is None:
        return None
    offset = abs(lufs - LOUDNESS_TARGET_LUFS)
    if offset <= LOUDNESS_TOLERANCE_LUFS:
        return 1.0
    falloff_start = LOUDNESS_TOLERANCE_LUFS
    falloff_end = LOUDNESS_TOLERANCE_LUFS + 6.0
    if offset >= falloff_end:
        return 0.0
    return max(0.0, 1.0 - (offset - falloff_start) / (falloff_end - falloff_start))


def _dynamic_range_to_band(db: float | None) -> float | None:
    """Map peak-to-loudness dB to 0..1 score with a flat pass window.

    Below ``DYNAMIC_RANGE_MIN_DB`` = over-compressed (score approaches 0).
    Above ``DYNAMIC_RANGE_MAX_DB`` = too dynamic for broadcast (also
    approaches 0). Inside the window = 1.0. Linear falloff 6 dB either
    side (matches loudness falloff geometry).
    """
    if db is None:
        return None
    if DYNAMIC_RANGE_MIN_DB <= db <= DYNAMIC_RANGE_MAX_DB:
        return 1.0
    if db < DYNAMIC_RANGE_MIN_DB:
        offset = DYNAMIC_RANGE_MIN_DB - db
    else:
        offset = db - DYNAMIC_RANGE_MAX_DB
    falloff_span = 6.0
    return max(0.0, 1.0 - offset / falloff_span)


def _normalised_score(sub: SubScore) -> float | None:
    """Return the 0..1 form the aggregate consumes.

    For meters that output native units (LUFS, dB), we translate to
    0..1 here. For meters already in 0..1 (source_balance,
    speech_clarity, intentionality, av_coherence), the value passes
    through.
    """
    if sub.value is None:
        return None
    if sub.normalised is not None:
        return sub.normalised
    if sub.name == "loudness":
        return _loudness_to_band(sub.value)
    if sub.name == "dynamic_range":
        return _dynamic_range_to_band(sub.value)
    # Already-0..1 meters — clamp for robustness.
    return max(0.0, min(1.0, sub.value))


def aggregate_mix_quality(sub_scores: list[SubScore], *, window_s: float = 1.0) -> MixQuality:
    """Compose six sub-scores into one MixQuality snapshot.

    Skips ``value=None`` sub-scores so a partially-wired pipeline
    still returns a meaningful aggregate over whichever meters ARE
    live. Returns ``aggregate=None`` only when NO sub-scores have
    values (nothing to aggregate).
    """
    normalised: list[float] = []
    for sub in sub_scores:
        n = _normalised_score(sub)
        if n is not None:
            normalised.append(n)
    agg = min(normalised) if normalised else None
    return MixQuality(aggregate=agg, sub_scores=list(sub_scores), window_s=window_s)


def empty_mix_quality() -> MixQuality:
    """Skeleton with all six sub-scores at ``value=None``.

    Used by the publisher at startup before any meter has emitted.
    Consumers see ``aggregate=None`` and the six sub-score slots so
    they can render "—" in the UI.
    """
    return MixQuality(
        aggregate=None,
        sub_scores=[
            SubScore(name="loudness", unit="LUFS", pass_band="-16 to -14"),
            SubScore(name="source_balance", unit="0..1", pass_band="≥0.7"),
            SubScore(name="speech_clarity", unit="0..1", pass_band="≥0.8"),
            SubScore(name="intentionality", unit="0..1", pass_band="≥0.95"),
            SubScore(name="dynamic_range", unit="dB", pass_band="7..14"),
            SubScore(name="av_coherence", unit="0..1", pass_band="≥0.6"),
        ],
    )
