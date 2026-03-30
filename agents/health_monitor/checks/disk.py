"""Disk space health checks."""

from __future__ import annotations

import time

from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group


@check_group("disk")
async def check_disk_usage() -> list[CheckResult]:
    t = time.monotonic()
    rc, out, err = await _u.run_cmd(["df", "--output=pcent", "/home"])
    if rc != 0:
        return [
            CheckResult(
                name="disk.home",
                group="disk",
                status=Status.DEGRADED,
                message="Cannot check disk usage",
                detail=err,
                duration_ms=_u._timed(t),
            )
        ]

    lines = out.strip().splitlines()
    if len(lines) < 2:
        return [
            CheckResult(
                name="disk.home",
                group="disk",
                status=Status.DEGRADED,
                message=f"Unexpected df output: {out}",
                duration_ms=_u._timed(t),
            )
        ]

    try:
        pct = int(lines[-1].strip().rstrip("%"))
    except ValueError:
        return [
            CheckResult(
                name="disk.home",
                group="disk",
                status=Status.DEGRADED,
                message=f"Cannot parse disk usage: {lines[-1]}",
                duration_ms=_u._timed(t),
            )
        ]

    if pct < 85:
        status = Status.HEALTHY
    elif pct < 95:
        status = Status.DEGRADED
    else:
        status = Status.FAILED

    return [
        CheckResult(
            name="disk.home",
            group="disk",
            status=status,
            message=f"/home {pct}% used",
            remediation="docker system prune -f" if status != Status.HEALTHY else None,
            duration_ms=_u._timed(t),
        )
    ]
