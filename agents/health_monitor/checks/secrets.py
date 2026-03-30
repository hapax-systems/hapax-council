"""Secret validation checks (environment variables + pass store)."""

from __future__ import annotations

import os
import subprocess
import time

from .. import constants as _c
from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group


def _pass_show(path: str) -> str:
    """Try to read a secret from pass. Returns empty string on failure."""
    try:
        result = subprocess.run(
            ["pass", "show", path],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""


def _get_secret(env_var: str, pass_path: str) -> tuple[str, str]:
    """Get secret from env var, falling back to pass. Returns (value, source)."""
    val = os.environ.get(env_var, "")
    if val:
        return val, "env"
    val = _pass_show(pass_path)
    if val:
        return val, "pass"
    return "", ""


@check_group("secrets")
async def check_env_secrets() -> list[CheckResult]:
    """Validate required secrets are accessible (env var or pass store)."""
    results: list[CheckResult] = []
    for var, pass_path in _c.REQUIRED_SECRETS.items():
        t = time.monotonic()
        val, source = _get_secret(var, pass_path)
        if not val:
            results.append(
                CheckResult(
                    name=f"secrets.{var.lower()}",
                    group="secrets",
                    status=Status.FAILED,
                    message=f"{var} not set (env or pass)",
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
