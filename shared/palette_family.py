"""Palette family — first-class colour-scheme abstraction (video-container Phase 2).

The scrim / mirror-emissive system needs a rich palette vocabulary that
behaves like the effect-preset family: a registry of named instances,
semantic tags for affordance recruitment, chains that sequence
instances over time, and a curve vocabulary for how substrate pixels
map through a palette.

**Operator directive 2026-04-23:** palettes are ORTHOGONAL to the
working-mode (research / R&D). ``working_mode_affinity`` below is an
affinity hint for Hapax recruitment, not a hard gate — the research
palette set can be recruited in R&D when the semantic fits, and vice
versa. At least a dozen palette instances are expected.

## Structure

- :class:`PaletteResponseCurve` — the rendering math. Six modes today
  (``lab_shift``, ``duotone``, ``gradient_map``, ``hue_rotate``,
  ``channel_mix``, ``identity``). More can be added without widening
  the palette record.
- :class:`ScrimPalette` — a named palette instance. Carries display
  metadata (name, description, semantic tags), a LAB anchor point,
  three perceptual axes (warmth / saturation / lightness), a response
  curve, an optional temporal profile, and a working-mode affinity
  hint. Hashable for cache keys; frozen for thread safety.
- :class:`PaletteChainStep` — one palette in a sequence with its dwell
  and transition spec.
- :class:`PaletteChain` — an ordered sequence of palettes with loop /
  no-loop semantics, mirroring the effect-preset-chain pattern.

## Consumers

Phase 2 of the video-container epic is pure types. Consumers arrive in
Phase 4 (``ReverieEmissiveCairoSource``) and Phase 5+ (scrim renderer),
which will take a :class:`ScrimPalette` by ``id`` (or a chain) and apply
its curve to substrate / emissive pixels. The scrim epic's "dozen+
palettes" live in a registry loaded at compositor init time; the
registry implementation is Phase 3 scope.

## Design notes

- **LAB over RGB.** Every palette carries its anchor and accent in
  CIE-LAB so the response curves can do perceptually-uniform shifts
  without surprise gamma artifacts. The curve evaluator converts to
  the target colour space at apply time.
- **Axes are descriptive, not prescriptive.** ``warmth_axis`` etc. are
  consultation surfaces for the Hapax recruitment agent — "pick
  something cool and saturated" — they're not used by the curve math.
- **Tags are freeform.** A Qdrant-embedded affordance descriptor
  builds on top of ``semantic_tags``. Typical tags: ``warm``,
  ``dawn``, ``sage``, ``lo-fi``, ``neon``, ``bruise``, ``dusk``,
  ``tender``. No closed vocabulary.
- **Affinity, not binding.** ``working_mode_affinity`` is a list of
  modes the palette reads well in; recruitment still allowed outside.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# CIE-LAB triple (L*, a*, b*). L* in [0, 100], a*/b* typically in [-128, 127].
LabTriple = tuple[float, float, float]

# Curve mode — the shape of how substrate pixels map through the palette.
# Six modes cover most intent today; new modes slot in alongside without
# widening every call site.
PaletteCurveMode = Literal[
    "identity",  # no modulation — useful for neutral / passthrough palettes
    "lab_shift",  # add (ΔL, Δa, Δb) to every pixel
    "duotone",  # map luminance to a two-colour gradient
    "gradient_map",  # luminance → multi-stop gradient lookup
    "hue_rotate",  # rotate hue by N degrees, preserve luminance + chroma
    "channel_mix",  # linear combination of R/G/B channels
]

# Temporal profile — how the palette breathes over its dwell.
# Not all palettes animate; ``steady`` is the no-op default.
TemporalProfile = Literal[
    "steady",  # no animation
    "breathing",  # gentle saturation/lightness pulse, ~0.1-0.3 Hz
    "drifting",  # slow hue drift, ~0.02-0.05 Hz
    "pulsing",  # rhythmic intensity pulse, synced to audio or beat
    "decaying",  # monotonic fade from intro level to steady level
]

# Working-mode affinity hint — NOT a hard gate.
WorkingModeAffinity = Literal["research", "rnd", "any"]


class PaletteResponseCurve(BaseModel):
    """The rendering math for a palette.

    Each curve mode reads a subset of ``params``. Params for unused
    modes are ignored by the evaluator — they exist so one record can
    describe a palette across multiple candidate modes during
    authoring, and so future mode additions don't require schema
    migrations.

    Typical params:

    - ``lab_shift``: ``delta_l``, ``delta_a``, ``delta_b``
    - ``duotone``: ``stop_low_lab`` (serialized as dict), ``stop_high_lab``
    - ``gradient_map``: ``stops`` (list of ``{t, lab}`` dicts)
    - ``hue_rotate``: ``degrees``
    - ``channel_mix``: ``rr``, ``rg``, ``rb``, ``gr``, ``gg``, ``gb``,
      ``br``, ``bg``, ``bb`` (3×3 matrix flattened)
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: PaletteCurveMode = "identity"
    # ``params`` holds mode-specific knobs. The shape is heterogeneous
    # by design: ``lab_shift`` uses floats; ``duotone`` uses list-valued
    # LAB triples; ``gradient_map`` nests a list of ``{t, lab}`` dicts.
    # The curve evaluator (Phase 3+) interprets the shape per-mode; the
    # schema stays permissive (``Any`` leaves) so author YAML is natural
    # and future modes can add fields without touching this file.
    params: dict[str, Any] = Field(default_factory=dict)
    preserve_luminance: bool = Field(
        default=False,
        description=(
            "When true, the curve output's L* is replaced by the input L*. "
            "Useful to keep legibility-critical features (glyph outlines) "
            "from dropping through the palette shift."
        ),
    )
    clip_s_curve: tuple[float, float] | None = Field(
        default=None,
        description=(
            "Optional (low, high) luminance clip applied after the curve. "
            "Softens extreme highlights / shadows to keep shader-combined "
            "frames from clipping during palette swaps. None = no clip."
        ),
    )


