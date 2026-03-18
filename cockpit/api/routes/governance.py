"""Governance observability routes — metrics for the principality.

GET /governance/heartbeat — single 0-1 score + breakdown
GET /governance/coverage — consent coverage index
GET /governance/blast-radius/{person_id} — revocation impact
GET /governance/authority — agent delegation metrics
GET /governance/lifecycle — consent timeline metrics
GET /governance/carriers — cross-domain carrier flow
"""

from __future__ import annotations

import dataclasses

from fastapi import APIRouter

router = APIRouter(prefix="/api/governance", tags=["governance"])


@router.get("/heartbeat")
async def governance_heartbeat() -> dict:
    """The single governance health score.

    Green (>=0.8): healthy. Yellow (0.5-0.8): attention needed. Red (<0.5): failures.
    """
    from cockpit.data.governance import collect_governance_heartbeat

    hb = collect_governance_heartbeat()
    return {
        "score": hb.score,
        "label": hb.label,
        "components": hb.components,
        "issues": hb.issues,
        "timestamp": hb.timestamp,
    }


@router.get("/coverage")
async def governance_coverage() -> dict:
    """Consent coverage index — per-principal, per-scope."""
    from cockpit.data.governance import collect_consent_coverage

    cov = collect_consent_coverage()
    return dataclasses.asdict(cov)


@router.get("/blast-radius/{person_id}")
async def blast_radius(person_id: str) -> dict:
    """Revocation impact: what would be purged if this person revokes?"""
    from cockpit.data.governance import collect_revocation_blast_radius

    blast = collect_revocation_blast_radius(person_id)
    return dataclasses.asdict(blast)


@router.get("/authority")
async def authority_utilization() -> dict:
    """Per-agent authority delegation metrics."""
    from cockpit.data.governance import collect_authority_utilization

    agents = collect_authority_utilization()
    return {
        "agent_count": len(agents),
        "agents": [dataclasses.asdict(a) for a in agents],
    }


@router.get("/lifecycle")
async def consent_lifecycle() -> dict:
    """Consent gate temporal metrics."""
    from cockpit.data.governance import collect_consent_lifecycle

    lc = collect_consent_lifecycle()
    return dataclasses.asdict(lc)


@router.get("/carriers")
async def carrier_flow() -> dict:
    """Cross-domain carrier fact metrics."""
    from cockpit.data.governance import collect_carrier_flow

    cf = collect_carrier_flow()
    return dataclasses.asdict(cf)
