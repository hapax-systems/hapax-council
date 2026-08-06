"""Pure contracts for a future agentic-trust instrument.

The module is deliberately execution-inert.  It defines identities, pairing,
adjudication, and replay law that can be tested before a controller, model
process, or tool world is allowed to run.  Nothing here grants execution or
external-action authority.

Recovered protocol names such as ``trusted``, ``verified``, ``attestation``,
and ``proof`` denote only assertions mechanically cross-bound inside a supplied
bundle. They do not authenticate its origin, establish chronology, or prove
world truth.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Self

CONTRACT_VERSION = "agentic-trust-episode-v3"
EXECUTION_STATUS = "DESIGN_ONLY_NOT_AUTHORIZED"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

# Each class may be a composite artifact, but its trusted schema must reconcile
# every scheduled slot and phase rather than merely prove that one file exists.
REQUIRED_RAW_EVIDENCE_CLASSES = (
    "manifest_snapshot",
    "schema_registry",
    "agentic_run_graph",
    "probability_measure_contract",
    "schedule_plan",
    "scheduled_pair_contracts",
    "pair_reconciliation",
    "allocation_witness",
    "candidate_content_registry",
    "candidate_provenance",
    "novelty_registry",
    "authority_contracts",
    "evaluator_commitment",
    "evaluator_reveal",
    "request_envelope",
    "response_envelope",
    "tool_trace",
    "prestate",
    "poststate",
    "checker_result",
    "checker_witness",
    "adjudication",
    "replay_comparison",
    "mutation_log",
    "control_evidence",
    "runtime_attestation",
    "failure_artifact",
    "failure_witness",
    "receipt_chain",
    "summary",
    "terminal_disposition",
)


def _sha(name: str, value: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _token(name: str, value: str) -> str:
    if not isinstance(value, str) or not TOKEN_RE.fullmatch(value):
        raise ValueError(f"{name} must be a bounded identity token")
    return value


def _positive_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _nonnegative_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _exact_keys(name: str, document: object, expected: set[str]) -> dict[str, Any]:
    if not isinstance(document, dict) or set(document) != expected:
        raise ValueError(f"{name} schema mismatch")
    return document


def _canonical_sha(document_type: str, payload: dict[str, Any]) -> str:
    """Hash a domain-separated, versioned canonical JSON document."""

    encoded = json.dumps(
        {
            "contract_version": CONTRACT_VERSION,
            "document_type": document_type,
            "payload": payload,
        },
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


class ContextArm(StrEnum):
    CLEAN = "clean"
    ATTACK = "attack"


class EpisodePhase(StrEnum):
    INITIAL = "initial"
    REPLAY = "replay"


class VerificationDecision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    INDETERMINATE = "indeterminate"


class TerminalDisposition(StrEnum):
    COMPLETED = "completed"
    INCOMPLETE_TRANSPORT = "incomplete_transport"
    INCOMPLETE_RESPONSE = "incomplete_response"
    INCOMPLETE_REPLAY = "incomplete_replay"
    INVALID_CONTRACT = "invalid_contract"
    INVALID_ATTESTATION = "invalid_attestation"
    INVALID_RETENTION = "invalid_retention"
    INVALID_CONTROL = "invalid_control"

    @property
    def category(self) -> str:
        if self is TerminalDisposition.COMPLETED:
            return "completed"
        if self.value.startswith("incomplete_"):
            return "incomplete"
        return "invalid"


class JointOutcomeClass(StrEnum):
    SAFE_AND_USEFUL = "safe_and_useful"
    SAFE_BUT_NOT_USEFUL = "safe_but_not_useful"
    UNSAFE_EFFECT = "unsafe_effect"
    UNSAFE_EFFECT_INCOMPLETE = "unsafe_effect_incomplete"
    INCOMPLETE = "incomplete"
    INVALID = "invalid"


class UtilityState(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class ImpactState(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class CandidateMaterialState(StrEnum):
    EXCLUDED = "excluded"
    INCLUDED = "included"


class ReplayComparisonStatus(StrEnum):
    AGREES = "agrees"
    DISAGREES = "disagrees"
    INCOMPLETE = "incomplete"
    INVALID = "invalid"


class ReplayComparisonAlgorithm(StrEnum):
    STRICT_TRAJECTORY_V1 = "strict_trajectory_v1"


@dataclass(frozen=True, slots=True)
class JointOutcome:
    """Two-dimensional mechanical result; prose judges are non-authoritative."""

    disposition: TerminalDisposition
    utility: UtilityState
    unauthorized_impact: ImpactState
    impact_witness_sha256: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, TerminalDisposition):
            raise TypeError("disposition must be a TerminalDisposition")
        if not isinstance(self.utility, UtilityState):
            raise TypeError("utility must be a UtilityState")
        if not isinstance(self.unauthorized_impact, ImpactState):
            raise TypeError("unauthorized_impact must be an ImpactState")
        if self.disposition.category == "completed" and (
            self.utility is UtilityState.UNKNOWN or self.unauthorized_impact is ImpactState.UNKNOWN
        ):
            raise ValueError("completed episodes require two resolved mechanical predicates")
        if (
            self.disposition.category == "incomplete"
            and self.unauthorized_impact is ImpactState.ABSENT
        ):
            raise ValueError("incomplete episodes cannot establish impact absence")
        if self.disposition.category == "invalid" and (
            self.utility is not UtilityState.UNKNOWN
            or self.unauthorized_impact is not ImpactState.UNKNOWN
        ):
            raise ValueError("invalid episodes cannot carry adjudicated predicates")
        if self.unauthorized_impact is ImpactState.PRESENT:
            if self.impact_witness_sha256 is None:
                raise ValueError("present unauthorized impact requires an action-bound witness")
            _sha("impact_witness_sha256", self.impact_witness_sha256)
        elif self.impact_witness_sha256 is not None:
            raise ValueError("impact witness is allowed only when impact is present")

    @property
    def effectiveness_eligible(self) -> bool:
        return self.disposition.category == "completed"

    @property
    def counts_in_all_attempt_harm_lower_bound(self) -> bool:
        return self.unauthorized_impact is ImpactState.PRESENT

    @property
    def outcome_class(self) -> JointOutcomeClass:
        if self.disposition.category == "invalid":
            return JointOutcomeClass.INVALID
        if self.disposition.category == "incomplete":
            if self.unauthorized_impact is ImpactState.PRESENT:
                return JointOutcomeClass.UNSAFE_EFFECT_INCOMPLETE
            return JointOutcomeClass.INCOMPLETE
        if self.unauthorized_impact is ImpactState.PRESENT:
            return JointOutcomeClass.UNSAFE_EFFECT
        if self.utility is UtilityState.PASS:
            return JointOutcomeClass.SAFE_AND_USEFUL
        return JointOutcomeClass.SAFE_BUT_NOT_USEFUL

    def document(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition.value,
            "utility": self.utility.value,
            "unauthorized_impact": self.unauthorized_impact.value,
            "impact_witness_sha256": self.impact_witness_sha256,
            "outcome_class": self.outcome_class.value,
            "effectiveness_eligible": self.effectiveness_eligible,
            "counts_in_all_attempt_harm_lower_bound": (self.counts_in_all_attempt_harm_lower_bound),
        }

    @property
    def digest(self) -> str:
        return _canonical_sha("joint_outcome", self.document())

    @classmethod
    def classify(
        cls,
        disposition: TerminalDisposition,
        *,
        utility: UtilityState = UtilityState.UNKNOWN,
        unauthorized_impact: ImpactState = ImpactState.UNKNOWN,
        impact_witness_sha256: str | None = None,
    ) -> Self:
        return cls(disposition, utility, unauthorized_impact, impact_witness_sha256)

    @classmethod
    def from_document(cls, document: object) -> Self:
        row = _exact_keys(
            "joint outcome",
            document,
            {
                "disposition",
                "utility",
                "unauthorized_impact",
                "impact_witness_sha256",
                "outcome_class",
                "effectiveness_eligible",
                "counts_in_all_attempt_harm_lower_bound",
            },
        )
        for field in (
            "effectiveness_eligible",
            "counts_in_all_attempt_harm_lower_bound",
        ):
            if type(row[field]) is not bool:
                raise TypeError(f"joint outcome {field} must be an exact boolean")
        outcome = cls(
            TerminalDisposition(row["disposition"]),
            UtilityState(row["utility"]),
            ImpactState(row["unauthorized_impact"]),
            row["impact_witness_sha256"],
        )
        if outcome.document() != row:
            raise ValueError("joint outcome contains non-derived fields")
        return outcome


@dataclass(frozen=True, slots=True)
class TransformationVerification:
    """Evidence that the attack arm is exactly the preregistered visible transform."""

    clean_scenario_sha256: str
    attack_scenario_sha256: str
    attack_transformation_sha256: str
    verifier_contract_sha256: str
    target_visible_diff_sha256: str
    observed_target_visible_diff_sha256: str
    verifier_witness_sha256: str
    verification_complete: bool
    exact_single_transformation: bool
    unmodified_surface_match: bool

    def __post_init__(self) -> None:
        for name in (
            "clean_scenario_sha256",
            "attack_scenario_sha256",
            "attack_transformation_sha256",
            "verifier_contract_sha256",
            "target_visible_diff_sha256",
            "observed_target_visible_diff_sha256",
            "verifier_witness_sha256",
        ):
            _sha(name, getattr(self, name))
        for name in (
            "verification_complete",
            "exact_single_transformation",
            "unmodified_surface_match",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be an exact boolean")
        if self.clean_scenario_sha256 == self.attack_scenario_sha256:
            raise ValueError("verified clean and attack scenarios must differ")

    @property
    def decision(self) -> VerificationDecision:
        if not self.verification_complete:
            return VerificationDecision.INDETERMINATE
        if (
            self.exact_single_transformation
            and self.unmodified_surface_match
            and self.observed_target_visible_diff_sha256 == self.target_visible_diff_sha256
        ):
            return VerificationDecision.ACCEPTED
        return VerificationDecision.REJECTED

    def document(self) -> dict[str, Any]:
        return {
            "clean_scenario_sha256": self.clean_scenario_sha256,
            "attack_scenario_sha256": self.attack_scenario_sha256,
            "attack_transformation_sha256": self.attack_transformation_sha256,
            "verifier_contract_sha256": self.verifier_contract_sha256,
            "target_visible_diff_sha256": self.target_visible_diff_sha256,
            "observed_target_visible_diff_sha256": self.observed_target_visible_diff_sha256,
            "verifier_witness_sha256": self.verifier_witness_sha256,
            "verification_complete": self.verification_complete,
            "exact_single_transformation": self.exact_single_transformation,
            "unmodified_surface_match": self.unmodified_surface_match,
            "decision": self.decision.value,
        }

    @property
    def digest(self) -> str:
        return _canonical_sha("transformation_verification", self.document())


@dataclass(frozen=True, slots=True)
class ScenarioPairContract:
    """Task-matched pair sharing everything except a verified context transform."""

    pair_id: str
    scenario_family_sha256: str
    base_task_sha256: str
    fixture_sha256: str
    tool_world_sha256: str
    tool_schema_sha256: str
    horizon_law_sha256: str
    authority_graph_sha256: str
    utility_checker_sha256: str
    security_checker_sha256: str
    evaluator_secret_commitment_sha256: str
    transformation_verification: TransformationVerification

    def __post_init__(self) -> None:
        _token("pair_id", self.pair_id)
        for name in (
            "scenario_family_sha256",
            "base_task_sha256",
            "fixture_sha256",
            "tool_world_sha256",
            "tool_schema_sha256",
            "horizon_law_sha256",
            "authority_graph_sha256",
            "utility_checker_sha256",
            "security_checker_sha256",
            "evaluator_secret_commitment_sha256",
        ):
            _sha(name, getattr(self, name))
        if not isinstance(self.transformation_verification, TransformationVerification):
            raise TypeError("transformation_verification has the wrong type")
        if self.transformation_verification.decision is not VerificationDecision.ACCEPTED:
            raise ValueError("scenario pair requires an accepted transformation verification")

    @property
    def clean_scenario_sha256(self) -> str:
        return self.transformation_verification.clean_scenario_sha256

    @property
    def attack_scenario_sha256(self) -> str:
        return self.transformation_verification.attack_scenario_sha256

    @property
    def attack_transformation_sha256(self) -> str:
        return self.transformation_verification.attack_transformation_sha256

    def scenario_for(self, arm: ContextArm) -> str:
        if not isinstance(arm, ContextArm):
            raise TypeError("arm must be a ContextArm")
        return (
            self.clean_scenario_sha256 if arm is ContextArm.CLEAN else self.attack_scenario_sha256
        )

    def document(self) -> dict[str, Any]:
        return {
            "pair_id": self.pair_id,
            "scenario_family_sha256": self.scenario_family_sha256,
            "base_task_sha256": self.base_task_sha256,
            "fixture_sha256": self.fixture_sha256,
            "tool_world_sha256": self.tool_world_sha256,
            "tool_schema_sha256": self.tool_schema_sha256,
            "horizon_law_sha256": self.horizon_law_sha256,
            "authority_graph_sha256": self.authority_graph_sha256,
            "utility_checker_sha256": self.utility_checker_sha256,
            "security_checker_sha256": self.security_checker_sha256,
            "evaluator_secret_commitment_sha256": self.evaluator_secret_commitment_sha256,
            "transformation_verification_sha256": self.transformation_verification.digest,
        }

    @property
    def digest(self) -> str:
        return _canonical_sha("scenario_pair_contract", self.document())


@dataclass(frozen=True, slots=True)
class ProbabilityMeasureContract:
    """Preregistered population and clustering law behind any probability claim."""

    estimand_sha256: str
    task_sampling_frame_sha256: str
    candidate_sampling_frame_sha256: str
    seed_sampling_law_sha256: str
    confirmatory_population_sha256: str
    missingness_analysis_sha256: str
    estimator_law_sha256: str
    weighting_law_sha256: str
    clustering_law_sha256: str
    clustering_unit: str

    def __post_init__(self) -> None:
        for name in (
            "estimand_sha256",
            "task_sampling_frame_sha256",
            "candidate_sampling_frame_sha256",
            "seed_sampling_law_sha256",
            "confirmatory_population_sha256",
            "missingness_analysis_sha256",
            "estimator_law_sha256",
            "weighting_law_sha256",
            "clustering_law_sha256",
        ):
            _sha(name, getattr(self, name))
        _token("clustering_unit", self.clustering_unit)

    def document(self) -> dict[str, Any]:
        return {
            "estimand_sha256": self.estimand_sha256,
            "task_sampling_frame_sha256": self.task_sampling_frame_sha256,
            "candidate_sampling_frame_sha256": self.candidate_sampling_frame_sha256,
            "seed_sampling_law_sha256": self.seed_sampling_law_sha256,
            "confirmatory_population_sha256": self.confirmatory_population_sha256,
            "missingness_analysis_sha256": self.missingness_analysis_sha256,
            "estimator_law_sha256": self.estimator_law_sha256,
            "weighting_law_sha256": self.weighting_law_sha256,
            "clustering_law_sha256": self.clustering_law_sha256,
            "clustering_unit": self.clustering_unit,
        }

    @property
    def digest(self) -> str:
        return _canonical_sha("probability_measure_contract", self.document())


@dataclass(frozen=True, slots=True)
class CandidateContentKey:
    """Material identity only; generator provenance cannot make bytes novel."""

    scenario_family_sha256: str
    attack_transformation_sha256: str
    rendered_attack_sha256: str

    def __post_init__(self) -> None:
        for name in (
            "scenario_family_sha256",
            "attack_transformation_sha256",
            "rendered_attack_sha256",
        ):
            _sha(name, getattr(self, name))

    def document(self) -> dict[str, Any]:
        return {
            "scenario_family_sha256": self.scenario_family_sha256,
            "attack_transformation_sha256": self.attack_transformation_sha256,
            "rendered_attack_sha256": self.rendered_attack_sha256,
        }

    @property
    def digest(self) -> str:
        return _canonical_sha("candidate_content_key", self.document())


@dataclass(frozen=True, slots=True)
class CandidateProvenanceKey:
    """Generator lineage for clustering and audit, separate from novelty credit."""

    candidate_content_sha256: str
    generator_contract_sha256: str
    generator_artifact_sha256: str
    source_lineage_sha256: str
    parent_set_sha256: str
    cluster_identity_sha256: str
    novelty_registry_genesis_sha256: str
    generator_seed: int

    def __post_init__(self) -> None:
        for name in (
            "candidate_content_sha256",
            "generator_contract_sha256",
            "generator_artifact_sha256",
            "source_lineage_sha256",
            "parent_set_sha256",
            "cluster_identity_sha256",
            "novelty_registry_genesis_sha256",
        ):
            _sha(name, getattr(self, name))
        _nonnegative_int("generator_seed", self.generator_seed)

    def document(self) -> dict[str, Any]:
        return {
            "candidate_content_sha256": self.candidate_content_sha256,
            "generator_contract_sha256": self.generator_contract_sha256,
            "generator_artifact_sha256": self.generator_artifact_sha256,
            "source_lineage_sha256": self.source_lineage_sha256,
            "parent_set_sha256": self.parent_set_sha256,
            "cluster_identity_sha256": self.cluster_identity_sha256,
            "novelty_registry_genesis_sha256": self.novelty_registry_genesis_sha256,
            "generator_seed": self.generator_seed,
        }

    @property
    def digest(self) -> str:
        return _canonical_sha("candidate_provenance_key", self.document())


@dataclass(frozen=True, slots=True)
class TrialAssignmentKey:
    """Target-specific assignment; never used as global material novelty."""

    candidate_content_sha256: str
    target_model_sha256: str
    authority_graph_sha256: str
    utility_checker_sha256: str
    security_checker_sha256: str
    generation_law_sha256: str
    replicate_index: int

    def __post_init__(self) -> None:
        for name in (
            "candidate_content_sha256",
            "target_model_sha256",
            "authority_graph_sha256",
            "utility_checker_sha256",
            "security_checker_sha256",
            "generation_law_sha256",
        ):
            _sha(name, getattr(self, name))
        _positive_int("replicate_index", self.replicate_index)

    def document(self) -> dict[str, Any]:
        return {
            "candidate_content_sha256": self.candidate_content_sha256,
            "target_model_sha256": self.target_model_sha256,
            "authority_graph_sha256": self.authority_graph_sha256,
            "utility_checker_sha256": self.utility_checker_sha256,
            "security_checker_sha256": self.security_checker_sha256,
            "generation_law_sha256": self.generation_law_sha256,
            "replicate_index": self.replicate_index,
        }

    @property
    def digest(self) -> str:
        return _canonical_sha("trial_assignment_key", self.document())


@dataclass(frozen=True, slots=True)
class ReplayLawContract:
    """Pre-query replay law restricted to the comparison implemented below."""

    reconstruction_law_sha256: str
    max_replays: int
    comparison_algorithm: ReplayComparisonAlgorithm
    initial_outcome_authoritative: bool

    def __post_init__(self) -> None:
        _sha("reconstruction_law_sha256", self.reconstruction_law_sha256)
        _positive_int("max_replays", self.max_replays)
        if self.comparison_algorithm is not ReplayComparisonAlgorithm.STRICT_TRAJECTORY_V1:
            raise ValueError("unsupported replay comparison algorithm")
        if self.initial_outcome_authoritative is not True:
            raise ValueError("replay law cannot permit rewriting the initial outcome")

    def document(self) -> dict[str, Any]:
        return {
            "reconstruction_law_sha256": self.reconstruction_law_sha256,
            "max_replays": self.max_replays,
            "comparison_algorithm": self.comparison_algorithm.value,
            "initial_outcome_authoritative": self.initial_outcome_authoritative,
        }

    @property
    def digest(self) -> str:
        return _canonical_sha("replay_law_contract", self.document())


@dataclass(frozen=True, slots=True)
class ScheduledPairKey:
    """Pre-query parent identity shared by exactly one clean and one attack child."""

    experiment_id: str
    scenario_pair: ScenarioPairContract
    probability_measure: ProbabilityMeasureContract
    policy: str
    history: str
    cycle: int
    pair_position: int
    crn_seed: int
    plan_sha256: str
    scheduler_state_sha256: str
    candidate_content: CandidateContentKey
    candidate_provenance: CandidateProvenanceKey
    trial_assignment: TrialAssignmentKey
    novelty_registry_overlay_sha256: str
    replay_law: ReplayLawContract
    manifest_sha256: str

    def __post_init__(self) -> None:
        for name in ("experiment_id", "policy", "history"):
            _token(name, getattr(self, name))
        if not isinstance(self.scenario_pair, ScenarioPairContract):
            raise TypeError("scenario_pair must be a ScenarioPairContract")
        if not isinstance(self.probability_measure, ProbabilityMeasureContract):
            raise TypeError("probability_measure must be a ProbabilityMeasureContract")
        if not isinstance(self.candidate_content, CandidateContentKey):
            raise TypeError("candidate_content must be a CandidateContentKey")
        if not isinstance(self.candidate_provenance, CandidateProvenanceKey):
            raise TypeError("candidate_provenance must be a CandidateProvenanceKey")
        if not isinstance(self.trial_assignment, TrialAssignmentKey):
            raise TypeError("trial_assignment must be a TrialAssignmentKey")
        if not isinstance(self.replay_law, ReplayLawContract):
            raise TypeError("replay_law must be a ReplayLawContract")
        if (
            self.candidate_content.scenario_family_sha256
            != self.scenario_pair.scenario_family_sha256
        ):
            raise ValueError("candidate content belongs to a different scenario family")
        if (
            self.candidate_content.attack_transformation_sha256
            != self.scenario_pair.attack_transformation_sha256
        ):
            raise ValueError("candidate content is not bound to the pair transformation")
        if (
            self.candidate_content.rendered_attack_sha256
            != self.scenario_pair.attack_scenario_sha256
        ):
            raise ValueError("candidate rendered material is not the scheduled attack scenario")
        if self.candidate_provenance.candidate_content_sha256 != self.candidate_content.digest:
            raise ValueError("candidate provenance is not bound to scheduled content")
        assignment = self.trial_assignment
        if assignment.candidate_content_sha256 != self.candidate_content.digest:
            raise ValueError("trial assignment is not bound to scheduled content")
        if assignment.authority_graph_sha256 != self.scenario_pair.authority_graph_sha256:
            raise ValueError("trial assignment authority differs from the scenario pair")
        if assignment.utility_checker_sha256 != self.scenario_pair.utility_checker_sha256:
            raise ValueError("trial assignment utility checker differs from the scenario pair")
        if assignment.security_checker_sha256 != self.scenario_pair.security_checker_sha256:
            raise ValueError("trial assignment security checker differs from the scenario pair")
        for name in ("cycle", "pair_position", "crn_seed"):
            _positive_int(name, getattr(self, name))
        for name in (
            "plan_sha256",
            "scheduler_state_sha256",
            "novelty_registry_overlay_sha256",
            "manifest_sha256",
        ):
            _sha(name, getattr(self, name))

    def document(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "scenario_pair_sha256": self.scenario_pair.digest,
            "probability_measure_sha256": self.probability_measure.digest,
            "pair_id": self.scenario_pair.pair_id,
            "policy": self.policy,
            "history": self.history,
            "cycle": self.cycle,
            "pair_position": self.pair_position,
            "crn_seed": self.crn_seed,
            "plan_sha256": self.plan_sha256,
            "scheduler_state_sha256": self.scheduler_state_sha256,
            "candidate_content_sha256": self.candidate_content.digest,
            "candidate_provenance_sha256": self.candidate_provenance.digest,
            "novelty_registry_genesis_sha256": (
                self.candidate_provenance.novelty_registry_genesis_sha256
            ),
            "trial_assignment_sha256": self.trial_assignment.digest,
            "novelty_registry_overlay_sha256": self.novelty_registry_overlay_sha256,
            "target_model_sha256": self.trial_assignment.target_model_sha256,
            "generation_law_sha256": self.trial_assignment.generation_law_sha256,
            "replay_law_sha256": self.replay_law.digest,
            "manifest_sha256": self.manifest_sha256,
        }

    @property
    def digest(self) -> str:
        return _canonical_sha("scheduled_pair_key", self.document())

    def children(self) -> tuple[ScheduledEpisodeKey, ScheduledEpisodeKey]:
        children = (
            ScheduledEpisodeKey(self, ContextArm.CLEAN, self.scenario_pair.clean_scenario_sha256),
            ScheduledEpisodeKey(self, ContextArm.ATTACK, self.scenario_pair.attack_scenario_sha256),
        )
        self.validate_children(children)
        return children

    def validate_children(
        self, children: tuple[ScheduledEpisodeKey, ...] | list[ScheduledEpisodeKey]
    ) -> None:
        if not isinstance(children, (tuple, list)) or len(children) != 2:
            raise ValueError("scheduled pair requires exactly two children")
        if any(not isinstance(child, ScheduledEpisodeKey) for child in children):
            raise TypeError("scheduled pair children have the wrong type")
        expected = {child.digest for child in self.children_unchecked()}
        observed = {child.digest for child in children}
        if len(observed) != 2 or observed != expected:
            raise ValueError("scheduled pair children must be exactly CLEAN and ATTACK")

    def children_unchecked(self) -> tuple[ScheduledEpisodeKey, ScheduledEpisodeKey]:
        return (
            ScheduledEpisodeKey(self, ContextArm.CLEAN, self.scenario_pair.clean_scenario_sha256),
            ScheduledEpisodeKey(self, ContextArm.ATTACK, self.scenario_pair.attack_scenario_sha256),
        )


@dataclass(frozen=True, slots=True)
class ScheduledEpisodeKey:
    """One arm of a scheduled pair; no response or outcome enters this identity."""

    scheduled_pair: ScheduledPairKey
    context_arm: ContextArm
    selected_scenario_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.scheduled_pair, ScheduledPairKey):
            raise TypeError("scheduled_pair must be a ScheduledPairKey")
        if not isinstance(self.context_arm, ContextArm):
            raise TypeError("context_arm must be a ContextArm")
        _sha("selected_scenario_sha256", self.selected_scenario_sha256)
        if self.selected_scenario_sha256 != self.scheduled_pair.scenario_pair.scenario_for(
            self.context_arm
        ):
            raise ValueError("selected scenario does not match the paired context arm")

    def document(self) -> dict[str, Any]:
        return {
            "scheduled_pair_sha256": self.scheduled_pair.digest,
            "context_arm": self.context_arm.value,
            "selected_scenario_sha256": self.selected_scenario_sha256,
        }

    @property
    def digest(self) -> str:
        return _canonical_sha("scheduled_episode_key", self.document())


@dataclass(frozen=True, slots=True)
class RequestBinding:
    """Bundle assertion joining exact request digests to one scheduled arm."""

    scheduled_episode: ScheduledEpisodeKey
    request_contract_sha256: str
    request_context_sha256: str
    request_semantics_sha256: str
    request_envelope_sha256: str
    renderer_contract_sha256: str
    renderer_witness_sha256: str
    candidate_material_state: CandidateMaterialState

    def __post_init__(self) -> None:
        if not isinstance(self.scheduled_episode, ScheduledEpisodeKey):
            raise TypeError("scheduled_episode must be a ScheduledEpisodeKey")
        for name in (
            "request_contract_sha256",
            "request_context_sha256",
            "request_semantics_sha256",
            "request_envelope_sha256",
            "renderer_contract_sha256",
            "renderer_witness_sha256",
        ):
            _sha(name, getattr(self, name))
        if self.request_context_sha256 != self.scheduled_episode.selected_scenario_sha256:
            raise ValueError("request context is not bound to the selected scenario arm")
        if not isinstance(self.candidate_material_state, CandidateMaterialState):
            raise TypeError("candidate_material_state has the wrong type")
        expected = (
            CandidateMaterialState.EXCLUDED
            if self.scheduled_episode.context_arm is ContextArm.CLEAN
            else CandidateMaterialState.INCLUDED
        )
        if self.candidate_material_state is not expected:
            raise ValueError("request candidate-material state contradicts its context arm")

    def document(self) -> dict[str, Any]:
        parent = self.scheduled_episode.scheduled_pair
        return {
            "scheduled_episode_sha256": self.scheduled_episode.digest,
            "scheduled_pair_sha256": parent.digest,
            "context_arm": self.scheduled_episode.context_arm.value,
            "request_contract_sha256": self.request_contract_sha256,
            "request_context_sha256": self.request_context_sha256,
            "request_semantics_sha256": self.request_semantics_sha256,
            "request_envelope_sha256": self.request_envelope_sha256,
            "renderer_contract_sha256": self.renderer_contract_sha256,
            "renderer_witness_sha256": self.renderer_witness_sha256,
            "candidate_material_state": self.candidate_material_state.value,
            "candidate_content_sha256": parent.candidate_content.digest,
            "plan_sha256": parent.plan_sha256,
            "cycle": parent.cycle,
            "pair_position": parent.pair_position,
            "crn_seed": parent.crn_seed,
            "tool_schema_sha256": parent.scenario_pair.tool_schema_sha256,
            "generation_law_sha256": parent.trial_assignment.generation_law_sha256,
        }

    @property
    def digest(self) -> str:
        return _canonical_sha("request_binding", self.document())


@dataclass(frozen=True, slots=True)
class EvaluatorSecretOpening:
    """Mechanically accepted bundle assertion about a commitment opening."""

    commitment_sha256: str
    realization_sha256: str
    opening_law_sha256: str
    opening_witness_sha256: str
    verification_complete: bool
    opens_commitment: bool

    def __post_init__(self) -> None:
        for name in (
            "commitment_sha256",
            "realization_sha256",
            "opening_law_sha256",
            "opening_witness_sha256",
        ):
            _sha(name, getattr(self, name))
        for name in ("verification_complete", "opens_commitment"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be an exact boolean")

    @property
    def accepted(self) -> bool:
        return self.verification_complete and self.opens_commitment

    def document(self) -> dict[str, Any]:
        return {
            "commitment_sha256": self.commitment_sha256,
            "realization_sha256": self.realization_sha256,
            "opening_law_sha256": self.opening_law_sha256,
            "opening_witness_sha256": self.opening_witness_sha256,
            "verification_complete": self.verification_complete,
            "opens_commitment": self.opens_commitment,
            "accepted": self.accepted,
        }

    @property
    def digest(self) -> str:
        return _canonical_sha("evaluator_secret_opening", self.document())


@dataclass(frozen=True, slots=True)
class RuntimeAttestation:
    """Bundle-asserted runtime identity reconciled with scheduled digest values."""

    scheduled_episode: ScheduledEpisodeKey
    served_model_sha256: str
    server_binary_sha256: str
    dependency_lock_sha256: str
    controller_sha256: str
    harness_sha256: str
    observed_tool_world_sha256: str
    attestation_contract_sha256: str
    attestation_witness_sha256: str
    verification_complete: bool
    binary_measurements_verified: bool

    def __post_init__(self) -> None:
        if not isinstance(self.scheduled_episode, ScheduledEpisodeKey):
            raise TypeError("scheduled_episode must be a ScheduledEpisodeKey")
        for name in (
            "served_model_sha256",
            "server_binary_sha256",
            "dependency_lock_sha256",
            "controller_sha256",
            "harness_sha256",
            "observed_tool_world_sha256",
            "attestation_contract_sha256",
            "attestation_witness_sha256",
        ):
            _sha(name, getattr(self, name))
        for name in ("verification_complete", "binary_measurements_verified"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be an exact boolean")

    @property
    def accepted(self) -> bool:
        parent = self.scheduled_episode.scheduled_pair
        return (
            self.verification_complete
            and self.binary_measurements_verified
            and self.served_model_sha256 == parent.trial_assignment.target_model_sha256
            and self.observed_tool_world_sha256 == parent.scenario_pair.tool_world_sha256
        )

    def document(self) -> dict[str, Any]:
        return {
            "scheduled_episode_sha256": self.scheduled_episode.digest,
            "scheduled_target_model_sha256": (
                self.scheduled_episode.scheduled_pair.trial_assignment.target_model_sha256
            ),
            "served_model_sha256": self.served_model_sha256,
            "server_binary_sha256": self.server_binary_sha256,
            "dependency_lock_sha256": self.dependency_lock_sha256,
            "controller_sha256": self.controller_sha256,
            "harness_sha256": self.harness_sha256,
            "scheduled_tool_world_sha256": (
                self.scheduled_episode.scheduled_pair.scenario_pair.tool_world_sha256
            ),
            "observed_tool_world_sha256": self.observed_tool_world_sha256,
            "attestation_contract_sha256": self.attestation_contract_sha256,
            "attestation_witness_sha256": self.attestation_witness_sha256,
            "verification_complete": self.verification_complete,
            "binary_measurements_verified": self.binary_measurements_verified,
            "accepted": self.accepted,
        }

    @property
    def digest(self) -> str:
        return _canonical_sha("runtime_attestation", self.document())


@dataclass(frozen=True, slots=True)
class EpisodePrestate:
    """Structured base-state/context join so pair equivalence is mechanically checkable."""

    request_binding: RequestBinding
    evaluator_secret_opening: EvaluatorSecretOpening
    fixture_sha256: str
    base_world_state_sha256: str
    rendered_context_sha256: str
    prestate_artifact_sha256: str
    construction_witness_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.request_binding, RequestBinding):
            raise TypeError("request_binding must be a RequestBinding")
        if not isinstance(self.evaluator_secret_opening, EvaluatorSecretOpening):
            raise TypeError("evaluator_secret_opening has the wrong type")
        for name in (
            "fixture_sha256",
            "base_world_state_sha256",
            "rendered_context_sha256",
            "prestate_artifact_sha256",
            "construction_witness_sha256",
        ):
            _sha(name, getattr(self, name))
        pair = self.request_binding.scheduled_episode.scheduled_pair.scenario_pair
        if self.fixture_sha256 != pair.fixture_sha256:
            raise ValueError("prestate fixture does not match the scenario pair")
        if self.rendered_context_sha256 != self.request_binding.request_context_sha256:
            raise ValueError("prestate context does not match the rendered request")
        if self.evaluator_secret_opening.commitment_sha256 != (
            pair.evaluator_secret_commitment_sha256
        ):
            raise ValueError("evaluator-secret opening targets the wrong commitment")
        if not self.evaluator_secret_opening.accepted:
            raise ValueError("evaluator-secret commitment opening was not verified")

    def document(self) -> dict[str, Any]:
        return {
            "request_binding_sha256": self.request_binding.digest,
            "evaluator_secret_opening_sha256": self.evaluator_secret_opening.digest,
            "fixture_sha256": self.fixture_sha256,
            "base_world_state_sha256": self.base_world_state_sha256,
            "rendered_context_sha256": self.rendered_context_sha256,
            "prestate_artifact_sha256": self.prestate_artifact_sha256,
            "construction_witness_sha256": self.construction_witness_sha256,
        }

    @property
    def digest(self) -> str:
        return _canonical_sha("episode_prestate", self.document())


@dataclass(frozen=True, slots=True)
class PairedRequestVerification:
    """Bundle assertion that request digests differ only by the admitted transform."""

    clean: RequestBinding
    attack: RequestBinding
    observed_target_visible_diff_sha256: str
    verifier_contract_sha256: str
    verifier_witness_sha256: str
    verification_complete: bool
    only_preregistered_delta: bool

    def __post_init__(self) -> None:
        if not isinstance(self.clean, RequestBinding) or not isinstance(
            self.attack, RequestBinding
        ):
            raise TypeError("paired request verification requires two request bindings")
        for name in (
            "observed_target_visible_diff_sha256",
            "verifier_contract_sha256",
            "verifier_witness_sha256",
        ):
            _sha(name, getattr(self, name))
        for name in ("verification_complete", "only_preregistered_delta"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be an exact boolean")
        clean_episode = self.clean.scheduled_episode
        attack_episode = self.attack.scheduled_episode
        parent = clean_episode.scheduled_pair
        parent.validate_children([clean_episode, attack_episode])
        if clean_episode.context_arm is not ContextArm.CLEAN:
            raise ValueError("paired request clean binding has the wrong arm")
        if attack_episode.context_arm is not ContextArm.ATTACK:
            raise ValueError("paired request attack binding has the wrong arm")
        if self.clean.request_semantics_sha256 == self.attack.request_semantics_sha256:
            raise ValueError("paired requests have identical context-bearing semantics")
        if self.clean.request_envelope_sha256 == self.attack.request_envelope_sha256:
            raise ValueError("paired requests have identical exact envelopes")
        expected_diff = parent.scenario_pair.transformation_verification.target_visible_diff_sha256
        if self.observed_target_visible_diff_sha256 != expected_diff:
            raise ValueError("paired request diff does not match the accepted transformation")
        if not self.accepted:
            raise ValueError("paired request transformation was not verified")

    @property
    def accepted(self) -> bool:
        return self.verification_complete and self.only_preregistered_delta

    def document(self) -> dict[str, Any]:
        return {
            "clean_request_binding_sha256": self.clean.digest,
            "attack_request_binding_sha256": self.attack.digest,
            "scheduled_pair_sha256": self.clean.scheduled_episode.scheduled_pair.digest,
            "candidate_content_sha256": (
                self.clean.scheduled_episode.scheduled_pair.candidate_content.digest
            ),
            "observed_target_visible_diff_sha256": (self.observed_target_visible_diff_sha256),
            "verifier_contract_sha256": self.verifier_contract_sha256,
            "verifier_witness_sha256": self.verifier_witness_sha256,
            "verification_complete": self.verification_complete,
            "only_preregistered_delta": self.only_preregistered_delta,
            "accepted": self.accepted,
        }

    @property
    def digest(self) -> str:
        return _canonical_sha("paired_request_verification", self.document())


@dataclass(frozen=True, slots=True)
class EpisodeEvidenceIdentity:
    """Post-attempt identity binding envelopes, trajectory, state, and checker output."""

    request_binding: RequestBinding
    evaluator_secret_opening: EvaluatorSecretOpening
    runtime_attestation: RuntimeAttestation
    prestate: EpisodePrestate
    phase: EpisodePhase
    attempt_ordinal: int
    response_envelope_sha256: str
    extraction_contract_sha256: str
    tool_trace_sha256: str
    poststate_sha256: str
    mutation_log_sha256: str
    checker_result_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.request_binding, RequestBinding):
            raise TypeError("request_binding must be a RequestBinding")
        if not isinstance(self.evaluator_secret_opening, EvaluatorSecretOpening):
            raise TypeError("evaluator_secret_opening has the wrong type")
        if not isinstance(self.runtime_attestation, RuntimeAttestation):
            raise TypeError("runtime_attestation has the wrong type")
        if not isinstance(self.prestate, EpisodePrestate):
            raise TypeError("prestate must be an EpisodePrestate")
        if not isinstance(self.phase, EpisodePhase):
            raise TypeError("phase must be an EpisodePhase")
        _nonnegative_int("attempt_ordinal", self.attempt_ordinal)
        if self.phase is EpisodePhase.INITIAL and self.attempt_ordinal != 0:
            raise ValueError("initial evidence must have attempt ordinal zero")
        if self.phase is EpisodePhase.REPLAY and self.attempt_ordinal < 1:
            raise ValueError("replay evidence must have a positive attempt ordinal")
        if self.prestate.request_binding.digest != self.request_binding.digest:
            raise ValueError("prestate is bound to a different request")
        if self.prestate.evaluator_secret_opening.digest != self.evaluator_secret_opening.digest:
            raise ValueError("prestate is bound to a different evaluator secret")
        if self.runtime_attestation.scheduled_episode.digest != self.scheduled_episode.digest:
            raise ValueError("runtime attestation is bound to a different scheduled episode")
        if not self.runtime_attestation.accepted:
            raise ValueError("runtime attestation does not open the scheduled runtime")
        for name in (
            "response_envelope_sha256",
            "extraction_contract_sha256",
            "tool_trace_sha256",
            "poststate_sha256",
            "mutation_log_sha256",
            "checker_result_sha256",
        ):
            _sha(name, getattr(self, name))

    @property
    def scheduled_episode(self) -> ScheduledEpisodeKey:
        return self.request_binding.scheduled_episode

    @property
    def request_contract_sha256(self) -> str:
        return self.request_binding.request_contract_sha256

    @property
    def request_context_sha256(self) -> str:
        return self.request_binding.request_context_sha256

    @property
    def request_semantics_sha256(self) -> str:
        return self.request_binding.request_semantics_sha256

    @property
    def request_envelope_sha256(self) -> str:
        return self.request_binding.request_envelope_sha256

    @property
    def request_binding_witness_sha256(self) -> str:
        return self.request_binding.renderer_witness_sha256

    @property
    def renderer_contract_sha256(self) -> str:
        return self.request_binding.renderer_contract_sha256

    @property
    def evaluator_secret_realization_sha256(self) -> str:
        return self.evaluator_secret_opening.realization_sha256

    @property
    def server_binary_sha256(self) -> str:
        return self.runtime_attestation.server_binary_sha256

    @property
    def dependency_lock_sha256(self) -> str:
        return self.runtime_attestation.dependency_lock_sha256

    @property
    def controller_sha256(self) -> str:
        return self.runtime_attestation.controller_sha256

    @property
    def harness_sha256(self) -> str:
        return self.runtime_attestation.harness_sha256

    @property
    def runtime_attestation_sha256(self) -> str:
        return self.runtime_attestation.digest

    @property
    def prestate_sha256(self) -> str:
        return self.prestate.prestate_artifact_sha256

    def document(self) -> dict[str, Any]:
        return {
            "scheduled_episode_sha256": self.scheduled_episode.digest,
            "scheduled_pair_sha256": self.scheduled_episode.scheduled_pair.digest,
            "context_arm": self.scheduled_episode.context_arm.value,
            "candidate_content_sha256": (
                self.scheduled_episode.scheduled_pair.candidate_content.digest
            ),
            "transformation_verification_sha256": (
                self.scheduled_episode.scheduled_pair.scenario_pair.transformation_verification.digest
            ),
            "target_visible_diff_sha256": (
                self.scheduled_episode.scheduled_pair.scenario_pair.transformation_verification.target_visible_diff_sha256
            ),
            "phase": self.phase.value,
            "attempt_ordinal": self.attempt_ordinal,
            "request_binding_sha256": self.request_binding.digest,
            "request_contract_sha256": self.request_contract_sha256,
            "request_context_sha256": self.request_context_sha256,
            "request_semantics_sha256": self.request_semantics_sha256,
            "request_envelope_sha256": self.request_envelope_sha256,
            "request_binding_witness_sha256": self.request_binding_witness_sha256,
            "evaluator_secret_opening_sha256": self.evaluator_secret_opening.digest,
            "evaluator_secret_realization_sha256": self.evaluator_secret_realization_sha256,
            "response_envelope_sha256": self.response_envelope_sha256,
            "extraction_contract_sha256": self.extraction_contract_sha256,
            "server_binary_sha256": self.server_binary_sha256,
            "dependency_lock_sha256": self.dependency_lock_sha256,
            "controller_sha256": self.controller_sha256,
            "harness_sha256": self.harness_sha256,
            "runtime_attestation_sha256": self.runtime_attestation_sha256,
            "tool_trace_sha256": self.tool_trace_sha256,
            "prestate_sha256": self.prestate_sha256,
            "prestate_contract_sha256": self.prestate.digest,
            "poststate_sha256": self.poststate_sha256,
            "mutation_log_sha256": self.mutation_log_sha256,
            "checker_result_sha256": self.checker_result_sha256,
        }

    @property
    def digest(self) -> str:
        return _canonical_sha("episode_evidence_identity", self.document())


@dataclass(frozen=True, slots=True)
class MechanicalCheckerResult:
    """Strict checker output from which an episode outcome is derived, never selected."""

    utility_checker_contract_sha256: str
    security_checker_contract_sha256: str
    checker_execution_witness_sha256: str
    tool_trace_sha256: str
    prestate_sha256: str
    poststate_sha256: str
    mutation_log_sha256: str
    utility: UtilityState
    unauthorized_impact: ImpactState
    utility_witness_sha256: str | None
    security_witness_sha256: str | None

    def __post_init__(self) -> None:
        for name in (
            "utility_checker_contract_sha256",
            "security_checker_contract_sha256",
            "checker_execution_witness_sha256",
            "tool_trace_sha256",
            "prestate_sha256",
            "poststate_sha256",
            "mutation_log_sha256",
        ):
            _sha(name, getattr(self, name))
        if not isinstance(self.utility, UtilityState):
            raise TypeError("utility must be a UtilityState")
        if not isinstance(self.unauthorized_impact, ImpactState):
            raise TypeError("unauthorized_impact must be an ImpactState")
        if self.utility is UtilityState.UNKNOWN:
            if self.utility_witness_sha256 is not None:
                raise ValueError("unknown utility cannot carry a utility witness")
        elif self.utility_witness_sha256 is None:
            raise ValueError("resolved utility requires a mechanical witness")
        else:
            _sha("utility_witness_sha256", self.utility_witness_sha256)
        if self.unauthorized_impact is ImpactState.UNKNOWN:
            if self.security_witness_sha256 is not None:
                raise ValueError("unknown impact cannot carry a security witness")
        elif self.security_witness_sha256 is None:
            raise ValueError("resolved impact requires a mechanical witness")
        else:
            _sha("security_witness_sha256", self.security_witness_sha256)

    def document(self) -> dict[str, Any]:
        return {
            "utility_checker_contract_sha256": self.utility_checker_contract_sha256,
            "security_checker_contract_sha256": self.security_checker_contract_sha256,
            "checker_execution_witness_sha256": self.checker_execution_witness_sha256,
            "tool_trace_sha256": self.tool_trace_sha256,
            "prestate_sha256": self.prestate_sha256,
            "poststate_sha256": self.poststate_sha256,
            "mutation_log_sha256": self.mutation_log_sha256,
            "utility": self.utility.value,
            "unauthorized_impact": self.unauthorized_impact.value,
            "utility_witness_sha256": self.utility_witness_sha256,
            "security_witness_sha256": self.security_witness_sha256,
        }

    @property
    def digest(self) -> str:
        return _canonical_sha("mechanical_checker_result", self.document())


@dataclass(frozen=True, slots=True)
class EpisodeAdjudication:
    """Join retained evidence to the only outcome derivable from its checker result."""

    evidence: EpisodeEvidenceIdentity
    checker_result: MechanicalCheckerResult
    disposition: TerminalDisposition
    terminal_witness_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, EpisodeEvidenceIdentity):
            raise TypeError("evidence must be an EpisodeEvidenceIdentity")
        if not isinstance(self.checker_result, MechanicalCheckerResult):
            raise TypeError("checker_result must be a MechanicalCheckerResult")
        if not isinstance(self.disposition, TerminalDisposition):
            raise TypeError("disposition must be a TerminalDisposition")
        _sha("terminal_witness_sha256", self.terminal_witness_sha256)
        if (
            self.disposition is TerminalDisposition.INCOMPLETE_REPLAY
            and self.evidence.phase is not EpisodePhase.REPLAY
        ):
            raise ValueError("incomplete_replay disposition requires replay-phase evidence")
        if self.checker_result.digest != self.evidence.checker_result_sha256:
            raise ValueError("checker result is not bound to the evidence identity")
        for field in (
            "tool_trace_sha256",
            "prestate_sha256",
            "poststate_sha256",
            "mutation_log_sha256",
        ):
            if getattr(self.checker_result, field) != getattr(self.evidence, field):
                raise ValueError(f"checker result {field} does not match retained evidence")
        pair = self.evidence.scheduled_episode.scheduled_pair.scenario_pair
        if self.checker_result.utility_checker_contract_sha256 != pair.utility_checker_sha256:
            raise ValueError("utility checker contract does not match the scenario pair")
        if self.checker_result.security_checker_contract_sha256 != pair.security_checker_sha256:
            raise ValueError("security checker contract does not match the scenario pair")
        # Force validation of disposition/predicate compatibility now, not lazily.
        _ = self.outcome

    @property
    def outcome(self) -> JointOutcome:
        return JointOutcome.classify(
            self.disposition,
            utility=self.checker_result.utility,
            unauthorized_impact=self.checker_result.unauthorized_impact,
            impact_witness_sha256=(
                self.checker_result.security_witness_sha256
                if self.checker_result.unauthorized_impact is ImpactState.PRESENT
                else None
            ),
        )

    def document(self) -> dict[str, Any]:
        return {
            "evidence_realization_sha256": self.evidence.digest,
            "checker_result_sha256": self.checker_result.digest,
            "terminal_witness_sha256": self.terminal_witness_sha256,
            "disposition": self.disposition.value,
            "outcome_sha256": self.outcome.digest,
            "outcome": self.outcome.document(),
        }

    @property
    def digest(self) -> str:
        return _canonical_sha("episode_adjudication", self.document())


@dataclass(frozen=True, slots=True)
class ReplayLink:
    """Proof that replay evidence uses the same frozen request and attempt law."""

    initial: EpisodeEvidenceIdentity
    replay: EpisodeEvidenceIdentity

    def __post_init__(self) -> None:
        if not isinstance(self.initial, EpisodeEvidenceIdentity) or not isinstance(
            self.replay, EpisodeEvidenceIdentity
        ):
            raise TypeError("replay link requires two episode evidence identities")
        if self.initial.phase is not EpisodePhase.INITIAL:
            raise ValueError("replay link initial evidence has the wrong phase")
        if self.replay.phase is not EpisodePhase.REPLAY:
            raise ValueError("replay link replay evidence has the wrong phase")
        if self.initial.scheduled_episode.digest != self.replay.scheduled_episode.digest:
            raise ValueError("replay invariant drift: scheduled_episode")
        replay_law = self.initial.scheduled_episode.scheduled_pair.replay_law
        if self.replay.attempt_ordinal > replay_law.max_replays:
            raise ValueError("replay ordinal exceeds the preregistered replay law")
        if self.initial.request_binding.digest != self.replay.request_binding.digest:
            raise ValueError("replay invariant drift: request_binding")
        if (
            self.initial.evaluator_secret_opening.digest
            != self.replay.evaluator_secret_opening.digest
        ):
            raise ValueError("replay invariant drift: evaluator_secret_opening")
        if self.initial.prestate.digest != self.replay.prestate.digest:
            raise ValueError("replay invariant drift: prestate_contract")
        invariant_fields = (
            "request_contract_sha256",
            "request_context_sha256",
            "request_semantics_sha256",
            "request_envelope_sha256",
            "request_binding_witness_sha256",
            "evaluator_secret_realization_sha256",
            "extraction_contract_sha256",
            "server_binary_sha256",
            "dependency_lock_sha256",
            "controller_sha256",
            "harness_sha256",
            "runtime_attestation_sha256",
            "prestate_sha256",
        )
        drift = [
            name
            for name in invariant_fields
            if getattr(self.initial, name) != getattr(self.replay, name)
        ]
        if drift:
            raise ValueError(f"replay invariant drift: {drift}")

    def comparison(
        self,
        initial_adjudication: EpisodeAdjudication,
        replay_adjudication: EpisodeAdjudication,
    ) -> ReplayComparison:
        return ReplayComparison(self, initial_adjudication, replay_adjudication)

    def document(self) -> dict[str, Any]:
        return {
            "initial_evidence_sha256": self.initial.digest,
            "replay_evidence_sha256": self.replay.digest,
            "replay_ordinal": self.replay.attempt_ordinal,
            "replay_law_sha256": (self.initial.scheduled_episode.scheduled_pair.replay_law.digest),
        }

    @property
    def digest(self) -> str:
        return _canonical_sha("replay_link", self.document())


@dataclass(frozen=True, slots=True)
class ReplayComparison:
    """Typed diagnostic; it never replaces the initial adjudication."""

    link: ReplayLink
    initial_adjudication: EpisodeAdjudication
    replay_adjudication: EpisodeAdjudication

    def __post_init__(self) -> None:
        if not isinstance(self.link, ReplayLink):
            raise TypeError("link must be a ReplayLink")
        if not isinstance(self.initial_adjudication, EpisodeAdjudication) or not isinstance(
            self.replay_adjudication, EpisodeAdjudication
        ):
            raise TypeError("replay comparison requires two adjudications")
        if self.initial_adjudication.evidence.digest != self.link.initial.digest:
            raise ValueError("initial adjudication is not bound to replay-link evidence")
        if self.replay_adjudication.evidence.digest != self.link.replay.digest:
            raise ValueError("replay adjudication is not bound to replay-link evidence")

    @property
    def dimension_matches(self) -> dict[str, bool]:
        return {
            "outcome": (
                self.initial_adjudication.outcome.document()
                == self.replay_adjudication.outcome.document()
            ),
            "response_envelope": (
                self.link.initial.response_envelope_sha256
                == self.link.replay.response_envelope_sha256
            ),
            "tool_trace": self.link.initial.tool_trace_sha256 == self.link.replay.tool_trace_sha256,
            "poststate": self.link.initial.poststate_sha256 == self.link.replay.poststate_sha256,
            "mutation_log": self.link.initial.mutation_log_sha256
            == self.link.replay.mutation_log_sha256,
            "checker_result": (
                self.link.initial.checker_result_sha256 == self.link.replay.checker_result_sha256
            ),
            "utility_checker_contract": (
                self.initial_adjudication.checker_result.utility_checker_contract_sha256
                == self.replay_adjudication.checker_result.utility_checker_contract_sha256
            ),
            "security_checker_contract": (
                self.initial_adjudication.checker_result.security_checker_contract_sha256
                == self.replay_adjudication.checker_result.security_checker_contract_sha256
            ),
            "utility_witness": (
                self.initial_adjudication.checker_result.utility_witness_sha256
                == self.replay_adjudication.checker_result.utility_witness_sha256
            ),
            "security_witness": (
                self.initial_adjudication.checker_result.security_witness_sha256
                == self.replay_adjudication.checker_result.security_witness_sha256
            ),
            "terminal_witness": (
                self.initial_adjudication.terminal_witness_sha256
                == self.replay_adjudication.terminal_witness_sha256
            ),
        }

    @property
    def status(self) -> ReplayComparisonStatus:
        categories = {
            self.initial_adjudication.outcome.disposition.category,
            self.replay_adjudication.outcome.disposition.category,
        }
        if "invalid" in categories:
            return ReplayComparisonStatus.INVALID
        if "incomplete" in categories:
            return ReplayComparisonStatus.INCOMPLETE
        if all(self.dimension_matches.values()):
            return ReplayComparisonStatus.AGREES
        return ReplayComparisonStatus.DISAGREES

    def document(self) -> dict[str, Any]:
        return {
            "replay_link_sha256": self.link.digest,
            "initial_adjudication_sha256": self.initial_adjudication.digest,
            "replay_adjudication_sha256": self.replay_adjudication.digest,
            "initial_outcome_authoritative_sha256": self.initial_adjudication.outcome.digest,
            "status": self.status.value,
            "dimension_matches": self.dimension_matches,
        }

    @property
    def digest(self) -> str:
        return _canonical_sha("replay_comparison", self.document())


@dataclass(frozen=True, slots=True)
class PairTerminalReconciliation:
    """Terminal proof that both and only both paired initial arms were adjudicated."""

    scheduled_pair: ScheduledPairKey
    clean_episode: ScheduledEpisodeKey
    attack_episode: ScheduledEpisodeKey
    request_verification: PairedRequestVerification
    clean_adjudication: EpisodeAdjudication
    attack_adjudication: EpisodeAdjudication

    def __post_init__(self) -> None:
        if not isinstance(self.scheduled_pair, ScheduledPairKey):
            raise TypeError("scheduled_pair must be a ScheduledPairKey")
        self.scheduled_pair.validate_children([self.clean_episode, self.attack_episode])
        if self.clean_episode.context_arm is not ContextArm.CLEAN:
            raise ValueError("clean reconciliation child has the wrong arm")
        if self.attack_episode.context_arm is not ContextArm.ATTACK:
            raise ValueError("attack reconciliation child has the wrong arm")
        if not isinstance(self.request_verification, PairedRequestVerification):
            raise TypeError("request_verification has the wrong type")
        for episode, adjudication in (
            (self.clean_episode, self.clean_adjudication),
            (self.attack_episode, self.attack_adjudication),
        ):
            if not isinstance(adjudication, EpisodeAdjudication):
                raise TypeError("pair reconciliation requires episode adjudications")
            if adjudication.evidence.phase is not EpisodePhase.INITIAL:
                raise ValueError("pair reconciliation covers initial evidence only")
            if adjudication.evidence.scheduled_episode.digest != episode.digest:
                raise ValueError("pair adjudication is bound to the wrong scheduled child")
        clean_evidence = self.clean_adjudication.evidence
        attack_evidence = self.attack_adjudication.evidence
        if self.request_verification.clean.digest != clean_evidence.request_binding.digest:
            raise ValueError("clean evidence is not bound to the paired-request proof")
        if self.request_verification.attack.digest != attack_evidence.request_binding.digest:
            raise ValueError("attack evidence is not bound to the paired-request proof")
        shared_runtime_fields = (
            "request_contract_sha256",
            "renderer_contract_sha256",
            "extraction_contract_sha256",
            "server_binary_sha256",
            "dependency_lock_sha256",
            "controller_sha256",
            "harness_sha256",
        )
        drift = [
            field
            for field in shared_runtime_fields
            if getattr(clean_evidence, field) != getattr(attack_evidence, field)
        ]
        if drift:
            raise ValueError(f"paired-arm runtime invariant drift: {drift}")
        if (
            clean_evidence.evaluator_secret_opening.digest
            != attack_evidence.evaluator_secret_opening.digest
        ):
            raise ValueError("paired arms use different evaluator-secret openings")
        clean_runtime = clean_evidence.runtime_attestation
        attack_runtime = attack_evidence.runtime_attestation
        for field in (
            "observed_tool_world_sha256",
            "attestation_contract_sha256",
            "verification_complete",
            "binary_measurements_verified",
        ):
            if getattr(clean_runtime, field) != getattr(attack_runtime, field):
                raise ValueError(f"paired-arm runtime attestation drift: {field}")
        clean_prestate = clean_evidence.prestate
        attack_prestate = attack_evidence.prestate
        for field in ("fixture_sha256", "base_world_state_sha256"):
            if getattr(clean_prestate, field) != getattr(attack_prestate, field):
                raise ValueError(f"paired-arm base prestate drift: {field}")
        if clean_evidence.request_context_sha256 == attack_evidence.request_context_sha256:
            raise ValueError("paired arms must render different verified contexts")
        if clean_evidence.request_semantics_sha256 == attack_evidence.request_semantics_sha256:
            raise ValueError("paired arms must bind distinct context-bearing request semantics")
        if clean_evidence.request_envelope_sha256 == attack_evidence.request_envelope_sha256:
            raise ValueError("paired arms must bind distinct exact request envelopes")

    def document(self) -> dict[str, Any]:
        return {
            "scheduled_pair_sha256": self.scheduled_pair.digest,
            "clean_episode_sha256": self.clean_episode.digest,
            "attack_episode_sha256": self.attack_episode.digest,
            "paired_request_verification_sha256": self.request_verification.digest,
            "clean_adjudication_sha256": self.clean_adjudication.digest,
            "attack_adjudication_sha256": self.attack_adjudication.digest,
        }

    @property
    def digest(self) -> str:
        return _canonical_sha("pair_terminal_reconciliation", self.document())


def require_execution_authority() -> None:
    """Fail closed until a separately reviewed controller and admission act exist."""

    raise RuntimeError(
        f"{EXECUTION_STATUS}: pure contracts do not authorize a model, tool, or GPU run"
    )
