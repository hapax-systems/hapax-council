"""Ollama capability — GPU VRAM management via Ollama model control."""

from __future__ import annotations

import json
from typing import Any

from agents.health_monitor import http_get, run_cmd
from shared.fix_capabilities.base import (
    Action,
    Capability,
    ExecutionResult,
    FixProposal,
    ProbeResult,
    Safety,
)

_OLLAMA_API_PS = "http://localhost:11434/api/ps"

_ACTIONS: dict[str, Action] = {
    "stop_model": Action(
        name="stop_model",
        safety=Safety.SAFE,
        params={"model_name": "str"},
        description="Stop a running Ollama model to free VRAM",
    ),
}


class OllamaCapability(Capability):
    """Manage GPU VRAM by stopping idle Ollama models."""

    name = "ollama"
    check_groups = {"gpu"}

    async def gather_context(self, check: Any) -> ProbeResult:
        """Query Ollama API for running models."""
        status, body = await http_get(_OLLAMA_API_PS)
        if status != 200:
            return ProbeResult(
                capability=self.name,
                raw={"models": [], "error": body},
            )
        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            return ProbeResult(
                capability=self.name,
                raw={"models": [], "error": f"JSON parse error: {e}"},
            )
        return ProbeResult(
            capability=self.name,
            raw={"models": data.get("models", [])},
        )

    def available_actions(self) -> list[Action]:
        """Return available Ollama actions."""
        return list(_ACTIONS.values())

    def validate(self, proposal: FixProposal) -> bool:
        """Validate proposal: action must exist and required params present."""
        if proposal.action_name not in _ACTIONS:
            return False
        return not (proposal.action_name == "stop_model" and not proposal.params.get("model_name"))

    async def execute(self, proposal: FixProposal) -> ExecutionResult:
        """Execute a validated fix proposal."""
        if proposal.action_name == "stop_model":
            model_name = proposal.params["model_name"]
            rc, stdout, stderr = await run_cmd(
                ["docker", "exec", "ollama", "ollama", "stop", model_name],
                timeout=30.0,
            )
            if rc == 0:
                return ExecutionResult(
                    success=True,
                    message=f"Stopped model {model_name}",
                    output=stdout,
                )
            return ExecutionResult(
                success=False,
                message=f"Failed to stop {model_name}: {stderr}",
                output=stderr,
            )
        return ExecutionResult(
            success=False,
            message=f"Unknown action: {proposal.action_name}",
        )
