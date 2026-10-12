"""Observe the process owning a sidecar, independently of its launch wrappers.

Linux pid/start-ticks pairs follow the same PID reuse convention as the estate's
orphan reaper. Observation failure narrows to shutdown, never another owner.
This module is also a stdlib-only executable for the SessionStart hook.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    start_ticks: int


def _process(pid: int, proc_root: Path) -> tuple[ProcessIdentity, int] | None:
    if pid <= 1:
        return None
    try:
        fields = (proc_root / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] in {"Z", "X", "x"}:
            return None
        return ProcessIdentity(pid, int(fields[19])), int(fields[1])
    except (OSError, IndexError, ValueError):
        return None


def process_identity(pid: int, *, proc_root: Path = Path("/proc")) -> ProcessIdentity | None:
    observed = _process(pid, proc_root)
    return observed[0] if observed else None


def find_codex_owner(pid: int, *, proc_root: Path = Path("/proc")) -> ProcessIdentity | None:
    """Find the nearest native Codex ancestor, never an arbitrary hook/uv parent.

    Executable identity comes from procfs, not a command-line substring or an
    inherited PID variable. Unsupported executable names stay unobserved.
    """
    seen: set[int] = set()
    while pid > 1 and pid not in seen:
        seen.add(pid)
        observed = _process(pid, proc_root)
        if observed is None:
            return None
        identity, parent = observed
        try:
            executable = os.readlink(proc_root / str(pid) / "exe")
        except OSError:
            return None
        if Path(executable.removesuffix(" (deleted)")).name == "codex":
            # Recheck in case the process exited or its PID was reused mid-read.
            return identity if process_identity(pid, proc_root=proc_root) == identity else None
        pid = parent
    return None


async def watch_owner(
    owner: ProcessIdentity,
    shutdown: Callable[[], None],
    *,
    interval: float = 1.0,
    proc_root: Path = Path("/proc"),
) -> None:
    """Stop this sidecar when its exact owner exits, including unreaped zombies."""
    while process_identity(owner.pid, proc_root=proc_root) == owner:
        await asyncio.sleep(interval)
    shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pid", type=int, help="hook process whose ancestry to observe")
    args = parser.parse_args()
    owner = find_codex_owner(args.pid)
    if owner is None:
        return 1
    print(owner.pid, owner.start_ticks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
