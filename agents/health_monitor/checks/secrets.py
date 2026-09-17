"""Secret validation checks (environment variables + the FileStore; never pass)."""

from __future__ import annotations

import os
import time

from shared.secrets import SecretIntegrityFailed, SecretUnavailable, get_secret, put_instruction

from .. import constants as _c
from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group


def _store_secret(name: str) -> str:
    """The FileStore value for ``name`` through ``shared.secrets``; ``""`` when absent.

    An integrity failure propagates: a blob that is present but will not verify must not be
    reported as "not set".
    """
    try:
        return get_secret(name, required=False) or ""
    except SecretIntegrityFailed:
        raise
    except SecretUnavailable:
        return ""


def _get_secret(env_var: str, name: str) -> tuple[str, str]:
    """Env var first, then the FileStore. Returns ``(value, source)``.

    ``source`` is ``"env"``, ``"store"``, ``""`` (absent) or ``"integrity_failed"``.
    """
    val = os.environ.get(env_var, "")
    if val:
        return val, "env"
    try:
        val = _store_secret(name)
    except SecretIntegrityFailed:
        return "", "integrity_failed"
    if val:
        return val, "store"
    return "", ""


@check_group("secrets")
async def check_env_secrets() -> list[CheckResult]:
    """Validate required secrets are accessible (env var or the FileStore)."""
    results: list[CheckResult] = []
    for var, name in _c.REQUIRED_SECRETS.items():
        t = time.monotonic()
        val, source = _get_secret(var, name)
        if source == "integrity_failed":
            results.append(
                CheckResult(
                    name=f"secrets.{var.lower()}",
                    group="secrets",
                    status=Status.FAILED,
                    message=f"{var}: stored blob failed its integrity check (not a missing secret)",
                    remediation="hapax-secret --audit",
                    duration_ms=_u._timed(t),
                )
            )
        elif not val:
            results.append(
                CheckResult(
                    name=f"secrets.{var.lower()}",
                    group="secrets",
                    status=Status.FAILED,
                    message=f"{var} not set (env or FileStore)",
                    remediation=put_instruction(name),
                    duration_ms=_u._timed(t),
                )
            )
        elif len(val) < 8:
            results.append(
                CheckResult(
                    name=f"secrets.{var.lower()}",
                    group="secrets",
                    status=Status.DEGRADED,
                    message=f"{var} suspiciously short ({len(val)} chars, via {source})",
                    duration_ms=_u._timed(t),
                )
            )
        else:
            results.append(
                CheckResult(
                    name=f"secrets.{var.lower()}",
                    group="secrets",
                    status=Status.HEALTHY,
                    message=f"{var} ok ({len(val)} chars, via {source})",
                    duration_ms=_u._timed(t),
                )
            )
    return results
