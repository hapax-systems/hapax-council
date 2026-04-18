"""HomagePackage — named aesthetic framework bundle.

HOMAGE spec §4.1–§4.7. A package is a DATA description of the grammar,
typography, palette, transitions, coupling rules, and signature
artefacts that collectively render as an authentic homage to some
aesthetic lineage (BitchX first; demoscene, ANSI BBS, HyperCard, etc.
as future members).

Packages are immutable at runtime. One package is active at a time.
The active-package registry lives in
``agents.studio_compositor.homage.__init__``. Swapping packages is a
structural-director move (spec §4.13, ``homage_rotation_mode``).

This module contains pure Pydantic models. No IO, no import from the
studio_compositor; the intent is that anyone — the director prompt, the
choreographer, observability, tests — can `from shared.homage_package
import HomagePackage` without pulling in Cairo or GStreamer.

Anti-pattern enforcement is field-validator-based: constructing a
BitchX-like package with a non-monospaced typography stack or a
``transition_frame_count`` other than 0 raises a ValidationError so the
spec §5.5 hard-refusal list is pinned in the type system.

Spec: ``docs/superpowers/specs/2026-04-18-homage-framework-design.md``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.voice_register import VoiceRegister

# ── Vocabularies ──────────────────────────────────────────────────────────

ColourRoleName = Literal[
    "muted",
    "bright",
    "accent_cyan",
    "accent_magenta",
    "accent_green",
    "accent_yellow",
    "accent_red",
    "accent_blue",
    "terminal_default",
    "background",
]
"""The semantic colour roles every HomagePalette must provide. Additional
accent hues may live under ``HomagePalette.extra``; the ten above are
load-bearing and validated."""


SizeClassName = Literal["compact", "normal", "large", "banner"]
"""Discrete typography size classes (spec §4.3). Intermediate sizes are
refused to preserve raster integrity."""


ContainerShape = Literal["angle-bracket", "square-bracket", "curly", "bare"]


# Named transitions every TransitionVocab must define (spec §4.5). Package
# authors may add more under ``TransitionVocab.extra``; the nine below
# are the load-bearing vocabulary every ward expects.
TransitionName = Literal[
    "zero-cut-in",
    "zero-cut-out",
    "join-message",
    "part-message",
    "topic-change",
    "netsplit-burst",
    "mode-change",
    "ticker-scroll-in",
    "ticker-scroll-out",
]


SignatureArtefactForm = Literal["quit-quip", "join-banner", "motd-block", "kick-reason"]


AntiPatternKind = Literal[
    "emoji",
    "anti-aliased",
    "proportional-font",
    "flat-ui-chrome",
    "iso-8601-timestamp",
    "rounded-corners",
    "right-aligned-timestamp",
    "fade-transition",
    "swiss-grid-motd",
    "box-draw-inline-rule",
]


# ── Sub-models ────────────────────────────────────────────────────────────


RGBA = tuple[float, float, float, float]


class HomagePalette(BaseModel):
    """Semantic role → RGBA mapping (spec §4.4).

    The ten load-bearing roles are required. Additional accent colours
    belong under ``extra``. Mode-aware remapping (research vs rnd
    working-mode) is handled by the consumer, not here — the palette
    is a single state, not a ladder.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    muted: RGBA
    bright: RGBA
    accent_cyan: RGBA
    accent_magenta: RGBA
    accent_green: RGBA
    accent_yellow: RGBA
    accent_red: RGBA
    accent_blue: RGBA
    terminal_default: RGBA
    background: RGBA
    extra: dict[str, RGBA] = Field(default_factory=dict)

    @field_validator(
        "muted",
        "bright",
        "accent_cyan",
        "accent_magenta",
        "accent_green",
        "accent_yellow",
        "accent_red",
        "accent_blue",
        "terminal_default",
        "background",
    )
    @classmethod
    def _rgba_in_range(cls, value: RGBA) -> RGBA:
        if len(value) != 4 or not all(0.0 <= c <= 1.0 for c in value):
            raise ValueError("RGBA channels must each be in [0.0, 1.0]")
        return value


