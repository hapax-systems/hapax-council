"""Typed contract helpers for criteria-bounded tier/ranking/bracket decisions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.content_programme_run_store import (
    BoundaryMappingState,
    ContentProgrammeRunStoreEvent,
    CuepointChapterDistinction,
    ProgrammeBoundaryEventRef,
    PublicPrivateMode,
    UnavailableReason,
)

type RankingFormat = Literal["tier_list", "ranking", "bracket"]
type CriterionDirection = Literal["higher_better", "lower_better", "categorical", "evidence_bound"]
type ComparisonOutcome = Literal["left", "right", "tie", "incomparable", "refused"]
type TieBreakMethod = Literal[
    "criterion_priority",
    "evidence_freshness",
    "uncertainty_lower_bound",
    "stable_id_order",
    "refusal_boundary",
    "no_tiebreak",
]
type UncertaintyState = Literal["low", "medium", "high", "unknown"]
type DecisionState = Literal["candidate", "accepted", "refused", "reversed", "superseded"]
type InconsistencyKind = Literal[
    "cycle",
    "criterion_conflict",
    "evidence_conflict",
    "tie_break_conflict",
    "reversal_required",
    "missing_evidence",
]
type InconsistencyResolutionState = Literal[
    "open",
    "refused",
    "resolved_by_tiebreak",
    "resolved_by_reversal",
]
type BoundarySurface = Literal["chapter", "shorts", "replay_card", "dataset", "zine"]
type OutputEligibility = Literal["private", "dry_run", "public_ready", "held", "blocked"]
type RankingRunStoreEventKind = Literal[
    "evidence_attached",
    "boundary_emitted",
    "claim_recorded",
    "correction_made",
    "conversion_held",
    "completed",
    "blocked",
]

BOUNDARY_SURFACES: tuple[BoundarySurface, ...] = (
    "chapter",
    "shorts",
    "replay_card",
    "dataset",
    "zine",
)
BOUNDARY_TYPES: dict[BoundarySurface, str] = {
    "chapter": "chapter.boundary",
    "shorts": "shorts.boundary",
    "replay_card": "replay_card.boundary",
    "dataset": "dataset.boundary",
    "zine": "zine.boundary",
}
RANKING_RUN_STORE_EVENT_TYPES: tuple[RankingRunStoreEventKind, ...] = (
    "evidence_attached",
    "boundary_emitted",
    "claim_recorded",
    "correction_made",
    "conversion_held",
    "completed",
    "blocked",
)


class TierRankingModel(BaseModel):
    """Strict immutable base for tier/ranking/bracket helper records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class EvidenceAnchor(TierRankingModel):
    evidence_id: str
    evidence_ref: str
    evidence_envelope_ref: str
    wcs_ref: str
    source_ref: str
    label: str
    supports: tuple[str, ...] = Field(default_factory=tuple)


class CandidateRecord(TierRankingModel):
    candidate_id: str
    label: str
    source_refs: tuple[str, ...] = Field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    evidence_envelope_refs: tuple[str, ...] = Field(default_factory=tuple)
    wcs_refs: tuple[str, ...] = Field(default_factory=tuple)
    rights_refs: tuple[str, ...] = Field(default_factory=tuple)


class CriterionRecord(TierRankingModel):
    criterion_id: str
    label: str
    description: str
    direction: CriterionDirection
    weight: float = Field(ge=0)
    scope_limit: str
    evidence_refs: tuple[str, ...]
    wcs_refs: tuple[str, ...]


class CandidateSetRecord(TierRankingModel):
    candidate_set_id: str
    title: str
    scope_limit: str
    candidates: tuple[CandidateRecord, ...] = Field(min_length=2)
    criteria: tuple[CriterionRecord, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...]
    wcs_refs: tuple[str, ...]

    @model_validator(mode="after")
    def validate_candidate_set(self) -> Self:
        _require_unique((candidate.candidate_id for candidate in self.candidates), "candidate_id")
        _require_unique((criterion.criterion_id for criterion in self.criteria), "criterion_id")
        _require_refs(self.evidence_refs, "candidate_set.evidence_refs", self.candidate_set_id)
        _require_refs(self.wcs_refs, "candidate_set.wcs_refs", self.candidate_set_id)
        return self


