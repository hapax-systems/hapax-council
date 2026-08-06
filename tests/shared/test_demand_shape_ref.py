"""Golden tests for DemandShapeRef (Edge A §2.2 / Edge C).

Digests pinned against ``stable_payload_hash`` on origin/main as of Edge A authoring.
"""

from __future__ import annotations

import pytest

from shared.demand_shape_ref import (
    DEFAULT_BASIS,
    SCHEMA_V0,
    build_demand_shape_ref_payload,
    demand_shape_ref,
    demand_shape_ref_from_parts,
)
from shared.sdlc_router import REQUIREMENT_VECTOR_DIMENSIONS

# Edge A §2.2 goldens (must not drift without explicit design amend + golden bump)
G1_DIGEST = "sha256:b246f6777e4c387a490c079ed045b7f9072fb02f925af9e2e1703234632f7597"
G2_DIGEST = "sha256:6eefd03216bb8c2f4602a5e2cd558abc1261bf62a9572c98d2c6bc76962730ca"
G3_DIGEST = "sha256:2c3674e465e9eae35362c7645c7d81b4dbb7dfd90769b8355e180fbdd3b69560"

_G1_VECTOR = {
    "quality_floor": 3,
    "information_scope": 2,
    "context_length": 2,
    "mutation_risk": 1,
    "verification_demand": 3,
    "ambiguity_novelty": 2,
    "composition_coupling": 1,
    "governance_sensitivity": 2,
}
_CONSTRAINT = {
    "mutation_surface": "source",
    "authority_level": "support_non_authoritative",
    "routing_class": "appendix_evidence_capture",
}


def test_g1_typical_mid_floor_digest() -> None:
    ref = demand_shape_ref_from_parts(
        requirement_vector=_G1_VECTOR,
        constraint=_CONSTRAINT,
        basis=DEFAULT_BASIS,
    )
    assert ref == G1_DIGEST


def test_g2_all_zero_floors_digest() -> None:
    zeros = {k: 0 for k in REQUIREMENT_VECTOR_DIMENSIONS}
    ref = demand_shape_ref_from_parts(
        requirement_vector=zeros,
        constraint=_CONSTRAINT,
        basis=DEFAULT_BASIS,
    )
    assert ref == G2_DIGEST


def test_g3_single_dimension_mutation_digest() -> None:
    mutated = dict(_G1_VECTOR)
    mutated["mutation_risk"] = 2
    ref = demand_shape_ref_from_parts(
        requirement_vector=mutated,
        constraint=_CONSTRAINT,
        basis=DEFAULT_BASIS,
    )
    assert ref == G3_DIGEST


def test_goldens_are_pairwise_distinct() -> None:
    assert len({G1_DIGEST, G2_DIGEST, G3_DIGEST}) == 3


def test_demand_shape_ref_revalidates_payload() -> None:
    payload = build_demand_shape_ref_payload(
        requirement_vector=_G1_VECTOR,
        constraint=_CONSTRAINT,
    )
    assert demand_shape_ref(payload) == G1_DIGEST
    assert payload["schema"] == SCHEMA_V0


def test_key_order_does_not_change_digest() -> None:
    # reversed insertion order must still hash identically (sort_keys)
    shuffled = {
        "governance_sensitivity": 2,
        "composition_coupling": 1,
        "ambiguity_novelty": 2,
        "verification_demand": 3,
        "mutation_risk": 1,
        "context_length": 2,
        "information_scope": 2,
        "quality_floor": 3,
    }
    assert (
        demand_shape_ref_from_parts(
            requirement_vector=shuffled,
            constraint=_CONSTRAINT,
        )
        == G1_DIGEST
    )


@pytest.mark.parametrize(
    "bad_vector",
    [
        {k: 0 for k in REQUIREMENT_VECTOR_DIMENSIONS if k != "mutation_risk"},  # missing
        {**_G1_VECTOR, "extra_dim": 1},  # unknown
        {**_G1_VECTOR, "mutation_risk": True},  # bool
        {**_G1_VECTOR, "mutation_risk": 3.0},  # float
        {**_G1_VECTOR, "mutation_risk": -1},
        {**_G1_VECTOR, "mutation_risk": 6},
    ],
)
def test_g4_negative_vector_fail_closed(bad_vector: dict) -> None:
    with pytest.raises(ValueError):
        demand_shape_ref_from_parts(
            requirement_vector=bad_vector,
            constraint=_CONSTRAINT,
        )


@pytest.mark.parametrize(
    "bad_constraint",
    [
        {"mutation_surface": "source", "authority_level": "support_non_authoritative"},
        {**_CONSTRAINT, "extra": "x"},
        {**_CONSTRAINT, "mutation_surface": ""},
        {**_CONSTRAINT, "mutation_surface": 1},
    ],
)
def test_g4_negative_constraint_fail_closed(bad_constraint: dict) -> None:
    with pytest.raises(ValueError):
        demand_shape_ref_from_parts(
            requirement_vector=_G1_VECTOR,
            constraint=bad_constraint,
        )


def test_empty_basis_fail_closed() -> None:
    with pytest.raises(ValueError, match="basis"):
        demand_shape_ref_from_parts(
            requirement_vector=_G1_VECTOR,
            constraint=_CONSTRAINT,
            basis="  ",
        )


def test_no_live_route_or_registry_import_side_effects() -> None:
    """Module must remain pure: import only hash + dimension SSOT."""
    import shared.demand_shape_ref as mod

    src = open(mod.__file__, encoding="utf-8").read()
    assert "platform_capability_registry" not in src
    assert "SdlcRouter(" not in src
    assert "evaluate_dispatch" not in src
