"""Artifact release state machine.

Tracks how public events become artifact candidates and progress through
release states. Each transition records evidence and reason. Refusal
states are first-class — missing provenance, private data, rights risk,
overclaiming, and manual-labor obligations all have explicit states.

Publication rows (GitHub release, profile, package, Pages) are treated
as publication state evidence, not rights clearance, scientific
validation, or monetization readiness.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)

type RefusalReason = Literal[
    "missing_provenance",
    "private_data",
    "rights_risk",
    "overclaiming",
    "manual_labor_obligation",
    "consent_missing",
    "monetization_unready",
]


class ReleaseState(StrEnum):
    CANDIDATE = "candidate"
    HELD = "held"
    BLOCKED = "blocked"
    PRIVATE_ONLY = "private_only"
    PUBLIC_SAFE = "public_safe"
    RELEASED = "released"
    REUSED = "reused"
    SOLD = "sold"
    LICENSED = "licensed"
    GRANT_USED = "grant_used"
    WITHDRAWN = "withdrawn"
    REFUSED = "refused"


TERMINAL_STATES = frozenset(
    {
        ReleaseState.RELEASED,
        ReleaseState.REUSED,
        ReleaseState.SOLD,
        ReleaseState.LICENSED,
        ReleaseState.GRANT_USED,
        ReleaseState.WITHDRAWN,
        ReleaseState.REFUSED,
    }
)

VALID_TRANSITIONS: dict[ReleaseState, frozenset[ReleaseState]] = {
    ReleaseState.CANDIDATE: frozenset(
        {
            ReleaseState.HELD,
            ReleaseState.BLOCKED,
            ReleaseState.PRIVATE_ONLY,
            ReleaseState.PUBLIC_SAFE,
            ReleaseState.REFUSED,
        }
    ),
    ReleaseState.HELD: frozenset(
        {
            ReleaseState.CANDIDATE,
            ReleaseState.BLOCKED,
            ReleaseState.PUBLIC_SAFE,
            ReleaseState.REFUSED,
            ReleaseState.WITHDRAWN,
        }
    ),
    ReleaseState.BLOCKED: frozenset(
        {
            ReleaseState.CANDIDATE,
            ReleaseState.REFUSED,
            ReleaseState.WITHDRAWN,
        }
    ),
    ReleaseState.PRIVATE_ONLY: frozenset(
        {
            ReleaseState.PUBLIC_SAFE,
            ReleaseState.REFUSED,
            ReleaseState.WITHDRAWN,
        }
    ),
    ReleaseState.PUBLIC_SAFE: frozenset(
        {
            ReleaseState.RELEASED,
            ReleaseState.HELD,
            ReleaseState.REFUSED,
            ReleaseState.WITHDRAWN,
        }
    ),
    ReleaseState.RELEASED: frozenset(
        {
            ReleaseState.REUSED,
            ReleaseState.SOLD,
            ReleaseState.LICENSED,
            ReleaseState.GRANT_USED,
            ReleaseState.WITHDRAWN,
        }
    ),
    ReleaseState.REUSED: frozenset({ReleaseState.WITHDRAWN}),
    ReleaseState.SOLD: frozenset({ReleaseState.WITHDRAWN}),
    ReleaseState.LICENSED: frozenset({ReleaseState.WITHDRAWN}),
    ReleaseState.GRANT_USED: frozenset({ReleaseState.WITHDRAWN}),
    ReleaseState.WITHDRAWN: frozenset(),
    ReleaseState.REFUSED: frozenset(),
}


class SourceRef(BaseModel):
    model_config = ConfigDict(frozen=True)
    ref_type: str
    ref_id: str


class ReleaseTransition(BaseModel):
    model_config = ConfigDict(frozen=True)
    from_state: ReleaseState
    to_state: ReleaseState
    reason: str
    transitioned_at: str
    evidence_refs: list[str] = Field(default_factory=list)
    refusal_reason: RefusalReason | None = None


class ArtifactReleaseRecord(BaseModel):
    artifact_id: str
    state: ReleaseState = ReleaseState.CANDIDATE
    public_event_refs: list[SourceRef] = Field(default_factory=list)
    run_refs: list[SourceRef] = Field(default_factory=list)
    archive_refs: list[SourceRef] = Field(default_factory=list)
    rights_class: str = "unknown"
    privacy_class: str = "unknown"
    claim_scope: str = ""
    release_reason: str = ""
    transitions: list[ReleaseTransition] = Field(default_factory=list)
    created_at: str = ""

    def transition(
        self,
        to_state: ReleaseState,
        *,
        reason: str,
        evidence_refs: list[str] | None = None,
        refusal_reason: RefusalReason | None = None,
    ) -> ReleaseTransition:
        valid = VALID_TRANSITIONS.get(self.state, frozenset())
        if to_state not in valid:
            msg = f"Invalid transition {self.state} -> {to_state}"
            raise InvalidTransitionError(msg)

        if to_state == ReleaseState.REFUSED and refusal_reason is None:
            msg = "Refusal requires a refusal_reason"
            raise InvalidTransitionError(msg)

        if to_state == ReleaseState.RELEASED and not self.public_event_refs:
            msg = "Cannot release without public_event_refs"
            raise InvalidTransitionError(msg)

        t = ReleaseTransition(
            from_state=self.state,
            to_state=to_state,
            reason=reason,
            transitioned_at=datetime.now(UTC).isoformat(),
            evidence_refs=evidence_refs or [],
            refusal_reason=refusal_reason,
        )
        self.state = to_state
        self.transitions.append(t)
        return t

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def blocked_reasons(self) -> list[str]:
        return [
            t.reason
            for t in self.transitions
            if t.to_state in (ReleaseState.BLOCKED, ReleaseState.REFUSED)
        ]


class InvalidTransitionError(ValueError):
    pass


class ReleaseMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)
    total: int = 0
    by_state: dict[str, int] = Field(default_factory=dict)
    by_refusal_reason: dict[str, int] = Field(default_factory=dict)
    conversion_funnel: dict[str, int] = Field(default_factory=dict)

    @classmethod
    def from_records(cls, records: list[ArtifactReleaseRecord]) -> ReleaseMetrics:
        by_state: dict[str, int] = {}
        by_refusal: dict[str, int] = {}
        funnel: dict[str, int] = {}

        for r in records:
            by_state[r.state.value] = by_state.get(r.state.value, 0) + 1
            for t in r.transitions:
                if t.refusal_reason:
                    by_refusal[t.refusal_reason] = by_refusal.get(t.refusal_reason, 0) + 1
            for t in r.transitions:
                key = f"{t.from_state.value}->{t.to_state.value}"
                funnel[key] = funnel.get(key, 0) + 1

        return cls(
            total=len(records),
            by_state=by_state,
            by_refusal_reason=by_refusal,
            conversion_funnel=funnel,
        )
