"""Purchased capacity uses real admission, never a simulated subscription wall."""

import json
from decimal import Decimal

import pytest

from tests.scripts.test_hapax_glmcp_reviewer import (
    GLMCP_PAYG_BUDGET_ID,
    _clean_env,
    _live_payg_setup,
    _load_module,
)


def setup_bundle(monkeypatch, tmp_path, model="glm-5.3"):
    m = _load_module()
    _clean_env(monkeypatch)
    path, receipts, _ = _live_payg_setup(m, monkeypatch, tmp_path)
    now = m.datetime.now(m.UTC).replace(microsecond=0)
    data = json.loads(path.read_text())
    budget = next(b for b in data["transition_budgets"] if b["budget_id"] == GLMCP_PAYG_BUDGET_ID)
    budget.update(
        total_cap_usd="10",
        daily_cap_usd="10",
        per_task_cap_usd="10",
        profiles_allowed=["glmcp-bundle-support"],
        task_classes_allowed=["bounded-support"],
        quality_floors_allowed=["deterministic_ok"],
        reason_subscription_path_not_used="operator purchased separate capacity; plan available",
        prepaid_bundle={
            "endpoint": "https://api.z.ai/api/paas/v4",
            "secret_source": "filestore:glmcp/api-key",  # pragma: allowlist secret -- entry name
            "account_binding_ref": "fixture-account-key-binding",
            "balance_evidence_ref": "fixture-provider-bundle-balance",
            "no_cash_fallback_evidence_ref": "fixture-provider-stop-observation",
            "observed_at": now.isoformat(),
            "fresh_until": (now + m.timedelta(minutes=15)).isoformat(),
            "model_token_limits": {"glm-5.3": 1000000, "glm-5.3-flash": 1000000},
            "model_available_tokens": {"glm-5.3": 120000000, "glm-5.3-flash": 100000000},
            "cash_fallback_allowed": False,
        },
    )
    data["transition_budgets"] = [budget] + [
        b for b in data["transition_budgets"] if b["budget_id"] != GLMCP_PAYG_BUDGET_ID
    ]
    data["spend_receipts"] = []
    data["artifact_provenance"] = []
    path.write_text(json.dumps(data))
    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_BILLING_MODE", "prepaid_bundle")
    monkeypatch.setenv("HAPAX_GLMCP_REVIEW_MODEL", model)
    return m, path, receipts


def edit_budget(path, edit):
    data = json.loads(path.read_text())
    edit(data["transition_budgets"][0])
    path.write_text(json.dumps(data))


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