class ScrimPalette(BaseModel):
    """A named palette instance — a family member.

    The registry holds ~dozen of these at minimum. Each is self-describing
    (Hapax can read tags + axes + affinity to pick one by feel) and
    self-contained (curve + temporal profile fully specify the render).

    Equality is by ``id`` only; two palettes with the same id in
    different registry snapshots are considered equal for cache-key
    purposes. Hashing follows the same rule.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(..., min_length=1, max_length=64)
    display_name: str = Field(..., min_length=1)
    description: str = Field(default="")

    # Semantic descriptors (Hapax-recruitment surfaces).
    semantic_tags: tuple[str, ...] = Field(default_factory=tuple)
    working_mode_affinity: tuple[WorkingModeAffinity, ...] = Field(
        default=("any",),
        description=(
            "Working modes where this palette reads well — hint, not gate. "
            "Recruitment may pick it outside its affinity when tags match."
        ),
    )

    # Perceptual axes — descriptive, for recruitment / search.
    warmth_axis: float = Field(default=0.0, ge=-1.0, le=1.0)
    saturation_axis: float = Field(default=0.5, ge=0.0, le=1.0)
    lightness_axis: float = Field(default=0.0, ge=-1.0, le=1.0)

    # Colour anchors (LAB).
    dominant_lab: LabTriple = Field(default=(50.0, 0.0, 0.0))
    accent_lab: LabTriple = Field(default=(75.0, 0.0, 0.0))

    # Render math.
    curve: PaletteResponseCurve = Field(default_factory=PaletteResponseCurve)

    # Animation envelope.
    temporal_profile: TemporalProfile = "steady"
    temporal_rate_hz: float = Field(default=0.0, ge=0.0, le=10.0)

    def __hash__(self) -> int:
        # Frozen BaseModel hashing normally walks every field; palettes are
        # cache-keyed by id in the registry so we override to that alone.
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ScrimPalette):
            return NotImplemented
        return self.id == other.id


class PaletteChainStep(BaseModel):
    """One palette in a chain, plus its dwell + transition envelope.

    ``transition_mode`` vocabulary mirrors effect-preset transitions:

    - ``crossfade`` — dissolve over ``transition_s`` seconds
    - ``pierce`` — the next palette briefly dominates then settles (the
      scrim "pierce" gesture; see nebulous-scrim spec §11.4)
    - ``swap`` — instantaneous hard cut (discouraged outside ritual)
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    palette_id: str = Field(..., min_length=1, max_length=64)
    dwell_s: float = Field(..., gt=0.0, description="Time at this palette before transition.")
    transition_mode: Literal["crossfade", "pierce", "swap"] = "crossfade"
    transition_s: float = Field(
        default=1.5,
        ge=0.0,
        description="Duration of the transition INTO the next step. 0 with mode=swap for hard cuts.",
    )

    @model_validator(mode="after")
    def _validate_swap(self) -> PaletteChainStep:
        # Hard-cut invariant: ``swap`` mode must have zero transition_s.
        # Otherwise the transition is ambiguous — is it a swap or a
        # fast crossfade? The chain runner chooses based on mode.
        if self.transition_mode == "swap" and self.transition_s > 0.0:
            raise ValueError(
                f"palette chain step for '{self.palette_id}': "
                "transition_mode='swap' requires transition_s=0.0"
            )
        return self


class PaletteChain(BaseModel):
    """Ordered sequence of palettes with transition specs.

    Chains are the palette equivalent of preset chains — they let the
    scrim / mirror-emissive system move through a narrative palette arc
    (e.g., dawn → mid-day → dusk → night) without per-palette
    recruitment churn.

    A chain with ``loop=False`` terminates on its last step's dwell +
    transition, after which the chain runner falls back to the
    operator's default palette or retires. ``loop=True`` wraps to
    ``steps[0]`` indefinitely.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(..., min_length=1, max_length=64)
    display_name: str = Field(..., min_length=1)
    description: str = Field(default="")
    semantic_tags: tuple[str, ...] = Field(default_factory=tuple)

    steps: tuple[PaletteChainStep, ...] = Field(..., min_length=1)
    loop: bool = Field(
        default=True,
        description="When True the chain restarts at steps[0] after the last step.",
    )

    @model_validator(mode="after")
    def _validate_steps(self) -> PaletteChain:
        if not self.steps:
            raise ValueError(f"palette chain {self.id}: steps must be non-empty")
        return self


__all__ = [
    "LabTriple",
    "PaletteChain",
    "PaletteChainStep",
    "PaletteCurveMode",
    "PaletteResponseCurve",
    "ScrimPalette",
    "TemporalProfile",
    "WorkingModeAffinity",
]
