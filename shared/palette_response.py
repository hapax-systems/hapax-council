"""Palette response — how a HomagePackage binds to the palette family.

This is the glue between the palette-family registry
(:mod:`shared.palette_family`) and the HOMAGE package descriptor. A
package declares *what* palette behaviour it wants (sync to the video
substrate, duotone its luminance, walk a chain over time); the response
record points at the palette or chain that provides it.

## Selection modes

A response targets EITHER a single palette OR a chain:

- ``palette_id`` set, ``palette_chain_id`` unset → single palette
- ``palette_chain_id`` set, ``palette_id`` unset → chain
- both set or both unset → schema error

The chain-selection path hands the active palette to the curve
evaluator every render tick; the consumer doesn't need to know whether
it's looking at a single or a chain.

## Sampling (palette_sync mode)

When the emissive leg tracks the video substrate's dominant colour
(``complementarity_mode="palette_sync"`` on the pair), the sampling
geometry lives here — where to sample from, how big a kernel, how to
weight the LAB channels.

- ``sample_points`` are normalised coords ``(u, v)`` in ``[0, 1]²``. The
  evaluator averages the kernel around each point, weights by
  ``sample_weights`` (default uniform), and produces the input colour
  for the palette curve.
- ``sample_size_px`` is the square kernel width.
- ``lab_weights`` modulates the output LAB channels before the emissive
  leg writes them — e.g., ``(1.0, 0.6, 0.6)`` preserves luminance while
  desaturating chroma response.

All sampling fields are ignored for non-sampling curve modes
(``duotone``, ``gradient_map``, etc. work directly on the emissive
leg's own luminance).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Sampling coordinate, normalised to [0, 1]².
SamplePoint = tuple[float, float]


class PaletteResponse(BaseModel):
    """Binds a HomagePackage to a palette family entry.

    Extra fields refused: the schema is the contract between package
    authors and the render path. Additions land here, not in ad-hoc
    ``params`` blobs elsewhere.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["palette_sync", "luminance_only", "duotone"] = Field(
        default="palette_sync",
        description=(
            "How the emissive leg relates to the video substrate:\n"
            "- palette_sync: sample the video, run through the palette curve\n"
            "- luminance_only: preserve video luminance, recolor via palette\n"
            "- duotone: map the emissive's own luminance through a 2-stop "
            "gradient derived from the palette's dominant + accent LAB"
        ),
    )

    # Exactly one of these two is set.
    palette_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="Registry ID of a single ``ScrimPalette``.",
    )
    palette_chain_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="Registry ID of a ``PaletteChain``; mutually exclusive with palette_id.",
    )

    # Sampling — only used when mode == "palette_sync".
    sample_points: tuple[SamplePoint, ...] = Field(
        default=((0.5, 0.5),),
        description=(
            "Normalised (u, v) coordinates in [0, 1]² to sample the video "
            "substrate at. Default is a single centre sample. Multi-point "
            "samples produce an averaged LAB input to the curve."
        ),
    )
    sample_weights: tuple[float, ...] | None = Field(
        default=None,
        description=(
            "Per-sample weights (must match ``sample_points`` length). None = uniform weighting."
        ),
    )
    sample_size_px: int = Field(
        default=32,
        ge=1,
        le=512,
        description="Square kernel width (pixels) around each sample point.",
    )
    lab_weights: tuple[float, float, float] = Field(
        default=(1.0, 1.0, 1.0),
        description=(
            "Per-channel (L*, a*, b*) multipliers applied to the curve "
            "output before the emissive leg draws. (1, 1, 1) = no scaling."
        ),
    )

    @model_validator(mode="after")
    def _validate_target(self) -> PaletteResponse:
        # Exactly-one-of invariant.
        has_palette = self.palette_id is not None
        has_chain = self.palette_chain_id is not None
        if has_palette == has_chain:
            raise ValueError(
                "PaletteResponse must set exactly one of palette_id or palette_chain_id "
                f"(got palette_id={self.palette_id!r}, palette_chain_id={self.palette_chain_id!r})"
            )

        # Sample weights must match point count if provided.
        if self.sample_weights is not None:
            if len(self.sample_weights) != len(self.sample_points):
                raise ValueError(
                    f"sample_weights length {len(self.sample_weights)} != "
                    f"sample_points length {len(self.sample_points)}"
                )
            if any(w < 0.0 for w in self.sample_weights):
                raise ValueError("sample_weights entries must be >= 0.0")

        # Sample points must lie in the unit square.
        for idx, (u, v) in enumerate(self.sample_points):
            if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
                raise ValueError(f"sample_points[{idx}] = ({u}, {v}) outside [0, 1]²")

        return self


__all__ = ["PaletteResponse", "SamplePoint"]
