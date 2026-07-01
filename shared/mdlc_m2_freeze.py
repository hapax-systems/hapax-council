"""MonDLC M2 freeze artifact contract.

The scorer consumes a frozen ladder. This module proves the freeze artifact
itself: artifact id, budget envelope, ladder, artifact ruler hash, signer,
timestamp, and signature reference must be present. The artifact ruler hash is
the authoritative frozen value; callers must pass the commit's carried ruler
hash so verifier admission proves end-to-end equality. Boolean freeze flags are
intentionally ignored, while budget-envelope publication/Flood routing fields
are part of the signed M2 evidence contract.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from math import isfinite
from pathlib import Path
from typing import Any, Final

from shared.capdlc_lifecycle import GateResult, GateStatus
from shared.legal_posture_registry import G2GateInput, LegalPostureRegistry, LegalPostureRow
from shared.mdlc_g2_legal import require_g2_legal
from shared.mdlc_measure import MonDLCLadder

MONDLC_M2_FREEZE_NAME: Final = "mdlc_m2_freeze"
MONDLC_M2_FREEZE_VERSION: Final = 1


class M2FreezeRefusalReason(StrEnum):
    """Machine-readable reasons the M2 freeze artifact cannot authorize commit."""

    MISSING_ARTIFACT = "missing_artifact"
    INVALID_ARTIFACT = "invalid_artifact"
    MISSING_ARTIFACT_ID = "missing_artifact_id"
    MISSING_BUDGET_ENVELOPE = "missing_budget_envelope"
    INVALID_BUDGET_ENVELOPE = "invalid_budget_envelope"
    MISSING_LADDER = "missing_ladder"
    INVALID_LADDER = "invalid_ladder"
    MISSING_RULER_HASH = "missing_ruler_hash"
    MISSING_RULER_HASH_COMMIT = "missing_ruler_hash_commit"
    RULER_HASH_MISMATCH = "ruler_hash_mismatch"
    LADDER_RULER_HASH_MISMATCH = "ladder_ruler_hash_mismatch"
    MISSING_SIGNER = "missing_signer"
    MISSING_SIGNED_AT = "missing_signed_at"
    INVALID_SIGNED_AT = "invalid_signed_at"
    MISSING_SIGNATURE_REF = "missing_signature_ref"
    INVALID_EVIDENCE_REFS = "invalid_evidence_refs"
    G2_TARGET_MISMATCH = "g2_target_mismatch"
    PUBLISH_ONLY_WITHOUT_FLOOD_PLAN = "publish_only_without_flood_plan"


_NEXT_ACTIONS: Final[dict[M2FreezeRefusalReason, str]] = {
    M2FreezeRefusalReason.MISSING_ARTIFACT: ("attach the signed M2 freeze artifact before commit"),
    M2FreezeRefusalReason.INVALID_ARTIFACT: "repair the signed M2 freeze artifact",
    M2FreezeRefusalReason.MISSING_ARTIFACT_ID: (
        "record the freeze artifact id so presence can be witnessed"
    ),
    M2FreezeRefusalReason.MISSING_BUDGET_ENVELOPE: (
        "record the budget envelope inside the freeze artifact"
    ),
    M2FreezeRefusalReason.INVALID_BUDGET_ENVELOPE: (
        "repair the budget envelope fields before commit"
    ),
    M2FreezeRefusalReason.MISSING_LADDER: "record the frozen ruler ladder before commit",
    M2FreezeRefusalReason.INVALID_LADDER: "repair the frozen ruler ladder before commit",
    M2FreezeRefusalReason.MISSING_RULER_HASH: "record the artifact ruler hash",
    M2FreezeRefusalReason.MISSING_RULER_HASH_COMMIT: (
        "supply the commit ruler hash from the freeze artifact"
    ),
    M2FreezeRefusalReason.RULER_HASH_MISMATCH: (
        "refuse commit and re-run against the matching frozen ruler hash"
    ),
    M2FreezeRefusalReason.LADDER_RULER_HASH_MISMATCH: (
        "repair the artifact so ladder.ruler_hash and artifact.ruler_hash match"
    ),
    M2FreezeRefusalReason.MISSING_SIGNER: "record the signer of the freeze artifact",
    M2FreezeRefusalReason.MISSING_SIGNED_AT: "record the freeze signature timestamp",
    M2FreezeRefusalReason.INVALID_SIGNED_AT: "record signed_at as a valid timestamp",
    M2FreezeRefusalReason.MISSING_SIGNATURE_REF: (
        "record the durable signature reference for the freeze artifact"
    ),
    M2FreezeRefusalReason.INVALID_EVIDENCE_REFS: (
        "record evidence_refs as a sequence of non-empty strings"
    ),
    M2FreezeRefusalReason.G2_TARGET_MISMATCH: (
        "repair the M2 freeze artifact so its surface, venue, and instrument match the G2 target"
    ),
    M2FreezeRefusalReason.PUBLISH_ONLY_WITHOUT_FLOOD_PLAN: (
        "set budget_envelope.flood_plan or mark budget_envelope.non_public/"
        "budget_envelope.no_audience for the publish-only M2 freeze artifact"
    ),
}


@dataclass(frozen=True)
class M2BudgetEnvelope:
    """Budget envelope captured by the M2 freeze artifact."""

    authority_ref: str
    currency: str
    max_notional: float
    max_position: float
    purpose: str = ""
    surface: str = ""
    venue: str = ""
    instrument: str = ""
    publish_only: bool = False
    flood_plan: str = ""
    non_public: bool = False
    no_audience: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "authority_ref", _required_string(self.authority_ref))
        object.__setattr__(self, "currency", _required_string(self.currency).upper())
        object.__setattr__(
            self,
            "max_notional",
            _non_negative_float(self.max_notional, field="max_notional"),
        )
        object.__setattr__(
            self,
            "max_position",
            _non_negative_float(self.max_position, field="max_position"),
        )
        object.__setattr__(self, "purpose", _optional_string(self.purpose))
        object.__setattr__(self, "surface", _optional_string(self.surface))
        object.__setattr__(self, "venue", _optional_string(self.venue))
        object.__setattr__(self, "instrument", _optional_string(self.instrument))
        object.__setattr__(self, "publish_only", _optional_bool(self.publish_only))
        object.__setattr__(self, "flood_plan", _optional_string(self.flood_plan))
        object.__setattr__(self, "non_public", _optional_bool(self.non_public))
        object.__setattr__(self, "no_audience", _optional_bool(self.no_audience))

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> M2BudgetEnvelope:
        try:
            return cls(
                authority_ref=_required_mapping_string(raw, "authority_ref"),
                currency=_required_mapping_string(raw, "currency"),
                max_notional=_non_negative_float(raw.get("max_notional"), field="max_notional"),
                max_position=_non_negative_float(raw.get("max_position"), field="max_position"),
                purpose=_optional_string(raw.get("purpose")),
                surface=_optional_string(raw.get("surface")),
                venue=_optional_string(raw.get("venue")),
                instrument=_optional_string(raw.get("instrument")),
                publish_only=_optional_bool(raw.get("publish_only")),
                flood_plan=_optional_string(raw.get("flood_plan")),
                non_public=_optional_bool(raw.get("non_public")),
                no_audience=_optional_bool(raw.get("no_audience")),
            )
        except _FreezeInputError:
            raise
        except (TypeError, ValueError) as exc:
            raise _FreezeInputError(
                M2FreezeRefusalReason.INVALID_BUDGET_ENVELOPE, str(exc)
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ref": self.authority_ref,
            "currency": self.currency,
            "max_notional": self.max_notional,
            "max_position": self.max_position,
            "purpose": self.purpose,
            "surface": self.surface,
            "venue": self.venue,
            "instrument": self.instrument,
            "publish_only": self.publish_only,
            "flood_plan": self.flood_plan,
            "non_public": self.non_public,
            "no_audience": self.no_audience,
        }


@dataclass(frozen=True)
class M2FreezeArtifact:
    """Signed M2 freeze artifact.

    This object is evidence of freeze presence. It is not a boolean latch.
    """

    artifact_id: str
    budget_envelope: M2BudgetEnvelope
    ladder: MonDLCLadder
    ruler_hash: str
    signer: str
    signed_at: datetime
    signature_ref: str
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.budget_envelope, M2BudgetEnvelope):
            raise TypeError("budget_envelope must be an M2BudgetEnvelope")
        if not isinstance(self.ladder, MonDLCLadder):
            raise TypeError("ladder must be a MonDLCLadder")
        object.__setattr__(self, "artifact_id", _required_string(self.artifact_id))
        object.__setattr__(self, "ruler_hash", _required_string(self.ruler_hash))
        object.__setattr__(self, "signer", _required_string(self.signer))
        object.__setattr__(self, "signed_at", _ensure_utc_datetime(self.signed_at))
        object.__setattr__(self, "signature_ref", _required_string(self.signature_ref))
        object.__setattr__(self, "evidence_refs", _string_tuple(self.evidence_refs))

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> M2FreezeArtifact:
        artifact_id = _required_mapping_string(raw, "artifact_id")
        budget_raw = _required_mapping(raw, "budget_envelope")
        ladder_raw = _required_mapping(raw, "ladder")
        return cls(
            artifact_id=artifact_id,
            budget_envelope=M2BudgetEnvelope.from_mapping(budget_raw),
            ladder=_ladder_from_mapping(ladder_raw),
            ruler_hash=_required_mapping_string(raw, "ruler_hash"),
            signer=_required_mapping_string(raw, "signer"),
            signed_at=_required_mapping_datetime(raw, "signed_at"),
            signature_ref=_required_mapping_string(raw, "signature_ref"),
            evidence_refs=_evidence_refs_from_mapping(raw),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "budget_envelope": self.budget_envelope.to_dict(),
            "ladder": {
                "ruler_hash": self.ladder.ruler_hash,
                "min_corroboration_count": self.ladder.min_corroboration_count,
                "freshness_ttl_seconds": self.ladder.freshness_ttl_seconds,
                "as_of": None if self.ladder.as_of is None else self.ladder.as_of.isoformat(),
                "positive_threshold": self.ladder.positive_threshold,
                "negative_threshold": self.ladder.negative_threshold,
            },
            "ruler_hash": self.ruler_hash,
            "signer": self.signer,
            "signed_at": self.signed_at.isoformat(),
            "signature_ref": self.signature_ref,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class M2FreezeVerification:
    """Result of verifying M2 freeze presence for commit."""

    verifier: str
    verifier_version: int
    status: GateStatus
    gate_result: GateResult
    reason: str
    refusal_reason: M2FreezeRefusalReason | None
    artifact: M2FreezeArtifact | None = None
    ruler_hash_commit: str | None = None
    expected_ruler_hash: str | None = None
    evidence_refs: tuple[str, ...] = ()
    next_action: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, GateStatus):
            raise TypeError("M2FreezeVerification.status must be a GateStatus identity")
        if not isinstance(self.gate_result, GateResult):
            raise TypeError("M2FreezeVerification.gate_result must be a GateResult identity")
        if self.refusal_reason is not None and not isinstance(
            self.refusal_reason, M2FreezeRefusalReason
        ):
            raise TypeError("refusal_reason must be an M2FreezeRefusalReason")
        object.__setattr__(self, "evidence_refs", _string_tuple(self.evidence_refs))

    @property
    def ok(self) -> bool:
        return self.status is GateStatus.LIT

    def __bool__(self) -> bool:
        raise TypeError("M2FreezeVerification truthiness is undefined; inspect status")

    def to_dict(self) -> dict[str, Any]:
        return {
            "verifier": self.verifier,
            "verifier_version": self.verifier_version,
            "status": self.status.value,
            "ok": self.ok,
            "reason": self.reason,
            "refusal_reason": None if self.refusal_reason is None else self.refusal_reason.value,
            "next_action": self.next_action,
            "artifact_id": None if self.artifact is None else self.artifact.artifact_id,
            "ruler_hash_commit": self.ruler_hash_commit,
            "expected_ruler_hash": self.expected_ruler_hash,
            "evidence_refs": list(self.evidence_refs),
            "gate_result": {
                "status": self.gate_result.status.value,
                "verdict": self.gate_result.verdict,
                "reason": self.gate_result.reason,
                "evidence_refs": list(self.gate_result.evidence_refs),
            },
        }


@dataclass(frozen=True)
class M2CommitAdmission:
    """Commit-ready M2 admission after freeze and G2 legal gates both pass."""

    freeze_artifact: M2FreezeArtifact
    legal_row: LegalPostureRow

    def __post_init__(self) -> None:
        if not isinstance(self.freeze_artifact, M2FreezeArtifact):
            raise TypeError("freeze_artifact must be an M2FreezeArtifact")
        if not isinstance(self.legal_row, LegalPostureRow):
            raise TypeError("legal_row must be a LegalPostureRow")


class M2FreezeRefusal(RuntimeError):
    """Raised when a caller requires M2 freeze admission and verification blocks."""

    def __init__(self, verification: M2FreezeVerification) -> None:
        self.verification = verification
        super().__init__(verification.reason)


class _FreezeInputError(ValueError):
    def __init__(self, reason: M2FreezeRefusalReason, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(detail or reason.value)


def verify_m2_freeze_artifact(
    artifact: M2FreezeArtifact | Mapping[str, Any] | None,
    *,
    ruler_hash_commit: str | None,
) -> M2FreezeVerification:
    """Verify that M2 commit is backed by a signed freeze artifact."""

    if artifact is None:
        return _refused(M2FreezeRefusalReason.MISSING_ARTIFACT)
    try:
        frozen_artifact = _coerce_artifact(artifact)
    except _FreezeInputError as exc:
        return _refused(exc.reason, detail=exc.detail)

    commit = ruler_hash_commit.strip() if isinstance(ruler_hash_commit, str) else ""
    if not commit:
        return _refused(
            M2FreezeRefusalReason.MISSING_RULER_HASH_COMMIT,
            artifact=frozen_artifact,
            expected_ruler_hash=frozen_artifact.ruler_hash,
        )
    if frozen_artifact.ladder.ruler_hash != frozen_artifact.ruler_hash:
        return _refused(
            M2FreezeRefusalReason.LADDER_RULER_HASH_MISMATCH,
            artifact=frozen_artifact,
            ruler_hash_commit=commit,
            expected_ruler_hash=frozen_artifact.ruler_hash,
        )
    if commit != frozen_artifact.ruler_hash:
        return _refused(
            M2FreezeRefusalReason.RULER_HASH_MISMATCH,
            artifact=frozen_artifact,
            ruler_hash_commit=commit,
            expected_ruler_hash=frozen_artifact.ruler_hash,
        )
    if _is_publish_only_without_flood_path(frozen_artifact.budget_envelope):
        return _refused(
            M2FreezeRefusalReason.PUBLISH_ONLY_WITHOUT_FLOOD_PLAN,
            artifact=frozen_artifact,
            ruler_hash_commit=commit,
            expected_ruler_hash=frozen_artifact.ruler_hash,
        )

    evidence_refs = _freeze_evidence_refs(frozen_artifact)
    return M2FreezeVerification(
        verifier=MONDLC_M2_FREEZE_NAME,
        verifier_version=MONDLC_M2_FREEZE_VERSION,
        status=GateStatus.LIT,
        gate_result=GateResult(
            status=GateStatus.LIT,
            verdict=True,
            reason="m2_freeze_artifact_present",
            evidence_refs=evidence_refs,
        ),
        reason="m2_freeze_artifact_present",
        refusal_reason=None,
        artifact=frozen_artifact,
        ruler_hash_commit=commit,
        expected_ruler_hash=frozen_artifact.ruler_hash,
        evidence_refs=evidence_refs,
        next_action=None,
    )


def require_m2_freeze_artifact(
    artifact: M2FreezeArtifact | Mapping[str, Any] | None,
    *,
    ruler_hash_commit: str | None,
) -> M2FreezeArtifact:
    """Return the artifact or raise :class:`M2FreezeRefusal`."""

    verification = verify_m2_freeze_artifact(artifact, ruler_hash_commit=ruler_hash_commit)
    if verification.status is not GateStatus.LIT or verification.artifact is None:
        raise M2FreezeRefusal(verification)
    return verification.artifact


def require_m2_commit_admission(
    artifact: M2FreezeArtifact | Mapping[str, Any] | None,
    *,
    ruler_hash_commit: str | None,
    g2_target: G2GateInput | Mapping[str, Any] | None = None,
    registry: LegalPostureRegistry | None = None,
    registry_path: Path | str | None = None,
    today: date | None = None,
) -> M2CommitAdmission:
    """Require M2 freeze presence and an exact fresh signed LIT G2 row."""

    freeze_artifact = require_m2_freeze_artifact(
        artifact,
        ruler_hash_commit=ruler_hash_commit,
    )
    legal_row = require_g2_legal(
        _commit_g2_target(g2_target, freeze_artifact),
        registry=registry,
        registry_path=registry_path,
        today=today,
    )
    return M2CommitAdmission(freeze_artifact=freeze_artifact, legal_row=legal_row)


def _commit_g2_target(
    target: G2GateInput | Mapping[str, Any] | None,
    artifact: M2FreezeArtifact,
) -> G2GateInput | Mapping[str, Any]:
    envelope = artifact.budget_envelope
    envelope_target = G2GateInput(
        surface=envelope.surface,
        venue=envelope.venue,
        instrument=envelope.instrument,
    )
    if target is not None:
        supplied = _supplied_g2_target(target, artifact)
        if supplied != envelope_target:
            raise M2FreezeRefusal(
                _refused(
                    M2FreezeRefusalReason.G2_TARGET_MISMATCH,
                    detail="caller-supplied G2 target differs from the signed freeze envelope",
                    artifact=artifact,
                )
            )
    return envelope_target


def _supplied_g2_target(
    target: G2GateInput | Mapping[str, Any],
    artifact: M2FreezeArtifact,
) -> G2GateInput:
    try:
        if isinstance(target, G2GateInput):
            return G2GateInput(
                surface=_required_string(target.surface),
                venue=_required_string(target.venue),
                instrument=_required_string(target.instrument),
            )
        if isinstance(target, Mapping):
            return G2GateInput(
                surface=_required_mapping_string(target, "surface"),
                venue=_required_mapping_string(target, "venue"),
                instrument=_required_mapping_string(target, "instrument"),
            )
    except (TypeError, ValueError, _FreezeInputError) as exc:
        raise M2FreezeRefusal(
            _refused(
                M2FreezeRefusalReason.G2_TARGET_MISMATCH,
                detail=str(exc),
                artifact=artifact,
            )
        ) from exc
    raise M2FreezeRefusal(
        _refused(
            M2FreezeRefusalReason.G2_TARGET_MISMATCH,
            detail="g2_target must be a G2GateInput or mapping",
            artifact=artifact,
        )
    )


def _coerce_artifact(value: M2FreezeArtifact | Mapping[str, Any]) -> M2FreezeArtifact:
    if isinstance(value, M2FreezeArtifact):
        return value
    if not isinstance(value, Mapping):
        raise _FreezeInputError(
            M2FreezeRefusalReason.MISSING_ARTIFACT,
            "freeze artifact must be an M2FreezeArtifact or mapping",
        )
    return _artifact_from_mapping(value)


def _artifact_from_mapping(raw: Mapping[str, Any]) -> M2FreezeArtifact:
    try:
        return M2FreezeArtifact.from_mapping(raw)
    except _FreezeInputError:
        raise
    except TypeError as exc:
        raise _FreezeInputError(M2FreezeRefusalReason.INVALID_LADDER, str(exc)) from exc
    except ValueError as exc:
        raise _FreezeInputError(_reason_from_value_error(exc), str(exc)) from exc


def _reason_from_value_error(exc: ValueError) -> M2FreezeRefusalReason:
    message = str(exc)
    if message.startswith("budget_envelope"):
        return M2FreezeRefusalReason.INVALID_BUDGET_ENVELOPE
    if message.startswith("ladder"):
        return M2FreezeRefusalReason.INVALID_LADDER
    if message.startswith("signed_at"):
        return M2FreezeRefusalReason.INVALID_SIGNED_AT
    return M2FreezeRefusalReason.INVALID_ARTIFACT


def _refused(
    reason: M2FreezeRefusalReason,
    *,
    detail: str = "",
    artifact: M2FreezeArtifact | None = None,
    ruler_hash_commit: str | None = None,
    expected_ruler_hash: str | None = None,
) -> M2FreezeVerification:
    next_action = _NEXT_ACTIONS[reason]
    message = reason.value if not detail else f"{reason.value}: {detail}"
    message = f"{message}; next action: {next_action}"
    evidence_refs = () if artifact is None else _freeze_evidence_refs(artifact)
    return M2FreezeVerification(
        verifier=MONDLC_M2_FREEZE_NAME,
        verifier_version=MONDLC_M2_FREEZE_VERSION,
        status=GateStatus.DARK,
        gate_result=GateResult(
            status=GateStatus.DARK,
            verdict=None,
            reason=message,
            evidence_refs=evidence_refs,
        ),
        reason=message,
        refusal_reason=reason,
        artifact=artifact,
        ruler_hash_commit=ruler_hash_commit,
        expected_ruler_hash=expected_ruler_hash,
        evidence_refs=evidence_refs,
        next_action=next_action,
    )


def _freeze_evidence_refs(artifact: M2FreezeArtifact) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            (
                f"m2-freeze:{artifact.artifact_id}",
                f"ruler-hash:{artifact.ruler_hash}",
                artifact.signature_ref,
                *artifact.evidence_refs,
            )
        )
    )


def _is_publish_only_without_flood_path(envelope: M2BudgetEnvelope) -> bool:
    if not envelope.publish_only:
        return False
    if envelope.flood_plan:
        return False
    return not (envelope.non_public or envelope.no_audience)


def _required_mapping(raw: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    value = raw.get(field)
    if not isinstance(value, Mapping):
        reason = (
            M2FreezeRefusalReason.MISSING_BUDGET_ENVELOPE
            if field == "budget_envelope"
            else M2FreezeRefusalReason.MISSING_LADDER
        )
        raise _FreezeInputError(reason, f"{field} must be a mapping")
    return value


def _required_mapping_string(raw: Mapping[str, Any], field: str) -> str:
    try:
        return _required_string(raw.get(field))
    except ValueError as exc:
        raise _FreezeInputError(_missing_string_reason(field), f"{field} is required") from exc


def _missing_string_reason(field: str) -> M2FreezeRefusalReason:
    reasons = {
        "artifact_id": M2FreezeRefusalReason.MISSING_ARTIFACT_ID,
        "ruler_hash": M2FreezeRefusalReason.MISSING_RULER_HASH,
        "signer": M2FreezeRefusalReason.MISSING_SIGNER,
        "signature_ref": M2FreezeRefusalReason.MISSING_SIGNATURE_REF,
    }
    return reasons.get(field, M2FreezeRefusalReason.INVALID_BUDGET_ENVELOPE)


def _required_mapping_datetime(raw: Mapping[str, Any], field: str) -> datetime:
    value = raw.get(field)
    if value is None:
        raise _FreezeInputError(M2FreezeRefusalReason.MISSING_SIGNED_AT, "signed_at is required")
    try:
        return _coerce_datetime(value)
    except (TypeError, ValueError) as exc:
        raise _FreezeInputError(M2FreezeRefusalReason.INVALID_SIGNED_AT, str(exc)) from exc


def _evidence_refs_from_mapping(raw: Mapping[str, Any]) -> tuple[str, ...]:
    try:
        return _coerce_refs(raw.get("evidence_refs"))
    except TypeError as exc:
        raise _FreezeInputError(M2FreezeRefusalReason.INVALID_EVIDENCE_REFS, str(exc)) from exc


def _ladder_from_mapping(raw: Mapping[str, Any]) -> MonDLCLadder:
    try:
        return MonDLCLadder(
            ruler_hash=_required_string(raw.get("ruler_hash")),
            min_corroboration_count=_finite_int(
                _required_ladder_value(raw, "min_corroboration_count"),
                field="min_corroboration_count",
            ),
            freshness_ttl_seconds=_finite_int(
                _required_ladder_value(raw, "freshness_ttl_seconds"),
                field="freshness_ttl_seconds",
            ),
            as_of=_optional_datetime(raw.get("as_of")),
            positive_threshold=_finite_float(
                _required_ladder_value(raw, "positive_threshold"), field="positive_threshold"
            ),
            negative_threshold=_finite_float(
                _required_ladder_value(raw, "negative_threshold"), field="negative_threshold"
            ),
        )
    except _FreezeInputError:
        raise
    except (TypeError, ValueError) as exc:
        raise _FreezeInputError(M2FreezeRefusalReason.INVALID_LADDER, str(exc)) from exc


def _required_ladder_value(raw: Mapping[str, Any], field: str) -> Any:
    if field not in raw:
        raise _FreezeInputError(M2FreezeRefusalReason.INVALID_LADDER, f"ladder.{field} is required")
    return raw[field]


def _required_string(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("required string is missing")
    return value.strip()


def _optional_string(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("optional field must be a string")
    return value.strip()


def _optional_bool(value: Any) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise ValueError("optional field must be a boolean")
    return value


def _finite_float(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    numeric_value = float(value)
    if not isfinite(numeric_value):
        raise ValueError(f"{field} must be finite")
    return numeric_value


def _non_negative_float(value: Any, *, field: str) -> float:
    numeric_value = _finite_float(value, field=field)
    if numeric_value < 0:
        raise ValueError(f"{field} must be >= 0")
    return numeric_value


def _finite_int(value: Any, *, field: str) -> int:
    numeric_value = _finite_float(value, field=field)
    integer_value = int(numeric_value)
    if integer_value != numeric_value:
        raise ValueError(f"{field} must be an integer")
    return integer_value


def _optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    return _coerce_datetime(value)


def _coerce_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _ensure_utc_datetime(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("timestamp string is empty")
        return _ensure_utc_datetime(datetime.fromisoformat(text.replace("Z", "+00:00")))
    raise TypeError("timestamp must be a datetime or ISO-8601 string")


def _ensure_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _coerce_refs(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    return _string_tuple(value)


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise TypeError("evidence refs must be a string sequence")
    refs: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise TypeError("evidence refs must be a string sequence")
        if item.strip():
            refs.append(item.strip())
    return tuple(refs)


__all__ = [
    "MONDLC_M2_FREEZE_NAME",
    "MONDLC_M2_FREEZE_VERSION",
    "M2BudgetEnvelope",
    "M2CommitAdmission",
    "M2FreezeArtifact",
    "M2FreezeRefusal",
    "M2FreezeRefusalReason",
    "M2FreezeVerification",
    "require_m2_commit_admission",
    "require_m2_freeze_artifact",
    "verify_m2_freeze_artifact",
]
