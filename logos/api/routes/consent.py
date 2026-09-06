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

import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from pathlib import Path
from threading import Lock
from urllib.parse import unquote

from fastapi import APIRouter, FastAPI, Query, Request, Response
from pydantic import BaseModel, Field
from werkzeug.security import safe_join

from logos._revocation_wiring import get_revocation_propagator
from logos.api.routes._config import HAPAX_HOME
from shared.governance.consent import (
    ConsentRegistry,
    estate_identity_operation,
    resolve_contract_id,
    resolve_principal_id,
)
from shared.governance.revocation import RevocationPropagator, RevocationReport
from shared.notify import send_notification
from shared.stream_archive import archive_root

_log = logging.getLogger(__name__)

# Existing archive-purge audit destination (scripts/archive-purge.py).
_PURGE_AUDIT_PATH = archive_root() / "purge.log"
_revocation_lock = Lock()


def _purge_retry_instruction(person_id: str) -> str:
    return (
        f"POST /api/consent/retry/{person_id} is valid for the current process only. "
        f"After restart, reconcile outstanding contracts from the durable purge_pending "
        f"record in {_PURGE_AUDIT_PATH}; no purge is automatically re-run."
    )


def _warn_pending_purges() -> None:
    try:
        # Startup reads audit residue only; it must not initialize the runtime
        # singleton or bind it to a snapshot of grants from process startup.
        pending = RevocationPropagator(ConsentRegistry(_contracts_dir=None)).pending_purges(
            _PURGE_AUDIT_PATH
        )
    except Exception as exc:
        cause = type(exc).__name__
        cause = cause if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", cause) else "unavailable"
        _log.warning(
            "purge_audit_unreadable: cause_class=%s; "
            "inspect the durable purge audit and restore custody before retrying",
            cause,
        )
        return
    for person_id in sorted(pending):
        _log.warning("purge_pending: %s; %s", person_id, _purge_retry_instruction(person_id))


@asynccontextmanager
async def _consent_lifespan(app: FastAPI):
    await asyncio.to_thread(_warn_pending_purges)
    yield


router = APIRouter(prefix="/api/consent", tags=["consent"], lifespan=_consent_lifespan)

_TRACE_ALLOWED_BASES = (
    Path(__file__).resolve().parents[3],
    HAPAX_HOME / "Documents" / "Personal",
    HAPAX_HOME / "documents",
    HAPAX_HOME / "projects" / "hapax-council",
)


def _resolve_trace_source(source: str) -> Path | None:
    decoded = unquote(source).strip()
    if not decoded or "\x00" in decoded:
        return None
    candidate = os.path.expanduser(decoded)
    if not os.path.isabs(candidate):
        return None
    for base in _TRACE_ALLOWED_BASES:
        try:
            resolved_base = base.resolve(strict=False)
        except OSError:
            continue
        rel = os.path.relpath(candidate, resolved_base)
        if rel == os.pardir or rel.startswith(f"{os.pardir}{os.sep}"):
            continue
        joined = safe_join(str(resolved_base), rel)
        if joined is not None:
            return Path(joined)
    return None


class ConsentCreateRequest(BaseModel):
    """Request to create a consent contract via a channel."""

    person_id: str = Field(description="Guest identifier")
    scope: list[str] = Field(description="Data categories consented to")
    channel_id: str = Field(default="operator-mediated", description="Channel used")
    direction: str = Field(default="one_way")
    visibility_mechanism: str = Field(default="on_request")


@router.post("/create")
async def create_consent(req: ConsentCreateRequest) -> dict:
    return await asyncio.to_thread(_create_consent, req)


