"""Pure onboarding classify — Edge A §3 / F2 residual after #4503+#4504."""

from __future__ import annotations

import pytest

from shared.agentic_trust_boundary import AGENTIC_TRUST_EVIDENCE_SURFACE_ID
from shared.capability_onboarding_classify import (
    ADMISSION_TUPLE_SCHEMA,
    SCHEMA_V0,
    admission_tuple_id,
    classify_onboarding_surface,
    demand_shape_ref_for_classify,
)
from shared.demand_shape_ref import demand_shape_ref_from_parts
from shared.sdlc_router import REQUIREMENT_VECTOR_DIMENSIONS

_VECTOR = {dim: 2 for dim in REQUIREMENT_VECTOR_DIMENSIONS}
_CONSTRAINT = {
    "mutation_surface": "source",
    "authority_level": "support_non_authoritative",
    "routing_class": "source_python",
}


def test_admit_supply_only_when_complete_permitted_eligible() -> None:
    result = classify_onboarding_surface(
        surface_id="codex.headless.full",
        modal_class="permitted",
        measurement_sufficiency="complete",
        equal_definition_complete=True,
        demand_eligible_candidate=True,
    )
    assert result["schema"] == SCHEMA_V0
    assert result["disposition"] == "admit_supply"
    assert result["may_fulfill_demand"] is True
    assert result["success"] is True


def test_explore_is_success_not_failure() -> None:
    result = classify_onboarding_surface(
        surface_id="new.surface.x",
        modal_class="permitted",
        measurement_sufficiency="partial",
        equal_definition_complete=True,
        demand_eligible_candidate=True,
    )
    assert result["disposition"] == "EXPLORE"
    assert result["success"] is True
    assert result["may_fulfill_demand"] is False


def test_incomparable_is_explore() -> None:
    result = classify_onboarding_surface(
        measurement_sufficiency="incomparable",
        modal_class="permitted",
    )
    assert result["disposition"] == "EXPLORE"
    assert "measurement_incomparable_explore" in result["reasons"]


def test_hold_on_unevaluable_modal() -> None:
    result = classify_onboarding_surface(
        modal_class="unevaluable",
        measurement_sufficiency="complete",
        equal_definition_complete=True,
        demand_eligible_candidate=True,
    )
    assert result["disposition"] == "HOLD"
    assert result["modal_class"] == "unevaluable"
    assert result["may_fulfill_demand"] is False


def test_refuse_on_forbidden_modal() -> None:
    result = classify_onboarding_surface(
        modal_class="forbidden",
        measurement_sufficiency="complete",
        equal_definition_complete=True,
        demand_eligible_candidate=True,
    )
    assert result["disposition"] == "refuse"
    assert result["success"] is True  # correct refuse is a successful classify


def test_evidence_only_instrument_cannot_admit_supply() -> None:
    result = classify_onboarding_surface(
        surface_id="some.observer",
        instrument_disposition="evidence_only_non_supply",
        modal_class="permitted",
        measurement_sufficiency="complete",
        equal_definition_complete=True,
        demand_eligible_candidate=True,
    )
    assert result["disposition"] == "evidence_only"
    assert result["may_fulfill_demand"] is False


def test_agentic_trust_surface_identity_cannot_admit_supply() -> None:
    result = classify_onboarding_surface(
        surface_id=AGENTIC_TRUST_EVIDENCE_SURFACE_ID,
        modal_class="permitted",
        measurement_sufficiency="complete",
        equal_definition_complete=True,
        demand_eligible_candidate=True,
    )
    assert result["disposition"] == "evidence_only"
    assert result["may_fulfill_demand"] is False


def test_agentic_trust_evidence_ref_cannot_admit_supply() -> None:
    result = classify_onboarding_surface(
        surface_id="looks.like.normal.route",
        evidence_refs=["AgenticTrustEvidenceReceiptV1:abc"],
        modal_class="permitted",
        measurement_sufficiency="complete",
        equal_definition_complete=True,
        demand_eligible_candidate=True,
    )
    assert result["disposition"] == "evidence_only"
    assert result["may_fulfill_demand"] is False


def test_unknown_modal_token_holds_incomplete_technical() -> None:
    result = classify_onboarding_surface(modal_class="maybe-yes")
    assert result["disposition"] == "HOLD"
    assert result["modal_class"] == "incomplete_technical"


def test_admission_tuple_id_stable_and_mutates() -> None:
    base = {
        "schema": ADMISSION_TUPLE_SCHEMA,
        "controller": {"kind": "session_lane", "id": "grok"},
        "instrument": {"instrument_id": "hapax-agentic-trust", "disposition": "evidence_only"},
    }
    a = admission_tuple_id(base)
    b = admission_tuple_id(dict(base))
    assert a == b
    assert a.startswith("sha256:")
    mutated = {**base, "controller": {"kind": "session_lane", "id": "codex"}}
    assert admission_tuple_id(mutated) != a


def test_demand_shape_ref_wrapper_matches_module() -> None:
    assert demand_shape_ref_for_classify(
        requirement_vector=_VECTOR,
        constraint=_CONSTRAINT,
    ) == demand_shape_ref_from_parts(
        requirement_vector=_VECTOR,
        constraint=_CONSTRAINT,
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"measurement_sufficiency": "complete", "equal_definition_complete": False},
        {"measurement_sufficiency": "absent"},
        {},
    ],
)
def test_never_admits_without_full_conditions(kwargs: dict) -> None:
    result = classify_onboarding_surface(modal_class="permitted", **kwargs)
    assert result["disposition"] != "admit_supply"
    assert result["may_fulfill_demand"] is False
