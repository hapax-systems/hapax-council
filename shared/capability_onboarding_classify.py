"""Capability onboarding classify — pure disposition (Edge A §3 / Edge B+C residual).

Maps a measured surface into one of five dispositions without a parallel FSM:

  admit_supply | evidence_only | EXPLORE | HOLD | refuse

EXPLORE is a successful onboarding output (sufficiency principle / forest finding C).
Does not register routes, activate agentic-trust as supply, or wire SdlcRouter.

Spec: 30-areas/hapax/capability-onboarding-process-edge-a-2026-08-04.md §3.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Final

from shared.agentic_trust_boundary import (
    is_agentic_trust_evidence_surface_identity,
    is_agentic_trust_supply_evidence_reference,
)
from shared.demand_shape_ref import DEFAULT_BASIS, demand_shape_ref_from_parts
from shared.route_metadata_schema import stable_payload_hash

SCHEMA_V0: Final[str] = "hapax.capability_onboarding_classify.v0"
ADMISSION_TUPLE_SCHEMA: Final[str] = "hapax.admission_tuple.v0"


class OnboardingDisposition(StrEnum):
    ADMIT_SUPPLY = "admit_supply"
    EVIDENCE_ONLY = "evidence_only"
    EXPLORE = "EXPLORE"
    HOLD = "HOLD"
    REFUSE = "refuse"


class ModalClass(StrEnum):
    PERMITTED = "permitted"
    FORBIDDEN = "forbidden"
    UNEVALUABLE = "unevaluable"
    INCOMPLETE_TECHNICAL = "incomplete_technical"


class MeasurementSufficiency(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    ABSENT = "absent"
    INCOMPARABLE = "incomparable"


def admission_tuple_id(tuple_fields: Mapping[str, Any]) -> str:
    """Content-address an admission-tuple payload (Edge A §1.3).

    Uses the same stable_payload_hash contract as DemandShapeRef. Does not
    validate the full admission schema — callers own field completeness.
    """
    if not isinstance(tuple_fields, Mapping):
        raise ValueError("tuple_fields must be a mapping")
    payload = {
        "schema": str(tuple_fields.get("schema") or ADMISSION_TUPLE_SCHEMA),
        **{k: v for k, v in tuple_fields.items() if k != "schema" and not str(k).startswith("__")},
    }
    return stable_payload_hash(payload)


def _as_str(value: object | None) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        return None
    text = value.strip()
    return text or None


def _parse_modal(value: object | None) -> ModalClass | None:
    text = _as_str(value)
    if text is None:
        return None
    try:
        return ModalClass(text)
    except ValueError:
        return None


def _parse_sufficiency(value: object | None) -> MeasurementSufficiency | None:
    text = _as_str(value)
    if text is None:
        return None
    try:
        return MeasurementSufficiency(text)
    except ValueError:
        return None


def classify_onboarding_surface(
    *,
    surface_id: str | None = None,
    instrument_disposition: str | None = None,
    instrument_id: str | None = None,
    modal_class: str | None = None,
    measurement_sufficiency: str | None = None,
    equal_definition_complete: bool | None = None,
    demand_eligible_candidate: bool | None = None,
    evidence_refs: list[str] | tuple[str, ...] | None = None,
    notes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify one observed surface into an onboarding disposition.

    Pure and fail-closed on unknown enum tokens (HOLD + incomplete_technical).
    Never returns admit_supply for evidence-only / agentic-trust observation identities.
    """
    reasons: list[str] = []
    modal = _parse_modal(modal_class)
    sufficiency = _parse_sufficiency(measurement_sufficiency)
    refs = tuple(evidence_refs or ())

    # --- hard evidence-only identity law (cannot collapse into supply) ---
    if is_agentic_trust_evidence_surface_identity(surface_id):
        reasons.append("agentic_trust_evidence_surface_identity")
        return _result(
            OnboardingDisposition.EVIDENCE_ONLY,
            ModalClass.PERMITTED if modal is None else modal,
            reasons,
            surface_id=surface_id,
            notes=notes,
        )
    if is_agentic_trust_supply_evidence_reference(surface_id) or any(
        is_agentic_trust_supply_evidence_reference(ref) for ref in refs
    ):
        reasons.append("agentic_trust_supply_evidence_reference_blocked")
        return _result(
            OnboardingDisposition.EVIDENCE_ONLY,
            ModalClass.PERMITTED if modal is None else modal,
            reasons,
            surface_id=surface_id,
            notes=notes,
        )
    inst_disp = (_as_str(instrument_disposition) or "").lower()
    if inst_disp in {"evidence_only", "evidence_only_non_supply"}:
        reasons.append("instrument_disposition_evidence_only")
        return _result(
            OnboardingDisposition.EVIDENCE_ONLY,
            ModalClass.PERMITTED if modal is None else modal,
            reasons,
            surface_id=surface_id,
            notes=notes,
        )
    inst_id = (_as_str(instrument_id) or "").lower()
    if "agentic-trust" in inst_id or "agentic_trust" in inst_id:
        reasons.append("instrument_id_agentic_trust")
        return _result(
            OnboardingDisposition.EVIDENCE_ONLY,
            ModalClass.PERMITTED if modal is None else modal,
            reasons,
            surface_id=surface_id,
            notes=notes,
        )

    # --- modal G ---
    if modal_class is not None and modal is None:
        reasons.append("modal_class_unknown_token")
        return _result(
            OnboardingDisposition.HOLD,
            ModalClass.INCOMPLETE_TECHNICAL,
            reasons,
            surface_id=surface_id,
            notes=notes,
        )
    if modal is ModalClass.FORBIDDEN:
        reasons.append("modal_forbidden")
        return _result(
            OnboardingDisposition.REFUSE,
            modal,
            reasons,
            surface_id=surface_id,
            notes=notes,
        )
    if modal in {ModalClass.UNEVALUABLE, ModalClass.INCOMPLETE_TECHNICAL}:
        reasons.append(f"modal_{modal.value}")
        return _result(
            OnboardingDisposition.HOLD,
            modal,
            reasons,
            surface_id=surface_id,
            notes=notes,
        )

    # --- measurement / sufficiency ---
    if measurement_sufficiency is not None and sufficiency is None:
        reasons.append("measurement_sufficiency_unknown_token")
        return _result(
            OnboardingDisposition.HOLD,
            ModalClass.INCOMPLETE_TECHNICAL,
            reasons,
            surface_id=surface_id,
            notes=notes,
        )
    if sufficiency is MeasurementSufficiency.ABSENT or sufficiency is None:
        reasons.append("measurement_absent_or_unspecified")
        return _result(
            OnboardingDisposition.HOLD,
            modal or ModalClass.UNEVALUABLE,
            reasons,
            surface_id=surface_id,
            notes=notes,
        )
    if sufficiency is MeasurementSufficiency.INCOMPARABLE:
        reasons.append("measurement_incomparable_explore")
        return _result(
            OnboardingDisposition.EXPLORE,
            modal or ModalClass.PERMITTED,
            reasons,
            surface_id=surface_id,
            notes=notes,
        )
    if sufficiency is MeasurementSufficiency.PARTIAL:
        reasons.append("measurement_partial_explore")
        return _result(
            OnboardingDisposition.EXPLORE,
            modal or ModalClass.PERMITTED,
            reasons,
            surface_id=surface_id,
            notes=notes,
        )

    # sufficiency COMPLETE from here
    if equal_definition_complete is False:
        reasons.append("equal_definition_incomplete")
        return _result(
            OnboardingDisposition.HOLD,
            modal or ModalClass.PERMITTED,
            reasons,
            surface_id=surface_id,
            notes=notes,
        )
    if equal_definition_complete is None:
        reasons.append("equal_definition_unspecified_explore")
        return _result(
            OnboardingDisposition.EXPLORE,
            modal or ModalClass.PERMITTED,
            reasons,
            surface_id=surface_id,
            notes=notes,
        )

    if demand_eligible_candidate is False:
        # measured + equal-definition but not demand-eligible → EXPLORE frontier
        reasons.append("not_demand_eligible_candidate")
        return _result(
            OnboardingDisposition.EXPLORE,
            modal or ModalClass.PERMITTED,
            reasons,
            surface_id=surface_id,
            notes=notes,
        )
    if demand_eligible_candidate is None:
        reasons.append("demand_eligible_unspecified_explore")
        return _result(
            OnboardingDisposition.EXPLORE,
            modal or ModalClass.PERMITTED,
            reasons,
            surface_id=surface_id,
            notes=notes,
        )

    if modal is not None and modal is not ModalClass.PERMITTED:
        reasons.append("admit_requires_permitted_modal")
        return _result(
            OnboardingDisposition.HOLD,
            modal,
            reasons,
            surface_id=surface_id,
            notes=notes,
        )

    reasons.append("admit_supply_complete")
    return _result(
        OnboardingDisposition.ADMIT_SUPPLY,
        modal or ModalClass.PERMITTED,
        reasons,
        surface_id=surface_id,
        notes=notes,
    )


