"""Tests for shared.fix_capabilities.systemd_cap — Systemd capability module."""

from unittest.mock import AsyncMock, patch

import pytest

from shared.fix_capabilities.base import (
    Capability,
    ExecutionResult,
    FixProposal,
    ProbeResult,
    Safety,
)
from shared.fix_capabilities.systemd_cap import SystemdCapability


@pytest.fixture
def cap() -> SystemdCapability:
    return SystemdCapability()


# ── Metadata ─────────────────────────────────────────────────────────────────


class TestSystemdCapabilityMetadata:
    def test_name(self, cap: SystemdCapability) -> None:
        assert cap.name == "systemd"

    def test_check_groups(self, cap: SystemdCapability) -> None:
        assert cap.check_groups == {"systemd"}

    def test_is_capability(self, cap: SystemdCapability) -> None:
        assert isinstance(cap, Capability)


# ── Probe (gather_context) ───────────────────────────────────────────────────


class TestSystemdProbe:
    @pytest.mark.asyncio
    async def test_gather_context_success(self, cap: SystemdCapability) -> None:
        """When systemctl lists units, probe returns parsed unit info."""
        systemctl_output = (
            "health-monitor.timer loaded active waiting\n"
            "health-monitor.service loaded active running\n"
            "daily-briefing.timer loaded active waiting\n"
        )
        with patch(
            "shared.fix_capabilities.systemd_cap.run_cmd",
            new_callable=AsyncMock,
            return_value=(0, systemctl_output, ""),
        ):
            result = await cap.gather_context(None)

        assert isinstance(result, ProbeResult)
        assert result.capability == "systemd"
        assert "units" in result.raw
        assert len(result.raw["units"]) == 3


# ── Actions ──────────────────────────────────────────────────────────────────


class TestSystemdActions:
    def test_available_actions(self, cap: SystemdCapability) -> None:
        actions = cap.available_actions()
        assert len(actions) == 2
        names = {a.name for a in actions}
        assert names == {"restart_unit", "reset_failed"}
        for a in actions:
            assert a.safety == Safety.SAFE

    def test_validate_restart_valid(self, cap: SystemdCapability) -> None:
        proposal = FixProposal(
            capability="systemd",
            action_name="restart_unit",
            params={"unit_name": "health-monitor.service"},
            safety=Safety.SAFE,
        )
        assert cap.validate(proposal) is True

    def test_validate_missing_unit_name(self, cap: SystemdCapability) -> None:
        proposal = FixProposal(
            capability="systemd",
            action_name="restart_unit",
            params={},
            safety=Safety.SAFE,
        )
        assert cap.validate(proposal) is False

    def test_validate_unknown_action(self, cap: SystemdCapability) -> None:
        proposal = FixProposal(
            capability="systemd",
            action_name="stop_unit",
            params={"unit_name": "foo.service"},
            safety=Safety.SAFE,
        )
        assert cap.validate(proposal) is False


# ── Execute ──────────────────────────────────────────────────────────────────


class TestSystemdExecute:
    @pytest.mark.asyncio
    async def test_execute_restart_unit_success(self, cap: SystemdCapability) -> None:
        proposal = FixProposal(
            capability="systemd",
            action_name="restart_unit",
            params={"unit_name": "health-monitor.service"},
            safety=Safety.SAFE,
        )
        with patch(
            "shared.fix_capabilities.systemd_cap.run_cmd",
            new_callable=AsyncMock,
            return_value=(0, "", ""),
        ) as mock_cmd:
            result = await cap.execute(proposal)

        assert isinstance(result, ExecutionResult)
        assert result.success is True
        assert "health-monitor.service" in result.message
        mock_cmd.assert_called_once_with(
            ["systemctl", "--user", "restart", "health-monitor.service"],
            timeout=15.0,
        )

    @pytest.mark.asyncio
    async def test_execute_reset_failed_success(self, cap: SystemdCapability) -> None:
        proposal = FixProposal(
            capability="systemd",
            action_name="reset_failed",
            params={"unit_name": "daily-briefing.timer"},
            safety=Safety.SAFE,
        )
        with patch(
            "shared.fix_capabilities.systemd_cap.run_cmd",
            new_callable=AsyncMock,
            return_value=(0, "", ""),
        ) as mock_cmd:
            result = await cap.execute(proposal)

        assert isinstance(result, ExecutionResult)
        assert result.success is True
        assert "daily-briefing.timer" in result.message
        mock_cmd.assert_called_once_with(
            ["systemctl", "--user", "reset-failed", "daily-briefing.timer"],
            timeout=15.0,
        )
