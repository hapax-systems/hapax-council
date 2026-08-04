"""Strict, execution-inert persistence for complete agentic run graphs.

The live contracts in :mod:`conservatory.agentic_contract` deliberately model
validated in-memory identities.  This module adds a closed persistence boundary:
canonical JSON, explicit recursive codecs, honest terminal records for attempts
that never acquired complete evidence, run-level cardinality checks, and derived
summary counts.  It performs no I/O beyond converting caller-provided bytes.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, fields
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, Self

from .contract import (
    CONTRACT_VERSION,
    CandidateContentKey,
    CandidateMaterialState,
    CandidateProvenanceKey,
    ContextArm,
    EpisodeAdjudication,
    EpisodeEvidenceIdentity,
    EpisodePhase,
    EpisodePrestate,
    EvaluatorSecretOpening,
    ImpactState,
    JointOutcome,
    JointOutcomeClass,
    MechanicalCheckerResult,
    PairedRequestVerification,
    PairTerminalReconciliation,
    ProbabilityMeasureContract,
    ReplayComparison,
    ReplayComparisonAlgorithm,
    ReplayComparisonStatus,
    ReplayLawContract,
    ReplayLink,
    RequestBinding,
    RuntimeAttestation,
    ScenarioPairContract,
    ScheduledEpisodeKey,
    ScheduledPairKey,
    TerminalDisposition,
    TransformationVerification,
    TrialAssignmentKey,
    UtilityState,
    VerificationDecision,
)
from .errors import VerificationResourceLimitExceeded
from .limits import DEFAULT_VERIFICATION_LIMITS, VerificationLimits, validate_json_resource_envelope

if TYPE_CHECKING:
    from enum import StrEnum

RUN_GRAPH_SCHEMA_VERSION = 1
RUN_GRAPH_DOCUMENT_TYPE = "agentic_run_graph"
TERMINAL_ATTEMPT_SCHEMA_VERSION = 1
TERMINAL_ATTEMPT_DOCUMENT_TYPE = "agentic_terminal_attempt_record"
RUN_SUMMARY_SCHEMA_VERSION = 1
RUN_SUMMARY_DOCUMENT_TYPE = "agentic_run_summary"
RUN_ARTIFACT_DATA_CLASSES = (
    "allocation_witness",
    "authority_contracts",
    "candidate_content_registry",
    "candidate_provenance",
    "evaluator_commitment",
    "evaluator_reveal",
    "manifest_snapshot",
    "novelty_registry",
    "pair_reconciliation",
    "probability_measure_contract",
    "schedule_plan",
    "scheduled_pair_contracts",
    "schema_registry",
    "summary",
)
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _sha(name: str, value: object) -> str:
    if type(value) is not str or SHA_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _token(name: str, value: object) -> str:
    if type(value) is not str or TOKEN_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a bounded identity token")
    return value


def _nonnegative_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _exact_dict(name: str, value: object, expected: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != expected:
        raise ValueError(f"{name} schema mismatch")
    return value


def _precheck_encoded_summary_cardinalities(value: object) -> None:
    """Bound fixed summary arrays before recursively constructing their rows."""

    encoded = _exact_dict("encoded run summary", value, {"fields", "type"})
    if encoded["type"] != "agentic_run_summary":
        raise ValueError("encoded run summary type mismatch")
    summary_fields = encoded["fields"]
    if type(summary_fields) is not dict:
        raise TypeError("encoded run summary fields must be an exact object")
    for field_name, expected_count in (
        ("initial_outcome_counts", len(JointOutcomeClass)),
        ("all_attempt_outcome_counts", len(JointOutcomeClass)),
        ("replay_status_counts", len(ReplayComparisonStatus)),
    ):
        rows = summary_fields.get(field_name)
        if type(rows) is not list:
            raise TypeError(f"encoded run summary {field_name} must be a list")
        if len(rows) != expected_count:
            raise ValueError(
                f"encoded run summary {field_name} must contain exactly {expected_count} rows"
            )


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _semantic_sha256(document_type: str, payload: object) -> str:
    """Domain-separated aggregate identity for one run artifact's semantics."""

    return hashlib.sha256(
        _canonical_json_bytes(
            {
                "contract_version": CONTRACT_VERSION,
                "document_type": document_type,
                "payload": payload,
            }
        )
    ).hexdigest()


def parse_strict_canonical_json(
    payload: bytes,
    *,
    limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
) -> object:
    """Parse one canonical UTF-8 JSON value without losing lexical evidence."""

    if type(payload) is not bytes:
        raise TypeError("canonical JSON input must be exact bytes")
    validate_json_resource_envelope(
        payload,
        label="canonical run document",
        limits=limits,
    )
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("run graph is not strict UTF-8") from exc

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")

    def parse_float(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError(f"non-finite JSON number: {value}")
        return parsed

    try:
        document = json.loads(
            text,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
            parse_float=parse_float,
        )
    except json.JSONDecodeError as exc:
        raise ValueError("run graph is not valid JSON") from exc
    try:
        canonical = _canonical_json_bytes(document)
    except (TypeError, ValueError) as exc:
        raise ValueError("run graph cannot be represented as canonical JSON") from exc
    if payload != canonical:
        raise ValueError("run graph bytes are not canonical JSON")
    return document


@dataclass(frozen=True, slots=True)
class PartialMechanicalObservation:
    """Retained predicates that may legitimately be unresolved at termination."""

    utility: UtilityState
    unauthorized_impact: ImpactState
    utility_witness_sha256: str | None = None
    security_witness_sha256: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.utility, UtilityState):
            raise TypeError("utility must be a UtilityState")
        if not isinstance(self.unauthorized_impact, ImpactState):
            raise TypeError("unauthorized_impact must be an ImpactState")
        if self.utility is UtilityState.UNKNOWN:
            if self.utility_witness_sha256 is not None:
                raise ValueError("unknown utility cannot carry a utility witness")
        elif self.utility_witness_sha256 is None:
            raise ValueError("resolved utility requires a retained witness")
        else:
            _sha("utility_witness_sha256", self.utility_witness_sha256)
        if self.unauthorized_impact is ImpactState.UNKNOWN:
            if self.security_witness_sha256 is not None:
                raise ValueError("unknown impact cannot carry a security witness")
        elif self.security_witness_sha256 is None:
            raise ValueError("resolved impact requires a retained witness")
        else:
            _sha("security_witness_sha256", self.security_witness_sha256)

    @classmethod
    def from_adjudication(cls, adjudication: EpisodeAdjudication) -> Self:
        if not isinstance(adjudication, EpisodeAdjudication):
            raise TypeError("adjudication must be an EpisodeAdjudication")
        checker = adjudication.checker_result
        return cls(
            checker.utility,
            checker.unauthorized_impact,
            checker.utility_witness_sha256,
            checker.security_witness_sha256,
        )


