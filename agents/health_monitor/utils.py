"""Shared utilities for health checks: run_cmd, http_get, timing."""

from __future__ import annotations

import asyncio
import time
from urllib.error import URLError
from urllib.request import Request, urlopen


async def run_cmd(
    cmd: list[str],
    timeout: float = 10.0,
    cwd: str | None = None,
) -> tuple[int, str, str]:
    """Run a command asynchronously and return (returncode, stdout, stderr)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return (
            proc.returncode or 0,
            stdout.decode("utf-8", errors="replace").strip(),
            stderr.decode("utf-8", errors="replace").strip(),
        )
    except TimeoutError:
        try:
            proc.kill()  # type: ignore[possibly-undefined]
        except ProcessLookupError:
            pass
        return (1, "", f"Command timed out after {timeout}s")
    except FileNotFoundError:
        return (127, "", f"Command not found: {cmd[0]}")
    except Exception as e:
        return (1, "", str(e))


async def http_get(url: str, timeout: float = 3.0) -> tuple[int, str]:
    """HTTP GET returning (status_code, body). Runs in executor to avoid blocking."""

    def _fetch() -> tuple[int, str]:
        req = Request(url)
        try:
            with urlopen(req, timeout=timeout) as resp:
                return (resp.status, resp.read().decode("utf-8", errors="replace"))
        except URLError as e:
            return (0, str(e))
        except Exception as e:
            return (0, str(e))

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch)


def _timed(start: float) -> int:
    """Return elapsed milliseconds since start."""
    return int((time.monotonic() - start) * 1000)