class UncertaintyRecord(TierRankingModel):
    uncertainty_id: str
    state: UncertaintyState
    explanation: str
    missing_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    evidence_refs: tuple[str, ...]
    wcs_refs: tuple[str, ...]

    @model_validator(mode="after")
    def validate_uncertainty(self) -> Self:
        _require_refs(self.evidence_refs, "uncertainty.evidence_refs", self.uncertainty_id)
        _require_refs(self.wcs_refs, "uncertainty.wcs_refs", self.uncertainty_id)
        return self


class PairwiseComparisonRecord(TierRankingModel):
    comparison_id: str
    left_candidate_id: str
    right_candidate_id: str
    criterion_ids: tuple[str, ...] = Field(min_length=1)
    outcome: ComparisonOutcome
    rationale: str
    evidence_refs: tuple[str, ...]
    evidence_envelope_refs: tuple[str, ...]
    wcs_refs: tuple[str, ...]
    uncertainty_ref: str
    state: DecisionState = "accepted"
    criteria_bounded: Literal[True] = True
    expert_verdict_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_comparison(self) -> Self:
        if self.left_candidate_id == self.right_candidate_id:
            raise ValueError("pairwise comparison candidates must differ")
        _require_refs(self.evidence_refs, "comparison.evidence_refs", self.comparison_id)
        _require_refs(
            self.evidence_envelope_refs,
            "comparison.evidence_envelope_refs",
            self.comparison_id,
        )
        _require_refs(self.wcs_refs, "comparison.wcs_refs", self.comparison_id)
        return self


class TieBreakRecord(TierRankingModel):
    tie_break_id: str
    applies_to_rank_ids: tuple[str, ...] = Field(min_length=1)
    method: TieBreakMethod
    criterion_priority: tuple[str, ...] = Field(default_factory=tuple)
    rationale: str
    evidence_refs: tuple[str, ...]
    evidence_envelope_refs: tuple[str, ...]
    wcs_refs: tuple[str, ...]
    uncertainty_ref: str
    state: DecisionState = "accepted"
    expert_verdict_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_tie_break(self) -> Self:
        if self.method != "no_tiebreak":
            _require_refs(self.evidence_refs, "tie_break.evidence_refs", self.tie_break_id)
            _require_refs(
                self.evidence_envelope_refs,
                "tie_break.evidence_envelope_refs",
                self.tie_break_id,
            )
            _require_refs(self.wcs_refs, "tie_break.wcs_refs", self.tie_break_id)
        return self


class RankRecord(TierRankingModel):
    rank_id: str
    candidate_id: str
    ordinal: int = Field(ge=1)
    tier_id: str
    comparison_refs: tuple[str, ...] = Field(min_length=1)
    criterion_ids: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...]
    evidence_envelope_refs: tuple[str, ...]
    wcs_refs: tuple[str, ...]
    uncertainty_ref: str
    tie_break_ref: str | None = None
    score: float | None = Field(default=None, ge=0, le=1)
    scope_limit: str
    public_claim_allowed: bool = False
    criteria_bounded: Literal[True] = True
    expert_verdict_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_rank(self) -> Self:
        _require_refs(self.evidence_refs, "rank.evidence_refs", self.rank_id)
        _require_refs(self.evidence_envelope_refs, "rank.evidence_envelope_refs", self.rank_id)
        _require_refs(self.wcs_refs, "rank.wcs_refs", self.rank_id)
        return self


class TierRecord(TierRankingModel):
    tier_id: str
    label: str
    ordinal: int = Field(ge=1)
    rank_refs: tuple[str, ...] = Field(min_length=1)
    criteria_summary: str
    evidence_refs: tuple[str, ...]
    wcs_refs: tuple[str, ...]
    uncertainty_ref: str


