"""SCED jailbreak Phase 1 offline ratchet gate.

Phase 1 wires candidate auto-falsification against direct lab bounty targets,
but it is still an offline, text-only verifier. It records target policy
metadata and refuses candidates that duplicate known material, fail the frozen
held-out set, or request any live submission path.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from math import isfinite
from typing import Any, Final

from shared.capdlc_lifecycle import GateResult, GateStatus
from shared.legal_posture_registry import G2GateInput
from shared.sced_jailbreak_ruler import (
    SCEDRulerFreeze,
    verify_collection_admission,
)

SCED_PHASE1_RATCHET_NAME: Final = "sced_jailbreak_phase1_ratchet"
SCED_PHASE1_RATCHET_VERSION: Final = 1
OFFLINE_SUBMISSION_MODE: Final = "offline_only"
_REF_NAMESPACE_SEPARATOR: Final = ":"

ANTHROPIC_UNIVERSAL_JAILBREAK_TARGET: Final = G2GateInput(
    surface="bug_bounty",
    venue="anthropic",
    instrument="direct_invited_model_safety_universal_jailbreak_bounty",
)
OPENAI_BIO_JAILBREAK_TARGET: Final = G2GateInput(
    surface="bug_bounty",
    venue="openai",
    instrument="direct_invited_bio_universal_jailbreak_bounty",
)


class SCEDPhase1RejectReason(StrEnum):
    """Machine-readable reasons the Phase 1 ratchet refuses a candidate."""

    COLLECTION_NOT_ADMITTED = "collection_not_admitted"
    INVALID_CANDIDATE = "invalid_candidate"
    INVALID_LEDGER = "invalid_ledger"
    INVALID_TARGET_POLICY = "invalid_target_policy"
    FREEZE_TARGET_MISMATCH = "freeze_target_mismatch"
    MISSING_TARGET_POLICY = "missing_target_policy"
    LIVE_SUBMISSION_REQUESTED = "live_submission_requested"
    DUPLICATE_CANDIDATE_DIGEST = "duplicate_candidate_digest"
    DUPLICATE_TECHNIQUE_REF = "duplicate_technique_ref"
    WITNESS_CANDIDATE_MISMATCH = "witness_candidate_mismatch"
    MISSING_SIMILARITY_OBSERVATION = "missing_similarity_observation"
    MISSING_SIMILARITY_COVERAGE = "missing_similarity_coverage"
    NOVELTY_SIMILARITY_DUPLICATE = "novelty_similarity_duplicate"
    MISSING_HELD_OUT_EVALUATION = "missing_held_out_evaluation"
    INVALID_HELD_OUT_EVALUATION = "invalid_held_out_evaluation"
    HELD_OUT_SET_MISMATCH = "held_out_set_mismatch"
    HELD_OUT_FAILURE = "held_out_failure"
    POLICY_THRESHOLD_NOT_MET = "policy_threshold_not_met"
    INVALID_SIMILARITY_OBSERVATION = "invalid_similarity_observation"


_NEXT_ACTIONS: Final[dict[SCEDPhase1RejectReason, str]] = {
    SCEDPhase1RejectReason.COLLECTION_NOT_ADMITTED: (
        "attach a valid Phase 0 SCED ruler freeze before Phase 1 candidate evaluation"
    ),
    SCEDPhase1RejectReason.INVALID_CANDIDATE: (
        "repair the candidate record using durable refs and a sha256 digest"
    ),
    SCEDPhase1RejectReason.INVALID_LEDGER: (
        "repair the ratchet ledger using candidate digests and durable technique refs"
    ),
    SCEDPhase1RejectReason.INVALID_TARGET_POLICY: (
        "repair the target policy snapshot refs and dates"
    ),
    SCEDPhase1RejectReason.FREEZE_TARGET_MISMATCH: (
        "re-freeze the SCED ruler with an M2 budget envelope for the candidate target"
    ),
    SCEDPhase1RejectReason.MISSING_TARGET_POLICY: (
        "record a direct-lab target policy snapshot before evaluating the candidate"
    ),
    SCEDPhase1RejectReason.LIVE_SUBMISSION_REQUESTED: (
        "keep Phase 1 offline; live submission is reserved for operator-ratified later phases"
    ),
    SCEDPhase1RejectReason.DUPLICATE_CANDIDATE_DIGEST: (
        "discard duplicate candidate material and generate a new offline candidate"
    ),
    SCEDPhase1RejectReason.DUPLICATE_TECHNIQUE_REF: (
        "discard duplicate technique material and generate a novel offline candidate"
    ),
    SCEDPhase1RejectReason.WITNESS_CANDIDATE_MISMATCH: (
        "rerun held-out and similarity witnesses for the evaluated candidate digest"
    ),
    SCEDPhase1RejectReason.MISSING_SIMILARITY_OBSERVATION: (
        "attach at least one durable similarity witness before admission"
    ),
    SCEDPhase1RejectReason.MISSING_SIMILARITY_COVERAGE: (
        "attach similarity witnesses for every frozen and ledger known-technique ref"
    ),
    SCEDPhase1RejectReason.NOVELTY_SIMILARITY_DUPLICATE: (
        "discard candidates at or above the frozen duplicate-similarity threshold"
    ),
    SCEDPhase1RejectReason.MISSING_HELD_OUT_EVALUATION: (
        "attach the held-out evaluation witness before advancing the ratchet"
    ),
    SCEDPhase1RejectReason.INVALID_HELD_OUT_EVALUATION: (
        "repair the held-out evaluation witness shape"
    ),
    SCEDPhase1RejectReason.HELD_OUT_SET_MISMATCH: (
        "rerun held-out evaluation against the frozen held-out refusal set id"
    ),
    SCEDPhase1RejectReason.HELD_OUT_FAILURE: (
        "discard this candidate and preserve failed_prompt_refs as rejection evidence"
    ),
    SCEDPhase1RejectReason.POLICY_THRESHOLD_NOT_MET: (
        "discard this candidate and rerun only after a witness clears the frozen category threshold"
    ),
    SCEDPhase1RejectReason.INVALID_SIMILARITY_OBSERVATION: (
        "repair similarity observations using durable refs, finite probabilities, and timestamps"
    ),
}


class _Phase1InputError(ValueError):
    def __init__(self, reason: SCEDPhase1RejectReason, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(detail or reason.value)


@dataclass(frozen=True)
class SCEDTargetPolicySnapshot:
    """Direct-lab target policy metadata recorded before candidate evaluation."""

    target: G2GateInput
    policy_refs: tuple[str, ...]
    policy_reviewed_on: date
    policy_published_on: date | None = None
    application_deadline: date | None = None
    testing_window_ends_on: date | None = None
    registry_row_ref: str = ""
    source_task: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "target", _coerce_target(self.target))
        refs = _durable_ref_tuple(self.policy_refs, field="policy_refs")
        if not refs:
            raise ValueError("target policy snapshot requires at least one policy ref")
        object.__setattr__(self, "policy_refs", refs)
        object.__setattr__(
            self, "policy_reviewed_on", _coerce_date(self.policy_reviewed_on, "policy_reviewed_on")
        )
        object.__setattr__(
            self,
            "policy_published_on",
            _coerce_optional_date(self.policy_published_on, "policy_published_on"),
        )
        object.__setattr__(
            self,
            "application_deadline",
            _coerce_optional_date(self.application_deadline, "application_deadline"),
        )
        object.__setattr__(
            self,
            "testing_window_ends_on",
            _coerce_optional_date(self.testing_window_ends_on, "testing_window_ends_on"),
        )
        object.__setattr__(
            self,
            "registry_row_ref",
            _optional_durable_ref(self.registry_row_ref, field="registry_row_ref"),
        )
        object.__setattr__(self, "source_task", _optional_string(self.source_task))

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> SCEDTargetPolicySnapshot:
        target_raw = raw.get("target", raw)
        return cls(
            target=_coerce_target(target_raw),
            policy_refs=_seq(raw.get("policy_refs")),
            policy_reviewed_on=raw.get("policy_reviewed_on"),  # type: ignore[arg-type]
            policy_published_on=raw.get("policy_published_on"),  # type: ignore[arg-type]
            application_deadline=raw.get("application_deadline"),  # type: ignore[arg-type]
            testing_window_ends_on=raw.get("testing_window_ends_on"),  # type: ignore[arg-type]
            registry_row_ref=raw.get("registry_row_ref", ""),  # type: ignore[arg-type]
            source_task=raw.get("source_task", ""),  # type: ignore[arg-type]
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": _target_to_dict(self.target),
            "policy_refs": list(self.policy_refs),
            "policy_reviewed_on": self.policy_reviewed_on.isoformat(),
            "policy_published_on": _date_or_none(self.policy_published_on),
            "application_deadline": _date_or_none(self.application_deadline),
            "testing_window_ends_on": _date_or_none(self.testing_window_ends_on),
            "registry_row_ref": self.registry_row_ref,
            "source_task": self.source_task,
        }


@dataclass(frozen=True)
class SCEDJailbreakCandidate:
    """Offline candidate reference. The prompt text itself is never stored here."""

    candidate_id: str
    candidate_digest: str
    target: G2GateInput
    submission_mode: str = OFFLINE_SUBMISSION_MODE
    technique_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_id",
            _required_durable_ref(self.candidate_id, field="candidate_id"),
        )
        object.__setattr__(
            self,
            "candidate_digest",
            _sha256_digest(self.candidate_digest, field="candidate_digest"),
        )
        object.__setattr__(self, "target", _coerce_target(self.target))
        object.__setattr__(
            self, "submission_mode", _required_string(self.submission_mode, field="submission_mode")
        )
        object.__setattr__(
            self,
            "technique_refs",
            _durable_ref_tuple(self.technique_refs, field="technique_refs"),
        )
        if not self.technique_refs:
            raise ValueError("technique_refs requires at least one durable technique ref")
        evidence_refs = _durable_ref_tuple(self.evidence_refs, field="evidence_refs")
        if not evidence_refs:
            raise ValueError("evidence_refs requires at least one durable evidence ref")
        object.__setattr__(self, "evidence_refs", evidence_refs)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> SCEDJailbreakCandidate:
        return cls(
            candidate_id=raw.get("candidate_id"),  # type: ignore[arg-type]
            candidate_digest=raw.get("candidate_digest"),  # type: ignore[arg-type]
            target=_coerce_target(raw.get("target", raw)),
            submission_mode=raw.get("submission_mode", OFFLINE_SUBMISSION_MODE),  # type: ignore[arg-type]
            technique_refs=_seq(raw.get("technique_refs")),
            evidence_refs=_seq(raw.get("evidence_refs")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_digest": self.candidate_digest,
            "target": _target_to_dict(self.target),
            "submission_mode": self.submission_mode,
            "technique_refs": list(self.technique_refs),
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class HeldOutEvaluation:
    """Offline witness that a candidate cleared or failed the frozen held-out set."""

    candidate_id: str
    candidate_digest: str
    set_id: str
    evaluated_at: datetime
    cleared_categories: tuple[str, ...]
    failed_prompt_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_id",
            _required_durable_ref(self.candidate_id, field="candidate_id"),
        )
        object.__setattr__(
            self,
            "candidate_digest",
            _sha256_digest(self.candidate_digest, field="candidate_digest"),
        )
        object.__setattr__(self, "set_id", _required_string(self.set_id, field="set_id"))
        object.__setattr__(
            self, "evaluated_at", _coerce_datetime(self.evaluated_at, "evaluated_at")
        )
        object.__setattr__(
            self,
            "cleared_categories",
            _ref_tuple(self.cleared_categories, field="cleared_categories"),
        )
        object.__setattr__(
            self,
            "failed_prompt_refs",
            _durable_ref_tuple(self.failed_prompt_refs, field="failed_prompt_refs"),
        )
        evidence_refs = _durable_ref_tuple(self.evidence_refs, field="evidence_refs")
        if not evidence_refs:
            raise ValueError("evidence_refs requires at least one durable evidence ref")
        object.__setattr__(self, "evidence_refs", evidence_refs)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> HeldOutEvaluation:
        return cls(
            candidate_id=raw.get("candidate_id"),  # type: ignore[arg-type]
            candidate_digest=raw.get("candidate_digest"),  # type: ignore[arg-type]
            set_id=raw.get("set_id"),  # type: ignore[arg-type]
            evaluated_at=raw.get("evaluated_at"),  # type: ignore[arg-type]
            cleared_categories=_seq(raw.get("cleared_categories")),
            failed_prompt_refs=_seq(raw.get("failed_prompt_refs")),
            evidence_refs=_seq(raw.get("evidence_refs")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_digest": self.candidate_digest,
            "set_id": self.set_id,
            "evaluated_at": self.evaluated_at.isoformat(),
            "cleared_categories": list(self.cleared_categories),
            "failed_prompt_refs": list(self.failed_prompt_refs),
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class SimilarityObservation:
    """Offline similarity witness against known technique material."""

    candidate_id: str
    candidate_digest: str
    against_ref: str
    similarity: float
    method_ref: str
    observed_at: datetime
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_id",
            _required_durable_ref(self.candidate_id, field="candidate_id"),
        )
        object.__setattr__(
            self,
            "candidate_digest",
            _sha256_digest(self.candidate_digest, field="candidate_digest"),
        )
        object.__setattr__(
            self,
            "against_ref",
            _required_durable_ref(self.against_ref, field="against_ref"),
        )
        similarity = _finite_float(self.similarity, field="similarity")
        if not 0.0 <= similarity <= 1.0:
            raise ValueError("similarity must be between 0.0 and 1.0")
        object.__setattr__(self, "similarity", similarity)
        object.__setattr__(
            self,
            "method_ref",
            _required_durable_ref(self.method_ref, field="method_ref"),
        )
        object.__setattr__(self, "observed_at", _coerce_datetime(self.observed_at, "observed_at"))
        evidence_refs = _durable_ref_tuple(self.evidence_refs, field="evidence_refs")
        if not evidence_refs:
            raise ValueError("evidence_refs requires at least one durable evidence ref")
        object.__setattr__(self, "evidence_refs", evidence_refs)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> SimilarityObservation:
        return cls(
            candidate_id=raw.get("candidate_id"),  # type: ignore[arg-type]
            candidate_digest=raw.get("candidate_digest"),  # type: ignore[arg-type]
            against_ref=raw.get("against_ref"),  # type: ignore[arg-type]
            similarity=raw.get("similarity"),  # type: ignore[arg-type]
            method_ref=raw.get("method_ref"),  # type: ignore[arg-type]
            observed_at=raw.get("observed_at"),  # type: ignore[arg-type]
            evidence_refs=_seq(raw.get("evidence_refs")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_digest": self.candidate_digest,
            "against_ref": self.against_ref,
            "similarity": self.similarity,
            "method_ref": self.method_ref,
            "observed_at": self.observed_at.isoformat(),
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class SCEDRatchetLedger:
    """Prior accepted candidates and techniques at the Phase 1 ratchet boundary."""

    candidate_digests: tuple[str, ...] = ()
    technique_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_digests",
            tuple(
                dict.fromkeys(
                    _sha256_digest(item, field="candidate_digests")
                    for item in self.candidate_digests
                )
            ),
        )
        object.__setattr__(
            self,
            "technique_refs",
            _durable_ref_tuple(self.technique_refs, field="technique_refs"),
        )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> SCEDRatchetLedger:
        return cls(
            candidate_digests=_seq(raw.get("candidate_digests")),
            technique_refs=_seq(raw.get("technique_refs")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_digests": list(self.candidate_digests),
            "technique_refs": list(self.technique_refs),
        }


@dataclass(frozen=True)
class SCEDPhase1Decision:
    """Result of offline Phase 1 candidate ratchet evaluation."""

    verifier: str
    verifier_version: int
    status: GateStatus
    gate_result: GateResult
    reason: str
    reject_reasons: tuple[SCEDPhase1RejectReason, ...]
    candidate_id: str | None = None
    candidate_digest: str | None = None
    technique_refs: tuple[str, ...] = ()
    target: G2GateInput | None = None
    ruler_hash: str | None = None
    target_policy_snapshot: SCEDTargetPolicySnapshot | None = None
    evidence_refs: tuple[str, ...] = ()
    next_action: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, GateStatus):
            raise TypeError("SCEDPhase1Decision.status must be a GateStatus identity")
        if not isinstance(self.gate_result, GateResult):
            raise TypeError("SCEDPhase1Decision.gate_result must be a GateResult identity")
        for reason in self.reject_reasons:
            if not isinstance(reason, SCEDPhase1RejectReason):
                raise TypeError("reject_reasons must be SCEDPhase1RejectReason values")
        if self.target is not None and not isinstance(self.target, G2GateInput):
            raise TypeError("target must be a G2GateInput")
        if self.target_policy_snapshot is not None and not isinstance(
            self.target_policy_snapshot, SCEDTargetPolicySnapshot
        ):
            raise TypeError("target_policy_snapshot must be a SCEDTargetPolicySnapshot")
        object.__setattr__(self, "technique_refs", tuple(self.technique_refs))
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))

    @property
    def ok(self) -> bool:
        return self.status is GateStatus.LIT

    def __bool__(self) -> bool:
        raise TypeError("SCEDPhase1Decision truthiness is undefined; inspect status")

    def to_dict(self) -> dict[str, Any]:
        policy = self.target_policy_snapshot
        return {
            "verifier": self.verifier,
            "verifier_version": self.verifier_version,
            "status": self.status.value,
            "ok": self.ok,
            "reason": self.reason,
            "reject_reasons": [reason.value for reason in self.reject_reasons],
            "next_action": self.next_action,
            "candidate_id": self.candidate_id,
            "candidate_digest": self.candidate_digest,
            "technique_refs": list(self.technique_refs),
            "target": None if self.target is None else _target_to_dict(self.target),
            "ruler_hash": self.ruler_hash,
            "target_policy_refs": [] if policy is None else list(policy.policy_refs),
            "target_policy_dates": None if policy is None else _policy_dates(policy),
            "target_policy_snapshot": None if policy is None else policy.to_dict(),
            "evidence_refs": list(self.evidence_refs),
            "gate_result": {
                "status": self.gate_result.status.value,
                "verdict": self.gate_result.verdict,
                "reason": self.gate_result.reason,
                "evidence_refs": list(self.gate_result.evidence_refs),
            },
        }


def default_target_policy_snapshots() -> tuple[SCEDTargetPolicySnapshot, ...]:
    """Return the current direct-lab target policy metadata used by Phase 1."""

    return (
        SCEDTargetPolicySnapshot(
            target=ANTHROPIC_UNIVERSAL_JAILBREAK_TARGET,
            policy_refs=(
                "url:https://support.claude.com/en/articles/12119250-model-safety-bug-bounty-program",
            ),
            policy_reviewed_on=date(2026, 6, 30),
            policy_published_on=date(2026, 3, 16),
            registry_row_ref=(
                "legal-posture-row:bug_bounty:anthropic:"
                "direct_invited_model_safety_universal_jailbreak_bounty"
            ),
            source_task="20260628-registry-phase3-bug-bounty-subtree",
        ),
        SCEDTargetPolicySnapshot(
            target=OPENAI_BIO_JAILBREAK_TARGET,
            policy_refs=("url:https://openai.com/index/gpt-5-5-bio-bug-bounty/",),
            policy_reviewed_on=date(2026, 6, 30),
            policy_published_on=date(2026, 4, 23),
            application_deadline=date(2026, 6, 22),
            testing_window_ends_on=date(2026, 7, 27),
            registry_row_ref=(
                "legal-posture-row:bug_bounty:openai:direct_invited_bio_universal_jailbreak_bounty"
            ),
            source_task="20260628-registry-phase3-bug-bounty-subtree",
        ),
    )


def evaluate_phase1_candidate(
    candidate: SCEDJailbreakCandidate | Mapping[str, Any],
    *,
    freeze: SCEDRulerFreeze | Mapping[str, Any] | None,
    ruler_hash_commit: str | None,
    held_out_evaluation: HeldOutEvaluation | Mapping[str, Any] | None,
    similarity_observations: Sequence[SimilarityObservation | Mapping[str, Any]] = (),
    ledger: SCEDRatchetLedger | Mapping[str, Any] | None = None,
    target_policies: Sequence[SCEDTargetPolicySnapshot | Mapping[str, Any]] | None = None,
) -> SCEDPhase1Decision:
    """Evaluate one offline candidate against the frozen Phase 0 ruler."""

    try:
        candidate_obj = _coerce_candidate(candidate)
    except _Phase1InputError as exc:
        return _refused((exc.reason,), detail=exc.detail)

    collection = verify_collection_admission(freeze, ruler_hash_commit=ruler_hash_commit)
    if collection.status is not GateStatus.LIT or collection.ruler is None:
        return _refused(
            (SCEDPhase1RejectReason.COLLECTION_NOT_ADMITTED,),
            candidate=candidate_obj,
            detail=collection.reason,
            ruler_hash=collection.ruler_hash,
            evidence_refs=candidate_obj.evidence_refs,
        )
    ruler = collection.ruler
    ruler_hash = collection.ruler_hash or ruler.canonical_hash()

    try:
        _require_freeze_target(candidate_obj, freeze)
        ledger_obj = _coerce_ledger(ledger)
        policy_snapshot = _policy_for_target(candidate_obj.target, target_policies)
        held_out = _coerce_held_out(held_out_evaluation)
        similarities = _coerce_similarities(similarity_observations)
    except _Phase1InputError as exc:
        return _refused(
            (exc.reason,),
            candidate=candidate_obj,
            detail=exc.detail,
            ruler_hash=ruler_hash,
            evidence_refs=candidate_obj.evidence_refs,
        )

    reject_reasons: list[SCEDPhase1RejectReason] = []
    if candidate_obj.submission_mode != OFFLINE_SUBMISSION_MODE:
        reject_reasons.append(SCEDPhase1RejectReason.LIVE_SUBMISSION_REQUESTED)
    if candidate_obj.candidate_digest in ledger_obj.candidate_digests:
        reject_reasons.append(SCEDPhase1RejectReason.DUPLICATE_CANDIDATE_DIGEST)
    if not _witnesses_match_candidate(candidate_obj, held_out, similarities):
        reject_reasons.append(SCEDPhase1RejectReason.WITNESS_CANDIDATE_MISMATCH)

    known_techniques = set(ledger_obj.technique_refs) | set(
        ruler.novelty_criterion.known_technique_refs
    )
    if known_techniques.intersection(candidate_obj.technique_refs):
        reject_reasons.append(SCEDPhase1RejectReason.DUPLICATE_TECHNIQUE_REF)
    if not similarities:
        reject_reasons.append(SCEDPhase1RejectReason.MISSING_SIMILARITY_OBSERVATION)
    observed_similarity_refs = {observation.against_ref for observation in similarities}
    if known_techniques and not known_techniques.issubset(observed_similarity_refs):
        reject_reasons.append(SCEDPhase1RejectReason.MISSING_SIMILARITY_COVERAGE)
    if any(
        observation.similarity >= ruler.novelty_criterion.max_duplicate_similarity
        for observation in similarities
    ):
        reject_reasons.append(SCEDPhase1RejectReason.NOVELTY_SIMILARITY_DUPLICATE)

    if held_out.set_id != ruler.held_out_refusal_set.set_id:
        reject_reasons.append(SCEDPhase1RejectReason.HELD_OUT_SET_MISMATCH)
    if held_out.failed_prompt_refs:
        reject_reasons.append(SCEDPhase1RejectReason.HELD_OUT_FAILURE)

    cleared = set(held_out.cleared_categories).intersection(
        ruler.policy_category_threshold.categories
    )
    if len(cleared) < ruler.policy_category_threshold.min_categories_cleared:
        reject_reasons.append(SCEDPhase1RejectReason.POLICY_THRESHOLD_NOT_MET)

    evidence_refs = _decision_evidence_refs(
        candidate_obj,
        policy_snapshot,
        ruler_hash,
        held_out,
        similarities,
    )
    if reject_reasons:
        return _refused(
            tuple(dict.fromkeys(reject_reasons)),
            candidate=candidate_obj,
            policy_snapshot=policy_snapshot,
            ruler_hash=ruler_hash,
            evidence_refs=evidence_refs,
        )
    return _admitted(candidate_obj, policy_snapshot, ruler_hash, evidence_refs)


def advance_ratchet(
    ledger: SCEDRatchetLedger | Mapping[str, Any],
    decision: SCEDPhase1Decision,
) -> SCEDRatchetLedger:
    """Advance the offline ledger only for a LIT Phase 1 decision."""

    ledger_obj = _coerce_ledger(ledger)
    if not _decision_can_advance(decision):
        return ledger_obj
    return SCEDRatchetLedger(
        candidate_digests=(
            *ledger_obj.candidate_digests,
            decision.candidate_digest,
        ),
        technique_refs=(
            *ledger_obj.technique_refs,
            *decision.technique_refs,
        ),
    )


def _decision_can_advance(decision: SCEDPhase1Decision) -> bool:
    return (
        decision.verifier == SCED_PHASE1_RATCHET_NAME
        and decision.verifier_version == SCED_PHASE1_RATCHET_VERSION
        and decision.status is GateStatus.LIT
        and decision.gate_result.status is GateStatus.LIT
        and decision.gate_result.verdict is True
        and not decision.reject_reasons
        and _decision_has_durable_candidate_id(decision)
        and _decision_has_candidate_digest(decision)
        and _decision_has_durable_technique_refs(decision)
        and decision.target is not None
        and _decision_has_ruler_hash(decision)
        and decision.target_policy_snapshot is not None
        and _decision_has_durable_evidence_refs(decision)
    )


def _decision_has_durable_candidate_id(decision: SCEDPhase1Decision) -> bool:
    if not decision.candidate_id:
        return False
    try:
        _required_durable_ref(decision.candidate_id, field="candidate_id")
    except ValueError:
        return False
    return True


def _decision_has_candidate_digest(decision: SCEDPhase1Decision) -> bool:
    try:
        _sha256_digest(decision.candidate_digest, field="candidate_digest")
    except ValueError:
        return False
    return True


def _decision_has_durable_technique_refs(decision: SCEDPhase1Decision) -> bool:
    try:
        return bool(_durable_ref_tuple(decision.technique_refs, field="technique_refs"))
    except ValueError:
        return False


def _decision_has_ruler_hash(decision: SCEDPhase1Decision) -> bool:
    ruler_hash = decision.ruler_hash
    return (
        isinstance(ruler_hash, str)
        and len(ruler_hash) == 64
        and all(char in "0123456789abcdef" for char in ruler_hash)
    )


def _decision_has_durable_evidence_refs(decision: SCEDPhase1Decision) -> bool:
    return _nonempty_durable_refs(decision.evidence_refs) and _nonempty_durable_refs(
        decision.gate_result.evidence_refs
    )


def _nonempty_durable_refs(values: Sequence[str]) -> bool:
    try:
        return bool(_durable_ref_tuple(values, field="evidence_refs"))
    except ValueError:
        return False


def _witnesses_match_candidate(
    candidate: SCEDJailbreakCandidate,
    held_out: HeldOutEvaluation,
    similarities: Sequence[SimilarityObservation],
) -> bool:
    if (
        held_out.candidate_id != candidate.candidate_id
        or held_out.candidate_digest != candidate.candidate_digest
    ):
        return False
    return all(
        observation.candidate_id == candidate.candidate_id
        and observation.candidate_digest == candidate.candidate_digest
        for observation in similarities
    )


def _coerce_candidate(value: SCEDJailbreakCandidate | Mapping[str, Any]) -> SCEDJailbreakCandidate:
    if isinstance(value, SCEDJailbreakCandidate):
        return value
    if isinstance(value, Mapping):
        try:
            return SCEDJailbreakCandidate.from_mapping(value)
        except (TypeError, ValueError) as exc:
            raise _Phase1InputError(SCEDPhase1RejectReason.INVALID_CANDIDATE, str(exc)) from exc
    raise _Phase1InputError(
        SCEDPhase1RejectReason.INVALID_CANDIDATE,
        "candidate must be a SCEDJailbreakCandidate or mapping",
    )


def _coerce_held_out(
    value: HeldOutEvaluation | Mapping[str, Any] | None,
) -> HeldOutEvaluation:
    if value is None:
        raise _Phase1InputError(SCEDPhase1RejectReason.MISSING_HELD_OUT_EVALUATION)
    if isinstance(value, HeldOutEvaluation):
        return value
    if isinstance(value, Mapping):
        try:
            return HeldOutEvaluation.from_mapping(value)
        except (TypeError, ValueError) as exc:
            raise _Phase1InputError(
                SCEDPhase1RejectReason.INVALID_HELD_OUT_EVALUATION, str(exc)
            ) from exc
    raise _Phase1InputError(
        SCEDPhase1RejectReason.INVALID_HELD_OUT_EVALUATION,
        "held_out_evaluation must be a HeldOutEvaluation or mapping",
    )


def _coerce_similarities(
    values: Sequence[SimilarityObservation | Mapping[str, Any]],
) -> tuple[SimilarityObservation, ...]:
    observations: list[SimilarityObservation] = []
    try:
        for value in values:
            if isinstance(value, SimilarityObservation):
                observations.append(value)
            elif isinstance(value, Mapping):
                observations.append(SimilarityObservation.from_mapping(value))
            else:
                raise TypeError("similarity observation must be an object or mapping")
    except (TypeError, ValueError) as exc:
        raise _Phase1InputError(
            SCEDPhase1RejectReason.INVALID_SIMILARITY_OBSERVATION, str(exc)
        ) from exc
    return tuple(observations)


def _coerce_ledger(value: SCEDRatchetLedger | Mapping[str, Any] | None) -> SCEDRatchetLedger:
    if value is None:
        return SCEDRatchetLedger()
    if isinstance(value, SCEDRatchetLedger):
        return value
    if isinstance(value, Mapping):
        try:
            return SCEDRatchetLedger.from_mapping(value)
        except (TypeError, ValueError) as exc:
            raise _Phase1InputError(SCEDPhase1RejectReason.INVALID_LEDGER, str(exc)) from exc
    raise _Phase1InputError(
        SCEDPhase1RejectReason.INVALID_LEDGER,
        "ledger must be a SCEDRatchetLedger or mapping",
    )


def _policy_for_target(
    target: G2GateInput,
    snapshots: Sequence[SCEDTargetPolicySnapshot | Mapping[str, Any]] | None,
) -> SCEDTargetPolicySnapshot:
    candidates = _target_policy_candidates(snapshots)
    for snapshot in candidates:
        try:
            policy = (
                snapshot
                if isinstance(snapshot, SCEDTargetPolicySnapshot)
                else _policy_snapshot_from_mapping(snapshot)
            )
        except (TypeError, ValueError) as exc:
            raise _Phase1InputError(SCEDPhase1RejectReason.INVALID_TARGET_POLICY, str(exc)) from exc
        if policy.target.normalized().key == target.normalized().key:
            return policy
    raise _Phase1InputError(
        SCEDPhase1RejectReason.MISSING_TARGET_POLICY,
        f"no target policy snapshot for {_target_key(target)}",
    )


def _target_policy_candidates(
    snapshots: Sequence[SCEDTargetPolicySnapshot | Mapping[str, Any]] | None,
) -> Sequence[SCEDTargetPolicySnapshot | Mapping[str, Any]]:
    if snapshots is None:
        return default_target_policy_snapshots()
    if isinstance(snapshots, str) or not isinstance(snapshots, Sequence):
        raise _Phase1InputError(
            SCEDPhase1RejectReason.INVALID_TARGET_POLICY,
            "target_policies must be a sequence of target policy snapshots",
        )
    return snapshots


def _policy_snapshot_from_mapping(value: Any) -> SCEDTargetPolicySnapshot:
    if not isinstance(value, Mapping):
        raise TypeError("target policy snapshot must be an object or mapping")
    return SCEDTargetPolicySnapshot.from_mapping(value)


def _require_freeze_target(
    candidate: SCEDJailbreakCandidate,
    freeze: SCEDRulerFreeze | Mapping[str, Any] | None,
) -> None:
    freeze_target = _freeze_budget_target(freeze)
    candidate_target = candidate.target.normalized()
    if freeze_target.key != candidate_target.key:
        raise _Phase1InputError(
            SCEDPhase1RejectReason.FREEZE_TARGET_MISMATCH,
            (
                "candidate target "
                f"{_target_key(candidate_target)} does not match signed M2 budget envelope target "
                f"{_target_key(freeze_target)}"
            ),
        )


def _freeze_budget_target(freeze: SCEDRulerFreeze | Mapping[str, Any] | None) -> G2GateInput:
    if isinstance(freeze, SCEDRulerFreeze):
        envelope = freeze.m2_artifact.budget_envelope
        raw_target = {
            "surface": envelope.surface,
            "venue": envelope.venue,
            "instrument": envelope.instrument,
        }
    elif isinstance(freeze, Mapping):
        artifact = freeze.get("m2_artifact")
        if artifact is None:
            artifact = freeze.get("freeze_artifact")
        if not isinstance(artifact, Mapping):
            raise _Phase1InputError(
                SCEDPhase1RejectReason.FREEZE_TARGET_MISMATCH,
                "freeze is missing the signed M2 artifact target",
            )
        envelope = artifact.get("budget_envelope")
        if not isinstance(envelope, Mapping):
            raise _Phase1InputError(
                SCEDPhase1RejectReason.FREEZE_TARGET_MISMATCH,
                "freeze is missing the signed M2 budget envelope target",
            )
        raw_target = envelope
    else:
        raise _Phase1InputError(
            SCEDPhase1RejectReason.FREEZE_TARGET_MISMATCH,
            "freeze is missing the signed M2 budget envelope target",
        )
    try:
        return _coerce_target(raw_target)
    except ValueError as exc:
        raise _Phase1InputError(
            SCEDPhase1RejectReason.FREEZE_TARGET_MISMATCH,
            f"freeze budget envelope target is incomplete: {exc}",
        ) from exc


def _admitted(
    candidate: SCEDJailbreakCandidate,
    policy_snapshot: SCEDTargetPolicySnapshot,
    ruler_hash: str,
    evidence_refs: tuple[str, ...],
) -> SCEDPhase1Decision:
    reason = "sced_phase1_candidate_admitted"
    return SCEDPhase1Decision(
        verifier=SCED_PHASE1_RATCHET_NAME,
        verifier_version=SCED_PHASE1_RATCHET_VERSION,
        status=GateStatus.LIT,
        gate_result=GateResult(
            status=GateStatus.LIT,
            verdict=True,
            reason=reason,
            evidence_refs=evidence_refs,
        ),
        reason=reason,
        reject_reasons=(),
        candidate_id=candidate.candidate_id,
        candidate_digest=candidate.candidate_digest,
        technique_refs=candidate.technique_refs,
        target=candidate.target,
        ruler_hash=ruler_hash,
        target_policy_snapshot=policy_snapshot,
        evidence_refs=evidence_refs,
        next_action=None,
    )


def _refused(
    reject_reasons: tuple[SCEDPhase1RejectReason, ...],
    *,
    candidate: SCEDJailbreakCandidate | None = None,
    policy_snapshot: SCEDTargetPolicySnapshot | None = None,
    detail: str = "",
    ruler_hash: str | None = None,
    evidence_refs: Sequence[str] = (),
) -> SCEDPhase1Decision:
    first_reason = reject_reasons[0]
    next_action = _NEXT_ACTIONS[first_reason]
    reason = "sced_phase1_candidate_refused:" + ",".join(reason.value for reason in reject_reasons)
    if detail:
        reason = f"{reason}: {detail}"
    reason = f"{reason}; next action: {next_action}"
    evidence = tuple(dict.fromkeys(evidence_refs))
    return SCEDPhase1Decision(
        verifier=SCED_PHASE1_RATCHET_NAME,
        verifier_version=SCED_PHASE1_RATCHET_VERSION,
        status=GateStatus.DARK,
        gate_result=GateResult(
            status=GateStatus.DARK,
            verdict=None,
            reason=reason,
            evidence_refs=evidence,
        ),
        reason=reason,
        reject_reasons=reject_reasons,
        candidate_id=None if candidate is None else candidate.candidate_id,
        candidate_digest=None if candidate is None else candidate.candidate_digest,
        technique_refs=() if candidate is None else candidate.technique_refs,
        target=None if candidate is None else candidate.target,
        ruler_hash=ruler_hash,
        target_policy_snapshot=policy_snapshot,
        evidence_refs=evidence,
        next_action=next_action,
    )


def _decision_evidence_refs(
    candidate: SCEDJailbreakCandidate,
    policy: SCEDTargetPolicySnapshot,
    ruler_hash: str,
    held_out: HeldOutEvaluation,
    similarities: Sequence[SimilarityObservation],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            (
                f"candidate:{candidate.candidate_id}",
                f"candidate-digest:{candidate.candidate_digest}",
                f"target:{_target_key(candidate.target)}",
                f"ruler-hash:{ruler_hash}",
                *policy.policy_refs,
                *(() if not policy.registry_row_ref else (policy.registry_row_ref,)),
                *candidate.evidence_refs,
                *held_out.evidence_refs,
                *(ref for observation in similarities for ref in observation.evidence_refs),
            )
        )
    )


def _policy_dates(policy: SCEDTargetPolicySnapshot) -> dict[str, str | None]:
    return {
        "policy_reviewed_on": policy.policy_reviewed_on.isoformat(),
        "policy_published_on": _date_or_none(policy.policy_published_on),
        "application_deadline": _date_or_none(policy.application_deadline),
        "testing_window_ends_on": _date_or_none(policy.testing_window_ends_on),
    }


def _coerce_target(value: G2GateInput | Mapping[str, Any] | Any) -> G2GateInput:
    if isinstance(value, G2GateInput):
        return value.normalized()
    if isinstance(value, Mapping):
        return G2GateInput(
            surface=_required_string(value.get("surface"), field="surface"),
            venue=_required_string(value.get("venue"), field="venue"),
            instrument=_required_string(value.get("instrument"), field="instrument"),
        ).normalized()
    raise ValueError("target must be a G2GateInput or mapping")


def _target_to_dict(target: G2GateInput) -> dict[str, str]:
    normalized = target.normalized()
    return {
        "surface": normalized.surface,
        "venue": normalized.venue,
        "instrument": normalized.instrument,
    }


def _target_key(target: G2GateInput) -> str:
    normalized = target.normalized()
    return ":".join(normalized.key)


def _required_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _optional_string(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("optional string field must be a string")
    return value.strip()


def _optional_durable_ref(value: Any, *, field: str) -> str:
    ref = _optional_string(value)
    if not ref:
        return ""
    return _required_durable_ref(ref, field=field)


def _sha256_digest(value: Any, *, field: str) -> str:
    digest = _required_string(value, field=field)
    prefix = "sha256:"
    hexdigest = digest.removeprefix(prefix)
    if (
        hexdigest == digest
        or len(hexdigest) != 64
        or any(char not in "0123456789abcdef" for char in hexdigest)
    ):
        raise ValueError(f"{field} must be a sha256:<64 lowercase hex> digest")
    return digest


def _ref_tuple(value: Any, *, field: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ValueError(f"{field} must be a sequence of strings")
    refs: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field} must be a sequence of strings")
        ref = item.strip()
        if ref:
            refs.append(ref)
    return tuple(dict.fromkeys(refs))


def _durable_ref_tuple(value: Any, *, field: str) -> tuple[str, ...]:
    refs = _ref_tuple(value, field=field)
    for ref in refs:
        if _REF_NAMESPACE_SEPARATOR not in ref or any(char.isspace() for char in ref):
            raise ValueError(f"{field} must contain durable reference tokens, not prose text")
    return refs


def _required_durable_ref(value: Any, *, field: str) -> str:
    refs = _durable_ref_tuple((value,), field=field)
    if not refs:
        raise ValueError(f"{field} requires one durable reference token")
    return refs[0]


def _seq(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ValueError("expected a sequence of strings")
    if not all(isinstance(item, str) for item in value):
        raise ValueError("expected a sequence of strings")
    return tuple(item.strip() for item in value)


def _coerce_date(value: Any, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        return date.fromisoformat(value.strip())
    raise ValueError(f"{field} must be an ISO date")


def _coerce_optional_date(value: Any, field: str) -> date | None:
    if value is None or value == "":
        return None
    return _coerce_date(value, field)


def _coerce_datetime(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        raise ValueError(f"{field} must be an ISO datetime")
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(UTC)


def _date_or_none(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _finite_float(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    numeric = float(value)
    if not isfinite(numeric):
        raise ValueError(f"{field} must be finite")
    return numeric


__all__ = [
    "ANTHROPIC_UNIVERSAL_JAILBREAK_TARGET",
    "OFFLINE_SUBMISSION_MODE",
    "OPENAI_BIO_JAILBREAK_TARGET",
    "SCED_PHASE1_RATCHET_NAME",
    "SCED_PHASE1_RATCHET_VERSION",
    "HeldOutEvaluation",
    "SCEDJailbreakCandidate",
    "SCEDPhase1Decision",
    "SCEDPhase1RejectReason",
    "SCEDRatchetLedger",
    "SCEDTargetPolicySnapshot",
    "SimilarityObservation",
    "advance_ratchet",
    "default_target_policy_snapshots",
    "evaluate_phase1_candidate",
]
