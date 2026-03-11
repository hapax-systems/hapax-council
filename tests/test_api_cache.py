"""Tests for cockpit API data cache."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from cockpit.api.cache import DataCache


class TestDataCache:
    def test_initial_state_empty(self):
        cache = DataCache()
        assert cache.health is None
        assert cache.gpu is None
        assert cache.containers == []
        assert cache.timers == []
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
            patch("cockpit.data.health.collect_live_health", mock_health),
            patch("cockpit.data.infrastructure.collect_docker", AsyncMock(return_value=[])),
            patch("cockpit.data.infrastructure.collect_timers", AsyncMock(return_value=[])),
            patch("cockpit.data.gpu.collect_vram", AsyncMock(return_value=None)),
        ):
            await cache.refresh_fast()
        assert cache.health is not None
        assert cache.health.overall_status == "healthy"

    async def test_refresh_slow_populates_nudges(self):
        cache = DataCache()
        with patch(
            "cockpit.data.nudges.collect_nudges",
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
        ):
            await cache.refresh_slow()
        assert len(cache.nudges) == 1
