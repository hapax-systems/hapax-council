"""Showrunner Segment + Beat primitives.

Plan A Phase A1 of the Gemini-reapproach content-programming epic.

Extends the existing ``shared/programme.py`` Programme layer with a
finer-grained ``Segment`` (sub-programme) and ``Beat`` (sub-segment)
primitive. A ``Programme`` spans minutes and carries capability bias
multipliers; a ``Segment`` spans seconds-to-minutes within a programme
and carries format + thesis + verbal-script guidance; a ``Beat``
spans a few seconds within a segment and carries narrative_goal +
screen-direction priors.

Architectural invariants pinned by Pydantic validators:

- ``segment_author`` is ``Literal["hapax"]`` — programmes are
  Hapax-authored (``feedback_hapax_authors_programmes``); segments
  inherit the same constraint.
- ``screen_directions_prior`` is a dict of capability-name →
  bias-multiplier (soft prior through AffordancePipeline). NEVER a
  direct dispatch (``programmes_enable_grounding``).
- ``capability_bias_positive`` multipliers live in [1.0, 5.0];
  ``capability_bias_negative`` in (0.0, 1.0]. Zero is a hard gate,
  architecturally forbidden.
- ``verbal_script`` is **guidance**, not mandatory. The director prompt
  that consumes it renders it as a soft prior preceded by "this is
  context for grounding, not a mandatory script."
- ``cadence_archetype`` is an optional Literal of the three cadence
  archetypes from the YouTuber research doc (see
  ``docs/superpowers/plans/2026-04-23-gemini-reapproach-plan-a-showrunner.md``
  §Phase A4). None = "no archetype hint, director picks freely."

This module is library-only. Phase A2 adds ``SegmentPlanner``; Phase A3
wires it into ``ProgrammeManager``. No runtime consumers exist at the
end of Phase A1 — the primitives are infrastructure waiting to be
invoked.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

CadenceArchetype = Literal[
    "clinical_pause",
    "freeze_frame_reaction",
    "percussive_glitch",
]
"""Three cadence archetypes salvaged from the delta-authored YouTuber
cadence research (commit da77cb43c's untracked-files blob, recovered
via git-reflog). Each archetype maps deterministically to a
preset-family-hint + homage-rotation-mode + beat-length range in
``shared/cadence_archetypes.py`` (shipped in Phase A4)."""


class Beat(BaseModel):
    """A few-second unit inside a Segment.

    Beats are consumed by ``ProgrammeManager`` during Segment activation
    (Phase A3): the active beat's ``screen_directions_prior`` is applied
    as capability-bias multipliers into the AffordancePipeline scorer,
    and the ``verbal_script`` is injected as GUIDANCE (not mandatory)
    into the director's unified prompt.
    """

    beat_id: str = Field(min_length=1, description="Stable identifier within a Segment.")

    narrative_goal: str = Field(
        min_length=1,
        description=(
            "One-sentence intent for this beat — what Hapax is trying to "
            "accomplish. Fed to the director as context, not quoted."
        ),
    )

    verbal_script: str = Field(
        default="",
        description=(
            "Soft guidance for the director's narration during this beat. "
            "Rendered into the unified prompt preceded by 'this is a prior "
            "for grounding, not a mandatory script'. May be empty — then "
            "no script hint is injected."
        ),
    )

    screen_directions_prior: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Capability-name → bias-multiplier. Each multiplier must be "
            "strictly positive; (0.0, 1.0] down-weights the capability, "
            "[1.0, 5.0] up-weights it. Composed with Programme's "
            "capability_bias_positive / capability_bias_negative in the "
            "affordance-pipeline scorer."
        ),
    )

    planned_duration_s: float = Field(gt=0.0, description="Target duration at normal pacing.")

    min_duration_s: float = Field(gt=0.0, description="Minimum duration before Beat can advance.")

    max_duration_s: float = Field(gt=0.0, description="Hard cap — Beat auto-advances at this.")

    cadence_archetype: CadenceArchetype | None = Field(
        default=None,
        description=(
            "Optional hint at which of the three cadence archetypes this "
            "beat favours. None = no hint (director picks freely)."
        ),
    )

    @field_validator("screen_directions_prior")
    @classmethod
    def _prior_multipliers_strictly_positive(cls, v: dict[str, float]) -> dict[str, float]:
        for name, mult in v.items():
            if not math.isfinite(mult) or mult <= 0.0:
                raise ValueError(
                    f"Beat.screen_directions_prior[{name!r}]={mult!r} — must be "
                    "strictly positive. Zero is architecturally forbidden "
                    "(hard gate); see feedback_no_expert_system_rules."
                )
            if mult > 5.0:
                raise ValueError(
                    f"Beat.screen_directions_prior[{name!r}]={mult!r} — "
                    "clamped to <= 5.0 to prevent saturation."
                )
        return v

    @model_validator(mode="after")
    def _duration_ordering(self) -> Beat:
        if not (self.min_duration_s <= self.planned_duration_s <= self.max_duration_s):
            raise ValueError(
                f"Beat.{self.beat_id}: duration ordering violated "
                f"(min={self.min_duration_s} planned={self.planned_duration_s} "
                f"max={self.max_duration_s}). Must satisfy "
                "min <= planned <= max."
            )
        return self


class Segment(BaseModel):
    """A seconds-to-minutes unit inside a Programme.

    Carries format + thesis (what kind of content this is + what it's
    about), plus a list of Beats that sequence the narrative arc. The
    segment itself can raise capability biases at its own scope, which
    compose with the parent Programme's biases and each active Beat's
    priors.
    """

    segment_id: str = Field(min_length=1)

    parent_programme_id: str = Field(
        min_length=1,
        description="The Programme this Segment activates inside.",
    )

    segment_author: Literal["hapax"] = Field(
        default="hapax",
        description=(
            "Pinned Literal — segments are Hapax-authored, never operator-"
            "written (memory: feedback_hapax_authors_programmes)."
        ),
    )

    format: str = Field(
        min_length=1,
        description=(
            "Named format (e.g. 'react-video', 'explainer', 'tier-list', "
            "'hothouse-freestyle'). Free-form at this layer; Segment"
            "Planner emits well-known tokens the catalog recognises."
        ),
    )

    thesis: str = Field(
        min_length=1,
        description=(
            "One-sentence argument the segment is making. Fed into the "
            "director as context; not quoted verbatim to the audience."
        ),
    )

    media_vectors: list[str] = Field(
        default_factory=list,
        description=(
            "Declared media dependencies (e.g. 'youtube-active', "
            "'vinyl-cover', 'operator-brio'). Read-only — the Segment-"
            "Planner populates this; runtime consumers use it to prefetch."
        ),
    )

    reusable: bool = Field(
        default=False,
        description=(
            "When True the segment's beats can be recycled into future "
            "Programmes (memory: stashed 'vinyl playing' / 'operator "
            "messing with gear' segments)."
        ),
    )

    beats: list[Beat] = Field(min_length=1, description="Non-empty sequence of beats.")

    capability_bias_positive: dict[str, float] = Field(default_factory=dict)
    capability_bias_negative: dict[str, float] = Field(default_factory=dict)

    @field_validator("capability_bias_positive")
    @classmethod
    def _positive_bias_in_band(cls, v: dict[str, float]) -> dict[str, float]:
        for name, mult in v.items():
            if not math.isfinite(mult) or mult < 1.0 or mult > 5.0:
                raise ValueError(
                    f"Segment.capability_bias_positive[{name!r}]={mult!r} — must be in [1.0, 5.0]."
                )
        return v

    @field_validator("capability_bias_negative")
    @classmethod
    def _negative_bias_in_band(cls, v: dict[str, float]) -> dict[str, float]:
        for name, mult in v.items():
            if not math.isfinite(mult) or mult <= 0.0 or mult > 1.0:
                raise ValueError(
                    f"Segment.capability_bias_negative[{name!r}]={mult!r} — "
                    "must be in (0.0, 1.0]. Zero is forbidden (hard gate)."
                )
        return v

    @field_validator("beats")
    @classmethod
    def _beat_ids_unique(cls, beats: list[Beat]) -> list[Beat]:
        seen: set[str] = set()
        for b in beats:
            if b.beat_id in seen:
                raise ValueError(
                    f"Segment.beats: duplicate beat_id {b.beat_id!r}. "
                    "Beat IDs must be unique within a segment."
                )
            seen.add(b.beat_id)
        return beats


class SegmentPlan(BaseModel):
    """The SegmentPlanner's emission — a list of Segments for a Programme.

    Phase A2 creates a planner that emits these; Phase A3 activates them
    in ``ProgrammeManager`` on programme boundary transitions. Until
    Phase A2 lands, this model is populated only in tests.
    """

    programme_id: str = Field(min_length=1)
    show_id: str = Field(min_length=1)
    planned_at: float = Field(gt=0.0, description="Unix timestamp (monotonic source).")
    plan_author: Literal["hapax-segment-planner"] = Field(default="hapax-segment-planner")
    segments: list[Segment] = Field(min_length=1)

    @field_validator("segments")
    @classmethod
    def _segment_ids_unique(cls, segs: list[Segment]) -> list[Segment]:
        seen: set[str] = set()
        for s in segs:
            if s.segment_id in seen:
                raise ValueError(f"SegmentPlan.segments: duplicate segment_id {s.segment_id!r}.")
            seen.add(s.segment_id)
        return segs

    @model_validator(mode="after")
    def _segments_share_parent_programme(self) -> SegmentPlan:
        for s in self.segments:
            if s.parent_programme_id != self.programme_id:
                raise ValueError(
                    f"SegmentPlan.segments[{s.segment_id!r}].parent_programme_id"
                    f"={s.parent_programme_id!r} != plan.programme_id="
                    f"{self.programme_id!r}. All segments in a plan must target "
                    "the same parent programme."
                )
        return self
