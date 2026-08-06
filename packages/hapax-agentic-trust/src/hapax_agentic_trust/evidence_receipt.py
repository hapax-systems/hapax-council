"""Strict evidence receipt derived from a caller-pinned terminal projection.

The receipt carries integer facts and exact content bindings. It deliberately
has no route, scalar score, policy effect, spend/public authority, or external
action authority. Optional energy/hardware observations are technical telemetry
only and are excluded from the mechanical-evidence basis digest. Canonical parsing
is structural, not authenticity verification; callers must cross-verify parsed
receipts against a held-fd :class:`VerifiedTerminalProjection`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, fields
from typing import Any, ClassVar, Self

from .contract import (
    CONTRACT_VERSION,
    TOKEN_RE,
    JointOutcomeClass,
    ReplayComparisonStatus,
)
from .limits import DEFAULT_VERIFICATION_LIMITS, VerificationLimits
from .run_graph import (
    AgenticRunSummary,
    OutcomeCount,
    ReplayStatusCount,
    parse_strict_canonical_json,
)
from .terminal import (
    AUTHORITY_STATUS,
    CALLER_ANCHOR_STATUS_MATCHED,
    TEMPORAL_ANCHOR_STATUS,
    TERMINAL_CLOSURE_LAW,
    VerifiedTerminalProjection,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _sha(name: str, value: object) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be exact text")
    if not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _count(name: str, value: object) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an exact integer")
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")
    return value


def _exact_dict(name: str, value: object, expected: set[str]) -> dict[str, Any]:
    if type(value) is not dict:
        raise TypeError(f"{name} must be an exact object")
    if set(value) != expected:
        raise ValueError(f"{name} fields differ from schema")
    return value


def _canonical_bytes(document: dict[str, Any]) -> bytes:
    return json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


@dataclass(frozen=True, slots=True)
class AgenticTrustIntegerFactsV1:
    """Integer facts copied from the mechanically reconciled run summary."""

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
    initial_outcome_counts: tuple[tuple[str, int], ...]
    all_attempt_outcome_counts: tuple[tuple[str, int], ...]
    replay_status_counts: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name.endswith("_counts"):
                if type(value) is not tuple:
                    raise TypeError(f"{field.name} must be an exact tuple")
                names: list[str] = []
                for row in value:
                    if type(row) is not tuple or len(row) != 2 or type(row[0]) is not str:
                        raise TypeError(f"{field.name} rows must be exact (name, count) tuples")
                    names.append(row[0])
                    _count(f"{field.name}.{row[0]}", row[1])
                if names != sorted(names) or len(names) != len(set(names)):
                    raise ValueError(f"{field.name} names must be unique and sorted")
            else:
                _count(field.name, value)
        if self.terminal_attempt_count != (
            self.completed_attempt_count
            + self.incomplete_attempt_count
            + self.invalid_attempt_count
        ):
            raise ValueError("terminal disposition facts do not reconcile")
        if self.all_attempt_denominator != self.terminal_attempt_count:
            raise ValueError("all-attempt denominator differs from terminal attempts")
        if (
            sum(count for _, count in self.all_attempt_outcome_counts)
            != self.terminal_attempt_count
        ):
            raise ValueError("all-attempt outcome facts do not reconcile")
        if self.scheduled_pair_count < 1:
            raise ValueError("scheduled_pair_count must be positive for a terminal run graph")
        # Reconstruct the canonical summary so every enum, coverage, phase,
        # denominator, numerator, and reconciliation invariant is enforced in
        # one authoritative implementation rather than a weaker receipt copy.
        self.to_summary()

    @classmethod
    def from_summary(cls, summary: AgenticRunSummary) -> Self:
        if not isinstance(summary, AgenticRunSummary):
            raise TypeError("summary must be an AgenticRunSummary")
        scalar_names = tuple(
            field.name
            for field in fields(summary)
            if field.name
            not in {"initial_outcome_counts", "all_attempt_outcome_counts", "replay_status_counts"}
        )
        values = {name: getattr(summary, name) for name in scalar_names}
        return cls(
            **values,
            initial_outcome_counts=tuple(
                (row.outcome_class.value, row.count) for row in summary.initial_outcome_counts
            ),
            all_attempt_outcome_counts=tuple(
                (row.outcome_class.value, row.count) for row in summary.all_attempt_outcome_counts
            ),
            replay_status_counts=tuple(
                (row.status.value, row.count) for row in summary.replay_status_counts
            ),
        )

    def to_summary(self) -> AgenticRunSummary:
        """Reconstruct the authoritative summary, enforcing its full invariant set."""

        scalar_names = tuple(
            field.name
            for field in fields(AgenticRunSummary)
            if field.name
            not in {"initial_outcome_counts", "all_attempt_outcome_counts", "replay_status_counts"}
        )
        values = {name: getattr(self, name) for name in scalar_names}
        return AgenticRunSummary(
            **values,
            initial_outcome_counts=tuple(
                OutcomeCount(JointOutcomeClass(name), count)
                for name, count in self.initial_outcome_counts
            ),
            all_attempt_outcome_counts=tuple(
                OutcomeCount(JointOutcomeClass(name), count)
                for name, count in self.all_attempt_outcome_counts
            ),
            replay_status_counts=tuple(
                ReplayStatusCount(ReplayComparisonStatus(name), count)
                for name, count in self.replay_status_counts
            ),
        )

    def document(self) -> dict[str, Any]:
        document = asdict(self)
        for name in (
            "initial_outcome_counts",
            "all_attempt_outcome_counts",
            "replay_status_counts",
        ):
            document[name] = [{"name": key, "count": value} for key, value in getattr(self, name)]
        return document

    @classmethod
    def from_document(cls, value: object) -> Self:
        expected = {field.name for field in fields(cls)}
        row = _exact_dict("integer facts", value, expected)
        values = dict(row)
        for name in (
            "initial_outcome_counts",
            "all_attempt_outcome_counts",
            "replay_status_counts",
        ):
            raw_rows = values[name]
            if type(raw_rows) is not list:
                raise TypeError(f"{name} must be an exact array")
            expected_count = (
                len(ReplayComparisonStatus)
                if name == "replay_status_counts"
                else len(JointOutcomeClass)
            )
            if len(raw_rows) != expected_count:
                raise ValueError(f"{name} must contain exactly {expected_count} rows")
            parsed: list[tuple[str, int]] = []
            for raw in raw_rows:
                item = _exact_dict(f"{name} row", raw, {"name", "count"})
                if type(item["name"]) is not str:
                    raise TypeError(f"{name} row name must be exact text")
                parsed.append((item["name"], _count(f"{name}.{item['name']}", item["count"])))
            values[name] = tuple(parsed)
        return cls(**values)


@dataclass(frozen=True, slots=True)
class TechnicalTelemetryV1:
    """Caller-supplied technical annotations with no measurement or economic claim."""

    gpu_energy_millijoules: int | None = None
    wall_time_milliseconds: int | None = None
    peak_vram_bytes: int | None = None

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if value is not None:
                _count(field.name, value)

    def document(self) -> dict[str, int | None]:
        return asdict(self)

    @classmethod
    def from_document(cls, value: object) -> Self:
        expected = {field.name for field in fields(cls)}
        row = _exact_dict("technical telemetry", value, expected)
        return cls(**row)


@dataclass(frozen=True, slots=True)
class AgenticTrustEvidenceReceiptV1:
    """No-authority receipt for content matching three caller-supplied anchors."""

    RECEIPT_SCHEMA_VERSION: ClassVar[int] = 1
    RECEIPT_TYPE: ClassVar[str] = "AgenticTrustEvidenceReceiptV1"
    EVALUATOR_SURFACE_ID: ClassVar[str] = "local_compute.agentic_trust_evaluator_surface"
    CLAIM_CEILING: ClassVar[str] = "caller_pinned_terminal_mechanical_evidence_only"
    AUTHENTICITY_STATUS: ClassVar[str] = "content_addressed_not_authenticated"
    ANCHOR_ORIGIN_STATUS: ClassVar[str] = "caller_supplied_not_authenticated"
    CHRONOLOGY_STATUS: ClassVar[str] = "not_verified"
    CUSTODY_OBSERVATION_STATUS: ClassVar[str] = (
        "sequential_revalidation_not_filesystem_immutability"
    )
    TECHNICAL_TELEMETRY_ORIGIN_STATUS: ClassVar[str] = "caller_supplied_not_authenticated"
    TECHNICAL_TELEMETRY_MEASUREMENT_STATUS: ClassVar[str] = "not_verified"

    run_id: str
    anchor_status: str
    preregistration_core_sha256: str
    manifest_snapshot_artifact_sha256: str
    terminal_bundle_sha256: str
    evidence_root_sha256: str
    graph_sha256: str
    summary_sha256: str
    integer_facts: AgenticTrustIntegerFactsV1
    technical_telemetry: TechnicalTelemetryV1 | None = None
    route_id: None = None
    demand_eligible: bool = False
    policy_effect: str = "none"
    may_authorize_external_action: bool = False
    may_authorize_spend: bool = False
    may_authorize_public_egress: bool = False

    def __post_init__(self) -> None:
        if type(self.run_id) is not str or TOKEN_RE.fullmatch(self.run_id) is None:
            raise ValueError("run_id must be a bounded identity token")
        if self.anchor_status != CALLER_ANCHOR_STATUS_MATCHED:
            raise ValueError("native evidence receipt requires matched caller anchor values")
        for name in (
            "preregistration_core_sha256",
            "manifest_snapshot_artifact_sha256",
            "terminal_bundle_sha256",
            "evidence_root_sha256",
            "graph_sha256",
            "summary_sha256",
        ):
            _sha(name, getattr(self, name))
        if not isinstance(self.integer_facts, AgenticTrustIntegerFactsV1):
            raise TypeError("integer_facts must be AgenticTrustIntegerFactsV1")
        if self.integer_facts.to_summary().digest != self.summary_sha256:
            raise ValueError("integer_facts do not match summary_sha256")
        if self.technical_telemetry is not None and not isinstance(
            self.technical_telemetry, TechnicalTelemetryV1
        ):
            raise TypeError("technical_telemetry must be TechnicalTelemetryV1 or None")
        if self.route_id is not None:
            raise ValueError("evidence-only receipt cannot name a route")
        if self.demand_eligible is not False:
            raise ValueError("evidence-only receipt cannot satisfy demand")
        if self.policy_effect != "none":
            raise ValueError("evidence-only receipt cannot carry a policy effect")
        for name in (
            "may_authorize_external_action",
            "may_authorize_spend",
            "may_authorize_public_egress",
        ):
            if getattr(self, name) is not False:
                raise ValueError(f"{name} must remain false")

    @classmethod
    def from_verified_projection(
        cls,
        projection: VerifiedTerminalProjection,
        *,
        technical_telemetry: TechnicalTelemetryV1 | None = None,
    ) -> Self:
        if not isinstance(projection, VerifiedTerminalProjection):
            raise TypeError("projection must be a VerifiedTerminalProjection")
        if not projection.caller_anchor_match:
            raise ValueError("native evidence receipt requires all three caller anchor values")
        document = projection.bundle.document
        return cls(
            run_id=projection.graph.run_id,
            anchor_status=projection.anchor_status,
            preregistration_core_sha256=document["preregistration_core_sha256"],
            manifest_snapshot_artifact_sha256=document["manifest_snapshot_artifact_sha256"],
            terminal_bundle_sha256=projection.bundle.bundle_sha256,
            evidence_root_sha256=projection.bundle.evidence_root_sha256,
            graph_sha256=projection.graph.digest,
            summary_sha256=projection.summary_sha256,
            integer_facts=AgenticTrustIntegerFactsV1.from_summary(projection.summary),
            technical_telemetry=technical_telemetry,
        )

    def _document(self, *, include_technical_telemetry: bool) -> dict[str, Any]:
        document: dict[str, Any] = {
            "schema_version": self.RECEIPT_SCHEMA_VERSION,
            "receipt_type": self.RECEIPT_TYPE,
            "evaluator_surface_id": self.EVALUATOR_SURFACE_ID,
            "claim_ceiling": self.CLAIM_CEILING,
            "contract_version": CONTRACT_VERSION,
            "authority_status": AUTHORITY_STATUS,
            "terminal_closure_law": TERMINAL_CLOSURE_LAW,
            "temporal_anchor_status": TEMPORAL_ANCHOR_STATUS,
            "anchor_status": self.anchor_status,
            "anchor_origin_status": self.ANCHOR_ORIGIN_STATUS,
            "chronology_status": self.CHRONOLOGY_STATUS,
            "custody_observation_status": self.CUSTODY_OBSERVATION_STATUS,
            "authenticity_status": self.AUTHENTICITY_STATUS,
            "technical_telemetry_origin_status": self.TECHNICAL_TELEMETRY_ORIGIN_STATUS,
            "technical_telemetry_measurement_status": self.TECHNICAL_TELEMETRY_MEASUREMENT_STATUS,
            "run_id": self.run_id,
            "preregistration_core_sha256": self.preregistration_core_sha256,
            "manifest_snapshot_artifact_sha256": self.manifest_snapshot_artifact_sha256,
            "terminal_bundle_sha256": self.terminal_bundle_sha256,
            "evidence_root_sha256": self.evidence_root_sha256,
            "graph_sha256": self.graph_sha256,
            "summary_sha256": self.summary_sha256,
            "integer_facts": self.integer_facts.document(),
            "route_id": self.route_id,
            "demand_eligible": self.demand_eligible,
            "policy_effect": self.policy_effect,
            "may_authorize_external_action": self.may_authorize_external_action,
            "may_authorize_spend": self.may_authorize_spend,
            "may_authorize_public_egress": self.may_authorize_public_egress,
        }
        if include_technical_telemetry:
            document["technical_telemetry"] = (
                None if self.technical_telemetry is None else self.technical_telemetry.document()
            )
        return document

    @property
    def mechanical_evidence_sha256(self) -> str:
        """Digest of mechanically reconciled fields, excluding technical telemetry."""

        return hashlib.sha256(
            _canonical_bytes(self._document(include_technical_telemetry=False))
        ).hexdigest()

    @property
    def receipt_sha256(self) -> str:
        return hashlib.sha256(self.to_bytes()).hexdigest()

    @property
    def non_supply_evidence_ref(self) -> str:
        """Namespaced citation that preserves this receipt's no-policy-effect type.

        ``receipt_sha256`` is content identity only.  Cross-system citations must
        retain the receipt class so an opaque digest cannot accidentally acquire a
        freshness, confidence, equivalence, or authority effect when wrapped.
        """

        return f"agentic-trust-evidence-receipt-v1:sha256:{self.receipt_sha256}"

    def to_bytes(self) -> bytes:
        return _canonical_bytes(self._document(include_technical_telemetry=True))

    @classmethod
    def parse_unverified(
        cls,
        payload: bytes,
        *,
        limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
    ) -> Self:
        """Parse a canonical self-consistent envelope without claiming authenticity."""

        document = parse_strict_canonical_json(payload, limits=limits)
        expected = {
            "schema_version",
            "receipt_type",
            "evaluator_surface_id",
            "claim_ceiling",
            "contract_version",
            "authority_status",
            "terminal_closure_law",
            "temporal_anchor_status",
            "anchor_status",
            "anchor_origin_status",
            "chronology_status",
            "custody_observation_status",
            "authenticity_status",
            "technical_telemetry_origin_status",
            "technical_telemetry_measurement_status",
            "run_id",
            "preregistration_core_sha256",
            "manifest_snapshot_artifact_sha256",
            "terminal_bundle_sha256",
            "evidence_root_sha256",
            "graph_sha256",
            "summary_sha256",
            "integer_facts",
            "technical_telemetry",
            "route_id",
            "demand_eligible",
            "policy_effect",
            "may_authorize_external_action",
            "may_authorize_spend",
            "may_authorize_public_egress",
        }
        row = _exact_dict("agentic trust evidence receipt", document, expected)
        for name, expected_value in (
            ("schema_version", cls.RECEIPT_SCHEMA_VERSION),
            ("receipt_type", cls.RECEIPT_TYPE),
            ("evaluator_surface_id", cls.EVALUATOR_SURFACE_ID),
            ("claim_ceiling", cls.CLAIM_CEILING),
            ("contract_version", CONTRACT_VERSION),
            ("authority_status", AUTHORITY_STATUS),
            ("terminal_closure_law", TERMINAL_CLOSURE_LAW),
            ("temporal_anchor_status", TEMPORAL_ANCHOR_STATUS),
            ("anchor_origin_status", cls.ANCHOR_ORIGIN_STATUS),
            ("chronology_status", cls.CHRONOLOGY_STATUS),
            ("custody_observation_status", cls.CUSTODY_OBSERVATION_STATUS),
            ("authenticity_status", cls.AUTHENTICITY_STATUS),
            ("technical_telemetry_origin_status", cls.TECHNICAL_TELEMETRY_ORIGIN_STATUS),
            (
                "technical_telemetry_measurement_status",
                cls.TECHNICAL_TELEMETRY_MEASUREMENT_STATUS,
            ),
        ):
            if row[name] != expected_value or type(row[name]) is not type(expected_value):
                raise ValueError(f"receipt {name} mismatch")
        telemetry = row["technical_telemetry"]
        receipt = cls(
            run_id=row["run_id"],
            anchor_status=row["anchor_status"],
            preregistration_core_sha256=row["preregistration_core_sha256"],
            manifest_snapshot_artifact_sha256=row["manifest_snapshot_artifact_sha256"],
            terminal_bundle_sha256=row["terminal_bundle_sha256"],
            evidence_root_sha256=row["evidence_root_sha256"],
            graph_sha256=row["graph_sha256"],
            summary_sha256=row["summary_sha256"],
            integer_facts=AgenticTrustIntegerFactsV1.from_document(row["integer_facts"]),
            technical_telemetry=(
                None if telemetry is None else TechnicalTelemetryV1.from_document(telemetry)
            ),
            route_id=row["route_id"],
            demand_eligible=row["demand_eligible"],
            policy_effect=row["policy_effect"],
            may_authorize_external_action=row["may_authorize_external_action"],
            may_authorize_spend=row["may_authorize_spend"],
            may_authorize_public_egress=row["may_authorize_public_egress"],
        )
        if receipt.to_bytes() != payload:
            raise ValueError("receipt does not round-trip to canonical bytes")
        return receipt

    @classmethod
    def from_bytes(
        cls,
        payload: bytes,
        *,
        limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
    ) -> Self:
        """Compatibility spelling for structural parsing; result is not authenticated."""

        return cls.parse_unverified(payload, limits=limits)

    def verify_against_projection(self, projection: VerifiedTerminalProjection) -> None:
        """Cross-verify every evidence field against one held-fd terminal projection."""

        expected = type(self).from_verified_projection(
            projection,
            technical_telemetry=self.technical_telemetry,
        )
        if self != expected:
            raise ValueError(
                "receipt does not match the verified terminal projection; next action: "
                "discard the envelope and re-import it with the same three held anchors"
            )

    @classmethod
    def from_bytes_verified(
        cls,
        payload: bytes,
        projection: VerifiedTerminalProjection,
        *,
        limits: VerificationLimits = DEFAULT_VERIFICATION_LIMITS,
    ) -> Self:
        """Parse and cross-verify a receipt against one held-fd content projection."""

        receipt = cls.parse_unverified(payload, limits=limits)
        receipt.verify_against_projection(projection)
        return receipt
