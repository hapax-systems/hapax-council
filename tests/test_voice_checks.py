"""Tests for voice daemon health checks.

All I/O is mocked. No real subprocess calls or filesystem access.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agents.health_monitor import (
    CHECK_REGISTRY,
    Status,
    check_voice_services,
    check_voice_socket,
    check_voice_vram_lock,
)

# ── Registration ─────────────────────────────────────────────────────────────


def test_voice_group_registered():
    assert "voice" in CHECK_REGISTRY
    assert len(CHECK_REGISTRY["voice"]) == 3


# ── check_voice_services ────────────────────────────────────────────────────


class TestCheckVoiceServices:
    @pytest.mark.asyncio
    @patch("httpx.get", side_effect=Exception("no process-compose"))
    @patch("agents.health_monitor.utils.run_cmd", new_callable=AsyncMock)
    async def test_all_active(self, mock_cmd, _mock_httpx):
        mock_cmd.return_value = (0, "active", "")
        results = await check_voice_services()
        assert len(results) >= 2
        assert all(r.status == Status.HEALTHY for r in results)
        assert all(r.remediation is None for r in results)

    @pytest.mark.asyncio
    @patch("httpx.get", side_effect=Exception("no process-compose"))
    @patch("agents.health_monitor.utils.run_cmd", new_callable=AsyncMock)
    async def test_voice_service_down(self, mock_cmd, _mock_httpx):
        async def side_effect(cmd, **kwargs):
            unit = cmd[-1]
            if "hapax-daimonion" in unit:
                return (3, "inactive", "")
            return (0, "active", "")

        mock_cmd.side_effect = side_effect
        results = await check_voice_services()

        voice = next(r for r in results if "daemon" in r.name)
        assert voice.status == Status.FAILED

    @pytest.mark.asyncio
    @patch("httpx.get", side_effect=Exception("no process-compose"))
    @patch("agents.health_monitor.utils.run_cmd", new_callable=AsyncMock)
    async def test_bt_keepalive_down_is_degraded(self, mock_cmd, _mock_httpx):
        async def side_effect(cmd, **kwargs):
            unit = cmd[-1]
            if "pipewire" in unit:
                return (3, "inactive", "")
            return (0, "active", "")

        mock_cmd.side_effect = side_effect
        results = await check_voice_services()

        pw = next(r for r in results if "pipewire" in r.name)
        assert pw.status == Status.FAILED


# ── check_voice_socket ──────────────────────────────────────────────────────


class TestCheckVoiceSocket:
    @pytest.mark.asyncio
    @patch("agents.health_monitor.checks.voice._voice_socket_path")
    async def test_socket_exists(self, mock_path, tmp_path):
        sock = tmp_path / "hapax-daimonion.sock"
        sock.touch()
        mock_path.return_value = str(sock)
        results = await check_voice_socket()
        assert results[0].status == Status.HEALTHY
        assert "socket exists" in results[0].message

    @pytest.mark.asyncio
    @patch("agents.health_monitor.checks.voice._voice_socket_path")
    async def test_socket_missing(self, mock_path, tmp_path):
        mock_path.return_value = str(tmp_path / "nonexistent.sock")
        results = await check_voice_socket()
        assert results[0].status == Status.DEGRADED
        assert "not found" in results[0].message
        assert results[0].remediation is not None

    @pytest.mark.asyncio
    @patch("agents.health_monitor.checks.voice._voice_socket_path")
    async def test_socket_name(self, mock_path, tmp_path):
        mock_path.return_value = str(tmp_path / "hapax-daimonion.sock")
        results = await check_voice_socket()
        assert results[0].name == "voice.hotkey_socket"
        assert results[0].group == "voice"


# ── check_voice_vram_lock ───────────────────────────────────────────────────


class TestCheckVoiceVramLock:
    @pytest.mark.asyncio
    async def test_no_lock_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "agents.health_monitor.constants.VOICE_VRAM_LOCK",
            tmp_path / "nonexistent.lock",
        )
        results = await check_voice_vram_lock()
        assert results[0].status == Status.HEALTHY
        assert "no lock held" in results[0].message

    @pytest.mark.asyncio
    async def test_lock_held_by_alive_process(self, tmp_path, monkeypatch):
        import os

        lock = tmp_path / "vram.lock"
        lock.write_text(str(os.getpid()))  # current process is alive
        monkeypatch.setattr("agents.health_monitor.constants.VOICE_VRAM_LOCK", lock)
        results = await check_voice_vram_lock()
        assert results[0].status == Status.HEALTHY
        assert "alive" in results[0].message

    @pytest.mark.asyncio
    async def test_stale_lock(self, tmp_path, monkeypatch):
        lock = tmp_path / "vram.lock"
        lock.write_text("999999999")  # PID that almost certainly doesn't exist
        monkeypatch.setattr("agents.health_monitor.constants.VOICE_VRAM_LOCK", lock)
        results = await check_voice_vram_lock()
        assert results[0].status == Status.DEGRADED
        assert "stale" in results[0].message
        assert results[0].remediation is not None
        assert "rm" in results[0].remediation

    @pytest.mark.asyncio
    async def test_corrupt_lock_content(self, tmp_path, monkeypatch):
        lock = tmp_path / "vram.lock"
        lock.write_text("not-a-number")
        monkeypatch.setattr("agents.health_monitor.constants.VOICE_VRAM_LOCK", lock)
        results = await check_voice_vram_lock()
        assert results[0].status == Status.DEGRADED
        assert "stale" in results[0].message

    @pytest.mark.asyncio
    async def test_lock_name_and_group(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "agents.health_monitor.constants.VOICE_VRAM_LOCK",
            tmp_path / "nonexistent.lock",
        )
        results = await check_voice_vram_lock()
        assert results[0].name == "voice.vram_lock"
        assert results[0].group == "voice"
