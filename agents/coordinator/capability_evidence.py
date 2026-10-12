"""Capability-evidence producer for the dispatch coordinator (NO-STALL U3a).

Composes the governed dispatch-policy sources plus the review-team family-outage
record into the capability-level evidence the availability predicate needs: one
report naming, per route, whether it is available now, what blocks it, which
receipts keep it fresh, and how long that evidence stays valid. Inert by
construction: it reads state and returns a report; it launches nothing, mutates
nothing, and is not wired into any runtime loop (U3b's own authorization gates
that wiring).

Family-outage semantics (v9 rule 1): an outage entry whose wall has a future
``resets_at`` blocks the family's routes; a wall whose ``resets_at`` has passed
is expired and blocks nothing; an entry with no usable ``resets_at`` qualifies as
a wall of unknown reset and blocks (unknown never releases). Family keys match a
route's declared platform exactly — aliases are never invented; the seat may
supply an explicit ``platform_family_map`` when wiring (U3b).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from shared.dispatcher_policy import (
    DispatchPolicySources,
    RouteAuthorityReceipt,
    _parse_duration_spec,
    route_authority_receipt_reference,
)
from shared.platform_capability_registry import RouteState, normalize_route_id

DEFAULT_OBSERVER_INTERVAL_S = 300
FAMILY_WALL_RESET_UNKNOWN = "family_wall_reset_unknown"
OUTAGE_STORE_UNREADABLE = "family_outage_store_unreadable"


@dataclass(frozen=True)
class RouteCapabilityEvidence:
    route_id: str
    platform: str
    available: bool
    blocked_reasons: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    valid_until: datetime
    family_wall: bool


@dataclass(frozen=True)
class CapabilityEvidenceReport:
    generated_at: datetime
    route_evidence: tuple[RouteCapabilityEvidence, ...]
    registry_error: str | None
    outage_read_error: str | None
    observer_interval_s: int

    def route(self, route_id: str) -> RouteCapabilityEvidence | None:
        return next((record for record in self.route_evidence if record.route_id == route_id), None)

    @property
    def usable_routes(self) -> tuple[str, ...]:
        if self.registry_error or self.outage_read_error:
            return ()
        return tuple(record.route_id for record in self.route_evidence if record.available)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _iso_z(value: datetime) -> str:
    return _as_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _family_covers(
    family: str,
    platform: str,
    platform_family_map: Mapping[str, Iterable[str]] | None,
) -> bool:
    if platform == family:
        return True
    if platform_family_map is None:
        return False
    return platform in tuple(platform_family_map.get(family, ()))


def _family_wall_reason(family: str, entry: object, now: datetime) -> str | None:
    if not isinstance(entry, Mapping):
        return FAMILY_WALL_RESET_UNKNOWN
    wall_evidence = entry.get("wall_evidence")
    resets_at = wall_evidence.get("resets_at") if isinstance(wall_evidence, Mapping) else None
    if not isinstance(resets_at, str) or not resets_at.strip():
        return FAMILY_WALL_RESET_UNKNOWN
    try:
        reset_dt = datetime.fromisoformat(resets_at)
    except ValueError:
        return FAMILY_WALL_RESET_UNKNOWN
    if _as_utc(reset_dt) <= now:
        return None
    return f"family-wall:{family}:resets-at:{_iso_z(reset_dt)}"


def _receipt_expiry(
    receipt: RouteAuthorityReceipt, *, now: datetime, observer_interval_s: int
) -> datetime:
    try:
        delta = _parse_duration_spec(receipt.stale_after)
    except ValueError:
        delta = None
    if delta is None:
        return now + timedelta(seconds=observer_interval_s)
    return _as_utc(receipt.issued_at) + delta


def _route_valid_until(
    route_id: str,
    receipts: tuple[RouteAuthorityReceipt, ...],
    *,
    now: datetime,
    observer_interval_s: int,
) -> tuple[datetime, tuple[str, ...]]:
    expiries: list[datetime] = []
    refs: list[str] = []
    for receipt in receipts:
        if normalize_route_id(receipt.route_id) != normalize_route_id(route_id):
            continue
        expiry = _receipt_expiry(receipt, now=now, observer_interval_s=observer_interval_s)
        if expiry <= now:
            continue
        expiries.append(expiry)
        refs.append(route_authority_receipt_reference(receipt))
    if not expiries:
        return now + timedelta(seconds=observer_interval_s), ()
    return min(expiries), tuple(refs)


def _read_family_outage(path: Path) -> tuple[dict[str, object], str | None]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, None
    except (OSError, UnicodeDecodeError) as exc:
        return {}, f"family_outage_store_unreadable:{exc.__class__.__name__}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, f"family_outage_store_unreadable:{exc.__class__.__name__}"
    if not isinstance(parsed, dict):
        return {}, "family_outage_store_unreadable:not_a_mapping"
    return parsed, None


def produce_capability_evidence(
    sources: DispatchPolicySources,
    family_outage_path: Path,
    *,
    now: datetime,
    observer_interval_s: int = DEFAULT_OBSERVER_INTERVAL_S,
    platform_family_map: Mapping[str, Iterable[str]] | None = None,
) -> CapabilityEvidenceReport:
    if observer_interval_s <= 0:
        raise ValueError("observer_interval_s must be positive")
    checked_at = _as_utc(now)
    if sources.registry is None:
        return CapabilityEvidenceReport(
            generated_at=checked_at,
            route_evidence=(),
            registry_error=sources.registry_error or "registry_unavailable",
            outage_read_error=None,
            observer_interval_s=observer_interval_s,
        )

    outage, outage_read_error = _read_family_outage(family_outage_path)

    route_evidence: list[RouteCapabilityEvidence] = []
    for route in sources.registry.routes:
        blocked_reasons = list(route.blocked_reasons)
        family_wall = False
        if outage_read_error is not None:
            blocked_reasons.append(OUTAGE_STORE_UNREADABLE)
        else:
            for family, entry in outage.items():
                if not _family_covers(family, route.platform.value, platform_family_map):
                    continue
                reason = _family_wall_reason(family, entry, checked_at)
                if reason is not None:
                    blocked_reasons.append(reason)
                    family_wall = True
        valid_until, evidence_refs = _route_valid_until(
            route.route_id,
            sources.route_authority_receipts,
            now=checked_at,
            observer_interval_s=observer_interval_s,
        )
        route_evidence.append(
            RouteCapabilityEvidence(
                route_id=route.route_id,
                platform=route.platform.value,
                available=route.route_state is RouteState.ACTIVE and not blocked_reasons,
                blocked_reasons=tuple(blocked_reasons),
                evidence_refs=evidence_refs,
                valid_until=valid_until,
                family_wall=family_wall,
            )
        )

    return CapabilityEvidenceReport(
        generated_at=checked_at,
        route_evidence=tuple(route_evidence),
        registry_error=None,
        outage_read_error=outage_read_error,
        observer_interval_s=observer_interval_s,
    )