@dataclass(frozen=True, slots=True)
class TerminalAttemptRecord:
    """Exactly one terminal state for one scheduled episode attempt."""

    scheduled_episode: ScheduledEpisodeKey
    phase: EpisodePhase
    attempt_ordinal: int
    disposition: TerminalDisposition
    observation: PartialMechanicalObservation
    control_evidence_sha256: str
    adjudication: EpisodeAdjudication | None
    failure_artifact_sha256: str | None
    failure_witness_sha256: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.scheduled_episode, ScheduledEpisodeKey):
            raise TypeError("scheduled_episode must be a ScheduledEpisodeKey")
        if not isinstance(self.phase, EpisodePhase):
            raise TypeError("phase must be an EpisodePhase")
        _nonnegative_int("attempt_ordinal", self.attempt_ordinal)
        if self.phase is EpisodePhase.INITIAL and self.attempt_ordinal != 0:
            raise ValueError("initial terminal attempts require ordinal zero")
        if self.phase is EpisodePhase.REPLAY and self.attempt_ordinal < 1:
            raise ValueError("replay terminal attempts require a positive ordinal")
        if not isinstance(self.disposition, TerminalDisposition):
            raise TypeError("disposition must be a TerminalDisposition")
        if not isinstance(self.observation, PartialMechanicalObservation):
            raise TypeError("observation must be a PartialMechanicalObservation")
        _sha("control_evidence_sha256", self.control_evidence_sha256)
        if (
            self.disposition is TerminalDisposition.INCOMPLETE_REPLAY
            and self.phase is not EpisodePhase.REPLAY
        ):
            raise ValueError("INCOMPLETE_REPLAY requires replay phase")

        if self.disposition is TerminalDisposition.COMPLETED:
            if not isinstance(self.adjudication, EpisodeAdjudication):
                raise ValueError("completed attempts require an adjudication")
            if self.failure_artifact_sha256 is not None:
                raise ValueError("completed attempts cannot carry a failure artifact")
            if self.failure_witness_sha256 is not None:
                raise ValueError("completed attempts cannot carry a failure witness")
            evidence = self.adjudication.evidence
            if evidence.scheduled_episode != self.scheduled_episode:
                raise ValueError("completed adjudication targets a different episode")
            if evidence.phase is not self.phase or evidence.attempt_ordinal != self.attempt_ordinal:
                raise ValueError("completed adjudication targets a different attempt")
            if self.adjudication.disposition is not TerminalDisposition.COMPLETED:
                raise ValueError("completed attempt requires completed adjudication")
            if self.observation != PartialMechanicalObservation.from_adjudication(
                self.adjudication
            ):
                raise ValueError("completed observation differs from adjudication")
            return

        if self.adjudication is not None:
            raise ValueError("noncompleted attempts forbid adjudication")
        _sha("failure_artifact_sha256", self.failure_artifact_sha256)
        _sha("failure_witness_sha256", self.failure_witness_sha256)
        if self.disposition.category == "invalid":
            if (
                self.observation.utility is not UtilityState.UNKNOWN
                or self.observation.unauthorized_impact is not ImpactState.UNKNOWN
            ):
                raise ValueError("invalid attempts cannot resolve predicates")
        elif self.disposition.category == "incomplete":
            if self.observation.unauthorized_impact is ImpactState.ABSENT:
                raise ValueError("incomplete attempts cannot establish impact absence")
        else:
            raise ValueError("unsupported noncompleted terminal disposition")
        # Reuse the mechanical outcome lattice as an additional compatibility check.
        _ = self.outcome

    @property
    def key(self) -> tuple[str, EpisodePhase, int]:
        return self.scheduled_episode.digest, self.phase, self.attempt_ordinal

    @property
    def outcome(self) -> JointOutcome:
        if self.adjudication is not None:
            return self.adjudication.outcome
        return JointOutcome.classify(
            self.disposition,
            utility=self.observation.utility,
            unauthorized_impact=self.observation.unauthorized_impact,
            impact_witness_sha256=(
                self.observation.security_witness_sha256
                if self.observation.unauthorized_impact is ImpactState.PRESENT
                else None
            ),
        )

    def to_bytes(self) -> bytes:
        """Canonical terminal-disposition artifact bytes for custody binding."""

        return _canonical_json_bytes(
            {
                "contract_version": CONTRACT_VERSION,
                "document_type": TERMINAL_ATTEMPT_DOCUMENT_TYPE,
                "payload": _encode_registered(self),
                "schema_version": TERMINAL_ATTEMPT_SCHEMA_VERSION,
            }
        )

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_bytes()).hexdigest()

    @classmethod
    def from_bytes(
        cls,
        payload: bytes,
        *,
        limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
    ) -> Self:
        document = parse_strict_canonical_json(payload, limits=limits)
        envelope = _exact_dict(
            "terminal attempt envelope",
            document,
            {"schema_version", "contract_version", "document_type", "payload"},
        )
        if type(envelope["schema_version"]) is not int or (
            envelope["schema_version"] != TERMINAL_ATTEMPT_SCHEMA_VERSION
        ):
            raise ValueError("terminal attempt schema_version mismatch")
        if envelope["contract_version"] != CONTRACT_VERSION:
            raise ValueError("terminal attempt contract_version mismatch")
        if envelope["document_type"] != TERMINAL_ATTEMPT_DOCUMENT_TYPE:
            raise ValueError("terminal attempt document_type mismatch")
        result = _decode_registered(envelope["payload"], cls)
        if result.to_bytes() != payload:
            raise ValueError("terminal attempt does not round-trip to identical canonical bytes")
        return result


@dataclass(frozen=True, slots=True)
class OutcomeCount:
    outcome_class: JointOutcomeClass
    count: int

    def __post_init__(self) -> None:
        if not isinstance(self.outcome_class, JointOutcomeClass):
            raise TypeError("outcome_class must be a JointOutcomeClass")
        _nonnegative_int("count", self.count)


@dataclass(frozen=True, slots=True)
class ReplayStatusCount:
    status: ReplayComparisonStatus
    count: int

    def __post_init__(self) -> None:
        if not isinstance(self.status, ReplayComparisonStatus):
            raise TypeError("status must be a ReplayComparisonStatus")
        _nonnegative_int("count", self.count)


@dataclass(frozen=True, slots=True)
class RunArtifactBinding:
    """Versioned semantic-to-exact-byte binding for one run-scoped artifact."""

    data_class: str
    semantic_reference_sha256: str
    encoded_artifact_sha256: str

    def __post_init__(self) -> None:
        if type(self.data_class) is not str:
            raise TypeError("data_class must be exact text")
        if self.data_class not in RUN_ARTIFACT_DATA_CLASSES:
            raise ValueError("data_class is not an allowed run artifact class")
        _sha("semantic_reference_sha256", self.semantic_reference_sha256)
        _sha("encoded_artifact_sha256", self.encoded_artifact_sha256)


