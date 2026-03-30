"""Docker container health checks."""

from __future__ import annotations

import json
import shlex
import time

from .. import constants as _c
from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group


@check_group("docker")
async def check_docker_daemon() -> list[CheckResult]:
    t = time.monotonic()
    rc, out, err = await _u.run_cmd(["docker", "info", "--format", "{{.ServerVersion}}"])
    if rc == 0 and out:
        return [
            CheckResult(
                name="docker.daemon",
                group="docker",
                status=Status.HEALTHY,
                message=f"Docker {out}",
                duration_ms=_u._timed(t),
            )
        ]
    return [
        CheckResult(
            name="docker.daemon",
            group="docker",
            status=Status.FAILED,
            message="Docker daemon unreachable",
            detail=err or out,
            remediation="sudo systemctl start docker",
            duration_ms=_u._timed(t),
        )
    ]


@check_group("docker")
async def check_compose_file() -> list[CheckResult]:
    t = time.monotonic()
    if _c.COMPOSE_FILE.is_file():
        return [
            CheckResult(
                name="docker.compose_file",
                group="docker",
                status=Status.HEALTHY,
                message=str(_c.COMPOSE_FILE),
                duration_ms=_u._timed(t),
            )
        ]
    return [
        CheckResult(
            name="docker.compose_file",
            group="docker",
            status=Status.FAILED,
            message=f"Compose file missing: {_c.COMPOSE_FILE}",
            remediation=f"ls -la {_c.COMPOSE_FILE.parent}/",
            duration_ms=_u._timed(t),
        )
    ]


@check_group("docker")
async def check_docker_containers() -> list[CheckResult]:
    t = time.monotonic()
    rc, out, err = await _u.run_cmd(
        ["docker", "compose", "-f", str(_c.COMPOSE_FILE), "ps", "--format", "json"]
    )
    if rc != 0:
        return [
            CheckResult(
                name="docker.containers",
                group="docker",
                status=Status.FAILED,
                message="docker compose ps failed",
                detail=err or out,
                duration_ms=_u._timed(t),
            )
        ]

    results: list[CheckResult] = []
    if not out:
        return [
            CheckResult(
                name="docker.containers",
                group="docker",
                status=Status.FAILED,
                message="No containers found",
                remediation=f"cd {_c.COMPOSE_FILE.parent} && docker compose up -d",
                duration_ms=_u._timed(t),
            )
        ]

    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            container = json.loads(line)
        except json.JSONDecodeError:
            continue

        name = container.get("Name", container.get("Service", "unknown"))
        service = container.get("Service", name)
        state = container.get("State", "unknown").lower()
        health = container.get("Health", "").lower()

        is_core = service in _c.CORE_CONTAINERS
        running = state == "running"

        if running and health in ("healthy", "", "starting"):
            status = Status.HEALTHY
            msg = f"running ({health})" if health else "running"
        elif running and health == "unhealthy":
            status = Status.DEGRADED
            msg = "running (unhealthy)"
        else:
            status = Status.FAILED if is_core else Status.DEGRADED
            msg = f"not running ({state})" if not is_core else f"not running ({state}) — CORE"

        remediation = None
        if not running:
            remediation = (
                f"cd {_c.COMPOSE_FILE.parent} && docker compose up -d {shlex.quote(service)}"
            )

        results.append(
            CheckResult(
                name=f"docker.{service}",
                group="docker",
                status=status,
                message=msg,
                remediation=remediation,
                duration_ms=_u._timed(t),
            )
        )

    return results


@check_group("docker")
async def check_agents_containers() -> list[CheckResult]:
    """Agents migrated from Docker to systemd user services."""
    t = time.monotonic()
    return [
        CheckResult(
            name="docker.agents_compose",
            group="docker",
            status=Status.HEALTHY,
            message="agents run as systemd user services (not Docker)",
            duration_ms=_u._timed(t),
        )
    ]
