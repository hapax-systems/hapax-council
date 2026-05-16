"""Compositor data model — Source, Surface, Assignment, Layout.

The unified content abstraction for the studio compositor. A Source produces
pixels (camera, video, shader, image, text, cairo, external_rgba). A Surface
is a destination region (rect, tile, masked region, wgpu binding, video
output). An Assignment binds a Source to a Surface with per-assignment
transform, opacity, and effects.

A Layout collects Sources, Surfaces, and Assignments into a named scene
that can be loaded from JSON and swapped at runtime.

Phase 2 of the compositor unification epic. The model exists alongside
the existing rendering code; no rendering paths are migrated yet.
See docs/superpowers/specs/2026-04-12-phase-2-data-model-design.md
"""

from __future__ import annotations

import difflib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _closest_match_hint(bad_id: str, candidates: set[str], cutoff: float = 0.6) -> str:
    """Build a " (did you mean: 'x', 'y')" suffix for error messages.

    Uses :func:`difflib.get_close_matches` to find the closest existing
    IDs. Returns an empty string when nothing is close enough (``cutoff``
    controls the minimum similarity). Mainly called from
    :meth:`Layout._validate_references`.
    """
    matches = difflib.get_close_matches(bad_id, candidates, n=3, cutoff=cutoff)
    if not matches:
        return ""
    quoted = ", ".join(f"'{m}'" for m in matches)
    return f" (did you mean: {quoted}?)"


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

SourceKind = Literal[
    "camera",  # USB camera via v4l2 (current GStreamer ingest)
    "video",  # YouTube PiP via youtube-player + source protocol
    "shader",  # WGSL/GLSL shader (effect_graph node)
    "image",  # PNG/JPEG file with mtime cache
    "text",  # Pango-rendered text
    "cairo",  # Python Cairo surface (Sierpinski, AlbumOverlay, TokenPole)
    "external_rgba",  # Raw RGBA from /dev/shm source protocol
    "ndi",  # NDI input (Phase 5)
    "generative",  # legacy/offline generative sources; live shaders stay source-bound.
]

UpdateCadence = Literal["always", "on_change", "manual", "rate"]
"""How often a source should be sampled by the executor.

* ``"always"`` — re-sample on every compositor frame (current default for
  live camera inputs and shader nodes).
* ``"on_change"`` — re-sample only when upstream state changes. The
  source is responsible for signalling change (file mtime, dirty flag,
  ``cache-control`` header, etc.).
* ``"manual"`` — re-sample only when an external caller triggers an
  explicit refresh. Used for one-shot batch renders and hot-swapped
  shader graphs.
* ``"rate"`` — re-sample at a fixed rate in Hz. Requires
  :attr:`SourceSchema.rate_hz` to be set.
"""

SurfaceKind = Literal[
    "rect",  # Fixed rectangle on the canvas (x, y, w, h)
    "tile",  # Compositor tile (positioned by layout algorithm)
    "masked_region",  # Inscribed rect inside a mask shape (Sierpinski corner)
    "wgpu_binding",  # Named wgpu bind group entry (content_slot_*)
    "video_out",  # /dev/video42, NDI, OBS feed
    "ndi_out",  # NDI source advertisement (Phase 5)
    "fx_chain_input",  # Named GStreamer appsrc pad feeding glvideomixer.
    #                    Source-registry epic PR 1: every registered source
    #                    gets a persistent appsrc pad so preset chain switches
    #                    can select any source as a main-layer input. The
    #                    surface's ``id`` is the pad name; geometry fields
    #                    (x/y/w/h) are not used — alpha is controlled by the
    #                    glvideomixer sink-pad ``alpha`` property.
]

BlendMode = Literal["over", "plus", "in", "out", "atop"]


# ---------------------------------------------------------------------------
# Source — typed content producer
# ---------------------------------------------------------------------------


