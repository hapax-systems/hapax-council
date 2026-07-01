"""MonDLC measurement scorer.

The scorer is intentionally standalone: it consumes a frozen ruler ladder and
one measured return-shaped value, then emits an honest-dark result without
importing optional payment-rail or NDCVB surfaces.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from shared.capdlc_lifecycle import GateResult, GateStatus

MDLC_MEASURE_SCORER_NAME = "mdlc_measure"
MDLC_MEASURE_SCORER_VERSION = 1


class MonDLCVerdict(StrEnum):
    """Native MonDLC verdicts."""

    CORROBORATED = "corroborated"
    UNDETERMINED = "undetermined"
    NEGATIVE = "negative"
    DARK = "dark"


class MonDLCGateName(StrEnum):
    """The explicit four-gate measurement structure."""

    RULER_HASH = "ruler_hash"
    OBSERVED_EVIDENCE = "observed_evidence"
    FRESHNESS = "freshness"
    CORROBORATION = "corroboration"


@dataclass(frozen=True)
class MonDLCGate:
    name: MonDLCGateName
    status: GateStatus
    reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, MonDLCGateName):
            raise TypeError("MonDLCGate.name must be a MonDLCGateName identity")
        if not isinstance(self.status, GateStatus):
            raise TypeError("MonDLCGate.status must be a GateStatus identity")


@dataclass(frozen=True)
class MonDLCLadder:
    """Frozen ruler ladder inputs consumed by :func:`score`."""

    ruler_hash: str
    min_corroboration_count: int = 2
    freshness_ttl_seconds: int = 86_400
    as_of: datetime | None = None
    positive_threshold: float = 0.0
    negative_threshold: float = -1.0

    def __post_init__(self) -> None:
        if not self.ruler_hash.strip():
            raise ValueError("MonDLCLadder.ruler_hash is required")
        if self.min_corroboration_count < 1:
            raise ValueError("min_corroboration_count must be >= 1")
        if self.freshness_ttl_seconds < 0:
            raise ValueError("freshness_ttl_seconds must be >= 0")
        if self.negative_threshold > self.positive_threshold:
            raise ValueError("negative_threshold must be <= positive_threshold")
        if self.as_of is not None:
            object.__setattr__(self, "as_of", _ensure_utc(self.as_of))


@dataclass(frozen=True)
class MonDLCMeasurement:
    """One realized return-shaped measurement."""

    value: float | None
    provenance: str = ""
    observed_at: datetime | None = None
    evidence_refs: tuple[str, ...] = ()
    corroborated_by: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.value is not None and isinstance(self.value, bool):
            raise TypeError("MonDLCMeasurement.value must be numeric or None")
        if self.value is not None and not isinstance(self.value, (int, float)):
            raise TypeError("MonDLCMeasurement.value must be numeric or None")
        object.__setattr__(
            self,
            "value",
            None if self.value is None else float(self.value),
        )
        if self.observed_at is not None:
            object.__setattr__(self, "observed_at", _ensure_utc(self.observed_at))
        object.__setattr__(self, "evidence_refs", _string_tuple(self.evidence_refs))
        object.__setattr__(self, "corroborated_by", _string_tuple(self.corroborated_by))


@dataclass(frozen=True)
class MonDLCScoreResult:
    """Guarded scorer output.

    ``bool(result)`` is deliberately undefined so callers cannot accidentally
    collapse the ``(GateStatus, MonDLCVerdict)`` pair into Python truthiness.
    """

    scorer: str
    scorer_version: int
    status: GateStatus
    verdict: MonDLCVerdict
    gate_result: GateResult
    gates: tuple[MonDLCGate, ...]
    reason: str
    ruler_hash_commit: str | None
    expected_ruler_hash: str
    measurement_value: float | None
    min_corroboration_count: int
    corroboration_count: int
    evidence_refs: tuple[str, ...] = ()
    refusal_reason: str | None = None
    next_action: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, GateStatus):
            raise TypeError("MonDLCScoreResult.status must be a GateStatus identity")
        if not isinstance(self.verdict, MonDLCVerdict):
            raise TypeError("MonDLCScoreResult.verdict must be a MonDLCVerdict identity")
        object.__setattr__(self, "gates", tuple(self.gates))
        object.__setattr__(self, "evidence_refs", _string_tuple(self.evidence_refs))

    @property
    def ok(self) -> bool:
        return self.status is GateStatus.LIT and self.verdict is MonDLCVerdict.CORROBORATED

    def __bool__(self) -> bool:
        raise TypeError("MonDLCScoreResult truthiness is undefined; inspect status and verdict")

    def to_dict(self) -> dict[str, Any]:
        return {
            "scorer": self.scorer,
            "scorer_version": self.scorer_version,
            "status": self.status.value,
            "verdict": self.verdict.value,
            "ok": self.ok,
            "reason": self.reason,
            "refusal_reason": self.refusal_reason,
            "next_action": self.next_action,
            "ruler_hash_commit": self.ruler_hash_commit,
            "expected_ruler_hash": self.expected_ruler_hash,
            "measurement_value": self.measurement_value,
            "min_corroboration_count": self.min_corroboration_count,
            "corroboration_count": self.corroboration_count,
            "evidence_refs": list(self.evidence_refs),
            "gates": [
                {
                    "name": gate.name.value,
                    "status": gate.status.value,
                    "reason": gate.reason,
                }
                for gate in self.gates
            ],
        }


def score(
    m: MonDLCMeasurement | Mapping[str, Any] | None,
    ladder: MonDLCLadder | Mapping[str, Any],
    *,
    ruler_hash_commit: str,
) -> MonDLCScoreResult:
    """Score one MonDLC measurement against a frozen ladder.

    Missing/projected/stale evidence never succeeds. A valid measurement can
    become LIT only when it satisfies the ruler hash, observed-evidence,
    freshness, and corroboration gates.
    """

    frozen_ladder = _coerce_ladder(ladder)
    measurement = _coerce_measurement(m)
    commit = ruler_hash_commit.strip() if isinstance(ruler_hash_commit, str) else ""
    now = frozen_ladder.as_of or datetime.now(UTC)

    ruler_gate = _ruler_hash_gate(commit, frozen_ladder.ruler_hash)
    observed_gate = _observed_evidence_gate(measurement)
    freshness_gate = _freshness_gate(
        measurement,
        now=now,
        ttl_seconds=frozen_ladder.freshness_ttl_seconds,
    )
    corroboration_count = _corroboration_count(measurement)
    corroboration_gate = _corroboration_gate(
        corroboration_count,
        frozen_ladder.min_corroboration_count,
    )
    gates = (ruler_gate, observed_gate, freshness_gate, corroboration_gate)

    dark_gate = next((gate for gate in gates if gate.status is GateStatus.DARK), None)
    if dark_gate is not None:
        return _result(
            status=GateStatus.DARK,
            verdict=MonDLCVerdict.DARK,
            reason=dark_gate.reason,
            refusal_reason=dark_gate.reason,
            ladder=frozen_ladder,
            measurement=measurement,
            ruler_hash_commit=commit or None,
            gates=gates,
            corroboration_count=corroboration_count,
        )

    partial_gate = next((gate for gate in gates if gate.status is GateStatus.PARTIAL), None)
    if partial_gate is not None:
        return _result(
            status=GateStatus.PARTIAL,
            verdict=MonDLCVerdict.UNDETERMINED,
            reason=partial_gate.reason,
            refusal_reason=None,
            ladder=frozen_ladder,
            measurement=measurement,
            ruler_hash_commit=commit,
            gates=gates,
            corroboration_count=corroboration_count,
        )

    value = measurement.value if measurement is not None else None
    if value is None:
        return _result(
            status=GateStatus.DARK,
            verdict=MonDLCVerdict.DARK,
            reason="measurement_missing",
            refusal_reason="measurement_missing",
            ladder=frozen_ladder,
            measurement=measurement,
            ruler_hash_commit=commit,
            gates=gates,
            corroboration_count=corroboration_count,
        )
    if value <= frozen_ladder.negative_threshold:
        return _result(
            status=GateStatus.LIT,
            verdict=MonDLCVerdict.NEGATIVE,
            reason="negative_realized_return",
            refusal_reason=None,
            ladder=frozen_ladder,
            measurement=measurement,
            ruler_hash_commit=commit,
            gates=gates,
            corroboration_count=corroboration_count,
        )
    if value > frozen_ladder.positive_threshold:
        return _result(
            status=GateStatus.LIT,
            verdict=MonDLCVerdict.CORROBORATED,
            reason="corroborated_realized_return",
            refusal_reason=None,
            ladder=frozen_ladder,
            measurement=measurement,
            ruler_hash_commit=commit,
            gates=gates,
            corroboration_count=corroboration_count,
        )
    return _result(
        status=GateStatus.PARTIAL,
        verdict=MonDLCVerdict.UNDETERMINED,
        reason="realized_return_below_lit_threshold",
        refusal_reason=None,
        ladder=frozen_ladder,
        measurement=measurement,
        ruler_hash_commit=commit,
        gates=gates,
        corroboration_count=corroboration_count,
    )


def _result(
    *,
    status: GateStatus,
    verdict: MonDLCVerdict,
    reason: str,
    refusal_reason: str | None,
    ladder: MonDLCLadder,
    measurement: MonDLCMeasurement | None,
    ruler_hash_commit: str | None,
    gates: tuple[MonDLCGate, ...],
    corroboration_count: int,
) -> MonDLCScoreResult:
    gate_result_verdict: bool | None = None
    if status is GateStatus.LIT:
        gate_result_verdict = verdict is MonDLCVerdict.CORROBORATED
    evidence_refs = _combined_evidence_refs(measurement)
    return MonDLCScoreResult(
        scorer=MDLC_MEASURE_SCORER_NAME,
        scorer_version=MDLC_MEASURE_SCORER_VERSION,
        status=status,
        verdict=verdict,
        gate_result=GateResult(
            status=status,
            verdict=gate_result_verdict,
            reason=reason,
            evidence_refs=evidence_refs,
        ),
        gates=gates,
        reason=reason,
        ruler_hash_commit=ruler_hash_commit,
        expected_ruler_hash=ladder.ruler_hash,
        measurement_value=None if measurement is None else measurement.value,
        min_corroboration_count=ladder.min_corroboration_count,
        corroboration_count=corroboration_count,
        evidence_refs=evidence_refs,
        refusal_reason=refusal_reason,
        next_action=_next_action_for_reason(reason),
    )


def _coerce_ladder(value: MonDLCLadder | Mapping[str, Any]) -> MonDLCLadder:
    if isinstance(value, MonDLCLadder):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("ladder must be a MonDLCLadder or mapping; pass the frozen ruler ladder")
    as_of = _optional_datetime(value.get("as_of"))
    return MonDLCLadder(
        ruler_hash=_required_str(value.get("ruler_hash"), field="ruler_hash"),
        min_corroboration_count=int(value.get("min_corroboration_count", value.get("min_N", 2))),
        freshness_ttl_seconds=int(
            value.get("freshness_ttl_seconds", value.get("freshness_ttl_s", 86_400))
        ),
        as_of=as_of,
        positive_threshold=float(value.get("positive_threshold", 0.0)),
        negative_threshold=float(value.get("negative_threshold", -1.0)),
    )


def _coerce_measurement(
    value: MonDLCMeasurement | Mapping[str, Any] | None,
) -> MonDLCMeasurement | None:
    if value is None:
        return None
    if isinstance(value, MonDLCMeasurement):
        return value
    if not isinstance(value, Mapping):
        raise TypeError(
            "measurement must be a MonDLCMeasurement, mapping, or None; "
            "pass a witnessed realized-return measurement"
        )
    raw_value = _first_present(value, "measurement", "value", "realized_return")
    measurement_value = None if raw_value is None else _numeric(raw_value, field="measurement")
    return MonDLCMeasurement(
        value=measurement_value,
        provenance=str(value.get("provenance") or ""),
        observed_at=_optional_datetime(value.get("observed_at", value.get("timestamp"))),
        evidence_refs=_coerce_refs(value.get("evidence_refs")),
        corroborated_by=_coerce_refs(value.get("corroborated_by")),
    )


def _ruler_hash_gate(commit: str, expected: str) -> MonDLCGate:
    if not commit:
        return MonDLCGate(MonDLCGateName.RULER_HASH, GateStatus.DARK, "ruler_hash_missing")
    if commit != expected:
        return MonDLCGate(MonDLCGateName.RULER_HASH, GateStatus.DARK, "ruler_hash_mismatch")
    return MonDLCGate(MonDLCGateName.RULER_HASH, GateStatus.LIT, "ruler_hash_matched")


def _observed_evidence_gate(measurement: MonDLCMeasurement | None) -> MonDLCGate:
    if measurement is None or measurement.value is None:
        return MonDLCGate(
            MonDLCGateName.OBSERVED_EVIDENCE,
            GateStatus.DARK,
            "measurement_missing",
        )
    provenance = measurement.provenance.strip().casefold()
    if provenance in {"projected", "projection", "forecast", "estimated", "synthetic"}:
        return MonDLCGate(
            MonDLCGateName.OBSERVED_EVIDENCE,
            GateStatus.DARK,
            "projected_measurement",
        )
    if provenance not in {"realized", "witnessed", "inbound_rail", "settled"}:
        return MonDLCGate(
            MonDLCGateName.OBSERVED_EVIDENCE,
            GateStatus.DARK,
            "unwitnessed_measurement",
        )
    return MonDLCGate(
        MonDLCGateName.OBSERVED_EVIDENCE,
        GateStatus.LIT,
        "observed_realized_measurement",
    )


def _freshness_gate(
    measurement: MonDLCMeasurement | None,
    *,
    now: datetime,
    ttl_seconds: int,
) -> MonDLCGate:
    if measurement is None or measurement.observed_at is None:
        return MonDLCGate(
            MonDLCGateName.FRESHNESS, GateStatus.DARK, "measurement_timestamp_missing"
        )
    age_seconds = (now - measurement.observed_at).total_seconds()
    if age_seconds < 0:
        return MonDLCGate(MonDLCGateName.FRESHNESS, GateStatus.DARK, "measurement_from_future")
    if age_seconds > ttl_seconds:
        return MonDLCGate(MonDLCGateName.FRESHNESS, GateStatus.DARK, "measurement_stale")
    return MonDLCGate(MonDLCGateName.FRESHNESS, GateStatus.LIT, "measurement_fresh")


def _corroboration_gate(count: int, minimum: int) -> MonDLCGate:
    if count < minimum:
        return MonDLCGate(
            MonDLCGateName.CORROBORATION,
            GateStatus.PARTIAL,
            "insufficient_corroboration",
        )
    return MonDLCGate(
        MonDLCGateName.CORROBORATION,
        GateStatus.LIT,
        "corroboration_threshold_met",
    )


def _corroboration_count(measurement: MonDLCMeasurement | None) -> int:
    if measurement is None:
        return 0
    return len(_combined_evidence_refs(measurement))


def _combined_evidence_refs(measurement: MonDLCMeasurement | None) -> tuple[str, ...]:
    if measurement is None:
        return ()
    return tuple(dict.fromkeys((*measurement.evidence_refs, *measurement.corroborated_by)))


def _next_action_for_reason(reason: str) -> str | None:
    actions = {
        "corroborated_realized_return": None,
        "negative_realized_return": "Review the loss evidence before any ratchet or release action.",
        "realized_return_below_lit_threshold": (
            "Collect more realized-return evidence or keep the measurement undetermined."
        ),
        "ruler_hash_missing": "Supply the frozen ruler_hash_commit from the ladder artifact.",
        "ruler_hash_mismatch": "Refuse commit and re-run against the matching frozen ruler hash.",
        "measurement_missing": "Attach a witnessed realized-return measurement before scoring.",
        "projected_measurement": "Replace projected or forecast value with witnessed inbound evidence.",
        "unwitnessed_measurement": "Use realized, witnessed, inbound_rail, or settled provenance.",
        "measurement_timestamp_missing": "Attach the observed_at timestamp for the witnessed event.",
        "measurement_from_future": "Refuse future-dated evidence and re-read the source clock.",
        "measurement_stale": "Refresh the measurement from a current witnessed source.",
        "insufficient_corroboration": "Add independent evidence refs until min_corroboration_count is met.",
    }
    return actions.get(reason)


def _first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _numeric(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be numeric; attach a witnessed numeric realized return")
    return float(value)


def _required_str(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required; supply the frozen ruler hash")
    return value.strip()


def _optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _ensure_utc(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        return _ensure_utc(datetime.fromisoformat(text))
    raise TypeError("datetime field must be datetime, ISO string, or None")


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _coerce_refs(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, Sequence):
        return _string_tuple(value)
    raise TypeError("evidence refs must be a string sequence; attach durable evidence ids")


def _string_tuple(value: Sequence[str]) -> tuple[str, ...]:
    return tuple(str(item).strip() for item in value if str(item).strip())


__all__ = [
    "MDLC_MEASURE_SCORER_NAME",
    "MDLC_MEASURE_SCORER_VERSION",
    "MonDLCGate",
    "MonDLCGateName",
    "MonDLCLadder",
    "MonDLCMeasurement",
    "MonDLCScoreResult",
    "MonDLCVerdict",
    "score",
]