@dataclass(frozen=True, slots=True)
class AgenticRunSummary:
    """Integer-only summary derived from a fully reconciled graph."""

    scheduled_pair_count: int
    scheduled_episode_count: int
    terminal_attempt_count: int
    initial_attempt_count: int
    replay_attempt_count: int
    completed_attempt_count: int
    incomplete_attempt_count: int
    invalid_attempt_count: int
    initial_effectiveness_denominator: int
    initial_all_attempt_denominator: int
    initial_observed_harm_numerator: int
    all_attempt_denominator: int
    all_attempt_observed_harm_numerator: int
    unknown_impact_attempt_count: int
    initial_clean_incomplete_count: int
    initial_attack_incomplete_count: int
    initial_clean_unknown_impact_count: int
    initial_attack_unknown_impact_count: int
    pair_reconciliation_count: int
    replay_comparison_count: int
    initial_outcome_counts: tuple[OutcomeCount, ...]
    all_attempt_outcome_counts: tuple[OutcomeCount, ...]
    replay_status_counts: tuple[ReplayStatusCount, ...]

    def __post_init__(self) -> None:
        for item in fields(self):
            if item.name in {
                "initial_outcome_counts",
                "all_attempt_outcome_counts",
                "replay_status_counts",
            }:
                continue
            _nonnegative_int(item.name, getattr(self, item.name))
        for name in ("initial_outcome_counts", "all_attempt_outcome_counts"):
            rows = getattr(self, name)
            if type(rows) is not tuple or any(not isinstance(row, OutcomeCount) for row in rows):
                raise TypeError(f"{name} must be a tuple of OutcomeCount")
        expected_classes = tuple(sorted(JointOutcomeClass, key=lambda item: item.value))
        if tuple(row.outcome_class for row in self.initial_outcome_counts) != expected_classes:
            raise ValueError("initial_outcome_counts must cover each outcome class canonically")
        if tuple(row.outcome_class for row in self.all_attempt_outcome_counts) != expected_classes:
            raise ValueError("all_attempt_outcome_counts must cover each outcome class canonically")
        if sum(row.count for row in self.initial_outcome_counts) != self.initial_attempt_count:
            raise ValueError("initial outcome counts do not sum to initial attempts")
        if sum(row.count for row in self.all_attempt_outcome_counts) != self.terminal_attempt_count:
            raise ValueError("all-attempt outcome counts do not sum to terminal attempts")
        if type(self.replay_status_counts) is not tuple or any(
            not isinstance(row, ReplayStatusCount) for row in self.replay_status_counts
        ):
            raise TypeError("replay_status_counts must be a tuple of ReplayStatusCount")
        expected_statuses = tuple(sorted(ReplayComparisonStatus, key=lambda item: item.value))
        if tuple(row.status for row in self.replay_status_counts) != expected_statuses:
            raise ValueError("replay_status_counts must cover each status canonically")
        if sum(row.count for row in self.replay_status_counts) != self.replay_attempt_count:
            raise ValueError("replay status counts do not sum to replay attempts")
        if self.scheduled_episode_count != 2 * self.scheduled_pair_count:
            raise ValueError("scheduled episode count is not exactly two arms per pair")
        if self.initial_attempt_count != self.scheduled_episode_count:
            raise ValueError("initial attempt denominator differs from schedule coverage")
        if self.terminal_attempt_count != (self.initial_attempt_count + self.replay_attempt_count):
            raise ValueError("terminal attempt phase counts do not reconcile")
        if self.terminal_attempt_count != (
            self.completed_attempt_count
            + self.incomplete_attempt_count
            + self.invalid_attempt_count
        ):
            raise ValueError("terminal disposition counts do not reconcile")
        if self.initial_all_attempt_denominator != self.initial_attempt_count:
            raise ValueError("initial all-attempt denominator is not total initial attempts")
        if self.all_attempt_denominator != self.terminal_attempt_count:
            raise ValueError("all-attempt denominator is not total terminal attempts")
        if self.initial_effectiveness_denominator > self.initial_attempt_count:
            raise ValueError("initial effectiveness denominator exceeds attempts")
        if self.initial_observed_harm_numerator > self.initial_attempt_count:
            raise ValueError("initial harm numerator exceeds attempts")
        if self.all_attempt_observed_harm_numerator > self.terminal_attempt_count:
            raise ValueError("all-attempt harm numerator exceeds attempts")
        if self.pair_reconciliation_count > self.scheduled_pair_count:
            raise ValueError("pair reconciliation count exceeds scheduled pairs")
        if self.replay_comparison_count > self.replay_attempt_count:
            raise ValueError("replay comparison count exceeds replay attempts")
        for name in (
            "initial_clean_incomplete_count",
            "initial_attack_incomplete_count",
            "initial_clean_unknown_impact_count",
            "initial_attack_unknown_impact_count",
        ):
            if getattr(self, name) > self.scheduled_pair_count:
                raise ValueError(f"{name} exceeds scheduled arm count")

        initial = {row.outcome_class: row.count for row in self.initial_outcome_counts}
        all_attempts = {row.outcome_class: row.count for row in self.all_attempt_outcome_counts}
        replay = {row.status: row.count for row in self.replay_status_counts}
        if any(all_attempts[key] < initial[key] for key in JointOutcomeClass):
            raise ValueError("all-attempt outcome count is below its initial-attempt count")
        completed_classes = (
            JointOutcomeClass.SAFE_AND_USEFUL,
            JointOutcomeClass.SAFE_BUT_NOT_USEFUL,
            JointOutcomeClass.UNSAFE_EFFECT,
        )
        incomplete_classes = (
            JointOutcomeClass.UNSAFE_EFFECT_INCOMPLETE,
            JointOutcomeClass.INCOMPLETE,
        )
        if self.completed_attempt_count != sum(all_attempts[key] for key in completed_classes):
            raise ValueError("completed disposition count differs from outcome classes")
        if self.incomplete_attempt_count != sum(all_attempts[key] for key in incomplete_classes):
            raise ValueError("incomplete disposition count differs from outcome classes")
        if self.invalid_attempt_count != all_attempts[JointOutcomeClass.INVALID]:
            raise ValueError("invalid disposition count differs from outcome classes")
        if self.initial_effectiveness_denominator != sum(initial[key] for key in completed_classes):
            raise ValueError("initial effectiveness denominator differs from completed outcomes")
        if self.initial_observed_harm_numerator != (
            initial[JointOutcomeClass.UNSAFE_EFFECT]
            + initial[JointOutcomeClass.UNSAFE_EFFECT_INCOMPLETE]
        ):
            raise ValueError("initial harm numerator differs from observed unsafe outcomes")
        if self.all_attempt_observed_harm_numerator != (
            all_attempts[JointOutcomeClass.UNSAFE_EFFECT]
            + all_attempts[JointOutcomeClass.UNSAFE_EFFECT_INCOMPLETE]
        ):
            raise ValueError("all-attempt harm numerator differs from observed unsafe outcomes")
        if self.unknown_impact_attempt_count != (
            all_attempts[JointOutcomeClass.INCOMPLETE] + all_attempts[JointOutcomeClass.INVALID]
        ):
            raise ValueError("unknown-impact count differs from outcome classes")
        initial_incomplete = sum(initial[key] for key in incomplete_classes)
        if (
            self.initial_clean_incomplete_count + self.initial_attack_incomplete_count
            != initial_incomplete
        ):
            raise ValueError("initial incomplete arm counts differ from outcome classes")
        initial_unknown = initial[JointOutcomeClass.INCOMPLETE] + initial[JointOutcomeClass.INVALID]
        if (
            self.initial_clean_unknown_impact_count + self.initial_attack_unknown_impact_count
            != initial_unknown
        ):
            raise ValueError("initial unknown-impact arm counts differ from outcome classes")

        replay_outcomes = {key: all_attempts[key] - initial[key] for key in JointOutcomeClass}
        replay_completed = sum(replay_outcomes[key] for key in completed_classes)
        replay_incomplete = sum(replay_outcomes[key] for key in incomplete_classes)
        replay_invalid = replay_outcomes[JointOutcomeClass.INVALID]
        if replay[ReplayComparisonStatus.INCOMPLETE] != replay_incomplete:
            raise ValueError("replay incomplete status count differs from replay outcomes")
        if replay[ReplayComparisonStatus.INVALID] != replay_invalid:
            raise ValueError("replay invalid status count differs from replay outcomes")
        if (
            replay[ReplayComparisonStatus.AGREES] + replay[ReplayComparisonStatus.DISAGREES]
            != replay_completed
        ):
            raise ValueError("replay completed status counts differ from replay outcomes")
        if self.replay_comparison_count != replay_completed:
            raise ValueError("replay comparison count differs from completed replay outcomes")

    def to_bytes(self) -> bytes:
        """Canonical summary artifact bytes for custody binding."""

        return _canonical_json_bytes(
            {
                "contract_version": CONTRACT_VERSION,
                "document_type": RUN_SUMMARY_DOCUMENT_TYPE,
                "payload": _encode_registered(self),
                "schema_version": RUN_SUMMARY_SCHEMA_VERSION,
            }
        )

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_bytes()).hexdigest()

    @classmethod
    def from_bytes(
        cls,
        payload: bytes,
        *,
        limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
    ) -> Self:
        document = parse_strict_canonical_json(payload, limits=limits)
        envelope = _exact_dict(
            "run summary envelope",
            document,
            {"schema_version", "contract_version", "document_type", "payload"},
        )
        if type(envelope["schema_version"]) is not int or (
            envelope["schema_version"] != RUN_SUMMARY_SCHEMA_VERSION
        ):
            raise ValueError("run summary schema_version mismatch")
        if envelope["contract_version"] != CONTRACT_VERSION:
            raise ValueError("run summary contract_version mismatch")
        if envelope["document_type"] != RUN_SUMMARY_DOCUMENT_TYPE:
            raise ValueError("run summary document_type mismatch")
        _precheck_encoded_summary_cardinalities(envelope["payload"])
        result = _decode_registered(envelope["payload"], cls)
        if result.to_bytes() != payload:
            raise ValueError("run summary does not round-trip to canonical bytes")
        return result


def _pair_sort_key(pair: ScheduledPairKey) -> tuple[int, int, str, str]:
    return (
        pair.cycle,
        pair.pair_position,
        pair.scenario_pair.pair_id,
        pair.digest,
    )


def _attempt_sort_key(record: TerminalAttemptRecord) -> tuple[Any, ...]:
    pair_key = _pair_sort_key(record.scheduled_episode.scheduled_pair)
    arm = 0 if record.scheduled_episode.context_arm is ContextArm.CLEAN else 1
    phase = 0 if record.phase is EpisodePhase.INITIAL else 1
    return (*pair_key, arm, phase, record.attempt_ordinal)


def _reconciliation_sort_key(
    reconciliation: PairTerminalReconciliation,
) -> tuple[int, int, str, str]:
    return _pair_sort_key(reconciliation.scheduled_pair)


def _replay_comparison_sort_key(comparison: ReplayComparison) -> tuple[Any, ...]:
    episode = comparison.link.replay.scheduled_episode
    pair_key = _pair_sort_key(episode.scheduled_pair)
    arm = 0 if episode.context_arm is ContextArm.CLEAN else 1
    return (*pair_key, arm, comparison.link.replay.attempt_ordinal, comparison.digest)


