"""Tests for logos API data cache."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from logos.api.cache import DataCache


class TestDataCache:
    def test_initial_state_empty(self):
        cache = DataCache()
        assert cache.health is None
        assert cache.gpu is None
        assert cache.containers == []
        assert cache.timers == []
        assert cache.goals is None
        assert cache.nudges == []

    async def test_refresh_fast_populates_health(self):
        cache = DataCache()
        mock_health = AsyncMock()
        mock_health.return_value = type(
            "H",
            (),
            {
                "overall_status": "healthy",
                "total_checks": 49,
                "healthy": 49,
                "degraded": 0,
                "failed": 0,
                "duration_ms": 100,
                "failed_checks": [],
                "timestamp": "",
            },
        )()
        with (
            patch("logos.data.health.collect_live_health", mock_health),
            patch("logos.data.infrastructure.collect_docker", AsyncMock(return_value=[])),
            patch("logos.data.infrastructure.collect_timers", AsyncMock(return_value=[])),
            patch("logos.data.gpu.collect_vram", AsyncMock(return_value=None)),
        ):
            await cache.refresh_fast()
        assert cache.health is not None
        assert cache.health.overall_status == "healthy"

    async def test_refresh_slow_populates_nudges(self):
        from logos.data.goals import GoalSnapshot

        cache = DataCache()
        goal_snapshot = GoalSnapshot(active_count=0, stale_count=0, source_path="/tmp/vault")
        with (
            patch("logos.data.briefing.collect_briefing", return_value=None),
            patch("logos.data.scout.collect_scout", return_value=None),
            patch("logos.data.drift.collect_drift", return_value=None),
            patch("logos.data.cost.collect_cost", return_value=None),
            patch("logos.data.goals.collect_goals", return_value=goal_snapshot),
            patch("logos.data.readiness.collect_readiness", return_value=None),
            patch("logos.data.agents.get_agent_registry", return_value=[]),
            patch("logos.data.studio.collect_studio", return_value=None),
            patch(
                "logos.data.nudges.collect_nudges",
                return_value=[
                    type(
                        "N",
                        (),
                        {
                            "category": "test",
                            "priority_score": 50,
                            "priority_label": "medium",
                            "title": "Test nudge",
                            "detail": "",
                            "suggested_action": "",
                            "command_hint": "",
                            "source_id": "",
                        },
                    )()
                ],
            ),
            patch("logos.accommodations.load_accommodations", return_value=None),
            patch("logos.data.orientation.collect_orientation", return_value=None),
        ):
            await cache.refresh_slow()
        assert len(cache.nudges) == 1

    async def test_refresh_slow_populates_goals(self):
        from logos.data.goals import GoalSnapshot

        cache = DataCache()
        goal_snapshot = GoalSnapshot(active_count=0, stale_count=0, source_path="/tmp/vault")
        with (
            patch("logos.data.briefing.collect_briefing", return_value=None),
            patch("logos.data.scout.collect_scout", return_value=None),
            patch("logos.data.drift.collect_drift", return_value=None),
            patch("logos.data.cost.collect_cost", return_value=None),
            patch("logos.data.goals.collect_goals", return_value=goal_snapshot),
            patch("logos.data.readiness.collect_readiness", return_value=None),
            patch("logos.data.agents.get_agent_registry", return_value=[]),
            patch("logos.data.studio.collect_studio", return_value=None),
            patch("logos.data.nudges.collect_nudges", return_value=[]),
            patch("logos.accommodations.load_accommodations", return_value=None),
            patch("logos.data.orientation.collect_orientation", return_value=None),
        ):
            await cache.refresh_slow()
        assert cache.goals is goal_snapshot
        assert cache.goals.source_model == "vault-native"
