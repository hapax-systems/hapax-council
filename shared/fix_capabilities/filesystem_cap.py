"""Filesystem capability — disk space management via Docker prune and cache clearing."""

from __future__ import annotations

from typing import Any

from agents.health_monitor import run_cmd
from shared.fix_capabilities.base import (
    Action,
    Capability,
    ExecutionResult,
    FixProposal,
    ProbeResult,
    Safety,
)

_SAFE_CACHE_DIRS: frozenset[str] = frozenset(
    {
        "/tmp/cache",
        "/home/user/.cache/uv",
        "/home/user/.cache/pip",
    }
)

_ACTIONS: dict[str, Action] = {
    "prune_docker": Action(
        name="prune_docker",
        safety=Safety.DESTRUCTIVE,
        description="Prune unused Docker images, containers, and volumes",
    ),
    "clear_cache_dir": Action(
        name="clear_cache_dir",
        safety=Safety.DESTRUCTIVE,
        params={"dir_path": "str"},
        description="Clear contents of an allowlisted cache directory",
    ),
}


class FilesystemCapability(Capability):
    """Manage disk space by pruning Docker artifacts and clearing caches."""

    name = "filesystem"
    check_groups = {"disk"}

    async def gather_context(self, check: Any) -> ProbeResult:
        """Run df to gather disk usage information."""
        rc, stdout, stderr = await run_cmd(
            ["df", "-h", "--output=source,size,used,avail,pcent,target", "/"],
            timeout=10.0,
        )
        if rc != 0:
            return ProbeResult(
                capability=self.name,
                raw={"disk_info": "", "error": stderr},
            )
        return ProbeResult(
            capability=self.name,
            raw={"disk_info": stdout},
        )

    def available_actions(self) -> list[Action]:
        """Return available filesystem actions."""
        return list(_ACTIONS.values())

    def validate(self, proposal: FixProposal) -> bool:
        """Validate proposal: action must exist; clear_cache_dir needs allowlisted path."""
        if proposal.action_name not in _ACTIONS:
            return False
        if proposal.action_name == "clear_cache_dir":
            dir_path = proposal.params.get("dir_path")
            if not dir_path:
                return False
            if dir_path not in _SAFE_CACHE_DIRS:
                return False
        return True

    async def execute(self, proposal: FixProposal) -> ExecutionResult:
        """Execute a validated fix proposal."""
        if proposal.action_name == "prune_docker":
            rc, stdout, stderr = await run_cmd(
                ["docker", "system", "prune", "-f", "--volumes"],
                timeout=60.0,
            )
            if rc == 0:
                return ExecutionResult(
                    success=True,
                    message="Docker system prune completed",
                    output=stdout,
                )
            return ExecutionResult(
                success=False,
                message=f"Docker prune failed: {stderr}",
                output=stderr,
            )
        if proposal.action_name == "clear_cache_dir":
            dir_path = proposal.params["dir_path"]
            if dir_path not in _SAFE_CACHE_DIRS:
                return ExecutionResult(
                    success=False,
                    message=f"Directory not in allowlist: {dir_path}",
                )
            rc, stdout, stderr = await run_cmd(
                ["find", dir_path, "-mindepth", "1", "-delete"],
                timeout=30.0,
            )
            if rc == 0:
                return ExecutionResult(
                    success=True,
                    message=f"Cleared cache directory: {dir_path}",
                    output=stdout,
                )
            return ExecutionResult(
                success=False,
                message=f"Failed to clear {dir_path}: {stderr}",
                output=stderr,
            )
        return ExecutionResult(
            success=False,
            message=f"Unknown action: {proposal.action_name}",
        )
