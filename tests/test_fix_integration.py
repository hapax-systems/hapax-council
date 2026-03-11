"""End-to-end integration test for the fix system."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agents.health_monitor import CheckResult, GroupResult, HealthReport, Status, worst_status
from shared.fix_capabilities import _REGISTRY, load_builtin_capabilities, get_capability_for_group
from shared.fix_capabilities.base import (
    ExecutionResult,
    FixProposal,
    ProbeResult,
    Safety,
)
from shared.fix_capabilities.pipeline import run_fix_pipeline


class TestEndToEnd:
    def setup_method(self):
        _REGISTRY.clear()
        load_builtin_capabilities()

    @pytest.mark.asyncio
    async def test_full_pipeline_gpu_fix(self):
        """GPU check fails -> Ollama probe -> LLM proposes stop_model -> executes."""
        check = CheckResult(
            name="gpu.vram", group="gpu", status=Status.FAILED,
            message="22000MiB / 24576MiB (90% used)",
            detail="Loaded Ollama models: deepseek-r1:14b",
        )
        report = HealthReport(
            timestamp="2026-03-09T12:00:00Z",
            hostname="test",
            overall_status=Status.FAILED,
            groups=[GroupResult(group="gpu", status=Status.FAILED, checks=[check])],
            total_checks=1, failed_count=1,
        )

        probe = ProbeResult(
            capability="ollama",
            raw={"models": [{"name": "deepseek-r1:14b", "size": 8_000_000_000}]},
        )
        proposal = FixProposal(
            capability="ollama", action_name="stop_model",
            params={"model_name": "deepseek-r1:14b"},
            rationale="Model using 8GB VRAM, stopping to free memory",
            safety=Safety.SAFE,
        )

        cap = get_capability_for_group("gpu")
        with patch.object(cap, "gather_context", new_callable=AsyncMock, return_value=probe), \
             patch("shared.fix_capabilities.pipeline.evaluate_check", new_callable=AsyncMock, return_value=proposal), \
             patch.object(cap, "execute", new_callable=AsyncMock, return_value=ExecutionResult(success=True, message="Stopped deepseek-r1:14b", output="ok")):
            result = await run_fix_pipeline(report, mode="apply")

        assert result.total == 1
        assert result.executed_count == 1
        assert result.outcomes[0].executed
        assert result.outcomes[0].execution_result.success

    @pytest.mark.asyncio
    async def test_full_pipeline_destructive_notifies(self):
        """Disk check fails -> filesystem probe -> LLM proposes prune -> notifies (doesn't execute)."""
        check = CheckResult(
            name="disk.space", group="disk", status=Status.FAILED,
            message="95% used",
        )
        report = HealthReport(
            timestamp="2026-03-09T12:00:00Z",
            hostname="test",
            overall_status=Status.FAILED,
            groups=[GroupResult(group="disk", status=Status.FAILED, checks=[check])],
            total_checks=1, failed_count=1,
        )

        probe = ProbeResult(capability="filesystem", raw={"disk": "95% used"})
        proposal = FixProposal(
            capability="filesystem", action_name="prune_docker",
            params={}, rationale="Disk nearly full",
            safety=Safety.DESTRUCTIVE,
        )

        cap = get_capability_for_group("disk")
        with patch.object(cap, "gather_context", new_callable=AsyncMock, return_value=probe), \
             patch("shared.fix_capabilities.pipeline.evaluate_check", new_callable=AsyncMock, return_value=proposal), \
             patch("shared.fix_capabilities.pipeline.send_notification") as mock_notify:
            result = await run_fix_pipeline(report, mode="apply")

        assert result.total == 1
        assert result.notified_count == 1
        assert not result.outcomes[0].executed
        mock_notify.assert_called_once()

    def test_all_capabilities_registered(self):
        """All expected capabilities are registered."""
        assert get_capability_for_group("gpu") is not None
        assert get_capability_for_group("docker") is not None
        assert get_capability_for_group("systemd") is not None
        assert get_capability_for_group("disk") is not None
