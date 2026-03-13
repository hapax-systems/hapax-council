"""Profiles capability — run profiler agent when profile data is stale."""

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
    "trigger_profiler": Action(
        name="trigger_profiler",
        safety=Safety.SAFE,
        description="Trigger the profiler systemd service to refresh operator profile data",
    ),
}


class ProfilesCapability(Capability):
    """Refresh operator profile by running the profiler agent."""

    name = "profiles"
    check_groups = {"profiles"}

    async def gather_context(self, check: Any) -> ProbeResult:
        """Check profile state file for staleness info."""
        import json
        from pathlib import Path

        state_file = Path.home() / "projects" / "hapax-council" / "profiles" / ".state.json"
        if state_file.is_file():
            try:
                data = json.loads(state_file.read_text())
                return ProbeResult(
                    capability=self.name,
                    raw={"last_run": data.get("last_run", "unknown"), "state_exists": True},
                )
            except (json.JSONDecodeError, OSError) as e:
                return ProbeResult(
                    capability=self.name,
                    raw={"error": str(e), "state_exists": True},
                )
        return ProbeResult(
            capability=self.name,
            raw={"state_exists": False},
        )

    def available_actions(self) -> list[Action]:
        return list(_ACTIONS.values())

    def validate(self, proposal: FixProposal) -> bool:
        return proposal.action_name in _ACTIONS

    async def execute(self, proposal: FixProposal) -> ExecutionResult:
        if proposal.action_name != "trigger_profiler":
            return ExecutionResult(success=False, message=f"Unknown action: {proposal.action_name}")

        # Trigger the systemd service (non-blocking — systemd runs it in background)
        rc, stdout, stderr = await run_cmd(
            ["systemctl", "--user", "start", "profile-update.service"],
            timeout=15.0,
        )
        if rc == 0:
            return ExecutionResult(
                success=True,
                message="Triggered profile-update.service (running in background)",
                output=stdout,
            )
        return ExecutionResult(
            success=False,
            message=f"Failed to trigger profiler: {stderr}",
            output=stderr,
        )
