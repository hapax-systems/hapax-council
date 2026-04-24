"""Ward pair record — video leg + mirror-emissive leg at one semantic slot.

Phase 2 of the video-container + mirror-emissive HOMAGE epic. Every
ward in the rebuilt system is either ``solo`` (a single SourceSchema,
legacy behaviour) or ``paired`` — a video leg that displays live / cam
/ recorded content, plus a mirror-emissive leg that renders a
complementary HOMAGE readout at the same semantic slot.

## Complementarity

The emissive leg doesn't just overlay the video; it *responds* to it.
Five complementarity modes describe the response shape:

- ``palette_sync`` — emissive colours sampled from the video substrate
  and pushed through the pair's ``PaletteResponse`` curve. Preserves
  glyph structure, breathes colour with the video.
- ``luminance_only`` — emissive keeps its own structure and luminance,
  video contributes only the value channel (useful for B&W source
  material).
- ``texture_density_map`` — emissive glyph density / line weight is
  modulated by video contrast per-region (dense areas → dense marks).
- ``structural_response`` — emissive marks are placed along edges
  detected in the video (Sobel once per tick).
- ``independent`` — emissive renders without consulting the video,
  legacy behaviour for packages that don't want the coupling.

The mode is declared once per pair; Phase 3+ renderers consume it.

## Identity

A pair's ``pair_id`` is stable across compositor restarts — it's the
join key for ward properties that apply to the pair as a whole (e.g.,
``front_state``). Pair records live in the layout JSON next to
:class:`~shared.compositor_model.SourceSchema` entries; each SourceSchema
referenced by a pair carries ``pair_role="paired"`` and a matching
``pair_leg``.

## Invariants

- ``video_leg_source_id`` and ``emissive_leg_source_id`` both non-empty.
- The two leg source IDs differ (same-id would be a config error).
- ``palette_response`` is set iff ``complementarity_mode="palette_sync"``
  — the response curve is what ``palette_sync`` uses; other modes have
  their own (non-palette) rendering math that the pair record doesn't
  describe.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.palette_response import PaletteResponse

ComplementarityMode = Literal[
    "palette_sync",
    "luminance_only",
    "texture_density_map",
    "structural_response",
    "independent",
]


class WardPair(BaseModel):
    """Record linking a video leg and an emissive leg at one ward slot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pair_id: str = Field(..., min_length=1, max_length=64)
    ward_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description=(
            "Ward identity the pair belongs to; ``ward_properties.json`` "
            "entries keyed by ``ward_id`` apply to both legs."
        ),
    )
    video_leg_source_id: str = Field(..., min_length=1, max_length=64)
    emissive_leg_source_id: str = Field(..., min_length=1, max_length=64)

    complementarity_mode: ComplementarityMode = "palette_sync"
    palette_response: PaletteResponse | None = Field(
        default=None,
        description=(
            "Palette binding for ``palette_sync`` mode. Must be None for "
            "other modes (their rendering math is declared elsewhere)."
        ),
    )

    @model_validator(mode="after")
    def _validate_pair(self) -> WardPair:
        if self.video_leg_source_id == self.emissive_leg_source_id:
            raise ValueError(
                f"pair {self.pair_id}: video and emissive leg source IDs must differ "
                f"(both are {self.video_leg_source_id!r})"
            )
        if self.complementarity_mode == "palette_sync":
            if self.palette_response is None:
                raise ValueError(
                    f"pair {self.pair_id}: complementarity_mode='palette_sync' "
                    "requires palette_response"
                )
        elif self.palette_response is not None:
            raise ValueError(
                f"pair {self.pair_id}: palette_response only valid with "
                "complementarity_mode='palette_sync' "
                f"(got mode={self.complementarity_mode!r})"
            )
        return self


__all__ = ["ComplementarityMode", "WardPair"]
