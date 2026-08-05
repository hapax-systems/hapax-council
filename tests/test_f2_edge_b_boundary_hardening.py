"""Edge B hardening: evidence-only cannot enter demand/supply paths via alternate identity.

Extends #4503 boundary suite + DemandShapeRef identity law for F2 residual.
"""

from __future__ import annotations

from shared.agentic_trust_boundary import (
    AGENTIC_TRUST_EVIDENCE_RECEIPT_CLASS,
    AGENTIC_TRUST_EVIDENCE_SURFACE_ID,
    agentic_trust_supply_evidence_paths,
    is_agentic_trust_supply_evidence_reference,
    normalize_supply_admission_identity,
)
from shared.capability_onboarding_classify import classify_onboarding_surface
from shared.demand_shape_ref import demand_shape_ref_from_parts
from shared.sdlc_router import REQUIREMENT_VECTOR_DIMENSIONS

_VECTOR = {dim: 3 for dim in REQUIREMENT_VECTOR_DIMENSIONS}
_CONSTRAINT = {
    "mutation_surface": "source",
    "authority_level": "support_non_authoritative",
    "routing_class": "source_python",
}


def test_alternate_surface_prefix_still_evidence_identity() -> None:
    for spelling in (
        AGENTIC_TRUST_EVIDENCE_SURFACE_ID,
        f"surface.{AGENTIC_TRUST_EVIDENCE_SURFACE_ID}",
        f"route.{AGENTIC_TRUST_EVIDENCE_SURFACE_ID}",
        AGENTIC_TRUST_EVIDENCE_SURFACE_ID.upper(),
    ):
        assert is_agentic_trust_supply_evidence_reference(spelling) or (
            normalize_supply_admission_identity(spelling) == AGENTIC_TRUST_EVIDENCE_SURFACE_ID
        )
        result = classify_onboarding_surface(
            surface_id=spelling,
            modal_class="permitted",
            measurement_sufficiency="complete",
            equal_definition_complete=True,
            demand_eligible_candidate=True,
        )
        assert result["disposition"] == "evidence_only"
        assert result["may_fulfill_demand"] is False


def test_receipt_class_string_cannot_smuggle_into_demand_fulfillment() -> None:
    result = classify_onboarding_surface(
        surface_id="innocent.route.id",
        evidence_refs=[
            f"{AGENTIC_TRUST_EVIDENCE_RECEIPT_CLASS}:deadbeef",
            "sha256:not-this-one",
        ],
        modal_class="permitted",
        measurement_sufficiency="complete",
        equal_definition_complete=True,
        demand_eligible_candidate=True,
    )
    assert result["disposition"] == "evidence_only"
    assert result["may_fulfill_demand"] is False


def test_nested_supply_payload_paths_locate_observation_refs() -> None:
    payload = {
        "route_id": "codex.headless.full",
        "quality_envelope": {
            "evidence_refs": [
                f"surface.{AGENTIC_TRUST_EVIDENCE_SURFACE_ID}",
            ]
        },
        "nested": {"non_supply_evidence_ref": "AgenticTrustEvidenceReceiptV1:x"},
    }
    paths = agentic_trust_supply_evidence_paths(payload)
    assert any("evidence_refs" in p for p in paths)
    assert any("non_supply_evidence_ref" in p for p in paths)


def test_demand_shape_ref_does_not_absorb_evidence_only_identity() -> None:
    """DemandShapeRef is demand-side; evidence-only surface ids never appear in the ref preimage."""
    ref = demand_shape_ref_from_parts(
        requirement_vector=_VECTOR,
        constraint=_CONSTRAINT,
    )
    assert AGENTIC_TRUST_EVIDENCE_SURFACE_ID not in ref
    assert "agentic" not in ref.lower()
    # Completing a DemandShapeRef must not grant admit_supply to an evidence-only surface
    result = classify_onboarding_surface(
        surface_id=AGENTIC_TRUST_EVIDENCE_SURFACE_ID,
        modal_class="permitted",
        measurement_sufficiency="complete",
        equal_definition_complete=True,
        demand_eligible_candidate=True,
        notes={"demand_shape_ref": ref},
    )
    assert result["disposition"] == "evidence_only"
    assert result["may_fulfill_demand"] is False


def test_forbidden_collapse_explore_to_admit_is_impossible_under_partial() -> None:
    """Under-measured surfaces stay EXPLORE even when demand_eligible is asserted."""
    result = classify_onboarding_surface(
        surface_id="new.capability.slice",
        modal_class="permitted",
        measurement_sufficiency="partial",
        equal_definition_complete=True,
        demand_eligible_candidate=True,
    )
    assert result["disposition"] == "EXPLORE"
    assert result["may_fulfill_demand"] is False
