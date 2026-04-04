"""Profile file and staleness health checks."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

from .. import constants as _c
from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group


@check_group("profiles")
async def check_profile_files() -> list[CheckResult]:
    t = time.monotonic()
    files = {
        ".state.json": Status.FAILED,
        "operator-profile.json": Status.FAILED,
    }
    results: list[CheckResult] = []

    for filename, severity_if_missing in files.items():
        path = _c.PROFILES_DIR / filename
        if not path.is_file():
            results.append(
                CheckResult(
                    name=f"profiles.{filename}",
                    group="profiles",
                    status=severity_if_missing,
                    message=f"missing: {path}",
                    remediation=(
                        f'cd {_c.PROFILES_DIR.parent} && eval "$(<.envrc)" && '
                        "uv run python -m agents.profiler --auto"
                    ),
                    duration_ms=_u._timed(t),
                )
            )
            continue

        try:
            text = path.read_text()
            json.loads(text)
            results.append(
                CheckResult(
                    name=f"profiles.{filename}",
                    group="profiles",
                    status=Status.HEALTHY,
                    message=f"valid JSON ({len(text)} bytes)",
                    duration_ms=_u._timed(t),
                )
            )
        except (json.JSONDecodeError, OSError) as e:
            results.append(
                CheckResult(
                    name=f"profiles.{filename}",
                    group="profiles",
                    status=Status.DEGRADED,
                    message=f"invalid JSON: {e}",
                    duration_ms=_u._timed(t),
                )
            )

    return results


@check_group("profiles")
async def check_profile_staleness() -> list[CheckResult]:
    t = time.monotonic()
    state_file = _c.PROFILES_DIR / ".state.json"
    if not state_file.is_file():
        return [
            CheckResult(
                name="profiles.staleness",
                group="profiles",
                status=Status.FAILED,
                message="No state file \u2014 cannot determine staleness",
                duration_ms=_u._timed(t),
            )
        ]

    try:
        data = json.loads(state_file.read_text())
        last_run_str = data.get("last_run")
        if not last_run_str:
            return [
                CheckResult(
                    name="profiles.staleness",
                    group="profiles",
                    status=Status.DEGRADED,
                    message="No last_run timestamp in state file",
                    duration_ms=_u._timed(t),
                )
            ]

        last_run = datetime.fromisoformat(last_run_str)
        now = datetime.now(UTC)
        if last_run.tzinfo is None:
            last_run = last_run.replace(tzinfo=UTC)
        age_hours = (now - last_run).total_seconds() / 3600

        # Timer runs every 12h — a single failure means 24h gap.
        # DEGRADED at 48h (missed 3+ cycles), FAILED at 96h.
        if age_hours < 48:
            status = Status.HEALTHY
        elif age_hours < 96:
            status = Status.DEGRADED
        else:
            status = Status.FAILED

        msg = f"last run {age_hours:.0f}h ago"
        remediation = None
        if status != Status.HEALTHY:
            remediation = (
                f'cd {_c.PROFILES_DIR.parent} && eval "$(<.envrc)" && '
                "uv run python -m agents.profiler --auto"
            )

        return [
            CheckResult(
                name="profiles.staleness",
                group="profiles",
                status=status,
                message=msg,
                remediation=remediation,
                duration_ms=_u._timed(t),
            )
        ]
    except (json.JSONDecodeError, OSError, ValueError) as e:
        return [
            CheckResult(
                name="profiles.staleness",
                group="profiles",
                status=Status.DEGRADED,
                message=f"Cannot parse state: {e}",
                duration_ms=_u._timed(t),
            )
        ]
