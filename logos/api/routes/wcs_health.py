"""World Capability Surface health dashboard API.

Exposes WCS health envelope and per-surface health records so workers,
director snapshots, and operator surfaces can read blocked, stale,
degraded, and claimable states without scraping logs.

CC-task: world-surface-health-api-dashboard
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from shared.world_surface_health import (
    HealthStatus,
    WorldSurfaceHealthEnvelope,
    WorldSurfaceHealthRecord,
    load_world_surface_health_fixtures,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["wcs-health"])


class HealthRowSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    surface_id: str
    surface_family: str
    status: str
    freshness_state: str
    freshness_age_s: int | None
    public_private_posture: str
    public_claim_allowed: bool
    monetization_allowed: bool
    claimable_health: bool
    blocking_reasons: list[str]
    warnings: list[str]
    fallback_available: bool
    owner: str


class DashboardResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    envelope_id: str
    checked_at: str
    overall_status: str
    public_live_allowed: bool
    public_archive_allowed: bool
    public_monetization_allowed: bool
    blocked_count: int
    stale_count: int
    unknown_count: int
    unsafe_count: int
    false_grounding_risk_count: int
    total_surfaces: int
    rows: list[HealthRowSummary]
    next_required_actions: list[str]


def _record_to_row(record: WorldSurfaceHealthRecord) -> HealthRowSummary:
    return HealthRowSummary(
        surface_id=record.surface_id,
        surface_family=record.surface_family.value,
        status=record.status.value,
        freshness_state=record.freshness.state.value,
        freshness_age_s=record.freshness.observed_age_s,
        public_private_posture=record.public_private_posture.value,
        public_claim_allowed=record.public_claim_allowed,
        monetization_allowed=record.monetization_allowed,
        claimable_health=record.claimable_health,
        blocking_reasons=list(record.blocking_reasons),
        warnings=list(record.warnings),
        fallback_available=record.fallback.mode.value != "none",
        owner=record.owner,
    )


def _envelope_to_dashboard(envelope: WorldSurfaceHealthEnvelope) -> DashboardResponse:
    return DashboardResponse(
        envelope_id=envelope.envelope_id,
        checked_at=envelope.checked_at,
        overall_status=envelope.overall_status.value,
        public_live_allowed=envelope.public_live_allowed,
        public_archive_allowed=envelope.public_archive_allowed,
        public_monetization_allowed=envelope.public_monetization_allowed,
        blocked_count=envelope.blocked_surface_count,
        stale_count=envelope.stale_surface_count,
        unknown_count=envelope.unknown_surface_count,
        unsafe_count=envelope.unsafe_surface_count,
        false_grounding_risk_count=envelope.false_grounding_risk_count,
        total_surfaces=len(envelope.records),
        rows=[_record_to_row(r) for r in envelope.records],
        next_required_actions=list(envelope.next_required_actions),
    )


@router.get("/wcs/health")
async def get_wcs_health() -> DashboardResponse:
    """Full WCS health dashboard — all surfaces with status and blockers."""
    fixtures = load_world_surface_health_fixtures()
    return _envelope_to_dashboard(fixtures.envelopes[0])


@router.get("/wcs/health/surface/{surface_id}")
async def get_wcs_surface_health(surface_id: str) -> HealthRowSummary | dict:
    """Single surface health record."""
    fixtures = load_world_surface_health_fixtures()
    for record in fixtures.envelopes[0].records:
        if record.surface_id == surface_id:
            return _record_to_row(record)
    return {"error": f"surface {surface_id!r} not found", "status": 404}


@router.get("/wcs/health/blocked")
async def get_wcs_blocked_surfaces() -> list[HealthRowSummary]:
    """Surfaces currently blocked, degraded, stale, or unsafe."""
    fixtures = load_world_surface_health_fixtures()
    non_healthy = {
        HealthStatus.BLOCKED,
        HealthStatus.DEGRADED,
        HealthStatus.STALE,
        HealthStatus.UNSAFE,
        HealthStatus.MISSING,
        HealthStatus.UNKNOWN,
    }
    return [_record_to_row(r) for r in fixtures.envelopes[0].records if r.status in non_healthy]


@router.get("/wcs/health/claimable")
async def get_wcs_claimable_surfaces() -> list[HealthRowSummary]:
    """Surfaces with claimable health — ready for public/monetization gates."""
    fixtures = load_world_surface_health_fixtures()
    return [_record_to_row(r) for r in fixtures.envelopes[0].records if r.claimable_health]
