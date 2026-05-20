"""WCS health degraded blocker bus.

Publishes WCS health failures and degraded states as first-class blocked
reasons that scheduler, runner, scrim, director, public-event, and
conversion surfaces can consume. Health events are not a hidden manual
review queue — they are machine-readable bus records.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)

type CapabilityState = Literal[
    "healthy",
    "degraded",
    "stale",
    "blocked",
    "recovered",
    "dry_run_only",
    "private_only",
]

type FalseGroundingCause = Literal[
    "stale_temporal_band",
    "protention_only_evidence",
    "stale_perceptual_field",
    "spanless_media",
    "synthetic_only_provenance",
    "missing_witness",
    "impression_missing",
]

type AuthorityCeiling = Literal[
    "public_monetizable",
    "public_live",
    "public_archive",
    "private_only",
    "dry_run_only",
    "blocked",
]

CEILINGS_ALLOWING_PUBLIC: frozenset[AuthorityCeiling] = frozenset(
    {
        "public_monetizable",
        "public_live",
        "public_archive",
    }
)


class WcsHealthBusEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    capability: str
    state: CapabilityState
    authority_ceiling: AuthorityCeiling
    witness_refs: list[str] = Field(default_factory=list)
    freshness_seconds: float | None = None
    false_grounding_causes: list[FalseGroundingCause] = Field(default_factory=list)
    public_claim_consequence: str = ""
    blocked_reason: str = ""
    emitted_at: str = ""

    def blocks_public_live(self) -> bool:
        return self.authority_ceiling not in CEILINGS_ALLOWING_PUBLIC

    def blocks_monetized(self) -> bool:
        return self.authority_ceiling != "public_monetizable"


class WcsBlockerSnapshot(BaseModel):
    """Machine-readable snapshot of current blocked reasons for scheduler/director."""

    model_config = ConfigDict(frozen=True)

    snapshot_at: str
    total_capabilities: int = 0
    healthy: int = 0
    degraded: int = 0
    blocked: int = 0
    blockers: list[WcsHealthBusEvent] = Field(default_factory=list)

    @property
    def all_healthy(self) -> bool:
        return self.blocked == 0 and self.degraded == 0

    def blocked_reasons(self) -> list[str]:
        return [e.blocked_reason for e in self.blockers if e.blocked_reason]

    def public_live_blocked(self) -> bool:
        return any(e.blocks_public_live() for e in self.blockers)

    def monetized_blocked(self) -> bool:
        return any(e.blocks_monetized() for e in self.blockers)


class WcsHealthBlockerBus:
    """Collects and publishes WCS health bus events."""

    def __init__(self) -> None:
        self._events: list[WcsHealthBusEvent] = []
        self._event_counter = 0

    def emit(
        self,
        capability: str,
        state: CapabilityState,
        *,
        authority_ceiling: AuthorityCeiling = "blocked",
        witness_refs: list[str] | None = None,
        freshness_seconds: float | None = None,
        false_grounding_causes: list[FalseGroundingCause] | None = None,
        public_claim_consequence: str = "",
        blocked_reason: str = "",
    ) -> WcsHealthBusEvent:
        self._event_counter += 1
        event = WcsHealthBusEvent(
            event_id=f"wcs-health-{self._event_counter}",
            capability=capability,
            state=state,
            authority_ceiling=authority_ceiling,
            witness_refs=witness_refs or [],
            freshness_seconds=freshness_seconds,
            false_grounding_causes=false_grounding_causes or [],
            public_claim_consequence=public_claim_consequence,
            blocked_reason=blocked_reason,
            emitted_at=datetime.now(UTC).isoformat(),
        )
        self._events.append(event)
        log.info(
            "wcs_health_bus: %s %s ceiling=%s%s",
            capability,
            state,
            authority_ceiling,
            f" reason={blocked_reason}" if blocked_reason else "",
        )
        return event

    def snapshot(self) -> WcsBlockerSnapshot:
        active = self._latest_per_capability()
        return WcsBlockerSnapshot(
            snapshot_at=datetime.now(UTC).isoformat(),
            total_capabilities=len(active),
            healthy=sum(1 for e in active if e.state == "healthy"),
            degraded=sum(1 for e in active if e.state == "degraded"),
            blocked=sum(
                1 for e in active if e.state in ("blocked", "stale", "dry_run_only", "private_only")
            ),
            blockers=[e for e in active if e.state != "healthy" and e.state != "recovered"],
        )

    def _latest_per_capability(self) -> list[WcsHealthBusEvent]:
        latest: dict[str, WcsHealthBusEvent] = {}
        for e in self._events:
            latest[e.capability] = e
        return list(latest.values())

    def clear(self) -> None:
        self._events.clear()
        self._event_counter = 0
