"""Check runner: parallel execution, result aggregation, quick_check."""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from collections.abc import Callable
from datetime import UTC, datetime

from opentelemetry import trace

# Ensure all check modules are imported (registers them into CHECK_REGISTRY)
from . import checks  # noqa: F401
from . import utils as _u
from .constants import LITELLM_BASE, OLLAMA_URL, QDRANT_URL
from .models import CheckResult, HealthReport, Status, build_group_result, worst_status
from .registry import CHECK_REGISTRY

_tracer = trace.get_tracer(__name__)
log = logging.getLogger("agents.health_monitor")


async def run_checks(
    groups: list[str] | None = None,
) -> HealthReport:
    """Run all (or selected) check groups and build a HealthReport."""
    with _tracer.start_as_current_span(
        "health_monitor.check",
        attributes={"agent.name": "health_monitor", "agent.repo": "hapax-council"},
    ):
        return await _run_checks_inner(groups)


async def _run_checks_inner(
    groups: list[str] | None = None,
) -> HealthReport:
    """Inner implementation of run_checks (wrapped by OTel span)."""
    start = time.monotonic()
    target_groups = groups or list(CHECK_REGISTRY.keys())

    all_fns: list[tuple[str, Callable]] = []
    for g in target_groups:
        for fn in CHECK_REGISTRY.get(g, []):
            all_fns.append((g, fn))

    async def _run_one(group: str, fn: Callable) -> tuple[str, list[CheckResult]]:
        try:
            results = await fn()
            return (group, results)
        except Exception as e:
            return (
                group,
                [
                    CheckResult(
                        name=f"{group}.error",
                        group=group,
                        status=Status.FAILED,
                        message=f"Check crashed: {e}",
                        duration_ms=0,
                    )
                ],
            )

    tasks = [_run_one(g, fn) for g, fn in all_fns]
    try:
        raw_results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), timeout=90.0
        )
    except TimeoutError:
        log.error("Health checks timed out after 90s")
        raw_results = [
            (
                "timeout",
                [
                    CheckResult(
                        name="checks.timeout",
                        group="timeout",
                        status=Status.FAILED,
                        message="Health checks timed out after 90s",
                        duration_ms=90000,
                    )
                ],
            )
        ]
    cleaned_results = []
    for r in raw_results:
        if isinstance(r, Exception):
            cleaned_results.append(
                (
                    "error",
                    [
                        CheckResult(
                            name="checks.exception",
                            group="error",
                            status=Status.FAILED,
                            message=f"Check exception: {r}",
                            duration_ms=0,
                        )
                    ],
                )
            )
        else:
            cleaned_results.append(r)
    raw_results = cleaned_results

    # Group results and annotate tiers
    from agents._service_tiers import ServiceTier, tier_for_check

    grouped: dict[str, list[CheckResult]] = {}
    for g, checks_list in raw_results:
        for c in checks_list:
            c.tier = int(tier_for_check(c.name, c.group))
        grouped.setdefault(g, []).extend(checks_list)

    group_results = []
    for g in target_groups:
        if g in grouped:
            group_results.append(build_group_result(g, grouped[g]))

    all_checks = [c for gr in group_results for c in gr.checks]
    all_statuses = [c.status for c in all_checks]
    h = sum(1 for s in all_statuses if s == Status.HEALTHY)
    d = sum(1 for s in all_statuses if s == Status.DEGRADED)
    f = sum(1 for s in all_statuses if s == Status.FAILED)

    failed_checks = [c for c in all_checks if c.status == Status.FAILED]
    if failed_checks and all(c.tier >= ServiceTier.OPTIONAL for c in failed_checks):
        overall = Status.DEGRADED
    else:
        overall = worst_status(*all_statuses) if all_statuses else Status.HEALTHY
    elapsed = _u._timed(start)

    summary = f"{h}/{len(all_checks)} healthy"
    if d:
        summary += f", {d} degraded"
    if f:
        summary += f", {f} failed"

    return HealthReport(
        timestamp=datetime.now(UTC).isoformat(),
        hostname=socket.gethostname(),
        overall_status=overall,
        groups=group_results,
        total_checks=len(all_checks),
        healthy_count=h,
        degraded_count=d,
        failed_count=f,
        duration_ms=elapsed,
        summary=summary,
    )


async def quick_check(
    required_services: list[str] | None = None,
) -> tuple[bool, list[CheckResult]]:
    """Fast pre-flight: HTTP endpoint checks only for named services."""
    service_urls = {
        "litellm": f"{LITELLM_BASE}/health/liveliness",
        "qdrant": f"{QDRANT_URL}/healthz",
        "ollama": f"{OLLAMA_URL}/api/tags",
        "langfuse": "http://localhost:3000/",
        "open-webui": "http://localhost:8080/health",
    }

    targets = required_services or ["litellm", "qdrant"]
    results: list[CheckResult] = []

    async def _check(name: str) -> CheckResult:
        url = service_urls.get(name)
        if not url:
            return CheckResult(
                name=f"preflight.{name}",
                group="preflight",
                status=Status.FAILED,
                message=f"Unknown service: {name}",
            )
        t = time.monotonic()
        code, body = await _u.http_get(url, timeout=3.0)
        if 200 <= code < 400:
            return CheckResult(
                name=f"preflight.{name}",
                group="preflight",
                status=Status.HEALTHY,
                message="reachable",
                duration_ms=_u._timed(t),
            )
        return CheckResult(
            name=f"preflight.{name}",
            group="preflight",
            status=Status.FAILED,
            message=f"unreachable (HTTP {code})",
            detail=body[:200] if body and code == 0 else None,
            duration_ms=_u._timed(t),
        )

    tasks = [_check(name) for name in targets]
    results = list(await asyncio.gather(*tasks))
    all_ok = all(r.status == Status.HEALTHY for r in results)
    return all_ok, results
