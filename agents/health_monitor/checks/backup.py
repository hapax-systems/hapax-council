"""Backup freshness checks (restic)."""

from __future__ import annotations

import time

from .. import constants as _c
from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group


@check_group("backup")
async def check_backup_freshness() -> list[CheckResult]:
    """GAP-13: Check local restic backup recency via repo mtime."""
    t = time.monotonic()

    candidates = [
        _c.RESTIC_REPO / "locks",
        _c.RESTIC_REPO / "snapshots",
        _c.RESTIC_REPO / "index",
    ]
    latest_mtime: float | None = None
    checked_path = ""
    for p in candidates:
        if p.exists():
            try:
                mtime = p.stat().st_mtime
                if latest_mtime is None or mtime > latest_mtime:
                    latest_mtime = mtime
                    checked_path = str(p)
            except OSError:
                continue

    if latest_mtime is None:
        return [
            CheckResult(
                name="backup.restic_freshness",
                group="backup",
                status=Status.FAILED,
                message="Restic repo not found or empty",
                detail=f"Checked: {_c.RESTIC_REPO}",
                remediation="systemctl --user start hapax-backup-local.service",
                duration_ms=_u._timed(t),
                tier=2,
            )
        ]

    age_h = (time.time() - latest_mtime) / 3600
    if age_h > _c.BACKUP_FAILED_H:
        status = Status.FAILED
        msg = f"Backup {age_h:.0f}h old (>{_c.BACKUP_FAILED_H}h)"
    elif age_h > _c.BACKUP_STALE_H:
        status = Status.DEGRADED
        msg = f"Backup {age_h:.0f}h old (>{_c.BACKUP_STALE_H}h)"
    else:
        status = Status.HEALTHY
        msg = f"Backup {age_h:.1f}h old"

    return [
        CheckResult(
            name="backup.restic_freshness",
            group="backup",
            status=status,
            message=msg,
            detail=f"Latest activity in {checked_path}",
            remediation="systemctl --user start hapax-backup-local.service"
            if status != Status.HEALTHY
            else None,
            duration_ms=_u._timed(t),
            tier=2,
        )
    ]
