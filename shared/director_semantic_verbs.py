"""shared/director_semantic_verbs.py — Director vocabulary substrate (cc-task u5 Phase 0).

Audit underutilization U5: the director emits semantic verbs (e.g.,
``ascend``, ``linger``, ``rupture``) into its narration / action
artifacts, but no downstream actor maps those verbs to concrete
compositor / shader actions. The verbs are received but never
consumed — the director "talks to itself."

This Phase 0 ships the substrate that closes that loop:

  SEMANTIC_VERBS                       — the canonical 10-verb vocabulary
  VerbAction                           — frozen dataclass per-verb action descriptor
  SEMANTIC_VERB_ACTIONS                — verb → VerbAction registry
  registered_verbs() / consumer_for()  — accessor pair for downstream actors
  no_orphan_verbs()                    — invariant the regression test pins

The Phase 0 actions are intentionally lightweight (a ``hint``
dict that downstream consumers can interpret at their own scale —
preset-family bias, shader uniform target, slot-rotator nudge). Phase 1
cc-tasks wire each verb's hint into a concrete consumer + a Prometheus
counter (``hapax_semantic_verb_consumed_total{verb=..., outcome=...}``).

Vocabulary rationale (10 verbs across 5 axes):
  - **temporal**: ascend (intensify), linger (dwell), accelerate (cycle faster)
  - **spatial**: gather (focus center), disperse (peripheral spread)
  - **phenomenological**: dwell (extend duration), rupture (sudden break)
  - **chromatic**: warm (palette shift toward Gruvbox-warm), cool (toward Solarized)
  - **structural**: align (snap to grid), drift (loosen alignment)

This 10-verb floor matches the cc-task acceptance criterion ("≥6 verbs
must have non-zero dispatch in a 10-min sample") with margin so a
director that only fires 6 distinct verbs in a window still has
coverage to spare.

Phase 1 (separate cc-tasks):
  * ``u5-semantic-verb-prometheus-counter`` — wire
    ``hapax_semantic_verb_consumed_total`` increment in
    ``preset_recruitment_consumer`` (or wherever the canonical chain
    mutator lands)
  * ``u5-verb-to-shader-uniform`` — concrete WGSL Params target per
    verb (e.g., ``rupture`` → temporal_distortion += 0.4 for 1 tick)
  * ``u5-verb-to-preset-family-bias`` — combine with
    ``shared.visual_mode_bias.PRESET_FAMILY_WEIGHTS`` so a director
    verb adjusts the per-mode bias for one tick
  * ``u5-livestream-evidence`` — operator-side 10-min sample showing
    ≥6 verbs dispatched
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

VerbAxis = Literal["temporal", "spatial", "phenomenological", "chromatic", "structural"]


@dataclass(frozen=True)
class VerbAction:
    """Per-verb action descriptor consumers interpret at their own scale.

    Phase 0 carries the verb's semantic axis + a free-form ``hint`` dict
    that documents what the action SHOULD do once Phase 1 wires its
    consumer. The hint is read by tests + tooling; consumers wire to
    the verb name + the dataclass directly.
    """

    verb: str
    axis: VerbAxis
    description: str
    hint: dict[str, object] = field(default_factory=dict)


SEMANTIC_VERB_ACTIONS: dict[str, VerbAction] = {
    "ascend": VerbAction(
        verb="ascend",
        axis="temporal",
        description="Intensify the current expressive register — push energy up",
        hint={
            "preset_family_weight_delta": {"fx.family.audio-reactive": +0.3},
            "shader_uniform_target": {"intensity": "+0.2"},
            "duration_ticks": 8,
        },
    ),
    "linger": VerbAction(
        verb="linger",
        axis="temporal",
        description="Dwell on the current moment — slow temporal cycling",
        hint={
            "motion_factor_multiplier": 0.5,
            "duration_ticks": 12,
        },
    ),
    "accelerate": VerbAction(
        verb="accelerate",
        axis="temporal",
        description="Cycle faster — shorten dwell, speed slot rotation",
        hint={
            "motion_factor_multiplier": 1.5,
            "slot_rotation_period_factor": 0.7,
            "duration_ticks": 6,
        },
    ),
    "gather": VerbAction(
        verb="gather",
        axis="spatial",
        description="Pull attention toward the center — collapse peripheral content",
        hint={
            "shader_uniform_target": {"feedback": "+0.15"},
            "duration_ticks": 4,
        },
    ),
    "disperse": VerbAction(
        verb="disperse",
        axis="spatial",
        description="Spread to peripheral regions — widen the visual field",
        hint={
            "shader_uniform_target": {"diffusion": "+0.25"},
            "duration_ticks": 6,
        },
    ),
    "dwell": VerbAction(
        verb="dwell",
        axis="phenomenological",
        description="Extend the present-moment duration — resist transition",
        hint={
            "transition_cooldown_factor": 1.5,
            "duration_ticks": 10,
        },
    ),
    "rupture": VerbAction(
        verb="rupture",
        axis="phenomenological",
        description="Sudden discontinuity — break the current register",
        hint={
            "shader_uniform_target": {"temporal_distortion": "+0.4"},
            "duration_ticks": 1,
            "force_preset_swap": True,
        },
    ),
    "warm": VerbAction(
        verb="warm",
        axis="chromatic",
        description="Shift palette toward warm Gruvbox tones",
        hint={
            "palette_bias": "warm",
            "duration_ticks": 8,
        },
    ),
    "cool": VerbAction(
        verb="cool",
        axis="chromatic",
        description="Shift palette toward cool Solarized tones",
        hint={
            "palette_bias": "cool",
            "duration_ticks": 8,
        },
    ),
    "align": VerbAction(
        verb="align",
        axis="structural",
        description="Snap visual elements to the underlying grid — tighten coherence",
        hint={
            "shader_uniform_target": {"coherence": "+0.2"},
            "duration_ticks": 6,
        },
    ),
    "drift": VerbAction(
        verb="drift",
        axis="structural",
        description="Loosen alignment — let elements wander from the grid",
        hint={
            "shader_uniform_target": {"coherence": "-0.2"},
            "duration_ticks": 8,
        },
    ),
}

# The verb vocabulary, sorted for deterministic iteration. Used by the
# tests' no-orphan-verbs invariant + by tooling that needs to enumerate
# the canonical set without instantiating actions.
SEMANTIC_VERBS: tuple[str, ...] = tuple(sorted(SEMANTIC_VERB_ACTIONS.keys()))


def registered_verbs() -> tuple[str, ...]:
    """Return the canonical verb vocabulary, sorted."""
    return SEMANTIC_VERBS


def consumer_for(verb: str) -> VerbAction | None:
    """Look up the action descriptor for a verb. Returns None if unknown."""
    return SEMANTIC_VERB_ACTIONS.get(verb)


def no_orphan_verbs() -> tuple[str, ...]:
    """Return any verb in SEMANTIC_VERBS that lacks an action entry.

    Always returns an empty tuple in Phase 0 by construction (the
    vocabulary is derived from the action dict's keys), but the
    function is the explicit invariant the regression test pins so
    that a Phase 1 vocabulary expansion that adds a verb to
    SEMANTIC_VERBS without registering its action is caught at CI.
    """
    return tuple(v for v in SEMANTIC_VERBS if v not in SEMANTIC_VERB_ACTIONS)
