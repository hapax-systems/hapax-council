"""Programme primitive — meso-tier content-programming layer.

Implements the core data model from
``docs/research/2026-04-19-content-programming-layer-design.md`` §3 and
``docs/superpowers/plans/2026-04-20-programme-layer-plan.md`` §2 Phase 1.

Architectural axiom — soft priors, never hard gates.
Programmes EXPAND grounding opportunities, they never REPLACE grounding.
The constraint envelope fields are score multipliers applied to the
affordance pipeline's existing scoring function, not capability-set
filters. A zero-bias would be a hard exclusion and is architecturally
forbidden; the Pydantic validator rejects it at instantiation, so no
downstream consumer can accidentally construct a hard gate.

References:
    - feedback memory: project_programmes_enable_grounding
    - feedback memory: feedback_hapax_authors_programmes
    - feedback memory: feedback_no_expert_system_rules
    - feedback memory: feedback_grounding_exhaustive
"""

from __future__ import annotations

import math
import re
import time
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Re-declared from agents.studio_compositor.structural_director to avoid
# the compositor → shared import cycle (same pattern shared/director_intent.py
# already uses for NarrativeHomageRotationMode).
ProgrammePresetFamilyHint = Literal[
    "audio-reactive",
    "calm-textural",
    "glitch-dense",
    "warm-minimal",
]

ProgrammeHomageRotationMode = Literal[
    "sequential",
    "random",
    "weighted_by_salience",
    "paused",
]


class ProgrammeDisplayDensity(StrEnum):
    """Mirrors agents.content_scheduler.DisplayDensity without importing it."""

    SPARSE = "sparse"
    STANDARD = "standard"
    DENSE = "dense"


class ProgrammeRole(StrEnum):
    """Programme roles spanning the operator's livestream content space.

    The first twelve roles are the original Phase 1 vocabulary covering
    operator-context programmes (listening / work_block / wind_down /
    etc.). The trailing seven (TIER_LIST through LECTURE) are
    segmented-content formats added per operator outcome 2 — auto-
    programmed segmented content. They give the Hapax-authored
    programme planner an explicit vocabulary for recognizable formats
    (tier list, top 10, rant, react, iceberg, interview, lecture)
    which downstream consumers (planner prompt, programme_authors
    agent, ward composers, preset_recruitment_consumer family bias)
    wire up incrementally in follow-up cc-tasks.

    Set is open to extension. Earlier "closed set" framing was a Phase
    1 design comment that the operator has now overridden — the
    grounding axiom (programmes EXPAND grounding opportunities, never
    REPLACE them) gives no architectural reason to fix the role count.
    """

    LISTENING = "listening"
    SHOWCASE = "showcase"
    RITUAL = "ritual"
    INTERLUDE = "interlude"
    WORK_BLOCK = "work_block"
    TUTORIAL = "tutorial"
    WIND_DOWN = "wind_down"
    HOTHOUSE_PRESSURE = "hothouse_pressure"
    AMBIENT = "ambient"
    EXPERIMENT = "experiment"
    REPAIR = "repair"
    INVITATION = "invitation"

    # Segmented-content formats — operator outcome 2 (auto-programmed
    # segmented content). Each maps to a recognizable content format
    # Hapax can run as a structured segment on the livestream.
    TIER_LIST = "tier_list"
    TOP_10 = "top_10"
    RANT = "rant"
    REACT = "react"
    ICEBERG = "iceberg"
    INTERVIEW = "interview"
    LECTURE = "lecture"


class ProgrammeStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    ABORTED = "aborted"


