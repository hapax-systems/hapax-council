"""Tests for connectivity health checks (multi-channel access layer).

All I/O is mocked. No real subprocess calls, HTTP requests, or filesystem access.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agents.health_monitor import (
    CHECK_REGISTRY,
    Status,
    check_gdrive_sync_freshness,
    check_n8n_health,
    check_ntfy,
    check_obsidian_sync,
    check_tailscale,
)

# ── Registration ─────────────────────────────────────────────────────────────


def test_connectivity_group_registered():
    assert "connectivity" in CHECK_REGISTRY
    assert len(CHECK_REGISTRY["connectivity"]) == 8  # +1 for check_pi_fleet


# ── check_tailscale ──────────────────────────────────────────────────────────


class TestCheckTailscale:
    @pytest.mark.asyncio
    @patch("agents.health_monitor.run_cmd")
    async def test_online(self, mock_cmd):
        mock_cmd.return_value = (
            0,
            '{"Self": {"Online": true}, "Peer": {"a": {"Online": true}}}',
            "",
        )
        results = await check_tailscale()
        assert len(results) == 1
        assert results[0].status == Status.HEALTHY
        assert "1 peer" in results[0].message

    @pytest.mark.asyncio
    @patch("agents.health_monitor.run_cmd")
    async def test_offline(self, mock_cmd):
        mock_cmd.return_value = (0, '{"Self": {"Online": false}, "Peer": {}}', "")
        results = await check_tailscale()
        assert results[0].status == Status.DEGRADED
        assert "offline" in results[0].message

    @pytest.mark.asyncio
    @patch("agents.health_monitor.run_cmd")
    async def test_not_installed(self, mock_cmd):
        mock_cmd.return_value = (127, "", "tailscale: not found")
        results = await check_tailscale()
        assert results[0].status == Status.HEALTHY
        assert "not installed" in results[0].message

    @pytest.mark.asyncio
    @patch("agents.health_monitor.run_cmd")
    async def test_not_installed_no_remediation(self, mock_cmd):
        mock_cmd.return_value = (127, "", "tailscale: not found")
        results = await check_tailscale()
        assert results[0].remediation is None

    @pytest.mark.asyncio
    @patch("agents.health_monitor.run_cmd")
    async def test_error(self, mock_cmd):
        mock_cmd.return_value = (1, "", "some error")
        results = await check_tailscale()
        assert results[0].status == Status.DEGRADED

    @pytest.mark.asyncio
    @patch("agents.health_monitor.run_cmd")
    async def test_multiple_peers(self, mock_cmd):
        peers = '{"Self": {"Online": true}, "Peer": {"a": {"Online": true}, "b": {"Online": true}, "c": {"Online": false}}}'
        mock_cmd.return_value = (0, peers, "")
        results = await check_tailscale()
        assert results[0].status == Status.HEALTHY
        assert "2 peer" in results[0].message  # Only online peers counted


# ── check_ntfy ───────────────────────────────────────────────────────────────


class TestCheckNtfy:
    @pytest.mark.asyncio
    @patch("agents.health_monitor.http_get")
    async def test_healthy(self, mock_http):
        mock_http.return_value = (200, '{"healthy": true}')
        results = await check_ntfy()
        assert results[0].status == Status.HEALTHY

    @pytest.mark.asyncio
    @patch("agents.health_monitor.http_get")
    async def test_unreachable(self, mock_http):
        mock_http.return_value = (0, "connection refused")
        results = await check_ntfy()
        assert results[0].status == Status.DEGRADED
        assert "unreachable" in results[0].message

    @pytest.mark.asyncio
    @patch("agents.health_monitor.http_get")
    async def test_server_error(self, mock_http):
        mock_http.return_value = (500, "internal error")
        results = await check_ntfy()
        assert results[0].status == Status.DEGRADED


# ── check_n8n_health ─────────────────────────────────────────────────────────


class TestCheckN8nHealth:
    @pytest.mark.asyncio
    @patch("agents.health_monitor.http_get")
    async def test_healthy(self, mock_http):
        mock_http.return_value = (200, '{"status": "ok"}')
        results = await check_n8n_health()
        assert results[0].status == Status.HEALTHY

    @pytest.mark.asyncio
    @patch("agents.health_monitor.http_get")
    async def test_unreachable(self, mock_http):
        mock_http.return_value = (0, "")
        results = await check_n8n_health()
        assert results[0].status == Status.DEGRADED


# ── check_obsidian_sync ──────────────────────────────────────────────────────


class TestCheckObsidianSync:
    @pytest.mark.asyncio
    @patch("agents.health_monitor.run_cmd")
    async def test_running(self, mock_cmd):
        mock_cmd.return_value = (0, "12345", "")
        results = await check_obsidian_sync()
        assert results[0].status == Status.HEALTHY
        assert results[0].name == "connectivity.obsidian"

    @pytest.mark.asyncio
    @patch("agents.health_monitor.run_cmd")
    async def test_not_running(self, mock_cmd):
        mock_cmd.return_value = (1, "", "")
        results = await check_obsidian_sync()
        assert results[0].status == Status.DEGRADED
        assert "not running" in results[0].message
        assert results[0].remediation is None


# ── check_gdrive_sync_freshness ──────────────────────────────────────────────


class TestCheckGdriveSyncFreshness:
    @pytest.mark.asyncio
    @patch("agents.health_monitor.run_cmd")
    @patch("agents.health_monitor.RAG_SOURCES_DIR", Path("/nonexistent"))
    async def test_dir_missing(self, mock_cmd):
        results = await check_gdrive_sync_freshness()
        assert results[0].status == Status.HEALTHY
        assert "not configured" in results[0].message
        assert results[0].remediation is None

    @pytest.mark.asyncio
    @patch("agents.health_monitor.run_cmd")
    async def test_container_running(self, mock_cmd, tmp_path):
        gdrive_dir = tmp_path / "gdrive"
        gdrive_dir.mkdir(parents=True)
        mock_cmd.return_value = (0, "running", "")
        with patch("agents.health_monitor.RAG_SOURCES_DIR", tmp_path):
            results = await check_gdrive_sync_freshness()
        assert results[0].status == Status.HEALTHY

    @pytest.mark.asyncio
    @patch("agents.health_monitor.run_cmd")
    async def test_container_not_running(self, mock_cmd, tmp_path):
        gdrive_dir = tmp_path / "gdrive"
        gdrive_dir.mkdir(parents=True)
        mock_cmd.return_value = (1, "", "No such container")
        with patch("agents.health_monitor.RAG_SOURCES_DIR", tmp_path):
            results = await check_gdrive_sync_freshness()
        assert results[0].status == Status.HEALTHY
