"""Secret-store and credential checks: the FileStore through ``shared.secrets``, never pass."""

from __future__ import annotations

import time

from shared.secrets import has_secret, list_secret_names, put_instruction, secret_store_root

from .. import constants as _c
from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group


@check_group("credentials")
async def check_secret_store() -> list[CheckResult]:
    """The FileStore answers with at least one name (names only, never values)."""
    t = time.monotonic()
    root = secret_store_root()
    where = f" at {root}" if root is not None else " via hapax-secret"
    names = list_secret_names()
    if names:
        return [
            CheckResult(
                name="credentials.secret_store",
                group="credentials",
                status=Status.HEALTHY,
                message=f"{len(names)} names{where}",
                duration_ms=_u._timed(t),
            )
        ]
    return [
        CheckResult(
            name="credentials.secret_store",
            group="credentials",
            status=Status.FAILED,
            message=f"FileStore unreachable or empty{where}",
            remediation="install the reins API (hapax-secret) on this host, then put the first secret",
            duration_ms=_u._timed(t),
        )
    ]


@check_group("credentials")
async def check_secret_entries() -> list[CheckResult]:
    t = time.monotonic()
    results: list[CheckResult] = []
    for entry in _c.EXPECTED_SECRETS:
        if has_secret(entry):
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
                    remediation=put_instruction(entry),
                    duration_ms=_u._timed(t),
                )
            )
    return results