def _result(
    disposition: OnboardingDisposition,
    modal: ModalClass,
    reasons: list[str],
    *,
    surface_id: str | None,
    notes: Mapping[str, Any] | None,
) -> dict[str, Any]:
    # Defense in depth: never emit admit_supply with a non-permitted modal.
    if disposition is OnboardingDisposition.ADMIT_SUPPLY and modal is not ModalClass.PERMITTED:
        disposition = OnboardingDisposition.HOLD
        reasons = [*reasons, "admit_collapsed_to_hold_non_permitted_modal"]
    out: dict[str, Any] = {
        "schema": SCHEMA_V0,
        "disposition": disposition.value,
        "modal_class": modal.value,
        "reasons": list(reasons),
        "surface_id": surface_id,
        "success": True,  # all five dispositions are successful classify outcomes
        "may_fulfill_demand": disposition is OnboardingDisposition.ADMIT_SUPPLY,
    }
    if notes:
        out["notes"] = dict(notes)
    return out


def demand_shape_ref_for_classify(
    *,
    requirement_vector: Mapping[str, object],
    constraint: Mapping[str, object],
    basis: str = DEFAULT_BASIS,
) -> str:
    """Build DemandShapeRef for an onboarding classify record (thin wrapper)."""
    return demand_shape_ref_from_parts(
        requirement_vector=requirement_vector,
        constraint=constraint,
        basis=basis,
    )
