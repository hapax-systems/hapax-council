"""N3 discover: delta → classify/ledger without supply admit."""

from __future__ import annotations

from pathlib import Path

from shared.capability_onboarding_classify import OnboardingDisposition
from shared.capability_onboarding_discover import (
    delta_to_classify_kwargs,
    discover_from_deltas,
)
from shared.capability_surface_delta import CapabilitySurfaceDelta


def _new_capability_delta(**overrides: object) -> CapabilitySurfaceDelta:
    payload: dict[str, object] = {
        "delta_schema": 1,
        "delta_id": "test:new-slice",
        "source": "test",
        "observed_at": "2026-08-06T00:00:00Z",
        "detected_by": "unit-test",
        "surface_id": "route.openrouter.test-model.high",
        "delta_kind": "new_capability",
        "prior_descriptor_ref": None,
        "observed_descriptor_ref": "provider-catalog:test:model",
        "evidence_refs": ["provider-catalog:test:fixture"],
        "authority_ceiling": "frontier_review_required",
        "affected_resource_pools": ["api_paid_spend"],
        "privacy_sensitive": False,
        "public_egress": False,
        "money_rail": False,
        "freshness_state": "delta_pending",
        "required_intake_action": "mint_intake_item",
        "remediation_ref": "cc-task-test-remediation",
        "summary": "new test capability for discover path",
    }
    payload.update(overrides)
    return CapabilitySurfaceDelta.model_validate(payload)


def test_delta_kwargs_force_non_supply_floors() -> None:
    kwargs = delta_to_classify_kwargs(_new_capability_delta())
    assert kwargs["demand_eligible_candidate"] is False
    assert kwargs["equal_definition_complete"] is False
    assert kwargs["measurement_sufficiency"] == "partial"
    assert "surface_delta:test:new-slice" in kwargs["evidence_refs"]


def test_new_capability_explores_on_dry_run() -> None:
    results = discover_from_deltas([_new_capability_delta()], dry_run=True)
    assert len(results) == 1
    assert results[0]["dry_run"] is True
    assert results[0]["ledger_path"] is None
    assert results[0]["classify"]["disposition"] == OnboardingDisposition.EXPLORE.value
    assert results[0]["classify"]["may_fulfill_demand"] is False


def test_agentic_trust_surface_evidence_only() -> None:
    delta = _new_capability_delta(
        delta_id="test:at",
        surface_id="local_compute.agentic_trust_evaluator_surface",
        observed_descriptor_ref="fixture:agentic-trust-descriptor",
        money_rail=False,
        affected_resource_pools=["local_cpu"],
    )
    results = discover_from_deltas([delta], dry_run=True)
    assert results[0]["classify"]["disposition"] == OnboardingDisposition.EVIDENCE_ONLY.value


def test_apply_writes_ledger(tmp_path: Path) -> None:
    results = discover_from_deltas(
        [_new_capability_delta()],
        dry_run=False,
        ledger_root=tmp_path,
    )
    assert results[0]["dry_run"] is False
    path = Path(results[0]["ledger_path"])
    assert path.exists()
    assert path.name == "explore.jsonl"
    assert "EXPLORE" in path.read_text(encoding="utf-8") or "explore" in path.name
