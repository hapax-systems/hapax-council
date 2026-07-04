"""Standalone SDLC route engine for capability-aware routing.

The router is intentionally separate from the live AffordancePipeline. It reads
typed route candidates, applies requirement floors before scoring, and only
updates its Thompson posteriors from witnessed gate outcomes.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.affordance import ActivationState
from shared.gate_log import GateEvent, read_gate_events
from shared.platform_capability_registry import SupplyVector

DEFAULT_SDLC_ROUTER_STATE = Path(
    os.environ.get(
        "HAPAX_SDLC_ROUTER_STATE",
        str(Path.home() / ".cache" / "hapax" / "sdlc-routing" / "router-state.json"),
    )
)
DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID = "codex.headless.full"
DEFAULT_THOMPSON_GAMMA = 0.9999

REQUIREMENT_VECTOR_DIMENSIONS = (
    "quality_floor",
    "information_scope",
    "context_length",
    "mutation_risk",
    "verification_demand",
    "ambiguity_novelty",
    "composition_coupling",
    "governance_sensitivity",
)
_REQUIREMENT_VECTOR_NEXT_ACTION = (
    "next action: provide requirement_vector as a mapping with all eight dimensions: "
    + ", ".join(REQUIREMENT_VECTOR_DIMENSIONS)
)
_REQUIREMENT_SCORE_NEXT_ACTION = (
    "next action: set each requirement_vector score to a strict integer from 0 through 5"
)
_CANDIDATE_CAPABILITY_NEXT_ACTION = (
    "next action: provide candidate capability_scores and capability_confidence as mappings "
    "keyed by non-quality requirement dimensions with strict integer scores from 0 through 5"
)
HARD_ACTIVATION_DIMENSIONS = ("information_scope", "context_length")
LEARNING_GATE_TYPES = frozenset(
    {"deterministic", "gold_verifier", "llm_acceptor", "frontier_review"}
)
LEARNING_GATE_RESULTS = frozenset({"accept", "reject"})

_REQUIREMENT_TO_SUPPLY_SCORES: Mapping[str, tuple[str, ...]] = {
    "information_scope": ("grounding", "current_docs_grounding"),
    "context_length": ("long_context",),
    "mutation_risk": ("source_editing", "architecture", "governance_reasoning"),
    "verification_demand": ("test_authoring", "multimodal_verification"),
    "ambiguity_novelty": ("ambiguity_resolution", "architecture"),
    "composition_coupling": ("coordination_reliability", "architecture"),
    "governance_sensitivity": (
        "governance_reasoning",
        "privacy_safety",
        "public_claim_safety",
    ),
}


class SdlcRouterAction(StrEnum):
    ROUTE = "route"
    SHADOW = "shadow"
    HOLD = "hold"


class _RouterModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SdlcRoutingRequest(_RouterModel):
    """The task-side facts the router is allowed to use."""

    task_id: str
    routing_class: str
    requirement_vector: dict[str, int] = Field(default_factory=dict)
    quality_floor: str = "frontier_required"
    mutation_surface: str = "source"
    authority_level: str = "authoritative"
    frontier_incumbent_route_id: str = DEFAULT_FRONTIER_INCUMBENT_ROUTE_ID

    @field_validator("requirement_vector", mode="before")
    @classmethod
    def _requirement_vector_uses_strict_int_scores(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            raise ValueError(
                f"requirement_vector must be a mapping; {_REQUIREMENT_VECTOR_NEXT_ACTION}"
            )
        for score in value.values():
            if isinstance(score, bool) or not isinstance(score, int):
                raise ValueError(
                    "requirement_vector scores must be strict integers 0..5; "
                    f"{_REQUIREMENT_SCORE_NEXT_ACTION}"
                )
        return value

    @model_validator(mode="after")
    def _requirement_vector_scores_are_bounded(self) -> SdlcRoutingRequest:
        missing_dimensions = tuple(
            dimension
            for dimension in REQUIREMENT_VECTOR_DIMENSIONS
            if dimension not in self.requirement_vector
        )
        if missing_dimensions:
            raise ValueError(
                "requirement_vector missing dimensions: "
                + ",".join(missing_dimensions)
                + f"; {_REQUIREMENT_VECTOR_NEXT_ACTION}"
            )
        for dimension, score in self.requirement_vector.items():
            if dimension not in REQUIREMENT_VECTOR_DIMENSIONS:
                raise ValueError(
                    f"unknown requirement_vector dimension: {dimension}; "
                    f"{_REQUIREMENT_VECTOR_NEXT_ACTION}"
                )
            if isinstance(score, bool) or score < 0 or score > 5:
                raise ValueError(
                    f"requirement_vector scores must be integers 0..5; "
                    f"{_REQUIREMENT_SCORE_NEXT_ACTION}"
                )
        return self


class ClassActivationEvidence(_RouterModel):
    """Per-class readiness evidence for authoritative non-frontier routing."""

    routing_class: str
    information_scope_value_count: int = Field(default=0, ge=0)
    context_length_value_count: int = Field(default=0, ge=0)
    floor_checker_live: bool = False
    floor_checker_ref: str | None = None
    evidence_refs: tuple[str, ...] = Field(default=())

    @property
    def active(self) -> bool:
        return (
            self.information_scope_value_count >= 1
            and self.context_length_value_count >= 1
            and self.floor_checker_live
        )

    @property
    def reason_codes(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if self.information_scope_value_count < 1:
            reasons.append("missing_d2_information_scope_value")
        if self.context_length_value_count < 1:
            reasons.append("missing_d3_context_length_value")
        if not self.floor_checker_live:
            reasons.append("floor_checker_not_live")
        return tuple(reasons)


class SdlcRouteCandidate(_RouterModel):
    """One route candidate after registry/policy projection."""

    route_id: str
    active: bool = True
    blocked_reasons: tuple[str, ...] = Field(default=())
    supported_quality_floors: tuple[str, ...] = Field(default=())
    supported_mutation_surfaces: tuple[str, ...] = Field(default=())
    authority_ceiling: str = "support_only"
    capability_scores: dict[str, int] = Field(default_factory=dict)
    capability_confidence: dict[str, int] = Field(default_factory=dict)
    evidence_refs: tuple[str, ...] = Field(default=())
    historical_class_score: int | None = Field(default=None, ge=0, le=5)
    historical_class_confidence: int = Field(default=0, ge=0, le=5)
    historical_evidence_refs: tuple[str, ...] = Field(default=())

    @field_validator("capability_scores", "capability_confidence", mode="before")
    @classmethod
    def _capability_maps_use_strict_bounded_scores(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            raise ValueError(
                f"candidate capability maps must be mappings; {_CANDIDATE_CAPABILITY_NEXT_ACTION}"
            )
        allowed_dimensions = set(REQUIREMENT_VECTOR_DIMENSIONS) - {"quality_floor"}
        for dimension, score in value.items():
            if dimension not in allowed_dimensions:
                raise ValueError(
                    f"unknown candidate capability dimension: {dimension}; "
                    f"{_CANDIDATE_CAPABILITY_NEXT_ACTION}"
                )
            if isinstance(score, bool) or not isinstance(score, int) or score < 0 or score > 5:
                raise ValueError(
                    "candidate capability scores must be strict integers 0..5; "
                    f"{_CANDIDATE_CAPABILITY_NEXT_ACTION}"
                )
        return value

    @classmethod
    def from_supply_vector(
        cls,
        supply: SupplyVector,
        *,
        routing_class: str,
        active: bool = True,
        blocked_reasons: Sequence[str] = (),
    ) -> SdlcRouteCandidate:
        scores = _requirement_scores_from_supply(supply)
        confidence = _requirement_confidence_from_supply(supply)
        evidence_refs = _requirement_evidence_refs_from_supply(supply)
        class_score = supply.historical_performance.class_posteriors.get(routing_class)
        return cls(
            route_id=supply.route.route_id,
            active=active,
            blocked_reasons=tuple(blocked_reasons),
            supported_quality_floors=tuple(
                floor.value if hasattr(floor, "value") else str(floor)
                for floor in supply.authority.supported_quality_floors
            ),
            supported_mutation_surfaces=tuple(supply.authority.supported_mutation_surfaces),
            authority_ceiling=supply.authority.ceiling,
            capability_scores=scores,
            capability_confidence=confidence,
            evidence_refs=evidence_refs,
            historical_class_score=class_score.score if class_score is not None else None,
            historical_class_confidence=class_score.confidence if class_score is not None else 0,
            historical_evidence_refs=tuple(class_score.evidence_refs)
            if class_score is not None
            else (),
        )


class RequirementFloorVeto(_RouterModel):
    route_id: str
    reason_codes: tuple[str, ...]


class SdlcCandidateScore(_RouterModel):
    route_id: str
    requirement_fit: float
    historical_fit: float
    thompson_sample: float
    aggregate_score: float
    evidence_refs: tuple[str, ...] = Field(default=())


class SdlcRouteDecision(_RouterModel):
    decision_schema: Literal[1] = 1
    task_id: str
    routing_class: str
    action: SdlcRouterAction
    selected_route_id: str | None
    shadow_route_id: str | None = None
    frontier_incumbent_route_id: str
    reason_codes: tuple[str, ...]
    candidate_scores: tuple[SdlcCandidateScore, ...] = Field(default=())
    vetoes: tuple[RequirementFloorVeto, ...] = Field(default=())
    class_activation: ClassActivationEvidence
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def route_allowed(self) -> bool:
        return self.action is SdlcRouterAction.ROUTE and self.selected_route_id is not None


class SdlcRouterState(_RouterModel):
    state_schema: Literal[1] = 1
    route_posteriors: dict[str, dict[str, ActivationState]] = Field(default_factory=dict)
    applied_gate_event_hashes: list[str] = Field(default_factory=list)

    def posterior_for_read(self, routing_class: str, route_id: str) -> ActivationState:
        return self.route_posteriors.get(routing_class, {}).get(route_id, ActivationState())

    def posterior_for_update(self, routing_class: str, route_id: str) -> ActivationState:
        per_class = self.route_posteriors.setdefault(routing_class, {})
        state = per_class.get(route_id)
        if state is None:
            state = ActivationState()
            per_class[route_id] = state
        return state


class SdlcRouter:
    """Feasibility-first, per-class activation-gated route selector."""

    def __init__(
        self,
        *,
        state: SdlcRouterState | None = None,
        activation_evidence: Mapping[str, ClassActivationEvidence] | None = None,
        thompson_sampler: Callable[[ActivationState], float] | None = None,
        gamma: float = DEFAULT_THOMPSON_GAMMA,
        judge_promotion: JudgePromotionDecision | None = None,
    ) -> None:
        self.state = state or SdlcRouterState()
        self.activation_evidence = dict(activation_evidence or {})
        self._thompson_sampler = thompson_sampler or (lambda state: state.thompson_sample())
        self.gamma = gamma
        # Judge-health promotion evidence (cost-capture phase 0). Default None is
        # the FAIL-CLOSED state: with no cleared JudgePromotionDecision, verdicts
        # from the LLM acceptor judge may never move Thompson posteriors — the
        # measured false-accept skew (docs/research/2026-06-14-local-judge-validation.md:
        # 239 false-accepts vs 145 false-rejects, kappa 0.703) would otherwise
        # systematically inflate route posteriors toward promotion.
        self.judge_promotion = judge_promotion

    @classmethod
    def load(
        cls,
        path: Path | str = DEFAULT_SDLC_ROUTER_STATE,
        *,
        activation_evidence: Mapping[str, ClassActivationEvidence] | None = None,
        thompson_sampler: Callable[[ActivationState], float] | None = None,
        gamma: float = DEFAULT_THOMPSON_GAMMA,
    ) -> SdlcRouter:
        target = Path(path)
        if not target.exists():
            return cls(
                activation_evidence=activation_evidence,
                thompson_sampler=thompson_sampler,
                gamma=gamma,
            )
        state = SdlcRouterState.model_validate_json(target.read_text(encoding="utf-8"))
        return cls(
            state=state,
            activation_evidence=activation_evidence,
            thompson_sampler=thompson_sampler,
            gamma=gamma,
        )

    def save(self, path: Path | str = DEFAULT_SDLC_ROUTER_STATE) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            self.state.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        return target

    def route(
        self,
        request: SdlcRoutingRequest,
        candidates: Iterable[SdlcRouteCandidate],
    ) -> SdlcRouteDecision:
        candidate_list = tuple(candidates)
        feasible, vetoes = _feasible_candidates(request, candidate_list)
        scores = tuple(self._score_candidate(request, candidate) for candidate in feasible)
        scores = tuple(
            sorted(
                scores,
                key=lambda score: (-score.aggregate_score, score.route_id),
            )
        )
        activation = self.activation_evidence.get(
            request.routing_class,
            ClassActivationEvidence(routing_class=request.routing_class),
        )

        if not activation.active:
            frontier_score = next(
                (
                    score
                    for score in scores
                    if score.route_id == request.frontier_incumbent_route_id
                ),
                None,
            )
            shadow = _best_non_frontier(scores, request.frontier_incumbent_route_id)
            if frontier_score is None:
                return SdlcRouteDecision(
                    task_id=request.task_id,
                    routing_class=request.routing_class,
                    action=SdlcRouterAction.HOLD,
                    selected_route_id=None,
                    shadow_route_id=shadow.route_id if shadow else None,
                    frontier_incumbent_route_id=request.frontier_incumbent_route_id,
                    reason_codes=(
                        "class_activation_gate_not_clear",
                        *activation.reason_codes,
                        "frontier_incumbent_not_feasible",
                    ),
                    candidate_scores=scores,
                    vetoes=vetoes,
                    class_activation=activation,
                )
            return SdlcRouteDecision(
                task_id=request.task_id,
                routing_class=request.routing_class,
                action=SdlcRouterAction.SHADOW,
                selected_route_id=request.frontier_incumbent_route_id,
                shadow_route_id=shadow.route_id if shadow else None,
                frontier_incumbent_route_id=request.frontier_incumbent_route_id,
                reason_codes=(
                    "class_activation_gate_not_clear",
                    *activation.reason_codes,
                    "frontier_incumbent_selected",
                ),
                candidate_scores=scores,
                vetoes=vetoes,
                class_activation=activation,
            )

        if not scores:
            return SdlcRouteDecision(
                task_id=request.task_id,
                routing_class=request.routing_class,
                action=SdlcRouterAction.HOLD,
                selected_route_id=None,
                frontier_incumbent_route_id=request.frontier_incumbent_route_id,
                reason_codes=("no_feasible_route_candidates",),
                vetoes=vetoes,
                class_activation=activation,
            )

        winner = scores[0]
        return SdlcRouteDecision(
            task_id=request.task_id,
            routing_class=request.routing_class,
            action=SdlcRouterAction.ROUTE,
            selected_route_id=winner.route_id,
            frontier_incumbent_route_id=request.frontier_incumbent_route_id,
            reason_codes=("class_activation_gate_clear", "requirement_floor_satisfied"),
            candidate_scores=scores,
            vetoes=vetoes,
            class_activation=activation,
        )

    def record_gate_event(self, event: GateEvent) -> bool:
        """Update posteriors from a witnessed gate result, never from selection."""

        if event.gate_type == "llm_acceptor" and not (
            self.judge_promotion is not None and self.judge_promotion.allowed
        ):
            # Refusal path (costcap phase 0 AC): an UNVALIDATED judge's verdicts are
            # noise in BOTH directions (accept AND reject) — neither may move a
            # posterior until the judge-health gate clears on a council-distribution
            # held set. Deterministic/gold_verifier/frontier_review gates are not
            # the LLM judge and learn as before.
            return False
        if (
            event.gate_type not in LEARNING_GATE_TYPES
            or event.gate_result not in LEARNING_GATE_RESULTS
            or event.provenance != "witnessed"  # only a WITNESSED verdict moves the Beta
            or not gate_event_thompson_update_allowed(event)
        ):
            return False
        event_hash = gate_event_hash(event)
        if event_hash in self.state.applied_gate_event_hashes:
            return False
        posterior = self.state.posterior_for_update(event.routing_class, event.route)
        if event.gate_result == "accept":
            posterior.record_success(gamma=self.gamma)
        else:
            posterior.record_failure(gamma=self.gamma)
        self.state.applied_gate_event_hashes.append(event_hash)
        return True

    def ingest_gate_events(
        self,
        *,
        path: Path | str | None = None,
        events: Iterable[GateEvent] | None = None,
    ) -> int:
        source = events if events is not None else read_gate_events(path=path)
        return sum(1 for event in source if self.record_gate_event(event))

    def _score_candidate(
        self,
        request: SdlcRoutingRequest,
        candidate: SdlcRouteCandidate,
    ) -> SdlcCandidateScore:
        dims = _scored_requirement_dimensions(request.requirement_vector)
        fit_values = [candidate.capability_scores[dimension] for dimension in dims]
        requirement_fit = sum(fit_values) / max(len(fit_values), 1)
        historical_fit = (
            float(candidate.historical_class_score)
            if candidate.historical_class_score is not None
            else 0.0
        )
        posterior = self.state.posterior_for_read(request.routing_class, candidate.route_id)
        thompson = self._thompson_sampler(posterior)
        aggregate = round(requirement_fit + historical_fit + thompson, 6)
        return SdlcCandidateScore(
            route_id=candidate.route_id,
            requirement_fit=round(requirement_fit, 6),
            historical_fit=round(historical_fit, 6),
            thompson_sample=round(thompson, 6),
            aggregate_score=aggregate,
            evidence_refs=tuple(
                dict.fromkeys([*candidate.evidence_refs, *candidate.historical_evidence_refs])
            ),
        )


def gate_event_hash(event: GateEvent) -> str:
    payload = event.model_dump(mode="json")
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def gate_event_learning_allowed(event: GateEvent) -> bool:
    eligibility = event.learning_eligibility
    if eligibility is None:
        return False
    if not (eligibility.thompson_update_allowed or eligibility.local_posterior_update_allowed):
        return False
    return _gate_event_learning_evidence_complete(event)


def gate_event_thompson_update_allowed(event: GateEvent) -> bool:
    eligibility = event.learning_eligibility
    if eligibility is None:
        return False
    if not eligibility.thompson_update_allowed:
        return False
    return _gate_event_learning_evidence_complete(event)


def _gate_event_learning_evidence_complete(event: GateEvent) -> bool:
    if not event.task_hash.strip():
        return False
    if not event.route.strip():
        return False
    if not event.routing_class.strip():
        return False
    return _gate_event_requirement_vector_is_complete(event.requirement_vector)


def _gate_event_requirement_vector_is_complete(
    requirement_vector: Mapping[str, object],
) -> bool:
    if set(requirement_vector) != set(REQUIREMENT_VECTOR_DIMENSIONS):
        return False
    return all(
        not isinstance(score, bool) and isinstance(score, int) and 0 <= score <= 5
        for score in requirement_vector.values()
    )


def requirement_floor_veto(
    request: SdlcRoutingRequest,
    candidate: SdlcRouteCandidate,
) -> RequirementFloorVeto | None:
    reasons: list[str] = []
    if not candidate.active:
        reasons.append("route_inactive")
    reasons.extend(candidate.blocked_reasons)
    if request.quality_floor not in candidate.supported_quality_floors:
        reasons.append(f"quality_floor_not_supported:{request.quality_floor}")
    if not _authority_satisfies(request.authority_level, candidate.authority_ceiling):
        reasons.append(f"authority_ceiling_not_satisfied:{candidate.authority_ceiling}")
    if (
        request.mutation_surface != "none"
        and request.mutation_surface not in candidate.supported_mutation_surfaces
    ):
        reasons.append(f"mutation_surface_not_supported:{request.mutation_surface}")

    for dimension, demand in request.requirement_vector.items():
        if dimension == "quality_floor" or demand <= 0:
            continue
        supply = candidate.capability_scores.get(dimension)
        if supply is None:
            reasons.append(f"requirement_floor_missing:{dimension}")
        elif supply < demand:
            reasons.append(f"requirement_floor_not_satisfied:{dimension}:{supply}<{demand}")

    if not reasons:
        return None
    return RequirementFloorVeto(route_id=candidate.route_id, reason_codes=tuple(reasons))


def _authority_satisfies(authority_level: str, authority_ceiling: str) -> bool:
    if authority_level == "authoritative":
        return authority_ceiling == "authoritative"
    if authority_level == "support_non_authoritative":
        return authority_ceiling in {
            "authoritative",
            "frontier_review_required",
            "support_only",
            "read_only",
        }
    if authority_level in {"evidence_receipt", "relay_only"}:
        return authority_ceiling in {
            "authoritative",
            "frontier_review_required",
            "support_only",
            "read_only",
        }
    return False


def _feasible_candidates(
    request: SdlcRoutingRequest,
    candidates: Sequence[SdlcRouteCandidate],
) -> tuple[tuple[SdlcRouteCandidate, ...], tuple[RequirementFloorVeto, ...]]:
    feasible: list[SdlcRouteCandidate] = []
    vetoes: list[RequirementFloorVeto] = []
    for candidate in candidates:
        veto = requirement_floor_veto(request, candidate)
        if veto is None:
            feasible.append(candidate)
        else:
            vetoes.append(veto)
    return tuple(feasible), tuple(vetoes)


def _best_non_frontier(
    scores: Sequence[SdlcCandidateScore],
    frontier_incumbent_route_id: str,
) -> SdlcCandidateScore | None:
    for score in scores:
        if score.route_id != frontier_incumbent_route_id:
            return score
    return None


def _scored_requirement_dimensions(requirement_vector: Mapping[str, int]) -> tuple[str, ...]:
    return tuple(
        dimension
        for dimension in REQUIREMENT_VECTOR_DIMENSIONS
        if dimension != "quality_floor" and requirement_vector.get(dimension, 0) > 0
    )


def _requirement_scores_from_supply(supply: SupplyVector) -> dict[str, int]:
    raw_scores = supply.capability_scores.model_dump()
    out: dict[str, int] = {}
    for requirement_dimension, supply_dimensions in _REQUIREMENT_TO_SUPPLY_SCORES.items():
        values = [
            int(raw_scores[dimension]["score"])
            for dimension in supply_dimensions
            if dimension in raw_scores
        ]
        if values:
            out[requirement_dimension] = min(values)
    return out


def _requirement_confidence_from_supply(supply: SupplyVector) -> dict[str, int]:
    raw_scores = supply.capability_scores.model_dump()
    out: dict[str, int] = {}
    for requirement_dimension, supply_dimensions in _REQUIREMENT_TO_SUPPLY_SCORES.items():
        values = [
            int(raw_scores[dimension]["confidence"])
            for dimension in supply_dimensions
            if dimension in raw_scores
        ]
        if values:
            out[requirement_dimension] = min(values)
    return out


def _requirement_evidence_refs_from_supply(supply: SupplyVector) -> tuple[str, ...]:
    raw_scores = supply.capability_scores.model_dump()
    refs: list[str] = []
    for supply_dimensions in _REQUIREMENT_TO_SUPPLY_SCORES.values():
        for dimension in supply_dimensions:
            if dimension in raw_scores:
                refs.extend(raw_scores[dimension].get("evidence_refs") or [])
    return tuple(dict.fromkeys(refs))


# --- judge health — cost-capture phase 0 (false-accept skew gate) ---------------------
# Task 20260628-costcap-phase0-fix-judge-validation-skew-false-accept. The local
# answer-verification judge (CompassVerifier-7B, shared/local_judge.py) measured
# NON-conservative on the VerifierBench held set: 239 false-accepts (judge says
# CORRECT where the authoritative reference says INCORRECT/INVALID — the dangerous
# direction for a gate) vs 145 false-rejects, agreement 83.8%, Cohen's kappa 0.703
# (docs/research/2026-06-14-local-judge-validation.md). Every shadow->authoritative
# offload flip (costcap phase 1) MUST pass ``authoritative_flip_allowed`` first; the
# gate holds fail-closed until the AC3 request threshold clears on the judge's own
# council-distribution shadow traffic.

#: The shadow log ``shared.local_judge.shadow_compare`` appends to — the
#: council-distribution held set the promotion gate is evaluated from.
DEFAULT_JUDGE_SHADOW_LOG = Path(
    os.environ.get(
        "HAPAX_JUDGE_SHADOW_LOG",
        str(Path.home() / ".cache" / "hapax" / "local-judge-shadow.jsonl"),
    )
)

_JUDGE_LABELS = ("A", "B", "C")


class JudgeHealthMeasure(_RouterModel):
    """False-accept/false-reject measurement over a held set of verdict pairs."""

    n_pairs: int
    n_scored: int
    n_excluded: int
    agreement: float | None
    cohen_kappa: float | None
    false_accept_count: int
    false_reject_count: int
    disagreement_count: int
    conservative_skewed: bool


class JudgeHealthThresholds(_RouterModel):
    """The AC3 request threshold (REQ-20260613-sdlc-cost-offload-program, carried by
    REQ-20260628-internal-cost-capture-dogfood): >=150 council-distribution items,
    agreement >=90%, Cohen's kappa >=0.80, disagreements conservative-skewed."""

    min_scored_items: int = 150
    min_agreement: float = 0.90
    min_kappa: float = 0.80
    require_conservative_skew: bool = True