@dataclass(frozen=True, slots=True)
class AgenticRunGraph:
    """Complete scheduled-run graph with authoritative attempt cardinality."""

    run_id: str
    manifest_sha256: str
    run_artifact_bindings: tuple[RunArtifactBinding, ...]
    scheduled_pairs: tuple[ScheduledPairKey, ...]
    terminal_attempts: tuple[TerminalAttemptRecord, ...]
    replay_comparisons: tuple[ReplayComparison, ...]
    pair_reconciliations: tuple[PairTerminalReconciliation, ...]

    SCHEMA_VERSION: ClassVar[int] = RUN_GRAPH_SCHEMA_VERSION
    DOCUMENT_TYPE: ClassVar[str] = RUN_GRAPH_DOCUMENT_TYPE

    @staticmethod
    def derive_run_artifact_semantic_references(
        scheduled_pairs: tuple[ScheduledPairKey, ...],
        terminal_attempts: tuple[TerminalAttemptRecord, ...],
        replay_comparisons: tuple[ReplayComparison, ...],
        pair_reconciliations: tuple[PairTerminalReconciliation, ...],
    ) -> dict[str, str]:
        """Derive every run-artifact semantic identity from the closed graph.

        Encoded artifact hashes remain independent because several artifacts are
        implementation-specific containers.  Their semantic side, however, is
        never caller-chosen: every reference is a deterministic projection of
        scheduled or observed graph state.
        """

        if not scheduled_pairs:
            raise ValueError("semantic references require scheduled pairs")
        first = scheduled_pairs[0]
        summary = AgenticRunGraph.derive_summary(
            scheduled_pairs,
            terminal_attempts,
            replay_comparisons,
            pair_reconciliations,
        )
        openings = []
        for record in terminal_attempts:
            if record.adjudication is None:
                continue
            opening = record.adjudication.evidence.evaluator_secret_opening
            openings.append(
                {
                    "attempt_ordinal": record.attempt_ordinal,
                    "evaluator_secret_opening_sha256": opening.digest,
                    "phase": record.phase.value,
                    "realization_sha256": opening.realization_sha256,
                    "scheduled_episode_sha256": record.scheduled_episode.digest,
                }
            )
        return {
            "allocation_witness": _semantic_sha256(
                "run_allocation_semantics_v1",
                [
                    {
                        "crn_seed": pair.crn_seed,
                        "cycle": pair.cycle,
                        "pair_position": pair.pair_position,
                        "scheduled_pair_sha256": pair.digest,
                        "trial_assignment_sha256": pair.trial_assignment.digest,
                    }
                    for pair in scheduled_pairs
                ],
            ),
            "authority_contracts": _semantic_sha256(
                "run_authority_contract_semantics_v1",
                [
                    {
                        "authority_graph_sha256": (pair.scenario_pair.authority_graph_sha256),
                        "horizon_law_sha256": pair.scenario_pair.horizon_law_sha256,
                        "scheduled_pair_sha256": pair.digest,
                        "security_checker_sha256": (pair.scenario_pair.security_checker_sha256),
                        "tool_schema_sha256": pair.scenario_pair.tool_schema_sha256,
                        "tool_world_sha256": pair.scenario_pair.tool_world_sha256,
                        "utility_checker_sha256": (pair.scenario_pair.utility_checker_sha256),
                    }
                    for pair in scheduled_pairs
                ],
            ),
            "candidate_content_registry": _semantic_sha256(
                "run_candidate_content_registry_semantics_v1",
                sorted({pair.candidate_content.digest for pair in scheduled_pairs}),
            ),
            "candidate_provenance": _semantic_sha256(
                "run_candidate_provenance_semantics_v1",
                sorted({pair.candidate_provenance.digest for pair in scheduled_pairs}),
            ),
            "evaluator_commitment": _semantic_sha256(
                "run_evaluator_commitment_semantics_v1",
                sorted(
                    {
                        pair.scenario_pair.evaluator_secret_commitment_sha256
                        for pair in scheduled_pairs
                    }
                ),
            ),
            "evaluator_reveal": _semantic_sha256(
                "run_evaluator_reveal_semantics_v1",
                openings,
            ),
            "manifest_snapshot": first.manifest_sha256,
            "novelty_registry": _semantic_sha256(
                "run_novelty_registry_semantics_v1",
                [
                    {
                        "genesis_sha256": (
                            pair.candidate_provenance.novelty_registry_genesis_sha256
                        ),
                        "overlay_sha256": pair.novelty_registry_overlay_sha256,
                        "scheduled_pair_sha256": pair.digest,
                    }
                    for pair in scheduled_pairs
                ],
            ),
            "pair_reconciliation": _semantic_sha256(
                "run_pair_reconciliation_semantics_v1",
                [row.digest for row in pair_reconciliations],
            ),
            "probability_measure_contract": first.probability_measure.digest,
            "schedule_plan": first.plan_sha256,
            "scheduled_pair_contracts": _semantic_sha256(
                "run_scheduled_pair_contract_semantics_v1",
                [
                    {
                        "attack_episode_sha256": pair.children()[1].digest,
                        "clean_episode_sha256": pair.children()[0].digest,
                        "replay_law_sha256": pair.replay_law.digest,
                        "scheduled_pair_sha256": pair.digest,
                    }
                    for pair in scheduled_pairs
                ],
            ),
            "schema_registry": _semantic_sha256(
                "run_schema_registry_semantics_v1",
                {
                    "run_graph_schema_version": RUN_GRAPH_SCHEMA_VERSION,
                    "terminal_attempt_schema_version": (TERMINAL_ATTEMPT_SCHEMA_VERSION),
                    "run_summary_schema_version": RUN_SUMMARY_SCHEMA_VERSION,
                },
            ),
            "summary": summary.digest,
        }

    def __post_init__(self) -> None:
        _token("run_id", self.run_id)
        _sha("manifest_sha256", self.manifest_sha256)
        if type(self.run_artifact_bindings) is not tuple or any(
            not isinstance(row, RunArtifactBinding) for row in self.run_artifact_bindings
        ):
            raise TypeError("run_artifact_bindings must be a tuple of RunArtifactBinding")
        observed_artifact_classes = tuple(row.data_class for row in self.run_artifact_bindings)
        if observed_artifact_classes != RUN_ARTIFACT_DATA_CLASSES:
            raise ValueError(
                "run_artifact_bindings must exactly cover run artifact classes in canonical order"
            )
        artifact_bindings = {row.data_class: row for row in self.run_artifact_bindings}
        if type(self.scheduled_pairs) is not tuple or not self.scheduled_pairs:
            raise ValueError("scheduled_pairs must be a nonempty tuple")
        if any(not isinstance(pair, ScheduledPairKey) for pair in self.scheduled_pairs):
            raise TypeError("scheduled_pairs contain a wrong type")
        if self.scheduled_pairs != tuple(sorted(self.scheduled_pairs, key=_pair_sort_key)):
            raise ValueError("scheduled_pairs are not in canonical order")
        if type(self.terminal_attempts) is not tuple or any(
            not isinstance(record, TerminalAttemptRecord) for record in self.terminal_attempts
        ):
            raise TypeError("terminal_attempts must be a tuple of terminal records")
        if self.terminal_attempts != tuple(sorted(self.terminal_attempts, key=_attempt_sort_key)):
            raise ValueError("terminal_attempts are not in canonical order")
        if type(self.replay_comparisons) is not tuple or any(
            not isinstance(row, ReplayComparison) for row in self.replay_comparisons
        ):
            raise TypeError("replay_comparisons must be a tuple of comparisons")
        if self.replay_comparisons != tuple(
            sorted(self.replay_comparisons, key=_replay_comparison_sort_key)
        ):
            raise ValueError("replay_comparisons are not in canonical order")
        if type(self.pair_reconciliations) is not tuple or any(
            not isinstance(row, PairTerminalReconciliation) for row in self.pair_reconciliations
        ):
            raise TypeError("pair_reconciliations must be a tuple of reconciliations")
        if self.pair_reconciliations != tuple(
            sorted(self.pair_reconciliations, key=_reconciliation_sort_key)
        ):
            raise ValueError("pair_reconciliations are not in canonical order")

        first = self.scheduled_pairs[0]
        experiment_id = first.experiment_id
        plan_sha256 = first.plan_sha256
        probability_measure_sha256 = first.probability_measure.digest
        policy = first.policy
        history = first.history
        pair_by_digest: dict[str, ScheduledPairKey] = {}
        positions: set[tuple[int, int]] = set()
        planned_episodes: dict[str, ScheduledEpisodeKey] = {}
        for pair in self.scheduled_pairs:
            if pair.experiment_id != experiment_id:
                raise ValueError("scheduled pairs do not share one experiment")
            if pair.plan_sha256 != plan_sha256:
                raise ValueError("scheduled pairs do not share one plan")
            if pair.manifest_sha256 != self.manifest_sha256:
                raise ValueError("scheduled pair manifest differs from run manifest")
            if pair.probability_measure.digest != probability_measure_sha256:
                raise ValueError("scheduled pairs do not share one probability measure")
            if pair.policy != policy:
                raise ValueError("scheduled pairs do not share one policy")
            if pair.history != history:
                raise ValueError("scheduled pairs do not share one history")
            position = (pair.cycle, pair.pair_position)
            if position in positions:
                raise ValueError("duplicate scheduled semantic position")
            positions.add(position)
            if pair.digest in pair_by_digest:
                raise ValueError("duplicate scheduled pair identity")
            pair_by_digest[pair.digest] = pair
            for episode in pair.children():
                if episode.digest in planned_episodes:
                    raise ValueError("scheduled episode belongs to multiple pairs")
                planned_episodes[episode.digest] = episode

        attempts_by_key: dict[tuple[str, EpisodePhase, int], TerminalAttemptRecord] = {}
        initial_by_episode: dict[str, TerminalAttemptRecord] = {}
        replay_ordinals: dict[str, list[int]] = {}
        for record in self.terminal_attempts:
            episode_digest = record.scheduled_episode.digest
            planned = planned_episodes.get(episode_digest)
            if planned is None or planned != record.scheduled_episode:
                raise ValueError("terminal attempt is outside the scheduled plan")
            if record.key in attempts_by_key:
                raise ValueError("duplicate terminal attempt key")
            attempts_by_key[record.key] = record
            if record.phase is EpisodePhase.INITIAL:
                if episode_digest in initial_by_episode:
                    raise ValueError("duplicate initial terminal attempt")
                initial_by_episode[episode_digest] = record
            else:
                replay_law = record.scheduled_episode.scheduled_pair.replay_law
                if record.attempt_ordinal > replay_law.max_replays:
                    raise ValueError("replay ordinal exceeds the scheduled pair law")
                replay_ordinals.setdefault(episode_digest, []).append(record.attempt_ordinal)
        if set(initial_by_episode) != set(planned_episodes):
            raise ValueError("initial terminal attempts do not exactly cover the schedule")
        for ordinals in replay_ordinals.values():
            ordered = sorted(ordinals)
            if ordered != list(range(1, max(ordered) + 1)):
                raise ValueError("replay ordinals are not contiguous from one")

        comparisons: dict[tuple[str, int], ReplayComparison] = {}
        for comparison in self.replay_comparisons:
            replay_evidence = comparison.link.replay
            episode_digest = replay_evidence.scheduled_episode.digest
            planned = planned_episodes.get(episode_digest)
            if planned is None or planned != replay_evidence.scheduled_episode:
                raise ValueError("replay comparison is outside the scheduled plan")
            key = (episode_digest, replay_evidence.attempt_ordinal)
            if key in comparisons:
                raise ValueError("duplicate replay comparison key")
            initial_record = attempts_by_key.get((episode_digest, EpisodePhase.INITIAL, 0))
            replay_record = attempts_by_key.get(
                (episode_digest, EpisodePhase.REPLAY, replay_evidence.attempt_ordinal)
            )
            if initial_record is None or replay_record is None:
                raise ValueError("replay comparison does not join recorded attempts")
            if (
                initial_record.disposition is not TerminalDisposition.COMPLETED
                or replay_record.disposition is not TerminalDisposition.COMPLETED
            ):
                raise ValueError("replay comparisons require two completed attempts")
            if (
                comparison.initial_adjudication != initial_record.adjudication
                or comparison.replay_adjudication != replay_record.adjudication
            ):
                raise ValueError("replay comparison does not use authoritative terminal attempts")
            comparisons[key] = comparison

        expected_comparisons: set[tuple[str, int]] = set()
        for record in self.terminal_attempts:
            if record.phase is not EpisodePhase.REPLAY:
                continue
            if record.disposition is not TerminalDisposition.COMPLETED:
                continue
            episode_digest = record.scheduled_episode.digest
            initial_record = initial_by_episode[episode_digest]
            if initial_record.disposition is not TerminalDisposition.COMPLETED:
                raise ValueError("a completed replay requires a completed authoritative initial")
            expected_comparisons.add((episode_digest, record.attempt_ordinal))
        if set(comparisons) != expected_comparisons:
            raise ValueError("replay comparisons must exist exactly for completed replay attempts")

        reconciliations: dict[str, PairTerminalReconciliation] = {}
        for reconciliation in self.pair_reconciliations:
            pair_digest = reconciliation.scheduled_pair.digest
            planned_pair = pair_by_digest.get(pair_digest)
            if planned_pair is None or planned_pair != reconciliation.scheduled_pair:
                raise ValueError("pair reconciliation is outside the scheduled plan")
            if pair_digest in reconciliations:
                raise ValueError("duplicate pair reconciliation")
            reconciliations[pair_digest] = reconciliation

        expected_reconciliations: set[str] = set()
        for pair_digest, pair in pair_by_digest.items():
            clean, attack = pair.children()
            clean_record = initial_by_episode[clean.digest]
            attack_record = initial_by_episode[attack.digest]
            both_completed = (
                clean_record.disposition is TerminalDisposition.COMPLETED
                and attack_record.disposition is TerminalDisposition.COMPLETED
            )
            if not both_completed:
                continue
            expected_reconciliations.add(pair_digest)
            reconciliation = reconciliations.get(pair_digest)
            if reconciliation is None:
                continue
            if (
                reconciliation.clean_adjudication != clean_record.adjudication
                or reconciliation.attack_adjudication != attack_record.adjudication
            ):
                raise ValueError("pair reconciliation does not use authoritative initial attempts")
        if set(reconciliations) != expected_reconciliations:
            raise ValueError("pair reconciliations must exist iff both initial arms completed")

        expected_semantic_references = self.derive_run_artifact_semantic_references(
            self.scheduled_pairs,
            self.terminal_attempts,
            self.replay_comparisons,
            self.pair_reconciliations,
        )
        if tuple(expected_semantic_references) != RUN_ARTIFACT_DATA_CLASSES:
            raise AssertionError("semantic reference derivation is out of registry order")
        for data_class, expected_sha256 in expected_semantic_references.items():
            if artifact_bindings[data_class].semantic_reference_sha256 != expected_sha256:
                raise ValueError(f"{data_class} binding differs from the graph semantic reference")
        if artifact_bindings["summary"].encoded_artifact_sha256 != self.summary.digest:
            raise ValueError("summary encoded artifact must equal canonical summary bytes")

    @property
    def experiment_id(self) -> str:
        return self.scheduled_pairs[0].experiment_id

    @property
    def plan_sha256(self) -> str:
        return self.scheduled_pairs[0].plan_sha256

    @property
    def probability_measure_sha256(self) -> str:
        return self.scheduled_pairs[0].probability_measure.digest

    @property
    def terminal_attempt_keys(self) -> tuple[tuple[str, EpisodePhase, int], ...]:
        """Canonical external reconciliation keys for every retained attempt."""

        return tuple(record.key for record in self.terminal_attempts)

    @property
    def terminal_disposition_profile(
        self,
    ) -> tuple[tuple[str, EpisodePhase, int, TerminalDisposition], ...]:
        """Canonical attempt keys paired with their terminal dispositions."""

        return tuple((*record.key, record.disposition) for record in self.terminal_attempts)

    @staticmethod
    def derive_summary(
        scheduled_pairs: tuple[ScheduledPairKey, ...],
        terminal_attempts: tuple[TerminalAttemptRecord, ...],
        replay_comparisons: tuple[ReplayComparison, ...],
        pair_reconciliations: tuple[PairTerminalReconciliation, ...],
    ) -> AgenticRunSummary:
        """Derive the canonical summary before constructing artifact bindings."""

        initial = tuple(
            record for record in terminal_attempts if record.phase is EpisodePhase.INITIAL
        )
        initial_counts = {
            outcome_class: sum(record.outcome.outcome_class is outcome_class for record in initial)
            for outcome_class in JointOutcomeClass
        }
        all_attempt_counts = {
            outcome_class: sum(
                record.outcome.outcome_class is outcome_class for record in terminal_attempts
            )
            for outcome_class in JointOutcomeClass
        }
        comparison_by_key = {
            (
                comparison.link.replay.scheduled_episode.digest,
                comparison.link.replay.attempt_ordinal,
            ): comparison
            for comparison in replay_comparisons
        }
        replay_statuses: list[ReplayComparisonStatus] = []
        for record in terminal_attempts:
            if record.phase is not EpisodePhase.REPLAY:
                continue
            if record.disposition.category == "incomplete":
                replay_statuses.append(ReplayComparisonStatus.INCOMPLETE)
            elif record.disposition.category == "invalid":
                replay_statuses.append(ReplayComparisonStatus.INVALID)
            else:
                replay_statuses.append(
                    comparison_by_key[
                        (record.scheduled_episode.digest, record.attempt_ordinal)
                    ].status
                )
        return AgenticRunSummary(
            scheduled_pair_count=len(scheduled_pairs),
            scheduled_episode_count=2 * len(scheduled_pairs),
            terminal_attempt_count=len(terminal_attempts),
            initial_attempt_count=len(initial),
            replay_attempt_count=len(terminal_attempts) - len(initial),
            completed_attempt_count=sum(
                record.disposition.category == "completed" for record in terminal_attempts
            ),
            incomplete_attempt_count=sum(
                record.disposition.category == "incomplete" for record in terminal_attempts
            ),
            invalid_attempt_count=sum(
                record.disposition.category == "invalid" for record in terminal_attempts
            ),
            initial_effectiveness_denominator=sum(
                record.outcome.effectiveness_eligible for record in initial
            ),
            initial_all_attempt_denominator=len(initial),
            initial_observed_harm_numerator=sum(
                record.outcome.counts_in_all_attempt_harm_lower_bound for record in initial
            ),
            all_attempt_denominator=len(terminal_attempts),
            all_attempt_observed_harm_numerator=sum(
                record.outcome.counts_in_all_attempt_harm_lower_bound
                for record in terminal_attempts
            ),
            unknown_impact_attempt_count=sum(
                record.outcome.unauthorized_impact is ImpactState.UNKNOWN
                for record in terminal_attempts
            ),
            initial_clean_incomplete_count=sum(
                record.scheduled_episode.context_arm is ContextArm.CLEAN
                and record.disposition.category == "incomplete"
                for record in initial
            ),
            initial_attack_incomplete_count=sum(
                record.scheduled_episode.context_arm is ContextArm.ATTACK
                and record.disposition.category == "incomplete"
                for record in initial
            ),
            initial_clean_unknown_impact_count=sum(
                record.scheduled_episode.context_arm is ContextArm.CLEAN
                and record.outcome.unauthorized_impact is ImpactState.UNKNOWN
                for record in initial
            ),
            initial_attack_unknown_impact_count=sum(
                record.scheduled_episode.context_arm is ContextArm.ATTACK
                and record.outcome.unauthorized_impact is ImpactState.UNKNOWN
                for record in initial
            ),
            pair_reconciliation_count=len(pair_reconciliations),
            replay_comparison_count=len(replay_comparisons),
            initial_outcome_counts=tuple(
                OutcomeCount(outcome_class, initial_counts[outcome_class])
                for outcome_class in sorted(JointOutcomeClass, key=lambda item: item.value)
            ),
            all_attempt_outcome_counts=tuple(
                OutcomeCount(outcome_class, all_attempt_counts[outcome_class])
                for outcome_class in sorted(JointOutcomeClass, key=lambda item: item.value)
            ),
            replay_status_counts=tuple(
                ReplayStatusCount(
                    status,
                    sum(observed is status for observed in replay_statuses),
                )
                for status in sorted(ReplayComparisonStatus, key=lambda item: item.value)
            ),
        )

    @property
    def summary(self) -> AgenticRunSummary:
        return self.derive_summary(
            self.scheduled_pairs,
            self.terminal_attempts,
            self.replay_comparisons,
            self.pair_reconciliations,
        )

    def to_bytes(self) -> bytes:
        payload = {
            "graph": _encode_registered(self),
            "summary": _encode_registered(self.summary),
        }
        return _canonical_json_bytes(
            {
                "contract_version": CONTRACT_VERSION,
                "document_type": RUN_GRAPH_DOCUMENT_TYPE,
                "payload": payload,
                "schema_version": RUN_GRAPH_SCHEMA_VERSION,
            }
        )

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_bytes()).hexdigest()

    @classmethod
    def from_bytes(
        cls,
        payload: bytes,
        *,
        limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
    ) -> Self:
        document = parse_strict_canonical_json(payload, limits=limits)
        envelope = _exact_dict(
            "run graph envelope",
            document,
            {"schema_version", "contract_version", "document_type", "payload"},
        )
        if type(envelope["schema_version"]) is not int or (
            envelope["schema_version"] != RUN_GRAPH_SCHEMA_VERSION
        ):
            raise ValueError("run graph schema_version mismatch")
        if envelope["contract_version"] != CONTRACT_VERSION:
            raise ValueError("run graph contract_version mismatch")
        if envelope["document_type"] != RUN_GRAPH_DOCUMENT_TYPE:
            raise ValueError("run graph document_type mismatch")
        body = _exact_dict("run graph payload", envelope["payload"], {"graph", "summary"})
        encoded_graph = _exact_dict("encoded run graph", body["graph"], {"fields", "type"})
        graph_fields = _exact_dict(
            "encoded run graph fields",
            encoded_graph["fields"],
            {
                "manifest_sha256",
                "pair_reconciliations",
                "replay_comparisons",
                "run_artifact_bindings",
                "run_id",
                "scheduled_pairs",
                "terminal_attempts",
            },
        )
        for field_name, maximum in (
            ("scheduled_pairs", limits.scheduled_pairs),
            ("pair_reconciliations", limits.scheduled_pairs),
            ("terminal_attempts", limits.terminal_attempts),
            ("replay_comparisons", limits.terminal_attempts),
        ):
            rows = graph_fields[field_name]
            if not isinstance(rows, list):
                raise TypeError(f"encoded run graph {field_name} must be a list")
            if len(rows) > maximum:
                raise VerificationResourceLimitExceeded(
                    f"encoded run graph {field_name} exceeds limit={maximum}; "
                    "next action: split the run into independently verified terminal bundles"
                )
        artifact_bindings = graph_fields["run_artifact_bindings"]
        if type(artifact_bindings) is not list:
            raise TypeError("encoded run graph run_artifact_bindings must be a list")
        if len(artifact_bindings) != len(RUN_ARTIFACT_DATA_CLASSES):
            raise ValueError(
                "encoded run graph run_artifact_bindings must have exact contract cardinality"
            )
        _precheck_encoded_summary_cardinalities(body["summary"])
        graph = _decode_registered(body["graph"], cls)
        persisted_summary = _decode_registered(body["summary"], AgenticRunSummary)
        if persisted_summary != graph.summary:
            raise ValueError("persisted run summary differs from derived summary")
        if graph.to_bytes() != payload:
            raise ValueError("run graph does not round-trip to identical canonical bytes")
        return graph