@estate_identity_operation()
def _create_consent(req: ConsentCreateRequest) -> dict:
    """Create a consent contract at runtime.

    Called when a guest grants consent via any channel. Writes contract
    to axioms/contracts/ and registers in memory.
    """
    from logos._governance import load_contracts

    registry = load_contracts()
    contract = registry.create_contract(
        person_id=resolve_principal_id(req.person_id),
        scope=frozenset(req.scope),
        direction=req.direction,
        visibility_mechanism=req.visibility_mechanism,
    )

    _log.info(
        "Consent created: %s for %s via %s (scope: %s)",
        contract.id,
        contract.parties[1],
        req.channel_id,
        sorted(req.scope),
    )

    return {
        "contract_id": contract.id,
        "person_id": contract.parties[1],
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
    from logos._consent_channels import GuestContext, build_channel_menu

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


def _revocation_response(report: RevocationReport, response: Response) -> dict:
    payload = asdict(report)
    payload["total_purged"] = report.total_purged
    payload["failures"] = [cause for result in report.purge_results for cause in result.failures]
    if report.retry_contract_ids or payload["failures"] or report.audit_failures:
        response.status_code = 503
        payload["durable_record"] = {"event": "purge_pending", "audit": str(_PURGE_AUDIT_PATH)}
        payload["retry_instruction"] = _purge_retry_instruction(report.person_id)
        if report.audit_failures:
            if report.purge_complete:
                payload["durable_record"]["event"] = "purge_complete"
            payload["durable_record"]["written"] = False
            payload["retry_instruction"] = (
                "Purge audit write failed; retain this response and repair the audit destination. "
                + payload["retry_instruction"]
            )
    return payload


def _run_revocation(
    person_id: str, app: FastAPI, *, retry: bool = False
) -> RevocationReport | None:
    with _revocation_lock, estate_identity_operation():
        # Reports belong to this app instance; the audit survives process replacement.
        if not hasattr(app.state, "pending_consent_revocations"):
            app.state.pending_consent_revocations = {}
        pending_revocations = app.state.pending_consent_revocations
        if not hasattr(app.state, "pending_consent_audit_completions"):
            app.state.pending_consent_audit_completions = {}
        audit_completions = app.state.pending_consent_audit_completions
        person_id = resolve_principal_id(person_id)
        prop = get_revocation_propagator()
        prop.refresh_contracts()
        pending = pending_revocations.get(person_id)
        if retry:
            if pending is None:
                return None
            report = prop.retry_purge(pending)
        else:
            report = prop.revoke(person_id)
            if pending is not None:
                # A repeated revoke must keep failures AND revoke any newly granted consent.
                report = RevocationReport(
                    contract_id=",".join(
                        dict.fromkeys(
                            filter(
                                None, (pending.contract_id + "," + report.contract_id).split(",")
                            )
                        )
                    ),
                    person_id=person_id,
                    contract_revoked=pending.contract_revoked or report.contract_revoked,
                    purge_results=pending.purge_results + report.purge_results,
                    retry_contract_ids=tuple(
                        dict.fromkeys(pending.retry_contract_ids + report.retry_contract_ids)
                    ),
                    retry_revocation_ids=tuple(
                        cid
                        for cid in dict.fromkeys(
                            pending.retry_revocation_ids + report.retry_revocation_ids
                        )
                        if cid not in report.contract_id.split(",")
                    ),
                    prior_purge_results=pending.prior_purge_results + report.prior_purge_results,
                )
        # Retire every obligation completed by this stage, including stages
        # that still leave other contracts pending. Preserve failed audit writes
        # in process so a subsequent retry can reconcile without repeating purges.
        completed = set(audit_completions.get(person_id, ()))
        if pending is not None:
            completed.update(set(pending.retry_contract_ids) - set(report.retry_contract_ids))
        audit_failures = []
        if completed:
            try:
                prop.record_purge_complete(person_id, tuple(sorted(completed)), _PURGE_AUDIT_PATH)
                audit_completions.pop(person_id, None)
            except Exception:
                audit_completions[person_id] = tuple(sorted(completed))
                audit_failures.append("purge_complete_audit_unwritten")
        if report.retry_contract_ids:
            try:
                prop.record_purge_pending(report, _PURGE_AUDIT_PATH)
            except Exception:
                audit_failures.append("purge_pending_audit_unwritten")
        report = replace(report, audit_failures=tuple(audit_failures))
        if report.retry_contract_ids or audit_failures:
            pending_revocations[person_id] = report
            if audit_failures:
                _log.warning(
                    "purge_audit_unwritten: retain the response and repair the audit destination; "
                    "current-process retry remains available"
                )
            try:
                send_notification(
                    "Consent purge pending"
                    if report.retry_contract_ids
                    else "Consent purge audit pending",
                    f"purge_pending: {person_id}; contracts={','.join(report.retry_contract_ids)}. "
                    + (
                        "Audit write failed; retain the response and repair the audit destination. "
                        if audit_failures
                        else ""
                    )
                    + _purge_retry_instruction(person_id),
                    priority="high",
                    tags=["warning"],
                )
            except Exception:
                _log.warning("purge_pending_notification_failed: inspect the durable purge audit")
        else:
            pending_revocations.pop(person_id, None)
        _log.info(
            "Revocation: revoked=%s, purged=%d, purge_complete=%s",
            report.contract_revoked,
            report.total_purged,
            report.purge_complete,
        )
        return report


@router.post("/revoke/{person_id}")
async def revoke_consent(person_id: str, response: Response, request: Request) -> dict:
    """Revoke consent and retain an incomplete purge for an explicit retry."""
    report = await asyncio.to_thread(_run_revocation, person_id, request.app)
    return _revocation_response(report, response)


@router.post("/retry/{person_id}")
async def retry_consent_purge(person_id: str, response: Response, request: Request) -> dict:
    """Resume a retained purge without restoring consent or losing prior effects."""
    report = await asyncio.to_thread(_run_revocation, person_id, request.app, retry=True)
    if report is None:
        response.status_code = 404
        return {
            "error": "purge_retry_unavailable",
            "durable_record": {"event": "purge_pending", "audit": str(_PURGE_AUDIT_PATH)},
            "retry_instruction": (
                "No report retained in this process. Inspect the durable purge_pending "
                "record for outstanding contracts and reconcile manually; consent remains revoked."
            ),
        }
    return _revocation_response(report, response)


@router.get("/trace")
async def trace_consent(
    source: str = Query(..., description="File path or source identifier"),
) -> dict:
    return await asyncio.to_thread(_trace_consent, source)


@estate_identity_operation()
def _trace_consent(source: str = Query(..., description="File path or source identifier")) -> dict:
    """Trace consent provenance for a file.

    Shows: consent label, provenance contracts, flow constraints,
    and revocation impact. This is the IFC claim made visible.
    """
    decoded_source = unquote(source).strip()
    source_path = _resolve_trace_source(source)

    # Extract consent metadata from the file
    label_data = None
    provenance_data: list[str] = []
    body_preview = ""
    body = ""
    consent_label = None

    if source_path is not None and source_path.exists():
        try:
            from logos._frontmatter import (
                extract_consent_label,
                extract_provenance,
                parse_frontmatter,
            )

            fm, body = parse_frontmatter(source_path)
            consent_label = extract_consent_label(fm)
            provenance = extract_provenance(fm)
            provenance_data = sorted({resolve_contract_id(cid) for cid in provenance})

            if consent_label is not None:
                label_data = [
                    {
                        "owner": resolve_principal_id(owner),
                        "readers": sorted({resolve_principal_id(reader) for reader in readers}),
                    }
                    for owner, readers in consent_label.policies
                ]
        except Exception:
            _log.warning("consent_trace_parse_failed: inspect source metadata before retrying")
            body = ""

    # Look up contracts from provenance
    contracts = []
    try:
        from logos._consent_reader import ConsentGatedReader
        from logos._governance import load_contracts
        from logos.api.deps.consent_gate import gate_response
        from logos.api.deps.stream_redaction import pii_redact, references_non_broadcast_person_id
        from shared.labeled_trace import serialize_label

        registry = load_contracts()
        preview = gate_response({"body": body, "_consent": serialize_label(consent_label)})
        with estate_identity_operation() as snapshot:
            if (
                preview.get("_redacted")
                or snapshot.contains_predecessor(body.lower())
                or references_non_broadcast_person_id(body, registry)
            ):
                body_preview = "[redacted]" if body else ""
            else:
                reader = ConsentGatedReader(registry, frozenset({"operator"}))
                body_preview = pii_redact(
                    reader.filter_tool_result("search_documents", preview.get("body", ""))
                )[:200]
        for contract_id in provenance_data:
            contract = registry.get(contract_id)
            if contract:
                contracts.append(
                    {
                        "id": resolve_contract_id(contract.id),
                        "parties": [resolve_principal_id(party) for party in contract.parties],
                        "scope": sorted(contract.scope),
                        "active": contract.active,
                        "created_at": contract.created_at,
                        "revoked_at": contract.revoked_at,
                    }
                )
    except Exception:
        _log.warning("consent_trace_unavailable: inspect contract storage before retrying")
        body_preview = "[redacted]" if body else ""

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

            from logos.api.routes._config import get_qdrant

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
            _log.warning(
                "consent_trace_count_unavailable: inspect document storage before retrying"
            )

    exported_source = str(source_path) if source_path is not None else decoded_source
    with estate_identity_operation() as snapshot:
        if snapshot.contains_predecessor(exported_source.lower()):
            exported_source = "[redacted]"
    return {
        "source": exported_source,
        "exists": source_path.exists() if source_path is not None else False,
        "body_preview": body_preview,
        "consent_label": label_data,
        "provenance": provenance_data,
        "contracts": contracts,
        "information_flow": flow_analysis,
        "revocation_impact": revocation_impact,
    }


@router.get("/contracts")
async def list_contracts() -> dict:
    return await asyncio.to_thread(
        _list_contracts,
    )


@estate_identity_operation()
def _list_contracts() -> dict:
    """List all consent contracts (active and revoked).

    LRR Phase 6 §4.A: when stream is publicly visible, replaces each party
    name with a positional role label (``operator`` stays; other parties
    become ``party_N``). ``scope`` is structural (e.g. ``voice_text``,
    ``biometrics``, ``broadcast``) and safe as-is; timestamps are safe.
    """
    try:
        from logos._governance import load_contracts
        from logos.api.deps.stream_redaction import is_publicly_visible

        registry = load_contracts()
        redact_parties = is_publicly_visible()
        contracts = []
        for contract in registry:
            parties_out: list[str]
            if redact_parties:
                parties_out = []
                n = 0
                for p in contract.parties:
                    if p == "operator":
                        parties_out.append("operator")
                    else:
                        n += 1
                        parties_out.append(f"party_{n}")
            else:
                parties_out = [resolve_principal_id(party) for party in contract.parties]
            contracts.append(
                {
                    "id": resolve_contract_id(contract.id),
                    "parties": parties_out,
                    "scope": sorted(contract.scope),
                    "active": contract.active,
                    "created_at": contract.created_at,
                    "revoked_at": contract.revoked_at,
                }
            )
        return {"contracts": contracts, "active_count": sum(1 for c in contracts if c["active"])}
    except Exception:
        _log.warning("Failed to list consent contracts", exc_info=True)
        return {"contracts": [], "active_count": 0, "error": "contract list unavailable"}


@router.get("/coverage")
async def consent_coverage() -> dict:
    """Summary of consent coverage across stored data.

    Shows how much data has consent labels vs public/unlabeled.
    This makes the IFC claim visible: you can see what's protected
    and what isn't.
    """
    try:
        from qdrant_client.models import Filter, IsNullCondition

        from logos.api.routes._config import get_qdrant

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
    except Exception:
        _log.warning("Failed to compute consent coverage", exc_info=True)
        return {"error": "consent coverage unavailable"}


@router.get("/precedents")
async def precedent_timeline(axiom_id: str | None = None) -> dict:
    """Axiom precedent timeline — accumulated case law.

    Shows governance decisions chronologically, proving that the
    constitutional system evolves through precedent without changing
    the axioms themselves.
    """
    try:
        from logos.api.routes._config import get_qdrant

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
    except Exception:
        _log.warning("Failed to load axiom precedents", exc_info=True)
        return {
            "error": "precedent timeline unavailable",
            "total_precedents": 0,
            "precedents": [],
        }


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
