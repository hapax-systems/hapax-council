"""Systemd service and timer health checks."""

from __future__ import annotations

import time

from .. import constants as _c
from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group


@check_group("systemd")
async def check_systemd_services() -> list[CheckResult]:
    services = [
        ("profile-update.timer", True, "systemctl --user enable --now profile-update.timer"),
        ("digest.timer", True, "systemctl --user enable --now digest.timer"),
        ("knowledge-maint.timer", True, "systemctl --user enable --now knowledge-maint.timer"),
        ("midi-route.service", False, None),
    ]
    results: list[CheckResult] = []

    for unit, required, fix_cmd in services:
        t = time.monotonic()
        rc, out, err = await _u.run_cmd(["systemctl", "--user", "is-active", unit])
        active = out.strip() == "active"

        detail = None
        if unit.endswith(".timer"):
            rc_en, out_en, _ = await _u.run_cmd(["systemctl", "--user", "is-enabled", unit])
            enabled = out_en.strip() == "enabled"

            if not enabled:
                results.append(
                    CheckResult(
                        name=f"systemd.{unit}",
                        group="systemd",
                        status=Status.FAILED if required else Status.HEALTHY,
                        message="not enabled",
                        remediation=fix_cmd,
                        duration_ms=_u._timed(t),
                    )
                )
                continue

            rc_t, out_t, _ = await _u.run_cmd(
                ["systemctl", "--user", "list-timers", unit, "--no-pager"]
            )
            if rc_t == 0 and out_t:
                lines = out_t.strip().splitlines()
                if len(lines) >= 2:
                    detail = lines[1].strip()

        if active:
            status = Status.HEALTHY
            msg = "active"
        elif required:
            status = Status.FAILED
            msg = out.strip() or "inactive"
        else:
            status = Status.HEALTHY
            msg = f"{out.strip() or 'inactive'} (optional)"

        results.append(
            CheckResult(
                name=f"systemd.{unit}",
                group="systemd",
                status=status,
                message=msg,
                detail=detail,
                remediation=fix_cmd if not active and required else None,
                duration_ms=_u._timed(t),
            )
        )

        if active and unit.endswith(".timer"):
            svc = unit.replace(".timer", ".service")
            t2 = time.monotonic()
            rc_s, out_s, _ = await _u.run_cmd(["systemctl", "--user", "is-failed", svc])
            if out_s.strip() == "failed":
                # Timer-backed service: a single failed run with retry pending
                # is normal operation, not degradation.
                results.append(
                    CheckResult(
                        name=f"systemd.{svc}",
                        group="systemd",
                        status=Status.HEALTHY,
                        message="last run failed (timer will retry)",
                        remediation=f"systemctl --user reset-failed {svc} && systemctl --user start {svc}",
                        duration_ms=_u._timed(t2),
                    )
                )

    return results


@check_group("systemd")
async def check_systemd_drift() -> list[CheckResult]:
    """Verify deployed systemd units match repo source."""
    t = time.monotonic()
    repo_units = _c.AI_AGENTS_DIR / "systemd" / "units"
    deployed_dir = _c.SYSTEMD_USER_DIR

    if not repo_units.exists():
        return [
            CheckResult(
                name="systemd.drift",
                group="systemd",
                status=Status.HEALTHY,
                message="No repo units directory found (skipped)",
                duration_ms=_u._timed(t),
            )
        ]

    pi6_offloaded = {
        "chrome-sync",
        "claude-code-sync",
        "gcalendar-sync",
        "gdrive-sync",
        "gmail-sync",
        "langfuse-sync",
        "obsidian-sync",
        "youtube-sync",
    }

    drifted = []
    for unit_file in sorted(repo_units.iterdir()):
        if unit_file.suffix not in (".service", ".timer"):
            continue
        stem = unit_file.name.rsplit(".", 1)[0]
        if stem in pi6_offloaded:
            continue
        deployed = deployed_dir / unit_file.name
        if not deployed.exists():
            drifted.append(f"{unit_file.name}: not deployed")
        elif unit_file.read_text() != deployed.read_text():
            drifted.append(f"{unit_file.name}: content differs")

    if drifted:
        return [
            CheckResult(
                name="systemd.drift",
                group="systemd",
                status=Status.DEGRADED,
                message=f"Systemd drift: {', '.join(drifted[:3])}{'...' if len(drifted) > 3 else ''}",
                remediation="bash ~/projects/hapax-council/systemd/scripts/install-units.sh",
                duration_ms=_u._timed(t),
            )
        ]
    return [
        CheckResult(
            name="systemd.drift",
            group="systemd",
            status=Status.HEALTHY,
            message=f"All {sum(1 for f in repo_units.iterdir() if f.suffix in ('.service', '.timer'))} units match deployed",
            duration_ms=_u._timed(t),
        )
    ]
