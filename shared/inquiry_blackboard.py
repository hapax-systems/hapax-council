"""Inquiry blackboard for autonomous source-following in segment prep.

Replaces fixed pipeline choreography with an opportunistic workspace.
Capabilities bid on blackboard objects they can improve. Quiescence
means no unresolved gap above risk threshold and no positive-value bid
inside budget.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Lead(BaseModel):
    model_config = ConfigDict(frozen=True)

    lead_id: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    source_pressure: str = Field(min_length=1)
    resolved: bool = False
    resolution: str = ""


class SourceGap(BaseModel):
    model_config = ConfigDict(frozen=False)

    gap_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    tried_sources: list[str] = Field(default_factory=list)
    recruited_sources: list[str] = Field(default_factory=list)
    claim_it_changes: str = Field(min_length=1)
    status: str = "open"
    risk: float = 0.5
    resolution: str = ""


class ClaimGap(BaseModel):
    model_config = ConfigDict(frozen=True)

    gap_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    severity: str = "blocking"


class FormProposal(BaseModel):
    model_config = ConfigDict(frozen=True)

    gap_id: str = Field(min_length=1)
    form_id: str = Field(min_length=1)
    grounding_question: str = Field(min_length=1)
    status: str = "proposed"


class ActionGap(BaseModel):
    model_config = ConfigDict(frozen=True)

    gap_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    status: str = "open"


class LayoutGap(BaseModel):
    model_config = ConfigDict(frozen=True)

    gap_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    layout_need: str = Field(min_length=1)
    status: str = "open"


class PersonageGap(BaseModel):
    model_config = ConfigDict(frozen=True)

    gap_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    violation_type: str = Field(min_length=1)
    status: str = "open"


class AuthorityGap(BaseModel):
    model_config = ConfigDict(frozen=True)

    gap_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    transition_blocked: str = Field(min_length=1)
    status: str = "open"


class ReviewGap(BaseModel):
    model_config = ConfigDict(frozen=True)

    gap_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    review_type: str = Field(min_length=1)
    status: str = "open"


class NoCandidateReason(BaseModel):
    model_config = ConfigDict(frozen=True)

    reason_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    lead_ids: list[str] = Field(default_factory=list)
    source_gaps: list[str] = Field(default_factory=list)
    budget_exhausted: bool = False


class Bid(BaseModel):
    model_config = ConfigDict(frozen=True)

    bidder: str = Field(min_length=1)
    target_gap_id: str = Field(min_length=1)
    expected_value: float = Field(ge=0.0, le=1.0)
    budget_cost: float = Field(ge=0.0)
    authority_boundary: str = Field(min_length=1)
    what_it_changes: str = ""


GapType = SourceGap | ClaimGap | ActionGap | LayoutGap | PersonageGap | AuthorityGap | ReviewGap


class BlackboardState(BaseModel):
    leads: list[Lead] = Field(default_factory=list)
    gaps: list[GapType] = Field(default_factory=list)
    bids: list[Bid] = Field(default_factory=list)
    no_candidate_reasons: list[NoCandidateReason] = Field(default_factory=list)
    budget_remaining: float = 0.0


def detect_quiescence(state: BlackboardState, risk_threshold: float = 0.5) -> bool:
    open_gaps_above_threshold = [
        g
        for g in state.gaps
        if getattr(g, "status", "open") == "open" and getattr(g, "risk", 0.5) >= risk_threshold
    ]
    if open_gaps_above_threshold:
        return False

    positive_bids = [b for b in state.bids if b.expected_value > 0 and b.what_it_changes]
    return not positive_bids


def detect_source_theater(bids: list[Bid]) -> list[str]:
    return [b.target_gap_id for b in bids if not b.what_it_changes.strip()]


def resolve_gap(gap: SourceGap, resolution: str) -> SourceGap:
    gap.status = "resolved"
    gap.resolution = resolution
    return gap
