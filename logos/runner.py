"""AgentRunner — subprocess lifecycle with streaming output."""

from __future__ import annotations

import asyncio
import shlex
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunResult:
    """Result of an agent or shell command execution."""

    args: list[str]
    exit_code: int
    duration_s: float
    cancelled: bool = False


class AgentRunner:
    """Manages subprocess execution with line-by-line output streaming.

    Args:
        project_dir: Working directory for subprocess execution.
        output_callback: Called with each line of stdout/stderr output.
    """

    def __init__(
        self,
        project_dir: Path,
        output_callback: Callable[[str], None],
    ) -> None:
        self._project_dir = project_dir
        self._callback = output_callback
        self._process: asyncio.subprocess.Process | None = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    async def run(self, args: list[str], label: str = "") -> RunResult:
        """Execute a command via subprocess_exec with streamed output.

        Args:
            args: Command and arguments (e.g. ["uv", "run", "python", "-m", "agents.briefing", "--save"]).
            label: Human-readable label for output header.
        """
        if self._running:
            self._callback("[runner] Another command is already running")
            return RunResult(args=args, exit_code=-1, duration_s=0.0)

        self._running = True
        cmd_str = " ".join(args)
        self._callback(f"$ {cmd_str}")

        start = time.monotonic()
        try:
            self._process = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(self._project_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            assert self._process.stdout is not None
            async for raw_line in self._process.stdout:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                self._callback(line)

            await self._process.wait()
            exit_code = self._process.returncode or 0
            duration = time.monotonic() - start

            status = "done" if exit_code == 0 else f"failed (exit {exit_code})"
            tag = label or args[-1] if args else "command"
            self._callback(f"--- {tag} {status} ({duration:.1f}s) ---")

            return RunResult(args=args, exit_code=exit_code, duration_s=duration)
        except asyncio.CancelledError:
            if self._process and self._process.returncode is None:
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=5.0)
                except TimeoutError:
                    self._process.kill()
            duration = time.monotonic() - start
            self._callback(f"--- {label or 'command'} cancelled ({duration:.1f}s) ---")
            return RunResult(args=args, exit_code=-1, duration_s=duration, cancelled=True)
        finally:
            self._process = None
            self._running = False

    async def run_shell(self, command: str, label: str = "") -> RunResult:
        """Execute a shell command string (supports pipes, redirects, etc.).

        Args:
            command: Shell command string.
            label: Human-readable label for output header.
        """
        if self._running:
            self._callback("[runner] Another command is already running")
            return RunResult(args=[command], exit_code=-1, duration_s=0.0)

        self._running = True
        self._callback(f"$ {command}")

        start = time.monotonic()
        try:
            self._process = await asyncio.create_subprocess_shell(
                command,
                cwd=str(self._project_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            assert self._process.stdout is not None
            async for raw_line in self._process.stdout:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                self._callback(line)

            await self._process.wait()
            exit_code = self._process.returncode or 0
            duration = time.monotonic() - start

            status = "done" if exit_code == 0 else f"failed (exit {exit_code})"
            tag = label or "shell"
            self._callback(f"--- {tag} {status} ({duration:.1f}s) ---")

            return RunResult(args=[command], exit_code=exit_code, duration_s=duration)
        except asyncio.CancelledError:
            if self._process and self._process.returncode is None:
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=5.0)
                except TimeoutError:
                    self._process.kill()
            duration = time.monotonic() - start
            self._callback(f"--- {label or 'shell'} cancelled ({duration:.1f}s) ---")
            return RunResult(args=[command], exit_code=-1, duration_s=duration, cancelled=True)
        finally:
            self._process = None
            self._running = False

    def cancel(self) -> None:
        """Request cancellation of the running process."""
        if self._process and self._process.returncode is None:
            self._process.terminate()

    @staticmethod
    def is_agent_command(command: str) -> bool:
        """Check if a command string is a direct agent invocation (safe for exec)."""
        return command.startswith("uv run python -m agents.")

    @staticmethod
    def parse_agent_command(command: str) -> list[str]:
        """Parse an agent command string into exec args."""
        return shlex.split(command)
