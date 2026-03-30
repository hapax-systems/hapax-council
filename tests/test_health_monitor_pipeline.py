"""Tests for health monitor v2 fix pipeline integration."""

from unittest.mock import AsyncMock, patch

import pytest

from agents.health_monitor import HealthReport, Status, run_fixes_v2
from shared.fix_capabilities.base import ExecutionResult, FixProposal
from shared.fix_capabilities.pipeline import FixOutcome, PipelineResult


def _make_report(status: Status = Status.FAILED) -> HealthReport:
    """Create a minimal health report for testing."""
    return HealthReport(
        timestamp="2026-03-09T00:00:00Z",
        hostname="test",
        overall_status=status,
        groups=[],
    )


def _proposal(
    action_name: str = "restart_container",
    capability: str = "docker",
    params: dict | None = None,
    rationale: str = "test",
    safety: str = "safe",
) -> FixProposal:
    return FixProposal(
        capability=capability,
        action_name=action_name,
        params=params or {},
        rationale=rationale,
        safety=safety,
    )


class TestRunFixesV2:
    """Tests for run_fixes_v2 integration."""

    @pytest.mark.asyncio
    async def test_fix_calls_pipeline(self):
        pipeline_result = PipelineResult(
            total=1,
            outcomes=[
                FixOutcome(
                    check_name="docker.qdrant",
                    proposal=_proposal(
                        action_name="restart_container",
                        capability="docker",
                        params={"container": "qdrant"},
                        rationale="Container is stopped",
                    ),
                    executed=True,
                    execution_result=ExecutionResult(
                        success=True,
                        message="Container restarted",
                    ),
                ),
            ],
        )

        with (
            patch("agents._fix_capabilities.load_builtin_capabilities") as mock_load,
            patch(
                "agents._fix_capabilities.run_fix_pipeline",
                new_callable=AsyncMock,
                return_value=pipeline_result,
            ) as mock_pipeline,
        ):
            report = _make_report()
            count = await run_fixes_v2(report, mode="apply")

            mock_load.assert_called_once()
            mock_pipeline.assert_awaited_once_with(report, mode="apply")
            assert count == 1

    @pytest.mark.asyncio
    async def test_fix_dry_run(self):
        pipeline_result = PipelineResult(
            total=1,
            outcomes=[
                FixOutcome(
                    check_name="gpu.ollama_running",
                    proposal=_proposal(
                        action_name="unload_model",
                        capability="ollama",
                        params={"model": "qwen3:30b-a3b"},
                        rationale="VRAM pressure",
                    ),
                ),
            ],
        )

        with (
            patch("agents._fix_capabilities.load_builtin_capabilities"),
            patch(
                "agents._fix_capabilities.run_fix_pipeline",
                new_callable=AsyncMock,
                return_value=pipeline_result,
            ) as mock_pipeline,
        ):
            report = _make_report()
            count = await run_fixes_v2(report, mode="dry_run")

            mock_pipeline.assert_awaited_once_with(report, mode="dry_run")
            assert count == 1

    @pytest.mark.asyncio
    async def test_no_proposals_returns_zero(self):
        pipeline_result = PipelineResult(total=0, outcomes=[])

        with (
            patch("agents._fix_capabilities.load_builtin_capabilities"),
            patch(
                "agents._fix_capabilities.run_fix_pipeline",
                new_callable=AsyncMock,
                return_value=pipeline_result,
            ),
        ):
            report = _make_report()
            count = await run_fixes_v2(report)

            assert count == 0

    @pytest.mark.asyncio
    async def test_held_destructive_outcome(self):
        pipeline_result = PipelineResult(
            total=1,
            outcomes=[
                FixOutcome(
                    check_name="docker.postgres",
                    proposal=_proposal(
                        action_name="recreate_container",
                        capability="docker",
                        params={"container": "postgres"},
                        rationale="Container unhealthy",
                        safety="destructive",
                    ),
                    notified=True,
                ),
            ],
        )

        with (
            patch("agents._fix_capabilities.load_builtin_capabilities"),
            patch(
                "agents._fix_capabilities.run_fix_pipeline",
                new_callable=AsyncMock,
                return_value=pipeline_result,
            ),
        ):
            report = _make_report()
            count = await run_fixes_v2(report, mode="apply")

            assert count == 1

    @pytest.mark.asyncio
    async def test_rejected_outcome(self):
        pipeline_result = PipelineResult(
            total=1,
            outcomes=[
                FixOutcome(
                    check_name="systemd.timer",
                    rejected_reason="Validation failed for restart_unit",
                ),
            ],
        )

        with (
            patch("agents._fix_capabilities.load_builtin_capabilities"),
            patch(
                "agents._fix_capabilities.run_fix_pipeline",
                new_callable=AsyncMock,
                return_value=pipeline_result,
            ),
        ):
            report = _make_report()
            count = await run_fixes_v2(report, mode="apply")

            assert count == 1

    @pytest.mark.asyncio
    async def test_failed_execution_outcome(self):
        pipeline_result = PipelineResult(
            total=1,
            outcomes=[
                FixOutcome(
                    check_name="docker.qdrant",
                    proposal=_proposal(
                        action_name="restart_container",
                        capability="docker",
                        params={"container": "qdrant"},
                        rationale="Container stopped",
                    ),
                    executed=True,
                    execution_result=ExecutionResult(
                        success=False,
                        message="Permission denied",
                    ),
                ),
            ],
        )

        with (
            patch("agents._fix_capabilities.load_builtin_capabilities"),
            patch(
                "agents._fix_capabilities.run_fix_pipeline",
                new_callable=AsyncMock,
                return_value=pipeline_result,
            ),
        ):
            report = _make_report()
            count = await run_fixes_v2(report, mode="apply")

            assert count == 1
