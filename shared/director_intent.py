"""Director intent schema — what the studio-compositor director emits per tick.

The director's role is the livestream's meta-structure communication device
(memory `feedback_director_grounding.md`). Its output is structured intent,
not capability invocations: a declared activity + stance + narrative utterance
+ compositional impingements. The impingements go through AffordancePipeline;
capabilities recruit from there. This keeps unified-semantic-recruitment
intact (no bypass paths — spec
`docs/superpowers/specs/2026-04-02-unified-semantic-recruitment-design.md`).

Epic: volitional grounded director (PR #1017, spec
`docs/superpowers/specs/2026-04-17-volitional-grounded-director-design.md`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from shared.stimmung import Stance

# ── Vocabulary ────────────────────────────────────────────────────────────

# HSEA Phase 2 activity extension (6 → 13 → 14). The six original activities
# come from the compositor's ``ACTIVITY_CAPABILITIES``; HSEA Phase 2 added
# seven (``docs/superpowers/specs/2026-04-15-hsea-phase-2-core-director-activities-design.md``).
# Epic 2 (2026-04-17) added ``music`` as the vinyl-decoupled music-featuring
# activity: ``vinyl`` is retained as an alias so prior runs' artifacts stay
# valid, but new prompts guide the LLM to emit ``music`` so the director
# talks about music whether or not the turntable is active.
ActivityVocabulary = Literal[
    "react",
    "chat",
    "vinyl",
    "music",
    "study",
    "observe",
    "silence",
    "draft",
    "reflect",
    "critique",
    "patch",
    "compose_drop",
    "synthesize",
    "exemplar_review",
]

# Tag families the AffordancePipeline knows how to recruit against. Each
# family corresponds to a compositional affordance catalog introduced in
# spec §3.3. Widening this literal requires updating the catalog seed
# script (`scripts/seed-compositional-affordances.py`).
#
# The ``ward.*`` families are the ward-property-management surface
# (memory ``reference_wards_taxonomy.md``): per-ward modulation of size,
# position, staging, highlighting, appearance, cadence, and multi-ward
# choreography. Dispatch lives in ``compositional_consumer.dispatch_ward_*``
# and writes to ``/dev/shm/hapax-compositor/ward-properties.json`` and
# ``/dev/shm/hapax-compositor/ward-animation-state.json``.
IntentFamily = Literal[
    "camera.hero",
    "preset.bias",
    "overlay.emphasis",
    "youtube.direction",
    "attention.winner",
    "stream_mode.transition",
    "ward.size",
    "ward.position",
    "ward.staging",
    "ward.highlight",
    "ward.appearance",
    "ward.cadence",
    "ward.choreography",
    # HOMAGE framework families (spec §4.11). Each member maps to a
    # package-specific transition recruited via the choreographer
    # (``agents.studio_compositor.homage.choreographer``). Dispatch
    # writes into ``/dev/shm/hapax-compositor/homage-pending-transitions.json``;
    # the choreographer reconciles against package concurrency rules on
    # the next tick.
    "homage.rotation",
    "homage.emergence",
    "homage.swap",
    "homage.cycle",
    "homage.recede",
    "homage.expand",
]

# Imagination-fragment material taxonomy (matches
# `shared/imagination.py::Material`). Re-declared here as a Literal to
# avoid an import cycle; keep values aligned.
CompositionalMaterial = Literal["water", "fire", "earth", "air", "void"]


# ── Models ────────────────────────────────────────────────────────────────


class CompositionalImpingement(BaseModel):
    """A narrative-bearing impingement the AffordancePipeline recruits against.

    Shape matches the existing `ImaginationFragment` contract (narrative,
    dimensions, material, salience) plus a tag family that lets the
    pipeline target the correct capability catalog.
    """

    narrative: str = Field(
        ...,
        min_length=1,
        description=(
            "Text the pipeline embeds and cosine-matches against the "
            "Qdrant affordances collection. Gibson-verb style."
        ),
    )
    dimensions: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Imagination-fragment 9-dim envelope (intensity, tension, "
            "depth, coherence, spectral_color, temporal_distortion, "
            "degradation, pitch_displacement, diffusion). Missing keys "
            "default to 0.0 at the pipeline."
        ),
    )
    material: CompositionalMaterial = Field(
        default="water",
        description="Imagination material enum — shapes the recruited capability's interaction style.",
    )
    salience: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Weight the pipeline applies during scoring.",
    )
    grounding_provenance: list[str] = Field(
        default_factory=list,
        description=(
            "Per-impingement perceptual-field keys this move grounds in. "
            "PR #1046 made compositional intent mandatory and required "
            "grounding_provenance per impingement, but the field was only "
            "on the envelope. Now first-class per impingement so the LLM "
            "can comply: e.g., a preset.bias impingement cites "
            "['audio.midi.beat_position'], a camera.hero cites "
            "['ir.ir_hand_zone.turntable']. Empty list is allowed (the "
            "pipeline accepts it) but the audit emits an UNGROUNDED "
            "warning for the operator to track in research-mode logs."
        ),
    )
    intent_family: IntentFamily = Field(
        ...,
        description="Tag family the pipeline's catalog routes to.",
    )

    @field_validator("narrative")
    @classmethod
    def _strip_narrative(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("narrative must be non-empty after strip")
        return stripped


class DirectorIntent(BaseModel):
    """One directorial move — what the narrative director emits per tick.

    The fields split into three groups:

    - *What Hapax senses* (`grounding_provenance`) — the PerceptualField
      signal names this move grounds in. Empty list is allowed (the
      pipeline accepts ungrounded fallback) but warrants inspection in
      the research log.
    - *What Hapax is doing* (`activity`, `stance`, `narrative_text`) —
      the legible, LLM-authored output. Posture vocabulary is explicitly
      excluded from narrative_text (hygiene enforced by tests).
    - *What compositional intent Hapax expresses* (`compositional_impingements`) —
      the recruitment-bound moves. **Every tick MUST emit at least one**
      (operator invariant, 2026-04-18: "there is no justifiable context
      where 'do nothing interesting' is acceptable"). If the LLM returned
      no impingements, the parser / micromove fallback is responsible for
      populating one before DirectorIntent construction.
    """

    grounding_provenance: list[str] = Field(
        default_factory=list,
        description=(
            "PerceptualField signal names this move grounds in. Examples: "
            "'audio.contact_mic.desk_activity.drumming', "
            "'visual.overhead_hand_zones.turntable', "
            "'ir.ir_hand_zone.turntable', 'album.artist'."
        ),
    )
    activity: ActivityVocabulary = Field(
        ...,
        description="HSEA Phase 2 activity label (13-label vocabulary).",
    )
    stance: Stance = Field(
        ...,
        description="System-wide self-assessment per shared.stimmung.Stance.",
    )
    narrative_text: str = Field(
        ...,
        description=(
            "Operator-hearing utterance. Subject to axiom `executive_function` "
            "`ex-prose-001` (no rhetorical pivots / performative insight / "
            "dramatic restatement) and `management_governance` "
            "`mg-drafting-visibility-001` (no feedback language about individuals)."
        ),
    )
    compositional_impingements: list[CompositionalImpingement] = Field(
        ...,
        min_length=1,
        description=(
            "Impingements the AffordancePipeline will recruit against. "
            "At least one is required per tick (operator invariant 2026-04-18). "
            "Parser-error / silence paths must populate a silence-hold micromove "
            "before constructing DirectorIntent."
        ),
    )

    def model_dump_for_jsonl(self) -> dict:
        """Serialization used by the research-observability JSONL writer.

        Uses `mode='json'` so Stance is serialized as its string value.
        """
        return self.model_dump(mode="json")