class TypographyStack(BaseModel):
    """Font stack + discrete size classes (spec §4.3).

    ``primary_font_family`` is required to be monospaced for any package
    whose ``GrammarRules.raster_cell_required`` is True; enforcement
    lives in ``HomagePackage`` because it crosses models.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    primary_font_family: str
    fallback_families: tuple[str, ...] = Field(default_factory=tuple)
    size_classes: dict[SizeClassName, int] = Field(
        ...,
        description="Pixel sizes per class. Must include 'compact' and 'normal'.",
    )
    weight: Literal["single", "dual"] = "single"
    monospaced: bool = True

    @field_validator("size_classes")
    @classmethod
    def _required_size_classes_present(
        cls, value: dict[SizeClassName, int]
    ) -> dict[SizeClassName, int]:
        required = {"compact", "normal"}
        missing = required - value.keys()
        if missing:
            raise ValueError(f"size_classes missing required keys: {sorted(missing)}")
        if any(px <= 0 for px in value.values()):
            raise ValueError("size_classes pixel values must be positive")
        return value


class GrammarRules(BaseModel):
    """Load-bearing structural rules every ward enforces (spec §4.2)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    punctuation_colour_role: ColourRoleName
    identity_colour_role: ColourRoleName
    content_colour_role: ColourRoleName
    line_start_marker: str
    container_shape: ContainerShape
    raster_cell_required: bool
    transition_frame_count: int = Field(ge=0, le=60)
    event_rhythm_as_texture: bool
    signed_artefacts_required: bool

    @field_validator("line_start_marker")
    @classmethod
    def _line_start_marker_non_empty(cls, value: str) -> str:
        stripped = value
        if not stripped:
            raise ValueError("line_start_marker must be non-empty")
        return value


class TransitionVocab(BaseModel):
    """Named transitions the package uses for entry/hold/exit/swap (spec §4.5)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    supported: frozenset[TransitionName]
    default_entry: TransitionName
    default_exit: TransitionName
    max_simultaneous_entries: int = Field(ge=1, le=8, default=2)
    max_simultaneous_exits: int = Field(ge=1, le=8, default=2)
    netsplit_burst_min_interval_s: float = Field(ge=30.0, default=120.0)
    extra: dict[str, str] = Field(
        default_factory=dict,
        description="Package-specific transition descriptors keyed by name.",
    )

    @model_validator(mode="after")
    def _defaults_are_supported(self) -> TransitionVocab:
        if self.default_entry not in self.supported:
            raise ValueError(f"default_entry {self.default_entry!r} not in supported set")
        if self.default_exit not in self.supported:
            raise ValueError(f"default_exit {self.default_exit!r} not in supported set")
        return self


class CouplingRules(BaseModel):
    """Bidirectional ward↔shader contract (spec §4.6).

    ``custom_slot_index`` is the index into ``uniforms.custom[N]`` the
    choreographer writes the 4-float homage payload into. BitchX uses
    index 4.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    custom_slot_index: int = Field(ge=0, le=7)
    payload_channels: tuple[str, str, str, str] = Field(
        default=(
            "active_transition_energy",
            "palette_accent_hue_deg",
            "signature_artefact_intensity",
            "rotation_phase",
        ),
        description=(
            "Names of the four floats in uniforms.custom[custom_slot_index]. "
            "Order matters — shaders read by index."
        ),
    )
    shader_feedback_enabled: bool = True
    shader_feedback_key: str = Field(
        default="shader_energy",
        description=(
            "Key read from /dev/shm/hapax-imagination/shader-feedback.json "
            "for ward cadence modulation."
        ),
    )


class SignatureRules(BaseModel):
    """Authorship convention for rotating artefacts (spec §4.7)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    author_tag: str
    attribution_inline: bool = True
    generated_content_only: bool = Field(
        default=True,
        description=(
            "When True, signature artefacts are agent-authored. Captured "
            "content (real chat messages, named persons) is forbidden. "
            "Enforced at axiom layer — interpersonal_transparency."
        ),
    )
    rotation_cadence_s_steady: float = Field(ge=10.0, default=90.0)
    rotation_cadence_s_deliberate: float = Field(ge=30.0, default=180.0)
    rotation_cadence_s_rapid: float = Field(ge=5.0, default=30.0)
    netsplit_burst_cadence_s: float = Field(ge=60.0, default=120.0)


class SignatureArtefact(BaseModel):
    """One rotating authored content record (spec §4.7 / §5.4)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str
    form: SignatureArtefactForm
    author_tag: str
    weight: float = Field(ge=0.0, le=1.0, default=1.0)

    @field_validator("content")
    @classmethod
    def _content_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("SignatureArtefact.content must be non-empty")
        return value


