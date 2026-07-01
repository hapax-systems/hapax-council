"""MonDLC G1 counterparty eligibility gate.

G1 answers only whether the counterparty class is eligible for an arbitrage
disposition. It does not decide G2 venue legality and does not score M value.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from shared.capdlc_lifecycle import GateResult, GateStatus

MONDLC_G1_COUNTERPARTY_NAME: Final = "mdlc_g1_counterparty"
MONDLC_G1_COUNTERPARTY_VERSION: Final = 1


class MonDLCCounterpartyClass(StrEnum):
    """Counterparty classes eligible for MonDLC arbitrage dispositions."""

    INSTITUTION = "institution"
    MARKET = "market"
    CORPORATION = "corporation"
    SOPHISTICATED_PARTY = "sophisticated_party"
    THE_WEALTHY = "the_wealthy"


ELIGIBLE_COUNTERPARTY_CLASSES: Final[frozenset[str]] = frozenset(
    item.value for item in MonDLCCounterpartyClass
)


class G1CounterpartyRefusalReason(StrEnum):
    """Machine-readable fail-closed G1 refusal reasons."""

    MISSING_COUNTERPARTY = "missing_counterparty"
    INVALID_COUNTERPARTY = "invalid_counterparty"
    MISSING_COUNTERPARTY_CLASS = "missing_counterparty_class"
    INELIGIBLE_COUNTERPARTY_CLASS = "ineligible_counterparty_class"
    INVALID_EVIDENCE_REFS = "invalid_evidence_refs"


_NEXT_ACTIONS: Final[dict[G1CounterpartyRefusalReason, str]] = {
    G1CounterpartyRefusalReason.MISSING_COUNTERPARTY: (
        "attach a counterparty record before M2 commit"
    ),
    G1CounterpartyRefusalReason.INVALID_COUNTERPARTY: (
        "repair the counterparty record before M2 commit"
    ),
    G1CounterpartyRefusalReason.MISSING_COUNTERPARTY_CLASS: (
        "record one eligible counterparty class before M2 commit"
    ),
    G1CounterpartyRefusalReason.INELIGIBLE_COUNTERPARTY_CLASS: (
        "refuse arbitrage unless the counterparty is institution, market, corporation, "
        "sophisticated_party, or the_wealthy"
    ),
    G1CounterpartyRefusalReason.INVALID_EVIDENCE_REFS: (
        "record evidence_refs as a sequence of non-empty strings"
    ),
}


@dataclass(frozen=True)
class MonDLCCounterparty:
    """Counterparty facts consumed by the G1 gate."""

    counterparty_class: MonDLCCounterpartyClass
    counterparty_id: str = ""
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.counterparty_class, MonDLCCounterpartyClass):
            object.__setattr__(
                self,
                "counterparty_class",
                _counterparty_class(self.counterparty_class),
            )
        object.__setattr__(self, "counterparty_id", _optional_string(self.counterparty_id))
        object.__setattr__(self, "evidence_refs", _string_tuple(self.evidence_refs))

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> MonDLCCounterparty:
        try:
            return cls(
                counterparty_class=_counterparty_class(raw.get("counterparty_class")),
                counterparty_id=_optional_string(raw.get("counterparty_id")),
                evidence_refs=_evidence_refs_from_mapping(raw),
            )
        except _G1InputError:
            raise
        except (TypeError, ValueError) as exc:
            raise _G1InputError(G1CounterpartyRefusalReason.INVALID_COUNTERPARTY, str(exc)) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "counterparty_class": self.counterparty_class.value,
            "counterparty_id": self.counterparty_id,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class G1CounterpartyVerification:
    """Result of verifying G1 counterparty eligibility."""

    validator: str
    validator_version: int
    status: GateStatus
    gate_result: GateResult
    reason: str
    refusal_reason: G1CounterpartyRefusalReason | None
    counterparty: MonDLCCounterparty | None = None
    counterparty_class: str | None = None
    evidence_refs: tuple[str, ...] = ()
    next_action: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, GateStatus):
            raise TypeError("G1CounterpartyVerification.status must be a GateStatus identity")
        if not isinstance(self.gate_result, GateResult):
            raise TypeError("G1CounterpartyVerification.gate_result must be a GateResult identity")
        if self.refusal_reason is not None and not isinstance(
            self.refusal_reason, G1CounterpartyRefusalReason
        ):
            raise TypeError("refusal_reason must be a G1CounterpartyRefusalReason")
        object.__setattr__(self, "evidence_refs", _string_tuple(self.evidence_refs))

    @property
    def ok(self) -> bool:
        return self.status is GateStatus.LIT

    def __bool__(self) -> bool:
        raise TypeError("G1CounterpartyVerification truthiness is undefined; inspect status")

    def to_dict(self) -> dict[str, Any]:
        return {
            "validator": self.validator,
            "validator_version": self.validator_version,
            "status": self.status.value,
            "ok": self.ok,
            "reason": self.reason,
            "refusal_reason": None if self.refusal_reason is None else self.refusal_reason.value,
            "next_action": self.next_action,
            "counterparty_class": self.counterparty_class,
            "counterparty_id": None
            if self.counterparty is None
            else self.counterparty.counterparty_id,
            "evidence_refs": list(self.evidence_refs),
            "gate_result": {
                "status": self.gate_result.status.value,
                "verdict": self.gate_result.verdict,
                "reason": self.gate_result.reason,
                "evidence_refs": list(self.gate_result.evidence_refs),
            },
        }


class ArbitrageRefusal(RuntimeError):
    """Raised when a caller requires G1 eligibility and verification blocks."""

    def __init__(self, verification: G1CounterpartyVerification) -> None:
        self.verification = verification
        super().__init__(verification.reason)


class _G1InputError(ValueError):
    def __init__(self, reason: G1CounterpartyRefusalReason, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(detail or reason.value)


def verify_g1_counterparty(
    counterparty: MonDLCCounterparty | Mapping[str, Any] | None,
) -> G1CounterpartyVerification:
    """Verify that the counterparty class admits MonDLC arbitrage."""

    if counterparty is None:
        return _refused(G1CounterpartyRefusalReason.MISSING_COUNTERPARTY)
    try:
        eligible_counterparty = _coerce_counterparty(counterparty)
    except _G1InputError as exc:
        return _refused(exc.reason, detail=exc.detail)

    evidence_refs = _counterparty_evidence_refs(eligible_counterparty)
    return G1CounterpartyVerification(
        validator=MONDLC_G1_COUNTERPARTY_NAME,
        validator_version=MONDLC_G1_COUNTERPARTY_VERSION,
        status=GateStatus.LIT,
        gate_result=GateResult(
            status=GateStatus.LIT,
            verdict=True,
            reason="counterparty_class_eligible",
            evidence_refs=evidence_refs,
        ),
        reason="counterparty_class_eligible",
        refusal_reason=None,
        counterparty=eligible_counterparty,
        counterparty_class=eligible_counterparty.counterparty_class.value,
        evidence_refs=evidence_refs,
    )


def require_g1_counterparty(
    counterparty: MonDLCCounterparty | Mapping[str, Any] | None,
) -> MonDLCCounterparty:
    """Return the eligible counterparty or raise :class:`ArbitrageRefusal`."""

    verification = verify_g1_counterparty(counterparty)
    if verification.status is not GateStatus.LIT or verification.counterparty is None:
        raise ArbitrageRefusal(verification)
    return verification.counterparty


def _coerce_counterparty(
    value: MonDLCCounterparty | Mapping[str, Any],
) -> MonDLCCounterparty:
    if isinstance(value, MonDLCCounterparty):
        return value
    if not isinstance(value, Mapping):
        raise _G1InputError(
            G1CounterpartyRefusalReason.INVALID_COUNTERPARTY,
            "counterparty must be a MonDLCCounterparty or mapping",
        )
    return MonDLCCounterparty.from_mapping(value)


def _counterparty_class(value: Any) -> MonDLCCounterpartyClass:
    if isinstance(value, MonDLCCounterpartyClass):
        return value
    if value is None:
        raise _G1InputError(
            G1CounterpartyRefusalReason.MISSING_COUNTERPARTY_CLASS,
            "counterparty_class is required",
        )
    if not isinstance(value, str) or not value.strip():
        raise _G1InputError(
            G1CounterpartyRefusalReason.MISSING_COUNTERPARTY_CLASS,
            "counterparty_class is required",
        )
    normalized = value.strip().casefold()
    try:
        return MonDLCCounterpartyClass(normalized)
    except ValueError as exc:
        raise _G1InputError(
            G1CounterpartyRefusalReason.INELIGIBLE_COUNTERPARTY_CLASS,
            f"counterparty_class {value.strip()!r} is not eligible",
        ) from exc


def _refused(
    reason: G1CounterpartyRefusalReason,
    *,
    detail: str = "",
) -> G1CounterpartyVerification:
    next_action = _NEXT_ACTIONS[reason]
    message = reason.value if not detail else f"{reason.value}: {detail}"
    message = f"{message}; next action: {next_action}"
    return G1CounterpartyVerification(
        validator=MONDLC_G1_COUNTERPARTY_NAME,
        validator_version=MONDLC_G1_COUNTERPARTY_VERSION,
        status=GateStatus.DARK,
        gate_result=GateResult(
            status=GateStatus.DARK,
            verdict=None,
            reason=message,
            evidence_refs=(),
        ),
        reason=message,
        refusal_reason=reason,
        counterparty=None,
        evidence_refs=(),
        next_action=next_action,
    )


def _counterparty_evidence_refs(counterparty: MonDLCCounterparty) -> tuple[str, ...]:
    refs = [f"counterparty-class:{counterparty.counterparty_class.value}"]
    if counterparty.counterparty_id:
        counterparty_ref = (
            counterparty.counterparty_id
            if counterparty.counterparty_id.startswith("counterparty:")
            else f"counterparty:{counterparty.counterparty_id}"
        )
        refs.append(counterparty_ref)
    refs.extend(counterparty.evidence_refs)
    return tuple(dict.fromkeys(refs))


def _optional_string(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("optional field must be a string")
    return value.strip()


def _evidence_refs_from_mapping(raw: Mapping[str, Any]) -> tuple[str, ...]:
    try:
        return _string_tuple(raw.get("evidence_refs"))
    except TypeError as exc:
        raise _G1InputError(G1CounterpartyRefusalReason.INVALID_EVIDENCE_REFS, str(exc)) from exc


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
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
    "ELIGIBLE_COUNTERPARTY_CLASSES",
    "MONDLC_G1_COUNTERPARTY_NAME",
    "MONDLC_G1_COUNTERPARTY_VERSION",
    "ArbitrageRefusal",
    "G1CounterpartyRefusalReason",
    "G1CounterpartyVerification",
    "MonDLCCounterparty",
    "MonDLCCounterpartyClass",
    "require_g1_counterparty",
    "verify_g1_counterparty",
]
