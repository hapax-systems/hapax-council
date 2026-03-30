"""Qdrant collection health checks."""

from __future__ import annotations

import json
import time

from .. import constants as _c
from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group


@check_group("qdrant")
async def check_qdrant_health() -> list[CheckResult]:
    t = time.monotonic()
    code, body = await _u.http_get(f"{_c.QDRANT_URL}/healthz")
    if code == 200:
        return [
            CheckResult(
                name="qdrant.health",
                group="qdrant",
                status=Status.HEALTHY,
                message="Qdrant healthy",
                duration_ms=_u._timed(t),
            )
        ]
    return [
        CheckResult(
            name="qdrant.health",
            group="qdrant",
            status=Status.FAILED,
            message=f"Qdrant unreachable (HTTP {code})",
            detail=body[:200] if body else None,
            remediation=f"cd {_c.COMPOSE_FILE.parent} && docker compose up -d qdrant",
            duration_ms=_u._timed(t),
        )
    ]


@check_group("qdrant")
async def check_qdrant_collections() -> list[CheckResult]:
    t = time.monotonic()
    code, body = await _u.http_get(f"{_c.QDRANT_URL}/collections")
    if code != 200:
        return [
            CheckResult(
                name="qdrant.collections",
                group="qdrant",
                status=Status.FAILED,
                message="Cannot list collections",
                detail=body[:200] if body else None,
                duration_ms=_u._timed(t),
            )
        ]

    try:
        data = json.loads(body)
        existing = {c["name"] for c in data.get("result", {}).get("collections", [])}
    except (json.JSONDecodeError, KeyError):
        return [
            CheckResult(
                name="qdrant.collections",
                group="qdrant",
                status=Status.DEGRADED,
                message="Cannot parse collections response",
                duration_ms=_u._timed(t),
            )
        ]

    _EXPECTED_DIM = {c: 768 for c in _c.REQUIRED_QDRANT_COLLECTIONS}

    results: list[CheckResult] = []
    for coll in sorted(_c.REQUIRED_QDRANT_COLLECTIONS):
        if coll in existing:
            detail = None
            status = Status.HEALTHY
            message = "exists"
            c2, b2 = await _u.http_get(f"{_c.QDRANT_URL}/collections/{coll}")
            if c2 == 200:
                try:
                    cdata = json.loads(b2)
                    result_data = cdata.get("result", {})
                    points = result_data.get("points_count", "?")
                    vectors_config = (
                        result_data.get("config", {}).get("params", {}).get("vectors", {})
                    )
                    actual_dim = vectors_config.get("size")
                    expected_dim = _EXPECTED_DIM.get(coll, 768)
                    if actual_dim is not None and actual_dim != expected_dim:
                        status = Status.DEGRADED
                        message = f"dimension mismatch: {actual_dim} != {expected_dim}"
                    detail = f"{points} points, {actual_dim or '?'}d"
                except (json.JSONDecodeError, KeyError):
                    pass
            results.append(
                CheckResult(
                    name=f"qdrant.{coll}",
                    group="qdrant",
                    status=status,
                    message=message,
                    detail=detail,
                    duration_ms=_u._timed(t),
                )
            )
        else:
            results.append(
                CheckResult(
                    name=f"qdrant.{coll}",
                    group="qdrant",
                    status=Status.FAILED,
                    message="missing",
                    remediation=(
                        f"curl -X PUT http://localhost:6333/collections/{coll} "
                        f"-H 'Content-Type: application/json' "
                        f'-d \'{{"vectors": {{"size": 768, "distance": "Cosine"}}}}\''
                    ),
                    duration_ms=_u._timed(t),
                )
            )

    return results