class ProgrammeConstraintEnvelope(BaseModel):
    """Soft-prior biases applied by the affordance pipeline + directors.

    Every bias multiplier must be strictly positive. Zero or negative
    multipliers would act as hard gates, which the architectural axiom
    forbids. ``capability_bias_negative`` is the down-weighting side but
    its keys must still map to strictly positive multipliers in (0, 1].
    """

    # Negative bias — down-weight these capabilities' affordance scores.
    # Multiplier must be in (0.0, 1.0]; 0.25 = "bias against but allow".
    capability_bias_negative: dict[str, float] = Field(default_factory=dict)

    # Positive bias — up-weight these capabilities' affordance scores.
    # Multiplier must be >= 1.0; 4.0 = "strongly prefer".
    capability_bias_positive: dict[str, float] = Field(default_factory=dict)

    preset_family_priors: list[ProgrammePresetFamilyHint] = Field(default_factory=list)
    homage_rotation_modes: list[ProgrammeHomageRotationMode] = Field(default_factory=list)
    homage_package: str | None = None

    ward_emphasis_target_rate_per_min: float | None = None
    narrative_cadence_prior_s: float | None = None
    structural_cadence_prior_s: float | None = None
    surface_threshold_prior: float | None = None
    reverie_saturation_target: float | None = None

    display_density: ProgrammeDisplayDensity | None = None
    consent_scope: str | None = None

    # Voice tier band override — Phase 3 integration with voice-tier
    # spectrum. When set, overrides the ProgrammeRole default band from
    # _ROLE_TIER_DEFAULTS. Represents the structural-director's per-
    # Programme prior; the narrative-director still picks inside it.
    # Tuple of (low, high) tier IntEnum values; validator checks
    # low ≤ high. Unset = "use the role default" (soft prior, never
    # exclusion). Research §2.2 of 2026-04-20-voice-tier-director-
    # integration.md.
    voice_tier_band_prior: tuple[int, int] | None = None

    # Monetization opt-ins — Phase 5 of the demonet plan. The set of
    # capability names the programme has explicitly opted in to
    # despite their medium-risk classification (see
    # docs/governance/monetization-risk-classification.md §medium).
    # The MonetizationRiskGate admits medium-risk capabilities only
    # when their name appears in this set for the active programme;
    # high-risk capabilities are blocked regardless (governance-side
    # policy). Validator rejects known-invalid tokens (whitespace,
    # empty strings) at envelope construction.
    monetization_opt_ins: set[str] = Field(default_factory=set)

    @field_validator("capability_bias_negative")
    @classmethod
    def _negative_bias_strictly_positive(cls, v: dict[str, float]) -> dict[str, float]:
        for name, mult in v.items():
            if not math.isfinite(mult) or mult <= 0.0 or mult > 1.0:
                raise ValueError(
                    f"capability_bias_negative[{name!r}]={mult!r} — must be in (0.0, 1.0]. "
                    "Zero is architecturally forbidden (hard gate). Use a small positive "
                    "multiplier like 0.1 for strong bias-against."
                )
        return v

    @field_validator("capability_bias_positive")
    @classmethod
    def _positive_bias_in_band(cls, v: dict[str, float]) -> dict[str, float]:
        # Audit B3 / Medium #18: positive bias is clamped to [1.0, 5.0].
        # The lower bound is the architectural axiom (positive bias is a
        # MULTIPLIER, never an attenuator — that's negative's job). The
        # upper bound prevents saturation: a 5x boost is "very strong
        # soft prior" without dominating the score and reducing the
        # programme to a hard whitelist.
        for name, mult in v.items():
            if not math.isfinite(mult) or mult < 1.0:
                raise ValueError(
                    f"capability_bias_positive[{name!r}]={mult!r} — must be >= 1.0. "
                    "Values below 1.0 belong in capability_bias_negative."
                )
            if mult > 5.0:
                raise ValueError(
                    f"capability_bias_positive[{name!r}]={mult!r} — must be <= 5.0. "
                    "Soft priors are bounded multipliers; a value above 5.0 saturates "
                    "the score and reduces the programme to a hard whitelist."
                )
        return v

    @field_validator("ward_emphasis_target_rate_per_min")
    @classmethod
    def _rate_non_negative(cls, v: float | None) -> float | None:
        if v is not None and (not math.isfinite(v) or v < 0.0):
            raise ValueError(f"ward_emphasis_target_rate_per_min={v!r} — must be >= 0.")
        return v

    @field_validator(
        "narrative_cadence_prior_s",
        "structural_cadence_prior_s",
    )
    @classmethod
    def _cadence_positive(cls, v: float | None) -> float | None:
        if v is not None and (not math.isfinite(v) or v <= 0.0):
            raise ValueError("cadence prior must be > 0 seconds")
        return v

    @field_validator("voice_tier_band_prior")
    @classmethod
    def _voice_tier_band_well_ordered(cls, v: tuple[int, int] | None) -> tuple[int, int] | None:
        if v is None:
            return v
        low, high = v
        if not (0 <= low <= 6 and 0 <= high <= 6):
            raise ValueError(
                f"voice_tier_band_prior={v!r} — each bound must be in 0..6 (VoiceTier range)."
            )
        if low > high:
            raise ValueError(f"voice_tier_band_prior={v!r} — low ({low}) must be ≤ high ({high}).")
        return v

    @field_validator("monetization_opt_ins")
    @classmethod
    def _opt_ins_well_formed(cls, v: set[str]) -> set[str]:
        for name in v:
            if not isinstance(name, str):
                raise ValueError(
                    f"monetization_opt_ins element {name!r} must be a string capability name"
                )
            stripped = name.strip()
            if not stripped or stripped != name:
                raise ValueError(
                    f"monetization_opt_ins element {name!r} — must be non-empty "
                    "and contain no leading/trailing whitespace"
                )
        return v

    @field_validator("surface_threshold_prior", "reverie_saturation_target")
    @classmethod
    def _unit_interval(cls, v: float | None) -> float | None:
        if v is not None and (not math.isfinite(v) or v < 0.0 or v > 1.0):
            raise ValueError("value must be in [0.0, 1.0]")
        return v

    def bias_multiplier(self, capability_name: str) -> float:
        """Composed bias multiplier for a capability (positive × negative)."""
        pos = self.capability_bias_positive.get(capability_name, 1.0)
        neg = self.capability_bias_negative.get(capability_name, 1.0)
        return pos * neg

    def expands_candidate_set(self, capability_name: str) -> bool:
        """A programme envelope ALWAYS expands (or preserves) the candidate set.

        Because zero multipliers are rejected by the validator, no envelope
        can strictly exclude a capability. This property encodes the
        architectural axiom at read time — consumers can use it as a
        self-check without depending on validator execution.
        """
        return self.bias_multiplier(capability_name) > 0.0