@dataclass(frozen=True, slots=True)
class _ObjectSpec:
    cls: type[Any]


@dataclass(frozen=True, slots=True)
class _EnumSpec:
    cls: type[StrEnum]


@dataclass(frozen=True, slots=True)
class _OptionalSpec:
    item: object


@dataclass(frozen=True, slots=True)
class _TupleSpec:
    item: object


@dataclass(frozen=True, slots=True)
class _ObjectCodec:
    tag: str
    cls: type[Any]
    field_specs: tuple[tuple[str, object], ...]


def _object(cls: type[Any]) -> _ObjectSpec:
    return _ObjectSpec(cls)


def _enum(cls: type[StrEnum]) -> _EnumSpec:
    return _EnumSpec(cls)


def _optional(item: object) -> _OptionalSpec:
    return _OptionalSpec(item)


def _tuple(item: object) -> _TupleSpec:
    return _TupleSpec(item)


_ENUM_TAGS = MappingProxyType(
    {
        ContextArm: "context_arm",
        EpisodePhase: "episode_phase",
        VerificationDecision: "verification_decision",
        TerminalDisposition: "terminal_disposition",
        JointOutcomeClass: "joint_outcome_class",
        UtilityState: "utility_state",
        ImpactState: "impact_state",
        CandidateMaterialState: "candidate_material_state",
        ReplayComparisonStatus: "replay_comparison_status",
        ReplayComparisonAlgorithm: "replay_comparison_algorithm",
    }
)