class SourceSchema(BaseModel):
    """A typed content producer with a schema.

    Sources don't know what surfaces they'll be assigned to. Surfaces don't
    know what sources will fill them. They meet at Assignment.

    The `backend` field is a dispatcher key consumed by the executor in
    Phase 3 — e.g. "wgsl_render", "cairo", "v4l2_camera", "pango_text".
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=64)
    kind: SourceKind
    backend: str
    params: dict[str, Any] = Field(default_factory=dict)
    update_cadence: UpdateCadence = Field(
        default="always",
        description=("When the executor should resample this source. See :data:`UpdateCadence`."),
    )
    rate_hz: float | None = Field(
        default=None,
        gt=0.0,
        description=(
            "Target sample rate in Hz. Required when ``update_cadence == 'rate'`` and "
            "must be unset otherwise — enforced by the ``_validate_rate`` model "
            "validator. ``None`` means 'no explicit rate', at which point the "
            "cadence's default sampling behavior applies."
        ),
    )
    tags: list[str] = Field(default_factory=list)

    # Video-container + mirror-emissive Phase 2 additions (2026-04-23).
    # ``pair_role`` defaults to ``solo`` so every existing source loads
    # unchanged; paired sources declare their leg + the ward identity
    # they belong to. See ``shared/ward_pair.py`` for the pair record
    # and :mod:`docs/superpowers/specs/2026-04-23-video-container-parallax-homage-spec`
    # §4.2 for the rationale.
    pair_role: Literal["solo", "paired"] = Field(
        default="solo",
        description=(
            "Whether this source stands alone or belongs to a WardPair. "
            "``solo`` (default) preserves legacy behaviour; ``paired`` requires "
            "``pair_leg`` and ``ward_id`` to be set."
        ),
    )
    pair_leg: Literal["video", "emissive"] | None = Field(
        default=None,
        description=(
            "Which leg of a WardPair this source is. Required when "
            "``pair_role='paired'``, forbidden otherwise."
        ),
    )
    ward_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description=(
            "Ward identity the source renders into. Required when "
            "``pair_role='paired'``; optional for solo sources (legacy "
            "wards pass None and rely on the source ID as ward identity)."
        ),
    )

    @model_validator(mode="after")
    def _validate_rate(self) -> SourceSchema:
        """Cadence/rate consistency check.

        ``update_cadence='rate'`` requires ``rate_hz`` to be set, and any
        other cadence forbids ``rate_hz``. This mirrors the executor's
        assumption: the ``rate`` cadence is the only path that reads
        ``rate_hz``, so a stray value under a different cadence would be
        silently ignored — we fail the schema instead of letting that
        through.
        """
        if self.update_cadence == "rate" and self.rate_hz is None:
            raise ValueError(f"source {self.id}: update_cadence='rate' requires rate_hz")
        if self.update_cadence != "rate" and self.rate_hz is not None:
            raise ValueError(f"source {self.id}: rate_hz only valid with update_cadence='rate'")
        # Paired-leg consistency check (Phase 2 of the video-container epic).
        # ``pair_leg`` and ``ward_id`` are mandatory when paired, forbidden
        # otherwise — otherwise a layout could declare a source as
        # ``paired`` without specifying which leg it is or what ward it
        # belongs to, which the pair renderer has no way to interpret.
        if self.pair_role == "paired":
            if self.pair_leg is None:
                raise ValueError(f"source {self.id}: pair_role='paired' requires pair_leg")
            if self.ward_id is None:
                raise ValueError(f"source {self.id}: pair_role='paired' requires ward_id")
        else:
            if self.pair_leg is not None:
                raise ValueError(f"source {self.id}: pair_leg only valid with pair_role='paired'")
        return self


# ---------------------------------------------------------------------------
# Surface — typed destination region
# ---------------------------------------------------------------------------


class SurfaceGeometry(BaseModel):
    """Geometric definition of a surface region.

    Different SurfaceKinds use different fields:
    - rect: x, y, w, h (absolute pixel coordinates)
    - tile: positioned by the compositor's layout algorithm at runtime
    - masked_region: mask name references a registered mask shape
    - wgpu_binding: binding_name is the wgpu bind group binding (e.g. content_slot_0)
    - video_out / ndi_out: ``target`` is the output device or NDI source
      name; ``render_target`` (Phase 5b2) is the render target name
      whose final output feeds this sink. Defaults to ``"main"`` so
      single-target layouts keep working.
    """

    model_config = ConfigDict(extra="forbid")

    kind: SurfaceKind
    x: int | None = None
    y: int | None = None
    w: int | None = None
    h: int | None = None
    mask: str | None = None
    binding_name: str | None = None
    target: str | None = None
    render_target: str | None = None


class SurfaceSchema(BaseModel):
    """A typed destination region with optional per-surface effect chain."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=64)
    geometry: SurfaceGeometry
    effect_chain: list[str] = Field(default_factory=list)
    blend_mode: BlendMode = "over"
    z_order: int = 0
    update_cadence: UpdateCadence = "always"


# ---------------------------------------------------------------------------
# Assignment — source-to-surface binding
# ---------------------------------------------------------------------------


RenderStage = Literal["pre_fx", "post_fx"]
"""Which cairooverlay callback an Assignment renders on.

* ``"post_fx"`` (default) — the assignment is blitted on the post-FX
  cairooverlay, after the glfeedback shader chain. This is the existing
  behavior for every Assignment (back-compat). Chrome wards belong here
  so shaders do not overwrite their content.
* ``"pre_fx"`` — the assignment is blitted on the BASE cairooverlay,
  before the shader chain. Substrate surfaces (camera PiPs, iconic
  Vitruvian figure, album art) belong here so shaders can decorate
  them. FINDING-W (ef7b-179) introduces this dimension.
"""