class BracketMatchRecord(TierRankingModel):
    match_id: str
    round_index: int = Field(ge=1)
    match_index: int = Field(ge=1)
    left_candidate_id: str
    right_candidate_id: str
    comparison_ref: str
    outcome: ComparisonOutcome
    winner_candidate_id: str | None = None

    @model_validator(mode="after")
    def validate_match(self) -> Self:
        if self.left_candidate_id == self.right_candidate_id:
            raise ValueError("bracket match candidates must differ")
        if self.outcome == "left" and self.winner_candidate_id != self.left_candidate_id:
            raise ValueError("left outcome requires left candidate as winner")
        if self.outcome == "right" and self.winner_candidate_id != self.right_candidate_id:
            raise ValueError("right outcome requires right candidate as winner")
        if self.outcome in {"tie", "incomparable", "refused"} and self.winner_candidate_id:
            raise ValueError("non-winning comparison outcome cannot set winner_candidate_id")
        return self


class BracketRoundRecord(TierRankingModel):
    round_id: str
    round_index: int = Field(ge=1)
    match_refs: tuple[str, ...] = Field(min_length=1)


class BracketRecord(TierRankingModel):
    bracket_id: str
    candidate_set_id: str
    rounds: tuple[BracketRoundRecord, ...] = Field(min_length=1)
    matches: tuple[BracketMatchRecord, ...] = Field(min_length=1)
    champion_candidate_id: str | None = None
    evidence_refs: tuple[str, ...]
    wcs_refs: tuple[str, ...]
    inconsistency_refs: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_bracket(self) -> Self:
        _require_unique((round_.round_id for round_ in self.rounds), "round_id")
        _require_unique((match.match_id for match in self.matches), "match_id")
        match_ids = {match.match_id for match in self.matches}
        for round_ in self.rounds:
            unknown_refs = set(round_.match_refs) - match_ids
            if unknown_refs:
                raise ValueError(f"unknown match_refs in {round_.round_id}: {sorted(unknown_refs)}")
        _require_refs(self.evidence_refs, "bracket.evidence_refs", self.bracket_id)
        _require_refs(self.wcs_refs, "bracket.wcs_refs", self.bracket_id)
        return self


class ReversalRecord(TierRankingModel):
    reversal_id: str
    reversed_at: datetime
    previous_decision_ref: str
    new_decision_ref: str
    reason: str
    evidence_refs: tuple[str, ...]
    evidence_envelope_refs: tuple[str, ...]
    wcs_refs: tuple[str, ...]
    uncertainty_ref: str
    boundary_required: Literal[True] = True
    public_correction_required: Literal[True] = True
    expert_verdict_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_reversal(self) -> Self:
        _require_refs(self.evidence_refs, "reversal.evidence_refs", self.reversal_id)
        _require_refs(
            self.evidence_envelope_refs,
            "reversal.evidence_envelope_refs",
            self.reversal_id,
        )
        _require_refs(self.wcs_refs, "reversal.wcs_refs", self.reversal_id)
        return self


class InconsistencyRecord(TierRankingModel):
    inconsistency_id: str
    kind: InconsistencyKind
    detected_at: datetime
    comparison_refs: tuple[str, ...] = Field(default_factory=tuple)
    rank_refs: tuple[str, ...] = Field(default_factory=tuple)
    criterion_ids: tuple[str, ...] = Field(default_factory=tuple)
    explanation: str
    evidence_refs: tuple[str, ...]
    wcs_refs: tuple[str, ...]
    resolution_state: InconsistencyResolutionState
    resolution_ref: str | None = None

    @model_validator(mode="after")
    def validate_inconsistency(self) -> Self:
        _require_refs(self.evidence_refs, "inconsistency.evidence_refs", self.inconsistency_id)
        _require_refs(self.wcs_refs, "inconsistency.wcs_refs", self.inconsistency_id)
        if self.resolution_state != "open" and self.resolution_ref is None:
            raise ValueError("resolved inconsistency requires resolution_ref")
        return self


class NoExpertVerdictPolicy(TierRankingModel):
    criteria_bounded_outputs_only: Literal[True] = True
    evidence_label_required: Literal[True] = True
    authoritative_verdict_allowed: Literal[False] = False
    domain_truth_adjudication_allowed: Literal[False] = False
    engagement_metric_source_allowed: Literal[False] = False
    public_claim_requires_effective_public_mode: Literal[True] = True


