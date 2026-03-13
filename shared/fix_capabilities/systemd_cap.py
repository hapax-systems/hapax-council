"""Systemd capability — restart and reset-failed for user units."""

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
    "restart_unit": Action(
        name="restart_unit",
        safety=Safety.SAFE,
        params={"unit_name": "str"},
        description="Restart a systemd user unit",
    ),
    "reset_failed": Action(
        name="reset_failed",
        safety=Safety.SAFE,
        params={"unit_name": "str"},
        description="Reset failed state of a systemd user unit",
    ),
    "sync_units": Action(
        name="sync_units",
        safety=Safety.SAFE,
        description="Copy repo systemd units to deployed location and reload",
    ),
}


class SystemdCapability(Capability):
    """Manage systemd user units — restart services and reset failed states."""

    name = "systemd"
    check_groups = {"systemd", "sync", "voice", "backup"}

    async def gather_context(self, check: Any) -> ProbeResult:
        """List all user timers and services via systemctl."""
        rc, stdout, stderr = await run_cmd(
            [
                "systemctl",
                "--user",
                "list-units",
                "--type=timer,service",
                "--all",
                "--no-pager",
                "--plain",
                "--no-legend",
            ],
            timeout=15.0,
        )
        units: list[dict[str, str]] = []
        if rc == 0:
            for line in stdout.strip().splitlines():
                parts = line.split()
                if len(parts) >= 4:
                    units.append(
                        {
                            "unit": parts[0],
                            "load": parts[1],
                            "active": parts[2],
                            "sub": parts[3],
                        }
                    )
        return ProbeResult(
            capability=self.name,
            raw={"units": units, **({"error": stderr} if rc != 0 else {})},
        )

    def available_actions(self) -> list[Action]:
        """Return available systemd actions."""
        return list(_ACTIONS.values())

    def validate(self, proposal: FixProposal) -> bool:
        """Validate proposal: action must exist and unit_name must be present."""
        if proposal.action_name not in _ACTIONS:
            return False
        return bool(proposal.params.get("unit_name"))

    async def execute(self, proposal: FixProposal) -> ExecutionResult:
        """Execute a validated fix proposal."""
        if proposal.action_name == "sync_units":
            return await self._sync_units()

        unit_name = proposal.params["unit_name"]

        if proposal.action_name == "restart_unit":
            cmd = ["systemctl", "--user", "restart", unit_name]
        elif proposal.action_name == "reset_failed":
            cmd = ["systemctl", "--user", "reset-failed", unit_name]
        else:
            return ExecutionResult(
                success=False,
                message=f"Unknown action: {proposal.action_name}",
            )

        rc, stdout, stderr = await run_cmd(cmd, timeout=15.0)
        if rc == 0:
            return ExecutionResult(
                success=True,
                message=f"{proposal.action_name} succeeded for {unit_name}",
                output=stdout,
            )
        return ExecutionResult(
            success=False,
            message=f"{proposal.action_name} failed for {unit_name}: {stderr}",
            output=stderr,
        )

    async def _sync_units(self) -> ExecutionResult:
        """Copy repo systemd units to user config dir and reload daemon."""
        import shutil
        from pathlib import Path

        from shared.config import SYSTEMD_USER_DIR

        repo_units = Path.home() / "projects" / "hapax-council" / "systemd" / "units"
        if not repo_units.exists():
            return ExecutionResult(success=False, message="Repo units dir not found")

        synced = []
        for unit_file in sorted(repo_units.iterdir()):
            if unit_file.suffix not in (".service", ".timer"):
                continue
            dest = SYSTEMD_USER_DIR / unit_file.name
            if not dest.exists() or unit_file.read_text() != dest.read_text():
                shutil.copy2(unit_file, dest)
                synced.append(unit_file.name)

        if not synced:
            return ExecutionResult(success=True, message="All units already in sync")

        rc, stdout, stderr = await run_cmd(["systemctl", "--user", "daemon-reload"], timeout=15.0)
        if rc != 0:
            return ExecutionResult(
                success=False,
                message=f"daemon-reload failed after syncing {synced}: {stderr}",
            )
        return ExecutionResult(
            success=True,
            message=f"Synced {len(synced)} units: {', '.join(synced)}",
        )