_CODECS = (
    _ObjectCodec(
        "joint_outcome",
        JointOutcome,
        (
            ("disposition", _enum(TerminalDisposition)),
            ("utility", _enum(UtilityState)),
            ("unauthorized_impact", _enum(ImpactState)),
            ("impact_witness_sha256", _optional(str)),
        ),
    ),
    _ObjectCodec(
        "transformation_verification",
        TransformationVerification,
        (
            ("clean_scenario_sha256", str),
            ("attack_scenario_sha256", str),
            ("attack_transformation_sha256", str),
            ("verifier_contract_sha256", str),
            ("target_visible_diff_sha256", str),
            ("observed_target_visible_diff_sha256", str),
            ("verifier_witness_sha256", str),
            ("verification_complete", bool),
            ("exact_single_transformation", bool),
            ("unmodified_surface_match", bool),
        ),
    ),
    _ObjectCodec(
        "scenario_pair_contract",
        ScenarioPairContract,
        (
            ("pair_id", str),
            ("scenario_family_sha256", str),
            ("base_task_sha256", str),
            ("fixture_sha256", str),
            ("tool_world_sha256", str),
            ("tool_schema_sha256", str),
            ("horizon_law_sha256", str),
            ("authority_graph_sha256", str),
            ("utility_checker_sha256", str),
            ("security_checker_sha256", str),
            ("evaluator_secret_commitment_sha256", str),
            ("transformation_verification", _object(TransformationVerification)),
        ),
    ),
    _ObjectCodec(
        "probability_measure_contract",
        ProbabilityMeasureContract,
        (
            ("estimand_sha256", str),
            ("task_sampling_frame_sha256", str),
            ("candidate_sampling_frame_sha256", str),
            ("seed_sampling_law_sha256", str),
            ("confirmatory_population_sha256", str),
            ("missingness_analysis_sha256", str),
            ("estimator_law_sha256", str),
            ("weighting_law_sha256", str),
            ("clustering_law_sha256", str),
            ("clustering_unit", str),
        ),
    ),
    _ObjectCodec(
        "candidate_content_key",
        CandidateContentKey,
        (
            ("scenario_family_sha256", str),
            ("attack_transformation_sha256", str),
            ("rendered_attack_sha256", str),
        ),
    ),
    _ObjectCodec(
        "candidate_provenance_key",
        CandidateProvenanceKey,
        (
            ("candidate_content_sha256", str),
            ("generator_contract_sha256", str),
            ("generator_artifact_sha256", str),
            ("source_lineage_sha256", str),
            ("parent_set_sha256", str),
            ("cluster_identity_sha256", str),
            ("novelty_registry_genesis_sha256", str),
            ("generator_seed", int),
        ),
    ),
    _ObjectCodec(
        "trial_assignment_key",
        TrialAssignmentKey,
        (
            ("candidate_content_sha256", str),
            ("target_model_sha256", str),
            ("authority_graph_sha256", str),
            ("utility_checker_sha256", str),
            ("security_checker_sha256", str),
            ("generation_law_sha256", str),
            ("replicate_index", int),
        ),
    ),
    _ObjectCodec(
        "replay_law_contract",
        ReplayLawContract,
        (
            ("reconstruction_law_sha256", str),
            ("max_replays", int),
            ("comparison_algorithm", _enum(ReplayComparisonAlgorithm)),
            ("initial_outcome_authoritative", bool),
        ),
    ),
    _ObjectCodec(
        "scheduled_pair_key",
        ScheduledPairKey,
        (
            ("experiment_id", str),
            ("scenario_pair", _object(ScenarioPairContract)),
            ("probability_measure", _object(ProbabilityMeasureContract)),
            ("policy", str),
            ("history", str),
            ("cycle", int),
            ("pair_position", int),
            ("crn_seed", int),
            ("plan_sha256", str),
            ("scheduler_state_sha256", str),
            ("candidate_content", _object(CandidateContentKey)),
            ("candidate_provenance", _object(CandidateProvenanceKey)),
            ("trial_assignment", _object(TrialAssignmentKey)),
            ("novelty_registry_overlay_sha256", str),
            ("replay_law", _object(ReplayLawContract)),
            ("manifest_sha256", str),
        ),
    ),
    _ObjectCodec(
        "scheduled_episode_key",
        ScheduledEpisodeKey,
        (
            ("scheduled_pair", _object(ScheduledPairKey)),
            ("context_arm", _enum(ContextArm)),
            ("selected_scenario_sha256", str),
        ),
    ),
    _ObjectCodec(
        "request_binding",
        RequestBinding,
        (
            ("scheduled_episode", _object(ScheduledEpisodeKey)),
            ("request_contract_sha256", str),
            ("request_context_sha256", str),
            ("request_semantics_sha256", str),
            ("request_envelope_sha256", str),
            ("renderer_contract_sha256", str),
            ("renderer_witness_sha256", str),
            ("candidate_material_state", _enum(CandidateMaterialState)),
        ),
    ),
    _ObjectCodec(
        "evaluator_secret_opening",
        EvaluatorSecretOpening,
        (
            ("commitment_sha256", str),
            ("realization_sha256", str),
            ("opening_law_sha256", str),
            ("opening_witness_sha256", str),
            ("verification_complete", bool),
            ("opens_commitment", bool),
        ),
    ),
    _ObjectCodec(
        "runtime_attestation",
        RuntimeAttestation,
        (
            ("scheduled_episode", _object(ScheduledEpisodeKey)),
            ("served_model_sha256", str),
            ("server_binary_sha256", str),
            ("dependency_lock_sha256", str),
            ("controller_sha256", str),
            ("harness_sha256", str),
            ("observed_tool_world_sha256", str),
            ("attestation_contract_sha256", str),
            ("attestation_witness_sha256", str),
            ("verification_complete", bool),
            ("binary_measurements_verified", bool),
        ),
    ),
    _ObjectCodec(
        "episode_prestate",
        EpisodePrestate,
        (
            ("request_binding", _object(RequestBinding)),
            ("evaluator_secret_opening", _object(EvaluatorSecretOpening)),
            ("fixture_sha256", str),
            ("base_world_state_sha256", str),
            ("rendered_context_sha256", str),
            ("prestate_artifact_sha256", str),
            ("construction_witness_sha256", str),
        ),
    ),
    _ObjectCodec(
        "paired_request_verification",
        PairedRequestVerification,
        (
            ("clean", _object(RequestBinding)),
            ("attack", _object(RequestBinding)),
            ("observed_target_visible_diff_sha256", str),
            ("verifier_contract_sha256", str),
            ("verifier_witness_sha256", str),
            ("verification_complete", bool),
            ("only_preregistered_delta", bool),
        ),
    ),
    _ObjectCodec(
        "episode_evidence_identity",
        EpisodeEvidenceIdentity,
        (
            ("request_binding", _object(RequestBinding)),
            ("evaluator_secret_opening", _object(EvaluatorSecretOpening)),
            ("runtime_attestation", _object(RuntimeAttestation)),
            ("prestate", _object(EpisodePrestate)),
            ("phase", _enum(EpisodePhase)),
            ("attempt_ordinal", int),
            ("response_envelope_sha256", str),
            ("extraction_contract_sha256", str),
            ("tool_trace_sha256", str),
            ("poststate_sha256", str),
            ("mutation_log_sha256", str),
            ("checker_result_sha256", str),
        ),
    ),
    _ObjectCodec(
        "mechanical_checker_result",
        MechanicalCheckerResult,
        (
            ("utility_checker_contract_sha256", str),
            ("security_checker_contract_sha256", str),
            ("checker_execution_witness_sha256", str),
            ("tool_trace_sha256", str),
            ("prestate_sha256", str),
            ("poststate_sha256", str),
            ("mutation_log_sha256", str),
            ("utility", _enum(UtilityState)),
            ("unauthorized_impact", _enum(ImpactState)),
            ("utility_witness_sha256", _optional(str)),
            ("security_witness_sha256", _optional(str)),
        ),
    ),
    _ObjectCodec(
        "episode_adjudication",
        EpisodeAdjudication,
        (
            ("evidence", _object(EpisodeEvidenceIdentity)),
            ("checker_result", _object(MechanicalCheckerResult)),
            ("disposition", _enum(TerminalDisposition)),
            ("terminal_witness_sha256", str),
        ),
    ),
    _ObjectCodec(
        "replay_link",
        ReplayLink,
        (
            ("initial", _object(EpisodeEvidenceIdentity)),
            ("replay", _object(EpisodeEvidenceIdentity)),
        ),
    ),
    _ObjectCodec(
        "replay_comparison",
        ReplayComparison,
        (
            ("link", _object(ReplayLink)),
            ("initial_adjudication", _object(EpisodeAdjudication)),
            ("replay_adjudication", _object(EpisodeAdjudication)),
        ),
    ),
    _ObjectCodec(
        "pair_terminal_reconciliation",
        PairTerminalReconciliation,
        (
            ("scheduled_pair", _object(ScheduledPairKey)),
            ("clean_episode", _object(ScheduledEpisodeKey)),
            ("attack_episode", _object(ScheduledEpisodeKey)),
            ("request_verification", _object(PairedRequestVerification)),
            ("clean_adjudication", _object(EpisodeAdjudication)),
            ("attack_adjudication", _object(EpisodeAdjudication)),
        ),
    ),
    _ObjectCodec(
        "partial_mechanical_observation",
        PartialMechanicalObservation,
        (
            ("utility", _enum(UtilityState)),
            ("unauthorized_impact", _enum(ImpactState)),
            ("utility_witness_sha256", _optional(str)),
            ("security_witness_sha256", _optional(str)),
        ),
    ),
    _ObjectCodec(
        "terminal_attempt_record",
        TerminalAttemptRecord,
        (
            ("scheduled_episode", _object(ScheduledEpisodeKey)),
            ("phase", _enum(EpisodePhase)),
            ("attempt_ordinal", int),
            ("disposition", _enum(TerminalDisposition)),
            ("observation", _object(PartialMechanicalObservation)),
            ("control_evidence_sha256", str),
            ("adjudication", _optional(_object(EpisodeAdjudication))),
            ("failure_artifact_sha256", _optional(str)),
            ("failure_witness_sha256", _optional(str)),
        ),
    ),
    _ObjectCodec(
        "outcome_count",
        OutcomeCount,
        (("outcome_class", _enum(JointOutcomeClass)), ("count", int)),
    ),
    _ObjectCodec(
        "replay_status_count",
        ReplayStatusCount,
        (("status", _enum(ReplayComparisonStatus)), ("count", int)),
    ),
    _ObjectCodec(
        "run_artifact_binding",
        RunArtifactBinding,
        (
            ("data_class", str),
            ("semantic_reference_sha256", str),
            ("encoded_artifact_sha256", str),
        ),
    ),
    _ObjectCodec(
        "agentic_run_summary",
        AgenticRunSummary,
        (
            ("scheduled_pair_count", int),
            ("scheduled_episode_count", int),
            ("terminal_attempt_count", int),
            ("initial_attempt_count", int),
            ("replay_attempt_count", int),
            ("completed_attempt_count", int),
            ("incomplete_attempt_count", int),
            ("invalid_attempt_count", int),
            ("initial_effectiveness_denominator", int),
            ("initial_all_attempt_denominator", int),
            ("initial_observed_harm_numerator", int),
            ("all_attempt_denominator", int),
            ("all_attempt_observed_harm_numerator", int),
            ("unknown_impact_attempt_count", int),
            ("initial_clean_incomplete_count", int),
            ("initial_attack_incomplete_count", int),
            ("initial_clean_unknown_impact_count", int),
            ("initial_attack_unknown_impact_count", int),
            ("pair_reconciliation_count", int),
            ("replay_comparison_count", int),
            ("initial_outcome_counts", _tuple(_object(OutcomeCount))),
            ("all_attempt_outcome_counts", _tuple(_object(OutcomeCount))),
            ("replay_status_counts", _tuple(_object(ReplayStatusCount))),
        ),
    ),
    _ObjectCodec(
        "agentic_run_graph_state",
        AgenticRunGraph,
        (
            ("run_id", str),
            ("manifest_sha256", str),
            ("run_artifact_bindings", _tuple(_object(RunArtifactBinding))),
            ("scheduled_pairs", _tuple(_object(ScheduledPairKey))),
            ("terminal_attempts", _tuple(_object(TerminalAttemptRecord))),
            ("replay_comparisons", _tuple(_object(ReplayComparison))),
            (
                "pair_reconciliations",
                _tuple(_object(PairTerminalReconciliation)),
            ),
        ),
    ),
)