class FinalDecisionRecord(TierRankingModel):
    schema_version: Literal[1] = 1
    decision_id: str
    run_id: str
    programme_id: str
    format_id: RankingFormat
    selected_at: datetime
    candidate_set: CandidateSetRecord
    comparisons: tuple[PairwiseComparisonRecord, ...] = Field(min_length=1)
    ranks: tuple[RankRecord, ...] = Field(min_length=1)
    tiers: tuple[TierRecord, ...] = Field(min_length=1)
    tie_breaks: tuple[TieBreakRecord, ...] = Field(default_factory=tuple)
    bracket: BracketRecord | None = None
    reversals: tuple[ReversalRecord, ...] = Field(default_factory=tuple)
    inconsistencies: tuple[InconsistencyRecord, ...] = Field(default_factory=tuple)
    evaluator_refs: tuple[str, ...] = Field(default_factory=tuple)
    run_store_refs: tuple[str, ...] = Field(default_factory=tuple)
    evidence_refs: tuple[str, ...]
    evidence_envelope_refs: tuple[str, ...]
    wcs_refs: tuple[str, ...]
    uncertainty_ref: str
    requested_public_private_mode: PublicPrivateMode
    public_private_mode: PublicPrivateMode
    output_eligibility: OutputEligibility
    public_claim_allowed: bool = False
    no_expert_verdict_policy: NoExpertVerdictPolicy = Field(default_factory=NoExpertVerdictPolicy)

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        _require_refs(self.evidence_refs, "final_decision.evidence_refs", self.decision_id)
        _require_refs(
            self.evidence_envelope_refs,
            "final_decision.evidence_envelope_refs",
            self.decision_id,
        )
        _require_refs(self.wcs_refs, "final_decision.wcs_refs", self.decision_id)

        candidate_ids = {candidate.candidate_id for candidate in self.candidate_set.candidates}
        criterion_ids = {criterion.criterion_id for criterion in self.candidate_set.criteria}
        comparison_ids = {comparison.comparison_id for comparison in self.comparisons}
        rank_ids = {rank.rank_id for rank in self.ranks}
        tier_ids = {tier.tier_id for tier in self.tiers}
        tie_break_ids = {tie_break.tie_break_id for tie_break in self.tie_breaks}
        uncertainty_refs = {self.uncertainty_ref}
        uncertainty_refs.update(comparison.uncertainty_ref for comparison in self.comparisons)
        uncertainty_refs.update(rank.uncertainty_ref for rank in self.ranks)
        uncertainty_refs.update(tie_break.uncertainty_ref for tie_break in self.tie_breaks)
        uncertainty_refs.update(reversal.uncertainty_ref for reversal in self.reversals)

        _require_unique(comparison_ids, "comparison_id")
        _require_unique(rank_ids, "rank_id")
        _require_unique(tier_ids, "tier_id")
        _require_unique(tie_break_ids, "tie_break_id")

        for comparison in self.comparisons:
            _require_member(comparison.left_candidate_id, candidate_ids, "left_candidate_id")
            _require_member(comparison.right_candidate_id, candidate_ids, "right_candidate_id")
            for criterion_id in comparison.criterion_ids:
                _require_member(criterion_id, criterion_ids, "comparison.criterion_ids")

        ranked_candidates = set()
        for rank in self.ranks:
            _require_member(rank.candidate_id, candidate_ids, "rank.candidate_id")
            _require_member(rank.tier_id, tier_ids, "rank.tier_id")
            for comparison_ref in rank.comparison_refs:
                _require_member(comparison_ref, comparison_ids, "rank.comparison_refs")
            for criterion_id in rank.criterion_ids:
                _require_member(criterion_id, criterion_ids, "rank.criterion_ids")
            if rank.tie_break_ref is not None:
                _require_member(rank.tie_break_ref, tie_break_ids, "rank.tie_break_ref")
            ranked_candidates.add(rank.candidate_id)

        missing_ranked_candidates = candidate_ids - ranked_candidates
        if missing_ranked_candidates:
            raise ValueError(f"unranked candidates: {sorted(missing_ranked_candidates)}")

        for tier in self.tiers:
            for rank_ref in tier.rank_refs:
                _require_member(rank_ref, rank_ids, "tier.rank_refs")

        for tie_break in self.tie_breaks:
            for rank_ref in tie_break.applies_to_rank_ids:
                _require_member(rank_ref, rank_ids, "tie_break.applies_to_rank_ids")

        for inconsistency in self.inconsistencies:
            for comparison_ref in inconsistency.comparison_refs:
                _require_member(comparison_ref, comparison_ids, "inconsistency.comparison_refs")
            for rank_ref in inconsistency.rank_refs:
                _require_member(rank_ref, rank_ids, "inconsistency.rank_refs")
            for criterion_id in inconsistency.criterion_ids:
                _require_member(criterion_id, criterion_ids, "inconsistency.criterion_ids")

        if self.bracket is not None:
            bracket_candidates = {
                candidate_id
                for match in self.bracket.matches
                for candidate_id in (match.left_candidate_id, match.right_candidate_id)
            }
            unknown_bracket_candidates = bracket_candidates - candidate_ids
            if unknown_bracket_candidates:
                raise ValueError(
                    f"unknown bracket candidates: {sorted(unknown_bracket_candidates)}"
                )
            for match in self.bracket.matches:
                _require_member(match.comparison_ref, comparison_ids, "bracket.comparison_ref")

        if self.public_private_mode in {"private", "dry_run"} and self.public_claim_allowed:
            raise ValueError("private or dry-run decisions cannot allow public claims")
        if self.public_claim_allowed and self.output_eligibility != "public_ready":
            raise ValueError("public claims require output_eligibility=public_ready")
        if self.output_eligibility == "public_ready" and not self.public_claim_allowed:
            raise ValueError("public_ready output requires public_claim_allowed=true")

        open_inconsistencies = [
            inconsistency.inconsistency_id
            for inconsistency in self.inconsistencies
            if inconsistency.resolution_state == "open"
        ]
        if self.public_claim_allowed and open_inconsistencies:
            raise ValueError(
                f"public claims cannot coexist with open inconsistencies: {open_inconsistencies}"
            )

        if not uncertainty_refs:
            raise ValueError("final decision must preserve uncertainty refs")
        return self


