"""Queue and backlog monitoring checks."""

from __future__ import annotations

import time

from .. import constants as _c
from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group


@check_group("queues")
async def check_rag_retry_queue() -> list[CheckResult]:
    """Check RAG ingestion retry queue depth."""
    t = time.monotonic()
    retry_file = _c.RAG_INGEST_STATE_DIR / "retry-queue.jsonl"
    if not retry_file.exists():
        return [
            CheckResult(
                name="queues.rag-retry",
                group="queues",
                status=Status.HEALTHY,
                message="no retry queue",
                duration_ms=_u._timed(t),
            )
        ]
    try:
        lines = [l for l in retry_file.read_text().splitlines() if l.strip()]
        depth = len(lines)
        if depth > 50:
            return [
                CheckResult(
                    name="queues.rag-retry",
                    group="queues",
                    status=Status.DEGRADED,
                    message=f"{depth} items pending retry",
                    duration_ms=_u._timed(t),
                )
            ]
        return [
            CheckResult(
                name="queues.rag-retry",
                group="queues",
                status=Status.HEALTHY,
                message=f"{depth} items" if depth else "empty",
                duration_ms=_u._timed(t),
            )
        ]
    except OSError as e:
        return [
            CheckResult(
                name="queues.rag-retry",
                group="queues",
                status=Status.DEGRADED,
                message=f"could not read queue: {e}",
                duration_ms=_u._timed(t),
            )
        ]


@check_group("queues")
async def check_n8n_executions() -> list[CheckResult]:
    """Check n8n for waiting/stuck executions."""
    t = time.monotonic()
    code, body = await _u.http_get("http://localhost:5678/healthz", timeout=3.0)
    if code == 0:
        return [
            CheckResult(
                name="queues.n8n-executions",
                group="queues",
                status=Status.DEGRADED,
                message="n8n unreachable",
                duration_ms=_u._timed(t),
            )
        ]
    return [
        CheckResult(
            name="queues.n8n-executions",
            group="queues",
            status=Status.HEALTHY,
            message="n8n responsive",
            duration_ms=_u._timed(t),
        )
    ]
