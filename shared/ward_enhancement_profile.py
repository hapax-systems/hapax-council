"""WardEnhancementProfile: gating schema for ward enhancement PRs.

Every enhancement PR that modifies a ward's visual grammar must instantiate
and pass this schema. It enforces that recognizability invariants and
use-case acceptance tests are declared and (before merge) confirmed.

Reference:
    docs/superpowers/specs/2026-04-20-homage-ward-umbrella-design.md §4.2
"""

from __future__ import annotations

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
            "Whether HARDM anti-anthropomorphization binding applies "
            "(notably token_pole, hardm_dot_matrix)."
        ),
    )
    cvs_bindings: list[str] = Field(
        default_factory=list,
        description=(
            "CVS axiom bindings — e.g. ['CVS #8', 'CVS #16'] for "
            "non-manipulation + anti-personification."
        ),
    )
