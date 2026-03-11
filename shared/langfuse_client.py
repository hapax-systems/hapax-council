"""shared/langfuse_client.py — Consolidated Langfuse API client.

Provides authenticated HTTP access to Langfuse's public API. Used by
profiler_sources (telemetry reader) and activity_analyzer (trace collector).
"""

from __future__ import annotations

import base64
import json
import logging
import os
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

log = logging.getLogger("shared.langfuse_client")

LANGFUSE_HOST: str = os.environ.get("LANGFUSE_HOST", "http://localhost:3000")
LANGFUSE_PK: str = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SK: str = os.environ.get("LANGFUSE_SECRET_KEY", "")


def langfuse_get(path: str, params: dict | None = None, *, timeout: int = 15) -> dict:
    """Make authenticated Langfuse API GET request.

    Args:
        path: API path (e.g. "/traces"). Prefixed with /api/public automatically.
        params: Query parameters (will be URL-encoded).
        timeout: Request timeout in seconds.

    Returns:
        Parsed JSON response, or empty dict on failure.
        Callers should check truthiness: empty dict means no data available.
    """
    if not LANGFUSE_PK or not LANGFUSE_SK:
        log.debug(
            "langfuse: no credentials configured — set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY"
        )
        return {}

    query = ""
    if params:
        query = "?" + urlencode(params)

    url = f"{LANGFUSE_HOST}/api/public{path}{query}"
    auth = base64.b64encode(f"{LANGFUSE_PK}:{LANGFUSE_SK}".encode()).decode()
    req = Request(url, headers={"Authorization": f"Basic {auth}"})

    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except URLError as exc:
        log.warning("langfuse_get %s failed (connection): %s", path, exc)
        return {}
    except json.JSONDecodeError as exc:
        log.warning("langfuse_get %s failed (invalid JSON response): %s", path, exc)
        return {}
    except OSError as exc:
        log.warning("langfuse_get %s failed (OS error): %s", path, exc)
        return {}


def is_available() -> bool:
    """Check if Langfuse is reachable and has traces."""
    if not LANGFUSE_PK:
        return False
    result = langfuse_get("/traces", {"limit": 1})
    return bool(result.get("data"))
