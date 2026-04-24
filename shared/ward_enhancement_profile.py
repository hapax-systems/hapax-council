"""WardEnhancementProfile: gating schema for ward enhancement PRs.

Every enhancement PR that modifies a ward's visual grammar must instantiate
and pass this schema. It enforces that recognizability invariants and
use-case acceptance tests are declared and (before merge) confirmed.

Reference:
    docs/superpowers/specs/2026-04-20-homage-ward-umbrella-design.md §4.2
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class WardEnhancementProfile(BaseModel):
    """Gate-keeping schema for ward enhancement work.

    Spec: `docs/superpowers/specs/2026-04-20-homage-ward-umbrella-design.md`
    §4.2. Each ward in the 15-ward catalog has exactly one profile; any
    enhancement / spatial-dynamism / effect-processing change must declare
    its impact against the profile's fields and pass the ward's acceptance
    test harness before merging.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "ward_id": "album",
                "recognizability_invariant": (
                    "Album title >=80% OCR; dominant contours edge-IoU >=0.65"
                ),
                "recognizability_tests": ["ocr_accuracy", "edge_iou"],
                "use_case_acceptance_test": "Operator identifies album at glance",
                "acceptance_test_harness": "tests/studio_compositor/test_album_acceptance.py",
                "accepted_enhancement_categories": ["posterize", "kuwahara"],
                "rejected_enhancement_categories": ["lens_distortion"],
                "spatial_dynamism_approved": True,
                "oq_02_bound_applicable": True,
                "hardm_binding": False,
                "cvs_bindings": ["CVS #8", "CVS #16"],
            }
        },
    )

    ward_id: str = Field(
        ...,
        description="Ward identifier (e.g., 'album', 'token_pole').",
    )
    recognizability_invariant: str = Field(
        ...,
        description=(
            "Prose property that must remain true for the ward to read as "
            "itself under any enhancement (spec §4.1)."
        ),
    )
    recognizability_tests: list[str] = Field(
        default_factory=list,
        description=(
            "Automated test identifiers — e.g. 'ocr_accuracy', 'edge_iou', "
            "'palette_delta_e', 'pearson_face_correlation'."
        ),
    )
    use_case_acceptance_test: str = Field(
        ...,
        description=(
            "What the operator / audience must be able to do with the ward "
            "for it to fulfill its communicative role (spec §4.1)."
        ),
    )
    acceptance_test_harness: str = Field(
        default="",
        description=(
            "Path to the acceptance-test script, e.g. "
            "'tests/studio_compositor/test_album_acceptance.py'."
        ),
    )
    accepted_enhancement_categories: list[str] = Field(
        default_factory=list,
        description="Subset of spec §5 technique families safe for this ward.",
    )
    rejected_enhancement_categories: list[str] = Field(
        default_factory=list,
        description="Technique families that violate this ward's invariants.",
    )
    spatial_dynamism_approved: bool = Field(
        default=False,
        description=(
            "Whether spatial-dynamism enhancements (depth, parallax, motion, "
            "placement drift) are approved for this ward."
        ),
    )
    oq_02_bound_applicable: bool = Field(
        default=True,
        description=(
            "Whether OQ-02 three-bound gates apply (anti-recognition, "
            "anti-opacity, anti-visualizer)."
        ),
    )
    hardm_binding: bool = Field(
        default=False,
        description=(
            "Whether the anti-anthropomorphization binding applies. "
            "Originally introduced for HARDM; HARDM retired 2026-04-23 "
            "(GEAL spec §12), and GEAL inherits the same 10-invariant "
            "gate — the field name is kept for backwards compatibility."
        ),
    )
    cvs_bindings: list[str] = Field(
        default_factory=list,
        description=(
            "CVS axiom bindings — e.g. ['CVS #8', 'CVS #16'] for "
            "non-manipulation + anti-personification."
        ),
    )
    deprecation: str | None = Field(
        default=None,
        description=(
            "If set, marks the ward as scheduled for retirement and "
            "explains the migration path. Used to keep the umbrella "
            "governance gate covering the live render path while a "
            "replacement ward is brought up — captions / GEM cutover "
            "is the founding example."
        ),
    )


class WardEnhancementProfileRegistry:
    """In-memory registry of ward enhancement profiles loaded from YAML.

    The YAML config at ``config/ward_enhancement_profiles.yaml`` is the
    operator-editable declarative binding of ward → profile. Ward IDs
    become top-level keys under ``wards:``; each entry's fields match
    ``WardEnhancementProfile``.
    """

    def __init__(self, profiles: dict[str, WardEnhancementProfile]) -> None:
        self.profiles = profiles

    @classmethod
    def load_from_yaml(cls, yaml_path: str | Path) -> WardEnhancementProfileRegistry:
        path = Path(yaml_path)
        if not path.exists():
            raise FileNotFoundError(f"Ward enhancement profile config not found: {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        profiles: dict[str, WardEnhancementProfile] = {}
        for ward_id, ward_data in (data.get("wards") or {}).items():
            profiles[ward_id] = WardEnhancementProfile(ward_id=ward_id, **(ward_data or {}))
        return cls(profiles)

    def get(self, ward_id: str) -> WardEnhancementProfile | None:
        return self.profiles.get(ward_id)

    def list_wards(self) -> list[str]:
        return list(self.profiles.keys())
