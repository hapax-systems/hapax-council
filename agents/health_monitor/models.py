"""Pydantic models and enums for health monitoring."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class Status(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"


class CheckResult(BaseModel):
    name: str
    group: str
    status: Status
    message: str
    detail: str | None = None
    remediation: str | None = None
    duration_ms: int = 0
    tier: int = 1  # ServiceTier value (0=critical, 1=important, 2=observability, 3=optional)


class GroupResult(BaseModel):
    group: str
    status: Status
    checks: list[CheckResult]
    healthy_count: int = 0
    degraded_count: int = 0
    failed_count: int = 0


class HealthReport(BaseModel):
    timestamp: str
    hostname: str
    overall_status: Status
    groups: list[GroupResult]
    total_checks: int = 0
    healthy_count: int = 0
    degraded_count: int = 0
    failed_count: int = 0
    duration_ms: int = 0
    summary: str = ""


def worst_status(*statuses: Status) -> Status:
    """Return the most severe status from the given statuses."""
    if Status.FAILED in statuses:
        return Status.FAILED
    if Status.DEGRADED in statuses:
        return Status.DEGRADED
    return Status.HEALTHY


def build_group_result(group: str, checks: list[CheckResult]) -> GroupResult:
    statuses = [c.status for c in checks]
    h = sum(1 for s in statuses if s == Status.HEALTHY)
    d = sum(1 for s in statuses if s == Status.DEGRADED)
    f = sum(1 for s in statuses if s == Status.FAILED)
    return GroupResult(
        group=group,
        status=worst_status(*statuses) if statuses else Status.HEALTHY,
        checks=checks,
        healthy_count=h,
        degraded_count=d,
        failed_count=f,
    )
