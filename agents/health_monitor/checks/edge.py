"""Raspberry Pi edge fleet health checks."""

from __future__ import annotations

import json
import time

from .. import constants as _c
from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group


@check_group("connectivity")
async def check_pi_fleet() -> list[CheckResult]:
    """Check Raspberry Pi edge nodes via heartbeat state files (tier 2)."""
    results: list[CheckResult] = []
    for hostname, spec in _c.PI_FLEET.items():
        t = time.monotonic()
        state_file = _c.EDGE_STATE_DIR / f"{hostname}.json"
        role = spec["role"]

        if not state_file.exists():
            results.append(
                CheckResult(
                    name=f"connectivity.pi.{hostname}",
                    group="connectivity",
                    status=Status.DEGRADED,
                    message=f"{hostname} ({role}): no heartbeat file",
                    remediation=f"Check if {hostname} is powered on and network-connected",
                    duration_ms=_u._timed(t),
                    tier=2,
                )
            )
            continue

        try:
            data = json.loads(state_file.read_text())
        except (json.JSONDecodeError, OSError):
            results.append(
                CheckResult(
                    name=f"connectivity.pi.{hostname}",
                    group="connectivity",
                    status=Status.DEGRADED,
                    message=f"{hostname} ({role}): heartbeat unreadable",
                    duration_ms=_u._timed(t),
                    tier=2,
                )
            )
            continue

        age = time.time() - data.get("last_seen_epoch", 0)
        cpu_temp = data.get("cpu_temp_c", "?")
        mem_avail = data.get("mem_available_mb", "?")
        disk_free = data.get("disk_free_gb", "?")
        services = data.get("services", {})
        uptime_h = data.get("uptime_s", 0) / 3600

        expected = spec.get("expected_services", [])
        down_services = [s for s in expected if services.get(s) != "active"]

        if age > 300:
            results.append(
                CheckResult(
                    name=f"connectivity.pi.{hostname}",
                    group="connectivity",
                    status=Status.DEGRADED,
                    message=f"{hostname} ({role}): last seen {age / 60:.0f}m ago",
                    remediation=f"SSH to {hostname}.local and check systemd services",
                    duration_ms=_u._timed(t),
                    tier=2,
                )
            )
        elif down_services:
            results.append(
                CheckResult(
                    name=f"connectivity.pi.{hostname}",
                    group="connectivity",
                    status=Status.DEGRADED,
                    message=(
                        f"{hostname} ({role}): services down: {', '.join(down_services)}. "
                        f"CPU {cpu_temp}\u00b0C, {mem_avail}MB free, {disk_free}GB disk"
                    ),
                    remediation=f"ssh hapax@{hostname}.local 'sudo systemctl restart {down_services[0]}'",
                    duration_ms=_u._timed(t),
                    tier=2,
                )
            )
        else:
            results.append(
                CheckResult(
                    name=f"connectivity.pi.{hostname}",
                    group="connectivity",
                    status=Status.HEALTHY,
                    message=(
                        f"{hostname} ({role}): up {uptime_h:.0f}h, "
                        f"CPU {cpu_temp}\u00b0C, {mem_avail}MB free, {disk_free}GB disk"
                    ),
                    duration_ms=_u._timed(t),
                    tier=2,
                )
            )

    return results
