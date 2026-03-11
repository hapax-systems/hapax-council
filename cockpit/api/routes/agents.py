"""Agent execution endpoints — run agents with SSE streaming output."""
from __future__ import annotations

import json
import os
import shlex

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from cockpit.api.cache import cache
from cockpit.api.sessions import agent_run_manager

# Detect if running inside Docker (/.dockerenv exists or init is not systemd)
_IN_CONTAINER = os.path.exists("/.dockerenv") or (
    os.path.exists("/proc/1/cgroup") and "docker" in open("/proc/1/cgroup").read()
)

router = APIRouter(prefix="/api/agents", tags=["agents"])


class AgentRunRequest(BaseModel):
    flags: list[str] = []


@router.post("/{name}/run")
async def run_agent(name: str, req: AgentRunRequest):
    """Start an agent subprocess with SSE streaming output.

    Returns an SSE stream with events: output, done, error.
    """
    # Find agent in registry
    agent = None
    for a in cache.agents or []:
        a_name = a.name if hasattr(a, "name") else a.get("name", "")
        if a_name == name:
            agent = a
            break

    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    if _IN_CONTAINER:
        raise HTTPException(
            status_code=503,
            detail="Agent execution unavailable in container mode. "
            "Run agents via CLI on the host.",
        )

    if agent_run_manager.is_running:
        raise HTTPException(status_code=409, detail="Another agent is already running")

    # Build command args from agent's base command + user flags
    command = agent.command if hasattr(agent, "command") else agent.get("command", "")
    args = shlex.split(command) + req.flags

    try:
        queue = await agent_run_manager.run(name, args)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))

    async def event_generator():
        while True:
            event = await queue.get()
            if event is None:
                break
            yield {
                "event": event["event"],
                "data": json.dumps(event["data"]),
            }

    return EventSourceResponse(event_generator())


@router.delete("/runs/current")
async def cancel_agent():
    """Cancel the currently running agent."""
    if not agent_run_manager.is_running:
        return JSONResponse(status_code=404, content={"detail": "No agent running"})

    cancelled = await agent_run_manager.cancel()
    return {"status": "cancelled" if cancelled else "not_running"}


@router.get("/runs/current")
async def get_run_status():
    """Get the status of the currently running agent."""
    status = agent_run_manager.active
    if status is None:
        return {"running": False}
    return {
        "running": True,
        "agent_name": status.agent_name,
        "pid": status.pid,
        "elapsed_s": round(__import__("time").monotonic() - status.started_at, 1),
    }
