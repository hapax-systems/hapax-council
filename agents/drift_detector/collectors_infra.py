"""Infrastructure collectors — Docker, systemd, listening ports."""

from __future__ import annotations

import json

from .config import LLM_STACK_DIR
from .introspect import run_cmd
from .models import ContainerInfo, SystemdUnit

COMPOSE_FILE = LLM_STACK_DIR / "docker-compose.yml"


async def collect_docker() -> tuple[str, list[ContainerInfo]]:
    rc, ver, _ = await run_cmd(["docker", "info", "--format", "{{.ServerVersion}}"])
    version = ver.strip() if rc == 0 else ""

    rc, out, _ = await run_cmd(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "ps", "--format", "json"]
    )
    containers = []
    if rc == 0 and out:
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                c = json.loads(line)
                ports = []
                for p in c.get("Publishers", []):
                    if p.get("PublishedPort"):
                        ports.append(
                            f"{p.get('URL', '')}:{p['PublishedPort']}->"
                            f"{p['TargetPort']}/{p.get('Protocol', 'tcp')}"
                        )
                containers.append(
                    ContainerInfo(
                        name=c.get("Name", ""),
                        service=c.get("Service", ""),
                        image=c.get("Image", ""),
                        state=c.get("State", ""),
                        health=c.get("Health", ""),
                        ports=ports,
                    )
                )
            except (json.JSONDecodeError, KeyError):
                continue

    return version, containers


async def collect_systemd() -> tuple[list[SystemdUnit], list[SystemdUnit]]:
    services: list[SystemdUnit] = []
    timers: list[SystemdUnit] = []

    for unit_type, target_list in [("service", services), ("timer", timers)]:
        rc, out, _ = await run_cmd(
            [
                "systemctl",
                "--user",
                "list-units",
                f"--type={unit_type}",
                "--no-pager",
                "--no-legend",
                "--plain",
            ]
        )
        if rc == 0 and out:
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 4:
                    name = parts[0]
                    active = parts[2]
                    rc2, en, _ = await run_cmd(["systemctl", "--user", "is-enabled", name])
                    rc3, desc, _ = await run_cmd(
                        [
                            "systemctl",
                            "--user",
                            "show",
                            name,
                            "--property=Description",
                            "--value",
                        ]
                    )
                    target_list.append(
                        SystemdUnit(
                            name=name,
                            type=unit_type,
                            active=active,
                            enabled=en.strip() if rc2 == 0 else "unknown",
                            description=desc.strip() if rc3 == 0 else "",
                        )
                    )

    return services, timers


async def collect_listening_ports_observation() -> tuple[list[str], str, str]:
    """Get currently listening TCP ports with observation status."""
    rc, out, err = await run_cmd(["ss", "-tlnp"])
    if rc != 0:
        detail = err.strip() or f"exit code {rc}"
        return [], "inconclusive", f"ss -tlnp failed: {detail}"

    ports: list[str] = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 4 and parts[0] == "LISTEN":
            ports.append(parts[3])

    if not ports:
        return [], "inconclusive", "ss -tlnp returned no TCP listeners"

    return sorted(set(ports)), "observed", ""


async def collect_listening_ports() -> list[str]:
    """Get currently listening TCP ports."""
    ports, _, _ = await collect_listening_ports_observation()
    return ports
