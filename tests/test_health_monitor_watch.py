"""Tests for watch and phone connectivity health checks."""

from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest

from agents.health_monitor import Status


class TestWatchConnectivityCheck:
    """Check #37: watch connectivity."""

    @pytest.mark.asyncio
    async def test_healthy_when_connected(self, tmp_path):
        from agents.health_monitor import check_watch_connected

        conn = tmp_path / "connection.json"
        conn.write_text(
            json.dumps(
                {
                    "last_seen_epoch": time.time(),
                    "battery_pct": 78,
                }
            )
        )
        with patch("agents.health_monitor.constants.WATCH_STATE_DIR", tmp_path):
            results = await check_watch_connected()
        assert len(results) == 1
        assert results[0].status == Status.HEALTHY
        assert "battery 78%" in results[0].message

    @pytest.mark.asyncio
    async def test_healthy_when_stale(self, tmp_path):
        from agents.health_monitor import check_watch_connected

        conn = tmp_path / "connection.json"
        conn.write_text(
            json.dumps(
                {
                    "last_seen_epoch": time.time() - 600,
                    "battery_pct": 78,
                }
            )
        )
        with patch("agents.health_monitor.constants.WATCH_STATE_DIR", tmp_path):
            results = await check_watch_connected()
        # Watch is tier 3 (non-critical), always reports HEALTHY
        assert results[0].status == Status.HEALTHY
        assert "battery 78%" in results[0].message

    @pytest.mark.asyncio
    async def test_skip_when_not_configured(self, tmp_path):
        from agents.health_monitor import check_watch_connected

        with patch("agents.health_monitor.constants.WATCH_STATE_DIR", tmp_path):
            results = await check_watch_connected()
        assert results[0].status == Status.HEALTHY
        assert "not configured" in results[0].message


class TestPhoneConnectivityCheck:
    """Check #38: phone connectivity."""

    @pytest.mark.asyncio
    async def test_healthy_when_connected(self, tmp_path):
        from agents.health_monitor import check_phone_connected

        conn = tmp_path / "phone_connection.json"
        conn.write_text(
            json.dumps(
                {
                    "last_seen_epoch": time.time(),
                    "battery_pct": 85,
                }
            )
        )
        with patch("agents.health_monitor.constants.WATCH_STATE_DIR", tmp_path):
            results = await check_phone_connected()
        assert len(results) == 1
        assert results[0].status == Status.HEALTHY
        assert "battery 85%" in results[0].message

    @pytest.mark.asyncio
    async def test_degraded_when_stale(self, tmp_path):
        from agents.health_monitor import check_phone_connected

        conn = tmp_path / "phone_connection.json"
        conn.write_text(
            json.dumps(
                {
                    "last_seen_epoch": time.time() - 600,
                    "battery_pct": 85,
                }
            )
        )
        with patch("agents.health_monitor.constants.WATCH_STATE_DIR", tmp_path):
            results = await check_phone_connected()
        assert results[0].status == Status.DEGRADED
        assert "last seen" in results[0].message

    @pytest.mark.asyncio
    async def test_not_configured_when_no_file(self, tmp_path):
        from agents.health_monitor import check_phone_connected

        with patch("agents.health_monitor.constants.WATCH_STATE_DIR", tmp_path):
            results = await check_phone_connected()
        assert results[0].status == Status.HEALTHY
        assert "not configured" in results[0].message
