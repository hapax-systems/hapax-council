"""Consent and governance routes (DD-8, DD-11, DD-23).

POST /consent/create — create a consent contract (runtime, from channel)
POST /consent/revoke/{person_id} — triggers revocation cascade
GET /consent/trace — trace consent provenance for a file
GET /consent/contracts — list active consent contracts
GET /consent/coverage — consent label coverage across Qdrant
GET /consent/precedents — axiom precedent timeline
GET /consent/channels — available consent channels for a guest
GET /consent/overhead — governance overhead measurement
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from shared.governance.revocation_wiring import get_revocation_propagator

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/consent", tags=["consent"])


class ConsentCreateRequest(BaseModel):
    """Request to create a consent contract via a channel."""

    person_id: str = Field(description="Guest identifier")
    scope: list[str] = Field(description="Data categories consented to")
    channel_id: str = Field(default="operator-mediated", description="Channel used")
    direction: str = Field(default="one_way")
    visibility_mechanism: str = Field(default="on_request")


@router.post("/create")
async def create_consent(req: ConsentCreateRequest) -> dict:
    """Create a consent contract at runtime.

    Called when a guest grants consent via any channel. Writes contract
    to axioms/contracts/ and registers in memory.
    """
    from shared.governance.consent import load_contracts

    registry = load_contracts()
    contract = registry.create_contract(
        person_id=req.person_id,
        scope=frozenset(req.scope),
        direction=req.direction,
        visibility_mechanism=req.visibility_mechanism,
    )

    _log.info(
        "Consent created: %s for %s via %s (scope: %s)",
        contract.id,
        req.person_id,
        req.channel_id,
        sorted(req.scope),
    )

    return {
        "contract_id": contract.id,
        "person_id": req.person_id,
        "scope": sorted(req.scope),
        "channel_used": req.channel_id,
        "active": contract.active,
        "created_at": contract.created_at,
    }


@router.get("/channels")
async def consent_channels(
    is_child: bool = False,
    guardian_present: bool = False,
    incapabilities: str = "",
) -> dict:
    """Available consent channels for a guest, friction-sorted."""
    from shared.governance.consent_channels import GuestContext, build_channel_menu

    incap_set = frozenset(i.strip() for i in incapabilities.split(",") if i.strip())
    guest = GuestContext(
        known_incapabilities=incap_set,
        is_child=is_child,
        guardian_present=guardian_present,
    )
    menu = build_channel_menu(guest=guest)

    return {
        "sufficient": menu.sufficient,
        "insufficiency_reason": menu.insufficiency_reason,
        "channels": [
            {
                "id": o.channel.id,
                "name": o.channel.name,
                "available": o.available,
                "reason": o.reason,
                "friction_total": round(o.friction.total, 2),
                "scope": sorted(o.channel.scope),
                "description": o.channel.description,
            }
            for o in menu.offers
        ],
    }


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
async def trace_consent(
    source: str = Query(..., description="File path or source identifier"),
) -> dict:
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
            contract = registry.get(contract_id)
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
        _log.warning("Failed to load consent contracts", exc_info=True)

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
            _log.warning("Qdrant point count failed", exc_info=True)

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
        for contract in registry:
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
        from qdrant_client.models import Filter, IsNullCondition

        from shared.config import get_qdrant

        client = get_qdrant()

        total = client.count(collection_name="documents").count

        # Count points where consent_label field exists (is not null)
        labeled = client.count(
            collection_name="documents",
            count_filter=Filter(must_not=[IsNullCondition(is_null={"key": "consent_label"})]),
        ).count

        # Count points where provenance field exists
        with_provenance = client.count(
            collection_name="documents",
            count_filter=Filter(must_not=[IsNullCondition(is_null={"key": "provenance"})]),
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


@router.get("/precedents")
async def precedent_timeline(axiom_id: str | None = None) -> dict:
    """Axiom precedent timeline — accumulated case law.

    Shows governance decisions chronologically, proving that the
    constitutional system evolves through precedent without changing
    the axioms themselves.
    """
    try:
        from shared.config import get_qdrant

        client = get_qdrant()

        # Scroll all precedents (small collection, ~10-50 points)
        results = client.scroll(
            collection_name="axiom-precedents",
            limit=100,
            with_payload=True,
            with_vectors=False,
        )
        points = results[0] if results else []

        precedents = []
        for p in points:
            payload = p.payload or {}
            # Filter by axiom if requested
            if axiom_id and payload.get("axiom_id") != axiom_id:
                continue
            precedents.append(
                {
                    "precedent_id": payload.get("precedent_id", ""),
                    "axiom_id": payload.get("axiom_id", ""),
                    "situation": payload.get("situation", ""),
                    "decision": payload.get("decision", ""),
                    "reasoning": (payload.get("reasoning") or "")[:500],
                    "timestamp": payload.get("timestamp", ""),
                    "cited_by": payload.get("cited_by", []),
                }
            )

        # Sort by precedent_id (contains date: PRE-YYYYMMDD-hash)
        precedents.sort(key=lambda p: p["precedent_id"])

        # Group by axiom
        by_axiom: dict[str, int] = {}
        for p in precedents:
            aid = p["axiom_id"]
            by_axiom[aid] = by_axiom.get(aid, 0) + 1

        return {
            "total_precedents": len(precedents),
            "by_axiom": by_axiom,
            "precedents": precedents,
            "filter": axiom_id,
        }
    except Exception as e:
        return {"error": str(e), "total_precedents": 0, "precedents": []}


@router.get("/overhead")
async def governance_overhead(days: int = 14) -> dict:
    """Governance overhead dashboard — alignment tax measurement.

    Shows the cost of governance across three dimensions:
    1. Token cost: governance LLM calls vs total
    2. SDLC pipeline: axiom-gate duration vs total
    3. Label operations: microbenchmark latencies
    """
    import dataclasses

    from agents.alignment_tax_meter import measure_alignment_tax

    snapshot = measure_alignment_tax(lookback_days=days)
    return dataclasses.asdict(snapshot)
