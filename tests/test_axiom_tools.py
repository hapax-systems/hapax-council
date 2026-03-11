# tests/test_axiom_tools.py
"""Tests for shared.axiom_tools."""
import asyncio
import json

import pytest
from unittest.mock import MagicMock, patch

from shared.axiom_tools import check_axiom_compliance, record_axiom_decision, get_axiom_tools


def _mock_ctx():
    ctx = MagicMock()
    ctx.deps = MagicMock()
    return ctx


class TestCheckAxiomCompliance:
    @pytest.mark.asyncio
    async def test_returns_precedents_when_found(self):
        ctx = _mock_ctx()
        mock_precedent = MagicMock()
        mock_precedent.id = "PRE-001"
        mock_precedent.decision = "compliant"
        mock_precedent.reasoning = "Device auth, not user auth"
        mock_precedent.tier = "T1"
        mock_precedent.authority = "operator"
        mock_precedent.distinguishing_facts = ["Single device"]
        mock_precedent.situation = "Tailscale access"

        with patch("shared.axiom_precedents.PrecedentStore") as MockStore, \
             patch("shared.axiom_registry.load_axioms") as mock_load:
            mock_axiom = MagicMock()
            mock_axiom.id = "single_user"
            mock_axiom.text = "Single user system."
            mock_load.return_value = [mock_axiom]
            MockStore.return_value.search.return_value = [mock_precedent]

            result = await check_axiom_compliance(
                ctx, situation="Adding Tailscale VPN", axiom_id="single_user",
            )

        assert "PRE-001" in result
        assert "compliant" in result

    @pytest.mark.asyncio
    async def test_returns_axiom_text_when_no_precedents(self):
        ctx = _mock_ctx()

        with patch("shared.axiom_precedents.PrecedentStore") as MockStore, \
             patch("shared.axiom_registry.load_axioms") as mock_load, \
             patch("shared.axiom_registry.load_implications") as mock_impl:
            mock_axiom = MagicMock()
            mock_axiom.id = "single_user"
            mock_axiom.text = "Single user system."
            mock_load.return_value = [mock_axiom]
            MockStore.return_value.search.return_value = []
            mock_impl.return_value = []

            result = await check_axiom_compliance(
                ctx, situation="Adding multi-tenant DB",
            )

        assert "Single user system" in result
        assert "No close precedents" in result

    @pytest.mark.asyncio
    async def test_returns_fallback_when_store_unavailable(self):
        ctx = _mock_ctx()

        with patch("shared.axiom_precedents.PrecedentStore") as MockStore, \
             patch("shared.axiom_registry.load_axioms") as mock_load:
            mock_axiom = MagicMock()
            mock_axiom.id = "single_user"
            mock_axiom.text = "Single user system."
            mock_axiom.weight = 100
            mock_axiom.type = "hardcoded"
            mock_load.return_value = [mock_axiom]
            MockStore.side_effect = ConnectionError("Qdrant down")

            result = await check_axiom_compliance(
                ctx, situation="Any situation",
            )

        assert "Precedent database unavailable" in result
        assert "single_user" in result

    @pytest.mark.asyncio
    async def test_returns_message_when_no_axioms(self):
        ctx = _mock_ctx()

        with patch("shared.axiom_registry.load_axioms") as mock_load:
            mock_load.return_value = []

            result = await check_axiom_compliance(
                ctx, situation="Any situation",
            )

        assert "No axioms defined" in result

    @pytest.mark.asyncio
    async def test_returns_not_found_for_unknown_axiom_id(self):
        ctx = _mock_ctx()

        with patch("shared.axiom_registry.load_axioms") as mock_load:
            mock_axiom = MagicMock()
            mock_axiom.id = "single_user"
            mock_load.return_value = [mock_axiom]

            result = await check_axiom_compliance(
                ctx, situation="Any situation", axiom_id="nonexistent",
            )

        assert "not found" in result


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
    async def test_check_compliance_domain_filter(self):
        """domain param includes constitutional + domain axioms."""
        ctx = _mock_ctx()
        const_axiom = MagicMock()
        const_axiom.id = "single_user"
        const_axiom.text = "Single user."
        const_axiom.scope = "constitutional"
        const_axiom.domain = None

        domain_axiom = MagicMock()
        domain_axiom.id = "management_governance"
        domain_axiom.text = "Management axiom."
        domain_axiom.scope = "domain"
        domain_axiom.domain = "management"

        with patch("shared.axiom_registry.load_axioms") as mock_load, \
             patch("shared.axiom_precedents.PrecedentStore", side_effect=Exception("no qdrant")):
            mock_load.side_effect = [
                [const_axiom],
                [domain_axiom],
            ]
            result = await check_axiom_compliance(ctx, "test situation", domain="management")

        assert "single_user" in result
        assert "management_governance" in result
        assert "[constitutional]" in result
        assert "[domain:management]" in result

    @pytest.mark.asyncio
    async def test_check_compliance_domain_includes_constitutional(self):
        """Constitutional axioms always present when domain is specified."""
        ctx = _mock_ctx()

        with patch("shared.axiom_registry.load_axioms") as mock_load, \
             patch("shared.axiom_precedents.PrecedentStore", side_effect=Exception("no qdrant")):
            const_axiom = MagicMock()
            const_axiom.id = "single_user"
            const_axiom.text = "Single user."
            const_axiom.scope = "constitutional"
            const_axiom.domain = None
            const_axiom.weight = 100
            const_axiom.type = "hardcoded"

            mock_load.side_effect = [
                [const_axiom],
                [],  # no domain axioms
            ]
            result = await check_axiom_compliance(ctx, "test situation", domain="management")

        assert mock_load.call_count == 2
        calls = mock_load.call_args_list
        assert calls[0].kwargs.get("scope") == "constitutional"
        assert calls[1].kwargs.get("domain") == "management"


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
        with patch("shared.axiom_tools.USAGE_LOG", usage_log), \
             patch("shared.axiom_registry.load_axioms", return_value=[]):
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
        with patch("shared.axiom_tools.USAGE_LOG", usage_log), \
             patch("shared.axiom_precedents.PrecedentStore") as MockStore:
            MockStore.return_value.record.return_value = "PRE-TEST"
            ctx = _mock_ctx()
            asyncio.run(record_axiom_decision(
                ctx, "single_user", "test", "compliant", "testing"
            ))
        assert usage_log.exists()
        lines = usage_log.read_text().strip().split("\n")
        entry = json.loads(lines[0])
        assert entry["tool"] == "record_axiom_decision"
        assert "ts" in entry