DEFAULT_JUDGE_HEALTH_THRESHOLDS = JudgeHealthThresholds()


class JudgePromotionDecision(_RouterModel):
    """The fail-closed verdict on whether judge verdicts may carry authority."""

    allowed: bool
    reason_codes: tuple[str, ...]
    measure: JudgeHealthMeasure
    thresholds: JudgeHealthThresholds


def _judge_cohen_kappa(gold: Sequence[str], pred: Sequence[str]) -> float:
    """Three-label Cohen's kappa, same convention as scripts/cost-offload/analyze.py
    (the harness behind the pinned validation report), so held-set reproductions
    match the published numbers exactly."""
    n = len(gold)
    po = sum(g == p for g, p in zip(gold, pred, strict=True)) / n
    pe = 0.0
    for label in _JUDGE_LABELS:
        gold_marginal = sum(1 for g in gold if g == label) / n
        pred_marginal = sum(1 for p in pred if p == label) / n
        pe += gold_marginal * pred_marginal
    # pe == 1 requires both marginals concentrated on one label, which forces po == 1;
    # analyze.py returns 1.0 for that degenerate case and we mirror it.
    return (po - pe) / (1 - pe) if (1 - pe) else 1.0


def measure_judge_health(pairs: Iterable[tuple[str, str]]) -> JudgeHealthMeasure:
    """Measure agreement, kappa, and the false-accept/false-reject split over a held
    set of ``(local, authoritative)`` verdict pairs (the ``shadow_compare`` schema).

    A pair with either label outside A/B/C is EXCLUDED from the metrics (an
    unparseable local verdict is a judge failure/escalation, not agreement) but
    stays visible in ``n_pairs``/``n_excluded`` — exclusion is counted, never silent.
    ``conservative_skewed`` is False on an empty set (fail-closed) and otherwise
    requires false-accepts to be absent or strictly fewer than false-rejects —
    the validation report's operationalization (239 > 145 -> not met).
    """
    all_pairs = tuple(pairs)
    scored = [
        (local, authoritative)
        for local, authoritative in all_pairs
        if local in _JUDGE_LABELS and authoritative in _JUDGE_LABELS
    ]
    n_scored = len(scored)
    false_accept = sum(1 for local, auth in scored if local == "A" and auth in ("B", "C"))
    false_reject = sum(1 for local, auth in scored if auth == "A" and local in ("B", "C"))
    disagreements = sum(1 for local, auth in scored if local != auth)
    agreement = (n_scored - disagreements) / n_scored if n_scored else None
    kappa = (
        _judge_cohen_kappa(
            [auth for _, auth in scored],
            [local for local, _ in scored],
        )
        if n_scored
        else None
    )
    return JudgeHealthMeasure(
        n_pairs=len(all_pairs),
        n_scored=n_scored,
        n_excluded=len(all_pairs) - n_scored,
        agreement=agreement,
        cohen_kappa=kappa,
        false_accept_count=false_accept,
        false_reject_count=false_reject,
        disagreement_count=disagreements,
        conservative_skewed=bool(n_scored) and (false_accept == 0 or false_accept < false_reject),
    )


