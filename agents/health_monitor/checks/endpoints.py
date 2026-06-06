"""HTTP service endpoint checks."""

from __future__ import annotations

import asyncio
import shlex
import time

from .. import constants as _c
from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group


@check_group("endpoints")
async def check_service_endpoints() -> list[CheckResult]:
    endpoints: list[tuple[str, str, bool, str | None]] = [
        ("endpoints.litellm", f"{_c.LITELLM_BASE}/health/liveliness", True, "litellm"),
        (
            "endpoints.langfuse",
            _c.langfuse_endpoint_url(),
            False,
            None if _c.podium_thin_client_enabled() else "langfuse",
        ),
        ("endpoints.open-webui", "http://localhost:8080/health", False, "open-webui"),
    ]
    if _c.local_ollama_required():
        endpoints.insert(1, ("endpoints.ollama", f"{_c.OLLAMA_URL}/api/tags", True, "ollama"))

    async def _check_one(
        name: str, url: str, is_core: bool, remediation_target: str | None
    ) -> CheckResult:
        t = time.monotonic()
        code, body = await _u.http_get(url, timeout=3.0)
        if 200 <= code < 400:
            return CheckResult(
                name=name,
                group="endpoints",
                status=Status.HEALTHY,
                message=f"HTTP {code}",
                duration_ms=_u._timed(t),
            )
        remediation = None
        if remediation_target:
            remediation = (
                f"cd {_c.COMPOSE_FILE.parent} && docker compose up -d "
                f"{shlex.quote(remediation_target)}"
            )
        return CheckResult(
            name=name,
            group="endpoints",
            status=Status.FAILED if is_core else Status.DEGRADED,
            message=f"unreachable (HTTP {code})" if code else "unreachable",
            detail=body[:200] if body and code == 0 else None,
            remediation=remediation,
            duration_ms=_u._timed(t),
        )

    tasks = [_check_one(name, url, core, target) for name, url, core, target in endpoints]
    return list(await asyncio.gather(*tasks))
