# tests/test_axiom_tools.py
"""Tests for shared.axiom_tools."""

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from shared.axiom_tools import check_axiom_compliance, get_axiom_tools, record_axiom_decision


def _mock_ctx():
    ctx = MagicMock()
    ctx.deps = MagicMock()
    return ctx


class TestCheckAxiomCompliance:
    @pytest.mark.asyncio
    async def test_compliant_when_no_violations(self):
        ctx = _mock_ctx()
        with patch("shared.axiom_enforcement.check_full") as mock_full:
            mock_full.return_value = MagicMock(
                compliant=True, violations=(), axiom_ids=(), checked_rules=5
            )
            result = await check_axiom_compliance(ctx, situation="Adding Tailscale VPN")
        assert "Compliant" in result

    @pytest.mark.asyncio
    async def test_non_compliant_shows_violations(self):
        ctx = _mock_ctx()
        with patch("shared.axiom_enforcement.check_full") as mock_full:
            mock_full.return_value = MagicMock(
                compliant=False,
                violations=("[T0] su-auth-001: No auth",),
                axiom_ids=("single_user",),
                checked_rules=5,
            )
            result = await check_axiom_compliance(ctx, situation="Adding OAuth2")
        assert "Non-compliant" in result
        assert "su-auth-001" in result
        assert "single_user" in result

    @pytest.mark.asyncio
    async def test_returns_message_when_no_axioms(self):
        ctx = _mock_ctx()
        with patch("shared.axiom_enforcement.check_full") as mock_full:
            mock_full.return_value = MagicMock(
                compliant=True, violations=(), axiom_ids=(), checked_rules=0
            )
            result = await check_axiom_compliance(ctx, situation="Any situation")
        assert "No axioms defined" in result

    @pytest.mark.asyncio
    async def test_delegates_axiom_id(self):
        ctx = _mock_ctx()
        with patch("shared.axiom_enforcement.check_full") as mock_full:
            mock_full.return_value = MagicMock(
                compliant=True, violations=(), axiom_ids=(), checked_rules=3
            )
            await check_axiom_compliance(ctx, situation="test", axiom_id="single_user")
        mock_full.assert_called_once_with(
            "test", axiom_id="single_user", domain=""
        )

    @pytest.mark.asyncio
    async def test_delegates_domain(self):
        ctx = _mock_ctx()
        with patch("shared.axiom_enforcement.check_full") as mock_full:
            mock_full.return_value = MagicMock(
                compliant=True, violations=(), axiom_ids=(), checked_rules=3
            )
            await check_axiom_compliance(ctx, situation="test", domain="management")
        mock_full.assert_called_once_with(
            "test", axiom_id="", domain="management"
        )


class TestRecordAxiomDecision:
    @pytest.mark.asyncio
    async def test_records_with_agent_authority(self):
        ctx = _mock_ctx()

        with patch("shared.axiom_precedents.PrecedentStore") as MockStore:
            MockStore.return_value.record.return_value = "PRE-001"

            result = await record_axiom_decision(
                ctx,
                axiom_id="single_user",
                situation="Adding OAuth2",
                decision="violation",
                reasoning="Multi-user identity management",
                tier="T0",
                distinguishing_facts='["Multiple user accounts"]',
            )

        assert "PRE-001" in result
        call_args = MockStore.return_value.record.call_args
        recorded = call_args[0][0]
        assert recorded.authority == "agent"

    @pytest.mark.asyncio
    async def test_handles_invalid_json_facts(self):
        ctx = _mock_ctx()

        with patch("shared.axiom_precedents.PrecedentStore") as MockStore:
            MockStore.return_value.record.return_value = "PRE-002"

            result = await record_axiom_decision(
                ctx,
                axiom_id="single_user",
                situation="Test",
                decision="compliant",
                reasoning="Test reasoning",
                distinguishing_facts="not valid json",
            )

        assert "PRE-002" in result
        call_args = MockStore.return_value.record.call_args
        recorded = call_args[0][0]
        assert recorded.distinguishing_facts == ["not valid json"]

    @pytest.mark.asyncio
    async def test_handles_store_failure(self):
        ctx = _mock_ctx()

        with patch("shared.axiom_precedents.PrecedentStore") as MockStore:
            MockStore.side_effect = ConnectionError("Qdrant down")

            result = await record_axiom_decision(
                ctx,
                axiom_id="single_user",
                situation="Test",
                decision="compliant",
                reasoning="Test reasoning",
            )

        assert "Failed to record" in result


class TestDomainAwareCompliance:
    @pytest.mark.asyncio
    async def test_check_compliance_domain_passed_through(self):
        """domain param is passed to check_full."""
        ctx = _mock_ctx()
        with patch("shared.axiom_enforcement.check_full") as mock_full:
            mock_full.return_value = MagicMock(
                compliant=True, violations=(), axiom_ids=(), checked_rules=7
            )
            await check_axiom_compliance(ctx, "test situation", domain="management")
        mock_full.assert_called_once_with("test situation", axiom_id="", domain="management")


class TestGetAxiomTools:
    def test_returns_list_of_functions(self):
        tools = get_axiom_tools()
        assert len(tools) == 2
        assert check_axiom_compliance in tools
        assert record_axiom_decision in tools


class TestUsageTelemetry:
    def test_check_axiom_compliance_logs_usage(self, tmp_path):
        """check_axiom_compliance should log usage to JSONL file."""
        usage_log = tmp_path / "tool-usage.jsonl"
        with (
            patch("shared.axiom_tools.USAGE_LOG", usage_log),
            patch(
                "shared.axiom_enforcement.check_full",
                return_value=MagicMock(
                    compliant=True, violations=(), axiom_ids=(), checked_rules=0
                ),
            ),
        ):
            ctx = _mock_ctx()
            asyncio.run(check_axiom_compliance(ctx, "test situation"))
        assert usage_log.exists()
        lines = usage_log.read_text().strip().split("\n")
        entry = json.loads(lines[0])
        assert entry["tool"] == "check_axiom_compliance"
        assert "ts" in entry

    def test_record_axiom_decision_logs_usage(self, tmp_path):
        """record_axiom_decision should log usage to JSONL file."""
        usage_log = tmp_path / "tool-usage.jsonl"
        with (
            patch("shared.axiom_tools.USAGE_LOG", usage_log),
            patch("shared.axiom_precedents.PrecedentStore") as MockStore,
        ):
            MockStore.return_value.record.return_value = "PRE-TEST"
            ctx = _mock_ctx()
            asyncio.run(record_axiom_decision(ctx, "single_user", "test", "compliant", "testing"))
        assert usage_log.exists()
        lines = usage_log.read_text().strip().split("\n")
        entry = json.loads(lines[0])
        assert entry["tool"] == "record_axiom_decision"
        assert "ts" in entry
