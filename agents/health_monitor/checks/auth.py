"""Authentication validation checks (LiteLLM, Langfuse)."""

from __future__ import annotations

import asyncio
import json
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from .. import constants as _c
from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group
from .secrets import _get_secret


@check_group("auth")
async def check_litellm_auth() -> list[CheckResult]:
    """Validate LiteLLM API key actually works (not just file existence)."""
    t = time.monotonic()
    api_key, _ = _get_secret("LITELLM_API_KEY", "litellm/master-key")
    if not api_key or api_key == "changeme":
        return [
            CheckResult(
                name="auth.litellm",
                group="auth",
                status=Status.DEGRADED,
                message="LITELLM_API_KEY not available (env or pass)",
                detail="Set via: export LITELLM_API_KEY=$(pass show litellm/master-key)",
                duration_ms=_u._timed(t),
            )
        ]

    def _check() -> tuple[int, str]:
        req = Request(
            f"{_c.LITELLM_BASE}/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        try:
            with urlopen(req, timeout=5) as resp:
                return (resp.status, resp.read().decode("utf-8", errors="replace"))
        except URLError as e:
            return (0, str(e))
        except Exception as e:
            return (0, str(e))

    loop = asyncio.get_running_loop()
    code, body = await loop.run_in_executor(None, _check)

    if code == 200:
        try:
            model_count = len(json.loads(body).get("data", []))
            return [
                CheckResult(
                    name="auth.litellm",
                    group="auth",
                    status=Status.HEALTHY,
                    message=f"authenticated ({model_count} models)",
                    duration_ms=_u._timed(t),
                )
            ]
        except (json.JSONDecodeError, KeyError):
            pass
        return [
            CheckResult(
                name="auth.litellm",
                group="auth",
                status=Status.HEALTHY,
                message="authenticated",
                duration_ms=_u._timed(t),
            )
        ]

    return [
        CheckResult(
            name="auth.litellm",
            group="auth",
            status=Status.FAILED,
            message=f"auth failed (HTTP {code})",
            detail=body[:200] if body else None,
            remediation="pass show litellm/master-key",
            duration_ms=_u._timed(t),
        )
    ]


@check_group("auth")
async def check_langfuse_auth() -> list[CheckResult]:
    """Validate Langfuse credentials work."""
    t = time.monotonic()
    pk, _ = _get_secret("LANGFUSE_PUBLIC_KEY", "langfuse/public-key")
    sk, _ = _get_secret("LANGFUSE_SECRET_KEY", "langfuse/secret-key")

    if not pk or not sk:
        return [
            CheckResult(
                name="auth.langfuse",
                group="auth",
                status=Status.DEGRADED,
                message="Langfuse keys not available (env or pass)",
                detail='Load via: eval "$(<.envrc)" in ai-agents dir',
                duration_ms=_u._timed(t),
            )
        ]

    import base64

    def _check() -> tuple[int, str]:
        creds = base64.b64encode(f"{pk}:{sk}".encode()).decode()
        req = Request(
            "http://localhost:3000/api/public/health",
            headers={"Authorization": f"Basic {creds}"},
        )
        try:
            with urlopen(req, timeout=5) as resp:
                return (resp.status, resp.read().decode("utf-8", errors="replace"))
        except URLError as e:
            return (0, str(e))
        except Exception as e:
            return (0, str(e))

    loop = asyncio.get_running_loop()
    code, body = await loop.run_in_executor(None, _check)

    if code == 200:
        return [
            CheckResult(
                name="auth.langfuse",
                group="auth",
                status=Status.HEALTHY,
                message="authenticated",
                duration_ms=_u._timed(t),
            )
        ]

    return [
        CheckResult(
            name="auth.langfuse",
            group="auth",
            status=Status.DEGRADED,
            message=f"auth failed (HTTP {code})",
            detail=body[:200] if body else None,
            duration_ms=_u._timed(t),
        )
    ]
