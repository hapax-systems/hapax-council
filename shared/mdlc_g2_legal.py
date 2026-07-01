"""MonDLC G2 legal venue gate.

G2 answers only whether a disposition has an exact fresh LIT legal-posture row
for its surface, venue, and instrument. It does not decide counterparty
eligibility (G1) and does not score measured return value (M).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from shared.capdlc_lifecycle import GateResult, GateStatus
from shared.legal_posture_registry import (
    G2GateDecision,
    G2GateInput,
    G2Reason,
    LegalPostureRegistry,
    LegalPostureRow,
    evaluate_g2_commit_gate,
)

MONDLC_G2_LEGAL_NAME: Final = "mdlc_g2_legal"
MONDLC_G2_LEGAL_VERSION: Final = 1


class G2LegalRefusalReason(StrEnum):
    """Machine-readable fail-closed G2 refusal reasons."""

    MISSING_TARGET = "missing_target"
    INVALID_TARGET = "invalid_target"
    REGISTRY_UNREADABLE = "registry_unreadable"
    NO_EXACT_ROW = "no_exact_row"
    DARK_ROW = "dark_row"
    UNSIGNED_NON_DARK = "unsigned_non_dark"
    STALE_NON_DARK = "stale_non_dark"
    PARTIAL_NOT_COMMITTABLE = "partial_not_committable"
    LIT_AUTHORITY_NOT_COMMITTABLE = "lit_authority_not_committable"
    LIT_HAS_OPEN_QUESTIONS = "lit_has_open_questions"


_G2_REASON_TO_REFUSAL: Final[dict[G2Reason, G2LegalRefusalReason]] = {
    G2Reason.INVALID_TARGET: G2LegalRefusalReason.INVALID_TARGET,
    G2Reason.REGISTRY_UNREADABLE: G2LegalRefusalReason.REGISTRY_UNREADABLE,
    G2Reason.NO_EXACT_ROW: G2LegalRefusalReason.NO_EXACT_ROW,
    G2Reason.DARK_ROW: G2LegalRefusalReason.DARK_ROW,
    G2Reason.UNSIGNED_NON_DARK: G2LegalRefusalReason.UNSIGNED_NON_DARK,
    G2Reason.STALE_NON_DARK: G2LegalRefusalReason.STALE_NON_DARK,
    G2Reason.PARTIAL_NOT_COMMITTABLE: G2LegalRefusalReason.PARTIAL_NOT_COMMITTABLE,
    G2Reason.LIT_AUTHORITY_NOT_COMMITTABLE: (G2LegalRefusalReason.LIT_AUTHORITY_NOT_COMMITTABLE),
    G2Reason.LIT_HAS_OPEN_QUESTIONS: G2LegalRefusalReason.LIT_HAS_OPEN_QUESTIONS,
}


_NEXT_ACTIONS: Final[dict[G2LegalRefusalReason, str]] = {
    G2LegalRefusalReason.MISSING_TARGET: (
        "attach a surface, venue, and instrument target before M2 commit"
    ),
    G2LegalRefusalReason.INVALID_TARGET: (
        "repair the g2 target so surface, venue, and instrument are non-empty strings"
    ),
    G2LegalRefusalReason.REGISTRY_UNREADABLE: (
        "restore a readable legal-posture registry before M2 commit"
    ),
    G2LegalRefusalReason.NO_EXACT_ROW: (
        "add an exact fresh operator-signed LIT legal-posture row before M2 commit"
    ),
    G2LegalRefusalReason.DARK_ROW: (
        "upgrade the exact legal-posture row to fresh operator-signed LIT before M2 commit"
    ),
    G2LegalRefusalReason.UNSIGNED_NON_DARK: (
        "obtain operator signature for the exact non-DARK legal-posture row"
    ),
    G2LegalRefusalReason.STALE_NON_DARK: (
        "refresh the exact legal-posture row and operator signature before M2 commit"
    ),
    G2LegalRefusalReason.PARTIAL_NOT_COMMITTABLE: (
        "resolve the partial legal posture and upgrade to LIT before M2 commit"
    ),
    G2LegalRefusalReason.LIT_AUTHORITY_NOT_COMMITTABLE: (
        "replace the LIT row authority with statute, regulation, case law, ToS clause, "
        "legal opinion, or agency guidance"
    ),
    G2LegalRefusalReason.LIT_HAS_OPEN_QUESTIONS: (
        "resolve every open legal-posture question before M2 commit"
    ),
}


@dataclass(frozen=True)
class G2LegalVerification:
    """Result of verifying G2 legal venue eligibility."""

    validator: str
    validator_version: int
    status: GateStatus
    gate_result: GateResult
    reason: str
    refusal_reason: G2LegalRefusalReason | None
    target: G2GateInput | None = None
    row: LegalPostureRow | None = None
    advisory_row: LegalPostureRow | None = None
    stale: bool = False
    evidence_refs: tuple[str, ...] = ()
    next_action: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, GateStatus):
            raise TypeError("G2LegalVerification.status must be a GateStatus identity")
        if not isinstance(self.gate_result, GateResult):
            raise TypeError("G2LegalVerification.gate_result must be a GateResult identity")
        if self.refusal_reason is not None and not isinstance(
            self.refusal_reason, G2LegalRefusalReason
        ):
            raise TypeError("refusal_reason must be a G2LegalRefusalReason")
        if self.target is not None and not isinstance(self.target, G2GateInput):
            raise TypeError("target must be a G2GateInput")
        object.__setattr__(self, "evidence_refs", _string_tuple(self.evidence_refs))

    @property
    def ok(self) -> bool:
        return self.status is GateStatus.LIT

    def __bool__(self) -> bool:
        raise TypeError("G2LegalVerification truthiness is undefined; inspect status")

    def to_dict(self) -> dict[str, Any]:
        return {
            "validator": self.validator,
            "validator_version": self.validator_version,
            "status": self.status.value,
            "ok": self.ok,
            "reason": self.reason,
            "refusal_reason": None if self.refusal_reason is None else self.refusal_reason.value,
            "next_action": self.next_action,
            "target": None if self.target is None else _target_to_dict(self.target),
            "row": None if self.row is None else _row_to_dict(self.row),
            "advisory_row": None if self.advisory_row is None else _row_to_dict(self.advisory_row),
            "stale": self.stale,
            "evidence_refs": list(self.evidence_refs),
            "gate_result": {
                "status": self.gate_result.status.value,
                "verdict": self.gate_result.verdict,
                "reason": self.gate_result.reason,
                "evidence_refs": list(self.gate_result.evidence_refs),
            },
        }


class G2LegalRefusal(RuntimeError):
    """Raised when a caller requires G2 legal admission and verification blocks."""

    def __init__(self, verification: G2LegalVerification) -> None:
        self.verification = verification
        super().__init__(verification.reason)


class _G2InputError(ValueError):
    def __init__(self, reason: G2LegalRefusalReason, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(detail or reason.value)


def verify_g2_legal(
    target: G2GateInput | Mapping[str, Any] | None,
    *,
    registry: LegalPostureRegistry | None = None,
    registry_path: Path | str | None = None,
    today: date | None = None,
) -> G2LegalVerification:
    """Verify that G2 admits a committed MonDLC disposition."""

    if target is None:
        return _refused(G2LegalRefusalReason.MISSING_TARGET)
    try:
        gate_input = _coerce_target(target)
    except _G2InputError as exc:
        return _refused(exc.reason, detail=exc.detail)

    decision = evaluate_g2_commit_gate(
        gate_input,
        registry=registry,
        registry_path=registry_path,
        today=today,
    )
    if decision.admitted:
        return _admitted(decision)
    return _refused_from_decision(decision)


def require_g2_legal(
    target: G2GateInput | Mapping[str, Any] | None,
    *,
    registry: LegalPostureRegistry | None = None,
    registry_path: Path | str | None = None,
    today: date | None = None,
) -> LegalPostureRow:
    """Return the admitted exact legal row or raise :class:`G2LegalRefusal`."""

    verification = verify_g2_legal(
        target,
        registry=registry,
        registry_path=registry_path,
        today=today,
    )
    if verification.status is not GateStatus.LIT or verification.row is None:
        raise G2LegalRefusal(verification)
    return verification.row


def _coerce_target(value: G2GateInput | Mapping[str, Any]) -> G2GateInput:
    if isinstance(value, G2GateInput):
        return value
    if not isinstance(value, Mapping):
        raise _G2InputError(
            G2LegalRefusalReason.INVALID_TARGET,
            "target must be a G2GateInput or mapping",
        )
    return G2GateInput(
        surface=_target_field(value, "surface"),
        venue=_target_field(value, "venue"),
        instrument=_target_field(value, "instrument"),
    )


def _target_field(raw: Mapping[str, Any], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise _G2InputError(
            G2LegalRefusalReason.INVALID_TARGET,
            f"{field} must be a non-empty string",
        )
    return value.strip()


def _admitted(decision: G2GateDecision) -> G2LegalVerification:
    if decision.row is None:
        raise ValueError("admitted g2 decision must carry the exact row")
    evidence_refs = _decision_evidence_refs(decision)
    return G2LegalVerification(
        validator=MONDLC_G2_LEGAL_NAME,
        validator_version=MONDLC_G2_LEGAL_VERSION,
        status=GateStatus.LIT,
        gate_result=GateResult(
            status=GateStatus.LIT,
            verdict=True,
            reason="fresh_lit_legal_posture_row",
            evidence_refs=evidence_refs,
        ),
        reason="fresh_lit_legal_posture_row",
        refusal_reason=None,
        target=decision.target,
        row=decision.row,
        advisory_row=decision.advisory_row,
        stale=False,
        evidence_refs=evidence_refs,
    )


def _refused_from_decision(decision: G2GateDecision) -> G2LegalVerification:
    refusal_reason = _G2_REASON_TO_REFUSAL[decision.reason]
    return _refused(
        refusal_reason,
        detail=decision.message,
        target=decision.target,
        row=decision.row,
        advisory_row=decision.advisory_row,
        stale=decision.stale,
    )


def _refused(
    reason: G2LegalRefusalReason,
    *,
    detail: str = "",
    target: G2GateInput | None = None,
    row: LegalPostureRow | None = None,
    advisory_row: LegalPostureRow | None = None,
    stale: bool = False,
) -> G2LegalVerification:
    next_action = _NEXT_ACTIONS[reason]
    message = reason.value if not detail else f"{reason.value}: {detail}"
    message = f"{message}; next action: {next_action}"
    evidence_refs = _row_evidence_refs(row) if row is not None else ()
    return G2LegalVerification(
        validator=MONDLC_G2_LEGAL_NAME,
        validator_version=MONDLC_G2_LEGAL_VERSION,
        status=GateStatus.DARK,
        gate_result=GateResult(
            status=GateStatus.DARK,
            verdict=None,
            reason=message,
            evidence_refs=evidence_refs,
        ),
        reason=message,
        refusal_reason=reason,
        target=target,
        row=row,
        advisory_row=advisory_row,
        stale=stale,
        evidence_refs=evidence_refs,
        next_action=next_action,
    )


def _decision_evidence_refs(decision: G2GateDecision) -> tuple[str, ...]:
    refs: list[str] = []
    if decision.row is not None:
        refs.extend(_row_evidence_refs(decision.row))
    elif decision.target is not None:
        refs.append(_target_ref(decision.target))
    return tuple(dict.fromkeys(refs))


def _row_evidence_refs(row: LegalPostureRow) -> tuple[str, ...]:
    refs = [_target_ref(G2GateInput(row.surface, row.venue, row.instrument))]
    if row.source_task:
        refs.append(f"cc-task:{row.source_task}")
    return tuple(dict.fromkeys(refs))


def _target_ref(target: G2GateInput) -> str:
    return f"legal-posture-row:{target.surface}:{target.venue}:{target.instrument}"


def _target_to_dict(target: G2GateInput) -> dict[str, str]:
    return {
        "surface": target.surface,
        "venue": target.venue,
        "instrument": target.instrument,
    }


def _row_to_dict(row: LegalPostureRow) -> dict[str, Any]:
    return {
        "surface": row.surface,
        "venue": row.venue,
        "instrument": row.instrument,
        "g2_verdict": row.verdict.value,
        "authority_basis": row.authority_basis,
        "review_date": row.review_date.isoformat(),
        "freshness_ttl_days": row.freshness_ttl_days,
        "operator_signed": row.operator_signed,
        "operator_sign_date": None
        if row.operator_sign_date is None
        else row.operator_sign_date.isoformat(),
        "open_questions": list(row.open_questions),
        "blocks_surfaces": list(row.blocks_surfaces),
        "source_task": row.source_task,
    }


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, tuple):
        raise TypeError("evidence refs must be a tuple of strings")
    refs: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise TypeError("evidence refs must be a tuple of strings")
        if not item.strip():
            raise TypeError("evidence refs must contain non-empty strings")
        refs.append(item.strip())
    return tuple(refs)


__all__ = [
    "G2LegalRefusal",
    "G2LegalRefusalReason",
    "G2LegalVerification",
    "MONDLC_G2_LEGAL_NAME",
    "MONDLC_G2_LEGAL_VERSION",
    "require_g2_legal",
    "verify_g2_legal",
]
