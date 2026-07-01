"""MonDLC M-instrument binding.

This is the INV-7 boundary: consumers bind to the scorer and rail-reader
contracts here instead of reimplementing measurement logic locally. The scorer
and rail reader are loaded lazily so importing this module does not require
optional payment-rail surfaces.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from shared.capdlc_lifecycle import GateResult, GateStatus

MONDLC_M_BINDING_NAME: Final = "mdlc_m_binding"
MONDLC_M_BINDING_VERSION: Final = 1
_CORROBORATED_VERDICT: Final = "corroborated"
_ACCEPTED_RAIL_STATUS: Final = "accepted"


class MonDLCBindingRefusalReason(StrEnum):
    """Machine-readable fail-closed binding refusal reasons."""

    MISSING_SCORER = "missing_scorer"
    MISSING_RAIL_READER = "missing_rail_reader"
    MISSING_RAIL_EVIDENCE = "missing_rail_evidence"
    MISSING_LADDER = "missing_ladder"
    RAIL_REFUSED = "rail_refused"
    UNSUPPORTED_SHAPE = "unsupported_shape"


_NEXT_ACTIONS: Final[dict[MonDLCBindingRefusalReason, str]] = {
    MonDLCBindingRefusalReason.MISSING_SCORER: (
        "install or restore shared.mdlc_measure before scoring MonDLC evidence"
    ),
    MonDLCBindingRefusalReason.MISSING_RAIL_READER: (
        "install or restore shared.mdlc_realized_return before reading durable payment events"
    ),
    MonDLCBindingRefusalReason.MISSING_RAIL_EVIDENCE: (
        "attach accepted realized inbound rail evidence with durable refs before binding"
    ),
    MonDLCBindingRefusalReason.MISSING_LADDER: (
        "supply the frozen MonDLC ruler ladder before binding measurement evidence"
    ),
    MonDLCBindingRefusalReason.RAIL_REFUSED: (
        "preserve the native rail refusal reason and do not score the refused event"
    ),
    MonDLCBindingRefusalReason.UNSUPPORTED_SHAPE: (
        "pass a native MonDLCScoreResult, rail result sequence, measurement mapping, "
        "or durable payment-event path"
    ),
}


@dataclass(frozen=True)
class MonDLCBindingResult:
    """Canonical binding result for M-instrument consumers."""

    binding: str
    binding_version: int
    status: GateStatus
    verdict: str
    gate_result: GateResult
    reason: str
    refusal_reason: MonDLCBindingRefusalReason | None
    evidence_refs: tuple[str, ...] = ()
    native_verdict: Any | None = None
    score_result: Any | None = None
    rail_results: tuple[Any, ...] = ()
    native_refusal_reason: str | None = None
    source_kind: str = ""
    scorer: str | None = None
    scorer_version: int | None = None
    next_action: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, GateStatus):
            raise TypeError("MonDLCBindingResult.status must be a GateStatus identity")
        if not isinstance(self.gate_result, GateResult):
            raise TypeError("MonDLCBindingResult.gate_result must be a GateResult identity")
        object.__setattr__(self, "evidence_refs", _string_tuple(self.evidence_refs))
        object.__setattr__(self, "rail_results", tuple(self.rail_results))

    @property
    def ok(self) -> bool:
        return self.status is GateStatus.LIT and self.verdict == _CORROBORATED_VERDICT

    def __bool__(self) -> bool:
        raise TypeError("MonDLCBindingResult truthiness is undefined; inspect status and verdict")

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding": self.binding,
            "binding_version": self.binding_version,
            "status": self.status.value,
            "verdict": self.verdict,
            "ok": self.ok,
            "reason": self.reason,
            "refusal_reason": None if self.refusal_reason is None else self.refusal_reason.value,
            "native_refusal_reason": self.native_refusal_reason,
            "next_action": self.next_action,
            "evidence_refs": list(self.evidence_refs),
            "source_kind": self.source_kind,
            "scorer": self.scorer,
            "scorer_version": self.scorer_version,
            "gate_result": {
                "status": self.gate_result.status.value,
                "verdict": self.gate_result.verdict,
                "reason": self.gate_result.reason,
                "evidence_refs": list(self.gate_result.evidence_refs),
            },
        }


def bind_m_result(
    source: Any,
    ladder: Any | None = None,
    *,
    ruler_hash_commit: str | None = None,
) -> MonDLCBindingResult:
    """Bind native MonDLC evidence/results through the canonical M boundary.

    Native score results are lifted directly. Rail results and measurement-like
    inputs are scored only by calling ``shared.mdlc_measure.score`` through the
    lazy scorer import path.
    """

    if _is_score_result(source):
        return _lift_score_result(source)
    if _is_rail_result(source):
        return _score_rail_results((source,), ladder, ruler_hash_commit=ruler_hash_commit)
    if _is_result_sequence(source):
        return _score_rail_results(tuple(source), ladder, ruler_hash_commit=ruler_hash_commit)
    return _score_measurement(source, ladder, ruler_hash_commit=ruler_hash_commit)


def bind_durable_payment_events(
    path: Path | str,
    ladder: Any,
    *,
    ruler_hash_commit: str,
) -> MonDLCBindingResult:
    """Read a durable payment-event stream and bind accepted rail results."""

    try:
        rail_module = _load_rail_module()
        rail_results = rail_module.realized_returns_from_durable_payment_events(path)
    except (AttributeError, ImportError, ModuleNotFoundError, OSError, ValueError) as exc:
        return _dark_result(
            reason="missing_or_invalid_rail_reader",
            refusal_reason=MonDLCBindingRefusalReason.MISSING_RAIL_READER,
            source_kind="durable_payment_events",
            detail=str(exc),
        )
    return _score_rail_results(
        tuple(rail_results),
        ladder,
        ruler_hash_commit=ruler_hash_commit,
        source_kind="durable_payment_events",
    )


def _lift_score_result(
    score_result: Any,
    *,
    source_kind: str = "score_result",
) -> MonDLCBindingResult:
    status = score_result.status
    gate_result = score_result.gate_result
    verdict = score_result.verdict
    reason = str(getattr(score_result, "reason", "") or "")
    refusal = str(getattr(score_result, "refusal_reason", "") or "") or None
    evidence_refs = _string_tuple(getattr(score_result, "evidence_refs", ()))
    return MonDLCBindingResult(
        binding=MONDLC_M_BINDING_NAME,
        binding_version=MONDLC_M_BINDING_VERSION,
        status=status,
        verdict=_value(verdict),
        gate_result=gate_result,
        reason=reason,
        refusal_reason=None,
        evidence_refs=evidence_refs,
        native_verdict=verdict,
        score_result=score_result,
        native_refusal_reason=refusal,
        source_kind=source_kind,
        scorer=str(getattr(score_result, "scorer", "") or "") or None,
        scorer_version=getattr(score_result, "scorer_version", None),
    )


def _score_rail_results(
    rail_results: tuple[Any, ...],
    ladder: Any | None,
    *,
    ruler_hash_commit: str | None,
    source_kind: str = "rail_result",
) -> MonDLCBindingResult:
    if ladder is None:
        return _dark_result(
            reason="missing_ladder",
            refusal_reason=MonDLCBindingRefusalReason.MISSING_LADDER,
            source_kind=source_kind,
            rail_results=rail_results,
        )
    if not rail_results:
        return _dark_result(
            reason="missing_rail_evidence",
            refusal_reason=MonDLCBindingRefusalReason.MISSING_RAIL_EVIDENCE,
            source_kind=source_kind,
            rail_results=rail_results,
        )

    accepted = tuple(
        result for result in rail_results if _rail_status(result) == _ACCEPTED_RAIL_STATUS
    )
    if not accepted:
        native_reason = _first_native_refusal_reason(rail_results)
        return _dark_result(
            reason="rail_refused",
            refusal_reason=MonDLCBindingRefusalReason.RAIL_REFUSED,
            source_kind=source_kind,
            rail_results=rail_results,
            native_refusal_reason=native_reason,
        )

    measurement = _measurement_from_rail_results(accepted)
    if measurement is None:
        return _dark_result(
            reason="missing_rail_evidence",
            refusal_reason=MonDLCBindingRefusalReason.MISSING_RAIL_EVIDENCE,
            source_kind=source_kind,
            rail_results=rail_results,
        )
    scored = _score_measurement(
        measurement,
        ladder,
        ruler_hash_commit=ruler_hash_commit,
        source_kind=source_kind,
    )
    return _with_rail_results(scored, rail_results)


def _score_measurement(
    measurement: Any,
    ladder: Any | None,
    *,
    ruler_hash_commit: str | None,
    source_kind: str = "measurement",
) -> MonDLCBindingResult:
    if ladder is None:
        return _dark_result(
            reason="missing_ladder",
            refusal_reason=MonDLCBindingRefusalReason.MISSING_LADDER,
            source_kind=source_kind,
        )
    try:
        measure_module = _load_measure_module()
        score = measure_module.score
    except (AttributeError, ImportError, ModuleNotFoundError) as exc:
        return _dark_result(
            reason="missing_scorer",
            refusal_reason=MonDLCBindingRefusalReason.MISSING_SCORER,
            source_kind=source_kind,
            detail=str(exc),
        )
    try:
        score_result = score(measurement, ladder, ruler_hash_commit=ruler_hash_commit or "")
    except (TypeError, ValueError) as exc:
        return _dark_result(
            reason="unsupported_shape",
            refusal_reason=MonDLCBindingRefusalReason.UNSUPPORTED_SHAPE,
            source_kind=source_kind,
            detail=str(exc),
        )
    return _lift_score_result(score_result, source_kind=source_kind)


def _measurement_from_rail_results(rail_results: tuple[Any, ...]) -> Mapping[str, Any] | None:
    values: list[float] = []
    observed_values: list[Any] = []
    evidence_refs: list[str] = []
    for result in rail_results:
        measurement = getattr(result, "measurement", None)
        if measurement is None:
            continue
        value = getattr(measurement, "value", None)
        if value is None:
            continue
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
        observed_at = getattr(measurement, "observed_at", None)
        if observed_at is not None:
            observed_values.append(observed_at)
        evidence_refs.extend(_string_tuple(getattr(measurement, "evidence_refs", ())))
        evidence_refs.extend(_string_tuple(getattr(measurement, "corroborated_by", ())))
        evidence_refs.extend(_string_tuple(getattr(result, "evidence_refs", ())))

    refs = tuple(dict.fromkeys(evidence_refs))
    if not values or not observed_values or not refs:
        return None
    return {
        "measurement": sum(values),
        "provenance": "inbound_rail",
        "observed_at": max(observed_values),
        "evidence_refs": refs,
    }


def _dark_result(
    *,
    reason: str,
    refusal_reason: MonDLCBindingRefusalReason,
    source_kind: str,
    detail: str | None = None,
    rail_results: tuple[Any, ...] = (),
    native_refusal_reason: str | None = None,
) -> MonDLCBindingResult:
    next_action = _NEXT_ACTIONS[refusal_reason]
    message = reason if not detail else f"{reason}: {detail}"
    message = f"{message}; next action: {next_action}"
    return MonDLCBindingResult(
        binding=MONDLC_M_BINDING_NAME,
        binding_version=MONDLC_M_BINDING_VERSION,
        status=GateStatus.DARK,
        verdict="dark",
        gate_result=GateResult(
            status=GateStatus.DARK,
            verdict=None,
            reason=message,
            evidence_refs=(),
        ),
        reason=message,
        refusal_reason=refusal_reason,
        source_kind=source_kind,
        rail_results=rail_results,
        native_refusal_reason=native_refusal_reason,
        next_action=next_action,
    )


def _with_rail_results(
    result: MonDLCBindingResult,
    rail_results: tuple[Any, ...],
) -> MonDLCBindingResult:
    return MonDLCBindingResult(
        binding=result.binding,
        binding_version=result.binding_version,
        status=result.status,
        verdict=result.verdict,
        gate_result=result.gate_result,
        reason=result.reason,
        refusal_reason=result.refusal_reason,
        evidence_refs=result.evidence_refs,
        native_verdict=result.native_verdict,
        score_result=result.score_result,
        rail_results=rail_results,
        native_refusal_reason=result.native_refusal_reason,
        source_kind=result.source_kind,
        scorer=result.scorer,
        scorer_version=result.scorer_version,
        next_action=result.next_action,
    )


def _is_score_result(value: Any) -> bool:
    return all(hasattr(value, attr) for attr in ("status", "verdict", "gate_result")) and bool(
        getattr(value, "scorer", "") == "mdlc_measure"
    )


def _is_rail_result(value: Any) -> bool:
    return all(
        hasattr(value, attr)
        for attr in ("status", "measurement", "refusal_reason", "evidence_refs")
    )


def _is_result_sequence(value: Any) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and not isinstance(value, Mapping)
        and all(_is_rail_result(item) for item in value)
    )


def _rail_status(result: Any) -> str:
    return _value(getattr(result, "status", "")).casefold()


def _first_native_refusal_reason(rail_results: tuple[Any, ...]) -> str | None:
    for result in rail_results:
        reason = _value(getattr(result, "refusal_reason", ""))
        if reason:
            return reason
    return None


def _value(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if not isinstance(value, Sequence):
        return ()
    refs: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            refs.append(item.strip())
    return tuple(refs)


def _load_measure_module() -> ModuleType:
    return import_module("shared.mdlc_measure")


def _load_rail_module() -> ModuleType:
    return import_module("shared.mdlc_realized_return")


__all__ = [
    "MONDLC_M_BINDING_NAME",
    "MONDLC_M_BINDING_VERSION",
    "MonDLCBindingRefusalReason",
    "MonDLCBindingResult",
    "bind_durable_payment_events",
    "bind_m_result",
]