# ── Top-level package ─────────────────────────────────────────────────────


class HomagePackage(BaseModel):
    """Named aesthetic framework bundle.

    Instances are frozen. Use ``HomagePackage.model_copy(update=...)``
    to derive variants (e.g., mode-aware palette swaps handled by the
    consumer).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = ""
    grammar: GrammarRules
    typography: TypographyStack
    palette: HomagePalette
    transition_vocabulary: TransitionVocab
    coupling_rules: CouplingRules
    signature_conventions: SignatureRules
    voice_register_default: VoiceRegister
    signature_artefacts: tuple[SignatureArtefact, ...] = Field(
        default_factory=tuple,
        description=(
            "Rotating corpus. The package ships a seed set; additions "
            "may be loaded from assets/homage/<name>/artefacts.yaml."
        ),
    )
    refuses_anti_patterns: frozenset[AntiPatternKind] = Field(
        default_factory=frozenset,
        description="Anti-patterns this package hard-refuses (spec §5.5).",
    )

    @model_validator(mode="after")
    def _raster_requires_monospace(self) -> HomagePackage:
        """Spec §4.2: raster_cell_required implies monospaced typography.

        Refuses a HomagePackage whose grammar claims a raster cell while
        the typography stack is non-monospaced — the canonical
        'BitchX-ish but wrong' anti-pattern.
        """
        if self.grammar.raster_cell_required and not self.typography.monospaced:
            raise ValueError(
                "raster_cell_required is True but typography.monospaced is False; "
                "this is the 'BitchX-ish but wrong' anti-pattern — "
                "see spec §5.5 (proportional-font refusal)."
            )
        return self

    @model_validator(mode="after")
    def _zero_frame_packages_cannot_declare_fade(self) -> HomagePackage:
        """BitchX lineage refuses fade/dissolve transitions (spec §5.5)."""
        if (
            "fade-transition" in self.refuses_anti_patterns
            and self.grammar.transition_frame_count > 0
        ):
            raise ValueError(
                "Package refuses fade-transition but declares "
                f"transition_frame_count={self.grammar.transition_frame_count}; "
                "zero-frame packages must declare transition_frame_count=0."
            )
        return self

    @model_validator(mode="after")
    def _grammar_colour_roles_are_known(self) -> HomagePackage:
        """Every grammar colour role must be resolvable against the palette."""
        palette_roles = set(type(self.palette).model_fields.keys()) - {"extra"}
        for role_name in (
            self.grammar.punctuation_colour_role,
            self.grammar.identity_colour_role,
            self.grammar.content_colour_role,
        ):
            if role_name not in palette_roles:
                raise ValueError(
                    f"grammar references colour role {role_name!r} "
                    f"not present on HomagePalette (known: {sorted(palette_roles)})"
                )
        return self

    def resolve_colour(self, role: ColourRoleName) -> RGBA:
        """Return the RGBA for a named role. Raises KeyError if unknown."""
        return getattr(self.palette, role)

    def artefacts_by_form(self, form: SignatureArtefactForm) -> tuple[SignatureArtefact, ...]:
        """Return the subset of signature artefacts for a given form."""
        return tuple(a for a in self.signature_artefacts if a.form == form)


__all__ = [
    "AntiPatternKind",
    "ColourRoleName",
    "ContainerShape",
    "CouplingRules",
    "GrammarRules",
    "HomagePackage",
    "HomagePalette",
    "RGBA",
    "SignatureArtefact",
    "SignatureArtefactForm",
    "SignatureRules",
    "SizeClassName",
    "TransitionName",
    "TransitionVocab",
    "TypographyStack",
]