def _build_codec_registries() -> tuple[MappingProxyType, MappingProxyType, MappingProxyType]:
    by_class: dict[type[Any], _ObjectCodec] = {}
    by_tag: dict[str, _ObjectCodec] = {}
    for codec in _CODECS:
        if codec.cls in by_class or codec.tag in by_tag:
            raise RuntimeError("duplicate agentic run graph codec")
        actual_fields = tuple(item.name for item in fields(codec.cls) if item.init)
        declared_fields = tuple(name for name, _spec in codec.field_specs)
        if actual_fields != declared_fields:
            raise RuntimeError(
                f"codec fields drifted for {codec.cls.__name__}: "
                f"{actual_fields!r} != {declared_fields!r}"
            )
        by_class[codec.cls] = codec
        by_tag[codec.tag] = codec
    enum_by_tag: dict[str, type[StrEnum]] = {}
    for enum_class, tag in _ENUM_TAGS.items():
        if tag in enum_by_tag:
            raise RuntimeError(f"duplicate enum codec tag: {tag}")
        enum_by_tag[tag] = enum_class
    return (
        MappingProxyType(by_class),
        MappingProxyType(by_tag),
        MappingProxyType(enum_by_tag),
    )


_CODEC_BY_CLASS, _CODEC_BY_TAG, _ENUM_BY_TAG = _build_codec_registries()


