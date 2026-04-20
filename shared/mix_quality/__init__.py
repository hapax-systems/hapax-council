"""MixQuality — the operator's "mix is ALWAYS good" invariant as a 0..1 gauge.

Skeleton implementation of ``docs/research/2026-04-20-mixquality-skeleton-
design.md``. Phase 0 (this module) ships the types + the aggregate formula;
each sub-score is a follow-up commit per the plan's §6 phased rollout.

Public surface:

- ``MixQuality`` — dataclass holding six sub-scores + aggregate
- ``SubScore`` — optional value + observability fields (name, band)
- ``aggregate_mix_quality(scores)`` — the min() formula from design §3

Consumers:

- ``structural_director`` biases ``audio.*`` recruitments on low mix quality
- Logos surface displays the six-panel mix-health UI
- Pre-live gate blocks go-live on sustained MixQuality < 0.7
- Cascade §13 reads ``av_coherence`` for cross-surface audit

Zone: delta (audio/DSP). Lives in ``shared/`` rather than
``agents/studio_compositor/`` so the compositor, director, and
pre-live gate all import from one canonical place.

Reference:
    - docs/research/2026-04-20-mixquality-skeleton-design.md
"""

from shared.mix_quality.aggregate import (
    MixQuality,
    SubScore,
    aggregate_mix_quality,
)

__all__ = ["MixQuality", "SubScore", "aggregate_mix_quality"]