def final_decision_is_evidence_bound(decision: FinalDecisionRecord) -> bool:
    """Check that every outward decision surface still carries evidence and WCS refs."""

    if not decision.evidence_refs or not decision.evidence_envelope_refs or not decision.wcs_refs:
        return False
    comparison_ok = all(
        comparison.evidence_refs and comparison.evidence_envelope_refs and comparison.wcs_refs
        for comparison in decision.comparisons
    )
    rank_ok = all(
        rank.evidence_refs and rank.evidence_envelope_refs and rank.wcs_refs
        for rank in decision.ranks
    )
    reversal_ok = all(
        reversal.evidence_refs and reversal.evidence_envelope_refs and reversal.wcs_refs
        for reversal in decision.reversals
    )
    return comparison_ok and rank_ok and reversal_ok


def can_feed_grounding_evaluator(decision: FinalDecisionRecord) -> bool:
    """Return whether the decision may be scored as attempt quality, not truth."""

    if not final_decision_is_evidence_bound(decision):
        return False
    policy = decision.no_expert_verdict_policy
    if policy.authoritative_verdict_allowed or policy.domain_truth_adjudication_allowed:
        return False
    return not any(
        inconsistency.kind == "missing_evidence"
        and inconsistency.resolution_state in {"open", "refused"}
        for inconsistency in decision.inconsistencies
    )


