"""Tests for Claude API quota seed in the spend ledger fixtures."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from shared.quota_spend_ledger import (
    PaidRouteRequest,
    build_dashboard,
    evaluate_paid_route_eligibility,
    load_quota_spend_ledger,
)

NOW = datetime(2026, 5, 17, 8, 0, 0, tzinfo=UTC)


class TestLedgerLoads:
    def test_fixture_loads_without_error(self) -> None:
        ledger = load_quota_spend_ledger()
        assert ledger.ledger_id == "quota-spend-ledger-reconciled-20260517"

    def test_quality_preserving_routes_available(self) -> None:
        ledger = load_quota_spend_ledger()
        assert ledger.quality_preserving_routes_available == "true"

    def test_local_resource_state_green(self) -> None:
        ledger = load_quota_spend_ledger()
        assert ledger.local_resource_state == "green"


class TestAnthropicQuotaSnapshot:
    def test_anthropic_snapshot_is_fresh(self) -> None:
        ledger = load_quota_spend_ledger()
        anthropic_snapshots = [s for s in ledger.quota_snapshots if s.provider == "anthropic"]
        assert len(anthropic_snapshots) == 1
        assert anthropic_snapshots[0].subscription_quota_state == "fresh"

    def test_tabbyapi_snapshot_is_fresh(self) -> None:
        ledger = load_quota_spend_ledger()
        local_snapshots = [s for s in ledger.quota_snapshots if s.provider == "tabbyapi"]
        assert len(local_snapshots) == 1
        assert local_snapshots[0].subscription_quota_state == "fresh"


class TestClaudeRouteEligibility:
    def test_claude_opus_route_eligible(self) -> None:
        ledger = load_quota_spend_ledger()
        request = PaidRouteRequest(
            route_id="litellm.anthropic.claude-opus-4",
            provider="anthropic",
            profile="frontier-full",
            task_class="agent-dispatch",
            quality_floor="frontier_required",
            estimated_cost_usd=Decimal("1.50"),
        )
        result = evaluate_paid_route_eligibility(ledger, request, now=NOW)
        assert result.eligible is True
        assert result.budget_id == "tb-20260510-anthropic-api-steady-state"
        assert result.cap_remaining_usd is not None
        assert result.cap_remaining_usd > 0

    def test_claude_coding_route_eligible(self) -> None:
        ledger = load_quota_spend_ledger()
        request = PaidRouteRequest(
            route_id="litellm.anthropic.claude-sonnet-4",
            provider="anthropic",
            profile="coding",
            task_class="agent-dispatch",
            quality_floor="capable_sufficient",
            estimated_cost_usd=Decimal("0.50"),
        )
        result = evaluate_paid_route_eligibility(ledger, request, now=NOW)
        assert result.eligible is True

    def test_google_route_eligible(self) -> None:
        ledger = load_quota_spend_ledger()
        request = PaidRouteRequest(
            route_id="litellm.google.gemini-3-pro",
            provider="google",
            profile="frontier-full",
            task_class="research",
            quality_floor="frontier_preferred",
            estimated_cost_usd=Decimal("0.80"),
        )
        result = evaluate_paid_route_eligibility(ledger, request, now=NOW)
        assert result.eligible is True

    def test_per_task_cap_enforced(self) -> None:
        ledger = load_quota_spend_ledger()
        request = PaidRouteRequest(
            route_id="litellm.anthropic.claude-opus-4",
            provider="anthropic",
            profile="frontier-full",
            task_class="agent-dispatch",
            quality_floor="frontier_required",
            estimated_cost_usd=Decimal("30.00"),
        )
        result = evaluate_paid_route_eligibility(ledger, request, now=NOW)
        assert result.eligible is False
        assert "exhausted" in result.state

    def test_unknown_provider_refused(self) -> None:
        ledger = load_quota_spend_ledger()
        request = PaidRouteRequest(
            route_id="litellm.openai.gpt-5",
            provider="openai",
            profile="frontier-full",
            task_class="agent-dispatch",
            quality_floor="frontier_required",
            estimated_cost_usd=Decimal("1.00"),
        )
        result = evaluate_paid_route_eligibility(ledger, request, now=NOW)
        assert result.eligible is False


class TestDashboard:
    def test_dashboard_shows_claude_eligible(self) -> None:
        ledger = load_quota_spend_ledger()
        dashboard = build_dashboard(ledger, now=NOW)
        assert dashboard.paid_api_route_eligible is True
        assert dashboard.subscription_quota_state == "fresh"
        assert dashboard.paid_api_budget_state == "active"
        assert dashboard.budget_ledger_stale is False

    def test_dashboard_quality_routes_available(self) -> None:
        ledger = load_quota_spend_ledger()
        dashboard = build_dashboard(ledger, now=NOW)
        assert dashboard.quality_preserving_routes_available == "true"
        assert dashboard.blocked_quality_floor_reason is None
