"""Consent management routes — revocation cascade (DD-8, DD-23).

POST /consent/revoke/{person_id} triggers revocation of all consent
contracts for a person and cascades purge through all registered
subsystems (carrier registry, etc.).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from shared.revocation_wiring import get_revocation_propagator

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/consent", tags=["consent"])


@router.post("/revoke/{person_id}")
async def revoke_consent(person_id: str) -> dict:
    """Revoke all consent contracts for a person and cascade purge."""
    prop = get_revocation_propagator()
    report = prop.revoke(person_id)

    _log.info(
        "Revocation for %s: revoked=%s, purged=%d",
        person_id,
        report.contract_revoked,
        report.total_purged,
    )

    return {
        "person_id": report.person_id,
        "contract_revoked": report.contract_revoked,
        "contract_id": report.contract_id,
        "total_purged": report.total_purged,
        "purge_results": [
            {
                "subsystem": r.subsystem,
                "items_purged": r.items_purged,
                "details": r.details,
            }
            for r in report.purge_results
        ],
    }
