"""Shared enhancement technique taxonomy (HOMAGE Ward Umbrella Phase 2).

Spec reference:
    docs/superpowers/specs/2026-04-20-homage-ward-umbrella-design.md §5

Single source of truth for all enhancement techniques. Ward enhancement
profiles bind to names here; they never invent diverging ones. Phase 2
ships the minimal set to unlock CBIP + Vitruvian annexes (4 techniques
+ 1 pre-existing remap). Later phases append.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["palette", "spatial", "temporal", "artifact", "compositional"]


class Technique(BaseModel):
    """A single enhancement technique."""

    name: str = Field(..., description="Technique identifier, e.g. 'posterize'.")
    node_ids: list[str] = Field(
        ...,
        description=("Effect-graph node IDs this technique compiles to (existing or new)."),
    )
    recognizability_risk: int = Field(
        ...,
        ge=0,
        le=5,
        description=("Risk score 0 (no impact on recognizability) to 5 (defeats it)."),
    )
    hardm_compatible: bool = Field(
        default=True,
        description="Whether technique aligns with HARDM anti-anthropomorphization.",
    )
    applicable_wards: list[str] = Field(
        default_factory=list,
        description=(
            "Ward IDs where this technique is safe. Empty means all wards not in rejected_wards."
        ),
    )
    rejected_wards: list[str] = Field(
        default_factory=list,
        description="Ward IDs where this technique is unsafe.",
    )
    notes: str = Field(
        default="",
        description="Implementation notes, cost estimate, caching strategy.",
    )


class TechniqueFamily(BaseModel):
    """A grouping of related techniques sharing a transformation class."""

    family_name: str
    category: Category
    techniques: list[Technique]


class TechniqueTaxonomy(BaseModel):
    """Master registry of enhancement techniques."""

    families: dict[str, TechniqueFamily] = Field(default_factory=dict)

    @classmethod
    def load(cls) -> TechniqueTaxonomy:
        """Canonical taxonomy (hardcoded; ships with Phase 2 set)."""
        families: dict[str, TechniqueFamily] = {
            "palette_transformations": TechniqueFamily(
                family_name="Palette transformations",
                category="palette",
                techniques=[
                    Technique(
                        name="remap",
                        node_ids=["colorgrade"],
                        recognizability_risk=1,
                        hardm_compatible=True,
                        applicable_wards=["album"],
                        notes=(
                            "Lookup-table recolor via existing colorgrade node. "
                            "Safe under OQ-02 brightness ceiling."
                        ),
                    ),
                    Technique(
                        name="posterize",
                        node_ids=["posterize"],
                        recognizability_risk=2,
                        hardm_compatible=True,
                        applicable_wards=["album", "sierpinski"],
                        notes=(
                            "Collapse palette to 4-8 colors via ordered Bayer "
                            "dither. CBIP-aligned. Target SSIM >=0.7."
                        ),
                    ),
                    Technique(
                        name="palette_extract",
                        node_ids=["palette_extract"],
                        recognizability_risk=1,
                        hardm_compatible=True,
                        applicable_wards=["album"],
                        notes=(
                            "K-means dominant-color extraction; render as "
                            "swatch grid. Non-destructive; contextualization move."
                        ),
                    ),
                ],
            ),
            "spatial_transformations": TechniqueFamily(
                family_name="Spatial transformations",
                category="spatial",
                techniques=[
                    Technique(
                        name="edge_detect",
                        node_ids=["edge_detect"],
                        recognizability_risk=2,
                        hardm_compatible=True,
                        applicable_wards=["album", "sierpinski"],
                        notes=(
                            "Sobel/Laplacian contours composited over posterized "
                            "interior. <100ms at 1280x720."
                        ),
                    ),
                    Technique(
                        name="kuwahara",
                        node_ids=["kuwahara"],
                        recognizability_risk=2,
                        hardm_compatible=True,
                        applicable_wards=["album", "sierpinski"],
                        notes=(
                            "Edge-preserving painterly blur via quadrant "
                            "min-variance. O(W*H*k^2); ~300ms at 1280x720; "
                            "cache-only for deliberative mode."
                        ),
                    ),
                ],
            ),
        }
        return cls(families=families)

    def get_family(self, family_name: str) -> TechniqueFamily | None:
        return self.families.get(family_name)

    def get_technique(self, technique_name: str) -> Technique | None:
        for family in self.families.values():
            for tech in family.techniques:
                if tech.name == technique_name:
                    return tech
        return None

    def get_applicable_techniques_for_ward(self, ward_id: str) -> list[Technique]:
        applicable: list[Technique] = []
        for family in self.families.values():
            for tech in family.techniques:
                if ward_id in tech.rejected_wards:
                    continue
                if tech.applicable_wards and ward_id not in tech.applicable_wards:
                    continue
                applicable.append(tech)
        return applicable
