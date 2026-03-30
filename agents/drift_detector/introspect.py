"""Infrastructure manifest generator — utilities and orchestration.

Individual collectors are in collectors.py and collectors_infra.py.
Human-readable formatting is in manifest_fmt.py.
"""

from __future__ import annotations

import asyncio
import json
import socket
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from opentelemetry import trace

from .models import EdgeNodeInfo, InfrastructureManifest

_tracer = trace.get_tracer(__name__)

# Re-export format_summary for backward compatibility
from .manifest_fmt import format_summary as format_summary  # noqa: F401

# ── Inlined utilities from health_monitor ──────────────────────────────────


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
            stdout.decode("utf-8", errors="replace") if stdout else "",
            stderr.decode("utf-8", errors="replace") if stderr else "",
        )
    except TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return (-1, "", "timeout")
    except FileNotFoundError:
        return (-1, "", f"command not found: {cmd[0]}")
    except Exception as e:
        return (-1, "", str(e))


async def http_get(url: str, timeout: float = 3.0) -> tuple[int, str]:
    """HTTP GET returning (status_code, body). Runs in executor."""

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


# ── Main collector ───────────────────────────────────────────────────────


async def generate_manifest() -> InfrastructureManifest:
    """Collect all infrastructure state into a single manifest."""
    with _tracer.start_as_current_span(
        "introspect.generate",
        attributes={"agent.name": "introspect", "agent.repo": "hapax-council"},
    ):
        return await _generate_manifest_inner()


async def _generate_manifest_inner() -> InfrastructureManifest:
    """Inner implementation of generate_manifest (wrapped by OTel span)."""
    from .collectors import (
        COMPOSE_FILE,
        collect_disk,
        collect_docker,
        collect_gpu,
        collect_listening_ports,
        collect_litellm_routes,
        collect_ollama,
        collect_pass_entries,
        collect_profile_files,
        collect_qdrant,
        collect_systemd,
    )

    (
        (docker_version, containers),
        (services, timers_list),
        collections,
        models,
        gpu,
        routes,
        disks,
        ports,
    ) = await asyncio.gather(
        collect_docker(),
        collect_systemd(),
        collect_qdrant(),
        collect_ollama(),
        collect_gpu(),
        collect_litellm_routes(),
        collect_disk(),
        collect_listening_ports(),
    )

    rc, os_info, _ = await run_cmd(["uname", "-sr"])

    edge_state_dir = Path.home() / "hapax-state" / "edge"
    edge_nodes: list[EdgeNodeInfo] = []
    if edge_state_dir.is_dir():
        for f in sorted(edge_state_dir.glob("*.json")):
            try:
                edge_nodes.append(EdgeNodeInfo.model_validate(json.loads(f.read_text())))
            except (json.JSONDecodeError, OSError):
                edge_nodes.append(EdgeNodeInfo(hostname=f.stem, error="unreadable"))

    return InfrastructureManifest(
        timestamp=datetime.now(UTC).isoformat(),
        hostname=socket.gethostname(),
        os_info=os_info.strip() if rc == 0 else "",
        docker_version=docker_version,
        containers=containers,
        systemd_units=services,
        systemd_timers=timers_list,
        qdrant_collections=collections,
        ollama_models=models,
        gpu=gpu,
        litellm_routes=routes,
        disk=disks,
        listening_ports=ports,
        pass_entries=collect_pass_entries(),
        compose_file=str(COMPOSE_FILE) if COMPOSE_FILE.is_file() else "",
        profile_files=collect_profile_files(),
        edge_nodes=edge_nodes,
    )