def load_judge_shadow_pairs(path: Path | str | None = None) -> tuple[tuple[str, str], ...]:
    """Read ``(local, authoritative)`` pairs from the shadow-compare jsonl log.

    A corrupt or malformed row becomes an excluded ``("", "")`` pair — it degrades
    the measure visibly instead of silently shrinking the held set. A missing log
    yields no pairs (and the promotion gate then refuses on the empty set)."""
    target = Path(os.path.expanduser(str(path if path is not None else DEFAULT_JUDGE_SHADOW_LOG)))
    if not target.exists():
        return ()
    out: list[tuple[str, str]] = []
    with target.open(encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                out.append(("", ""))
                continue
            local = row.get("local") if isinstance(row, Mapping) else None
            authoritative = row.get("authoritative") if isinstance(row, Mapping) else None
            if isinstance(local, str) and isinstance(authoritative, str):
                out.append((local, authoritative))
            else:
                out.append(("", ""))
    return tuple(out)


def judge_promotion_gate(
    measure: JudgeHealthMeasure,
    thresholds: JudgeHealthThresholds = DEFAULT_JUDGE_HEALTH_THRESHOLDS,
) -> JudgePromotionDecision:
    """Evaluate a held-set measure against the request threshold — fail-closed.

    Every failing bar is surfaced as its own reason code so an operator can see
    exactly which promotion requirement is unmet (executive_function: errors
    include next actions — the reason names the floor and the measured value)."""
    reasons: list[str] = []
    if measure.n_scored == 0:
        reasons.append("judge_held_set_missing")
    elif measure.n_scored < thresholds.min_scored_items:
        reasons.append(
            f"judge_held_set_insufficient:{measure.n_scored}<{thresholds.min_scored_items}"
        )
    if measure.n_scored > 0:
        if measure.agreement is not None and measure.agreement < thresholds.min_agreement:
            reasons.append(
                f"judge_agreement_below_floor:{measure.agreement:.4f}<{thresholds.min_agreement}"
            )
        if measure.cohen_kappa is not None and measure.cohen_kappa < thresholds.min_kappa:
            reasons.append(
                f"judge_kappa_below_floor:{measure.cohen_kappa:.4f}<{thresholds.min_kappa}"
            )
        if thresholds.require_conservative_skew and not measure.conservative_skewed:
            reasons.append(
                "judge_not_conservative_skewed:"
                f"false_accept={measure.false_accept_count}"
                f">=false_reject={measure.false_reject_count}"
            )
    return JudgePromotionDecision(
        allowed=not reasons,
        reason_codes=tuple(reasons),
        measure=measure,
        thresholds=thresholds,
    )


def authoritative_flip_allowed(
    *,
    log_path: Path | str | None = None,
    thresholds: JudgeHealthThresholds = DEFAULT_JUDGE_HEALTH_THRESHOLDS,
) -> JudgePromotionDecision:
    """THE gate a shadow->authoritative offload flip must pass (costcap phase 1).

    Fail-closed end to end: a missing/empty/corrupt shadow log, an insufficient
    held set, or any unmet bar refuses the flip with explicit reason codes."""
    return judge_promotion_gate(measure_judge_health(load_judge_shadow_pairs(log_path)), thresholds)
