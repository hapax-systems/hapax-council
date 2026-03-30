"""Password store and credential checks."""

from __future__ import annotations

import shlex
import time

from .. import constants as _c
from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group


@check_group("credentials")
async def check_pass_store() -> list[CheckResult]:
    t = time.monotonic()
    if _c.PASSWORD_STORE.is_dir():
        return [
            CheckResult(
                name="credentials.pass_store",
                group="credentials",
                status=Status.HEALTHY,
                message=str(_c.PASSWORD_STORE),
                duration_ms=_u._timed(t),
            )
        ]
    return [
        CheckResult(
            name="credentials.pass_store",
            group="credentials",
            status=Status.FAILED,
            message=f"Password store missing: {_c.PASSWORD_STORE}",
            remediation="pass init <gpg-id>",
            duration_ms=_u._timed(t),
        )
    ]


@check_group("credentials")
async def check_pass_entries() -> list[CheckResult]:
    t = time.monotonic()
    results: list[CheckResult] = []
    for entry in _c.PASS_ENTRIES:
        gpg_file = _c.PASSWORD_STORE / f"{entry}.gpg"
        if gpg_file.is_file():
            results.append(
                CheckResult(
                    name=f"credentials.{entry}",
                    group="credentials",
                    status=Status.HEALTHY,
                    message="present",
                    duration_ms=_u._timed(t),
                )
            )
        else:
            results.append(
                CheckResult(
                    name=f"credentials.{entry}",
                    group="credentials",
                    status=Status.FAILED,
                    message="missing",
                    remediation=f"pass insert {shlex.quote(entry)}",
                    duration_ms=_u._timed(t),
                )
            )
    return results