def _encode_typed(value: object, spec: object) -> object:
    if spec in {str, int, bool}:
        if type(value) is not spec:
            raise TypeError(f"expected exact {spec.__name__}, got {type(value).__name__}")
        return value
    if isinstance(spec, _OptionalSpec):
        return None if value is None else _encode_typed(value, spec.item)
    if isinstance(spec, _TupleSpec):
        if type(value) is not tuple:
            raise TypeError("expected an exact tuple")
        return [_encode_typed(item, spec.item) for item in value]
    if isinstance(spec, _EnumSpec):
        if type(value) is not spec.cls:
            raise TypeError(f"expected enum {spec.cls.__name__}")
        return {"enum": _ENUM_TAGS[spec.cls], "value": value.value}
    if isinstance(spec, _ObjectSpec):
        if type(value) is not spec.cls:
            raise TypeError(f"expected object {spec.cls.__name__}")
        return _encode_registered(value)
    raise RuntimeError(f"unknown codec specification: {spec!r}")


def _encode_registered(value: object) -> dict[str, Any]:
    codec = _CODEC_BY_CLASS.get(type(value))
    if codec is None:
        raise TypeError(f"unregistered agentic graph type: {type(value).__name__}")
    return {
        "fields": {
            name: _encode_typed(getattr(value, name), spec) for name, spec in codec.field_specs
        },
        "type": codec.tag,
    }


def _decode_typed(value: object, spec: object) -> object:
    if spec in {str, int, bool}:
        if type(value) is not spec:
            raise TypeError(f"expected exact {spec.__name__}, got {type(value).__name__}")
        return value
    if isinstance(spec, _OptionalSpec):
        return None if value is None else _decode_typed(value, spec.item)
    if isinstance(spec, _TupleSpec):
        if type(value) is not list:
            raise TypeError("persisted tuple must be a JSON array")
        return tuple(_decode_typed(item, spec.item) for item in value)
    if isinstance(spec, _EnumSpec):
        row = _exact_dict("enum value", value, {"enum", "value"})
        expected_tag = _ENUM_TAGS[spec.cls]
        if row["enum"] != expected_tag or _ENUM_BY_TAG.get(row["enum"]) is not spec.cls:
            raise ValueError(f"enum tag mismatch for {spec.cls.__name__}")
        if type(row["value"]) is not str:
            raise TypeError("enum value must be exact text")
        return spec.cls(row["value"])
    if isinstance(spec, _ObjectSpec):
        return _decode_registered(value, spec.cls)
    raise RuntimeError(f"unknown codec specification: {spec!r}")


def _decode_registered(value: object, expected_class: type[Any]) -> Any:
    row = _exact_dict("registered object", value, {"type", "fields"})
    codec = _CODEC_BY_CLASS.get(expected_class)
    if codec is None:
        raise TypeError(f"unregistered expected type: {expected_class.__name__}")
    if row["type"] != codec.tag or _CODEC_BY_TAG.get(row["type"]) is not codec:
        raise ValueError(f"registered object type mismatch for {expected_class.__name__}")
    field_values = _exact_dict(
        f"{codec.tag} fields",
        row["fields"],
        {name for name, _spec in codec.field_specs},
    )
    kwargs = {name: _decode_typed(field_values[name], spec) for name, spec in codec.field_specs}
    result = codec.cls(**kwargs)
    if _encode_registered(result) != row:
        raise ValueError(f"{codec.tag} did not round-trip through its constructor")
    return result
