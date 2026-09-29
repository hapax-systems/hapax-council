"""Inventory disposition keeps an omitted evidence surface out of admitted supply."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared.capability_inventory_contract import InventoryDisposition
from shared.entitlement_census import (
    CensusConfig,
    CensusConfigError,
    EntitlementState,
    HostHoldings,
    load_inventory_dispositions,
    run_census,
    validate_registry_inventory_join,
)


def test_tagged_baseline_is_validated_and_registry_ids_must_be_present(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    payload = {
        "schema_version": 2,
        "count": 1,
        "records": {
            "sample.route": {
                "inventory_disposition": "admitted_supply",
                "fingerprint": "a" * 64,
            }
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    dispositions = load_inventory_dispositions(path)
    assert dispositions["sample.route"] is InventoryDisposition.ADMITTED_SUPPLY
    with pytest.raises(CensusConfigError, match="absent from capability inventory baseline"):
        validate_registry_inventory_join(
            {"routes": [{"route_id": "different.route"}]}, dispositions
        )
    payload["count"] = 2
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CensusConfigError, match="invalid"):
        load_inventory_dispositions(path)


def test_evidence_only_shape_is_visible_but_does_not_satisfy_supply() -> None:
    now = datetime(2026, 9, 28, tzinfo=UTC)
    shape_id = "model_provider.sample_surface"
    config = CensusConfig.model_validate(
        {
            "schema": "hapax.entitlement_census.v1",
            "hosts": [{"host_id": "appendix", "transport": "local"}],
            "entitlements": [
                {
                    "entitlement_id": "sample",
                    "provider": "sample",
                    "kind": "cognition",
                    "cost_class": "subscription",
                    "credential_names": ["sample-key"],
                    "registry_shape_ids": [shape_id],
                }
            ],
        }
    )
    run = run_census(
        config,
        now=now,
        holdings=[
            HostHoldings(
                host_id="appendix",
                reachable=True,
                observed_at=now,
                filestore_names=("sample-key",),
            )
        ],
        registry={
            "omitted_capability_shapes": [{"shape_id": shape_id, "shape_class": "model_provider"}]
        },
        inventory_dispositions={shape_id: InventoryDisposition.EVIDENCE_ONLY_NON_SUPPLY},
        ledger=None,
        prior_view=None,
        resolve_secret=lambda _: None,
        http_get=lambda *_: (_ for _ in ()).throw(AssertionError("unexpected network")),
        read_home_file=lambda _: None,
    )
    row = run.rows[0]
    assert row.state is EntitlementState.HELD
    assert row.declared_shapes == (shape_id,)
    assert row.recruitment_stage == "usable-undeclared"
    assert any("evidence-only" in reason for reason in row.reasons)
    assert [(d.surface_id, d.delta_kind.value) for d in run.deltas] == [
        ("entitlement.sample", "new_capability")
    ]
