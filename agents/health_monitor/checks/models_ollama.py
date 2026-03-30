"""Ollama model availability checks."""

from __future__ import annotations

import json
import shlex
import time

from .. import constants as _c
from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group


@check_group("models")
async def check_ollama_models() -> list[CheckResult]:
    """Verify expected Ollama models are pulled."""
    t = time.monotonic()
    code, body = await _u.http_get(f"{_c.OLLAMA_URL}/api/tags", timeout=5.0)
    if code != 200:
        return [
            CheckResult(
                name="models.ollama_api",
                group="models",
                status=Status.FAILED,
                message="Cannot list Ollama models",
                detail=body[:200] if body else None,
                duration_ms=_u._timed(t),
            )
        ]

    try:
        data = json.loads(body)
        pulled = {m["name"].split(":")[0] for m in data.get("models", [])}
        pulled_full = {m["name"] for m in data.get("models", [])}
    except (json.JSONDecodeError, KeyError):
        return [
            CheckResult(
                name="models.ollama_api",
                group="models",
                status=Status.DEGRADED,
                message="Cannot parse model list",
                duration_ms=_u._timed(t),
            )
        ]

    results: list[CheckResult] = []
    for model in _c.EXPECTED_OLLAMA_MODELS:
        base = model.split(":")[0]
        if model in pulled_full or base in pulled:
            results.append(
                CheckResult(
                    name=f"models.{base}",
                    group="models",
                    status=Status.HEALTHY,
                    message="pulled",
                    duration_ms=_u._timed(t),
                )
            )
        else:
            results.append(
                CheckResult(
                    name=f"models.{base}",
                    group="models",
                    status=Status.DEGRADED,
                    message="not pulled",
                    remediation=f"docker exec ollama ollama pull {shlex.quote(model)}",
                    duration_ms=_u._timed(t),
                )
            )

    return results