class SegmentAsset(BaseModel):
    """One media asset referenced by a prepared script block.

    Populated during daily_segment_prep alongside the prepared_script.
    The playback loop publishes these to SHM at sentence tempo so the
    DURF compositor ward can display relevant visuals per-block.
    """

    kind: Literal["image", "youtube", "url", "text"] = "text"
    url: str | None = None
    caption: str | None = None
    block_index: int | None = None  # which script block this belongs to


class ProgrammeContent(BaseModel):
    """Concrete content grounding — perception inputs, never scripted text.

    Hapax-authored only; operator never populates these fields directly.
    ``narrative_beat`` is a 1-2 sentence prose intent the programme
    planner emits as *direction* for the narrative director — not a
    scripted utterance Hapax reads aloud.

    ``segment_beats`` (optional) carries an ordered list of beat cues
    for segmented-content programmes. Each beat is a short directive
    (NOT a scripted line) that the director advances through — the
    actual spoken delivery is composed spontaneously from assets +
    perception at each beat. Think of it as a show rundown:

        ["hook: introduce topic and why it matters",
         "item_10: present entry #10 with context",
         "item_9: present entry #9, contrast with #10",
         ...
         "item_1: reveal #1 with operator's distinctive angle",
         "close: invite chat reactions and tease next segment"]

    The director reads the *current* beat (indexed by programme
    elapsed time / beat count) and composes its narrative_text to
    advance that beat. Beat transitions happen via
    ``programme.beat_advance`` intent family.

    ``segment_cues`` is legacy executable compositor authority. It may
    remain on non-responsible/static rehearsals, but responsible hosting
    content must use proposal-only ``beat_layout_intents`` and runtime
    receipts instead.
    """

    music_track_ids: list[str] = Field(default_factory=list)
    operator_task_ref: str | None = None
    research_objective_ref: str | None = None
    narrative_beat: str | None = None
    segment_beats: list[str] = Field(default_factory=list)
    segment_cues: list[str] = Field(default_factory=list)
    hosting_context: str | dict[str, Any] | None = None
    authority: str | None = None
    beat_layout_intents: list[dict[str, Any]] = Field(default_factory=list)
    layout_decision_contract: dict[str, Any] = Field(default_factory=dict)
    runtime_layout_validation: dict[str, Any] = Field(default_factory=dict)
    layout_decision_receipts: list[dict[str, Any]] = Field(default_factory=list)
    prepared_artifact_ref: dict[str, Any] | str | None = None
    artifact_path_diagnostic: str | None = None
    segment_beat_durations: list[float] = Field(default_factory=list)
    """Seconds per beat, paired 1:1 with segment_beats.

    The planner specifies how long each beat should last. The opening
    beat is typically short (30-60s), body beats are longer (60-120s),
    and the closing beat is moderate (45-90s). If empty or shorter
    than segment_beats, missing durations default to
    (planned_duration_s / len(segment_beats)).
    """
    prepared_script: list[str] = Field(default_factory=list)
    """Pre-composed narration text, one entry per segment_beat.

    Populated by the daily prep runner BEFORE the programme activates.
    During delivery, the programme loop reads these chunks sequentially
    and feeds them to TTS.  No LLM calls during delivery.

    Each entry is 8-20 sentences (800-2000 characters) of broadcast-
    ready prose — the actual words Hapax will speak for that beat.
    Unlike segment_beats (which are director cues / rundown notes),
    these are composed and iteratively refined output.
    """
    segment_assets: list[SegmentAsset] = Field(default_factory=list)
    """Per-block media assets for DURF ward display during playback.

    Populated during daily_segment_prep. Each asset carries a kind
    (image/youtube/url/text), URL, caption, and the block_index it
    belongs to. The playback loop publishes the current block's assets
    to SHM so the DURF can render them at sentence tempo.
    """
    invited_capabilities: set[str] = Field(default_factory=set)

    @field_validator("narrative_beat")
    @classmethod
    def _narrative_beat_is_direction_not_script(cls, v: str | None) -> str | None:
        if v is None:
            return v
        stripped = v.strip()
        if not stripped:
            return None
        if len(stripped) > 500:
            raise ValueError(
                "narrative_beat > 500 chars — programme direction, not a scripted utterance"
            )
        return stripped

    @field_validator("segment_beats")
    @classmethod
    def _segment_beats_reasonable(cls, v: list[str]) -> list[str]:
        if len(v) > 30:
            raise ValueError(f"segment_beats has {len(v)} entries — max 30 per programme")
        return [b.strip() for b in v if b.strip()]

    @field_validator("segment_cues")
    @classmethod
    def _segment_cues_reasonable(cls, v: list[str]) -> list[str]:
        if len(v) > 30:
            raise ValueError(f"segment_cues has {len(v)} entries — max 30 per programme")
        return [c.strip() for c in v if c.strip()]

    @field_validator("beat_layout_intents")
    @classmethod
    def _beat_layout_intents_are_needs_only(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        _reject_layout_authority_fields(v)
        return v

    @field_validator("layout_decision_contract")
    @classmethod
    def _layout_decision_contract_is_non_authoritative(cls, v: dict[str, Any]) -> dict[str, Any]:
        if not v:
            return {}
        _reject_layout_authority_fields(v)
        if v.get("may_command_layout") is not False:
            raise ValueError("layout_decision_contract may only declare may_command_layout=false")
        return {"may_command_layout": False}

    @field_validator("runtime_layout_validation")
    @classmethod
    def _runtime_layout_validation_is_code_owned(cls, v: dict[str, Any]) -> dict[str, Any]:
        _reject_layout_authority_fields(v)
        return {}

    @field_validator("layout_decision_receipts")
    @classmethod
    def _layout_decision_receipts_are_runtime_owned(
        cls, v: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if v:
            raise ValueError(
                "ProgrammeContent layout_decision_receipts are runtime-owned; "
                "planner/prepared content may not carry layout receipts"
            )
        return []

    @field_validator("segment_beat_durations")
    @classmethod
    def _segment_beat_durations_reasonable(cls, v: list[float]) -> list[float]:
        if len(v) > 30:
            raise ValueError(f"segment_beat_durations has {len(v)} entries — max 30 per programme")
        return [max(15.0, d) for d in v]  # Floor of 15s per beat

    @model_validator(mode="after")
    def _responsible_hosting_quarantines_segment_cues(self) -> ProgrammeContent:
        if self.segment_cues and self.beat_layout_intents:
            raise ValueError(
                "ProgrammeContent cannot mix executable segment_cues with beat_layout_intents"
            )
        if self.segment_cues and _content_hosting_context_is_responsible(self.hosting_context):
            raise ValueError(
                "responsible hosting ProgrammeContent cannot carry executable segment_cues; "
                "use proposal-only beat_layout_intents"
            )
        if _content_hosting_context_is_responsible(self.hosting_context):
            for index, intent in enumerate(self.beat_layout_intents):
                if _layout_intent_allows_default_static_success(intent):
                    raise ValueError(
                        "responsible hosting ProgrammeContent cannot allow default/static "
                        "layout success: "
                        f"beat_layout_intents[{index}].default_static_success_allowed"
                    )
        return self


def _content_hosting_context_is_responsible(value: str | dict[str, Any] | None) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return _hosting_context_token(value) not in {
            "nonresponsiblestatic",
            "internalrehearsal",
        }
    mode = value.get("mode") or value.get("hosting_context")
    return _content_hosting_context_is_responsible(mode if isinstance(mode, str) else None)


def _hosting_context_token(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _layout_intent_allows_default_static_success(intent: dict[str, Any]) -> bool:
    raw = intent.get("default_static_success_allowed")
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return _hosting_context_token(raw) in {"1", "allowed", "true", "yes"}
    return raw is not None and bool(raw)


_FORBIDDEN_LAYOUT_AUTHORITY_KEY_TOKENS = frozenset(
    {
        "layout",
        "layoutid",
        "layoutname",
        "requestedlayout",
        "selectedlayout",
        "targetlayout",
        "activelayout",
        "surface",
        "surfaces",
        "surfaceid",
        "coordinates",
        "coordinate",
        "shm",
        "shmpath",
        "segmentcues",
        "cue",
        "cues",
        "command",
        "commands",
        "camera",
        "zorder",
        "directlayoutcommand",
        "directlayoutcommands",
        "layoutdecisionreceipt",
        "layoutdecisionreceipts",
        "layoutreceipt",
        "layoutreceipts",
        "publicbroadcastbypass",
        "receiptrefs",
        "runtimepolicy",
        "runtimereadback",
        "wcsreadbackrequirements",
    }
)


_FORBIDDEN_LAYOUT_AUTHORITY_VALUE_PREFIX_TOKENS = frozenset(
    {
        "command",
        "commands",
        "coordinate",
        "coordinates",
        "cue",
        "layout",
        "shm",
        "surface",
        "zindex",
        "zorder",
    }
)


_FORBIDDEN_LAYOUT_AUTHORITY_VALUE_TOKENS = frozenset(
    {
        "balancedv2",
        "broadcastbypass",
        "defaultjson",
        "defaultlayout",
        "defaultstatic",
        "devshm",
        "fallbackreceipt",
        "garagedoor",
        "layoutreceipt",
        "layoutstate",
        "layoutstore",
        "nonresponsiblestatic",
        "publicbroadcast",
        "publicbroadcastbypass",
        "publicbypass",
        "renderedframe",
        "spokenonlyfallback",
        "staticlayout",
        "wardreadback",
    }
)


_FORBIDDEN_LAYOUT_AUTHORITY_VALUE_SUBSTRINGS = frozenset(
    {
        "broadcastbypass",
        "compositorlayouts",
        "defaultjson",
        "defaultlayout",
        "defaultstatic",
        "devshm",
        "layoutreceipt",
        "layoutstate",
        "layoutstore",
        "nonresponsiblestatic",
        "publicbroadcastbypass",
        "spokenonlyfallback",
        "staticlayout",
        "wardreadback",
        "wcsreadback",
    }
)


_FORBIDDEN_LAYOUT_AUTHORITY_VALUE_PATTERNS = (
    re.compile(r"(^|[\s:/=._-])(?:command|cue|layout|shm|surface)\s*[:=.]"),
    re.compile(r"\b(?:x|y|w|h|width|height|z|z_index|z-index|zindex)\s*[:=]\s*-?\d"),
    re.compile(r"\bswitch(?:_to)?(?:_layout)?\b"),
)


def _reject_layout_authority_fields(value: Any, *, prefix: str = "") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str):
                continue
            path = f"{prefix}.{key}" if prefix else key
            token = _hosting_context_token(key)
            if token in _FORBIDDEN_LAYOUT_AUTHORITY_KEY_TOKENS:
                raise ValueError(
                    f"ProgrammeContent layout proposals cannot carry concrete layout authority: {path}"
                )
            _reject_layout_authority_fields(nested, prefix=path)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_layout_authority_fields(nested, prefix=f"{prefix}[{index}]")
    elif isinstance(value, str):
        _reject_layout_authority_string(value, path=prefix)


def _reject_layout_authority_string(value: str, *, path: str) -> None:
    stripped = value.strip()
    if not stripped:
        return

    raw = stripped.lower()
    token = _hosting_context_token(stripped)
    forbidden = (
        token in _FORBIDDEN_LAYOUT_AUTHORITY_VALUE_TOKENS
        or any(
            token.startswith(prefix) for prefix in _FORBIDDEN_LAYOUT_AUTHORITY_VALUE_PREFIX_TOKENS
        )
        or any(part in token for part in _FORBIDDEN_LAYOUT_AUTHORITY_VALUE_SUBSTRINGS)
        or any(pattern.search(raw) for pattern in _FORBIDDEN_LAYOUT_AUTHORITY_VALUE_PATTERNS)
    )
    if forbidden:
        location = path or "<value>"
        raise ValueError(
            "ProgrammeContent layout proposals cannot carry command-like layout authority "
            f"at {location}: {stripped!r}"
        )


class ProgrammeRitual(BaseModel):
    """Entry / exit choreography marking the programme boundary."""

    entry_signature_artefact: str | None = None
    entry_ward_choreography: list[str] = Field(default_factory=list)
    entry_substrate_palette_shift: str | None = None
    exit_signature_artefact: str | None = None
    exit_ward_choreography: list[str] = Field(default_factory=list)
    exit_substrate_palette_shift: str | None = None
    boundary_freeze_s: float = 4.0

    @field_validator("boundary_freeze_s")
    @classmethod
    def _boundary_freeze_reasonable(cls, v: float) -> float:
        if not math.isfinite(v) or v < 0.0 or v > 30.0:
            raise ValueError(f"boundary_freeze_s={v!r} — must be in [0, 30] seconds")
        return v


class ProgrammeSuccessCriteria(BaseModel):
    """How the programme knows it is done (or should abort).

    Predicates are NAMES looked up by the programme-monitor loop, not
    inline code. This keeps the primitive declarative and JSON-round-
    trippable.
    """

    completion_predicates: list[str] = Field(default_factory=list)
    abort_predicates: list[str] = Field(default_factory=list)
    min_duration_s: float = 600.0  # 10-min floor; operator hard requirement
    max_duration_s: float = 7200.0  # 2-hour cap; segments target 1 hour

    @model_validator(mode="after")
    def _durations_ordered(self) -> ProgrammeSuccessCriteria:
        if self.min_duration_s < 0 or self.max_duration_s <= 0:
            raise ValueError("durations must be positive")
        if self.min_duration_s > self.max_duration_s:
            raise ValueError(
                f"min_duration_s={self.min_duration_s} > max_duration_s={self.max_duration_s}"
            )
        return self


ProgrammeAuthorship = Literal["hapax", "operator"]

# D-26a (demonet plan §Phase 5 lines 354-358): operator-authored
# programmes may opt-in up to MAX_OPT_INS medium-risk capabilities.
# Hapax-authored programmes may not opt in to ANY medium-risk
# capability (the exception path is reserved for explicit operator
# consent per the bilateral-contract pattern; consent_gate analog).
MAX_OPT_INS: int = 3


class Programme(BaseModel):
    programme_id: str
    role: ProgrammeRole
    status: ProgrammeStatus = ProgrammeStatus.PENDING
    planned_duration_s: float

    actual_started_at: float | None = None
    actual_ended_at: float | None = None

    # Authorship axis (D-26a / demonet Phase 5 line 359-367). Defaults
    # to "hapax" per memory `feedback_hapax_authors_programmes` — the
    # operator does NOT write show outlines / cue sheets. The one
    # exception is `constraints.monetization_opt_ins`, where expanding
    # candidacy beyond the safe set requires operator consent;
    # operator-authored Programmes signal that consent by carrying
    # `authorship="operator"` and may set up to MAX_OPT_INS opt-ins.
    authorship: ProgrammeAuthorship = "hapax"

    constraints: ProgrammeConstraintEnvelope = Field(default_factory=ProgrammeConstraintEnvelope)
    content: ProgrammeContent = Field(default_factory=ProgrammeContent)
    ritual: ProgrammeRitual = Field(default_factory=ProgrammeRitual)
    success: ProgrammeSuccessCriteria = Field(default_factory=ProgrammeSuccessCriteria)

    parent_show_id: str
    parent_condition_id: str | None = None
    notes: str = ""

    @field_validator("programme_id", "parent_show_id")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("id must be non-empty")
        return v

    @field_validator("planned_duration_s")
    @classmethod
    def _planned_positive(cls, v: float) -> float:
        if not math.isfinite(v) or v <= 0.0:
            raise ValueError("planned_duration_s must be > 0")
        return v

    @property
    def monetization_opt_ins(self) -> set[str]:
        """Delegate to ``constraints.monetization_opt_ins``.

        ``MonetizationRiskGate._ProgrammeLike`` protocol expects the set
        directly on the Programme object. Rather than require callers
        to unwrap ``.constraints`` (which would leak envelope structure
        into the gate's signature), Programme exposes the opt-ins at
        the top level as a read-only view. Demonet Phase 5.
        """
        return self.constraints.monetization_opt_ins

    @model_validator(mode="after")
    def _end_after_start(self) -> Programme:
        if (
            self.actual_started_at is not None
            and self.actual_ended_at is not None
            and self.actual_ended_at < self.actual_started_at
        ):
            raise ValueError("actual_ended_at precedes actual_started_at")
        return self

    @model_validator(mode="after")
    def _opt_ins_authorship_invariant(self) -> Programme:
        """D-26a (demonet plan §Phase 5 lines 354-358): authorship gates
        the monetization_opt_ins set.

          - Hapax-authored: opt-ins MUST be empty. Hapax cannot
            unilaterally expand candidacy past the safe set; that
            requires operator consent (parallel to consent-gate's
            bilateral-contract requirement).
          - Operator-authored: opt-ins capped at MAX_OPT_INS so a single
            programme can't unbound the safe set.

        High-risk capabilities are blocked regardless of authorship by
        the gate's short-circuit at `monetization_safety.py:169`; this
        validator only governs medium-risk opt-ins.
        """
        opt_ins = self.constraints.monetization_opt_ins
        if self.authorship == "hapax" and opt_ins:
            raise ValueError(
                f"Programme {self.programme_id!r}: hapax-authored programmes "
                f"may not set monetization_opt_ins (got {sorted(opt_ins)!r}). "
                "Set authorship='operator' to signal explicit operator consent "
                "(per demonet plan §Phase 5 + memory feedback_hapax_authors_programmes)."
            )
        if self.authorship == "operator" and len(opt_ins) > MAX_OPT_INS:
            raise ValueError(
                f"Programme {self.programme_id!r}: operator-authored opt-ins "
                f"exceed MAX_OPT_INS={MAX_OPT_INS} (got {len(opt_ins)}). "
                "Trim the set or split into multiple programmes."
            )
        return self

    @property
    def elapsed_s(self) -> float | None:
        """Seconds since programme activation; ``None`` if not started."""
        if self.actual_started_at is None:
            return None
        end = self.actual_ended_at if self.actual_ended_at is not None else time.time()
        return max(0.0, end - self.actual_started_at)

    def bias_multiplier(self, capability_name: str) -> float:
        """Shortcut: ``self.constraints.bias_multiplier(name)``."""
        return self.constraints.bias_multiplier(capability_name)

    def expands_candidate_set(self, capability_name: str) -> bool:
        """Shortcut: always True under the architectural axiom."""
        return self.constraints.expands_candidate_set(capability_name)

    def validate_soft_priors_only(self) -> None:
        """Re-run the envelope validators — callable by consumers as a self-check."""
        ProgrammeConstraintEnvelope.model_validate(self.constraints.model_dump())


class ProgrammePlan(BaseModel):
    """A 2-5 programme sequence emitted by the Hapax planner (Phase 3).

    The planner LLM emits this at show-start and at each programme
    boundary; the ProgrammePlanStore persists each Programme; the
    ProgrammeManager walks them.

    The ``plan_author`` is a `Literal` pinned to ``"hapax-director-planner"``
    — the operator does NOT write programme plans (per memory
    ``feedback_hapax_authors_programmes``). The validator rejects any
    other authorship token at construction so a vault-supplied JSON
    masquerading as a plan is unambiguously rejected.

    All programmes in a plan share the parent ``show_id``; the
    cross-reference invariant catches mistyped shows at construction.
    """

    plan_id: str
    show_id: str
    plan_author: Literal["hapax-director-planner"] = "hapax-director-planner"
    programmes: list[Programme] = Field(min_length=1, max_length=5)
    created_at: float = Field(default_factory=time.time)

    @field_validator("plan_id", "show_id")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("id must be non-empty")
        return v

    @model_validator(mode="after")
    def _programmes_share_show(self) -> ProgrammePlan:
        for p in self.programmes:
            if p.parent_show_id != self.show_id:
                raise ValueError(
                    f"programme {p.programme_id!r} has parent_show_id="
                    f"{p.parent_show_id!r} but plan show_id={self.show_id!r}"
                )
        return self
