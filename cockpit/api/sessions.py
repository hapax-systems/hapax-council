"""Session management for agent runs and chat.

AgentRunManager: tracks active subprocess, enforces single concurrent run.
SessionManager: chat session lifecycle (Phase 3).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("cockpit.api.sessions")

PROJECT_DIR = Path(__file__).parent.parent.parent


@dataclass
class AgentRunStatus:
    """Status of an active agent run."""

    agent_name: str
    started_at: float
    pid: int | None = None


class AgentRunManager:
    """Manages a single active agent subprocess.

    Enforces that only one agent runs at a time. Provides SSE-compatible
    streaming via an asyncio.Queue.
    """

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._status: AgentRunStatus | None = None
        self._lock = asyncio.Lock()

    @property
    def active(self) -> AgentRunStatus | None:
        return self._status

    @property
    def is_running(self) -> bool:
        return self._status is not None

    async def run(self, agent_name: str, args: list[str]) -> asyncio.Queue[dict]:
        """Start an agent subprocess and return a queue of SSE events.

        Uses subprocess_exec (not shell) for safety — args are passed as a list,
        never interpolated into a shell string.

        Events:
            {"event": "output", "data": {"line": "..."}}
            {"event": "done", "data": {"exit_code": N, "duration": F}}
            {"event": "error", "data": {"message": "..."}}

        Raises:
            RuntimeError: If another agent is already running.
        """
        async with self._lock:
            if self._status is not None:
                raise RuntimeError(f"Agent '{self._status.agent_name}' is already running")
            self._status = AgentRunStatus(agent_name=agent_name, started_at=time.monotonic())

        queue: asyncio.Queue[dict] = asyncio.Queue()

        async def _stream():
            start = time.monotonic()
            try:
                self._process = await asyncio.create_subprocess_exec(
                    *args,
                    cwd=str(PROJECT_DIR),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                if self._status:
                    self._status.pid = self._process.pid

                assert self._process.stdout is not None
                async for raw_line in self._process.stdout:
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                    await queue.put({"event": "output", "data": {"line": line}})

                await self._process.wait()
                exit_code = self._process.returncode or 0
                duration = time.monotonic() - start
                await queue.put(
                    {
                        "event": "done",
                        "data": {"exit_code": exit_code, "duration": round(duration, 1)},
                    }
                )
            except asyncio.CancelledError:
                if self._process and self._process.returncode is None:
                    self._process.terminate()
                    try:
                        await asyncio.wait_for(self._process.wait(), timeout=5.0)
                    except TimeoutError:
                        self._process.kill()
                duration = time.monotonic() - start
                await queue.put(
                    {
                        "event": "done",
                        "data": {
                            "exit_code": -1,
                            "duration": round(duration, 1),
                            "cancelled": True,
                        },
                    }
                )
            except Exception as e:
                log.exception("Agent run error: %s", e)
                await queue.put({"event": "error", "data": {"message": str(e)}})
            finally:
                self._process = None
                self._status = None
                await queue.put(None)  # Sentinel: stream ended

        self._task = asyncio.create_task(_stream())
        return queue

    async def cancel(self) -> bool:
        """Cancel the currently running agent. Returns True if cancelled."""
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except TimeoutError:
                self._process.kill()
            return True
        return False

    async def shutdown(self) -> None:
        """Cleanup on server shutdown."""
        await self.cancel()


# Singleton
agent_run_manager = AgentRunManager()