class Assignment(BaseModel):
    """Binding of source to surface with per-assignment overrides."""

    model_config = ConfigDict(extra="forbid")

    source: str
    surface: str
    transform: dict[str, float] = Field(default_factory=dict)
    opacity: float = Field(1.0, ge=0.0, le=1.0)
    per_assignment_effects: list[str] = Field(default_factory=list)
    non_destructive: bool = Field(
        default=False,
        description=(
            "Task #157: when True, the compositor clamps this assignment's "
            "rendered alpha to a ceiling of 0.6 so the underlying video "
            "content stays at least 0.4 visible. Wards and other "
            "informational overlays that composite over camera PiPs set "
            "this flag so the camera underneath remains recognizable. "
            "Default False keeps existing layouts byte-identical."
        ),
    )
    render_stage: RenderStage = Field(
        default="post_fx",
        description=(
            "FINDING-W (ef7b-179): which cairooverlay callback this "
            "assignment renders on. ``post_fx`` (default, back-compat) "
            "renders after the shader chain so chrome stays crisp. "
            "``pre_fx`` renders before the shader chain so substrate "
            "surfaces (camera PiPs, iconic Vitruvian figure, album art) "
            "are decorated by the shaders."
        ),
    )


# ---------------------------------------------------------------------------
# Layout — named scene
# ---------------------------------------------------------------------------


class Layout(BaseModel):
    """A named scene composed of sources, surfaces, and assignments.

    Layouts are stored as JSON files at ~/.config/hapax-compositor/layouts/
    and loaded by the LayoutStore at startup.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=64)
    description: str = ""
    sources: list[SourceSchema]
    surfaces: list[SurfaceSchema]
    assignments: list[Assignment]

    @model_validator(mode="after")
    def _validate_references(self) -> Layout:
        source_ids = {s.id for s in self.sources}
        surface_ids = {s.id for s in self.surfaces}
        if len(source_ids) != len(self.sources):
            raise ValueError(f"layout {self.name!r}: duplicate source IDs")
        if len(surface_ids) != len(self.surfaces):
            raise ValueError(f"layout {self.name!r}: duplicate surface IDs")
        for a in self.assignments:
            if a.source not in source_ids:
                hint = _closest_match_hint(a.source, source_ids)
                raise ValueError(
                    f"layout {self.name!r}: assignment references unknown source: {a.source}{hint}"
                )
            if a.surface not in surface_ids:
                hint = _closest_match_hint(a.surface, surface_ids)
                raise ValueError(
                    f"layout {self.name!r}: assignment references unknown surface: "
                    f"{a.surface}{hint}"
                )
        return self

    def video_outputs(self) -> list[SurfaceSchema]:
        """Return surfaces whose geometry kind is ``video_out``.

        Phase 5b2: the OutputRouter (Phase 5b3) consumes this list to
        wire each output sink to the render target named by the
        surface's ``geometry.render_target`` field (default ``"main"``).
        Surfaces are returned in stable layout order so the resulting
        sink ordering is reproducible.
        """
        return [s for s in self.surfaces if s.geometry.kind == "video_out"]

    # ------------------------------------------------------------------
    # Convenience lookups (audit follow-up)
    # ------------------------------------------------------------------
    #
    # Phase 2-7 audit identified that every consumer (compile.py,
    # OutputRouter, future executor) reinvents the same iteration
    # patterns over sources/surfaces/assignments. These helpers
    # consolidate the lookups in one place.

    def source_by_id(self, source_id: str) -> SourceSchema | None:
        """Return the source with ``source_id``, or None if not present.

        O(n) scan over ``self.sources``. Layouts are small (tens of
        sources at most) so the linear scan is the right call —
        building an index would add complexity for negligible gain.
        """
        for source in self.sources:
            if source.id == source_id:
                return source
        return None

    def surface_by_id(self, surface_id: str) -> SurfaceSchema | None:
        """Return the surface with ``surface_id``, or None if not present."""
        for surface in self.surfaces:
            if surface.id == surface_id:
                return surface
        return None

    def assignments_for_source(self, source_id: str) -> list[Assignment]:
        """Return every assignment whose source is ``source_id``.

        Returned in stable layout order. Empty list if the source has
        no assignments (e.g. it's culled this layout).
        """
        return [a for a in self.assignments if a.source == source_id]

    def assignments_for_surface(self, surface_id: str) -> list[Assignment]:
        """Return every assignment whose surface is ``surface_id``.

        Returned in stable layout order. Multiple assignments may
        target the same surface (Phase 4 dedup will compose them by
        z_order + opacity).
        """
        return [a for a in self.assignments if a.surface == surface_id]

    def render_targets(self) -> tuple[str, ...]:
        """Return the sorted set of render target names declared by
        any ``video_out`` surface in this layout.

        Computed by walking ``video_outputs()`` and collecting the
        ``geometry.render_target`` value of each (defaulting to
        ``"main"`` for surfaces that omit it). The OutputRouter and
        future multi-target executor consume this to know which
        targets the host needs to wire.
        """
        names = {(s.geometry.render_target or "main") for s in self.video_outputs()}
        return tuple(sorted(names))
