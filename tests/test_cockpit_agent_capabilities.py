from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from agents._agent_registry import get_registry
from shared import cockpit_agent_capabilities as cockpit_caps
from shared.cockpit_agent_capabilities import (
    COCKPIT_PLATFORM_CAPABILITY_REGISTRY_ENV,
    COCKPIT_QUOTA_SPEND_LEDGER_ENV,
    CockpitSupplyLeaf,
    admit_cockpit_agent_invocation,
    cockpit_capability_for,
    cockpit_capability_for_invocation,
)
from shared.platform_capability_receipts import PLATFORM_CAPABILITY_RECEIPT_DIR_ENV

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = REPO_ROOT / "config" / "platform-capability-registry.json"
LEDGER = REPO_ROOT / "config" / "quota-spend-ledger-fixtures.json"
NOW = datetime(2026, 6, 1, 0, 10, tzinfo=UTC)
NOW_ISO = "2026-06-01T00:00:00Z"


def _mark_route_fresh(route: dict[str, object]) -> None:
    route["route_state"] = "active"
    route["blocked_reasons"] = []
    freshness = route["freshness"]
    assert isinstance(freshness, dict)
    evidence = freshness["evidence"]
    assert isinstance(evidence, dict)
    for surface in ("capability", "quota", "resource", "provider_docs"):
        freshness[f"{surface}_checked_at"] = NOW_ISO
        freshness[f"{surface}_stale_after"] = "24h"
        surface_evidence = evidence[surface]
        assert isinstance(surface_evidence, dict)
        surface_evidence["blocked_reasons"] = []
        surface_evidence["evidence_refs"] = [f"test:{route['route_id']}:{surface}"]
    scores = route["capability_scores"]
    assert isinstance(scores, dict)
    for score in scores.values():
        assert isinstance(score, dict)
        score["observed_at"] = NOW_ISO
    for tool in route.get("tool_state", []):
        assert isinstance(tool, dict)
        tool["observed_at"] = NOW_ISO
        tool["stale_after"] = "24h"


