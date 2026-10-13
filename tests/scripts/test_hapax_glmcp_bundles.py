"""Purchased capacity uses real admission, never a simulated subscription wall."""

from decimal import Decimal

import pytest


def test_flash_has_own_list_price_and_no_subscription_promotion():
    from shared.quota_spend_ledger import GLMCP_ADMISSION_MODELS, glmcp_payg_usage_cost_usd

    assert "glm-5.3-flash" not in GLMCP_ADMISSION_MODELS
    assert glmcp_payg_usage_cost_usd(
        model="glm-5.3-flash", prompt_tokens=1000000, cached_tokens=0, completion_tokens=1000000
    ) == Decimal("0.65")


@pytest.mark.parametrize("model,profile", [("glm-5.3", "api_frontier"), ("glm-5.3-flash", "flash")])
def test_bundle_declarations_remain_unqualified_support(model, profile):
    from shared.platform_capability_registry import load_platform_capability_registry

    registry = load_platform_capability_registry()
    route = registry.require("glmcp.receipt_only." + profile)
    assert "requires accepted stages 2/3" in route.launcher
    assert route.sanctioned_wrapper == "scripts/hapax-glmcp-reviewer"
    assert route.execution_descriptor.model_id.value == "z_ai-" + model
    assert route.execution_descriptor.effort.value == "max"
    assert route.route_state.value == "blocked"
    assert route.worker_tier.value == "read_only_sidecar"
    assert route.auth_surface.value == "api_key"
    assert [floor.value for floor in route.quality_envelope.eligible_quality_floors] == [
        "deterministic_ok"
    ]
    assert all(
        score.score == 0 and score.confidence == 0
        for score in route.capability_scores.__dict__.values()
    )
    assert registry.require("glmcp.review.direct").model_or_engine == "z_ai-glm-coding-plan:glm-5.2"


@pytest.mark.parametrize("model", ["glm-5.3", "glm-5.3-flash"])
def test_paid_route_model_identity_survives_descriptor_materialization(model):
    from types import SimpleNamespace

    from shared.platform_capability_registry import derive_execution_descriptor

    route = SimpleNamespace(model_or_engine="z_ai:" + model)
    assert derive_execution_descriptor(route).model_id.value == "z_ai-" + model
