"""Tests for shared.health_analysis — LLM root cause analysis (mocked)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.health_analysis import RemediationPlan, RootCauseAnalysis


class TestRootCauseAnalysis:
    def test_schema_defaults(self):
        rca = RootCauseAnalysis(
            summary="Docker Qdrant container is down",
            probable_cause="OOM killed",
        )
        assert rca.confidence == "medium"
        assert rca.related_failures == []
        assert rca.suggested_actions == []

    @pytest.mark.asyncio
    async def test_analyze_failures_calls_agent(self):
        from shared.health_analysis import analyze_failures

        mock_rca = RootCauseAnalysis(
            summary="OOM killed",
            probable_cause="Container exceeded memory limit",
            suggested_actions=["Restart qdrant"],
            confidence="high",
        )
        mock_result = MagicMock()
        mock_result.output = mock_rca
        with patch("shared.health_analysis._rca_agent") as agent:
            agent.run = AsyncMock(return_value=mock_result)
            result = await analyze_failures(
                [{"name": "docker.qdrant", "message": "not running", "detail": None}],
            )
        assert result.summary == "OOM killed"
        assert result.confidence == "high"

    def test_remediation_plan_schema(self):
        plan = RemediationPlan(
            summary="Restart qdrant",
            steps=[],
        )
        assert plan.requires_confirmation is True
