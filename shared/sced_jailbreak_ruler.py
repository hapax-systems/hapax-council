"""SCED jailbreak-effectiveness ruler freeze (bounty phase 0).

The AI red-team / bug-bounty play measures universal-jailbreak effectiveness
against invited lab programs. To keep that a single-case experimental design
(SCED) rather than a post-hoc story, the *ruler* -- what counts as an effective
universal jailbreak -- must be frozen before any candidate is collected.

This module:

* Types the ruler content: a held-out refusal set, a policy-category threshold,
  and a novelty criterion, plus the numeric effectiveness thresholds.
* Binds the freeze to the M2 freeze artifact mechanism
  (:mod:`shared.mdlc_m2_freeze`): the artifact's authoritative ``ruler_hash`` is
  the canonical hash of the frozen ruler content, so the freeze is a hash, not
  mutable prose or a boolean flag.
* Gates collection: :func:`verify_collection_admission` refuses unless a signed
  freeze binds the exact ruler content it claims to freeze -- so collection can
  never precede freeze.

Only durable references are stored (prompt refs, technique refs, a sealed
digest) -- never weaponizable prompt text -- honoring ``no_secret_value_storage``
and the text-only legal posture in
``docs/monetization/bug-bounty-legal-posture-research.md``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Any, Final

from shared.capdlc_lifecycle import GateResult, GateStatus
from shared.mdlc_m2_freeze import (
    M2BudgetEnvelope,
    M2FreezeArtifact,
    M2FreezeRefusalReason,
    verify_m2_freeze_artifact,
)
from shared.mdlc_measure import MonDLCLadder

SCED_RULER_NAME: Final = "sced_jailbreak_ruler"
SCED_RULER_VERSION: Final = 1
SCED_RULER_SCHEMA: Final = "sced_jailbreak_ruler/1"


class SCEDCollectionRefusalReason(StrEnum):
    """Machine-readable reasons the SCED gate refuses to admit collection."""

    MISSING_FREEZE = "missing_freeze"
    INVALID_FREEZE = "invalid_freeze"
    MISSING_RULER = "missing_ruler"
    INVALID_RULER = "invalid_ruler"
    MISSING_HELD_OUT_REFUSAL_SET = "missing_held_out_refusal_set"
    MISSING_POLICY_CATEGORY_THRESHOLD = "missing_policy_category_threshold"
    MISSING_NOVELTY_CRITERION = "missing_novelty_criterion"
    M2_RULER_HASH_MISMATCH = "m2_ruler_hash_mismatch"
    M2_LADDER_MISMATCH = "m2_ladder_mismatch"
    M2_FREEZE_REFUSED = "m2_freeze_refused"


_NEXT_ACTIONS: Final[dict[SCEDCollectionRefusalReason, str]] = {
    SCEDCollectionRefusalReason.MISSING_FREEZE: (
        "attach the signed SCED ruler freeze before any collection"
    ),
    SCEDCollectionRefusalReason.INVALID_FREEZE: "repair the SCED ruler freeze structure",
    SCEDCollectionRefusalReason.MISSING_RULER: "record the frozen ruler inside the freeze",
    SCEDCollectionRefusalReason.INVALID_RULER: "repair the frozen ruler payload",
    SCEDCollectionRefusalReason.MISSING_HELD_OUT_REFUSAL_SET: (
        "record the held-out refusal set in the ruler"
    ),
    SCEDCollectionRefusalReason.MISSING_POLICY_CATEGORY_THRESHOLD: (
        "record the policy-category threshold in the ruler"
    ),
    SCEDCollectionRefusalReason.MISSING_NOVELTY_CRITERION: (
        "record the novelty criterion in the ruler"
    ),
    SCEDCollectionRefusalReason.M2_RULER_HASH_MISMATCH: (
        "re-freeze so the M2 artifact ruler hash equals the ruler canonical hash"
    ),
    SCEDCollectionRefusalReason.M2_LADDER_MISMATCH: (
        "re-freeze so the M2 ladder thresholds equal the frozen ruler thresholds"
    ),
    SCEDCollectionRefusalReason.M2_FREEZE_REFUSED: (
        "resolve the underlying M2 freeze refusal before collection"
    ),
}


class _SCEDInputError(ValueError):
    def __init__(self, reason: SCEDCollectionRefusalReason, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(detail or reason.value)


# --- ruler content ------------------------------------------------------------


@dataclass(frozen=True)
class HeldOutRefusalSet:
    """A sealed set of refusal prompts held out of jailbreak tuning.

    Only durable references and a sealed digest are stored -- never the refusal
    prompt text -- so the held-out set is committed (its membership cannot be
    silently swapped) without importing weaponizable content into the repo.
    """

    set_id: str
    prompt_refs: tuple[str, ...]
    sealed_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "set_id", _required_string(self.set_id, field="set_id"))
        refs = _ref_tuple(self.prompt_refs, field="prompt_refs")
        if not refs:
            raise ValueError("held-out refusal set requires at least one prompt ref")
        object.__setattr__(self, "prompt_refs", refs)
        object.__setattr__(
            self, "sealed_digest", _required_string(self.sealed_digest, field="sealed_digest")
        )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> HeldOutRefusalSet:
        return cls(
            set_id=raw.get("set_id"),  # type: ignore[arg-type]
            prompt_refs=_seq(raw.get("prompt_refs")),
            sealed_digest=raw.get("sealed_digest"),  # type: ignore[arg-type]
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "set_id": self.set_id,
            "prompt_refs": list(self.prompt_refs),
            "sealed_digest": self.sealed_digest,
        }


@dataclass(frozen=True)
class PolicyCategoryThreshold:
    """Universality bar: a candidate must clear at least N policy categories."""

    categories: tuple[str, ...]
    min_categories_cleared: int

    def __post_init__(self) -> None:
        categories = _ref_tuple(self.categories, field="categories")
        if not categories:
            raise ValueError("policy category threshold requires at least one category")
        object.__setattr__(self, "categories", categories)
        minimum = _finite_int(self.min_categories_cleared, field="min_categories_cleared")
        if not 1 <= minimum <= len(categories):
            raise ValueError(f"min_categories_cleared must be between 1 and {len(categories)}")
        object.__setattr__(self, "min_categories_cleared", minimum)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> PolicyCategoryThreshold:
        return cls(
            categories=_seq(raw.get("categories")),
            min_categories_cleared=raw.get("min_categories_cleared"),  # type: ignore[arg-type]
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "categories": list(self.categories),
            "min_categories_cleared": self.min_categories_cleared,
        }


@dataclass(frozen=True)
class NoveltyCriterion:
    """A candidate too similar to a known technique is a duplicate, not novel."""

    known_technique_refs: tuple[str, ...]
    max_duplicate_similarity: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "known_technique_refs",
            _ref_tuple(self.known_technique_refs, field="known_technique_refs"),
        )
        similarity = _finite_float(self.max_duplicate_similarity, field="max_duplicate_similarity")
        if not 0.0 <= similarity <= 1.0:
            raise ValueError("max_duplicate_similarity must be between 0.0 and 1.0")
        object.__setattr__(self, "max_duplicate_similarity", similarity)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> NoveltyCriterion:
        return cls(
            known_technique_refs=_seq(raw.get("known_technique_refs")),
            max_duplicate_similarity=raw.get("max_duplicate_similarity"),  # type: ignore[arg-type]
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "known_technique_refs": list(self.known_technique_refs),
            "max_duplicate_similarity": self.max_duplicate_similarity,
        }


@dataclass(frozen=True)
class SCEDJailbreakRuler:
    """The frozen universal-jailbreak-effectiveness ruler.

    The canonical hash covers both the qualitative components (held-out set,
    policy-category threshold, novelty criterion) and the numeric effectiveness
    thresholds, so nothing that defines effectiveness can drift from the frozen
    hash.
    """

    ruler_id: str
    held_out_refusal_set: HeldOutRefusalSet
    policy_category_threshold: PolicyCategoryThreshold
    novelty_criterion: NoveltyCriterion
    min_corroboration_count: int = 2
    freshness_ttl_seconds: int = 86_400
    positive_threshold: float = 0.0
    negative_threshold: float = -1.0

    def __post_init__(self) -> None:
        if not isinstance(self.held_out_refusal_set, HeldOutRefusalSet):
            raise TypeError("held_out_refusal_set must be a HeldOutRefusalSet")
        if not isinstance(self.policy_category_threshold, PolicyCategoryThreshold):
            raise TypeError("policy_category_threshold must be a PolicyCategoryThreshold")
        if not isinstance(self.novelty_criterion, NoveltyCriterion):
            raise TypeError("novelty_criterion must be a NoveltyCriterion")
        object.__setattr__(self, "ruler_id", _required_string(self.ruler_id, field="ruler_id"))
        object.__setattr__(
            self,
            "min_corroboration_count",
            _finite_int(self.min_corroboration_count, field="min_corroboration_count"),
        )
        object.__setattr__(
            self,
            "freshness_ttl_seconds",
            _finite_int(self.freshness_ttl_seconds, field="freshness_ttl_seconds"),
        )
        object.__setattr__(
            self,
            "positive_threshold",
            _finite_float(self.positive_threshold, field="positive_threshold"),
        )
        object.__setattr__(
            self,
            "negative_threshold",
            _finite_float(self.negative_threshold, field="negative_threshold"),
        )
        if self.min_corroboration_count < 1:
            raise ValueError("min_corroboration_count must be >= 1")
        if self.freshness_ttl_seconds < 0:
            raise ValueError("freshness_ttl_seconds must be >= 0")
        if self.negative_threshold > self.positive_threshold:
            raise ValueError("negative_threshold must be <= positive_threshold")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": SCED_RULER_SCHEMA,
            "ruler_id": self.ruler_id,
            "held_out_refusal_set": self.held_out_refusal_set.to_dict(),
            "policy_category_threshold": self.policy_category_threshold.to_dict(),
            "novelty_criterion": self.novelty_criterion.to_dict(),
            "min_corroboration_count": self.min_corroboration_count,
            "freshness_ttl_seconds": self.freshness_ttl_seconds,
            "positive_threshold": self.positive_threshold,
            "negative_threshold": self.negative_threshold,
        }

    def canonical_hash(self) -> str:
        blob = json.dumps(self.canonical_payload(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def to_ladder(self, *, as_of: datetime | None = None) -> MonDLCLadder:
        return MonDLCLadder(
            ruler_hash=self.canonical_hash(),
            min_corroboration_count=self.min_corroboration_count,
            freshness_ttl_seconds=self.freshness_ttl_seconds,
            as_of=as_of,
            positive_threshold=self.positive_threshold,
            negative_threshold=self.negative_threshold,
        )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> SCEDJailbreakRuler:
        held = _required_component(
            raw, "held_out_refusal_set", SCEDCollectionRefusalReason.MISSING_HELD_OUT_REFUSAL_SET
        )
        policy = _required_component(
            raw,
            "policy_category_threshold",
            SCEDCollectionRefusalReason.MISSING_POLICY_CATEGORY_THRESHOLD,
        )
        novelty = _required_component(
            raw, "novelty_criterion", SCEDCollectionRefusalReason.MISSING_NOVELTY_CRITERION
        )
        try:
            return cls(
                ruler_id=raw.get("ruler_id"),  # type: ignore[arg-type]
                held_out_refusal_set=HeldOutRefusalSet.from_mapping(held),
                policy_category_threshold=PolicyCategoryThreshold.from_mapping(policy),
                novelty_criterion=NoveltyCriterion.from_mapping(novelty),
                min_corroboration_count=raw.get("min_corroboration_count", 2),
                freshness_ttl_seconds=raw.get("freshness_ttl_seconds", 86_400),
                positive_threshold=raw.get("positive_threshold", 0.0),
                negative_threshold=raw.get("negative_threshold", -1.0),
            )
        except (TypeError, ValueError) as exc:
            raise _SCEDInputError(SCEDCollectionRefusalReason.INVALID_RULER, str(exc)) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "ruler_id": self.ruler_id,
            "held_out_refusal_set": self.held_out_refusal_set.to_dict(),
            "policy_category_threshold": self.policy_category_threshold.to_dict(),
            "novelty_criterion": self.novelty_criterion.to_dict(),
            "min_corroboration_count": self.min_corroboration_count,
            "freshness_ttl_seconds": self.freshness_ttl_seconds,
            "positive_threshold": self.positive_threshold,
            "negative_threshold": self.negative_threshold,
        }


@dataclass(frozen=True)
class SCEDRulerFreeze:
    """A frozen SCED ruler bound to its signed M2 freeze artifact."""

    ruler: SCEDJailbreakRuler
    m2_artifact: M2FreezeArtifact

    def __post_init__(self) -> None:
        if not isinstance(self.ruler, SCEDJailbreakRuler):
            raise TypeError("ruler must be a SCEDJailbreakRuler")
        if not isinstance(self.m2_artifact, M2FreezeArtifact):
            raise TypeError("m2_artifact must be an M2FreezeArtifact")

    def to_dict(self) -> dict[str, Any]:
        return {"ruler": self.ruler.to_dict(), "m2_artifact": self.m2_artifact.to_dict()}

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> SCEDRulerFreeze:
        ruler_raw = raw.get("ruler")
        if not isinstance(ruler_raw, Mapping):
            raise _SCEDInputError(SCEDCollectionRefusalReason.MISSING_RULER)
        m2_raw = raw.get("m2_artifact")
        if m2_raw is None:
            m2_raw = raw.get("freeze_artifact")
        if not isinstance(m2_raw, Mapping):
            raise _SCEDInputError(
                SCEDCollectionRefusalReason.INVALID_FREEZE, "missing m2 freeze artifact"
            )
        return cls(
            ruler=SCEDJailbreakRuler.from_mapping(ruler_raw),
            m2_artifact=M2FreezeArtifact.from_mapping(m2_raw),
        )


# --- collection admission gate ------------------------------------------------


@dataclass(frozen=True)
class SCEDCollectionAdmission:
    """Result of checking whether SCED collection may proceed.

    ``bool()`` is deliberately undefined: callers must inspect ``status``.
    """

    verifier: str
    verifier_version: int
    status: GateStatus
    gate_result: GateResult
    reason: str
    refusal_reason: SCEDCollectionRefusalReason | None
    m2_refusal_reason: M2FreezeRefusalReason | None = None
    ruler: SCEDJailbreakRuler | None = None
    ruler_hash: str | None = None
    ruler_hash_commit: str | None = None
    evidence_refs: tuple[str, ...] = ()
    next_action: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, GateStatus):
            raise TypeError("SCEDCollectionAdmission.status must be a GateStatus identity")
        if not isinstance(self.gate_result, GateResult):
            raise TypeError("SCEDCollectionAdmission.gate_result must be a GateResult identity")
        if self.refusal_reason is not None and not isinstance(
            self.refusal_reason, SCEDCollectionRefusalReason
        ):
            raise TypeError("refusal_reason must be a SCEDCollectionRefusalReason")
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))

    @property
    def ok(self) -> bool:
        return self.status is GateStatus.LIT

    def __bool__(self) -> bool:
        raise TypeError("SCEDCollectionAdmission truthiness is undefined; inspect status")

    def to_dict(self) -> dict[str, Any]:
        return {
            "verifier": self.verifier,
            "verifier_version": self.verifier_version,
            "status": self.status.value,
            "ok": self.ok,
            "reason": self.reason,
            "refusal_reason": None if self.refusal_reason is None else self.refusal_reason.value,
            "m2_refusal_reason": (
                None if self.m2_refusal_reason is None else self.m2_refusal_reason.value
            ),
            "next_action": self.next_action,
            "ruler_id": None if self.ruler is None else self.ruler.ruler_id,
            "ruler_hash": self.ruler_hash,
            "ruler_hash_commit": self.ruler_hash_commit,
            "evidence_refs": list(self.evidence_refs),
        }


class SCEDCollectionRefusal(RuntimeError):
    """Raised when a caller requires collection admission and the gate refuses."""

    def __init__(self, admission: SCEDCollectionAdmission) -> None:
        self.admission = admission
        super().__init__(admission.reason)


def freeze_ruler(
    ruler: SCEDJailbreakRuler,
    *,
    artifact_id: str,
    budget_envelope: M2BudgetEnvelope | Mapping[str, Any],
    signer: str,
    signed_at: datetime,
    signature_ref: str,
    evidence_refs: Sequence[str] = (),
    as_of: datetime | None = None,
) -> SCEDRulerFreeze:
    """Build a freeze whose M2 artifact ruler hash is the ruler canonical hash."""

    envelope = (
        budget_envelope
        if isinstance(budget_envelope, M2BudgetEnvelope)
        else M2BudgetEnvelope.from_mapping(budget_envelope)
    )
    ruler_hash = ruler.canonical_hash()
    artifact = M2FreezeArtifact(
        artifact_id=artifact_id,
        budget_envelope=envelope,
        ladder=ruler.to_ladder(as_of=as_of),
        ruler_hash=ruler_hash,
        signer=signer,
        signed_at=signed_at,
        signature_ref=signature_ref,
        evidence_refs=tuple(evidence_refs),
    )
    return SCEDRulerFreeze(ruler=ruler, m2_artifact=artifact)


def verify_collection_admission(
    freeze: SCEDRulerFreeze | Mapping[str, Any] | None,
    *,
    ruler_hash_commit: str | None,
) -> SCEDCollectionAdmission:
    """Admit SCED collection only when a signed freeze binds this exact ruler.

    Collection cannot precede freeze: without a present freeze whose M2 artifact
    hash equals the ruler's canonical hash and whose commit hash matches, the
    gate stays DARK.
    """

    if freeze is None:
        return _refused(SCEDCollectionRefusalReason.MISSING_FREEZE)
    try:
        ruler, m2_raw = _coerce_freeze(freeze)
    except _SCEDInputError as exc:
        return _refused(exc.reason, detail=exc.detail)

    expected = ruler.canonical_hash()
    commit = _commit_str(ruler_hash_commit)
    artifact = _coerce_m2_typed(m2_raw)
    if artifact is not None:
        if artifact.ruler_hash != expected:
            return _refused(
                SCEDCollectionRefusalReason.M2_RULER_HASH_MISMATCH,
                detail=f"artifact freezes {artifact.ruler_hash!r}, not the ruler hash",
                ruler=ruler,
                ruler_hash=expected,
                ruler_hash_commit=commit,
            )
        if not _ladder_matches_ruler(artifact.ladder, ruler):
            return _refused(
                SCEDCollectionRefusalReason.M2_LADDER_MISMATCH,
                ruler=ruler,
                ruler_hash=expected,
                ruler_hash_commit=commit,
            )

    m2 = verify_m2_freeze_artifact(
        artifact if artifact is not None else m2_raw,
        ruler_hash_commit=ruler_hash_commit,
    )
    if m2.status is not GateStatus.LIT:
        return _refused(
            SCEDCollectionRefusalReason.M2_FREEZE_REFUSED,
            detail=m2.reason,
            m2_refusal=m2.refusal_reason,
            ruler=ruler,
            ruler_hash=expected,
            ruler_hash_commit=m2.ruler_hash_commit,
        )

    return _admitted(ruler, expected, m2)


def require_collection_admission(
    freeze: SCEDRulerFreeze | Mapping[str, Any] | None,
    *,
    ruler_hash_commit: str | None,
) -> SCEDCollectionAdmission:
    """Return the admission on LIT or raise :class:`SCEDCollectionRefusal`."""

    admission = verify_collection_admission(freeze, ruler_hash_commit=ruler_hash_commit)
    if admission.status is not GateStatus.LIT:
        raise SCEDCollectionRefusal(admission)
    return admission


def _coerce_freeze(
    freeze: SCEDRulerFreeze | Mapping[str, Any],
) -> tuple[SCEDJailbreakRuler, Any]:
    if isinstance(freeze, SCEDRulerFreeze):
        return freeze.ruler, freeze.m2_artifact
    if isinstance(freeze, Mapping):
        ruler_raw = freeze.get("ruler")
        if ruler_raw is None:
            raise _SCEDInputError(SCEDCollectionRefusalReason.MISSING_RULER)
        ruler = _coerce_ruler(ruler_raw)
        m2_raw = freeze.get("m2_artifact")
        if m2_raw is None:
            m2_raw = freeze.get("freeze_artifact")
        return ruler, m2_raw
    raise _SCEDInputError(
        SCEDCollectionRefusalReason.INVALID_FREEZE,
        "freeze must be a SCEDRulerFreeze or mapping",
    )


def _coerce_ruler(value: SCEDJailbreakRuler | Mapping[str, Any]) -> SCEDJailbreakRuler:
    if isinstance(value, SCEDJailbreakRuler):
        return value
    if isinstance(value, Mapping):
        return SCEDJailbreakRuler.from_mapping(value)
    raise _SCEDInputError(
        SCEDCollectionRefusalReason.INVALID_RULER,
        "ruler must be a SCEDJailbreakRuler or mapping",
    )


def _coerce_m2_typed(value: Any) -> M2FreezeArtifact | None:
    if isinstance(value, M2FreezeArtifact):
        return value
    if isinstance(value, Mapping):
        try:
            return M2FreezeArtifact.from_mapping(value)
        except (TypeError, ValueError):
            return None
    return None


def _ladder_matches_ruler(ladder: MonDLCLadder, ruler: SCEDJailbreakRuler) -> bool:
    return (
        ladder.min_corroboration_count == ruler.min_corroboration_count
        and ladder.freshness_ttl_seconds == ruler.freshness_ttl_seconds
        and ladder.positive_threshold == ruler.positive_threshold
        and ladder.negative_threshold == ruler.negative_threshold
    )


def _admission_evidence(ruler: SCEDJailbreakRuler, ruler_hash: str, m2: Any) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            (
                f"sced-ruler:{ruler.ruler_id}",
                f"ruler-hash:{ruler_hash}",
                *m2.evidence_refs,
            )
        )
    )


def _admitted(ruler: SCEDJailbreakRuler, ruler_hash: str, m2: Any) -> SCEDCollectionAdmission:
    evidence = _admission_evidence(ruler, ruler_hash, m2)
    return SCEDCollectionAdmission(
        verifier=SCED_RULER_NAME,
        verifier_version=SCED_RULER_VERSION,
        status=GateStatus.LIT,
        gate_result=GateResult(
            status=GateStatus.LIT,
            verdict=True,
            reason="sced_ruler_freeze_present",
            evidence_refs=evidence,
        ),
        reason="sced_ruler_freeze_present",
        refusal_reason=None,
        ruler=ruler,
        ruler_hash=ruler_hash,
        ruler_hash_commit=m2.ruler_hash_commit,
        evidence_refs=evidence,
        next_action=None,
    )


def _refused(
    reason: SCEDCollectionRefusalReason,
    *,
    detail: str = "",
    m2_refusal: M2FreezeRefusalReason | None = None,
    ruler: SCEDJailbreakRuler | None = None,
    ruler_hash: str | None = None,
    ruler_hash_commit: str | None = None,
) -> SCEDCollectionAdmission:
    next_action = _NEXT_ACTIONS[reason]
    message = reason.value if not detail else f"{reason.value}: {detail}"
    message = f"{message}; next action: {next_action}"
    return SCEDCollectionAdmission(
        verifier=SCED_RULER_NAME,
        verifier_version=SCED_RULER_VERSION,
        status=GateStatus.DARK,
        gate_result=GateResult(
            status=GateStatus.DARK,
            verdict=None,
            reason=message,
            evidence_refs=(),
        ),
        reason=message,
        refusal_reason=reason,
        m2_refusal_reason=m2_refusal,
        ruler=ruler,
        ruler_hash=ruler_hash,
        ruler_hash_commit=ruler_hash_commit,
        evidence_refs=(),
        next_action=next_action,
    )


def _required_component(
    raw: Mapping[str, Any], field: str, reason: SCEDCollectionRefusalReason
) -> Mapping[str, Any]:
    value = raw.get(field)
    if not isinstance(value, Mapping):
        raise _SCEDInputError(reason, f"{field} must be a mapping")
    return value


def _commit_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _required_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


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


def _seq(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ValueError("expected a sequence of strings")
    return tuple(value)


def _finite_float(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    numeric = float(value)
    if not isfinite(numeric):
        raise ValueError(f"{field} must be finite")
    return numeric


def _finite_int(value: Any, *, field: str) -> int:
    numeric = _finite_float(value, field=field)
    integer = int(numeric)
    if integer != numeric:
        raise ValueError(f"{field} must be an integer")
    return integer


__all__ = [
    "SCED_RULER_NAME",
    "SCED_RULER_SCHEMA",
    "SCED_RULER_VERSION",
    "HeldOutRefusalSet",
    "NoveltyCriterion",
    "PolicyCategoryThreshold",
    "SCEDCollectionAdmission",
    "SCEDCollectionRefusal",
    "SCEDCollectionRefusalReason",
    "SCEDJailbreakRuler",
    "SCEDRulerFreeze",
    "freeze_ruler",
    "require_collection_admission",
    "verify_collection_admission",
]
