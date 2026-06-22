"""Inquiry blackboard for autonomous source-following in segment prep.

Replaces fixed pipeline choreography with an opportunistic workspace.
Capabilities bid on blackboard objects they can improve. Quiescence
means no unresolved gap above risk threshold and no positive-value bid
inside budget.
"""

from __future__ import annotations

import os
from typing import Literal

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


# --- Deontic ledger (the public commitment/challenge economy) -----------------
# A claim is WARRANTED to the degree its supporting structure is adequate to its
# own PURPORT (what it commits to / excludes) — one differential, no claim-type
# branch. Asserting a claim posts a Commitment; the matter and rival interpreters
# post Challenges; an independent rival posts an ExhaustionAttestation ("I sought a
# stronger commitment you incurred and found none"). "Good enough" is not a score:
# it is the event-state where every commitment has discharged (by deferral /
# inference / reliability) and no challenge stands, AND silence is positively
# attested — never merely absent. See the felt-overreach synthesis (wf_dc4ea020).


class Commitment(BaseModel):
    model_config = ConfigDict(frozen=True)

    claim_id: str = Field(min_length=1)
    # The consequential commitments this claim licenses (its purport), read off its
    # CONTENT — not a type tag. The empirical reality-check rides whichever of these
    # is "commits to mind-independent evidence existing", wherever it is projected.
    purport: tuple[str, ...] = Field(default_factory=tuple)
    incompatibilities: tuple[str, ...] = Field(default_factory=tuple)
    rebuttal_condition: str = ""
    qualifier: str = ""
    discharge_route: Literal["deferral", "inference", "reliability", "undischarged"] = (
        "undischarged"
    )


class Challenge(BaseModel):
    model_config = ConfigDict(frozen=True)

    challenge_id: str = Field(min_length=1)
    target_claim_id: str = Field(min_length=1)
    counter_position: str = Field(min_length=1)
    # The rival is an LLM and may only PROPOSE; a challenge discharges against
    # reality contact (empirical purport) or "undefeated after N families" (else).
    challenger_family: str = Field(min_length=1)
    status: Literal["open", "discharged", "retracted"] = "open"
    # An open challenge that was vindication-attempted and still stands is a RED
    # on the forward path to rest — the felt obstacle, not a scalar.
    vindication_attempted: bool = False


class ExhaustionAttestation(BaseModel):
    model_config = ConfigDict(frozen=True)

    claim_id: str = Field(min_length=1)
    attester_family: str = Field(min_length=1)
    # True = the attester found a STRONGER commitment the claim incurred but did not
    # declare (an under-projection) -> the claim cannot rest. Silence is not rest.
    found_stronger_commitment: bool = False


class BlackboardState(BaseModel):
    leads: list[Lead] = Field(default_factory=list)
    gaps: list[GapType] = Field(default_factory=list)
    bids: list[Bid] = Field(default_factory=list)
    no_candidate_reasons: list[NoCandidateReason] = Field(default_factory=list)
    budget_remaining: float = 0.0
    # Deontic-ledger fields (default empty -> legacy callers unaffected).
    commitments: list[Commitment] = Field(default_factory=list)
    challenges: list[Challenge] = Field(default_factory=list)
    attestations: list[ExhaustionAttestation] = Field(default_factory=list)


_INVERTED_QUIESCENCE_ENV = "HAPAX_INVERTED_QUIESCENCE"


def inverted_quiescence_enabled() -> bool:
    """Deontic-ledger quiescence is OFF by default. When on, it FAILS toward
    not-quiescent (block rest) — never back toward the old silence-passes default."""
    return os.environ.get(_INVERTED_QUIESCENCE_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def attested_quiescence(state: BlackboardState) -> bool:
    """Inverted, threshold-free quiescence: rest requires POSITIVE attestation.

    Silence is not rest. A board with no commitments has asserted nothing it could
    be pulled up short on -> NOT quiescent. Otherwise quiescent iff:
      (a) every commitment has discharged (deferral/inference/reliability) or carries
          an exhaustion-attestation with found_stronger_commitment=False,
      (b) no challenge is open-AND-vindication-attempted (a standing red on the
          forward path to rest), and
      (c) every published claim carries >=1 attestation from an independent family
          (an unattested claim is itself a standing open gap — silence, made loud).
    """
    claim_ids = {c.claim_id for c in state.commitments}
    if not claim_ids:
        return False  # the inversion: an empty/thin board can never rest

    # A rival that found a STRONGER un-declared commitment is reporting an
    # under-projection (overreach-by-omission) — a standing gap the claim cannot
    # rest on until it is taken up. Reading oneself thinly buys nothing.
    if any(a.found_stronger_commitment and a.claim_id in claim_ids for a in state.attestations):
        return False

    exhausted = {a.claim_id for a in state.attestations if not a.found_stronger_commitment}
    for commitment in state.commitments:
        if commitment.discharge_route == "undischarged" and commitment.claim_id not in exhausted:
            return False  # (a) an unmet, un-attested commitment blocks rest

    if any(ch.status == "open" and ch.vindication_attempted for ch in state.challenges):
        return False  # (b) a vindication-attempted challenge that still stands is RED

    families_by_claim: dict[str, set[str]] = {}
    for attestation in state.attestations:
        families_by_claim.setdefault(attestation.claim_id, set()).add(attestation.attester_family)
    # (c) every published claim carries >=1 attestation from an independent family;
    # an unattested claim is itself a standing open gap — silence, made loud.
    return all(families_by_claim.get(claim_id) for claim_id in claim_ids)


def detect_quiescence(state: BlackboardState, risk_threshold: float = 0.5) -> bool:
    if inverted_quiescence_enabled():
        return attested_quiescence(state)
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