def emit_deterministic_boundaries(
    decision: FinalDecisionRecord,
    *,
    public_event_mapping_refs: Mapping[BoundarySurface, str] | None = None,
) -> tuple[ProgrammeBoundaryEventRef, ...]:
    """Emit stable boundary refs for chapters, Shorts, replay cards, datasets, and zines."""

    refs = public_event_mapping_refs or {}
    boundaries: list[ProgrammeBoundaryEventRef] = []
    for index, surface in enumerate(BOUNDARY_SURFACES, start=1):
        mapping_ref = refs.get(surface)
        mapping_state = _mapping_state(decision.public_private_mode, mapping_ref)
        unavailable_reasons = _boundary_unavailable_reasons(
            decision.public_private_mode, mapping_ref
        )
        boundaries.append(
            ProgrammeBoundaryEventRef(
                boundary_id=f"pbe_{decision.decision_id}_{surface}_{index:03d}",
                sequence=index,
                boundary_type=BOUNDARY_TYPES[surface],
                duplicate_key=f"{decision.run_id}:{decision.decision_id}:{surface}:{index:03d}",
                cuepoint_chapter_distinction=_cuepoint_chapter_distinction(surface),
                public_event_mapping_ref=mapping_ref,
                mapping_state=mapping_state,
                unavailable_reasons=unavailable_reasons,
            )
        )
    return tuple(boundaries)


def build_run_store_events(
    decision: FinalDecisionRecord,
    boundaries: Sequence[ProgrammeBoundaryEventRef],
    *,
    occurred_at: datetime | None = None,
    producer: str = "tier_ranking_bracket_engine",
    start_sequence: int = 0,
) -> tuple[ContentProgrammeRunStoreEvent, ...]:
    """Project a final decision into append-only run-store events by reference only."""

    now = occurred_at or datetime.now(UTC)
    boundary_ids = tuple(boundary.boundary_id for boundary in boundaries)
    events: list[ContentProgrammeRunStoreEvent] = []

    def add(event_type: RankingRunStoreEventKind, payload_refs: tuple[str, ...]) -> None:
        sequence = start_sequence + len(events)
        events.append(
            ContentProgrammeRunStoreEvent(
                event_id=f"event:{decision.decision_id}:{event_type}:{sequence:03d}",
                run_id=decision.run_id,
                sequence=sequence,
                event_type=event_type,
                occurred_at=now,
                idempotency_key=f"{decision.run_id}:{decision.decision_id}:{event_type}:{sequence:03d}",
                producer=producer,
                payload_refs=payload_refs,
                evidence_refs=decision.evidence_refs,
                boundary_event_refs=boundary_ids if event_type == "boundary_emitted" else (),
                capability_outcome_refs=decision.wcs_refs,
            )
        )

    add("evidence_attached", (decision.candidate_set.candidate_set_id,))
    add("boundary_emitted", boundary_ids)
    add("claim_recorded", (decision.decision_id,))
    for reversal in decision.reversals:
        add("correction_made", (reversal.reversal_id,))

    if decision.output_eligibility in {"held", "dry_run"}:
        add("conversion_held", (decision.decision_id,))
    elif decision.output_eligibility == "blocked":
        add("blocked", (decision.decision_id,))
    else:
        add("completed", (decision.decision_id,))
    return tuple(events)


def _mapping_state(mode: PublicPrivateMode, mapping_ref: str | None) -> BoundaryMappingState:
    if mode in {"private", "dry_run"}:
        return "internal_only"
    return "research_vehicle_linked" if mapping_ref else "held"


def _boundary_unavailable_reasons(
    mode: PublicPrivateMode, mapping_ref: str | None
) -> tuple[UnavailableReason, ...]:
    if mode == "private":
        return ("private_mode",)
    if mode == "dry_run":
        return ("dry_run_mode",)
    if mapping_ref is None:
        return ("research_vehicle_public_event_missing",)
    return ()


def _cuepoint_chapter_distinction(surface: BoundarySurface) -> CuepointChapterDistinction:
    if surface == "chapter":
        return "vod_chapter_boundary"
    if surface == "shorts":
        return "live_cuepoint_candidate"
    return "none"


def _require_refs(refs: Sequence[str], field_name: str, record_id: str) -> None:
    if not tuple(refs):
        raise ValueError(f"{field_name} required for {record_id}")


def _require_unique(values: Sequence[str] | set[str], field_name: str) -> None:
    values_tuple = tuple(values)
    if len(values_tuple) != len(set(values_tuple)):
        raise ValueError(f"duplicate {field_name}")


def _require_member(value: str, allowed: set[str], field_name: str) -> None:
    if value not in allowed:
        raise ValueError(f"unknown {field_name}: {value}")
