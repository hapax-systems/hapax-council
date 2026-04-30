"""Tests for control-surface route health WCS projection."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from shared.capability_classification_inventory import load_capability_classification_inventory
from shared.world_surface_health import (
    FallbackMode,
    HealthDimensionId,
    HealthDimensionState,
    HealthStatus,
    PublicPrivatePosture,
    SurfaceFamily,
)
from shared.world_surface_health_control_adapter import (
    CONTROL_HEALTH_FIXTURES,
    REQUIRED_CONTROL_ROUTE_FAMILIES,
    CommandApplicationState,
    ControlRouteHealthFixtureSet,
    ControlTargetState,
    ReadbackPolicy,
    load_control_health_fixtures,
    project_control_health_records,
)


def _json(path: Path = CONTROL_HEALTH_FIXTURES) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _dimension_state(record, dimension_id: HealthDimensionId) -> HealthDimensionState:
    dimensions = {dimension.dimension: dimension for dimension in record.health_dimensions}
    return dimensions[dimension_id].state


def test_fixture_rows_are_seeded_from_capability_classification_inventory() -> None:
    fixture_set = load_control_health_fixtures()
    inventory = load_capability_classification_inventory()

    assert {
        route.route_family.value for route in fixture_set.routes
    } >= REQUIRED_CONTROL_ROUTE_FAMILIES
    for route in fixture_set.routes:
        row = inventory.require_row(route.classification_row_id)

        assert route.target_ref == row.concrete_interface
        assert route.expected_route_ref == f"route:{row.concrete_interface}"
        assert route.authority_ceiling.value == row.claim_authority_ceiling.value
        assert row.evidence_ref in route.evidence_envelope_refs


def test_projected_rows_are_bounded_control_wcs_records() -> None:
    records = project_control_health_records()

    assert records
    for record in records:
        assert record.surface_family is SurfaceFamily.CONTROL
        assert record.public_claim_allowed is False
        assert record.monetization_allowed is False
        assert record.claimable_health is False
        assert record.claimability.public_live is False
        assert record.claimability.grounded is False
        assert record.satisfies_claimable_health() is False
        assert "control_route_health_does_not_grant_public_or_success_authority" in record.warnings


def test_mounted_control_requires_route_target_readback_and_witness() -> None:
    fixture_set = load_control_health_fixtures()
    mounted = fixture_set.routes_by_id()["control.midi.s4_clock_transport.mounted"]
    records = {
        record.surface_id.removesuffix(".health"): record
        for record in project_control_health_records()
    }
    record = records[mounted.route_id]

    assert mounted.satisfies_control_action_witness() is True
    assert mounted.command_state is CommandApplicationState.ACCEPTED
    assert mounted.target_state is ControlTargetState.PRESENT
    assert mounted.readback_policy is ReadbackPolicy.REQUIRED
    assert _dimension_state(record, HealthDimensionId.ROUTE_BINDING) is (HealthDimensionState.PASS)
    assert _dimension_state(record, HealthDimensionId.EXECUTION_WITNESS) is (
        HealthDimensionState.PASS
    )
    assert _dimension_state(record, HealthDimensionId.WORLD_WITNESS) is (HealthDimensionState.PASS)


@pytest.mark.parametrize(
    ("route_id", "dimension_id", "expected_state"),
    [
        (
            "control.midi.s4_clock_transport.absent",
            HealthDimensionId.PRODUCER_EXISTS,
            HealthDimensionState.MISSING,
        ),
        (
            "control.desktop.hyprland_focus.wrong_route",
            HealthDimensionId.ROUTE_BINDING,
            HealthDimensionState.FAIL,
        ),
        (
            "control.companion.phone_awareness.stale",
            HealthDimensionId.SOURCE_FRESHNESS,
            HealthDimensionState.STALE,
        ),
        (
            "control.hardware.s4_firmware.noop",
            HealthDimensionId.WORLD_WITNESS,
            HealthDimensionState.BLOCKED,
        ),
    ],
)
def test_absent_stale_wrong_route_and_noop_do_not_satisfy_action_success(
    route_id: str,
    dimension_id: HealthDimensionId,
    expected_state: HealthDimensionState,
) -> None:
    fixture_set = load_control_health_fixtures()
    routes = fixture_set.routes_by_id()
    records = {
        record.surface_id.removesuffix(".health"): record
        for record in project_control_health_records()
    }

    assert routes[route_id].satisfies_control_action_witness() is False
    assert _dimension_state(records[route_id], dimension_id) is expected_state


def test_private_device_binding_is_visible_but_never_public_claimable() -> None:
    fixture_set = load_control_health_fixtures()
    private_route = fixture_set.routes_by_id()["control.device.camera_overhead.private_binding"]
    records = {
        record.surface_id.removesuffix(".health"): record
        for record in project_control_health_records()
    }
    record = records[private_route.route_id]

    assert record.status is HealthStatus.PRIVATE_ONLY
    assert record.private_only is True
    assert record.public_private_posture is PublicPrivatePosture.PRIVATE_ONLY
    assert record.public_claim_allowed is False
    assert record.claimability.public_live is False
    assert _dimension_state(record, HealthDimensionId.PRIVACY_CONSENT) is (
        HealthDimensionState.PASS
    )


def test_blocked_hardware_remains_visible_as_operator_reason_noop() -> None:
    fixture_set = load_control_health_fixtures()
    blocked = fixture_set.routes_by_id()["control.hardware.s4_firmware.noop"]
    records = {
        record.surface_id.removesuffix(".health"): record
        for record in project_control_health_records()
    }
    record = records[blocked.route_id]

    assert record.status is HealthStatus.BLOCKED
    assert blocked.command_state is CommandApplicationState.NO_OP
    assert record.fallback.mode is FallbackMode.NO_OP_EXPLAIN
    assert record.fallback.reason_code == "firmware_witness_missing"
    assert "firmware_witness_missing" in record.blocking_reasons


def test_accepted_command_for_absent_target_is_rejected() -> None:
    payload = _json()
    bad = deepcopy(payload)
    route = next(
        item
        for item in bad["routes"]
        if item["route_id"] == "control.midi.s4_clock_transport.absent"
    )
    route["command_state"] = "accepted"
    route["command_refs"] = ["command:forged"]

    with pytest.raises(ValidationError):
        ControlRouteHealthFixtureSet.model_validate(bad)


def test_wrong_route_must_name_a_mismatched_observed_route() -> None:
    payload = _json()
    bad = deepcopy(payload)
    route = next(
        item
        for item in bad["routes"]
        if item["route_id"] == "control.desktop.hyprland_focus.wrong_route"
    )
    route["observed_route_ref"] = route["expected_route_ref"]

    with pytest.raises(ValidationError):
        ControlRouteHealthFixtureSet.model_validate(bad)
