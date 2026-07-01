"""Phase-0 API packaging harness for NDCVB detection results.

This module is intentionally schema-level only: it wraps already-produced
NDCVB verdict-shaped outputs into a JSON-ready response envelope without
creating a runtime endpoint, customer-data intake path, provider call, or public
offer surface.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from shared.segment_ndcvb_axis_b import AxisBNDCVBError, evaluate_ndcvb_axis_b

NDCVB_API_HARNESS_VERSION: Final = 1
NDCVB_API_SCHEMA: Final = "hapax.ndcvb.phase0_detection_result.v1"
NDCVB_PRODUCT_SURFACE_ID: Final = "ndcvb-b2b-api-phase0-harness"
NDCVB_PHASE: Final = "phase0_packaging_only"
NDCVB_REQUIRED_BATTERY_GATE_COUNT: Final = 4
_DEFAULT_PURPOSE: Final = "operator_internal_phase0_packaging"
_REQUIRED_GATE_IDS: Final[frozenset[str]] = frozenset(
    {
        "stimulus_capture",
        "counterfactual_probe",
        "cross_context_consistency",
        "source_traceability",
    }
)
_REQUEST_ID_RE: Final = re.compile(r"^ndcvb-api-req-[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REFERENCE_RE: Final = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")

_REQUEST_KEYS: Final = frozenset(
    {
        "request_id",
        "artifact_ref",
        "evidence_ref",
        "run_ref",
        "purpose",
    }
)
_VERDICT_KEYS: Final = frozenset(
    {
        "bound",
        "correspondent",
        "kind",
        "rationale",
        "rendered",
        "source",
        "verdict",
    }
)
_BATTERY_GATE_KEYS: Final = frozenset(
    {
        "confidence",
        "detail",
        "gate_id",
        "passed",
        "provenance",
    }
)
_FORBIDDEN_REQUEST_KEYS: Final = frozenset(
    {
        "client",
        "client_id",
        "content",
        "customer",
        "customer_data",
        "customer_id",
        "document",
        "email",
        "input",
        "input_text",
        "payload",
        "prompt",
        "raw",
        "raw_payload",
        "raw_text",
        "tenant",
        "tenant_id",
        "user",
        "user_id",
    }
)
_REQUEST_NEXT_ACTION: Final = (
    "next_action=send only operator-generated request_id matching ndcvb-api-req-*, "
    "artifact_ref, evidence_ref, optional run_ref, "
    f"and optional purpose exactly {_DEFAULT_PURPOSE!r}; do not pass raw payload, "
    "customer, tenant, or user data"
)
_VERDICT_NEXT_ACTION: Final = (
    "next_action=send only NDCVB verdict-shaped fields: correspondent, kind, bound, "
    "rationale, source, rendered, or verdict; do not pass raw payload, customer, "
    "tenant, or user data"
)
_BATTERY_NEXT_ACTION: Final = (
    "next_action=provide exactly four canonical gate mappings "
    "(stimulus_capture, counterfactual_probe, cross_context_consistency, "
    "source_traceability) with boolean passed, confidence in [0.0, 1.0], non-empty "
    "provenance refs, and optional local-only detail that is not returned by the "
    "public envelope; do not pass raw payload, customer, tenant, or user data"
)
_TEXT_NEXT_ACTION: Final = "next_action=provide a non-empty string reference value"
_REF_NEXT_ACTION: Final = (
    "next_action=provide a URI-like reference such as vault:..., ndcvb:..., or local:..."
)


class NDCVBApiStatus(StrEnum):
    """Machine-readable disposition for the packaged detection result."""

    CLEAR = "clear"
    HOLD = "hold"
    REFUSED_NO_RELEASE = "refused_no_release"


class NDCVBApiHarnessError(ValueError):
    """Invalid phase-0 NDCVB API packaging input."""


@dataclass(frozen=True)
class NDCVBPackagingRequest:
    """Reference-only request descriptor for the phase-0 harness.

    The harness carries refs to already-local artifacts and evidence. It does
    not accept raw prompt, completion, customer, tenant, or document payloads.
    """

    request_id: str
    artifact_ref: str
    evidence_ref: str
    run_ref: str | None = None
    purpose: str = _DEFAULT_PURPOSE

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _request_id(self.request_id))
        object.__setattr__(
            self,
            "artifact_ref",
            _required_reference(self.artifact_ref, "artifact_ref"),
        )
        object.__setattr__(
            self,
            "evidence_ref",
            _required_reference(self.evidence_ref, "evidence_ref"),
        )
        object.__setattr__(self, "run_ref", _optional_reference(self.run_ref, "run_ref"))
        object.__setattr__(
            self,
            "purpose",
            _purpose(self.purpose),
        )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> NDCVBPackagingRequest:
        """Build a strict request descriptor from API-like input."""

        _validate_mapping_keys(
            raw,
            allowed_keys=_REQUEST_KEYS,
            next_action=_REQUEST_NEXT_ACTION,
            label="phase-0 harness request",
        )
        return cls(
            request_id=_request_id(raw.get("request_id")),
            artifact_ref=_required_text(raw.get("artifact_ref"), "artifact_ref"),
            evidence_ref=_required_text(raw.get("evidence_ref"), "evidence_ref"),
            run_ref=_optional_text(raw.get("run_ref"), "run_ref"),
            purpose=_purpose(raw.get("purpose")),
        )

    def to_api(self) -> dict[str, Any]:
        """Return the public schema fragment for this reference-only request."""

        return {
            "request_id": self.request_id,
            "artifact_ref": self.artifact_ref,
            "evidence_ref": self.evidence_ref,
            "run_ref": self.run_ref,
            "purpose": self.purpose,
            "raw_payload_persisted": False,
            "customer_data_path_enabled": False,
        }


@dataclass(frozen=True)
class NDCVBBatteryGate:
    """One gate receipt from the external four-gate dissociation battery."""

    gate_id: str
    passed: bool
    confidence: float
    provenance: tuple[str, ...]
    detail: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "gate_id", _gate_id(self.gate_id))
        if not isinstance(self.passed, bool):
            raise NDCVBApiHarnessError(
                _with_next_action("battery gate passed must be a boolean", _BATTERY_NEXT_ACTION)
            )
        object.__setattr__(
            self,
            "confidence",
            _unit_float(self.confidence, field="confidence"),
        )
        object.__setattr__(
            self,
            "provenance",
            _provenance_tuple(self.provenance, field="provenance"),
        )
        object.__setattr__(self, "detail", _optional_detail(self.detail, "detail"))

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> NDCVBBatteryGate:
        """Build one battery-gate receipt from API-like input."""

        _validate_mapping_keys(
            raw,
            allowed_keys=_BATTERY_GATE_KEYS,
            next_action=_BATTERY_NEXT_ACTION,
            label="battery gate",
        )
        gate_id = _gate_id(raw.get("gate_id"))
        passed = raw.get("passed")
        if not isinstance(passed, bool):
            raise NDCVBApiHarnessError(
                _with_next_action("battery gate passed must be a boolean", _BATTERY_NEXT_ACTION)
            )
        confidence = _unit_float(raw.get("confidence"), field="confidence")
        provenance = _provenance_tuple(raw.get("provenance"), field="provenance")
        detail = _optional_detail(raw.get("detail"), "detail")
        return cls(
            gate_id=gate_id,
            passed=passed,
            confidence=confidence,
            provenance=provenance,
            detail=detail,
        )

    def to_api(self) -> dict[str, Any]:
        """Return this gate as a JSON-serializable schema fragment."""

        return {
            "gate_id": self.gate_id,
            "passed": self.passed,
            "confidence": round(self.confidence, 3),
            "provenance": list(self.provenance),
        }


def package_ndcvb_detection_result(
    *,
    request: NDCVBPackagingRequest | Mapping[str, Any],
    verdicts: Sequence[Mapping[str, Any] | str],
    battery_gates: Sequence[NDCVBBatteryGate | Mapping[str, Any]],
) -> dict[str, Any]:
    """Package NDCVB detection output for the bounded phase-0 API surface.

    ``verdicts`` are still validated by ``evaluate_ndcvb_axis_b()``, so the
    forbidden-verdict language guard and dissociation veto remain the engine's
    own behavior rather than a duplicate policy in this harness.
    """

    request_record = _coerce_request(request)
    _validate_verdict_inputs(verdicts)
    gate_records = _coerce_battery_gates(battery_gates)
    try:
        engine_report = evaluate_ndcvb_axis_b(verdicts)
    except AxisBNDCVBError as exc:
        raise NDCVBApiHarnessError(
            _with_next_action(
                "NDCVB verdict validation failed; Axis-B guard refused the verdict input",
                _VERDICT_NEXT_ACTION,
            )
        ) from exc
    battery_report = _battery_report(gate_records)
    status = _status_for(engine_report=engine_report, battery_ok=battery_report["ok"])
    result_confidence = _result_confidence(engine_report)
    provenance = _overall_provenance(
        request_record=request_record,
        engine_report=engine_report,
        battery_gates=gate_records,
    )

    return {
        "schema": NDCVB_API_SCHEMA,
        "harness_version": NDCVB_API_HARNESS_VERSION,
        "surface": {
            "surface_id": NDCVB_PRODUCT_SURFACE_ID,
            "phase": NDCVB_PHASE,
            "api_transport_enabled": False,
            "public_offer_enabled": False,
            "customer_data_path_enabled": False,
            "provider_spend_enabled": False,
            "runtime_endpoint_enabled": False,
        },
        "request": request_record.to_api(),
        "status": status.value,
        "detection": {
            "kind": engine_report["kind"],
            "verdict": engine_report["verdict"],
            "ok": engine_report["ok"] is True,
            "confidence": result_confidence,
            "confidence_basis": _confidence_basis(engine_report),
            "provenance": provenance,
            "violations": _public_violations(engine_report.get("violations", [])),
        },
        "battery": battery_report,
        "engine_guards": {
            "engine": engine_report["scorer"],
            "engine_version": engine_report["scorer_version"],
            "forbidden_verdict_language_enforced": True,
            "dissociated_veto_required": engine_report["dissociated_veto_required"] is True,
            "floor_gate": dict(engine_report["floor_gate"]),
            "release_boundary": "closed"
            if engine_report["dissociated_veto_required"] is True
            else "phase0_schema_only",
        },
    }


def _coerce_request(
    request: NDCVBPackagingRequest | Mapping[str, Any],
) -> NDCVBPackagingRequest:
    if isinstance(request, NDCVBPackagingRequest):
        return request
    if not isinstance(request, Mapping):
        raise NDCVBApiHarnessError(
            _with_next_action(
                "request must be a mapping or NDCVBPackagingRequest",
                _REQUEST_NEXT_ACTION,
            )
        )
    return NDCVBPackagingRequest.from_mapping(request)


def _validate_verdict_inputs(verdicts: Sequence[Mapping[str, Any] | str]) -> None:
    if isinstance(verdicts, (str, bytes)) or not isinstance(verdicts, Sequence):
        raise NDCVBApiHarnessError(
            _with_next_action("verdicts must be a sequence", _VERDICT_NEXT_ACTION)
        )
    for verdict in verdicts:
        if isinstance(verdict, str):
            continue
        if not isinstance(verdict, Mapping):
            raise NDCVBApiHarnessError(
                _with_next_action(
                    "verdict must be a mapping or rendered verdict string",
                    _VERDICT_NEXT_ACTION,
                )
            )
        _validate_mapping_keys(
            verdict,
            allowed_keys=_VERDICT_KEYS,
            next_action=_VERDICT_NEXT_ACTION,
            label="NDCVB verdict",
        )
        _optional_reference(verdict.get("source"), "source")


def _validate_mapping_keys(
    raw: Mapping[object, Any],
    *,
    allowed_keys: frozenset[str],
    next_action: str,
    label: str,
) -> None:
    raw_keys = set(raw)
    non_string_keys = [key for key in raw_keys if not isinstance(key, str)]
    if non_string_keys:
        raise NDCVBApiHarnessError(_with_next_action(f"{label} keys must be strings", next_action))
    string_keys = {key for key in raw_keys if isinstance(key, str)}
    forbidden = sorted(string_keys & _FORBIDDEN_REQUEST_KEYS)
    if forbidden:
        if label == "phase-0 harness request":
            message = f"phase-0 harness accepts refs only; forbidden request keys (count={len(forbidden)})"
        else:
            message = (
                f"{label} accepts declared fields only; forbidden keys (count={len(forbidden)})"
            )
        raise NDCVBApiHarnessError(_with_next_action(message, next_action))
    unknown = sorted(string_keys - allowed_keys)
    if unknown:
        raise NDCVBApiHarnessError(
            _with_next_action(
                f"{label} has unsupported keys (count={len(unknown)})",
                next_action,
            )
        )


def _coerce_battery_gates(
    battery_gates: Sequence[NDCVBBatteryGate | Mapping[str, Any]],
) -> tuple[NDCVBBatteryGate, ...]:
    if isinstance(battery_gates, (str, bytes)) or not isinstance(battery_gates, Sequence):
        raise NDCVBApiHarnessError(
            _with_next_action("battery_gates must be a sequence", _BATTERY_NEXT_ACTION)
        )
    gates = tuple(
        gate if isinstance(gate, NDCVBBatteryGate) else _coerce_battery_gate(gate)
        for gate in battery_gates
    )
    if len(gates) != NDCVB_REQUIRED_BATTERY_GATE_COUNT:
        raise NDCVBApiHarnessError(
            _with_next_action(
                "phase-0 NDCVB packaging requires exactly "
                f"{NDCVB_REQUIRED_BATTERY_GATE_COUNT} battery gates",
                _BATTERY_NEXT_ACTION,
            )
        )
    gate_ids = [gate.gate_id for gate in gates]
    duplicate_ids = sorted({gate_id for gate_id in gate_ids if gate_ids.count(gate_id) > 1})
    if duplicate_ids:
        raise NDCVBApiHarnessError(
            _with_next_action(
                "battery gate ids must be unique: " + ", ".join(duplicate_ids),
                _BATTERY_NEXT_ACTION,
            )
        )
    return gates


def _coerce_battery_gate(gate: object) -> NDCVBBatteryGate:
    if not isinstance(gate, Mapping):
        raise NDCVBApiHarnessError(
            _with_next_action(
                "battery gate must be a mapping or NDCVBBatteryGate",
                _BATTERY_NEXT_ACTION,
            )
        )
    return NDCVBBatteryGate.from_mapping(gate)


def _battery_report(gates: Sequence[NDCVBBatteryGate]) -> dict[str, Any]:
    passed = [gate for gate in gates if gate.passed]
    failed = [gate for gate in gates if not gate.passed]
    min_confidence = min(gate.confidence for gate in gates)
    return {
        "battery_id": "ndcvb_four_gate_dissociation_battery",
        "required_gate_count": NDCVB_REQUIRED_BATTERY_GATE_COUNT,
        "observed_gate_count": len(gates),
        "passed_gate_count": len(passed),
        "failed_gate_ids": [gate.gate_id for gate in failed],
        "ok": not failed,
        "min_confidence": round(min_confidence, 3),
        "gates": [gate.to_api() for gate in gates],
    }


def _status_for(*, engine_report: Mapping[str, Any], battery_ok: bool) -> NDCVBApiStatus:
    if engine_report.get("dissociated_veto_required") is True:
        return NDCVBApiStatus.REFUSED_NO_RELEASE
    if not battery_ok or engine_report.get("ok") is not True:
        return NDCVBApiStatus.HOLD
    return NDCVBApiStatus.CLEAR


def _result_confidence(engine_report: Mapping[str, Any]) -> float | None:
    sensitivity_bound = engine_report.get("sensitivity_bound")
    if isinstance(sensitivity_bound, (int, float)) and not isinstance(sensitivity_bound, bool):
        return round(float(sensitivity_bound), 3)
    score_0_100 = engine_report.get("score_0_100")
    if isinstance(score_0_100, (int, float)) and not isinstance(score_0_100, bool):
        return round(float(score_0_100) / 100.0, 3)
    return None


def _confidence_basis(engine_report: Mapping[str, Any]) -> str:
    if engine_report.get("sensitivity_bound") is not None:
        return "ndcvb_sensitivity_bound"
    if engine_report.get("score_0_100") is not None:
        return "ndcvb_score_0_100"
    return "unavailable_below_floor"


def _public_violations(raw_violations: object) -> list[dict[str, Any]]:
    if isinstance(raw_violations, (str, bytes)) or not isinstance(raw_violations, Sequence):
        return []
    public: list[dict[str, Any]] = []
    for violation in raw_violations:
        if not isinstance(violation, Mapping):
            continue
        item: dict[str, Any] = {}
        reason = violation.get("reason")
        if isinstance(reason, str) and reason.strip():
            item["reason"] = reason.strip()
        bound = violation.get("bound")
        if isinstance(bound, (int, float)) and not isinstance(bound, bool) and math.isfinite(bound):
            item["bound"] = round(float(bound), 3)
        correspondents = violation.get("correspondents")
        if isinstance(correspondents, Sequence) and not isinstance(correspondents, (str, bytes)):
            item["correspondent_count"] = len(correspondents)
        if item:
            public.append(item)
    return public


def _overall_provenance(
    *,
    request_record: NDCVBPackagingRequest,
    engine_report: Mapping[str, Any],
    battery_gates: Sequence[NDCVBBatteryGate],
) -> list[str]:
    refs: list[str] = [
        request_record.artifact_ref,
        request_record.evidence_ref,
    ]
    if request_record.run_ref:
        refs.append(request_record.run_ref)
    for correspondent in engine_report.get("correspondent_scores", []):
        if isinstance(correspondent, Mapping):
            source = correspondent.get("source")
            if isinstance(source, str) and source.strip():
                refs.append(source.strip())
    for gate in battery_gates:
        refs.extend(gate.provenance)
    return list(dict.fromkeys(refs))


def _required_text(value: Any, field: str) -> str:
    text = _optional_text(value, field)
    if text is None:
        raise NDCVBApiHarnessError(_with_next_action(f"{field} is required", _TEXT_NEXT_ACTION))
    return text


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise NDCVBApiHarnessError(
            _with_next_action(f"{field} must be a string", _TEXT_NEXT_ACTION)
        )
    text = value.strip()
    if not text:
        raise NDCVBApiHarnessError(
            _with_next_action(f"{field} must not be empty", _TEXT_NEXT_ACTION)
        )
    return text


def _request_id(value: Any) -> str:
    text = _required_text(value, "request_id")
    if not _REQUEST_ID_RE.match(text):
        raise NDCVBApiHarnessError(
            _with_next_action(
                "request_id must be an operator-generated ndcvb-api-req-* identifier",
                _REQUEST_NEXT_ACTION,
            )
        )
    return text


def _gate_id(value: Any) -> str:
    text = _required_text(value, "gate_id")
    if text not in _REQUIRED_GATE_IDS:
        raise NDCVBApiHarnessError(
            _with_next_action(
                "battery gate_id must be one of the canonical four-gate identifiers",
                _BATTERY_NEXT_ACTION,
            )
        )
    return text


def _required_reference(value: Any, field: str) -> str:
    text = _required_text(value, field)
    _assert_reference(text, field)
    return text


def _optional_reference(value: Any, field: str) -> str | None:
    text = _optional_text(value, field)
    if text is None:
        return None
    _assert_reference(text, field)
    return text


def _purpose(value: Any) -> str:
    text = _optional_text(value, "purpose")
    if text is None:
        return _DEFAULT_PURPOSE
    if text != _DEFAULT_PURPOSE:
        raise NDCVBApiHarnessError(
            _with_next_action(
                f"purpose must be omitted or exactly {_DEFAULT_PURPOSE!r}",
                _REQUEST_NEXT_ACTION,
            )
        )
    return text


def _assert_reference(text: str, field: str) -> None:
    if not _REFERENCE_RE.match(text):
        raise NDCVBApiHarnessError(
            _with_next_action(f"{field} must be a URI-like reference", _REF_NEXT_ACTION)
        )


def _optional_detail(value: Any, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise NDCVBApiHarnessError(
            _with_next_action(f"{field} must be a string", _TEXT_NEXT_ACTION)
        )
    return value.strip()


def _unit_float(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NDCVBApiHarnessError(
            _with_next_action(
                f"{field} must be a number in [0.0, 1.0]",
                _BATTERY_NEXT_ACTION,
            )
        )
    number = float(value)
    if not math.isfinite(number) or number < 0.0 or number > 1.0:
        raise NDCVBApiHarnessError(
            _with_next_action(
                f"{field} must be a number in [0.0, 1.0]",
                _BATTERY_NEXT_ACTION,
            )
        )
    return number


def _provenance_tuple(value: Any, *, field: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise NDCVBApiHarnessError(
            _with_next_action(
                f"{field} must be a non-empty string sequence",
                _BATTERY_NEXT_ACTION,
            )
        )
    items = tuple(_required_reference(item, field) for item in value)
    if not items:
        raise NDCVBApiHarnessError(
            _with_next_action(
                f"{field} must be a non-empty string sequence",
                _BATTERY_NEXT_ACTION,
            )
        )
    return items


def _with_next_action(message: str, next_action: str) -> str:
    return f"{message}; {next_action}"


__all__ = [
    "NDCVB_API_HARNESS_VERSION",
    "NDCVB_API_SCHEMA",
    "NDCVB_PHASE",
    "NDCVB_PRODUCT_SURFACE_ID",
    "NDCVB_REQUIRED_BATTERY_GATE_COUNT",
    "NDCVBApiHarnessError",
    "NDCVBApiStatus",
    "NDCVBBatteryGate",
    "NDCVBPackagingRequest",
    "package_ndcvb_detection_result",
]
