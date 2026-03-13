"""Queues capability — process or clear stale RAG retry queue entries."""

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
    "process_retry_queue": Action(
        name="process_retry_queue",
        safety=Safety.SAFE,
        description="Trigger the RAG ingest service to process retry queue items",
    ),
    "clear_retry_queue": Action(
        name="clear_retry_queue",
        safety=Safety.DESTRUCTIVE,
        description="Clear the RAG retry queue (discards failed items)",
    ),
}


class QueuesCapability(Capability):
    """Manage RAG ingestion retry queue."""

    name = "queues"
    check_groups = {"queues"}

    async def gather_context(self, check: Any) -> ProbeResult:
        """Read retry queue to understand depth and age."""
        import json
        from pathlib import Path

        retry_file = (
            Path.home() / "projects" / "hapax-council" / "data" / "rag-ingest" / "retry-queue.jsonl"
        )
        if not retry_file.exists():
            return ProbeResult(capability=self.name, raw={"depth": 0, "exists": False})

        try:
            lines = [l for l in retry_file.read_text().splitlines() if l.strip()]
            depth = len(lines)
            # Sample first and last entry for age context
            sample = {}
            if lines:
                try:
                    first = json.loads(lines[0])
                    sample["oldest"] = first.get("timestamp", first.get("added_at", "unknown"))
                except json.JSONDecodeError:
                    pass
                if len(lines) > 1:
                    try:
                        last = json.loads(lines[-1])
                        sample["newest"] = last.get("timestamp", last.get("added_at", "unknown"))
                    except json.JSONDecodeError:
                        pass
            return ProbeResult(
                capability=self.name,
                raw={"depth": depth, "exists": True, **sample},
            )
        except OSError as e:
            return ProbeResult(
                capability=self.name,
                raw={"depth": 0, "exists": True, "error": str(e)},
            )

    def available_actions(self) -> list[Action]:
        return list(_ACTIONS.values())

    def validate(self, proposal: FixProposal) -> bool:
        return proposal.action_name in _ACTIONS

    async def execute(self, proposal: FixProposal) -> ExecutionResult:
        if proposal.action_name == "process_retry_queue":
            # Trigger the systemd service (non-blocking — systemd runs it in background)
            rc, stdout, stderr = await run_cmd(
                ["systemctl", "--user", "start", "rag-ingest.service"],
                timeout=15.0,
            )
            if rc == 0:
                return ExecutionResult(
                    success=True,
                    message="Triggered rag-ingest.service (running in background)",
                    output=stdout,
                )
            return ExecutionResult(
                success=False,
                message=f"Failed to trigger RAG ingest: {stderr}",
                output=stderr,
            )

        if proposal.action_name == "clear_retry_queue":
            from pathlib import Path

            retry_file = (
                Path.home()
                / "projects"
                / "hapax-council"
                / "data"
                / "rag-ingest"
                / "retry-queue.jsonl"
            )
            if retry_file.exists():
                retry_file.write_text("")
                return ExecutionResult(
                    success=True,
                    message="Retry queue cleared",
                )
            return ExecutionResult(
                success=True,
                message="Retry queue file does not exist (already clear)",
            )

        return ExecutionResult(
            success=False,
            message=f"Unknown action: {proposal.action_name}",
        )