def _write_fresh_registry(
    tmp_path: Path,
    *,
    route_ids: tuple[str, ...] = ("api.headless.provider_gateway",),
) -> Path:
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for route_id in route_ids:
        route = next(route for route in payload["routes"] if route["route_id"] == route_id)
        _mark_route_fresh(route)
        telemetry = route.get("telemetry")
        if route_id == "local_tool.local.worker" and isinstance(telemetry, dict):
            telemetry["quota_source"] = "manual"
    target = tmp_path / "platform-capability-registry.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def _write_fresh_ledger(tmp_path: Path) -> Path:
    payload = json.loads(LEDGER.read_text(encoding="utf-8"))
    payload["ledger_id"] = "quota-spend-ledger-cockpit-test"
    payload["captured_at"] = NOW_ISO
    payload["paid_api_budget_freshness_ttl_s"] = 86400
    for budget in payload["transition_budgets"]:
        if budget["budget_id"] == "tb-20260510-anthropic-api-steady-state":
            budget["expires_at"] = "2026-07-10T00:00:00Z"
            budget["providers_allowed"] = ["anthropic", "google", "perplexity"]
            budget["profiles_allowed"] = ["frontier-fast"]
            budget["task_classes_allowed"] = ["agent-dispatch"]
            budget["quality_floors_allowed"] = ["frontier_required"]
    target = tmp_path / "quota-spend-ledger.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def _write_exhausted_ledger(tmp_path: Path) -> Path:
    path = _write_fresh_ledger(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    for budget in payload["transition_budgets"]:
        if budget["budget_id"] == "tb-20260510-anthropic-api-steady-state":
            budget["total_cap_usd"] = "0.001"
            budget["daily_cap_usd"] = "0.001"
            budget["per_task_cap_usd"] = "0.001"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_local_resource_ledger(
    tmp_path: Path,
    *,
    include_snapshot: bool = True,
    snapshot_fresh_until: str | None = None,
    local_resource_state: str = "green",
) -> Path:
    path = _write_fresh_ledger(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["local_resource_state"] = local_resource_state
    snapshots = []
    for snapshot in payload["quota_snapshots"]:
        if snapshot["capacity_pool"] != "local_compute":
            snapshots.append(snapshot)
            continue
        if include_snapshot:
            if snapshot_fresh_until is not None:
                snapshot["fresh_until"] = snapshot_fresh_until
            snapshots.append(snapshot)
    payload["quota_snapshots"] = snapshots
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_cockpit_inventory_covers_all_manifest_cli_agents() -> None:
    for manifest in get_registry().cli_agents():
        capability = cockpit_capability_for(manifest.id, manifest_model=manifest.model)

        assert capability.agent_id == manifest.id
        assert capability.classifications
        if manifest.model is not None:
            assert capability.supply_leaves, manifest.id
            assert capability.receipt_classes
            for leaf in capability.supply_leaves:
                assert leaf.platform_route_id
                assert leaf.route_id
                assert leaf.provider
                assert leaf.resource_pools
                assert leaf.quota_source
                assert leaf.cost_source


def test_unknown_llm_manifest_fails_closed_instead_of_synthesizing_leaf() -> None:
    with pytest.raises(KeyError, match="untracked cockpit agent capability"):
        cockpit_capability_for("new-llm-agent", manifest_model="fast")


def test_flag_overlay_projection_exposes_supply_leaf_details() -> None:
    from logos.data.agents import _capability_info

    info = _capability_info(cockpit_capability_for("activity-analyzer"))

    assert "--synthesize" in info.llm_flag_overlays
    leaves = info.llm_flag_overlay_leaves["--synthesize"]
    assert leaves[0].capability_id == "cockpit.agent.activity_analyzer.fast_synthesis"
    assert leaves[0].platform_route_id == "api.headless.provider_gateway"
    assert leaves[0].resource_pools == ["api_paid_spend"]


def test_model_alias_leaf_routes_match_agents_config() -> None:
    from agents._config import MODELS

    aliases = {"fast", "balanced"}
    for capability in (
        cockpit_capability_for(manifest.id, manifest_model=manifest.model)
        for manifest in get_registry().cli_agents()
    ):
        for leaf in capability.supply_leaves:
            if leaf.model_alias in aliases:
                assert leaf.model_route == MODELS[leaf.model_alias]


def test_deterministic_default_path_keeps_evidence_waiver() -> None:
    admission = admit_cockpit_agent_invocation("activity-analyzer", flags=())

    assert admission.admitted is True
    assert admission.requires_admission is False
    assert admission.receipts == ()
    assert admission.evidence_only_waiver is not None


def test_runtime_mutation_flag_refuses_evidence_waiver() -> None:
    admission = admit_cockpit_agent_invocation("health-monitor", flags=("--fix",))

    assert admission.admitted is False
    assert admission.requires_admission is True
    assert admission.receipts == ()
    assert "non_read_only_invocation_requires_route_receipt" in admission.reason_codes
    assert "runtime_mutation_flag:--fix" in admission.reason_codes


def test_runtime_public_surface_without_supply_leaves_fails_closed() -> None:
    admission = admit_cockpit_agent_invocation("studio-compositor", flags=())

    assert admission.admitted is False
    assert admission.requires_admission is True
    assert admission.receipts == ()
    assert "non_read_only_invocation_requires_route_receipt" in admission.reason_codes
    assert "runtime_mutation_surface_requires_route_receipt" in admission.reason_codes
    assert "public_egress_surface_requires_route_receipt" in admission.reason_codes


def test_optional_llm_flag_requires_admission_and_fails_without_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(COCKPIT_QUOTA_SPEND_LEDGER_ENV, str(tmp_path / "missing-ledger.json"))

    admission = admit_cockpit_agent_invocation(
        "activity-analyzer",
        flags=("--synthesize",),
        now=NOW,
    )

    assert admission.requires_admission is True
    assert admission.admitted is False
    assert "quota_spend_ledger_unavailable:QuotaSpendLedgerError" in admission.reason_codes


def test_paid_llm_command_admits_with_fresh_gateway_and_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(COCKPIT_QUOTA_SPEND_LEDGER_ENV, str(_write_fresh_ledger(tmp_path)))
    monkeypatch.setenv(
        COCKPIT_PLATFORM_CAPABILITY_REGISTRY_ENV, str(_write_fresh_registry(tmp_path))
    )
    monkeypatch.setenv(PLATFORM_CAPABILITY_RECEIPT_DIR_ENV, "none")

    admission = admit_cockpit_agent_invocation(
        "briefing",
        manifest_model="fast",
        flags=(),
        now=NOW,
    )

    assert admission.admitted is True
    assert admission.requires_admission is True
    refs = {ref for receipt in admission.receipts for ref in receipt.receipt_refs}
    assert "tb-20260510-anthropic-api-steady-state" in refs
    assert "platform-capability-registry:api.headless.provider_gateway" in refs


def test_local_compute_leaf_admits_with_fresh_local_resource(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(COCKPIT_QUOTA_SPEND_LEDGER_ENV, str(_write_fresh_ledger(tmp_path)))
    monkeypatch.setenv(
        COCKPIT_PLATFORM_CAPABILITY_REGISTRY_ENV,
        str(_write_fresh_registry(tmp_path, route_ids=("local_tool.local.worker",))),
    )
    monkeypatch.setenv(PLATFORM_CAPABILITY_RECEIPT_DIR_ENV, "none")

    admission = admit_cockpit_agent_invocation(
        "code-review",
        manifest_model="balanced",
        flags=("--model=local-fast",),
        now=NOW,
    )

    assert admission.admitted is True
    assert admission.requires_admission is True
    assert admission.receipts[0].capacity_pool == "local_compute"
    assert "local_resource_green" in admission.receipts[0].reason_codes


@pytest.mark.parametrize(
    ("ledger_kwargs", "expected_reason"),
    [
        ({"include_snapshot": False}, "local_resource_snapshot_missing"),
        (
            {"snapshot_fresh_until": "2026-05-31T00:00:00Z"},
            "local_resource_snapshot_not_fresh",
        ),
        ({"local_resource_state": "red"}, "local_resource_state:red"),
    ],
)
def test_local_compute_leaf_refuses_on_local_resource_blockers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ledger_kwargs: dict[str, object],
    expected_reason: str,
) -> None:
    monkeypatch.setenv(
        COCKPIT_QUOTA_SPEND_LEDGER_ENV,
        str(_write_local_resource_ledger(tmp_path, **ledger_kwargs)),
    )
    monkeypatch.setenv(
        COCKPIT_PLATFORM_CAPABILITY_REGISTRY_ENV,
        str(_write_fresh_registry(tmp_path, route_ids=("local_tool.local.worker",))),
    )
    monkeypatch.setenv(PLATFORM_CAPABILITY_RECEIPT_DIR_ENV, "none")

    admission = admit_cockpit_agent_invocation(
        "code-review",
        manifest_model="balanced",
        flags=("--model=local-fast",),
        now=NOW,
    )

    assert admission.admitted is False
    assert expected_reason in admission.reason_codes


def test_unsupported_capacity_pool_refuses_with_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(COCKPIT_QUOTA_SPEND_LEDGER_ENV, str(_write_fresh_ledger(tmp_path)))
    leaf = CockpitSupplyLeaf(
        capability_id="cockpit.agent.test.unsupported",
        route_id="unsupported.route",
        platform_route_id="api.headless.provider_gateway",
        provider="test",
        model_alias=None,
        model_route=None,
        capacity_pool="unsupported_pool",
        profile="test",
    )

    receipt = cockpit_caps._admit_leaf(leaf, now=NOW)

    assert receipt.admitted is False
    assert receipt.reason_codes == ("unsupported_capacity_pool:unsupported_pool",)


def test_platform_route_missing_is_reported_directly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        COCKPIT_PLATFORM_CAPABILITY_REGISTRY_ENV, str(_write_fresh_registry(tmp_path))
    )
    monkeypatch.setenv(PLATFORM_CAPABILITY_RECEIPT_DIR_ENV, "none")

    reasons, refs = cockpit_caps._platform_route_block_reasons("missing.route", now=NOW)

    assert reasons == ("platform_route_missing:missing.route",)
    assert refs == ()


@pytest.mark.parametrize(
    ("error", "expected_reason"),
    [
        (
            "api.headless.provider_gateway: quota stale; checked_at expired",
            "platform_route_quota_stale",
        ),
        (
            "api.headless.provider_gateway: resource checked_at is in the future",
            "platform_route_resource_future",
        ),
        (
            "api.headless.provider_gateway: provider_docs freshness is unknown",
            "platform_route_provider_docs_unknown",
        ),
    ],
)
def test_platform_route_freshness_reason_normalizes_errors(
    error: str, expected_reason: str
) -> None:
    assert cockpit_caps._platform_route_freshness_reason(error) == expected_reason


def test_paid_llm_command_refuses_when_budget_is_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(COCKPIT_QUOTA_SPEND_LEDGER_ENV, str(_write_exhausted_ledger(tmp_path)))
    monkeypatch.setenv(
        COCKPIT_PLATFORM_CAPABILITY_REGISTRY_ENV, str(_write_fresh_registry(tmp_path))
    )
    monkeypatch.setenv(PLATFORM_CAPABILITY_RECEIPT_DIR_ENV, "none")

    admission = admit_cockpit_agent_invocation(
        "briefing",
        manifest_model="fast",
        flags=(),
        now=NOW,
    )

    assert admission.admitted is False
    assert any("cap_exhausted" in reason for reason in admission.reason_codes)


def test_model_override_changes_code_review_supply_leaf() -> None:
    capability = cockpit_capability_for_invocation(
        "code-review",
        manifest_model="balanced",
        flags=("--model=fast",),
    )

    assert len(capability.supply_leaves) == 1
    assert capability.supply_leaves[0].model_alias == "fast"
    assert capability.supply_leaves[0].model_route == "gemini-flash"


@pytest.mark.asyncio
async def test_llm_cockpit_run_refuses_before_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from logos.api.app import app
    from logos.api.cache import cache
    from logos.api.routes import agents as agent_route
    from logos.data.agents import AgentInfo

    cache.agents = [
        AgentInfo(
            name="briefing",
            uses_llm=True,
            description="Daily operational briefing",
            command="uv run python -m agents.briefing",
            model_alias="fast",
            module="agents.briefing",
        )
    ]
    monkeypatch.setattr(agent_route, "_IN_CONTAINER", False)
    run_mock = AsyncMock()
    monkeypatch.setattr(agent_route.agent_run_manager, "run", run_mock)
    monkeypatch.setenv(COCKPIT_QUOTA_SPEND_LEDGER_ENV, str(tmp_path / "missing-ledger.json"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/agents/briefing/run", json={"flags": []})

    assert response.status_code == 403
    assert "cockpit_agent_capability_admission_refused" in response.json()["detail"]
    run_mock.assert_not_called()


@pytest.mark.asyncio
async def test_llm_flag_overlay_cockpit_run_refuses_before_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from logos.api.app import app
    from logos.api.cache import cache
    from logos.api.routes import agents as agent_route
    from logos.data.agents import AgentInfo

    cache.agents = [
        AgentInfo(
            name="activity-analyzer",
            uses_llm=False,
            description="Analyze cockpit activity",
            command="uv run python -m agents.activity_analyzer",
            model_alias=None,
            module="agents.activity_analyzer",
        )
    ]
    monkeypatch.setattr(agent_route, "_IN_CONTAINER", False)
    run_mock = AsyncMock()
    monkeypatch.setattr(agent_route.agent_run_manager, "run", run_mock)
    monkeypatch.setenv(COCKPIT_QUOTA_SPEND_LEDGER_ENV, str(tmp_path / "missing-ledger.json"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/agents/activity-analyzer/run",
            json={"flags": ["--synthesize"]},
        )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert "cockpit_agent_capability_admission_refused" in detail
    assert "activity_analyzer.fast_synthesis" in detail
    run_mock.assert_not_called()


@pytest.mark.asyncio
async def test_cockpit_run_admission_errors_fail_clean_before_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from logos.api.app import app
    from logos.api.cache import cache
    from logos.api.routes import agents as agent_route
    from logos.data.agents import AgentInfo

    def raise_runtime_error(*args: object, **kwargs: object) -> None:
        raise RuntimeError("synthetic admission failure")

    cache.agents = [
        AgentInfo(
            name="activity-analyzer",
            uses_llm=False,
            description="Analyze cockpit activity",
            command="uv run python -m agents.activity_analyzer",
            model_alias=None,
            module="agents.activity_analyzer",
        )
    ]
    monkeypatch.setattr(agent_route, "_IN_CONTAINER", False)
    monkeypatch.setattr(agent_route, "require_cockpit_agent_admission", raise_runtime_error)
    run_mock = AsyncMock()
    monkeypatch.setattr(agent_route.agent_run_manager, "run", run_mock)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/agents/activity-analyzer/run", json={"flags": []})

    assert response.status_code == 403
    assert "cockpit_admission_unavailable:RuntimeError" in response.json()["detail"]
    run_mock.assert_not_called()


@pytest.mark.asyncio
async def test_untracked_llm_cockpit_run_refuses_with_next_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from logos.api.app import app
    from logos.api.cache import cache
    from logos.api.routes import agents as agent_route
    from logos.data.agents import AgentInfo

    cache.agents = [
        AgentInfo(
            name="new-llm-agent",
            uses_llm=True,
            description="Untracked LLM agent",
            command="uv run python -m agents.new_llm_agent",
            model_alias="fast",
            module="agents.new_llm_agent",
        )
    ]
    monkeypatch.setattr(agent_route, "_IN_CONTAINER", False)
    run_mock = AsyncMock()
    monkeypatch.setattr(agent_route.agent_run_manager, "run", run_mock)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/agents/new-llm-agent/run", json={"flags": []})

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert "untracked cockpit agent capability" in detail
    assert "next_action=add the cockpit agent" in detail
    run_mock.assert_not_called()
