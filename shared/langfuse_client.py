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


def query_zero_result_spans(hours: int = 24) -> list[dict]:
    """G3: Find RAG spans with zero results in the last N hours.

    Returns list of dicts with keys: collection, query (truncated), trace_id, timestamp.
    """
    if not LANGFUSE_PK:
        return []

    from datetime import UTC, datetime, timedelta

    from_time = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    zero_results: list[dict] = []
    page = 1

    while page <= 10:
        resp = langfuse_get(
            "/observations",
            {"fromStartTime": from_time, "type": "SPAN", "limit": 100, "page": page},
            timeout=15,
        )
        if not resp:
            break

        for obs in resp.get("data", []):
            name = obs.get("name", "")
            if "rag" not in name.lower() and "search" not in name.lower():
                continue
            metadata = obs.get("metadata") or {}
            output = obs.get("output") or {}
            # Check for rag.result_count=0 in metadata or output
            result_count = (
                metadata.get("rag.result_count")
                or metadata.get("result_count")
                or output.get("result_count")
            )
            if result_count is not None and int(result_count) == 0:
                zero_results.append(
                    {
                        "collection": metadata.get(
                            "rag.collection", metadata.get("collection", "")
                        ),
                        "query": (metadata.get("rag.query", metadata.get("query", "")))[:100],
                        "trace_id": obs.get("traceId", ""),
                        "timestamp": obs.get("startTime", ""),
                    }
                )

        total_items = resp.get("meta", {}).get("totalItems", 0)
        if page * 100 >= total_items:
            break
        page += 1

    return zero_results


def query_recent_errors(service: str, hours: int = 1) -> list[dict]:
    """G4: Find error-level traces for a service in the last N hours.

    Returns list of dicts with keys: trace_id, name, message, timestamp.
    """
    if not LANGFUSE_PK:
        return []

    from datetime import UTC, datetime, timedelta

    from_time = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    errors: list[dict] = []
    page = 1

    while page <= 5:
        resp = langfuse_get(
            "/observations",
            {
                "fromStartTime": from_time,
                "type": "SPAN",
                "limit": 100,
                "page": page,
            },
            timeout=10,
        )
        if not resp:
            break

        for obs in resp.get("data", []):
            if obs.get("level") != "ERROR":
                continue
            name = obs.get("name", "")
            metadata = obs.get("metadata") or {}
            obs_service = metadata.get("service", metadata.get("agent_name", name))
            if service.lower() not in obs_service.lower():
                continue
            errors.append(
                {
                    "trace_id": obs.get("traceId", ""),
                    "name": name,
                    "message": (obs.get("statusMessage") or "")[:200],
                    "timestamp": obs.get("startTime", ""),
                }
            )

        total_items = resp.get("meta", {}).get("totalItems", 0)
        if page * 100 >= total_items:
            break
        page += 1

    return errors
