"""Director intent schema — what the studio-compositor director emits per tick.

The director's role is the livestream's meta-structure communication device
(memory `feedback_director_grounding.md`). Its output is structured intent,
not capability invocations: a declared activity + stance + narrative utterance
+ compositional impingements + per-tick structural intent. The impingements
go through AffordancePipeline; capabilities recruit from there. The structural
intent drives the ward-property surface directly (rotation mode, per-ward
emphasis / dispatch / retire / placement-bias) so the director visibly shapes
the livestream surface every tick without waiting for the slow (90s) structural
tier. This keeps unified-semantic-recruitment intact (no bypass paths — spec
`docs/superpowers/specs/2026-04-02-unified-semantic-recruitment-design.md`).

Epic: volitional grounded director (PR #1017, spec
`docs/superpowers/specs/2026-04-17-volitional-grounded-director-design.md`).
Homage-surface activation (2026-04-18, cascade-delta): `NarrativeStructuralIntent`
lets the fast narrative tier drive ward-level rotation / emphasis / dispatch /
placement every tick so the homage surface becomes aesthetically active —
spec §4.13 + operator directive "unavoidable evidence of active thoughtful
manipulation".
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

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
    # GEM (Graffiti Emphasis Mural) ward authoring. Producer at
    # agents/hapax_daimonion/gem_producer.py tails the impingement bus
    # and renders CP437 keyframes to /dev/shm/hapax-gem/gem-frames.json
    # on any gem.* impingement. The compositor recruitment consumer also
    # writes recruited GEM frames there when an affordance lands, keeping
    # the surface dynamic without turning it into a cue/layout command
    # channel. Plan:
    # docs/superpowers/plans/2026-04-21-gem-ward-activation-plan.md
    # §1 Phase 3 was registered as affordances (commit 18944c10e1e0)
    # but never reached this Literal. Adding them here closes the
    # gap end-to-end.
    "gem.emphasis",
    "gem.composition",
    # gem.spawn (cc-task `director-moves-richness-expansion`): a fresh
    # GEM keyframe spawn distinct from emphasis/composition — the move
    # when the surface should mint a new graffiti rather than modulate
    # an existing mural. Used by the director when a beat or phrase
    # warrants its own mark on the lower band.
    "gem.spawn",
    # Director micromove vocabulary expansion (cc-task
    # `director-moves-richness-expansion`, operator outcome 3 of 5).
    # Operator constraint: NO presets — these families are parametric
    # modulation + chain composition. The director never picks a preset
    # family; instead it modulates parameters or composes transitions.
    #
    # transition.fade / transition.cut: chain-composition transitions
    # already implemented as ``transition.fade.smooth`` /
    # ``transition.cut.hard`` capabilities — see
    # ``shared/compositional_affordances.py`` ``_TRANSITION``. The
    # director emits the family tag, recruitment picks the variant.
    "transition.fade",
    "transition.cut",
    # composition.reframe: parametric reframe of the active hero
    # camera's crop/zoom — not a camera swap (camera.hero) and not a
    # preset (operator forbids). Modulates ``ward-properties.json``'s
    # camera-tile scale + position_offset envelope so the same camera
    # is reframed in place.
    "composition.reframe",
    # pace.tempo_shift: parametric shift of the surface's effective
    # cadence — slows or accelerates ward emphasis, transition timing,
    # narrative ticks. Writes to
    # ``/dev/shm/hapax-compositor/pace-state.json`` so cadence-aware
    # consumers (homage choreographer, ward animation) can pick up the
    # multiplier.
    "pace.tempo_shift",
    # mood.tone_pivot: parametric color/warmth/saturation pivot. NOT a
    # preset family selection — modulates the per-pass uniforms (color
    # warmth, saturation, brightness) directly via
    # ``/dev/shm/hapax-imagination/uniforms.json`` overrides. The
    # generative substrate keeps running; only the parametric color
    # envelope shifts.
    "mood.tone_pivot",
    # programme.beat_advance: signals the active programme's narrative
    # beat should advance. Consumer is the programme manager —
    # advancing a beat is structural content programming, not visual
    # composition. The director recognises when the current programme
    # has played out and emits this family to mark the boundary.
    "programme.beat_advance",
    # Director parametric vocabulary expansion tranche 2. Operator
    # constraint remains: NO presets. These families recruit bounded
    # parametric envelopes only; consumers ease surface/node parameters
    # within authored bounds rather than selecting preset families.
    #
    # intensity.surge: temporary lift across all nine visual-chain
    # dimensions with bounded Reverie node-param targets.
    "intensity.surge",
    # silence.invitation: quiets narration/motion/chrome/visual-chain
    # surfaces into a low-activity hold while the frame remains directed.
    "silence.invitation",
    # chrome.density: sparser / denser ward chrome density envelope.
    "chrome.density",
    # attention.refocus: soft camera-weight rebalancing without a hard
    # camera.hero swap.
    "attention.refocus",
    # YouTube viewer-telemetry impingements (ytb-005). Emitted by
    # ``agents.youtube_telemetry`` from Analytics + Reporting APIs at a
    # 3-min cadence (under the 500-req/day soft cap). Salience is a
    # function of deviation from a 24h rolling-median baseline; the
    # AffordancePipeline cosine-matches the narrative against the
    # affordances catalog and may or may not recruit. No dispatcher in
    # ``compositional_consumer`` — telemetry is environmental stimulus,
    # not a direct action.
    "youtube.telemetry",
]

# Imagination-fragment material taxonomy (matches
# `shared/imagination.py::Material`). Re-declared here as a Literal to
# avoid an import cycle; keep values aligned.
CompositionalMaterial = Literal["water", "fire", "earth", "air", "void"]

SYNTHETIC_GROUNDING_PREFIXES = ("inferred.", "fallback.")


def is_synthetic_grounding_marker(value: str) -> bool:
    """True for provenance-like markers that are diagnostics, not evidence."""
    if not isinstance(value, str):
        return False
    marker = value.strip()
    if not marker:
        return False
    lowered = marker.lower()
    normalized = lowered.replace("_", "-")
    return (
        lowered.startswith(SYNTHETIC_GROUNDING_PREFIXES)
        or normalized in {"parser-error", "silence-hold"}
        or normalized.startswith("parser-error.")
        or normalized.startswith("silence-hold.")
    )


def split_grounding_provenance(entries: list[str]) -> tuple[list[str], list[str]]:
    """Split real evidence refs from diagnostic grounding placeholders."""
    real: list[str] = []
    synthetic: list[str] = []
    for entry in entries:
        if not isinstance(entry, str):
            continue
        cleaned = entry.strip()
        if not cleaned:
            continue
        if is_synthetic_grounding_marker(cleaned):
            synthetic.append(cleaned)
        else:
            real.append(cleaned)
    return real, synthetic


def _dedupe_preserve_order(entries: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for entry in entries:
        if entry in seen:
            continue
        seen.add(entry)
        out.append(entry)
    return out


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
            "warning for the operator to track in research-mode logs. "
            "Synthetic diagnostics such as inferred.* and fallback.* are "
            "migrated to synthetic_grounding_markers and must not satisfy "
            "public/WCS/recruitment grounding gates."
        ),
    )
    synthetic_grounding_markers: list[str] = Field(
        default_factory=list,
        description=(
            "Diagnostic placeholders for missing real grounding, e.g. "
            "inferred.<stance>.<family>, fallback.<reason>, parser-error, "
            "or silence-hold. These markers keep LLM/fallback compliance "
            "observable but are not evidence and must not satisfy public "
            "claim, WCS, or recruitment audit success."
        ),
    )
    intent_family: IntentFamily = Field(
        ...,
        description="Tag family the pipeline's catalog routes to.",
    )
    diagnostic: bool = Field(
        default=False,
        description=(
            "Marks an impingement whose narrative is internal routing / "
            "governance text that must not reach viewer-facing surfaces. "
            "Set by deterministic-code fallbacks (silence_hold, parser "
            "errors). On-screen consumers that render impingement "
            "narrative (e.g. ActivityHeader gloss) MUST skip diagnostic "
            "entries. The AffordancePipeline still recruits against them "
            "— the flag is purely a 'show-don't-tell' fence for legibility "
            "surfaces, not a recruitment gate."
        ),
    )

    @field_validator("narrative")
    @classmethod
    def _strip_narrative(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("narrative must be non-empty after strip")
        return stripped

    @model_validator(mode="after")
    def _separate_synthetic_grounding(self) -> CompositionalImpingement:
        real, moved_synthetic = split_grounding_provenance(self.grounding_provenance)
        misplaced_real, explicit_synthetic = split_grounding_provenance(
            self.synthetic_grounding_markers
        )
        self.grounding_provenance = _dedupe_preserve_order(real + misplaced_real)
        self.synthetic_grounding_markers = _dedupe_preserve_order(
            moved_synthetic + explicit_synthetic
        )
        return self

    @property
    def has_real_grounding_provenance(self) -> bool:
        return bool(self.grounding_provenance)


# Per-tick rotation strategy the narrative director chooses to drive the
# homage choreographer. Matches
# ``agents.studio_compositor.structural_director.HomageRotationMode``;
# re-declared here to avoid the compositor → shared import cycle.
NarrativeHomageRotationMode = Literal[
    "sequential",
    "random",
    "weighted_by_salience",
    "paused",
]


# Canonical ward-id set the narrative director may target. Widening this
# literal requires updating the ward_registry + ward-property consumer.
# Limited to the 18 legible wards on the surface (chat_ambient_ward,
# activity_header, stance_indicator, grounding_provenance_ticker,
# impingement_cascade, recruitment_candidate_panel, thinking_indicator,
# pressure_gauge, activity_variety_log, whos_here, token_pole, album,
# sierpinski, hardm_dot_matrix, stream_overlay, captions_source,
# research_marker_overlay, hothouse_keyword_legend) so a typo in the LLM
# output collapses to an empty emphasis list rather than writing a stray
# ward-properties entry.
WardId = Literal[
    "chat_ambient",
    "activity_header",
    "stance_indicator",
    "grounding_provenance_ticker",
    "impingement_cascade",
    "recruitment_candidate_panel",
    "thinking_indicator",
    "pressure_gauge",
    "activity_variety_log",
    "whos_here",
    "token_pole",
    "album_overlay",
    "sierpinski",
    "hardm_dot_matrix",
    "stream_overlay",
    "captions",
    "research_marker_overlay",
    "chat_keyword_legend",
    "vinyl_platter",
    "overlay_zones",
]


# Placement-hint vocabulary a narrative structural-intent entry may attach
# to a ward_id. Each hint is translated by the compositional consumer into
# a ``WardProperties`` field: ``drift_*`` / ``position_offset_*`` / ``scale``.
# Unknown hints are dropped silently (fail-open; the empty string survives
# as the default no-op).
WardPlacementHint = Literal[
    "none",
    "drift_left",
    "drift_right",
    "drift_up",
    "drift_down",
    "pulse_center",
    "scale_0.8x",
    "scale_1.0x",
    "scale_1.15x",
    "scale_1.3x",
]


class NarrativeStructuralIntent(BaseModel):
    """Per-tick structural intent the narrative director declares.

    Distinct from the slow (90s) ``structural_director.StructuralIntent``:
    the narrative tier runs every ``HAPAX_NARRATIVE_CADENCE_S`` (default
    30s) and can therefore make the homage surface visibly active on a
    much tighter loop. Consumers:

    1. The ward-property manager reads ``ward_emphasis`` and bumps
       ``glow_radius_px``, ``alpha``, ``scale_bump_pct``, and
       ``border_pulse_hz`` on each listed ward for a short window
       (default ~4s decay).
    2. The choreographer's pending-transitions queue receives
       ``homage.emergence`` entries for ``ward_dispatch`` and
       ``homage.recede`` entries for ``ward_retire``.
    3. ``placement_bias`` maps per-ward position hints into the ward's
       ``drift_*`` / ``scale`` overrides.
    4. ``homage_rotation_mode`` flows through to the choreographer as an
       every-tick override of the structural director's slower mode.

    Missing fields default to empty / ``"sequential"`` so legacy parser
    output (LLMs that don't know the new field) degrade gracefully.
    """

    homage_rotation_mode: NarrativeHomageRotationMode | None = Field(
        default=None,
        description=(
            "Per-tick override of the homage choreographer's rotation "
            "strategy. None → leave the slow structural tier's choice in "
            "place (fail-open to the default). sequential/random/"
            "weighted_by_salience/paused match the choreographer."
        ),
    )
    ward_emphasis: list[str] = Field(
        default_factory=list,
        description=(
            "Ward ids to emphasize this tick. Each entry gets "
            "glow_radius_px + alpha=1.0 + scale_bump + border_pulse "
            "for a ~4s decaying window. Typo / unknown ward ids are "
            "dropped at the consumer."
        ),
    )
    ward_dispatch: list[str] = Field(
        default_factory=list,
        description=(
            "Ward ids to freshly dispatch (FSM ABSENT → ENTERING). The "
            "consumer enqueues a homage.emergence pending transition."
        ),
    )
    ward_retire: list[str] = Field(
        default_factory=list,
        description=(
            "Ward ids to retire (FSM HOLD → EXITING). The consumer "
            "enqueues a homage.recede pending transition."
        ),
    )
    placement_bias: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Per-ward placement hint. Keys are ward_ids; values are "
            "drift_left / drift_right / drift_up / drift_down / "
            "pulse_center / scale_0.8x / scale_1.0x / scale_1.15x / "
            "scale_1.3x. Unknown hints silently dropped."
        ),
    )

    @field_validator("ward_emphasis", "ward_dispatch", "ward_retire")
    @classmethod
    def _cap_list_len(cls, v: list[str]) -> list[str]:
        """Cap ward lists at 4 to prevent a pathological LLM emission
        from bumping every ward simultaneously."""
        if not isinstance(v, list):
            return []
        return [entry for entry in v[:4] if isinstance(entry, str) and entry]

    @field_validator("placement_bias")
    @classmethod
    def _cap_placement_bias(cls, v: dict[str, str]) -> dict[str, str]:
        """Cap placement_bias at 4 entries + stringify values."""
        if not isinstance(v, dict):
            return {}
        out: dict[str, str] = {}
        for key, value in list(v.items())[:4]:
            if isinstance(key, str) and isinstance(value, str) and key and value:
                out[key] = value
        return out


class DirectorIntent(BaseModel):
    """One directorial move — what the narrative director emits per tick.

    The fields split into four groups:

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
    - *What structural surface moves Hapax wants this tick* (`structural_intent`) —
      ward-level emphasis / dispatch / retire / placement-bias + homage
      rotation-mode override. Consumed by the compositor's ward-property
      manager + choreographer (see ``compositional_consumer``).
    """

    grounding_provenance: list[str] = Field(
        default_factory=list,
        description=(
            "PerceptualField signal names this move grounds in. Examples: "
            "'audio.contact_mic.desk_activity.drumming', "
            "'visual.overhead_hand_zones.turntable', "
            "'ir.ir_hand_zone.turntable', 'album.artist'. Synthetic "
            "fallback/inferred markers are migrated to "
            "synthetic_grounding_markers and do not count as evidence."
        ),
    )
    synthetic_grounding_markers: list[str] = Field(
        default_factory=list,
        description=(
            "Diagnostic placeholders for missing top-level grounding. "
            "Kept out of grounding_provenance so downstream claim, WCS, "
            "and recruitment gates fail closed when only synthetic markers "
            "are present."
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
    structural_intent: NarrativeStructuralIntent = Field(
        default_factory=NarrativeStructuralIntent,
        description=(
            "Per-tick homage surface directives. Ward emphasis + "
            "dispatch + retire + placement-bias + rotation-mode "
            "override. Defaults to an empty container so legacy LLM "
            "output (pre-field) deserializes cleanly; the consumer "
            "no-ops on an empty container."
        ),
    )

    @model_validator(mode="after")
    def _separate_synthetic_grounding(self) -> DirectorIntent:
        real, moved_synthetic = split_grounding_provenance(self.grounding_provenance)
        misplaced_real, explicit_synthetic = split_grounding_provenance(
            self.synthetic_grounding_markers
        )
        self.grounding_provenance = _dedupe_preserve_order(real + misplaced_real)
        self.synthetic_grounding_markers = _dedupe_preserve_order(
            moved_synthetic + explicit_synthetic
        )
        return self

    @property
    def has_real_grounding_provenance(self) -> bool:
        return bool(self.grounding_provenance)

    def model_dump_for_jsonl(self) -> dict:
        """Serialization used by the research-observability JSONL writer.

        Uses `mode='json'` so Stance is serialized as its string value.
        """
        return self.model_dump(mode="json")
