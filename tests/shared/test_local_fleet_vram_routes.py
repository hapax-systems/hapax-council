"""The 2026-09-27 local shapes are declared and stay blocked.

A local_inference_entitlement receipt clears only its removable set. The demand-map
floor reason is not in that set, so minting the receipt cannot admit these routes.
"""

from __future__ import annotations

import json

from shared.dispatcher_policy import (
    apply_route_authority_receipts,
    build_route_authority_receipt,
    write_route_authority_receipt,
)
from shared.platform_capability_registry import (
    PLATFORM_CAPABILITY_REGISTRY,
    PlatformCapabilityRegistry,
)

FIT = "measured_demand_fit_below_floor_20260927"
DECLARED = (
    "local_tool.headless.worker",
    "local_tool.local.lite",
    "local_tool.review.direct",
    "local_tool.local.full",
    "local_tool.headless.flash",
    "local_tool.headless.lane",
)


def _registry() -> PlatformCapabilityRegistry:
    return PlatformCapabilityRegistry.model_validate(
        json.loads(PLATFORM_CAPABILITY_REGISTRY.read_text(encoding="utf-8"))
    )


def test_measured_local_shapes_are_declared_and_blocked() -> None:
    registry = _registry()
    for route_id in DECLARED:
        route = registry.route_map()[route_id]
        assert route.route_state.value == "blocked"
        assert FIT in route.blocked_reasons
        assert route.execution_descriptor.quantization.value == "not_applicable"


def test_entitlement_receipt_does_not_clear_the_demand_floor(tmp_path) -> None:
    registry = _registry()
    route_id = "local_tool.headless.worker"
    receipt = build_route_authority_receipt(
        receipt_type="local_inference_entitlement",
        route_id=route_id,
        evidence_refs=["measurement:local-fleet-vram-demand-map-20260927"],
        signed_by="grok-fleet",
    )
    write_route_authority_receipt(receipt, receipt_dir=tmp_path)

    applied = apply_route_authority_receipts(registry, receipt_dir=tmp_path)
    after = applied.route_map()[route_id]

    assert FIT in after.blocked_reasons
    assert after.route_state.value == "blocked"
    assert "local_inference_worker_receipt_admission_required" not in after.blocked_reasons
