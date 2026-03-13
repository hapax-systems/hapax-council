"""Tests for shared.fix_capabilities.docker_cap — Docker capability module."""

from unittest.mock import AsyncMock, patch

import pytest

from shared.fix_capabilities.base import (
    Capability,
    ExecutionResult,
    FixProposal,
    ProbeResult,
    Safety,
)
from shared.fix_capabilities.docker_cap import DockerCapability


@pytest.fixture
def cap() -> DockerCapability:
    return DockerCapability()


# -- Metadata -----------------------------------------------------------------


class TestDockerCapabilityMetadata:
    def test_name(self, cap: DockerCapability) -> None:
        assert cap.name == "docker"

    def test_check_groups(self, cap: DockerCapability) -> None:
        assert cap.check_groups == {
            "docker",
            "endpoints",
            "latency",
            "qdrant",
            "auth",
            "traces",
            "connectivity",
        }

    def test_is_capability(self, cap: DockerCapability) -> None:
        assert isinstance(cap, Capability)


# -- Probe (gather_context) ---------------------------------------------------


class TestDockerProbe:
    @pytest.mark.asyncio
    async def test_gather_context_success(self, cap: DockerCapability) -> None:
        """When docker ps succeeds, probe returns parsed container list."""
        docker_output = (
            "qdrant|Up 3 hours|3 hours\n"
            "ollama|Up 2 hours|2 hours\n"
            "postgres|Exited (1) 5 minutes ago|5 minutes"
        )
        with patch(
            "shared.fix_capabilities.docker_cap.run_cmd",
            new_callable=AsyncMock,
            return_value=(0, docker_output, ""),
        ):
            result = await cap.gather_context(None)

        assert isinstance(result, ProbeResult)
        assert result.capability == "docker"
        containers = result.raw["containers"]
        assert len(containers) == 3
        assert containers[0]["name"] == "qdrant"
        assert containers[0]["status"] == "Up 3 hours"
        assert containers[0]["running_for"] == "3 hours"
        assert containers[2]["name"] == "postgres"
        assert containers[2]["status"] == "Exited (1) 5 minutes ago"
        assert "error" not in result.raw

    @pytest.mark.asyncio
    async def test_gather_context_docker_unavailable(self, cap: DockerCapability) -> None:
        """When docker is unavailable, probe returns empty containers + error."""
        with patch(
            "shared.fix_capabilities.docker_cap.run_cmd",
            new_callable=AsyncMock,
            return_value=(1, "", "Cannot connect to the Docker daemon"),
        ):
            result = await cap.gather_context(None)

        assert isinstance(result, ProbeResult)
        assert result.capability == "docker"
        assert result.raw["containers"] == []
        assert "error" in result.raw
        assert "Cannot connect to the Docker daemon" in result.raw["error"]


# -- Actions -------------------------------------------------------------------


class TestDockerActions:
    def test_available_actions(self, cap: DockerCapability) -> None:
        actions = cap.available_actions()
        assert len(actions) == 2
        names = {a.name for a in actions}
        assert names == {"restart_container", "start_container"}
        for a in actions:
            assert a.safety == Safety.SAFE

    def test_validate_restart_valid(self, cap: DockerCapability) -> None:
        proposal = FixProposal(
            capability="docker",
            action_name="restart_container",
            params={"container_name": "qdrant"},
            safety=Safety.SAFE,
        )
        assert cap.validate(proposal) is True

    def test_validate_missing_container_name(self, cap: DockerCapability) -> None:
        proposal = FixProposal(
            capability="docker",
            action_name="restart_container",
            params={},
            safety=Safety.SAFE,
        )
        assert cap.validate(proposal) is False

    def test_validate_unknown_action(self, cap: DockerCapability) -> None:
        proposal = FixProposal(
            capability="docker",
            action_name="remove_container",
            params={"container_name": "qdrant"},
            safety=Safety.SAFE,
        )
        assert cap.validate(proposal) is False


# -- Execute -------------------------------------------------------------------


class TestDockerExecute:
    @pytest.mark.asyncio
    async def test_execute_restart_success(self, cap: DockerCapability) -> None:
        proposal = FixProposal(
            capability="docker",
            action_name="restart_container",
            params={"container_name": "qdrant"},
            safety=Safety.SAFE,
        )
        with patch(
            "shared.fix_capabilities.docker_cap.run_cmd",
            new_callable=AsyncMock,
            return_value=(0, "qdrant", ""),
        ) as mock_cmd:
            result = await cap.execute(proposal)

        assert isinstance(result, ExecutionResult)
        assert result.success is True
        assert "qdrant" in result.message
        mock_cmd.assert_called_once_with(
            ["docker", "restart", "qdrant"],
            timeout=30.0,
        )

    @pytest.mark.asyncio
    async def test_execute_start_success(self, cap: DockerCapability) -> None:
        proposal = FixProposal(
            capability="docker",
            action_name="start_container",
            params={"container_name": "ollama"},
            safety=Safety.SAFE,
        )
        with patch(
            "shared.fix_capabilities.docker_cap.run_cmd",
            new_callable=AsyncMock,
            return_value=(0, "ollama", ""),
        ) as mock_cmd:
            result = await cap.execute(proposal)

        assert isinstance(result, ExecutionResult)
        assert result.success is True
        assert "ollama" in result.message
        mock_cmd.assert_called_once_with(
            ["docker", "start", "ollama"],
            timeout=30.0,
        )
