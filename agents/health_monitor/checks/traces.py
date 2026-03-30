"""Langfuse trace correlation checks."""

from __future__ import annotations

import time

from .. import utils as _u
from ..models import CheckResult, Status
from ..registry import check_group


@check_group("traces")
async def check_langfuse_error_spikes() -> list[CheckResult]:
    """G4: Correlate Langfuse error traces with service health."""
    t = time.monotonic()

    try:
        from agents._langfuse_client import LANGFUSE_PK, query_recent_errors
    except ImportError:
        return []

    if not LANGFUSE_PK:
        return [
            CheckResult(
                name="traces.langfuse_errors",
                group="traces",
                status=Status.HEALTHY,
                message="Langfuse credentials not configured (skipped)",
                duration_ms=_u._timed(t),
                tier=2,
            )
        ]

    services = ["logos", "briefing", "health", "drift", "scout", "voice"]
    results: list[CheckResult] = []

    for svc in services:
        try:
            errors = query_recent_errors(svc, hours=1)
        except Exception:
            continue

        if len(errors) > 5:
            status = Status.DEGRADED
            msg = f"{svc}: {len(errors)} error traces in last hour"
            top_msgs = "; ".join(e.get("message", "")[:60] for e in errors[:3] if e.get("message"))
            results.append(
                CheckResult(
                    name=f"traces.{svc}_errors",
                    group="traces",
                    status=status,
                    message=msg,
                    detail=top_msgs or None,
                    duration_ms=_u._timed(t),
                    tier=2,
                )
            )

    if not results:
        results.append(
            CheckResult(
                name="traces.langfuse_errors",
                group="traces",
                status=Status.HEALTHY,
                message="No error spikes in Langfuse traces",
                duration_ms=_u._timed(t),
                tier=2,
            )
        )

    return results
