"""Docker capability — container restart/start for failed Docker services."""

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

_ACTIONS: dict[str, Action] = {
    "restart_container": Action(
        name="restart_container",
        safety=Safety.SAFE,
        params={"container_name": "str"},
        description="Restart a Docker container",
    ),
    "start_container": Action(
        name="start_container",
        safety=Safety.SAFE,
        params={"container_name": "str"},
        description="Start a stopped Docker container",
    ),
}


class DockerCapability(Capability):
    """Manage Docker containers by restarting or starting them."""

    name = "docker"
    check_groups = {"docker", "endpoints", "latency", "qdrant", "auth", "traces", "connectivity"}

    async def gather_context(self, check: Any) -> ProbeResult:
        """Run docker ps -a to gather container status."""
        rc, stdout, stderr = await run_cmd(
            ["docker", "ps", "-a", "--format", "{{.Names}}|{{.Status}}|{{.RunningFor}}"],
            timeout=10.0,
        )
        if rc != 0:
            return ProbeResult(
                capability=self.name,
                raw={"containers": [], "error": stderr},
            )
        containers: list[dict[str, str]] = []
        for line in stdout.strip().splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3:
                containers.append(
                    {
                        "name": parts[0],
                        "status": parts[1],
                        "running_for": parts[2],
                    }
                )
        return ProbeResult(
            capability=self.name,
            raw={"containers": containers},
        )

    def available_actions(self) -> list[Action]:
        """Return available Docker actions."""
        return list(_ACTIONS.values())

    def validate(self, proposal: FixProposal) -> bool:
        """Validate proposal: action must exist and container_name must be present."""
        if proposal.action_name not in _ACTIONS:
            return False
        return bool(proposal.params.get("container_name"))

    async def execute(self, proposal: FixProposal) -> ExecutionResult:
        """Execute a validated fix proposal."""
        container_name = proposal.params["container_name"]
        if proposal.action_name == "restart_container":
            cmd = ["docker", "restart", container_name]
        elif proposal.action_name == "start_container":
            cmd = ["docker", "start", container_name]
        else:
            return ExecutionResult(
                success=False,
                message=f"Unknown action: {proposal.action_name}",
            )

        rc, stdout, stderr = await run_cmd(cmd, timeout=30.0)
        if rc == 0:
            return ExecutionResult(
                success=True,
                message=f"{proposal.action_name.replace('_', ' ').title()}: {container_name}",
                output=stdout,
            )
        return ExecutionResult(
            success=False,
            message=f"Failed to {proposal.action_name} {container_name}: {stderr}",
            output=stderr,
        )
