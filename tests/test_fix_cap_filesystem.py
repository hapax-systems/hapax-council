"""Tests for shared.fix_capabilities.filesystem_cap — Filesystem capability module."""

from unittest.mock import AsyncMock, patch

import pytest

from shared.fix_capabilities.base import (
    Capability,
    ExecutionResult,
    FixProposal,
    ProbeResult,
    Safety,
)
from shared.fix_capabilities.filesystem_cap import FilesystemCapability


@pytest.fixture
def cap() -> FilesystemCapability:
    return FilesystemCapability()


# -- Metadata -----------------------------------------------------------------


class TestFilesystemCapabilityMetadata:
    def test_name(self, cap: FilesystemCapability) -> None:
        assert cap.name == "filesystem"

    def test_check_groups(self, cap: FilesystemCapability) -> None:
        assert cap.check_groups == {"disk"}

    def test_is_capability(self, cap: FilesystemCapability) -> None:
        assert isinstance(cap, Capability)


# -- Probe (gather_context) ---------------------------------------------------


class TestFilesystemProbe:
    @pytest.mark.asyncio
    async def test_gather_context_success(self, cap: FilesystemCapability) -> None:
        """When df succeeds, probe returns disk info."""
        df_output = (
            "Filesystem      Size  Used Avail Use% Mounted on\n"
            "/dev/nvme0n1p2  468G  312G  132G  71% /"
        )
        with patch(
            "shared.fix_capabilities.filesystem_cap.run_cmd",
            new_callable=AsyncMock,
            return_value=(0, df_output, ""),
        ):
            result = await cap.gather_context(None)

        assert isinstance(result, ProbeResult)
        assert result.capability == "filesystem"
        assert result.raw["disk_info"] == df_output


# -- Actions -------------------------------------------------------------------


class TestFilesystemActions:
    def test_available_actions(self, cap: FilesystemCapability) -> None:
        actions = cap.available_actions()
        assert len(actions) == 2
        names = {a.name for a in actions}
        assert names == {"prune_docker", "clear_cache_dir"}
        for a in actions:
            assert a.safety == Safety.DESTRUCTIVE

    def test_validate_prune_docker(self, cap: FilesystemCapability) -> None:
        proposal = FixProposal(
            capability="filesystem",
            action_name="prune_docker",
            safety=Safety.DESTRUCTIVE,
        )
        assert cap.validate(proposal) is True

    def test_validate_clear_cache_dir_valid(self, cap: FilesystemCapability) -> None:
        proposal = FixProposal(
            capability="filesystem",
            action_name="clear_cache_dir",
            params={"dir_path": "/tmp/cache"},
            safety=Safety.DESTRUCTIVE,
        )
        assert cap.validate(proposal) is True

    def test_validate_clear_cache_dir_missing_path(self, cap: FilesystemCapability) -> None:
        proposal = FixProposal(
            capability="filesystem",
            action_name="clear_cache_dir",
            params={},
            safety=Safety.DESTRUCTIVE,
        )
        assert cap.validate(proposal) is False

    def test_validate_clear_cache_dir_path_not_in_allowlist(
        self, cap: FilesystemCapability
    ) -> None:
        proposal = FixProposal(
            capability="filesystem",
            action_name="clear_cache_dir",
            params={"dir_path": "/etc/passwd"},
            safety=Safety.DESTRUCTIVE,
        )
        assert cap.validate(proposal) is False


# -- Execute -------------------------------------------------------------------


class TestFilesystemExecute:
    @pytest.mark.asyncio
    async def test_execute_prune_docker_success(self, cap: FilesystemCapability) -> None:
        proposal = FixProposal(
            capability="filesystem",
            action_name="prune_docker",
            safety=Safety.DESTRUCTIVE,
        )
        with patch(
            "shared.fix_capabilities.filesystem_cap.run_cmd",
            new_callable=AsyncMock,
            return_value=(0, "Total reclaimed space: 2.1GB", ""),
        ) as mock_cmd:
            result = await cap.execute(proposal)

        assert isinstance(result, ExecutionResult)
        assert result.success is True
        assert "prune" in result.message.lower() or "docker" in result.message.lower()
        mock_cmd.assert_called_once_with(
            ["docker", "system", "prune", "-f", "--volumes"],
            timeout=60.0,
        )
