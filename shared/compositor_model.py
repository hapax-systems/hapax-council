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

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    "generative",  # noise_gen, solid, waveform_render
]

UpdateCadence = Literal["always", "on_change", "manual", "rate"]

SurfaceKind = Literal[
    "rect",  # Fixed rectangle on the canvas (x, y, w, h)
    "tile",  # Compositor tile (positioned by layout algorithm)
    "masked_region",  # Inscribed rect inside a mask shape (Sierpinski corner)
    "wgpu_binding",  # Named wgpu bind group entry (content_slot_*)
    "video_out",  # /dev/video42, NDI, OBS feed
    "ndi_out",  # NDI source advertisement (Phase 5)
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
    update_cadence: UpdateCadence = "always"
    rate_hz: float | None = None
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_rate(self) -> SourceSchema:
        if self.update_cadence == "rate" and self.rate_hz is None:
            raise ValueError(f"source {self.id}: update_cadence='rate' requires rate_hz")
        if self.update_cadence != "rate" and self.rate_hz is not None:
            raise ValueError(f"source {self.id}: rate_hz only valid with update_cadence='rate'")
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
    - video_out / ndi_out: target is the output device or NDI source name
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


class Assignment(BaseModel):
    """Binding of source to surface with per-assignment overrides."""

    model_config = ConfigDict(extra="forbid")

    source: str
    surface: str
    transform: dict[str, float] = Field(default_factory=dict)
    opacity: float = Field(1.0, ge=0.0, le=1.0)
    per_assignment_effects: list[str] = Field(default_factory=list)


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
                raise ValueError(
                    f"layout {self.name!r}: assignment references unknown source: {a.source}"
                )
            if a.surface not in surface_ids:
                raise ValueError(
                    f"layout {self.name!r}: assignment references unknown surface: {a.surface}"
                )
        return self
