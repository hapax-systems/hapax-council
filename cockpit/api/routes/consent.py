"""Consent management routes — revocation cascade and trace (DD-8, DD-11, DD-23).

POST /consent/revoke/{person_id} — triggers revocation cascade
GET /consent/trace — trace consent provenance for a file or Qdrant source
GET /consent/contracts — list active consent contracts
GET /consent/coverage — summary of consent coverage across stored data
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, Query

from shared.governance.revocation_wiring import get_revocation_propagator

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


@router.get("/trace")
async def trace_consent(source: str = Query(..., description="File path or source identifier")) -> dict:
    """Trace consent provenance for a file.

    Shows: consent label, provenance contracts, flow constraints,
    and revocation impact. This is the IFC claim made visible.
    """
    source_path = Path(unquote(source))

    # Extract consent metadata from the file
    label_data = None
    provenance_data: list[str] = []
    body_preview = ""

    if source_path.exists():
        try:
            from shared.frontmatter import (
                extract_consent_label,
                extract_provenance,
                parse_frontmatter,
            )

            fm, body = parse_frontmatter(source_path)
            consent_label = extract_consent_label(fm)
            provenance = extract_provenance(fm)
            provenance_data = sorted(provenance)
            body_preview = body[:200] if body else ""

            if consent_label is not None:
                label_data = [
                    {"owner": owner, "readers": sorted(readers)}
                    for owner, readers in consent_label.policies
                ]
        except Exception as e:
            _log.debug("Failed to parse %s: %s", source_path, e)

    # Look up contracts from provenance
    contracts = []
    try:
        from shared.governance.consent import load_contracts

        registry = load_contracts()
        for contract_id in provenance_data:
            contract = registry._contracts.get(contract_id)
            if contract:
                contracts.append(
                    {
                        "id": contract.id,
                        "parties": list(contract.parties),
                        "scope": sorted(contract.scope),
                        "active": contract.active,
                        "created_at": contract.created_at,
                        "revoked_at": contract.revoked_at,
                    }
                )
    except Exception:
        pass

    # Information flow analysis

    has_label = label_data is not None
    is_public = not has_label or label_data == []
    flow_analysis = {
        "has_consent_label": has_label,
        "is_public": is_public,
        "can_flow_to_public": is_public,
        "label_policy_count": len(label_data) if label_data else 0,
    }

    if not is_public and label_data:
        flow_analysis["label_policies"] = label_data
        flow_analysis["note"] = (
            "This data has consent restrictions. It can only flow to contexts "
            "whose consent label is a superset of these policies."
        )

    # Revocation impact (how many Qdrant points share this provenance)
    revocation_impact = None
    if provenance_data:
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            from shared.config import get_qdrant

            client = get_qdrant()
            total = 0
            for contract_id in provenance_data:
                result = client.count(
                    collection_name="documents",
                    count_filter=Filter(
                        must=[
                            FieldCondition(
                                key="provenance",
                                match=MatchValue(value=contract_id),
                            )
                        ]
                    ),
                )
                total += result.count
            revocation_impact = {
                "contracts": provenance_data,
                "qdrant_points_affected": total,
                "note": f"Revoking these contracts would purge {total} Qdrant points",
            }
        except Exception:
            pass

    return {
        "source": str(source_path),
        "exists": source_path.exists(),
        "body_preview": body_preview,
        "consent_label": label_data,
        "provenance": provenance_data,
        "contracts": contracts,
        "information_flow": flow_analysis,
        "revocation_impact": revocation_impact,
    }


@router.get("/contracts")
async def list_contracts() -> dict:
    """List all consent contracts (active and revoked)."""
    try:
        from shared.governance.consent import load_contracts

        registry = load_contracts()
        contracts = []
        for _cid, contract in registry._contracts.items():
            contracts.append(
                {
                    "id": contract.id,
                    "parties": list(contract.parties),
                    "scope": sorted(contract.scope),
                    "active": contract.active,
                    "created_at": contract.created_at,
                    "revoked_at": contract.revoked_at,
                }
            )
        return {"contracts": contracts, "active_count": sum(1 for c in contracts if c["active"])}
    except Exception as e:
        return {"contracts": [], "active_count": 0, "error": str(e)}


@router.get("/coverage")
async def consent_coverage() -> dict:
    """Summary of consent coverage across stored data.

    Shows how much data has consent labels vs public/unlabeled.
    This makes the IFC claim visible: you can see what's protected
    and what isn't.
    """
    try:
        from qdrant_client.models import FieldCondition, Filter, MatchExcept

        from shared.config import get_qdrant

        client = get_qdrant()

        total = client.count(collection_name="documents").count

        # Count points with consent_label field
        labeled = client.count(
            collection_name="documents",
            count_filter=Filter(
                must=[FieldCondition(key="consent_label", match=MatchExcept(except_=[]))]
            ),
        ).count

        # Count points with provenance field
        with_provenance = client.count(
            collection_name="documents",
            count_filter=Filter(
                must=[FieldCondition(key="provenance", match=MatchExcept(except_=[]))]
            ),
        ).count

        return {
            "total_points": total,
            "with_consent_label": labeled,
            "with_provenance": with_provenance,
            "unlabeled": total - labeled,
            "coverage_pct": round(labeled / total * 100, 1) if total > 0 else 0,
            "note": (
                "Unlabeled data is treated as public (ConsentLabel.bottom()). "
                "To protect data about non-operator persons, add consent_label "
                "and provenance to the source file's YAML frontmatter."
            ),
        }
    except Exception as e:
        return {"error": str(e)}
