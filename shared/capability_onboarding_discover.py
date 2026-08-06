"""N3: surface_delta → onboarding classify/ledger discover bridge.

Turns capability-surface delta rows into disposition ledger writes
(EXPLORE | HOLD | evidence_only | refuse) without admitting supply.

**Hard law:** discovery never sets ``demand_eligible_candidate=True`` and never
sets ``equal_definition_complete=True``. Classify cannot return admit_supply
from this path under those constraints (and agentic-trust identities stay
evidence_only via existing classify law).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from shared.capability_onboarding_classify import (
    MeasurementSufficiency,
    OnboardingDisposition,
    classify_onboarding_surface,
)
from shared.capability_onboarding_ledger import append_classify_result
from shared.capability_surface_delta import (
    AuthorityCeiling,
    CapabilitySurfaceDelta,
    DeltaKind,
    FreshnessState,
    RequiredIntakeAction,
)


def delta_to_classify_kwargs(delta: CapabilitySurfaceDelta | Mapping[str, Any]) -> dict[str, Any]:
    """Map one surface delta into ``classify_onboarding_surface`` kwargs.

    Fail-closed toward under-measurement (EXPLORE/HOLD), never toward supply.
    """
    if isinstance(delta, CapabilitySurfaceDelta):
        d = delta
    else:
        d = CapabilitySurfaceDelta.model_validate(delta)

    evidence_refs = list(d.evidence_refs)
    evidence_refs.append(f"surface_delta:{d.delta_id}")
    if d.observed_descriptor_ref:
        evidence_refs.append(d.observed_descriptor_ref)
    if d.prior_descriptor_ref:
        evidence_refs.append(d.prior_descriptor_ref)

    measurement = _measurement_from_freshness(d.freshness_state, d.delta_kind)
    instrument_disposition = _instrument_disposition(d.authority_ceiling)
    modal = _modal_hint(d)

    return {
        "surface_id": d.surface_id,
        "instrument_disposition": instrument_disposition,
        "instrument_id": d.detected_by,
        "modal_class": modal,
        "measurement_sufficiency": measurement,
        # Discovery path hard floors — never complete definition / demand-eligible.
        "equal_definition_complete": False,
        "demand_eligible_candidate": False,
        "evidence_refs": evidence_refs,
        "notes": {
            "delta_id": d.delta_id,
            "delta_kind": d.delta_kind.value,
            "freshness_state": d.freshness_state.value,
            "required_intake_action": d.required_intake_action.value,
            "authority_ceiling": d.authority_ceiling.value,
            "privacy_sensitive": d.privacy_sensitive,
            "public_egress": d.public_egress,
            "money_rail": d.money_rail,
            "summary": d.summary,
            "source": d.source,
            "discover_path": "surface_delta_v1",
        },
    }


def _measurement_from_freshness(freshness: FreshnessState, kind: DeltaKind) -> str:
    if kind is DeltaKind.ABSENT_DETERMINATION or freshness is FreshnessState.ABSENT:
        return MeasurementSufficiency.ABSENT.value
    if kind is DeltaKind.STALE_DETERMINATION or freshness is FreshnessState.STALE:
        return MeasurementSufficiency.PARTIAL.value
    if freshness in {FreshnessState.DARK, FreshnessState.HELD, FreshnessState.UNKNOWN}:
        return MeasurementSufficiency.INCOMPARABLE.value
    # delta_pending / aging / fresh still under-measured for onboarding admit
    return MeasurementSufficiency.PARTIAL.value


def _instrument_disposition(ceiling: AuthorityCeiling) -> str | None:
    if ceiling in {AuthorityCeiling.SUPPORT_ONLY, AuthorityCeiling.READ_ONLY}:
        return "evidence_only"
    return None


def _modal_hint(delta: CapabilitySurfaceDelta) -> str | None:
    # Money/public high-risk deltas stay technically incomplete until dedicated admission.
    if delta.money_rail and delta.required_intake_action is RequiredIntakeAction.MINT_INTAKE_ITEM:
        return None  # classify uses partial measurement → EXPLORE
    if delta.delta_kind is DeltaKind.ABSENT_DETERMINATION:
        return None
    return None


def discover_from_deltas(
    deltas: Sequence[CapabilitySurfaceDelta | Mapping[str, Any]] | Iterable[Any],
    *,
    dry_run: bool = False,
    ledger_root: str | None = None,
    source_ref: str | None = None,
) -> list[dict[str, Any]]:
    """Classify each delta; optionally append to disposition ledgers.

    Returns list of {classify, ledger_path?, row?, dry_run, source_ref}.
    Never admits supply.
    """
    results: list[dict[str, Any]] = []
    for raw in deltas:
        kwargs = delta_to_classify_kwargs(raw)
        # Double-lock: never allow demand-eligible from this path
        kwargs["demand_eligible_candidate"] = False
        kwargs["equal_definition_complete"] = False
        src = source_ref or (
            f"surface_delta:{(raw.delta_id if isinstance(raw, CapabilitySurfaceDelta) else raw.get('delta_id'))}"
        )
        # Classify first; refuse admit_supply before any durable write.
        classify = classify_onboarding_surface(**kwargs)
        if classify.get("disposition") == OnboardingDisposition.ADMIT_SUPPLY.value:
            raise RuntimeError(
                "discover path produced admit_supply; next action: inspect "
                "delta_to_classify_kwargs floors (must keep demand_eligible=false)"
            )
        if dry_run:
            results.append(
                {
                    "classify": classify,
                    "dry_run": True,
                    "source_ref": src,
                    "ledger_path": None,
                    "row": None,
                }
            )
            continue
        path, row = append_classify_result(
            classify,
            root=ledger_root,
            source_ref=src,
            demand_shape_ref=None,
            admission_tuple_id=None,
        )
        results.append(
            {
                "classify": classify,
                "ledger_path": str(path),
                "row": row,
                "dry_run": False,
                "source_ref": src,
            }
        )
    return results
