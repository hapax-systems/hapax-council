"""Gate-0 execution admission and machine-only lease contracts.

This module extends the existing lifecycle position; it is not another FSM or
authority store. Context, route, resource, and capability records remain
evidence. A separately authenticated authority input is validated and narrowed
before an admission can be issued, and only a current execution lease may be
consumed by a machine adapter.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Self

from hapax.context_canon import ContextFrame, ContextPosition, ContextSelection
from hapax.context_canon.contract import _domain_hash
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from shared.coord_projection import (
    LifecycleTransitionError,
    ReadOnlyFsSnapshot,
    ReadOnlySnapshotError,
    _load_private_manifest_payload,
    _normalized_path,
)
from shared.dispatcher_policy import DispatchAction, DispatchRequest, RouteDecision
from shared.epistemic_impingement import (
    EpistemicImpingementError,
    EpistemicImpingementTrace,
    require_current_epistemic_trace,
)

if TYPE_CHECKING:
    from shared.sdlc_claim import AppliedClaimPublicationSnapshot

ACTION_INTENT_SCHEMA = "hapax.action-intent.v1"
EFFECT_MANIFEST_SCHEMA = "hapax.effect-manifest.v1"
EXECUTOR_DESCRIPTOR_SCHEMA = "hapax.executor-descriptor.v1"
EXECUTOR_REGISTRY_PROJECTION_SCHEMA = "hapax.executor-registry-projection.v1"
EXECUTION_TRUST_QUERY_SCHEMA = "hapax.execution-trust-query.v1"
EXECUTION_TRUST_ENVELOPE_SCHEMA = "hapax.execution-trust-envelope.v1"
EXECUTION_CURRENTNESS_QUERY_SCHEMA = "hapax.execution-currentness-query.v2"
EXECUTION_CURRENTNESS_ENVELOPE_SCHEMA = "hapax.execution-currentness-envelope.v2"
FRONTIER_VALIDITY_ENVELOPE_SCHEMA = "hapax.frontier-validity-envelope.v1"
PROTECTED_APERTURE_DECISION_SCHEMA = "hapax.protected-aperture-decision.v1"
HISTORICAL_PROTECTED_CLAIM_COORDINATES_SCHEMA = "hapax.protected-claim-coordinates.v1"
PROSPECTIVE_CLAIM_PUBLICATION_BASIS_SCHEMA = "hapax.prospective-claim-publication-basis.v1"
PROSPECTIVE_CLAIM_PUBLICATION_CARRIER_SCHEMA = "hapax.prospective-claim-publication-carrier.v1"
PROTECTED_CLAIM_COORDINATES_SCHEMA = "hapax.protected-claim-coordinates.v2"
PROTECTED_ACTION_REQUEST_SCHEMA = "hapax.protected-action-request.v1"
HISTORICAL_EXECUTION_INVOCATION_ENVELOPE_SCHEMA = "hapax.execution-invocation-envelope.v1"
EXECUTION_INVOCATION_ENVELOPE_SCHEMA = "hapax.execution-invocation-envelope.v2"
EXECUTION_COMPOSITION_PORT_DESCRIPTORS_SCHEMA = "hapax.execution-composition-port-descriptors.v3"
EXECUTION_COMPOSITION_MANIFEST_SCHEMA = "hapax.execution-composition-manifest.v2"
HISTORICAL_EXECUTION_INVOCATION_BUNDLE_SCHEMA = "hapax.execution-invocation-bundle.v2"
EXECUTION_INVOCATION_BUNDLE_SCHEMA = "hapax.execution-invocation-bundle.v3"
EXECUTION_INVOCATION_BUNDLE_POINTER_SCHEMA = "hapax.execution-invocation-bundle-pointer.v2"
PROTECTED_ACTION_DECISION_SCHEMA = "hapax.protected-action-decision.v1"
PROTECTED_ACTION_HOLD_SCHEMA = "hapax.protected-action-hold.v1"
COMPLETION_EVALUATION_SCHEMA = "hapax.completion-evaluation.v1"
COMPLETION_EVALUATION_QUERY_SCHEMA = "hapax.completion-evaluation-query.v1"
OUTCOME_PIPELINE_READINESS_QUERY_SCHEMA = "hapax.outcome-pipeline-readiness-query.v1"
OUTCOME_PIPELINE_READINESS_ENVELOPE_SCHEMA = "hapax.outcome-pipeline-readiness-envelope.v1"
EFFECT_OBSERVATION_SCHEMA = "hapax.effect-observation.v1"
OUTCOME_EVENT_SCHEMA = "hapax.outcome-event.v1"
EVENT_APPEND_RECEIPT_SCHEMA = "hapax.event-append-receipt.v1"
OUTCOME_RECEIPT_SCHEMA = "hapax.outcome-receipt.v1"
OUTCOME_PROJECTION_SNAPSHOT_SCHEMA = "hapax.outcome-projection-snapshot.v1"
OUTCOME_REPLAY_CATALOG_SCHEMA = "hapax.outcome-replay-catalog-snapshot.v1"
OUTCOME_REPLAY_RESULT_SCHEMA = "hapax.outcome-replay-result.v1"
CLAIM_PUBLICATION_COMPLETION_EVIDENCE_SCHEMA = "hapax.claim-publication-completion-evidence.v3"
AUTHORITY_EVIDENCE_SCHEMA = "hapax.authority-evidence.v1"
VALID_AUTHORITY_GRANT_SCHEMA = "hapax.valid-authority-grant.v1"
AUTHORITY_HOLD_SCHEMA = "hapax.authority-hold.v1"
CLAIM_PROOF_SCHEMA = "hapax.applied-claim-proof.v1"
ADMITTED_CLAIM_PROOF_SCHEMA = "hapax.applied-claim-proof.v2"
HISTORICAL_APPLIED_CLAIM_OWNERSHIP_SCHEMA = "hapax.applied-claim-ownership-proof.v3"
APPLIED_CLAIM_OWNERSHIP_SCHEMA = "hapax.applied-claim-ownership-proof.v7"
CURRENT_CLAIM_POSITION_SCHEMA = "hapax.current-claim-position.v3"
DEPENDENCY_CLOSURE_SCHEMA = "hapax.dependency-closure-evidence.v1"
QUOTA_RESERVATION_SCHEMA = "hapax.quota-reservation-evidence.v1"
EXECUTION_TARGET_SCHEMA = "hapax.execution-target-evidence.v1"
EXECUTION_ADMISSION_SCHEMA = "hapax.execution-admission.v1"
HISTORICAL_BOUND_EXECUTION_CALL_SCHEMA = "hapax.bound-execution-call.v1"
BOUND_EXECUTION_CALL_SCHEMA = "hapax.bound-execution-call.v2"
HISTORICAL_EXECUTION_LEASE_V2_SCHEMA = "hapax.execution-lease.v2"
EXECUTION_LEASE_SCHEMA = "hapax.execution-lease.v3"
SCHEMA_ID = "https://hapax.systems/schemas/execution-admission.schema.json"
_MAX_EXECUTION_INVOCATION_BUNDLE_BYTES = 16 * 1024 * 1024
_MAX_EXECUTION_COMPOSITION_MANIFEST_BYTES = 1024 * 1024
_MAX_BOUND_MODULE_BYTES = 64 * 1024 * 1024


class ExecutionAdmissionError(RuntimeError):
    """Typed fail-closed refusal at an execution boundary."""

    def __init__(self, reason_code: str, repair_action: str, detail: str = "") -> None:
        self.reason_code = reason_code
        self.repair_action = repair_action
        self.detail = detail
        message = f"{reason_code}: {repair_action}"
        if detail:
            message += f" ({detail})"
        super().__init__(message)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


def _require_exact_type(value: Any, expected: type[Any], label: str) -> Any:
    """Reject duck types and subclasses before invoking any supplied object."""

    if type(value) is not expected:
        raise ExecutionAdmissionError(
            "execution_projection_type_invalid",
            "supply the exact immutable Gate-0 data carrier",
            label,
        )
    return value


def _nonblank(value: str) -> str:
    if not value or value != value.strip():
        raise ValueError("wire strings must be nonblank without edge whitespace")
    value.encode("utf-8", errors="strict")
    return value


def _string_set(value: tuple[str, ...], *, allow_empty: bool = False) -> tuple[str, ...]:
    if not allow_empty and not value:
        raise ValueError("string set must not be empty")
    if value != tuple(sorted(set(value))):
        raise ValueError("string set must be sorted and unique")
    if any(_nonblank(item) != item for item in value):
        raise ValueError("string set contains an invalid entry")
    return value


def _canonical_timestamp(value: str | datetime) -> str:
    try:
        parsed = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )
    except ValueError as exc:
        raise ValueError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must carry a timezone")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _checked_timestamp(value: str) -> str:
    canonical = _canonical_timestamp(value)
    if canonical != value:
        raise ValueError("timestamp must be canonical UTC with microseconds")
    return value


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _payload_hash(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", by_alias=True)
    return _sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    )


def _self_hash(domain: str, body: Mapping[str, object]) -> str:
    return _domain_hash(domain, body)


class ContentAddress(_FrozenModel):
    """An exact external object reference and its content hash."""

    ref: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("ref")
    @classmethod
    def validate_ref(cls, value: str) -> str:
        return _nonblank(value)


def content_address(ref: str, value: object) -> ContentAddress:
    return ContentAddress(ref=_nonblank(ref), sha256=_payload_hash(value))


def _content_address_key(value: ContentAddress) -> tuple[str, str]:
    return value.ref, value.sha256


def _content_address_set(
    value: tuple[ContentAddress, ...],
    *,
    allow_empty: bool = False,
) -> tuple[ContentAddress, ...]:
    if not allow_empty and not value:
        raise ValueError("content-address set must not be empty")
    expected = tuple(sorted(value, key=_content_address_key))
    if len({_content_address_key(item) for item in expected}) != len(expected):
        raise ValueError("content-address set must be sorted and unique")
    if value != expected:
        raise ValueError("content-address set must be sorted and unique")
    return value


class RootDisposition(_FrozenModel):
    """Frontier evidence for one exact root, shared by trust and currentness."""

    root: ContentAddress
    disposition: Literal[
        "current",
        "superseded",
        "revoked",
        "missing",
        "contradicted",
        "unknown",
    ]
    superseding_roots: tuple[ContentAddress, ...]
    reason_codes: tuple[str, ...]
    source_event_refs: tuple[str, ...] = Field(min_length=1)

    @field_validator("superseding_roots")
    @classmethod
    def validate_superseding(
        cls,
        value: tuple[ContentAddress, ...],
    ) -> tuple[ContentAddress, ...]:
        return _content_address_set(value, allow_empty=True)

    @field_validator("reason_codes", "source_event_refs")
    @classmethod
    def validate_sets(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _string_set(value, allow_empty=info.field_name == "reason_codes")

    @model_validator(mode="after")
    def validate_disposition(self) -> Self:
        if self.disposition == "current":
            if self.reason_codes or self.superseding_roots:
                raise ValueError("current roots cannot carry reasons or replacements")
        elif not self.reason_codes:
            raise ValueError("noncurrent roots require typed reasons")
        if self.disposition == "superseded" and not self.superseding_roots:
            raise ValueError("superseded roots require replacements")
        if self.disposition != "superseded" and self.superseding_roots:
            raise ValueError("only superseded roots may carry replacements")
        return self


class FrontierValidityEnvelope(_FrozenModel):
    """Moving, non-authorizing validity for one immutable projection."""

    schema_id: Literal["hapax.frontier-validity-envelope.v1"] = Field(alias="schema")
    envelope_ref: str
    envelope_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    subject_projection: ContentAddress
    resolver: ContentAddress
    event_plane: ContentAddress
    source_frontier: ContentAddress
    checked_frontier: ContentAddress
    root_dispositions: tuple[RootDisposition, ...] = Field(min_length=1)
    decision: Literal["valid", "hold"]
    reason_codes: tuple[str, ...]
    repair_refs: tuple[str, ...]
    checked_at: str
    stale_after: str
    may_authorize: Literal[False]

    @field_validator("envelope_ref")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("reason_codes", "repair_refs")
    @classmethod
    def validate_sets(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _string_set(value, allow_empty=True)

    @field_validator("checked_at", "stale_after")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        roots = tuple(item.root for item in self.root_dispositions)
        if roots != tuple(sorted(roots, key=_content_address_key)) or len(
            {_content_address_key(item) for item in roots}
        ) != len(roots):
            raise ValueError("frontier validity roots must be sorted and unique")
        valid = (
            all(item.disposition == "current" for item in self.root_dispositions)
            and not self.reason_codes
            and not self.repair_refs
            and self.checked_at < self.stale_after
        )
        if (self.decision == "valid") != valid:
            raise ValueError("frontier validity decision differs from its evidence")
        if self.decision == "hold" and (
            not self.reason_codes
            or self.repair_refs != tuple(f"repair:{item}" for item in self.reason_codes)
        ):
            raise ValueError("held frontier validity requires exact reason/repair pairs")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"envelope_ref", "envelope_hash"},
        )
        expected = _self_hash(FRONTIER_VALIDITY_ENVELOPE_SCHEMA, body)
        if self.envelope_hash != expected or self.envelope_ref != (
            f"frontier-validity-envelope@sha256:{expected}"
        ):
            raise ValueError("frontier validity reference/hash do not bind its body")
        return self


class HistoricalSupportDisposition(_FrozenModel):
    """Authenticity evidence for durable support that is not action-current authority."""

    root: ContentAddress
    disposition: Literal["present", "missing", "contradicted", "unknown"]
    reason_codes: tuple[str, ...]
    source_event_refs: tuple[str, ...] = Field(min_length=1)

    @field_validator("reason_codes", "source_event_refs")
    @classmethod
    def validate_sets(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _string_set(value, allow_empty=info.field_name == "reason_codes")

    @model_validator(mode="after")
    def validate_disposition(self) -> Self:
        if self.disposition == "present" and self.reason_codes:
            raise ValueError("present historical support cannot carry reasons")
        if self.disposition != "present" and not self.reason_codes:
            raise ValueError("unavailable historical support requires typed reasons")
        return self


ExecutionTrustClass = Literal[
    "authenticated_authority_receipt",
    "execution_lease_issuer",
]


class ExecutionTrustQuery(_FrozenModel):
    """Exact, non-authorizing question to the current trust projection."""

    schema_id: Literal["hapax.execution-trust-query.v1"] = Field(alias="schema")
    query_ref: str
    query_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    trust_class: ExecutionTrustClass
    subject_roots: tuple[ContentAddress, ...] = Field(min_length=1)
    presented_receipt: ContentAddress
    required_roots: tuple[ContentAddress, ...] = Field(min_length=2)
    supersession_frontier_ref: str
    queried_at: str
    may_authorize: Literal[False]

    @field_validator("query_ref", "supersession_frontier_ref")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("subject_roots", "required_roots")
    @classmethod
    def validate_roots(
        cls,
        value: tuple[ContentAddress, ...],
    ) -> tuple[ContentAddress, ...]:
        return _content_address_set(value)

    @field_validator("queried_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_query(self) -> Self:
        roots = {_content_address_key(item) for item in self.required_roots}
        anchors = {
            *(_content_address_key(item) for item in self.subject_roots),
            _content_address_key(self.presented_receipt),
        }
        if not anchors.issubset(roots):
            raise ValueError("trust query omits a subject root or presented receipt")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"query_ref", "query_hash"},
        )
        expected = _self_hash(EXECUTION_TRUST_QUERY_SCHEMA, body)
        if self.query_hash != expected or self.query_ref != (
            f"execution-trust-query@sha256:{expected}"
        ):
            raise ValueError("trust query reference/hash do not bind its body")
        return self


def build_execution_trust_query(
    *,
    trust_class: ExecutionTrustClass,
    subject_roots: Sequence[ContentAddress],
    presented_receipt: ContentAddress,
    required_roots: Sequence[ContentAddress],
    supersession_frontier_ref: str,
    queried_at: str | datetime,
) -> ExecutionTrustQuery:
    roots = tuple(
        sorted(
            {
                _content_address_key(item): item
                for item in (*required_roots, *subject_roots, presented_receipt)
            }.values(),
            key=_content_address_key,
        )
    )
    body: dict[str, object] = {
        "schema": EXECUTION_TRUST_QUERY_SCHEMA,
        "trust_class": trust_class,
        "subject_roots": tuple(
            sorted(
                {_content_address_key(item): item for item in subject_roots}.values(),
                key=_content_address_key,
            )
        ),
        "presented_receipt": presented_receipt,
        "required_roots": roots,
        "supersession_frontier_ref": _nonblank(supersession_frontier_ref),
        "queried_at": _canonical_timestamp(queried_at),
        "may_authorize": False,
    }
    digest = _self_hash(EXECUTION_TRUST_QUERY_SCHEMA, body)
    return ExecutionTrustQuery.model_validate(
        {
            **body,
            "query_ref": f"execution-trust-query@sha256:{digest}",
            "query_hash": digest,
        }
    )


class ExecutionTrustEnvelope(_FrozenModel):
    """Frontier-bound answer produced by the installed trust projection."""

    schema_id: Literal["hapax.execution-trust-envelope.v1"] = Field(alias="schema")
    envelope_ref: str
    envelope_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    query: ContentAddress
    resolver: ContentAddress
    decision: Literal["trusted", "hold"]
    event_frontier: ContentAddress
    supersession_frontier_ref: str
    root_dispositions: tuple[RootDisposition, ...] = Field(min_length=1)
    reason_codes: tuple[str, ...]
    repair_refs: tuple[str, ...]
    checked_at: str
    stale_after: str
    may_authorize: Literal[False]

    @field_validator("envelope_ref", "supersession_frontier_ref")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("reason_codes", "repair_refs")
    @classmethod
    def validate_sets(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _string_set(value, allow_empty=True)

    @field_validator("checked_at", "stale_after")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        if self.checked_at >= self.stale_after:
            raise ValueError("trust envelope requires a future freshness horizon")
        roots = tuple(item.root for item in self.root_dispositions)
        if roots != tuple(sorted(roots, key=_content_address_key)) or len(
            {_content_address_key(item) for item in roots}
        ) != len(roots):
            raise ValueError("trust root dispositions must be sorted and unique")
        if self.decision == "trusted":
            if (
                any(item.disposition != "current" for item in self.root_dispositions)
                or self.reason_codes
                or self.repair_refs
            ):
                raise ValueError("trusted envelopes require roots and no repair claims")
        elif not self.reason_codes or self.repair_refs != tuple(
            f"repair:{item}" for item in self.reason_codes
        ):
            raise ValueError("held trust envelopes require exact reason/repair pairs")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"envelope_ref", "envelope_hash"},
        )
        expected = _self_hash(EXECUTION_TRUST_ENVELOPE_SCHEMA, body)
        if self.envelope_hash != expected or self.envelope_ref != (
            f"execution-trust-envelope@sha256:{expected}"
        ):
            raise ValueError("trust envelope reference/hash do not bind its body")
        return self


@dataclass(frozen=True)
class ExecutionTrustResolver:
    """Data-only trust projection catalog; an empty instance fails closed."""

    resolver: ContentAddress | None = None
    envelopes: tuple[ExecutionTrustEnvelope, ...] = ()

    def __post_init__(self) -> None:
        if self.resolver is not None:
            _require_exact_type(
                self.resolver, ContentAddress, "execution trust resolver descriptor"
            )
            object.__setattr__(
                self,
                "resolver",
                ContentAddress.model_validate(self.resolver.model_dump(mode="json")),
            )
        checked = tuple(
            ExecutionTrustEnvelope.model_validate(
                _require_exact_type(
                    item,
                    ExecutionTrustEnvelope,
                    "execution trust envelope",
                ).model_dump(mode="json", by_alias=True)
            )
            for item in self.envelopes
        )
        keys = tuple((item.query.ref, item.query.sha256) for item in checked)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("trust projection catalog must be sorted and query-unique")
        if self.resolver is not None and any(item.resolver != self.resolver for item in checked):
            raise ValueError("trust projection catalog differs from its resolver descriptor")
        object.__setattr__(self, "envelopes", checked)

    def evaluate(self, query: ExecutionTrustQuery) -> ExecutionTrustEnvelope:
        _require_exact_type(query, ExecutionTrustQuery, "execution trust query")
        checked_query = ExecutionTrustQuery.model_validate(
            query.model_dump(mode="json", by_alias=True)
        )
        if self.resolver is None:
            raise ExecutionAdmissionError(
                "execution_trust_resolver_unavailable",
                "install the accepted Spine-backed trust projection before admission",
                checked_query.trust_class,
            )
        expected_query = ContentAddress(
            ref=checked_query.query_ref,
            sha256=checked_query.query_hash,
        )
        envelope = next(
            (item for item in self.envelopes if item.query == expected_query),
            None,
        )
        if envelope is None:
            raise ExecutionAdmissionError(
                "execution_trust_projection_missing",
                "install the exact sealed trust result for this query",
                checked_query.query_ref,
            )
        reasons: list[str] = []
        if envelope.query != expected_query:
            reasons.append("execution_trust_query_mismatch")
        if envelope.resolver != self.resolver:
            reasons.append("execution_trust_resolver_mismatch")
        if envelope.supersession_frontier_ref != checked_query.supersession_frontier_ref:
            reasons.append("execution_trust_frontier_mismatch")
        if tuple(item.root for item in envelope.root_dispositions) != checked_query.required_roots:
            reasons.append("execution_trust_root_coverage_mismatch")
        if not envelope.checked_at <= checked_query.queried_at < envelope.stale_after:
            reasons.append("execution_trust_envelope_stale")
        if reasons:
            raise ExecutionAdmissionError(
                "execution_trust_not_current",
                "hold admission and refresh the exact frontier-bound trust projection",
                ",".join(sorted(set(reasons))),
            )
        return envelope

    def require_trusted(self, query: ExecutionTrustQuery) -> ExecutionTrustEnvelope:
        envelope = self.evaluate(query)
        if envelope.decision != "trusted":
            raise ExecutionAdmissionError(
                "execution_trust_not_current",
                "hold admission and refresh the exact frontier-bound trust projection",
                ",".join(envelope.reason_codes or ("execution_trust_held",)),
            )
        return envelope

    def resolve(self, query: ExecutionTrustQuery) -> ExecutionTrustEnvelope:
        """Compatibility spelling for operational consumers requiring trust."""

        return self.require_trusted(query)


DEFAULT_EXECUTION_TRUST_RESOLVER = ExecutionTrustResolver()


class EffectManifest(_FrozenModel):
    """Immutable description of the effect and its proof obligations."""

    schema_id: Literal["hapax.effect-manifest.v1"] = Field(alias="schema")
    manifest_ref: str
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    operation: str
    capability_role: str
    execution_host: str
    mutating: bool = Field(strict=True)
    external_effect: bool = Field(strict=True)
    effect_classes: tuple[str, ...]
    effect_targets: tuple[ContentAddress, ...]
    scope_refs: tuple[str, ...]
    observation_contract: ContentAddress
    completion_predicate: ContentAddress
    idempotence_class: Literal["idempotent", "non_idempotent"]
    reconciliation_contract: ContentAddress | None
    compensation: ContentAddress | None
    may_authorize: Literal[False]

    @field_validator("manifest_ref", "operation", "capability_role", "execution_host")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("effect_classes", "scope_refs")
    @classmethod
    def validate_sets(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _string_set(
            value,
            allow_empty=info.field_name in {"effect_classes", "scope_refs"},
        )

    @field_validator("effect_targets")
    @classmethod
    def validate_targets(cls, value: tuple[ContentAddress, ...]) -> tuple[ContentAddress, ...]:
        return _content_address_set(value, allow_empty=True)

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        has_effect = self.mutating or self.external_effect
        if has_effect and (not self.effect_classes or not self.effect_targets):
            raise ValueError("effects require effect classes and exact targets")
        if has_effect and not self.scope_refs:
            raise ValueError("effect-bearing manifests require immutable scope")
        if has_effect and self.reconciliation_contract is None:
            raise ValueError("effect-bearing manifests require a reconciliation contract")
        if not has_effect and (
            self.effect_classes
            or self.effect_targets
            or self.scope_refs
            or self.idempotence_class != "idempotent"
            or self.reconciliation_contract is not None
            or self.compensation is not None
        ):
            raise ValueError("no-effect manifests cannot carry effect or recovery claims")
        if self.idempotence_class == "non_idempotent" and self.reconciliation_contract is None:
            raise ValueError("non-idempotent effects require reconciliation")
        if self.reconciliation_contract is None and self.compensation is not None:
            raise ValueError("compensation requires a reconciliation contract")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"manifest_ref", "manifest_hash"},
        )
        expected = _self_hash(EFFECT_MANIFEST_SCHEMA, body)
        if (
            self.manifest_hash != expected
            or self.manifest_ref != f"effect-manifest@sha256:{expected}"
        ):
            raise ValueError("effect manifest reference/hash do not bind its body")
        return self


def build_effect_manifest(
    *,
    operation: str,
    capability_role: str,
    execution_host: str,
    mutating: bool,
    external_effect: bool,
    effect_classes: Sequence[str],
    effect_targets: Sequence[ContentAddress],
    scope_refs: Sequence[str],
    observation_contract: ContentAddress,
    completion_predicate: ContentAddress,
    idempotence_class: Literal["idempotent", "non_idempotent"],
    reconciliation_contract: ContentAddress | None,
    compensation: ContentAddress | None,
) -> EffectManifest:
    body: dict[str, object] = {
        "schema": EFFECT_MANIFEST_SCHEMA,
        "operation": _nonblank(operation),
        "capability_role": _nonblank(capability_role),
        "execution_host": _nonblank(execution_host),
        "mutating": mutating,
        "external_effect": external_effect,
        "effect_classes": tuple(sorted(set(effect_classes))),
        "effect_targets": tuple(
            sorted(
                {_content_address_key(item): item for item in effect_targets}.values(),
                key=_content_address_key,
            )
        ),
        "scope_refs": tuple(sorted(set(scope_refs))),
        "observation_contract": observation_contract,
        "completion_predicate": completion_predicate,
        "idempotence_class": idempotence_class,
        "reconciliation_contract": reconciliation_contract,
        "compensation": compensation,
        "may_authorize": False,
    }
    digest = _self_hash(EFFECT_MANIFEST_SCHEMA, body)
    return EffectManifest.model_validate(
        {
            **body,
            "manifest_ref": f"effect-manifest@sha256:{digest}",
            "manifest_hash": digest,
        }
    )


class EffectManifestResolver:
    """Immutable exact-address manifest lookup; empty until activation composition."""

    def __init__(
        self,
        manifests: Iterable[EffectManifest] = (),
        *,
        resolver: ContentAddress | None = None,
    ) -> None:
        indexed: dict[tuple[str, str], EffectManifest] = {}
        for manifest in manifests:
            _require_exact_type(manifest, EffectManifest, "effect manifest")
            checked = EffectManifest.model_validate(manifest.model_dump(mode="json", by_alias=True))
            address = ContentAddress(
                ref=checked.manifest_ref,
                sha256=checked.manifest_hash,
            )
            key = _content_address_key(address)
            if key in indexed:
                raise ValueError("effect manifest resolver collision")
            indexed[key] = checked
        self._manifests = indexed
        if resolver is not None:
            _require_exact_type(resolver, ContentAddress, "effect manifest resolver descriptor")
            resolver = ContentAddress.model_validate(resolver.model_dump(mode="json"))
        self.resolver = resolver

    def resolve(self, address: ContentAddress) -> EffectManifest:
        _require_exact_type(address, ContentAddress, "effect manifest address")
        manifest = self._manifests.get(_content_address_key(address))
        if manifest is None:
            raise ExecutionAdmissionError(
                "effect_manifest_unavailable",
                "install the exact admitted effect manifest before execution",
                address.ref,
            )
        return manifest


DEFAULT_EFFECT_MANIFEST_RESOLVER = EffectManifestResolver()


class ExecutorDescriptor(_FrozenModel):
    """Static implementation identity, separate from adapter and route identity."""

    schema_id: Literal["hapax.executor-descriptor.v1"] = Field(alias="schema")
    descriptor_ref: str
    descriptor_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    executor: ContentAddress
    adapter: ContentAddress
    harness: ContentAddress
    runtime_identity: ContentAddress
    active_generation_roots: tuple[ContentAddress, ...] = Field(min_length=1)
    execution_host: str
    platform: str
    mode: str
    profile: str
    selected_descriptor_leaf: str
    entrypoint: str
    may_authorize: Literal[False]

    @field_validator(
        "descriptor_ref",
        "execution_host",
        "platform",
        "mode",
        "profile",
        "selected_descriptor_leaf",
        "entrypoint",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("active_generation_roots")
    @classmethod
    def validate_roots(
        cls,
        value: tuple[ContentAddress, ...],
    ) -> tuple[ContentAddress, ...]:
        return _content_address_set(value)

    @model_validator(mode="after")
    def validate_descriptor(self) -> Self:
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"descriptor_ref", "descriptor_hash"},
        )
        expected = _self_hash(EXECUTOR_DESCRIPTOR_SCHEMA, body)
        if self.descriptor_hash != expected or self.descriptor_ref != (
            f"executor-descriptor@sha256:{expected}"
        ):
            raise ValueError("executor descriptor reference/hash do not bind its body")
        return self


def build_executor_descriptor(
    *,
    executor: ContentAddress,
    adapter: ContentAddress,
    harness: ContentAddress,
    runtime_identity: ContentAddress,
    active_generation_roots: Sequence[ContentAddress],
    execution_host: str,
    platform: str,
    mode: str,
    profile: str,
    selected_descriptor_leaf: str,
    entrypoint: str,
) -> ExecutorDescriptor:
    body: dict[str, object] = {
        "schema": EXECUTOR_DESCRIPTOR_SCHEMA,
        "executor": executor,
        "adapter": adapter,
        "harness": harness,
        "runtime_identity": runtime_identity,
        "active_generation_roots": tuple(
            sorted(
                {_content_address_key(item): item for item in active_generation_roots}.values(),
                key=_content_address_key,
            )
        ),
        "execution_host": _nonblank(execution_host),
        "platform": _nonblank(platform),
        "mode": _nonblank(mode),
        "profile": _nonblank(profile),
        "selected_descriptor_leaf": _nonblank(selected_descriptor_leaf),
        "entrypoint": _nonblank(entrypoint),
        "may_authorize": False,
    }
    digest = _self_hash(EXECUTOR_DESCRIPTOR_SCHEMA, body)
    return ExecutorDescriptor.model_validate(
        {
            **body,
            "descriptor_ref": f"executor-descriptor@sha256:{digest}",
            "descriptor_hash": digest,
        }
    )


class ExecutorRegistryProjection(_FrozenModel):
    """Frontier-bound support projection of exact executor implementations."""

    schema_id: Literal["hapax.executor-registry-projection.v1"] = Field(alias="schema")
    projection_ref: str
    projection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_host: str
    registry_source: ContentAddress
    event_frontier: ContentAddress
    descriptors: tuple[ContentAddress, ...] = Field(min_length=1)
    observed_at: str
    checked_at: str
    stale_after: str
    may_authorize: Literal[False]

    @field_validator("projection_ref", "execution_host")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("descriptors")
    @classmethod
    def validate_descriptors(
        cls,
        value: tuple[ContentAddress, ...],
    ) -> tuple[ContentAddress, ...]:
        return _content_address_set(value)

    @field_validator("observed_at", "checked_at", "stale_after")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        if not self.observed_at <= self.checked_at < self.stale_after:
            raise ValueError("executor registry projection timestamps are not usable")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"projection_ref", "projection_hash"},
        )
        expected = _self_hash(EXECUTOR_REGISTRY_PROJECTION_SCHEMA, body)
        if self.projection_hash != expected or self.projection_ref != (
            f"executor-registry-projection@sha256:{expected}"
        ):
            raise ValueError("executor registry projection reference/hash do not bind its body")
        return self


def build_executor_registry_projection(
    *,
    execution_host: str,
    registry_source: ContentAddress,
    event_frontier: ContentAddress,
    descriptors: Sequence[ExecutorDescriptor],
    observed_at: str | datetime,
    checked_at: str | datetime,
    stale_after: str | datetime,
) -> ExecutorRegistryProjection:
    checked_descriptors = tuple(
        sorted(
            (
                ExecutorDescriptor.model_validate(item.model_dump(mode="json", by_alias=True))
                for item in descriptors
            ),
            key=lambda item: (item.descriptor_ref, item.descriptor_hash),
        )
    )
    host = _nonblank(execution_host)
    if any(item.execution_host != host for item in checked_descriptors):
        raise ExecutionAdmissionError(
            "executor_registry_host_mismatch",
            "build one registry projection per exact execution host",
        )
    body: dict[str, object] = {
        "schema": EXECUTOR_REGISTRY_PROJECTION_SCHEMA,
        "execution_host": host,
        "registry_source": registry_source,
        "event_frontier": event_frontier,
        "descriptors": tuple(
            ContentAddress(ref=item.descriptor_ref, sha256=item.descriptor_hash)
            for item in checked_descriptors
        ),
        "observed_at": _canonical_timestamp(observed_at),
        "checked_at": _canonical_timestamp(checked_at),
        "stale_after": _canonical_timestamp(stale_after),
        "may_authorize": False,
    }
    digest = _self_hash(EXECUTOR_REGISTRY_PROJECTION_SCHEMA, body)
    return ExecutorRegistryProjection.model_validate(
        {
            **body,
            "projection_ref": f"executor-registry-projection@sha256:{digest}",
            "projection_hash": digest,
        }
    )


class ExecutionCurrentnessQuery(_FrozenModel):
    schema_id: Literal["hapax.execution-currentness-query.v2"] = Field(alias="schema")
    query_ref: str
    query_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_ref: str
    lane: str
    session_ref: str
    claim_epoch: int = Field(gt=0, strict=True)
    invocation_id: str
    attempt_fence: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str
    supersession_frontier_ref: str
    execution_lease: ContentAddress
    bound_execution_call: ContentAddress
    effect_manifest: ContentAddress
    executor_descriptor: ContentAddress
    executor_registry_projection: ContentAddress
    authority_trust_query: ContentAddress
    authority_trust_envelope: ContentAddress
    issuer_trust_query: ContentAddress
    issuer_trust_envelope: ContentAddress
    required_roots: tuple[ContentAddress, ...] = Field(min_length=1)
    historical_support_roots: tuple[ContentAddress, ...]
    queried_at: str
    may_authorize: Literal[False]

    @field_validator(
        "query_ref",
        "task_ref",
        "lane",
        "session_ref",
        "invocation_id",
        "idempotency_key",
        "supersession_frontier_ref",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("required_roots", "historical_support_roots")
    @classmethod
    def validate_roots(
        cls,
        value: tuple[ContentAddress, ...],
        info: Any,
    ) -> tuple[ContentAddress, ...]:
        return _content_address_set(
            value,
            allow_empty=info.field_name == "historical_support_roots",
        )

    @field_validator("queried_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_query(self) -> Self:
        anchors = {
            _content_address_key(item)
            for item in (
                self.execution_lease,
                self.bound_execution_call,
                self.effect_manifest,
                self.executor_descriptor,
                self.executor_registry_projection,
                self.authority_trust_query,
                self.authority_trust_envelope,
                self.issuer_trust_query,
                self.issuer_trust_envelope,
            )
        }
        required_roots = {_content_address_key(item) for item in self.required_roots}
        if not anchors.issubset(required_roots):
            raise ValueError("currentness query omits a load-bearing anchor")
        if required_roots.intersection(
            {_content_address_key(item) for item in self.historical_support_roots}
        ):
            raise ValueError("current and historical-support roots must be disjoint")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"query_ref", "query_hash"},
        )
        expected = _self_hash(EXECUTION_CURRENTNESS_QUERY_SCHEMA, body)
        if self.query_hash != expected or self.query_ref != (
            f"execution-currentness-query@sha256:{expected}"
        ):
            raise ValueError("currentness query reference/hash do not bind its body")
        return self


class ExecutionCurrentnessEnvelope(_FrozenModel):
    schema_id: Literal["hapax.execution-currentness-envelope.v2"] = Field(alias="schema")
    envelope_ref: str
    envelope_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    query: ContentAddress
    resolver: ContentAddress
    decision: Literal["current", "hold"]
    event_frontier: ContentAddress
    supersession_frontier_ref: str
    root_dispositions: tuple[RootDisposition, ...] = Field(min_length=1)
    historical_support_dispositions: tuple[HistoricalSupportDisposition, ...]
    idempotency_state: Literal["available", "completed", "in_progress", "conflicted", "unknown"]
    reason_codes: tuple[str, ...]
    repair_refs: tuple[str, ...]
    checked_at: str
    stale_after: str
    may_authorize: Literal[False]

    @field_validator("envelope_ref", "supersession_frontier_ref")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("reason_codes", "repair_refs")
    @classmethod
    def validate_sets(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _string_set(value, allow_empty=True)

    @field_validator("checked_at", "stale_after")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        roots = tuple(item.root for item in self.root_dispositions)
        if roots != tuple(sorted(roots, key=_content_address_key)) or len(
            {_content_address_key(item) for item in roots}
        ) != len(roots):
            raise ValueError("root dispositions must be sorted and unique")
        support_roots = tuple(item.root for item in self.historical_support_dispositions)
        if support_roots != tuple(sorted(support_roots, key=_content_address_key)) or len(
            {_content_address_key(item) for item in support_roots}
        ) != len(support_roots):
            raise ValueError("historical support dispositions must be sorted and unique")
        current = (
            all(item.disposition == "current" for item in self.root_dispositions)
            and all(item.disposition == "present" for item in self.historical_support_dispositions)
            and self.idempotency_state == "available"
            and not self.reason_codes
            and not self.repair_refs
            and self.checked_at < self.stale_after
        )
        if (self.decision == "current") != current:
            raise ValueError("currentness decision does not match root dispositions")
        if self.decision == "hold" and (
            not self.reason_codes
            or self.repair_refs != tuple(f"repair:{reason}" for reason in self.reason_codes)
        ):
            raise ValueError("held currentness requires exact reason/repair pairs")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"envelope_ref", "envelope_hash"},
        )
        expected = _self_hash(EXECUTION_CURRENTNESS_ENVELOPE_SCHEMA, body)
        if self.envelope_hash != expected or self.envelope_ref != (
            f"execution-currentness-envelope@sha256:{expected}"
        ):
            raise ValueError("currentness envelope reference/hash do not bind its body")
        return self


@dataclass(frozen=True)
class ExecutionCurrentnessResolver:
    """Data-only currentness projection catalog; an empty instance fails closed."""

    resolver: ContentAddress | None = None
    envelopes: tuple[ExecutionCurrentnessEnvelope, ...] = ()

    def __post_init__(self) -> None:
        if self.resolver is not None:
            _require_exact_type(
                self.resolver,
                ContentAddress,
                "execution currentness resolver descriptor",
            )
            object.__setattr__(
                self,
                "resolver",
                ContentAddress.model_validate(self.resolver.model_dump(mode="json")),
            )
        checked = tuple(
            ExecutionCurrentnessEnvelope.model_validate(
                _require_exact_type(
                    item,
                    ExecutionCurrentnessEnvelope,
                    "execution currentness envelope",
                ).model_dump(mode="json", by_alias=True)
            )
            for item in self.envelopes
        )
        keys = tuple((item.query.ref, item.query.sha256) for item in checked)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("currentness catalog must be sorted and query-unique")
        if self.resolver is not None and any(item.resolver != self.resolver for item in checked):
            raise ValueError("currentness catalog differs from its resolver descriptor")
        object.__setattr__(self, "envelopes", checked)

    def resolve(self, query: ExecutionCurrentnessQuery) -> ExecutionCurrentnessEnvelope:
        _require_exact_type(query, ExecutionCurrentnessQuery, "execution currentness query")
        checked_query = ExecutionCurrentnessQuery.model_validate(
            query.model_dump(mode="json", by_alias=True)
        )
        if self.resolver is None:
            raise ExecutionAdmissionError(
                "execution_currentness_resolver_unavailable",
                "install the accepted Spine-backed currentness projection before effects",
            )
        expected_query = ContentAddress(
            ref=checked_query.query_ref,
            sha256=checked_query.query_hash,
        )
        envelope = next(
            (item for item in self.envelopes if item.query == expected_query),
            None,
        )
        if envelope is None:
            raise ExecutionAdmissionError(
                "execution_currentness_projection_missing",
                "install the exact sealed currentness result for this query",
                checked_query.query_ref,
            )
        dispositions = tuple(item.root for item in envelope.root_dispositions)
        support_dispositions = tuple(item.root for item in envelope.historical_support_dispositions)
        reasons: list[str] = []
        if envelope.query != expected_query:
            reasons.append("currentness_query_mismatch")
        if envelope.resolver != self.resolver:
            reasons.append("currentness_resolver_mismatch")
        if dispositions != checked_query.required_roots:
            reasons.append("currentness_root_coverage_mismatch")
        if support_dispositions != checked_query.historical_support_roots:
            reasons.append("currentness_historical_support_coverage_mismatch")
        if envelope.supersession_frontier_ref != checked_query.supersession_frontier_ref:
            reasons.append("currentness_supersession_frontier_mismatch")
        if not envelope.checked_at <= checked_query.queried_at < envelope.stale_after:
            reasons.append("currentness_envelope_stale")
        if envelope.decision != "current":
            reasons.extend(envelope.reason_codes or ("currentness_held",))
        if reasons:
            raise ExecutionAdmissionError(
                "execution_currentness_not_current",
                "hold effects and refresh the exact Spine-backed currentness envelope",
                ",".join(sorted(set(reasons))),
            )
        return envelope


DEFAULT_EXECUTION_CURRENTNESS_RESOLVER = ExecutionCurrentnessResolver()


class ProtectedApertureDecision(_FrozenModel):
    """Pure classification of one exact ingress payload; never an authority grant."""

    schema_id: Literal["hapax.protected-aperture-decision.v1"] = Field(alias="schema")
    decision_ref: str
    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_invocation: ContentAddress
    disposition: Literal["protected", "unprotected", "hold"]
    aperture_id: (
        Literal[
            "hapax.non-operational-aperture.local-observation.v1",
            "hapax.non-operational-aperture.cognition-support-projection.v1",
            "hapax.non-operational-aperture.governance-intake-capture.v1",
        ]
        | None
    )
    surface: Literal[
        "source",
        "runtime",
        "connector",
        "launcher",
        "lifecycle",
        "intake",
        "probe",
    ]
    operation: str
    tool_name: str | None
    command: ContentAddress | None
    paths: tuple[str, ...]
    connector_name: str | None
    classifier_module: ContentAddress
    reason_codes: tuple[str, ...]
    repair_refs: tuple[str, ...]
    may_authorize: Literal[False]

    @field_validator("decision_ref", "operation")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("tool_name", "connector_name")
    @classmethod
    def validate_optional_string(cls, value: str | None) -> str | None:
        return None if value is None else _nonblank(value)

    @field_validator("paths")
    @classmethod
    def validate_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        checked = _string_set(value, allow_empty=True)
        if any(not Path(item).is_absolute() or str(Path(item)) != item for item in checked):
            raise ValueError("protected ingress paths must be normalized absolute paths")
        return checked

    @field_validator("reason_codes", "repair_refs")
    @classmethod
    def validate_reason_sets(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _string_set(value, allow_empty=True)

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        if self.disposition == "protected":
            if self.aperture_id is not None or self.reason_codes or self.repair_refs:
                raise ValueError("protected ingress cannot claim an aperture or refusal")
        elif self.disposition == "unprotected":
            if self.aperture_id is None or self.reason_codes or self.repair_refs:
                raise ValueError("unprotected ingress requires one exact named aperture")
        elif (
            self.aperture_id is not None
            or not self.reason_codes
            or self.repair_refs != tuple(f"repair:{item}" for item in self.reason_codes)
        ):
            raise ValueError("held ingress requires exact reason/repair pairs")
        if self.surface == "connector" and self.connector_name is None:
            raise ValueError("connector ingress requires an exact connector name")
        if self.surface != "connector" and self.connector_name is not None:
            raise ValueError("non-connector ingress cannot carry a connector name")
        if self.surface == "source" and not self.paths:
            raise ValueError("source ingress requires at least one exact path")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"decision_ref", "decision_hash"},
        )
        expected = _self_hash(PROTECTED_APERTURE_DECISION_SCHEMA, body)
        if self.decision_hash != expected or self.decision_ref != (
            f"protected-aperture-decision@sha256:{expected}"
        ):
            raise ValueError("protected aperture decision does not bind its body")
        return self


def build_protected_aperture_decision(
    *,
    raw_invocation: ContentAddress,
    disposition: Literal["protected", "unprotected", "hold"],
    aperture_id: Literal[
        "hapax.non-operational-aperture.local-observation.v1",
        "hapax.non-operational-aperture.cognition-support-projection.v1",
        "hapax.non-operational-aperture.governance-intake-capture.v1",
    ]
    | None,
    surface: Literal["source", "runtime", "connector", "launcher", "lifecycle", "intake", "probe"],
    operation: str,
    classifier_module: ContentAddress,
    tool_name: str | None = None,
    command: ContentAddress | None = None,
    paths: Sequence[str] = (),
    connector_name: str | None = None,
    reason_codes: Sequence[str] = (),
) -> ProtectedApertureDecision:
    reasons = tuple(sorted(set(reason_codes)))
    body: dict[str, object] = {
        "schema": PROTECTED_APERTURE_DECISION_SCHEMA,
        "raw_invocation": raw_invocation,
        "disposition": disposition,
        "aperture_id": aperture_id,
        "surface": surface,
        "operation": _nonblank(operation),
        "tool_name": None if tool_name is None else _nonblank(tool_name),
        "command": command,
        "paths": tuple(sorted(set(paths))),
        "connector_name": None if connector_name is None else _nonblank(connector_name),
        "classifier_module": classifier_module,
        "reason_codes": reasons,
        "repair_refs": tuple(f"repair:{item}" for item in reasons),
        "may_authorize": False,
    }
    digest = _self_hash(PROTECTED_APERTURE_DECISION_SCHEMA, body)
    return ProtectedApertureDecision.model_validate(
        {
            **body,
            "decision_ref": f"protected-aperture-decision@sha256:{digest}",
            "decision_hash": digest,
        }
    )


def protected_raw_invocation_address(
    value: Mapping[str, object] | Sequence[object],
) -> ContentAddress:
    """Hash exact structured ingress data without retaining prompt or secret bodies."""

    if isinstance(value, (str, bytes, bytearray)):
        raise ValueError("raw invocation must be a JSON object or array")
    digest = _payload_hash(value)
    return ContentAddress(
        ref=f"protected-raw-invocation@sha256:{digest}",
        sha256=digest,
    )


def module_file_address(path: Path) -> ContentAddress:
    """Address one FD-pinned, stable, owner-bound regular module file."""

    normalized = _normalized_path(path.expanduser())
    try:
        with ReadOnlyFsSnapshot(
            max_total_bytes=_MAX_BOUND_MODULE_BYTES,
            change_scope="observed_paths",
        ) as snapshot:
            parent = snapshot.pin_absolute_dir(normalized.parent, private_final=False)
            if parent is None:  # pragma: no cover - required directory
                raise AssertionError("module parent unexpectedly absent")
            observation = snapshot.observe_file_at(
                parent,
                normalized.name,
                private=False,
                max_bytes=_MAX_BOUND_MODULE_BYTES,
            )
            snapshot.seal()
    except (OSError, ReadOnlySnapshotError) as exc:
        raise ValueError("module identity requires stable owner-bound regular bytes") from exc
    if not observation.present or observation.captured is None:
        raise ValueError("module identity requires stable owner-bound regular bytes")
    digest = observation.captured.content_sha256
    return ContentAddress(ref=f"file:{normalized}@sha256:{digest}", sha256=digest)


def _private_file_is_absent(path: Path) -> bool:
    """Observe one private path as absent without a check/open race or atime write."""

    normalized = _normalized_path(path.expanduser())
    try:
        with ReadOnlyFsSnapshot(
            max_total_bytes=_MAX_EXECUTION_COMPOSITION_MANIFEST_BYTES,
            change_scope="observed_paths",
        ) as snapshot:
            parent = snapshot.pin_absolute_dir(
                normalized.parent,
                private_final=True,
                allow_missing=True,
            )
            if parent is None:
                snapshot.seal()
                return True
            observation = snapshot.observe_file_at(
                parent,
                normalized.name,
                private=True,
                max_bytes=_MAX_EXECUTION_COMPOSITION_MANIFEST_BYTES,
            )
            snapshot.seal()
    except (OSError, ReadOnlySnapshotError) as exc:
        raise ExecutionAdmissionError(
            "execution_composition_receipt_observation_unsafe",
            "restore the receipt root as one stable private observation boundary",
            str(normalized),
        ) from exc
    return not observation.present


class HistoricalProtectedClaimCoordinatesV1(_FrozenModel):
    """Historical coordinates retained for exact pre-convergence inspection."""

    schema_id: Literal["hapax.protected-claim-coordinates.v1"] = Field(alias="schema")
    coordinates_ref: str
    coordinates_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: Literal["prospective", "publication_bound", "applied"]
    task_ref: str
    lane: str
    session_ref: str
    claim_epoch: int = Field(gt=0, strict=True)
    claim_publication_intent: ContentAddress
    admitted_claim: ContentAddress | None
    may_authorize: Literal[False]

    @field_validator("coordinates_ref", "task_ref", "lane", "session_ref")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @model_validator(mode="after")
    def validate_coordinates(self) -> Self:
        if (self.state == "applied") != (self.admitted_claim is not None):
            raise ValueError("only applied claim coordinates carry an admitted claim")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"coordinates_ref", "coordinates_hash"},
        )
        expected = _self_hash(HISTORICAL_PROTECTED_CLAIM_COORDINATES_SCHEMA, body)
        if self.coordinates_hash != expected or self.coordinates_ref != (
            f"protected-claim-coordinates@sha256:{expected}"
        ):
            raise ValueError("protected claim coordinates do not bind their body")
        return self


class ProspectiveClaimPublicationBasis(_FrozenModel):
    """Path-independent pre-publication facts; evidence only, never authority."""

    schema_id: Literal["hapax.prospective-claim-publication-basis.v1"] = Field(alias="schema")
    basis_ref: str
    basis_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_publication_intent: ContentAddress
    task_ref: str
    lane: str
    session_ref: str
    claim_epoch: int = Field(gt=0, strict=True)
    authority_case: str
    dispatch_message_id: str
    dispatch_binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dispatch_binding_receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    coord_dispatch_idempotency_key: str
    claim_mode: Literal["claim", "resume"]
    from_status: str
    to_status: str
    task_note_before_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_note_after_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_note_mode: int = Field(ge=0, le=0o777, strict=True)
    mutation_scope_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    may_authorize: Literal[False]

    @field_validator(
        "basis_ref",
        "task_ref",
        "lane",
        "session_ref",
        "authority_case",
        "dispatch_message_id",
        "coord_dispatch_idempotency_key",
        "from_status",
        "to_status",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @model_validator(mode="after")
    def validate_basis(self) -> Self:
        if self.claim_publication_intent.ref != (
            f"claim-publication-intent@sha256:{self.claim_publication_intent.sha256}"
        ):
            raise ValueError("prospective basis requires a canonical publication intent")
        if self.task_note_before_sha256 == self.task_note_after_sha256:
            raise ValueError("prospective basis requires a distinct task-note postimage")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"basis_ref", "basis_hash"},
        )
        expected = _self_hash(PROSPECTIVE_CLAIM_PUBLICATION_BASIS_SCHEMA, body)
        if self.basis_hash != expected or self.basis_ref != (
            f"prospective-claim-publication-basis@sha256:{expected}"
        ):
            raise ValueError("prospective claim basis reference/hash do not bind its body")
        return self


def build_prospective_claim_publication_basis(
    *,
    claim_publication_intent: ContentAddress,
    task_ref: str,
    lane: str,
    session_ref: str,
    claim_epoch: int,
    authority_case: str,
    dispatch_message_id: str,
    dispatch_binding_hash: str,
    dispatch_binding_receipt_hash: str,
    coord_dispatch_idempotency_key: str,
    claim_mode: Literal["claim", "resume"],
    from_status: str,
    to_status: str,
    task_note_before_sha256: str,
    task_note_after_sha256: str,
    task_note_mode: int,
    mutation_scope_hash: str,
) -> ProspectiveClaimPublicationBasis:
    body: dict[str, object] = {
        "schema": PROSPECTIVE_CLAIM_PUBLICATION_BASIS_SCHEMA,
        "claim_publication_intent": claim_publication_intent,
        "task_ref": _nonblank(task_ref),
        "lane": _nonblank(lane),
        "session_ref": _nonblank(session_ref),
        "claim_epoch": claim_epoch,
        "authority_case": _nonblank(authority_case),
        "dispatch_message_id": _nonblank(dispatch_message_id),
        "dispatch_binding_hash": dispatch_binding_hash,
        "dispatch_binding_receipt_hash": dispatch_binding_receipt_hash,
        "coord_dispatch_idempotency_key": _nonblank(coord_dispatch_idempotency_key),
        "claim_mode": claim_mode,
        "from_status": _nonblank(from_status),
        "to_status": _nonblank(to_status),
        "task_note_before_sha256": task_note_before_sha256,
        "task_note_after_sha256": task_note_after_sha256,
        "task_note_mode": task_note_mode,
        "mutation_scope_hash": mutation_scope_hash,
        "may_authorize": False,
    }
    digest = _self_hash(PROSPECTIVE_CLAIM_PUBLICATION_BASIS_SCHEMA, body)
    return ProspectiveClaimPublicationBasis.model_validate(
        {
            **body,
            "basis_ref": f"prospective-claim-publication-basis@sha256:{digest}",
            "basis_hash": digest,
        }
    )


class ProspectiveClaimPublicationCarrier(_FrozenModel):
    """Path-free reconstruction bytes for a prospective publication basis."""

    schema_id: Literal["hapax.prospective-claim-publication-carrier.v1"] = Field(alias="schema")
    carrier_ref: str
    carrier_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    basis: ProspectiveClaimPublicationBasis
    note_after: str
    may_authorize: Literal[False]

    @field_validator("carrier_ref")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @model_validator(mode="after")
    def validate_carrier(self) -> Self:
        try:
            note_bytes = self.note_after.encode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise ValueError("prospective task-note postimage must be UTF-8") from exc
        if _sha256(note_bytes) != self.basis.task_note_after_sha256:
            raise ValueError("prospective carrier postimage differs from its basis")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"carrier_ref", "carrier_hash"},
        )
        expected = _self_hash(PROSPECTIVE_CLAIM_PUBLICATION_CARRIER_SCHEMA, body)
        if self.carrier_hash != expected or self.carrier_ref != (
            f"prospective-claim-publication-carrier@sha256:{expected}"
        ):
            raise ValueError("prospective claim carrier reference/hash do not bind its body")
        return self


def build_prospective_claim_publication_carrier(
    basis: ProspectiveClaimPublicationBasis,
    *,
    note_after: bytes,
) -> ProspectiveClaimPublicationCarrier:
    checked_basis = ProspectiveClaimPublicationBasis.model_validate(
        basis.model_dump(mode="json", by_alias=True)
    )
    try:
        note_text = note_after.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ValueError("prospective task-note postimage must be UTF-8") from exc
    body: dict[str, object] = {
        "schema": PROSPECTIVE_CLAIM_PUBLICATION_CARRIER_SCHEMA,
        "basis": checked_basis,
        "note_after": note_text,
        "may_authorize": False,
    }
    digest = _self_hash(PROSPECTIVE_CLAIM_PUBLICATION_CARRIER_SCHEMA, body)
    return ProspectiveClaimPublicationCarrier.model_validate(
        {
            **body,
            "carrier_ref": f"prospective-claim-publication-carrier@sha256:{digest}",
            "carrier_hash": digest,
        }
    )


class ProtectedClaimCoordinates(_FrozenModel):
    """Active coordinates bind exactly one prospective or applied claim basis."""

    schema_id: Literal["hapax.protected-claim-coordinates.v2"] = Field(alias="schema")
    coordinates_ref: str
    coordinates_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: Literal["prospective", "applied"]
    task_ref: str
    lane: str
    session_ref: str
    claim_epoch: int = Field(gt=0, strict=True)
    claim_publication_intent: ContentAddress
    claim_basis: ContentAddress
    may_authorize: Literal[False]

    @field_validator("coordinates_ref", "task_ref", "lane", "session_ref")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @model_validator(mode="after")
    def validate_coordinates(self) -> Self:
        expected_prefix = (
            "prospective-claim-publication-basis"
            if self.state == "prospective"
            else "applied-claim-ownership"
        )
        if self.claim_basis.ref != f"{expected_prefix}@sha256:{self.claim_basis.sha256}":
            raise ValueError("claim coordinate state differs from its typed basis")
        if self.claim_publication_intent.ref != (
            f"claim-publication-intent@sha256:{self.claim_publication_intent.sha256}"
        ):
            raise ValueError("claim coordinates require a canonical publication intent")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"coordinates_ref", "coordinates_hash"},
        )
        expected = _self_hash(PROTECTED_CLAIM_COORDINATES_SCHEMA, body)
        if self.coordinates_hash != expected or self.coordinates_ref != (
            f"protected-claim-coordinates@sha256:{expected}"
        ):
            raise ValueError("protected claim coordinates do not bind their body")
        return self


def build_protected_claim_coordinates(
    *,
    state: Literal["prospective", "applied"],
    task_ref: str,
    lane: str,
    session_ref: str,
    claim_epoch: int,
    claim_publication_intent: ContentAddress,
    claim_basis: ContentAddress,
) -> ProtectedClaimCoordinates:
    body: dict[str, object] = {
        "schema": PROTECTED_CLAIM_COORDINATES_SCHEMA,
        "state": state,
        "task_ref": _nonblank(task_ref),
        "lane": _nonblank(lane),
        "session_ref": _nonblank(session_ref),
        "claim_epoch": claim_epoch,
        "claim_publication_intent": claim_publication_intent,
        "claim_basis": claim_basis,
        "may_authorize": False,
    }
    digest = _self_hash(PROTECTED_CLAIM_COORDINATES_SCHEMA, body)
    return ProtectedClaimCoordinates.model_validate(
        {
            **body,
            "coordinates_ref": f"protected-claim-coordinates@sha256:{digest}",
            "coordinates_hash": digest,
        }
    )


class ProtectedActionRequest(_FrozenModel):
    """Self-hashed ingress request whose roots must be consumed by ActionIntent."""

    schema_id: Literal["hapax.protected-action-request.v1"] = Field(alias="schema")
    request_ref: str
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_invocation: ContentAddress
    aperture_decision: ContentAddress
    operation: str
    ingress_surface: str
    platform: str
    mode: str
    profile: str
    execution_host: str
    runtime_identity: ContentAddress
    ingress_module: ContentAddress
    admission_module: ContentAddress
    claim_coordinates: ContentAddress
    task_ref: str
    lane: str
    session_ref: str
    claim_epoch: int = Field(gt=0, strict=True)
    claim_mode: str
    effect_manifest: ContentAddress
    active_generation_roots: tuple[ContentAddress, ...] = Field(min_length=1)
    requested_effect_targets: tuple[ContentAddress, ...]
    requested_scope_refs: tuple[str, ...]
    supersession_frontier_ref: str
    required_roots: tuple[ContentAddress, ...] = Field(min_length=1)
    requested_at: str
    mutating: bool = Field(strict=True)
    may_authorize: Literal[False]
    authorizes_direct_fallthrough: Literal[False]

    @field_validator(
        "request_ref",
        "operation",
        "ingress_surface",
        "platform",
        "mode",
        "profile",
        "execution_host",
        "task_ref",
        "lane",
        "session_ref",
        "claim_mode",
        "supersession_frontier_ref",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("requested_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @field_validator(
        "active_generation_roots",
        "requested_effect_targets",
        "required_roots",
    )
    @classmethod
    def validate_address_sets(
        cls,
        value: tuple[ContentAddress, ...],
        info: Any,
    ) -> tuple[ContentAddress, ...]:
        return _content_address_set(
            value,
            allow_empty=info.field_name == "requested_effect_targets",
        )

    @field_validator("requested_scope_refs")
    @classmethod
    def validate_scope(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _string_set(value, allow_empty=True)

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        if self.mutating and not self.requested_scope_refs:
            raise ValueError("mutating protected requests require exact scope")
        if (
            self.ingress_module not in self.active_generation_roots
            or self.admission_module not in self.active_generation_roots
        ):
            raise ValueError("active generation roots must include both executing modules")
        expected_roots = tuple(
            sorted(
                {
                    _content_address_key(item): item
                    for item in (
                        self.raw_invocation,
                        self.aperture_decision,
                        self.runtime_identity,
                        self.ingress_module,
                        self.admission_module,
                        self.claim_coordinates,
                        self.effect_manifest,
                        *self.active_generation_roots,
                        *self.requested_effect_targets,
                    )
                }.values(),
                key=_content_address_key,
            )
        )
        if self.required_roots != expected_roots:
            raise ValueError("protected request roots must exactly cover every bound input")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"request_ref", "request_hash"},
        )
        expected = _self_hash(PROTECTED_ACTION_REQUEST_SCHEMA, body)
        if self.request_hash != expected or self.request_ref != (
            f"protected-action-request@sha256:{expected}"
        ):
            raise ValueError("protected action request does not bind its body")
        return self


def build_protected_action_request(
    aperture: ProtectedApertureDecision,
    claim: ProtectedClaimCoordinates,
    *,
    platform: str,
    mode: str,
    profile: str,
    execution_host: str,
    runtime_identity: ContentAddress,
    ingress_module: ContentAddress,
    admission_module: ContentAddress,
    claim_mode: str,
    effect_manifest: ContentAddress,
    active_generation_roots: Sequence[ContentAddress],
    requested_effect_targets: Sequence[ContentAddress],
    requested_scope_refs: Sequence[str],
    supersession_frontier_ref: str,
    requested_at: str | datetime,
    mutating: bool,
) -> ProtectedActionRequest:
    checked_aperture = ProtectedApertureDecision.model_validate(
        aperture.model_dump(mode="json", by_alias=True)
    )
    checked_claim = ProtectedClaimCoordinates.model_validate(
        claim.model_dump(mode="json", by_alias=True)
    )
    if checked_aperture.disposition != "protected":
        raise ExecutionAdmissionError(
            "protected_action_aperture_not_protected",
            "route only protected ingress through the execution pipeline",
            checked_aperture.disposition,
        )
    if checked_claim.state == "prospective" and checked_aperture.operation != "claim.publish":
        raise ExecutionAdmissionError(
            "prospective_claim_operation_forbidden",
            "use prospective claim coordinates only for exact claim publication",
            checked_aperture.operation,
        )
    if checked_claim.state == "applied" and checked_aperture.operation == "claim.publish":
        raise ExecutionAdmissionError(
            "applied_claim_publication_reentry_forbidden",
            "publish from prospective coordinates or reconcile the existing receipt",
            checked_claim.claim_basis.ref,
        )
    generations = tuple(
        sorted(
            {
                _content_address_key(item): item
                for item in (*active_generation_roots, ingress_module, admission_module)
            }.values(),
            key=_content_address_key,
        )
    )
    targets = tuple(
        sorted(
            {_content_address_key(item): item for item in requested_effect_targets}.values(),
            key=_content_address_key,
        )
    )
    aperture_address = ContentAddress(
        ref=checked_aperture.decision_ref,
        sha256=checked_aperture.decision_hash,
    )
    claim_address = ContentAddress(
        ref=checked_claim.coordinates_ref,
        sha256=checked_claim.coordinates_hash,
    )
    roots = tuple(
        sorted(
            {
                _content_address_key(item): item
                for item in (
                    checked_aperture.raw_invocation,
                    aperture_address,
                    runtime_identity,
                    ingress_module,
                    admission_module,
                    claim_address,
                    effect_manifest,
                    *generations,
                    *targets,
                )
            }.values(),
            key=_content_address_key,
        )
    )
    body: dict[str, object] = {
        "schema": PROTECTED_ACTION_REQUEST_SCHEMA,
        "raw_invocation": checked_aperture.raw_invocation,
        "aperture_decision": aperture_address,
        "operation": checked_aperture.operation,
        "ingress_surface": checked_aperture.surface,
        "platform": _nonblank(platform),
        "mode": _nonblank(mode),
        "profile": _nonblank(profile),
        "execution_host": _nonblank(execution_host),
        "runtime_identity": runtime_identity,
        "ingress_module": ingress_module,
        "admission_module": admission_module,
        "claim_coordinates": claim_address,
        "task_ref": checked_claim.task_ref,
        "lane": checked_claim.lane,
        "session_ref": checked_claim.session_ref,
        "claim_epoch": checked_claim.claim_epoch,
        "claim_mode": _nonblank(claim_mode),
        "effect_manifest": effect_manifest,
        "active_generation_roots": generations,
        "requested_effect_targets": targets,
        "requested_scope_refs": tuple(sorted(set(requested_scope_refs))),
        "supersession_frontier_ref": _nonblank(supersession_frontier_ref),
        "required_roots": roots,
        "requested_at": _canonical_timestamp(requested_at),
        "mutating": mutating,
        "may_authorize": False,
        "authorizes_direct_fallthrough": False,
    }
    digest = _self_hash(PROTECTED_ACTION_REQUEST_SCHEMA, body)
    return ProtectedActionRequest.model_validate(
        {
            **body,
            "request_ref": f"protected-action-request@sha256:{digest}",
            "request_hash": digest,
        }
    )


class HistoricalExecutionInvocationEnvelopeV1(_FrozenModel):
    """Historical admitted-claim invocation projection for exact inspection."""

    schema_id: Literal["hapax.execution-invocation-envelope.v1"] = Field(alias="schema")
    envelope_ref: str
    envelope_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    protected_action_request: ContentAddress
    execution_lease: ContentAddress
    execution_admission: ContentAddress
    action_intent: ContentAddress
    authority_grant: ContentAddress
    admitted_claim: ContentAddress
    context_frame: ContentAddress
    epistemic_trace: ContentAddress
    execution_target: ContentAddress
    route_decision: ContentAddress
    effect_manifest: ContentAddress
    executor_descriptor: ContentAddress
    executor_registry_projection: ContentAddress
    may_authorize: Literal[False]

    @field_validator("envelope_ref")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"envelope_ref", "envelope_hash"},
        )
        expected = _self_hash(HISTORICAL_EXECUTION_INVOCATION_ENVELOPE_SCHEMA, body)
        if self.envelope_hash != expected or self.envelope_ref != (
            f"execution-invocation-envelope@sha256:{expected}"
        ):
            raise ValueError("execution invocation envelope does not bind its body")
        return self


class ExecutionInvocationEnvelope(_FrozenModel):
    """Current content-addressed projection of every active invocation root."""

    schema_id: Literal["hapax.execution-invocation-envelope.v2"] = Field(alias="schema")
    envelope_ref: str
    envelope_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    protected_action_request: ContentAddress
    execution_lease: ContentAddress
    bound_execution_call: ContentAddress
    execution_admission: ContentAddress
    action_intent: ContentAddress
    authority_grant: ContentAddress
    claim_coordinates: ContentAddress
    claim_basis: ContentAddress
    task_note: ContentAddress
    context_frame: ContentAddress
    epistemic_trace: ContentAddress
    execution_target: ContentAddress
    route_decision: ContentAddress
    effect_manifest: ContentAddress
    executor_descriptor: ContentAddress
    executor_registry_projection: ContentAddress
    may_authorize: Literal[False]

    @field_validator("envelope_ref")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"envelope_ref", "envelope_hash"},
        )
        expected = _self_hash(EXECUTION_INVOCATION_ENVELOPE_SCHEMA, body)
        if self.envelope_hash != expected or self.envelope_ref != (
            f"execution-invocation-envelope@sha256:{expected}"
        ):
            raise ValueError("execution invocation envelope does not bind its body")
        return self


class ProtectedActionHold(_FrozenModel):
    """Canonical transport HOLD when no complete protected request can be resolved."""

    schema_id: Literal["hapax.protected-action-hold.v1"] = Field(alias="schema")
    hold_ref: str
    hold_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_invocation: ContentAddress
    operation: str
    ingress_surface: str
    ingress_module: ContentAddress | None
    admission_module: ContentAddress
    checked_at: str
    reason_codes: tuple[str, ...] = Field(min_length=1)
    repair_refs: tuple[str, ...] = Field(min_length=1)
    may_authorize: Literal[False]
    authorizes_direct_fallthrough: Literal[False]

    @field_validator("hold_ref", "operation", "ingress_surface")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("checked_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @field_validator("reason_codes", "repair_refs")
    @classmethod
    def validate_sets(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _string_set(value)

    @model_validator(mode="after")
    def validate_hold(self) -> Self:
        if self.repair_refs != tuple(f"repair:{item}" for item in self.reason_codes):
            raise ValueError("protected action HOLD requires exact reason/repair pairs")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"hold_ref", "hold_hash"},
        )
        expected = _self_hash(PROTECTED_ACTION_HOLD_SCHEMA, body)
        if self.hold_hash != expected or self.hold_ref != (
            f"protected-action-hold@sha256:{expected}"
        ):
            raise ValueError("protected action HOLD does not bind its body")
        return self


def build_protected_action_hold(
    *,
    raw_invocation: ContentAddress,
    operation: str,
    ingress_surface: str,
    ingress_module: ContentAddress | None,
    admission_module: ContentAddress,
    checked_at: str | datetime,
    reason_codes: Sequence[str],
) -> ProtectedActionHold:
    reasons = tuple(sorted(set(reason_codes)))
    body: dict[str, object] = {
        "schema": PROTECTED_ACTION_HOLD_SCHEMA,
        "raw_invocation": raw_invocation,
        "operation": _nonblank(operation),
        "ingress_surface": _nonblank(ingress_surface),
        "ingress_module": ingress_module,
        "admission_module": admission_module,
        "checked_at": _canonical_timestamp(checked_at),
        "reason_codes": reasons,
        "repair_refs": tuple(f"repair:{item}" for item in reasons),
        "may_authorize": False,
        "authorizes_direct_fallthrough": False,
    }
    digest = _self_hash(PROTECTED_ACTION_HOLD_SCHEMA, body)
    return ProtectedActionHold.model_validate(
        {
            **body,
            "hold_ref": f"protected-action-hold@sha256:{digest}",
            "hold_hash": digest,
        }
    )


class ProtectedActionDecision(_FrozenModel):
    """Non-authorizing evaluation result; success means dispatch, never fallthrough."""

    schema_id: Literal["hapax.protected-action-decision.v1"] = Field(alias="schema")
    decision_ref: str
    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    request: ContentAddress
    invocation_envelope: ContentAddress | None
    disposition: Literal["hold", "dispatch_to_executor"]
    currentness_query: ContentAddress | None
    currentness_envelope: ContentAddress | None
    outcome_readiness_query: ContentAddress | None
    outcome_readiness_envelope: ContentAddress | None
    executor_descriptor: ContentAddress | None
    checked_at: str
    reason_codes: tuple[str, ...]
    repair_refs: tuple[str, ...]
    may_authorize: Literal[False]
    authorizes_direct_fallthrough: Literal[False]

    @field_validator("decision_ref")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("checked_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @field_validator("reason_codes", "repair_refs")
    @classmethod
    def validate_sets(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _string_set(value, allow_empty=True)

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        dispatch_fields = (
            self.invocation_envelope,
            self.currentness_query,
            self.currentness_envelope,
            self.outcome_readiness_query,
            self.outcome_readiness_envelope,
            self.executor_descriptor,
        )
        if self.disposition == "dispatch_to_executor":
            if (
                any(item is None for item in dispatch_fields)
                or self.reason_codes
                or self.repair_refs
            ):
                raise ValueError("executor dispatch requires every proof and no refusal")
        elif (
            any(item is not None for item in dispatch_fields)
            or not self.reason_codes
            or self.repair_refs != tuple(f"repair:{item}" for item in self.reason_codes)
        ):
            raise ValueError("held protected actions require only reason/repair pairs")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"decision_ref", "decision_hash"},
        )
        expected = _self_hash(PROTECTED_ACTION_DECISION_SCHEMA, body)
        if self.decision_hash != expected or self.decision_ref != (
            f"protected-action-decision@sha256:{expected}"
        ):
            raise ValueError("protected action decision does not bind its body")
        return self


class ActionIntent(_FrozenModel):
    schema_id: Literal["hapax.action-intent.v1"] = Field(alias="schema")
    intent_ref: str
    intent_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_ref: str
    position_ref: str
    position_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    action_id: str
    action_class: str
    operation: str
    capability_role: str
    execution_host: str
    acting_subject: ContentAddress
    protected_action_request: ContentAddress
    effect_manifest: ContentAddress
    requested_effect_targets: tuple[ContentAddress, ...]
    parent_spec: ContentAddress
    decomposition: ContentAddress
    requested_scope_refs: tuple[str, ...]
    required_authorization_flags: tuple[str, ...] = Field(min_length=1)
    lifecycle_admission_ref: str | None
    lifecycle_transition_to: str | None
    lifecycle_transition_edge: Literal["next", "fall"] | None
    mutating: bool = Field(strict=True)
    may_authorize: Literal[False]

    @field_validator(
        "intent_ref",
        "task_ref",
        "position_ref",
        "action_id",
        "action_class",
        "operation",
        "capability_role",
        "execution_host",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("requested_scope_refs", "required_authorization_flags")
    @classmethod
    def validate_sets(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _string_set(value, allow_empty=info.field_name == "requested_scope_refs")

    @field_validator("requested_effect_targets")
    @classmethod
    def validate_effect_targets(
        cls,
        value: tuple[ContentAddress, ...],
    ) -> tuple[ContentAddress, ...]:
        return _content_address_set(value, allow_empty=True)

    @field_validator(
        "lifecycle_admission_ref",
        "lifecycle_transition_to",
    )
    @classmethod
    def validate_optional_string(cls, value: str | None) -> str | None:
        return None if value is None else _nonblank(value)

    @model_validator(mode="after")
    def validate_intent(self) -> Self:
        if self.mutating and not self.requested_scope_refs:
            raise ValueError("mutating action intents require an immutable scope")
        if self.action_class == "lifecycle_operation":
            if (
                self.lifecycle_admission_ref is None
                or self.lifecycle_transition_to is not None
                or self.lifecycle_transition_edge is not None
            ):
                raise ValueError("lifecycle operations require only an admission ref")
        elif self.action_class == "lifecycle_transition":
            if (
                self.operation != "lifecycle.transition"
                or self.lifecycle_admission_ref is None
                or self.lifecycle_transition_to is None
                or self.lifecycle_transition_edge is None
            ):
                raise ValueError("lifecycle transitions require admission, edge, and target")
        elif any(
            item is not None
            for item in (
                self.lifecycle_admission_ref,
                self.lifecycle_transition_to,
                self.lifecycle_transition_edge,
            )
        ):
            raise ValueError("non-lifecycle intents cannot carry lifecycle bindings")
        body = self.model_dump(mode="json", by_alias=True, exclude={"intent_ref", "intent_hash"})
        expected = _self_hash(ACTION_INTENT_SCHEMA, body)
        if self.intent_hash != expected or self.intent_ref != f"action-intent@sha256:{expected}":
            raise ValueError("intent reference/hash do not bind the action intent")
        return self


def build_action_intent(
    position: ContextPosition,
    *,
    action_id: str,
    action_class: str,
    operation: str,
    capability_role: str,
    execution_host: str,
    acting_subject: ContentAddress,
    protected_action_request: ContentAddress,
    effect_manifest: EffectManifest,
    requested_effect_targets: Sequence[ContentAddress],
    parent_spec: ContentAddress,
    decomposition: ContentAddress,
    requested_scope_refs: Sequence[str],
    mutating: bool,
    lifecycle_admission_ref: str | None = None,
    lifecycle_transition_to: str | None = None,
    lifecycle_transition_edge: Literal["next", "fall"] | None = None,
) -> ActionIntent:
    checked_manifest = EffectManifest.model_validate(
        effect_manifest.model_dump(mode="json", by_alias=True)
    )
    scope = tuple(sorted(set(requested_scope_refs)))
    targets = tuple(
        sorted(
            {_content_address_key(item): item for item in requested_effect_targets}.values(),
            key=_content_address_key,
        )
    )
    required_authorization_flags = tuple(
        item.name for item in position.authorized_flags if item.authorized
    )
    if (
        checked_manifest.operation != operation
        or checked_manifest.capability_role != capability_role
        or checked_manifest.execution_host != execution_host
        or checked_manifest.mutating != mutating
        or checked_manifest.scope_refs != scope
        or checked_manifest.effect_targets != targets
    ):
        raise ExecutionAdmissionError(
            "action_intent_effect_manifest_mismatch",
            "build the intent from one manifest with the same operation, role, host, and scope",
        )
    body: dict[str, object] = {
        "schema": ACTION_INTENT_SCHEMA,
        "task_ref": position.task_ref,
        "position_ref": position.position_ref,
        "position_hash": position.position_hash,
        "action_id": _nonblank(action_id),
        "action_class": _nonblank(action_class),
        "operation": _nonblank(operation),
        "capability_role": _nonblank(capability_role),
        "execution_host": _nonblank(execution_host),
        "acting_subject": acting_subject,
        "protected_action_request": protected_action_request,
        "effect_manifest": ContentAddress(
            ref=checked_manifest.manifest_ref,
            sha256=checked_manifest.manifest_hash,
        ),
        "requested_effect_targets": targets,
        "parent_spec": parent_spec,
        "decomposition": decomposition,
        "requested_scope_refs": scope,
        "required_authorization_flags": tuple(sorted(set(required_authorization_flags))),
        "lifecycle_admission_ref": lifecycle_admission_ref,
        "lifecycle_transition_to": lifecycle_transition_to,
        "lifecycle_transition_edge": lifecycle_transition_edge,
        "mutating": mutating,
        "may_authorize": False,
    }
    digest = _self_hash(ACTION_INTENT_SCHEMA, body)
    return ActionIntent.model_validate(
        {**body, "intent_ref": f"action-intent@sha256:{digest}", "intent_hash": digest}
    )


class AuthorityEvidence(_FrozenModel):
    """Authenticated evidence for authority that already exists outside this evaluator."""

    schema_id: Literal["hapax.authority-evidence.v1"] = Field(alias="schema")
    evidence_ref: str
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    authority_source: ContentAddress
    authenticated_receipt: ContentAddress
    issuer: ContentAddress
    subject: ContentAddress
    authority_case: str
    authority_ceiling: str
    authorized_action_classes: tuple[str, ...] = Field(min_length=1)
    authorized_operations: tuple[str, ...] = Field(min_length=1)
    authorized_flags: tuple[str, ...] = Field(min_length=1)
    scope_refs: tuple[str, ...]
    not_before: str
    valid_until: str
    supersession_frontier_ref: str
    revoked_by_refs: tuple[str, ...]
    may_mint_sovereign_act: Literal[False]
    authorizes_operator: Literal[False]

    @field_validator(
        "evidence_ref",
        "authority_case",
        "authority_ceiling",
        "supersession_frontier_ref",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator(
        "authorized_action_classes",
        "authorized_operations",
        "authorized_flags",
        "scope_refs",
        "revoked_by_refs",
    )
    @classmethod
    def validate_sets(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _string_set(value, allow_empty=info.field_name in {"scope_refs", "revoked_by_refs"})

    @field_validator("not_before", "valid_until")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if self.not_before >= self.valid_until:
            raise ValueError("authority evidence requires a non-empty validity interval")
        body = self.model_dump(
            mode="json", by_alias=True, exclude={"evidence_ref", "evidence_hash"}
        )
        expected = _self_hash(AUTHORITY_EVIDENCE_SCHEMA, body)
        if (
            self.evidence_hash != expected
            or self.evidence_ref != f"authority-evidence@sha256:{expected}"
        ):
            raise ValueError("authority evidence reference/hash do not bind its body")
        return self


def build_authority_evidence(
    *,
    authority_source: ContentAddress,
    authenticated_receipt: ContentAddress,
    issuer: ContentAddress,
    subject: ContentAddress,
    authority_case: str,
    authority_ceiling: str,
    authorized_action_classes: Sequence[str],
    authorized_operations: Sequence[str],
    authorized_flags: Sequence[str],
    scope_refs: Sequence[str],
    not_before: str | datetime,
    valid_until: str | datetime,
    supersession_frontier_ref: str,
    revoked_by_refs: Sequence[str] = (),
) -> AuthorityEvidence:
    body: dict[str, object] = {
        "schema": AUTHORITY_EVIDENCE_SCHEMA,
        "authority_source": authority_source,
        "authenticated_receipt": authenticated_receipt,
        "issuer": issuer,
        "subject": subject,
        "authority_case": _nonblank(authority_case),
        "authority_ceiling": _nonblank(authority_ceiling),
        "authorized_action_classes": tuple(sorted(set(authorized_action_classes))),
        "authorized_operations": tuple(sorted(set(authorized_operations))),
        "authorized_flags": tuple(sorted(set(authorized_flags))),
        "scope_refs": tuple(sorted(set(scope_refs))),
        "not_before": _canonical_timestamp(not_before),
        "valid_until": _canonical_timestamp(valid_until),
        "supersession_frontier_ref": _nonblank(supersession_frontier_ref),
        "revoked_by_refs": tuple(sorted(set(revoked_by_refs))),
        "may_mint_sovereign_act": False,
        "authorizes_operator": False,
    }
    digest = _self_hash(AUTHORITY_EVIDENCE_SCHEMA, body)
    return AuthorityEvidence.model_validate(
        {
            **body,
            "evidence_ref": f"authority-evidence@sha256:{digest}",
            "evidence_hash": digest,
        }
    )


class ValidAuthorityGrant(_FrozenModel):
    schema_id: Literal["hapax.valid-authority-grant.v1"] = Field(alias="schema")
    grant_ref: str
    grant_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    intent_ref: str
    intent_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_ref: str
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    authority_source: ContentAddress
    authenticated_receipt: ContentAddress
    authority_issuer: ContentAddress
    acting_subject: ContentAddress
    authority_trust_query: ExecutionTrustQuery
    authority_trust_envelope: ExecutionTrustEnvelope
    position_ref: str
    position_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_ref: str
    authority_case: str
    authority_ceiling: str
    action_class: str
    operation: str
    authorized_flags: tuple[str, ...] = Field(min_length=1)
    scope_refs: tuple[str, ...]
    issued_at: str
    valid_until: str
    supersession_frontier_ref: str
    validation_method_ref: str
    authorizes_machine_admission: Literal[True]
    authorizes_operator: Literal[False]
    may_mint_sovereign_act: Literal[False]

    @field_validator(
        "grant_ref",
        "intent_ref",
        "evidence_ref",
        "position_ref",
        "task_ref",
        "authority_case",
        "authority_ceiling",
        "action_class",
        "operation",
        "supersession_frontier_ref",
        "validation_method_ref",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("authorized_flags", "scope_refs")
    @classmethod
    def validate_sets(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _string_set(value, allow_empty=info.field_name == "scope_refs")

    @field_validator("issued_at", "valid_until")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_grant(self) -> Self:
        if self.issued_at >= self.valid_until:
            raise ValueError("valid authority grant requires a future validity horizon")
        expected_query = ContentAddress(
            ref=self.authority_trust_query.query_ref,
            sha256=self.authority_trust_query.query_hash,
        )
        expected_subjects = tuple(
            sorted(
                {
                    _content_address_key(item): item
                    for item in (
                        ContentAddress(ref=self.intent_ref, sha256=self.intent_hash),
                        ContentAddress(ref=self.evidence_ref, sha256=self.evidence_hash),
                        ContentAddress(ref=self.position_ref, sha256=self.position_hash),
                        self.authority_source,
                        self.authority_issuer,
                        self.acting_subject,
                    )
                }.values(),
                key=_content_address_key,
            )
        )
        if (
            self.authority_trust_query.trust_class != "authenticated_authority_receipt"
            or self.authority_trust_query.subject_roots != expected_subjects
            or self.authority_trust_query.presented_receipt != self.authenticated_receipt
            or self.authority_trust_query.supersession_frontier_ref
            != self.supersession_frontier_ref
            or self.authority_trust_envelope.query != expected_query
            or self.authority_trust_envelope.decision != "trusted"
            or self.authority_trust_envelope.supersession_frontier_ref
            != self.supersession_frontier_ref
            or self.issued_at != self.authority_trust_query.queried_at
            or self.issued_at >= self.authority_trust_envelope.stale_after
            or self.valid_until > self.authority_trust_envelope.stale_after
        ):
            raise ValueError("authority grant trust projection binding mismatch")
        body = self.model_dump(mode="json", by_alias=True, exclude={"grant_ref", "grant_hash"})
        expected = _self_hash(VALID_AUTHORITY_GRANT_SCHEMA, body)
        if self.grant_hash != expected or self.grant_ref != f"authority-grant@sha256:{expected}":
            raise ValueError("authority grant reference/hash do not bind its body")
        return self


class AuthorityHold(_FrozenModel):
    schema_id: Literal["hapax.authority-hold.v1"] = Field(alias="schema")
    hold_ref: str
    hold_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    intent_ref: str
    intent_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_ref: str
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    position_ref: str
    position_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    authority_trust_query: ExecutionTrustQuery
    authority_trust_envelope: ExecutionTrustEnvelope | None
    checked_at: str
    reason_codes: tuple[str, ...] = Field(min_length=1)
    repair_refs: tuple[str, ...] = Field(min_length=1)
    may_authorize: Literal[False]

    @field_validator("hold_ref", "intent_ref", "evidence_ref", "position_ref")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("reason_codes", "repair_refs")
    @classmethod
    def validate_sets(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _string_set(value)

    @field_validator("checked_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_hold(self) -> Self:
        if (
            self.authority_trust_query.trust_class != "authenticated_authority_receipt"
            or self.authority_trust_query.queried_at != self.checked_at
            or (
                self.authority_trust_envelope is not None
                and self.authority_trust_envelope.query
                != ContentAddress(
                    ref=self.authority_trust_query.query_ref,
                    sha256=self.authority_trust_query.query_hash,
                )
            )
        ):
            raise ValueError("authority hold trust query/envelope mismatch")
        body = self.model_dump(mode="json", by_alias=True, exclude={"hold_ref", "hold_hash"})
        expected = _self_hash(AUTHORITY_HOLD_SCHEMA, body)
        if self.hold_hash != expected or self.hold_ref != f"authority-hold@sha256:{expected}":
            raise ValueError("authority hold reference/hash do not bind its body")
        return self


def _authority_hold(
    intent: ActionIntent,
    evidence: AuthorityEvidence,
    position: ContextPosition,
    *,
    trust_query: ExecutionTrustQuery,
    trust_envelope: ExecutionTrustEnvelope | None,
    checked_at: str,
    reason_codes: Sequence[str],
) -> AuthorityHold:
    reasons = tuple(sorted(set(reason_codes)))
    body: dict[str, object] = {
        "schema": AUTHORITY_HOLD_SCHEMA,
        "intent_ref": intent.intent_ref,
        "intent_hash": intent.intent_hash,
        "evidence_ref": evidence.evidence_ref,
        "evidence_hash": evidence.evidence_hash,
        "position_ref": position.position_ref,
        "position_hash": position.position_hash,
        "authority_trust_query": trust_query.model_dump(mode="json", by_alias=True),
        "authority_trust_envelope": (
            None
            if trust_envelope is None
            else trust_envelope.model_dump(mode="json", by_alias=True)
        ),
        "checked_at": checked_at,
        "reason_codes": reasons,
        "repair_refs": tuple(f"repair:{reason}" for reason in reasons),
        "may_authorize": False,
    }
    digest = _self_hash(AUTHORITY_HOLD_SCHEMA, body)
    return AuthorityHold.model_validate(
        {**body, "hold_ref": f"authority-hold@sha256:{digest}", "hold_hash": digest}
    )


def validate_authority(
    intent: ActionIntent,
    evidence: AuthorityEvidence,
    position: ContextPosition,
    *,
    now: str | datetime,
    validation_method_ref: str = "method:gate0-authority-validation-v1",
    trust_resolver: ExecutionTrustResolver | None = None,
) -> ValidAuthorityGrant | AuthorityHold:
    """Validate and narrow existing authority; never originate a SovereignAct."""

    checked_at = _canonical_timestamp(now)
    try:
        intent = ActionIntent.model_validate(intent.model_dump(mode="json", by_alias=True))
        evidence = AuthorityEvidence.model_validate(evidence.model_dump(mode="json", by_alias=True))
        position = ContextPosition.model_validate(position.model_dump(mode="json", by_alias=True))
    except Exception as exc:
        raise ExecutionAdmissionError(
            "authority_validation_input_malformed",
            "restore the exact self-validating intent, evidence, and lifecycle position",
            type(exc).__name__,
        ) from exc
    intent_address = ContentAddress(ref=intent.intent_ref, sha256=intent.intent_hash)
    evidence_address = ContentAddress(ref=evidence.evidence_ref, sha256=evidence.evidence_hash)
    position_address = ContentAddress(
        ref=position.position_ref,
        sha256=position.position_hash,
    )
    trust_query = build_execution_trust_query(
        trust_class="authenticated_authority_receipt",
        subject_roots=(
            intent_address,
            evidence_address,
            position_address,
            evidence.authority_source,
            evidence.issuer,
            intent.acting_subject,
        ),
        presented_receipt=evidence.authenticated_receipt,
        required_roots=(
            intent_address,
            evidence_address,
            position_address,
            evidence.authority_source,
            evidence.authenticated_receipt,
            evidence.issuer,
            intent.acting_subject,
        ),
        supersession_frontier_ref=evidence.supersession_frontier_ref,
        queried_at=checked_at,
    )
    reasons: list[str] = []
    trust_envelope: ExecutionTrustEnvelope | None = None
    try:
        trust_envelope = _seal_execution_trust_resolver(trust_resolver).evaluate(trust_query)
        if trust_envelope.decision != "trusted":
            reasons.extend(trust_envelope.reason_codes or ("execution_trust_held",))
    except ExecutionAdmissionError as exc:
        reasons.append(exc.reason_code)
    if evidence.revoked_by_refs:
        reasons.append("authority_revoked")
    if not (evidence.not_before <= checked_at < evidence.valid_until):
        reasons.append("authority_evidence_not_current")
    if intent.task_ref != position.task_ref:
        reasons.append("authority_task_mismatch")
    if (
        intent.position_ref != position.position_ref
        or intent.position_hash != position.position_hash
    ):
        reasons.append("authority_position_mismatch")
    if evidence.authority_case != position.authority_case:
        reasons.append("authority_case_mismatch")
    if evidence.subject != intent.acting_subject:
        reasons.append("authority_subject_mismatch")
    if intent.action_class not in evidence.authorized_action_classes:
        reasons.append("authority_action_class_not_granted")
    if intent.operation not in evidence.authorized_operations:
        reasons.append("authority_operation_not_granted")
    if not set(intent.requested_scope_refs).issubset(evidence.scope_refs):
        reasons.append("authority_evidence_scope_insufficient")
    if not set(intent.requested_scope_refs).issubset(position.mutation_scope_refs):
        reasons.append("authority_position_scope_insufficient")
    position_flags = {item.name: item.authorized for item in position.authorized_flags}
    exact_required_flags = tuple(
        sorted(name for name, authorized in position_flags.items() if authorized)
    )
    if intent.required_authorization_flags != exact_required_flags:
        reasons.append("authority_intent_flags_not_exact_for_position")
    if not set(intent.required_authorization_flags).issubset(evidence.authorized_flags):
        reasons.append("authority_evidence_flags_insufficient")
    if any(not position_flags.get(name, False) for name in intent.required_authorization_flags):
        reasons.append("authority_position_flags_insufficient")
    if reasons:
        return _authority_hold(
            intent,
            evidence,
            position,
            trust_query=trust_query,
            trust_envelope=trust_envelope,
            checked_at=checked_at,
            reason_codes=reasons,
        )
    if trust_envelope is None:
        raise AssertionError("trusted authority validation requires an envelope")

    body: dict[str, object] = {
        "schema": VALID_AUTHORITY_GRANT_SCHEMA,
        "intent_ref": intent.intent_ref,
        "intent_hash": intent.intent_hash,
        "evidence_ref": evidence.evidence_ref,
        "evidence_hash": evidence.evidence_hash,
        "authority_source": evidence.authority_source,
        "authenticated_receipt": evidence.authenticated_receipt,
        "authority_issuer": evidence.issuer,
        "acting_subject": intent.acting_subject,
        "authority_trust_query": trust_query.model_dump(mode="json", by_alias=True),
        "authority_trust_envelope": trust_envelope.model_dump(mode="json", by_alias=True),
        "position_ref": position.position_ref,
        "position_hash": position.position_hash,
        "task_ref": position.task_ref,
        "authority_case": position.authority_case,
        "authority_ceiling": evidence.authority_ceiling,
        "action_class": intent.action_class,
        "operation": intent.operation,
        "authorized_flags": intent.required_authorization_flags,
        "scope_refs": intent.requested_scope_refs,
        "issued_at": checked_at,
        "valid_until": min(evidence.valid_until, trust_envelope.stale_after),
        "supersession_frontier_ref": evidence.supersession_frontier_ref,
        "validation_method_ref": _nonblank(validation_method_ref),
        "authorizes_machine_admission": True,
        "authorizes_operator": False,
        "may_mint_sovereign_act": False,
    }
    digest = _self_hash(VALID_AUTHORITY_GRANT_SCHEMA, body)
    return ValidAuthorityGrant.model_validate(
        {**body, "grant_ref": f"authority-grant@sha256:{digest}", "grant_hash": digest}
    )


class AppliedClaimProof(_FrozenModel):
    """Exact applied claim receipt/manifest plus the current task-note snapshot."""

    schema_id: Literal["hapax.applied-claim-proof.v1"] = Field(alias="schema")
    proof_ref: str
    proof_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_anchor_ref: str
    publication_id: str
    task_ref: str
    lane: str
    session_ref: str
    claim_epoch: int = Field(gt=0, strict=True)
    authority_case: str
    dispatch_message_id: str
    dispatch_binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dispatch_binding_receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    coord_dispatch_idempotency_key: str
    intent_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_publication_intent: ContentAddress
    claim_note_postimage_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_task_note: ContentAddress
    receipt: ContentAddress
    manifest: ContentAddress
    may_authorize: Literal[False]

    @field_validator(
        "proof_ref",
        "claim_anchor_ref",
        "publication_id",
        "task_ref",
        "lane",
        "session_ref",
        "authority_case",
        "dispatch_message_id",
        "coord_dispatch_idempotency_key",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @model_validator(mode="after")
    def validate_proof(self) -> Self:
        if self.claim_publication_intent != ContentAddress(
            ref=f"claim-publication-intent@sha256:{self.intent_sha256}",
            sha256=self.intent_sha256,
        ):
            raise ValueError("claim publication intent address is not canonical")
        if self.claim_anchor_ref != f"claim-publication@sha256:{self.receipt.sha256}":
            raise ValueError("claim anchor must bind the applied receipt bytes")
        body = self.model_dump(mode="json", by_alias=True, exclude={"proof_ref", "proof_hash"})
        expected = _self_hash(CLAIM_PROOF_SCHEMA, body)
        if self.proof_hash != expected or self.proof_ref != f"applied-claim@sha256:{expected}":
            raise ValueError("applied claim proof reference/hash do not bind its body")
        return self


class AdmittedAppliedClaimProof(_FrozenModel):
    """Applied claim proof that consumes the exact admitted-publication roots."""

    schema_id: Literal["hapax.applied-claim-proof.v2"] = Field(alias="schema")
    proof_ref: str
    proof_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_anchor_ref: str
    publication_id: str
    task_ref: str
    lane: str
    session_ref: str
    claim_epoch: int = Field(gt=0, strict=True)
    authority_case: str
    dispatch_message_id: str
    dispatch_binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dispatch_binding_receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    coord_dispatch_idempotency_key: str
    intent_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_publication_intent: ContentAddress
    claim_note_postimage_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_task_note: ContentAddress
    receipt: ContentAddress
    receipt_schema: Literal["hapax.claim-publication-receipt.v3"]
    manifest: ContentAddress
    admission_consumption: ContentAddress
    execution_admission: ContentAddress
    valid_authority_grant: ContentAddress
    authority_evidence: ContentAddress
    authenticated_authority_receipt: ContentAddress
    context_position: ContentAddress
    supersession_frontier_ref: str
    admission_checked_at: str
    admission_valid_until: str
    may_authorize: Literal[False]

    @field_validator(
        "proof_ref",
        "claim_anchor_ref",
        "publication_id",
        "task_ref",
        "lane",
        "session_ref",
        "authority_case",
        "dispatch_message_id",
        "coord_dispatch_idempotency_key",
        "supersession_frontier_ref",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("admission_checked_at", "admission_valid_until")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_proof(self) -> Self:
        if self.claim_publication_intent != ContentAddress(
            ref=f"claim-publication-intent@sha256:{self.intent_sha256}",
            sha256=self.intent_sha256,
        ):
            raise ValueError("claim publication intent address is not canonical")
        if self.claim_anchor_ref != f"claim-publication@sha256:{self.receipt.sha256}":
            raise ValueError("claim anchor must bind the applied receipt bytes")
        admitted_addresses = (
            self.admission_consumption,
            self.execution_admission,
            self.valid_authority_grant,
            self.authority_evidence,
            self.authenticated_authority_receipt,
            self.context_position,
        )
        if any(
            not address.ref.endswith(f"@sha256:{address.sha256}") for address in admitted_addresses
        ):
            raise ValueError("admitted claim roots must use canonical content addresses")
        body = self.model_dump(mode="json", by_alias=True, exclude={"proof_ref", "proof_hash"})
        expected = _self_hash(ADMITTED_CLAIM_PROOF_SCHEMA, body)
        if self.proof_hash != expected or self.proof_ref != f"applied-claim@sha256:{expected}":
            raise ValueError("admitted claim proof reference/hash do not bind its body")
        return self


class HistoricalAppliedClaimOwnershipProofV3(_FrozenModel):
    """Historical ownership derived before publication outcome gating."""

    schema_id: Literal["hapax.applied-claim-ownership-proof.v3"] = Field(alias="schema")
    proof_ref: str
    proof_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_anchor_ref: str
    publication_id: str
    task_ref: str
    lane: str
    session_ref: str
    claim_epoch: int = Field(gt=0, strict=True)
    authority_case: str
    dispatch_message_id: str
    dispatch_binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dispatch_binding_receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    coord_dispatch_idempotency_key: str
    intent_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_publication_intent: ContentAddress
    claim_note_postimage_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt: ContentAddress
    receipt_schema: Literal["hapax.claim-publication-receipt.v3"]
    manifest: ContentAddress
    admission_consumption: ContentAddress
    publication_action_intent: ContentAddress
    publication_execution_admission: ContentAddress
    publication_valid_authority_grant: ContentAddress
    publication_authority_evidence: ContentAddress
    publication_authenticated_authority_receipt: ContentAddress
    publication_context_position: ContentAddress
    publication_supersession_frontier_ref: str
    publication_checked_at: str
    publication_authorization_valid_until: str
    may_authorize: Literal[False]

    @field_validator(
        "proof_ref",
        "claim_anchor_ref",
        "publication_id",
        "task_ref",
        "lane",
        "session_ref",
        "authority_case",
        "dispatch_message_id",
        "coord_dispatch_idempotency_key",
        "publication_supersession_frontier_ref",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("publication_checked_at", "publication_authorization_valid_until")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_proof(self) -> Self:
        if self.claim_publication_intent != ContentAddress(
            ref=f"claim-publication-intent@sha256:{self.intent_sha256}",
            sha256=self.intent_sha256,
        ):
            raise ValueError("claim publication intent address is not canonical")
        if self.claim_anchor_ref != f"claim-publication@sha256:{self.receipt.sha256}":
            raise ValueError("claim anchor must bind the applied receipt bytes")
        if not self.publication_checked_at < self.publication_authorization_valid_until:
            raise ValueError("publication provenance requires a non-empty historical interval")
        publication_roots = (
            self.admission_consumption,
            self.publication_action_intent,
            self.publication_execution_admission,
            self.publication_valid_authority_grant,
            self.publication_authority_evidence,
            self.publication_authenticated_authority_receipt,
            self.publication_context_position,
        )
        if any(
            not address.ref.endswith(f"@sha256:{address.sha256}") for address in publication_roots
        ):
            raise ValueError("claim ownership provenance must use content addresses")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"proof_ref", "proof_hash"},
        )
        expected = _self_hash(HISTORICAL_APPLIED_CLAIM_OWNERSHIP_SCHEMA, body)
        if self.proof_hash != expected or self.proof_ref != (
            f"applied-claim-ownership@sha256:{expected}"
        ):
            raise ValueError("claim ownership proof reference/hash do not bind its body")
        return self


def _admitted_applied_claim_proof(
    snapshot: AppliedClaimPublicationSnapshot,
) -> AdmittedAppliedClaimProof:
    from shared.sdlc_claim import (
        ClaimPublicationError,
        resolve_claim_publication_admission_provenance,
    )

    receipt = snapshot.receipt
    try:
        provenance = resolve_claim_publication_admission_provenance(snapshot)
    except ClaimPublicationError as exc:
        raise ExecutionAdmissionError(
            exc.reason_code,
            exc.repair_action,
            exc.detail or receipt.publication_id,
        ) from exc
    consumption = provenance.admission_consumption
    expected_consumption = ContentAddress(
        ref=consumption.consumption_ref,
        sha256=consumption.consumption_hash,
    )
    binding = snapshot.intent.binding
    key = binding.coord_dispatch_idempotency_key
    if not key:
        raise ExecutionAdmissionError(
            "claim_dispatch_idempotency_key_missing",
            "reclaim through a dispatch carrying one end-to-end idempotency key",
            binding.task_id,
        )
    body: dict[str, object] = {
        "schema": ADMITTED_CLAIM_PROOF_SCHEMA,
        "claim_anchor_ref": f"claim-publication@sha256:{_sha256(snapshot.receipt_content)}",
        "publication_id": receipt.publication_id,
        "task_ref": receipt.task_id,
        "lane": receipt.role,
        "session_ref": receipt.session_id,
        "claim_epoch": receipt.claim_epoch,
        "authority_case": binding.authority_case,
        "dispatch_message_id": binding.dispatch_message_id,
        "dispatch_binding_hash": binding.binding_hash,
        "dispatch_binding_receipt_hash": receipt.binding_receipt_hash,
        "coord_dispatch_idempotency_key": key,
        "intent_sha256": receipt.intent_sha256,
        "claim_publication_intent": ContentAddress(
            ref=snapshot.intent.intent_ref,
            sha256=snapshot.intent.intent_sha256,
        ),
        "claim_note_postimage_sha256": receipt.claim_note_postimage_sha256,
        "current_task_note": ContentAddress(
            ref=str(snapshot.current_task.path), sha256=snapshot.current_task.sha256
        ),
        "receipt": ContentAddress(
            ref=str(receipt.receipt_path), sha256=_sha256(snapshot.receipt_content)
        ),
        "receipt_schema": receipt.schema,
        "manifest": ContentAddress(
            ref=str(receipt.manifest_path), sha256=_sha256(snapshot.manifest_content)
        ),
        "admission_consumption": expected_consumption,
        "execution_admission": consumption.execution_admission,
        "valid_authority_grant": consumption.valid_authority_grant,
        "authority_evidence": consumption.authority_evidence,
        "authenticated_authority_receipt": consumption.authenticated_authority_receipt,
        "context_position": consumption.context_position,
        "supersession_frontier_ref": consumption.supersession_frontier_ref,
        "admission_checked_at": consumption.checked_at,
        "admission_valid_until": consumption.valid_until,
        "may_authorize": False,
    }
    digest = _self_hash(ADMITTED_CLAIM_PROOF_SCHEMA, body)
    return AdmittedAppliedClaimProof.model_validate(
        {**body, "proof_ref": f"applied-claim@sha256:{digest}", "proof_hash": digest}
    )


def applied_claim_proof(
    snapshot: AppliedClaimPublicationSnapshot,
) -> AppliedClaimProof | AdmittedAppliedClaimProof:
    """Project the locked applied snapshot without treating its mutable task note as authority."""

    if snapshot.admission_consumption is not None:
        from shared.sdlc_claim import ClaimAdmissionConsumption

        if isinstance(snapshot.admission_consumption, ClaimAdmissionConsumption):
            raise ExecutionAdmissionError(
                "current_claim_ownership_outcome_required",
                "resolve the publication outcome before deriving active v7 ownership",
                snapshot.receipt.publication_id,
            )
        return _admitted_applied_claim_proof(snapshot)

    receipt = snapshot.receipt
    binding = snapshot.intent.binding
    key = binding.coord_dispatch_idempotency_key
    if not key:
        raise ExecutionAdmissionError(
            "claim_dispatch_idempotency_key_missing",
            "reclaim through a dispatch carrying one end-to-end idempotency key",
            binding.task_id,
        )
    body: dict[str, object] = {
        "schema": CLAIM_PROOF_SCHEMA,
        "claim_anchor_ref": f"claim-publication@sha256:{_sha256(snapshot.receipt_content)}",
        "publication_id": receipt.publication_id,
        "task_ref": receipt.task_id,
        "lane": receipt.role,
        "session_ref": receipt.session_id,
        "claim_epoch": receipt.claim_epoch,
        "authority_case": binding.authority_case,
        "dispatch_message_id": binding.dispatch_message_id,
        "dispatch_binding_hash": binding.binding_hash,
        "dispatch_binding_receipt_hash": receipt.binding_receipt_hash,
        "coord_dispatch_idempotency_key": key,
        "intent_sha256": receipt.intent_sha256,
        "claim_publication_intent": ContentAddress(
            ref=snapshot.intent.intent_ref,
            sha256=snapshot.intent.intent_sha256,
        ),
        "claim_note_postimage_sha256": receipt.claim_note_postimage_sha256,
        "current_task_note": ContentAddress(
            ref=str(snapshot.current_task.path), sha256=snapshot.current_task.sha256
        ),
        "receipt": ContentAddress(
            ref=str(receipt.receipt_path), sha256=_sha256(snapshot.receipt_content)
        ),
        "manifest": ContentAddress(
            ref=str(receipt.manifest_path), sha256=_sha256(snapshot.manifest_content)
        ),
        "may_authorize": False,
    }
    digest = _self_hash(CLAIM_PROOF_SCHEMA, body)
    return AppliedClaimProof.model_validate(
        {**body, "proof_ref": f"applied-claim@sha256:{digest}", "proof_hash": digest}
    )


def require_admitted_applied_claim_proof(
    snapshot: AppliedClaimPublicationSnapshot,
) -> AdmittedAppliedClaimProof:
    """Require the transaction-v2 proof; legacy claims remain inspection-only."""

    proof = applied_claim_proof(snapshot)
    if not isinstance(proof, AdmittedAppliedClaimProof):
        raise ExecutionAdmissionError(
            "admitted_applied_claim_required",
            "publish and resolve the exact admitted transaction-v2 claim",
            proof.proof_ref,
        )
    return proof


def historical_applied_claim_ownership_proof(
    snapshot: AppliedClaimPublicationSnapshot,
) -> HistoricalAppliedClaimOwnershipProofV3:
    """Project durable ownership while retaining publication authority as provenance."""

    from shared.sdlc_claim import HistoricalClaimAdmissionConsumptionV1

    if not isinstance(
        snapshot.admission_consumption,
        HistoricalClaimAdmissionConsumptionV1,
    ):
        raise ExecutionAdmissionError(
            "historical_claim_ownership_v3_required",
            "supply an exact historical transaction-v2 publication for v3 inspection",
            snapshot.receipt.publication_id,
        )
    from shared.sdlc_claim import resolve_claim_publication_admission_provenance

    publication = _admitted_applied_claim_proof(snapshot)
    provenance = resolve_claim_publication_admission_provenance(snapshot)
    body: dict[str, object] = {
        "schema": HISTORICAL_APPLIED_CLAIM_OWNERSHIP_SCHEMA,
        "claim_anchor_ref": publication.claim_anchor_ref,
        "publication_id": publication.publication_id,
        "task_ref": publication.task_ref,
        "lane": publication.lane,
        "session_ref": publication.session_ref,
        "claim_epoch": publication.claim_epoch,
        "authority_case": publication.authority_case,
        "dispatch_message_id": publication.dispatch_message_id,
        "dispatch_binding_hash": publication.dispatch_binding_hash,
        "dispatch_binding_receipt_hash": publication.dispatch_binding_receipt_hash,
        "coord_dispatch_idempotency_key": publication.coord_dispatch_idempotency_key,
        "intent_sha256": publication.intent_sha256,
        "claim_publication_intent": publication.claim_publication_intent,
        "claim_note_postimage_sha256": publication.claim_note_postimage_sha256,
        "receipt": publication.receipt,
        "receipt_schema": publication.receipt_schema,
        "manifest": publication.manifest,
        "admission_consumption": publication.admission_consumption,
        "publication_action_intent": provenance.publication_action_intent,
        "publication_execution_admission": publication.execution_admission,
        "publication_valid_authority_grant": publication.valid_authority_grant,
        "publication_authority_evidence": publication.authority_evidence,
        "publication_authenticated_authority_receipt": (
            publication.authenticated_authority_receipt
        ),
        "publication_context_position": publication.context_position,
        "publication_supersession_frontier_ref": publication.supersession_frontier_ref,
        "publication_checked_at": publication.admission_checked_at,
        "publication_authorization_valid_until": publication.admission_valid_until,
        "may_authorize": False,
    }
    digest = _self_hash(HISTORICAL_APPLIED_CLAIM_OWNERSHIP_SCHEMA, body)
    return HistoricalAppliedClaimOwnershipProofV3.model_validate(
        {
            **body,
            "proof_ref": f"applied-claim-ownership@sha256:{digest}",
            "proof_hash": digest,
        }
    )


def require_historical_applied_claim_ownership_proof(
    snapshot: AppliedClaimPublicationSnapshot,
) -> HistoricalAppliedClaimOwnershipProofV3:
    """Require historical v3 ownership for inspection only."""

    return historical_applied_claim_ownership_proof(snapshot)


ClaimPublicationArtifactKind = Literal[
    "receipt",
    "manifest",
    "task_note",
    "claim",
    "epoch",
    "dispatch_binding",
]


class ClaimPublicationArtifact(_FrozenModel):
    """One exact postimage produced by an applied claim publication."""

    kind: ClaimPublicationArtifactKind
    key: str
    path: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mode: int = Field(ge=0, le=0o777, strict=True)
    file_address: ContentAddress

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        checked = _nonblank(value)
        path = Path(checked)
        if not path.is_absolute() or path == Path("/") or str(_normalized_path(path)) != checked:
            raise ValueError("claim publication artifact path must be normalized and absolute")
        return checked

    @model_validator(mode="after")
    def validate_artifact(self) -> Self:
        required_mode = {
            "receipt": 0o600,
            "manifest": 0o600,
            "claim": 0o644,
            "epoch": 0o644,
            "dispatch_binding": 0o600,
        }.get(self.kind)
        if required_mode is not None and self.mode != required_mode:
            raise ValueError(
                f"claim publication {self.kind} postimages must be mode-{required_mode:04o}"
            )
        expected_ref = f"file:{self.path}@sha256:{self.content_sha256}"
        if self.file_address != ContentAddress(
            ref=expected_ref,
            sha256=self.content_sha256,
        ):
            raise ValueError("claim publication artifact address does not bind its postimage")
        return self


class ClaimPublicationCompletionEvidence(_FrozenModel):
    """Stable evidence that one exact admitted claim publication completed."""

    schema_id: Literal["hapax.claim-publication-completion-evidence.v3"] = Field(alias="schema")
    evidence_ref: str
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    publication_id: str
    task_ref: str
    lane: str
    session_ref: str
    claim_epoch: int = Field(gt=0, strict=True)
    claim_publication_intent: ContentAddress
    admission_consumption: ContentAddress
    execution_lease: ContentAddress
    bound_execution_call: ContentAddress
    claim_note_postimage_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dispatch_binding_postimage_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifacts: tuple[ClaimPublicationArtifact, ...] = Field(min_length=9, max_length=9)
    projection_vector: ContentAddress
    effect_observation: ContentAddress
    outcome_projection: ContentAddress
    outcome_receipt: ContentAddress
    committer: ContentAddress
    event_plane: ContentAddress
    outcome_validity_resolver: ContentAddress
    source_event_frontier: ContentAddress
    outcome: Literal["succeeded"]
    effect_disposition: Literal["applied"]
    closure_state: Literal["closed"]
    observed_at: str
    committed_at: str
    may_authorize: Literal[False]

    @field_validator(
        "evidence_ref",
        "publication_id",
        "task_ref",
        "lane",
        "session_ref",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("observed_at", "committed_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        role_session_key = f"{self.lane}-{self.session_ref}"
        expected_vector = (
            ("receipt", self.publication_id),
            ("manifest", self.publication_id),
            ("task_note", self.task_ref),
            *(
                (kind, key)
                for key in (self.lane, role_session_key)
                for kind in (
                    "claim",
                    "epoch",
                    "dispatch_binding",
                )
            ),
        )
        if tuple((item.kind, item.key) for item in self.artifacts) != expected_vector:
            raise ValueError("claim completion evidence requires the exact postimage vector")
        if len({item.path for item in self.artifacts}) != len(self.artifacts):
            raise ValueError("claim completion evidence artifact paths must be unique")
        task_artifact = self.artifacts[2]
        claim_hash = _sha256(f"{self.task_ref}\n".encode("ascii"))
        epoch_hash = _sha256(f"{self.claim_epoch} {self.task_ref}\n".encode("ascii"))
        if (
            task_artifact.content_sha256 != self.claim_note_postimage_sha256
            or any(self.artifacts[index].content_sha256 != claim_hash for index in (3, 6))
            or any(self.artifacts[index].content_sha256 != epoch_hash for index in (4, 7))
            or any(
                self.artifacts[index].content_sha256
                != self.dispatch_binding_postimage_sha256
                for index in (5, 8)
            )
        ):
            raise ValueError("claim completion postimages do not bind the publication identity")
        if self.observed_at > self.committed_at:
            raise ValueError("claim completion cannot commit before its effect observation")
        canonical_refs = (
            (
                self.projection_vector,
                "claim-publication-projection-vector@sha256:",
            ),
            (self.effect_observation, "effect-observation@sha256:"),
            (self.outcome_projection, "outcome-projection-snapshot@sha256:"),
            (self.outcome_receipt, "outcome-receipt@sha256:"),
        )
        if any(address.ref != f"{prefix}{address.sha256}" for address, prefix in canonical_refs):
            raise ValueError("claim completion evidence requires canonical chain addresses")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"evidence_ref", "evidence_hash"},
        )
        expected = _self_hash(CLAIM_PUBLICATION_COMPLETION_EVIDENCE_SCHEMA, body)
        if self.evidence_hash != expected or self.evidence_ref != (
            f"claim-publication-completion-evidence@sha256:{expected}"
        ):
            raise ValueError("claim completion reference/hash do not bind its body")
        return self


class AppliedClaimOwnershipProof(_FrozenModel):
    """Outcome-gated durable ownership; never publication or action authority."""

    schema_id: Literal["hapax.applied-claim-ownership-proof.v7"] = Field(alias="schema")
    proof_ref: str
    proof_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_anchor_ref: str
    publication_id: str
    task_ref: str
    lane: str
    session_ref: str
    claim_epoch: int = Field(gt=0, strict=True)
    authority_case: str
    dispatch_message_id: str
    dispatch_binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dispatch_binding_receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    coord_dispatch_idempotency_key: str
    intent_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_publication_intent: ContentAddress
    claim_note_postimage_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dispatch_binding_postimage_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt: ContentAddress
    receipt_schema: Literal["hapax.claim-publication-receipt.v4"]
    manifest: ContentAddress
    admission_consumption: ContentAddress
    publication_action_intent: ContentAddress
    publication_execution_admission: ContentAddress
    publication_valid_authority_grant: ContentAddress
    publication_authority_evidence: ContentAddress
    publication_authenticated_authority_receipt: ContentAddress
    publication_context_position: ContentAddress
    publication_execution_lease: ContentAddress
    publication_bound_execution_call: ContentAddress
    publication_outcome_projection: ContentAddress
    publication_outcome_receipt: ContentAddress
    publication_completion_evidence: ClaimPublicationCompletionEvidence
    publication_outcome_committed_at: str
    publication_supersession_frontier_ref: str
    publication_checked_at: str
    publication_authorization_valid_until: str
    may_authorize: Literal[False]

    @field_validator(
        "proof_ref",
        "claim_anchor_ref",
        "publication_id",
        "task_ref",
        "lane",
        "session_ref",
        "authority_case",
        "dispatch_message_id",
        "coord_dispatch_idempotency_key",
        "publication_supersession_frontier_ref",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator(
        "publication_outcome_committed_at",
        "publication_checked_at",
        "publication_authorization_valid_until",
    )
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_proof(self) -> Self:
        if self.claim_publication_intent != ContentAddress(
            ref=f"claim-publication-intent@sha256:{self.intent_sha256}",
            sha256=self.intent_sha256,
        ):
            raise ValueError("claim publication intent address is not canonical")
        if self.claim_anchor_ref != f"claim-publication@sha256:{self.receipt.sha256}":
            raise ValueError("claim anchor must bind the applied receipt bytes")
        if not self.publication_checked_at < self.publication_authorization_valid_until:
            raise ValueError("publication provenance requires a non-empty historical interval")
        if self.publication_outcome_committed_at < self.publication_checked_at:
            raise ValueError("publication outcome cannot predate its checked publication evidence")
        if self.publication_outcome_receipt.ref != (
            f"outcome-receipt@sha256:{self.publication_outcome_receipt.sha256}"
        ):
            raise ValueError("claim ownership requires a canonical publication outcome receipt")
        if self.publication_outcome_projection.ref != (
            f"outcome-projection-snapshot@sha256:{self.publication_outcome_projection.sha256}"
        ):
            raise ValueError("claim ownership requires a canonical outcome projection snapshot")
        completion = self.publication_completion_evidence
        if (
            completion.publication_id != self.publication_id
            or completion.task_ref != self.task_ref
            or completion.lane != self.lane
            or completion.session_ref != self.session_ref
            or completion.claim_epoch != self.claim_epoch
            or completion.claim_publication_intent != self.claim_publication_intent
            or completion.claim_note_postimage_sha256 != self.claim_note_postimage_sha256
            or completion.dispatch_binding_postimage_sha256
            != self.dispatch_binding_postimage_sha256
            or completion.admission_consumption != self.admission_consumption
            or completion.execution_lease != self.publication_execution_lease
            or completion.bound_execution_call != self.publication_bound_execution_call
            or completion.outcome_projection != self.publication_outcome_projection
            or completion.outcome_receipt != self.publication_outcome_receipt
            or completion.committed_at != self.publication_outcome_committed_at
            or completion.artifacts[0].path != self.receipt.ref
            or completion.artifacts[0].content_sha256 != self.receipt.sha256
            or completion.artifacts[1].path != self.manifest.ref
            or completion.artifacts[1].content_sha256 != self.manifest.sha256
        ):
            raise ValueError("claim ownership differs from its publication completion evidence")
        roots = (
            self.admission_consumption,
            self.publication_action_intent,
            self.publication_execution_admission,
            self.publication_valid_authority_grant,
            self.publication_authority_evidence,
            self.publication_authenticated_authority_receipt,
            self.publication_context_position,
            self.publication_execution_lease,
            self.publication_bound_execution_call,
            self.publication_outcome_projection,
            self.publication_outcome_receipt,
            ContentAddress(
                ref=completion.evidence_ref,
                sha256=completion.evidence_hash,
            ),
        )
        if any(not item.ref.endswith(f"@sha256:{item.sha256}") for item in roots):
            raise ValueError("claim ownership provenance must use content addresses")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"proof_ref", "proof_hash"},
        )
        expected = _self_hash(APPLIED_CLAIM_OWNERSHIP_SCHEMA, body)
        if self.proof_hash != expected or self.proof_ref != (
            f"applied-claim-ownership@sha256:{expected}"
        ):
            raise ValueError("claim ownership proof reference/hash do not bind its body")
        return self


def _applied_claim_ownership_resolution(
    snapshot: AppliedClaimPublicationSnapshot,
    *,
    outcome_committer: OutcomeCommitter,
    queried_at: str | datetime,
) -> tuple[AppliedClaimOwnershipProof, OutcomeReplayResult]:
    """Project stable ownership only from the installed event-plane replay catalog."""

    from shared.sdlc_claim import (
        AppliedClaimPublicationSnapshot as SnapshotType,
    )
    from shared.sdlc_claim import (
        ClaimAdmissionConsumption,
        resolve_claim_publication_admission_provenance,
    )

    checked_snapshot = _require_exact_type(
        snapshot,
        SnapshotType,
        "applied claim publication snapshot",
    )
    configured_outcomes = _seal_outcome_committer(outcome_committer)
    consumption = checked_snapshot.admission_consumption
    if type(consumption) is not ClaimAdmissionConsumption:
        raise ExecutionAdmissionError(
            "current_action_claim_ownership_v7_required",
            "publish through transaction-v3 before deriving current ownership",
            checked_snapshot.receipt.publication_id,
        )
    provenance = resolve_claim_publication_admission_provenance(checked_snapshot)
    if provenance.execution_lease is None:
        raise ExecutionAdmissionError(
            "claim_publication_execution_lease_missing",
            "restore the receipt-bound publication execution lease",
            checked_snapshot.receipt.publication_id,
        )
    publication_lease = provenance.execution_lease
    replay = configured_outcomes.replay(publication_lease, queried_at=queried_at)
    if replay is None:
        raise ExecutionAdmissionError(
            "claim_publication_outcome_receipt_missing",
            "install the exact canonical publication outcome projection",
            checked_snapshot.receipt.publication_id,
        )
    projection = replay.projection
    outcome = projection.outcome_receipt
    expected_lease = ContentAddress(
        ref=publication_lease.lease_ref,
        sha256=publication_lease.lease_hash,
    )
    expected_call = ContentAddress(
        ref=publication_lease.bound_call.call_ref,
        sha256=publication_lease.bound_call.call_hash,
    )
    if (
        outcome.execution_lease != expected_lease
        or outcome.bound_execution_call != expected_call
        or outcome.effect_manifest != publication_lease.effect_manifest
        or outcome.executor_descriptor != publication_lease.executor_descriptor
        or outcome.executor_registry_projection != publication_lease.executor_registry_projection
        or outcome.executor != publication_lease.executor
        or outcome.observation_contract != publication_lease.observation_contract
        or outcome.completion_predicate != publication_lease.completion_predicate
        or outcome.reconciliation_contract != publication_lease.reconciliation_contract
        or outcome.invocation_id != publication_lease.invocation_id
        or outcome.attempt_fence != publication_lease.attempt_fence
        or outcome.idempotency_key != publication_lease.idempotency_key
        or projection.activation_generation_roots != publication_lease.active_generation_roots
    ):
        raise ExecutionAdmissionError(
            "claim_publication_outcome_binding_mismatch",
            "resolve the canonical outcome for the exact publication execution lease",
            checked_snapshot.receipt.publication_id,
        )
    if (
        outcome.outcome != "succeeded"
        or outcome.effect_disposition != "applied"
        or outcome.closure_state != "closed"
    ):
        raise ExecutionAdmissionError(
            "claim_publication_outcome_not_applied",
            "reconcile claim publication to one closed successful applied outcome",
            f"{outcome.outcome}:{outcome.effect_disposition}:{outcome.closure_state}",
        )
    outcome_address = ContentAddress(
        ref=outcome.receipt_ref,
        sha256=outcome.receipt_hash,
    )
    receipt_address = ContentAddress(
        ref=str(checked_snapshot.receipt.receipt_path),
        sha256=_sha256(checked_snapshot.receipt_content),
    )
    completion = build_claim_publication_completion_evidence(
        checked_snapshot,
        projection,
        outcome_validity_resolver=replay.validity.resolver,
    )
    body: dict[str, object] = {
        "schema": APPLIED_CLAIM_OWNERSHIP_SCHEMA,
        "claim_anchor_ref": f"claim-publication@sha256:{receipt_address.sha256}",
        "publication_id": checked_snapshot.receipt.publication_id,
        "task_ref": checked_snapshot.receipt.task_id,
        "lane": checked_snapshot.receipt.role,
        "session_ref": checked_snapshot.receipt.session_id,
        "claim_epoch": checked_snapshot.receipt.claim_epoch,
        "authority_case": checked_snapshot.intent.binding.authority_case,
        "dispatch_message_id": checked_snapshot.intent.binding.dispatch_message_id,
        "dispatch_binding_hash": checked_snapshot.intent.binding.binding_hash,
        "dispatch_binding_receipt_hash": checked_snapshot.receipt.binding_receipt_hash,
        "coord_dispatch_idempotency_key": (
            checked_snapshot.intent.binding.coord_dispatch_idempotency_key
        ),
        "intent_sha256": checked_snapshot.receipt.intent_sha256,
        "claim_publication_intent": ContentAddress(
            ref=checked_snapshot.intent.intent_ref,
            sha256=checked_snapshot.intent.intent_sha256,
        ),
        "claim_note_postimage_sha256": checked_snapshot.receipt.claim_note_postimage_sha256,
        "dispatch_binding_postimage_sha256": completion.dispatch_binding_postimage_sha256,
        "receipt": receipt_address,
        "receipt_schema": checked_snapshot.receipt.schema,
        "manifest": ContentAddress(
            ref=str(checked_snapshot.receipt.manifest_path),
            sha256=_sha256(checked_snapshot.manifest_content),
        ),
        "admission_consumption": ContentAddress(
            ref=consumption.consumption_ref,
            sha256=consumption.consumption_hash,
        ),
        "publication_action_intent": consumption.action_intent,
        "publication_execution_admission": consumption.execution_admission,
        "publication_valid_authority_grant": consumption.valid_authority_grant,
        "publication_authority_evidence": consumption.authority_evidence,
        "publication_authenticated_authority_receipt": (
            consumption.authenticated_authority_receipt
        ),
        "publication_context_position": consumption.context_position,
        "publication_execution_lease": consumption.execution_lease,
        "publication_bound_execution_call": consumption.bound_execution_call,
        "publication_outcome_projection": ContentAddress(
            ref=projection.snapshot_ref,
            sha256=projection.snapshot_hash,
        ),
        "publication_outcome_receipt": outcome_address,
        "publication_completion_evidence": completion,
        "publication_outcome_committed_at": outcome.committed_at,
        "publication_supersession_frontier_ref": consumption.supersession_frontier_ref,
        "publication_checked_at": consumption.checked_at,
        "publication_authorization_valid_until": consumption.valid_until,
        "may_authorize": False,
    }
    digest = _self_hash(APPLIED_CLAIM_OWNERSHIP_SCHEMA, body)
    proof = AppliedClaimOwnershipProof.model_validate(
        {
            **body,
            "proof_ref": f"applied-claim-ownership@sha256:{digest}",
            "proof_hash": digest,
        }
    )
    return proof, replay


def applied_claim_ownership_proof(
    snapshot: AppliedClaimPublicationSnapshot,
    *,
    outcome_committer: OutcomeCommitter,
    queried_at: str | datetime,
) -> AppliedClaimOwnershipProof:
    proof, _ = _applied_claim_ownership_resolution(
        snapshot,
        outcome_committer=outcome_committer,
        queried_at=queried_at,
    )
    return proof


def require_applied_claim_ownership_proof(
    snapshot: AppliedClaimPublicationSnapshot,
    *,
    outcome_committer: OutcomeCommitter,
    queried_at: str | datetime,
) -> AppliedClaimOwnershipProof:
    return applied_claim_ownership_proof(
        snapshot,
        outcome_committer=outcome_committer,
        queried_at=queried_at,
    )


class CurrentClaimLeaseFile(_FrozenModel):
    """One exact current claim sidecar observed in a sealed lease vector."""

    path: str
    kind: Literal["claim", "epoch", "dispatch_binding"]
    key: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mode: int = Field(ge=0, le=0o777, strict=True)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        checked = _nonblank(value)
        path = Path(checked)
        if not path.is_absolute() or path == Path("/"):
            raise ValueError("current claim lease paths must be bounded and absolute")
        if str(_normalized_path(path)) != checked:
            raise ValueError("current claim lease paths must be normalized")
        return checked

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        return _nonblank(value)


class CurrentClaimPosition(_FrozenModel):
    """Current task/lease position bound to outcome-gated ownership, never authority."""

    schema_id: Literal["hapax.current-claim-position.v3"] = Field(alias="schema")
    position_ref: str
    position_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    applied_claim_ownership: ContentAddress
    current_task_note: ContentAddress
    lease_files: tuple[CurrentClaimLeaseFile, ...] = Field(min_length=6, max_length=6)
    task_ref: str
    lane: str
    session_ref: str
    claim_epoch: int = Field(gt=0, strict=True)
    may_authorize: Literal[False]

    @field_validator("position_ref", "task_ref", "lane", "session_ref")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @model_validator(mode="after")
    def validate_position(self) -> Self:
        if self.applied_claim_ownership.ref != (
            f"applied-claim-ownership@sha256:{self.applied_claim_ownership.sha256}"
        ):
            raise ValueError("current claim position requires canonical applied ownership")
        task_path = Path(self.current_task_note.ref)
        if (
            not task_path.is_absolute()
            or task_path == Path("/")
            or str(_normalized_path(task_path)) != self.current_task_note.ref
        ):
            raise ValueError("current task note address must use a normalized absolute path")
        role_session_key = f"{self.lane}-{self.session_ref}"
        expected_vector = tuple(
            (key, kind)
            for key in (self.lane, role_session_key)
            for kind in ("claim", "epoch", "dispatch_binding")
        )
        observed_vector = tuple((item.key, item.kind) for item in self.lease_files)
        if observed_vector != expected_vector:
            raise ValueError("current claim position requires exact role/role-session vectors")
        if len({item.path for item in self.lease_files}) != len(self.lease_files):
            raise ValueError("current claim position lease paths must be unique")
        if len({str(Path(item.path).parent) for item in self.lease_files}) != 1:
            raise ValueError("current claim position lease files must share one cache root")
        expected_names = {
            "claim": lambda key: f"cc-active-task-{key}",
            "epoch": lambda key: f"cc-claim-epoch-{key}",
            "dispatch_binding": lambda key: f"cc-claim-dispatch-{key}.json",
        }
        if any(
            Path(item.path).name != expected_names[item.kind](item.key) for item in self.lease_files
        ):
            raise ValueError("current claim position lease paths must bind their kind and key")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"position_ref", "position_hash"},
        )
        expected = _self_hash(CURRENT_CLAIM_POSITION_SCHEMA, body)
        if self.position_hash != expected or self.position_ref != (
            f"current-claim-position@sha256:{expected}"
        ):
            raise ValueError("current claim position reference/hash do not bind its body")
        return self


def build_current_claim_position(
    snapshot: AppliedClaimPublicationSnapshot,
    ownership: AppliedClaimOwnershipProof,
    *,
    outcome_replay: OutcomeReplayResult,
) -> CurrentClaimPosition:
    """Project the task and both lease vectors from one sealed applied snapshot."""

    from shared.sdlc_claim import AppliedClaimPublicationSnapshot as SnapshotType

    checked_snapshot = _require_exact_type(
        snapshot,
        SnapshotType,
        "applied claim publication snapshot",
    )
    checked_ownership = AppliedClaimOwnershipProof.model_validate(
        _require_exact_type(
            ownership,
            AppliedClaimOwnershipProof,
            "applied claim ownership proof",
        ).model_dump(mode="json", by_alias=True)
    )
    checked_replay = OutcomeReplayResult.model_validate(
        _require_exact_type(
            outcome_replay,
            OutcomeReplayResult,
            "outcome replay result",
        ).model_dump(mode="json", by_alias=True)
    )
    checked_validity = checked_replay.validity
    receipt = checked_snapshot.receipt
    task = checked_snapshot.current_task
    leases = checked_snapshot.leases
    expected_identity = (
        receipt.task_id,
        receipt.role,
        receipt.session_id,
        receipt.claim_epoch,
    )
    if (
        checked_ownership.task_ref,
        checked_ownership.lane,
        checked_ownership.session_ref,
        checked_ownership.claim_epoch,
    ) != expected_identity or task.task_id != receipt.task_id:
        raise ExecutionAdmissionError(
            "current_claim_position_identity_mismatch",
            "resolve ownership and current position from one sealed applied publication",
            receipt.publication_id,
        )
    completion = checked_ownership.publication_completion_evidence
    if (
        checked_validity.decision != "valid"
        or checked_validity.subject_projection != checked_ownership.publication_outcome_projection
        or checked_validity.event_plane != completion.event_plane
        or checked_validity.resolver != completion.outcome_validity_resolver
        or checked_validity.source_frontier != completion.source_event_frontier
        or checked_replay.projection.snapshot_ref
        != checked_ownership.publication_outcome_projection.ref
        or checked_replay.projection.snapshot_hash
        != checked_ownership.publication_outcome_projection.sha256
    ):
        raise ExecutionAdmissionError(
            "current_claim_outcome_validity_mismatch",
            "bind current claim position to the exact valid publication outcome frontier",
            receipt.publication_id,
        )
    if (
        checked_ownership.publication_id != receipt.publication_id
        or checked_ownership.claim_publication_intent
        != ContentAddress(
            ref=checked_snapshot.intent.intent_ref,
            sha256=checked_snapshot.intent.intent_sha256,
        )
        or checked_ownership.receipt
        != ContentAddress(
            ref=str(receipt.receipt_path),
            sha256=_sha256(checked_snapshot.receipt_content),
        )
        or checked_ownership.manifest
        != ContentAddress(
            ref=str(receipt.manifest_path),
            sha256=_sha256(checked_snapshot.manifest_content),
        )
        or checked_ownership.claim_note_postimage_sha256 != receipt.claim_note_postimage_sha256
    ):
        raise ExecutionAdmissionError(
            "current_claim_position_ownership_mismatch",
            "derive current position from the exact ownership-bound publication snapshot",
            receipt.publication_id,
        )
    role_session_key = f"{checked_ownership.lane}-{checked_ownership.session_ref}"
    expected_keys = (checked_ownership.lane, role_session_key)
    if (
        len(leases) != 2
        or tuple(item.claim_key for item in leases) != expected_keys
        or leases[0].binding != leases[1].binding
        or any(
            (
                item.binding.task_id,
                item.binding.lane,
                item.binding.session_id,
                item.binding.claim_epoch,
            )
            != expected_identity
            for item in leases
        )
    ):
        raise ExecutionAdmissionError(
            "current_claim_position_lease_vector_mismatch",
            "restore the exact role and role-session lease vectors",
            receipt.publication_id,
        )
    lease_files = tuple(
        CurrentClaimLeaseFile(
            path=str(_normalized_path(path)),
            kind=kind,
            key=lease.claim_key,
            content_sha256=_sha256(content),
            mode=mode,
        )
        for lease in leases
        for kind, path, content, mode in (
            ("claim", lease.claim_path, lease.claim_content, lease.claim_mode),
            ("epoch", lease.epoch_path, lease.epoch_content, lease.epoch_mode),
            (
                "dispatch_binding",
                lease.binding_path,
                lease.binding_content,
                lease.binding_mode,
            ),
        )
    )
    current_task_note = ContentAddress(
        ref=str(_normalized_path(task.path)),
        sha256=task.sha256,
    )
    body: dict[str, object] = {
        "schema": CURRENT_CLAIM_POSITION_SCHEMA,
        "applied_claim_ownership": ContentAddress(
            ref=checked_ownership.proof_ref,
            sha256=checked_ownership.proof_hash,
        ),
        "current_task_note": current_task_note,
        "lease_files": lease_files,
        "task_ref": checked_ownership.task_ref,
        "lane": checked_ownership.lane,
        "session_ref": checked_ownership.session_ref,
        "claim_epoch": checked_ownership.claim_epoch,
        "may_authorize": False,
    }
    digest = _self_hash(CURRENT_CLAIM_POSITION_SCHEMA, body)
    return CurrentClaimPosition.model_validate(
        {
            **body,
            "position_ref": f"current-claim-position@sha256:{digest}",
            "position_hash": digest,
        }
    )


def _current_claim_position_address(position: CurrentClaimPosition) -> ContentAddress:
    return ContentAddress(ref=position.position_ref, sha256=position.position_hash)


def _require_current_claim_position(
    ownership: AppliedClaimOwnershipProof,
    current_task_note: ContentAddress,
    target: ExecutionTargetEvidence,
    position: CurrentClaimPosition | None,
    *,
    claim_resolution: AppliedClaimResolution | None,
    queried_at: str | datetime,
) -> AppliedClaimBasisResolution:
    ownership = AppliedClaimOwnershipProof.model_validate(
        _require_exact_type(
            ownership,
            AppliedClaimOwnershipProof,
            "applied claim ownership proof",
        ).model_dump(mode="json", by_alias=True)
    )
    current_task_note = ContentAddress.model_validate(
        _require_exact_type(
            current_task_note,
            ContentAddress,
            "current task note",
        ).model_dump(mode="json")
    )
    target = ExecutionTargetEvidence.model_validate(
        _require_exact_type(
            target,
            ExecutionTargetEvidence,
            "execution target evidence",
        ).model_dump(mode="json", by_alias=True)
    )
    if position is None:
        raise ExecutionAdmissionError(
            "current_claim_position_required",
            "resolve the current task and both claim lease vectors before applied-claim use",
            ownership.task_ref,
        )
    try:
        checked = CurrentClaimPosition.model_validate(
            _require_exact_type(
                position,
                CurrentClaimPosition,
                "current claim position",
            ).model_dump(mode="json", by_alias=True)
        )
    except Exception as exc:
        raise ExecutionAdmissionError(
            "current_claim_position_malformed",
            "restore the exact self-validating active claim position",
            type(exc).__name__,
        ) from exc
    if claim_resolution is None:
        raise ExecutionAdmissionError(
            "current_claim_resolution_required",
            "re-resolve the applied claim and outcome frontier at the use time",
            ownership.task_ref,
        )
    try:
        checked_resolution = _require_exact_type(
            claim_resolution,
            AppliedClaimResolution,
            "applied claim resolution",
        )
        live = checked_resolution.resolve_basis(queried_at=queried_at)
        _require_exact_type(
            live,
            AppliedClaimBasisResolution,
            "applied claim basis resolution",
        )
    except ExecutionAdmissionError:
        raise
    except Exception as exc:
        raise ExecutionAdmissionError(
            "current_claim_resolution_malformed",
            "restore the exact live applied-claim resolver",
            type(exc).__name__,
        ) from exc
    ownership_address = ContentAddress(
        ref=ownership.proof_ref,
        sha256=ownership.proof_hash,
    )
    if (
        checked.applied_claim_ownership != ownership_address
        or checked.current_task_note != current_task_note
        or checked.task_ref != ownership.task_ref
        or checked.lane != ownership.lane
        or checked.session_ref != ownership.session_ref
        or checked.claim_epoch != ownership.claim_epoch
        or target.host_scoped_claim != _current_claim_position_address(checked)
        or live.ownership != ownership
        or live.current_task_note != current_task_note
        or live.current_position != checked
    ):
        raise ExecutionAdmissionError(
            "current_claim_position_mismatch",
            "rebuild the target from the exact current ownership, task, and lease position",
            ownership.task_ref,
        )
    return live


def parse_protected_claim_coordinates_record(
    value: Mapping[str, object],
) -> HistoricalProtectedClaimCoordinatesV1 | ProtectedClaimCoordinates:
    """Parse exact historical-v1 or active-v2 coordinates without upgrading."""

    schema = value.get("schema")
    if schema == HISTORICAL_PROTECTED_CLAIM_COORDINATES_SCHEMA:
        return HistoricalProtectedClaimCoordinatesV1.model_validate(value)
    if schema == PROTECTED_CLAIM_COORDINATES_SCHEMA:
        return ProtectedClaimCoordinates.model_validate(value)
    raise ExecutionAdmissionError(
        "protected_claim_coordinates_schema_unknown",
        "supply exact historical-v1 or active-v2 coordinate bytes",
        str(schema),
    )


def parse_execution_invocation_envelope_record(
    value: Mapping[str, object],
) -> HistoricalExecutionInvocationEnvelopeV1 | ExecutionInvocationEnvelope:
    """Parse exact historical-v1 or active-v2 envelopes without upgrading."""

    schema = value.get("schema")
    if schema == HISTORICAL_EXECUTION_INVOCATION_ENVELOPE_SCHEMA:
        return HistoricalExecutionInvocationEnvelopeV1.model_validate(value)
    if schema == EXECUTION_INVOCATION_ENVELOPE_SCHEMA:
        return ExecutionInvocationEnvelope.model_validate(value)
    raise ExecutionAdmissionError(
        "execution_invocation_envelope_schema_unknown",
        "supply exact historical-v1 or active-v2 envelope bytes",
        str(schema),
    )


def parse_applied_claim_ownership_record(
    value: Mapping[str, object],
) -> HistoricalAppliedClaimOwnershipProofV3 | AppliedClaimOwnershipProof:
    """Parse exact historical-v3 or active-v7 ownership without upgrading."""

    schema = value.get("schema")
    if schema == HISTORICAL_APPLIED_CLAIM_OWNERSHIP_SCHEMA:
        return HistoricalAppliedClaimOwnershipProofV3.model_validate(value)
    if schema == APPLIED_CLAIM_OWNERSHIP_SCHEMA:
        return AppliedClaimOwnershipProof.model_validate(value)
    raise ExecutionAdmissionError(
        "applied_claim_ownership_schema_unknown",
        "supply exact historical-v3 or active-v7 ownership bytes",
        str(schema),
    )


class DependencyClosureEvidence(_FrozenModel):
    schema_id: Literal["hapax.dependency-closure-evidence.v1"] = Field(alias="schema")
    closure_ref: str
    closure_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_descriptor_leaf: str
    dependency_refs: tuple[str, ...] = Field(min_length=1)
    independent_failure_domain_refs: tuple[str, ...] = Field(min_length=1)
    required_independent_fulfillments: int = Field(ge=1, strict=True)
    provisioned_independent_fulfillments: int = Field(ge=0, strict=True)
    redundancy_satisfied: bool = Field(strict=True)
    source_receipt_refs: tuple[str, ...] = Field(min_length=1)
    observed_at: str
    checked_at: str
    stale_after: str
    may_authorize: Literal[False]

    @field_validator("closure_ref", "selected_descriptor_leaf")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("dependency_refs", "independent_failure_domain_refs", "source_receipt_refs")
    @classmethod
    def validate_sets(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _string_set(value)

    @field_validator("observed_at", "checked_at", "stale_after")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_closure(self) -> Self:
        if not self.observed_at <= self.checked_at < self.stale_after:
            raise ValueError("dependency closure timestamps are not usable")
        enough = self.provisioned_independent_fulfillments >= self.required_independent_fulfillments
        if self.redundancy_satisfied != enough:
            raise ValueError("redundancy verdict differs from the K-of-N evidence")
        if self.provisioned_independent_fulfillments > len(self.independent_failure_domain_refs):
            raise ValueError("provisioned fulfillments exceed named failure domains")
        body = self.model_dump(mode="json", by_alias=True, exclude={"closure_ref", "closure_hash"})
        expected = _self_hash(DEPENDENCY_CLOSURE_SCHEMA, body)
        if (
            self.closure_hash != expected
            or self.closure_ref != f"dependency-closure@sha256:{expected}"
        ):
            raise ValueError("dependency closure reference/hash do not bind its body")
        return self


def build_dependency_closure_evidence(
    *,
    selected_descriptor_leaf: str,
    dependency_refs: Sequence[str],
    independent_failure_domain_refs: Sequence[str],
    required_independent_fulfillments: int,
    provisioned_independent_fulfillments: int,
    source_receipt_refs: Sequence[str],
    observed_at: str | datetime,
    checked_at: str | datetime,
    stale_after: str | datetime,
) -> DependencyClosureEvidence:
    body: dict[str, object] = {
        "schema": DEPENDENCY_CLOSURE_SCHEMA,
        "selected_descriptor_leaf": _nonblank(selected_descriptor_leaf),
        "dependency_refs": tuple(sorted(set(dependency_refs))),
        "independent_failure_domain_refs": tuple(sorted(set(independent_failure_domain_refs))),
        "required_independent_fulfillments": required_independent_fulfillments,
        "provisioned_independent_fulfillments": provisioned_independent_fulfillments,
        "redundancy_satisfied": (
            provisioned_independent_fulfillments >= required_independent_fulfillments
        ),
        "source_receipt_refs": tuple(sorted(set(source_receipt_refs))),
        "observed_at": _canonical_timestamp(observed_at),
        "checked_at": _canonical_timestamp(checked_at),
        "stale_after": _canonical_timestamp(stale_after),
        "may_authorize": False,
    }
    digest = _self_hash(DEPENDENCY_CLOSURE_SCHEMA, body)
    return DependencyClosureEvidence.model_validate(
        {
            **body,
            "closure_ref": f"dependency-closure@sha256:{digest}",
            "closure_hash": digest,
        }
    )


class QuotaReservationEvidence(_FrozenModel):
    schema_id: Literal["hapax.quota-reservation-evidence.v1"] = Field(alias="schema")
    reservation_ref: str
    reservation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["reserved", "not_applicable"]
    route_leaf: str
    idempotency_key: str
    post_reservation_headroom: str | None
    reserve_floor: str | None
    unit: str | None
    reason_refs: tuple[str, ...]
    source_receipt_refs: tuple[str, ...] = Field(min_length=1)
    reserved_at: str
    expires_at: str
    may_authorize: Literal[False]

    @field_validator("reservation_ref", "route_leaf", "idempotency_key")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("unit")
    @classmethod
    def validate_optional_string(cls, value: str | None) -> str | None:
        return None if value is None else _nonblank(value)

    @field_validator("reason_refs", "source_receipt_refs")
    @classmethod
    def validate_sets(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _string_set(value, allow_empty=info.field_name == "reason_refs")

    @field_validator("reserved_at", "expires_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_reservation(self) -> Self:
        if self.reserved_at >= self.expires_at:
            raise ValueError("quota reservation requires a future expiry")
        if self.status == "reserved":
            if (
                self.post_reservation_headroom is None
                or self.reserve_floor is None
                or self.unit is None
                or self.reason_refs
            ):
                raise ValueError("reserved quota requires headroom/floor/unit and no N/A reason")
            try:
                headroom = Decimal(self.post_reservation_headroom)
                floor = Decimal(self.reserve_floor)
            except InvalidOperation as exc:
                raise ValueError("quota values must be canonical decimals") from exc
            if headroom < floor:
                raise ValueError("post-reservation headroom falls below the reserve floor")
        elif (
            self.post_reservation_headroom is not None
            or self.reserve_floor is not None
            or self.unit is not None
            or not self.reason_refs
        ):
            raise ValueError("not-applicable quota requires only explicit reason evidence")
        body = self.model_dump(
            mode="json", by_alias=True, exclude={"reservation_ref", "reservation_hash"}
        )
        expected = _self_hash(QUOTA_RESERVATION_SCHEMA, body)
        if (
            self.reservation_hash != expected
            or self.reservation_ref != f"quota-reservation@sha256:{expected}"
        ):
            raise ValueError("quota reservation reference/hash do not bind its body")
        return self


def build_quota_reservation_evidence(
    *,
    status: Literal["reserved", "not_applicable"],
    route_leaf: str,
    idempotency_key: str,
    source_receipt_refs: Sequence[str],
    reserved_at: str | datetime,
    expires_at: str | datetime,
    post_reservation_headroom: str | None = None,
    reserve_floor: str | None = None,
    unit: str | None = None,
    reason_refs: Sequence[str] = (),
) -> QuotaReservationEvidence:
    body: dict[str, object] = {
        "schema": QUOTA_RESERVATION_SCHEMA,
        "status": status,
        "route_leaf": _nonblank(route_leaf),
        "idempotency_key": _nonblank(idempotency_key),
        "post_reservation_headroom": post_reservation_headroom,
        "reserve_floor": reserve_floor,
        "unit": unit,
        "reason_refs": tuple(sorted(set(reason_refs))),
        "source_receipt_refs": tuple(sorted(set(source_receipt_refs))),
        "reserved_at": _canonical_timestamp(reserved_at),
        "expires_at": _canonical_timestamp(expires_at),
        "may_authorize": False,
    }
    digest = _self_hash(QUOTA_RESERVATION_SCHEMA, body)
    return QuotaReservationEvidence.model_validate(
        {
            **body,
            "reservation_ref": f"quota-reservation@sha256:{digest}",
            "reservation_hash": digest,
        }
    )


class ExecutionTargetEvidence(_FrozenModel):
    schema_id: Literal["hapax.execution-target-evidence.v1"] = Field(alias="schema")
    target_ref: str
    target_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_host: str
    selected_descriptor_leaf: str
    host_scoped_claim: ContentAddress
    effect_manifest: ContentAddress
    executor_descriptor: ContentAddress
    executor_registry_projection: ContentAddress
    executor: ContentAddress
    adapter: ContentAddress
    harness: ContentAddress
    runtime_identity: ContentAddress
    active_generation_roots: tuple[ContentAddress, ...] = Field(min_length=1)
    environment_observation: ContentAddress
    observed_at: str
    checked_at: str
    stale_after: str
    may_authorize: Literal[False]

    @field_validator("target_ref", "execution_host", "selected_descriptor_leaf")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("observed_at", "checked_at", "stale_after")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @field_validator("active_generation_roots")
    @classmethod
    def validate_generation_roots(
        cls,
        value: tuple[ContentAddress, ...],
    ) -> tuple[ContentAddress, ...]:
        return _content_address_set(value)

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        if not self.observed_at <= self.checked_at < self.stale_after:
            raise ValueError("execution target timestamps are not usable")
        body = self.model_dump(mode="json", by_alias=True, exclude={"target_ref", "target_hash"})
        expected = _self_hash(EXECUTION_TARGET_SCHEMA, body)
        if self.target_hash != expected or self.target_ref != f"execution-target@sha256:{expected}":
            raise ValueError("execution target reference/hash do not bind its body")
        return self


def build_execution_target_evidence(
    *,
    host_scoped_claim: ContentAddress,
    effect_manifest: EffectManifest,
    executor_descriptor: ExecutorDescriptor,
    executor_registry_projection: ExecutorRegistryProjection,
    environment_observation: ContentAddress,
    observed_at: str | datetime,
    checked_at: str | datetime,
    stale_after: str | datetime,
) -> ExecutionTargetEvidence:
    manifest = EffectManifest.model_validate(effect_manifest.model_dump(mode="json", by_alias=True))
    descriptor = ExecutorDescriptor.model_validate(
        executor_descriptor.model_dump(mode="json", by_alias=True)
    )
    projection = ExecutorRegistryProjection.model_validate(
        executor_registry_projection.model_dump(mode="json", by_alias=True)
    )
    descriptor_address = ContentAddress(
        ref=descriptor.descriptor_ref,
        sha256=descriptor.descriptor_hash,
    )
    if (
        projection.execution_host != descriptor.execution_host
        or descriptor_address not in projection.descriptors
    ):
        raise ExecutionAdmissionError(
            "execution_target_registry_mismatch",
            "resolve the executor from one exact host-scoped registry projection",
        )
    observed = _canonical_timestamp(observed_at)
    checked = _canonical_timestamp(checked_at)
    requested_stale_after = _canonical_timestamp(stale_after)
    if observed < projection.observed_at or checked < projection.checked_at:
        raise ExecutionAdmissionError(
            "execution_target_predates_registry_projection",
            "observe the host target after resolving the exact current registry projection",
        )
    effective_stale_after = min(requested_stale_after, projection.stale_after)
    body: dict[str, object] = {
        "schema": EXECUTION_TARGET_SCHEMA,
        "execution_host": descriptor.execution_host,
        "selected_descriptor_leaf": descriptor.selected_descriptor_leaf,
        "host_scoped_claim": host_scoped_claim,
        "effect_manifest": ContentAddress(
            ref=manifest.manifest_ref,
            sha256=manifest.manifest_hash,
        ),
        "executor_descriptor": descriptor_address,
        "executor_registry_projection": ContentAddress(
            ref=projection.projection_ref,
            sha256=projection.projection_hash,
        ),
        "executor": descriptor.executor,
        "adapter": descriptor.adapter,
        "harness": descriptor.harness,
        "runtime_identity": descriptor.runtime_identity,
        "active_generation_roots": descriptor.active_generation_roots,
        "environment_observation": environment_observation,
        "observed_at": observed,
        "checked_at": checked,
        "stale_after": effective_stale_after,
        "may_authorize": False,
    }
    digest = _self_hash(EXECUTION_TARGET_SCHEMA, body)
    return ExecutionTargetEvidence.model_validate(
        {
            **body,
            "target_ref": f"execution-target@sha256:{digest}",
            "target_hash": digest,
        }
    )


class ExecutionAdmission(_FrozenModel):
    """Non-authorizing decision evidence for one exact action and position."""

    schema_id: Literal["hapax.execution-admission.v1"] = Field(alias="schema")
    admission_ref: str
    admission_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["admit", "hold", "refuse"]
    lease_eligible: bool = Field(strict=True)
    task_ref: str
    lane: str
    session_ref: str
    authority_case: str
    intent: ContentAddress
    effect_manifest: ContentAddress
    authority_grant: ContentAddress | None
    authority_trust_query: ExecutionTrustQuery | None
    authority_trust_envelope: ExecutionTrustEnvelope | None
    task_note: ContentAddress
    parent_spec: ContentAddress
    decomposition: ContentAddress
    context_frame: ContentAddress
    context_position: ContentAddress
    canon_bundle: ContentAddress
    canon_image: ContentAddress
    impingement_trace: ContentAddress
    fact_frontier: ContentAddress
    context_selection: ContentAddress
    audience_seal_receipt: ContentAddress
    claim_publication_intent: ContentAddress
    demand_vector: ContentAddress | None
    demand_derivation_receipt: ContentAddress | None
    supply_vector: ContentAddress | None
    supply_refresh_receipt: ContentAddress | None
    route_decision: ContentAddress | None
    selected_descriptor_leaf: str | None
    dependency_closure: ContentAddress | None
    quota_reservation: ContentAddress | None
    execution_target: ContentAddress | None
    dispatch_message_id: str
    idempotency_key: str
    authorized_flags: tuple[str, ...]
    immutable_scope_refs: tuple[str, ...]
    issued_at: str
    valid_until: str
    supersession_frontier_ref: str
    supersedes_refs: tuple[str, ...]
    reason_codes: tuple[str, ...]
    repair_refs: tuple[str, ...]
    may_authorize: Literal[False]
    authorizes_operator: Literal[False]

    @field_validator(
        "admission_ref",
        "task_ref",
        "lane",
        "session_ref",
        "authority_case",
        "dispatch_message_id",
        "idempotency_key",
        "supersession_frontier_ref",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("selected_descriptor_leaf")
    @classmethod
    def validate_optional_string(cls, value: str | None) -> str | None:
        return None if value is None else _nonblank(value)

    @field_validator(
        "authorized_flags",
        "immutable_scope_refs",
        "supersedes_refs",
        "reason_codes",
        "repair_refs",
    )
    @classmethod
    def validate_sets(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _string_set(
            value,
            allow_empty=info.field_name
            in {
                "authorized_flags",
                "immutable_scope_refs",
                "supersedes_refs",
                "reason_codes",
                "repair_refs",
            },
        )

    @field_validator("issued_at", "valid_until")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_admission(self) -> Self:
        required_evidence = (
            self.authority_grant,
            self.authority_trust_query,
            self.authority_trust_envelope,
            self.demand_vector,
            self.demand_derivation_receipt,
            self.supply_vector,
            self.supply_refresh_receipt,
            self.route_decision,
            self.dependency_closure,
            self.quota_reservation,
            self.execution_target,
        )
        if self.decision == "admit":
            if (
                not self.lease_eligible
                or any(item is None for item in required_evidence)
                or self.selected_descriptor_leaf is None
                or not self.authorized_flags
                or self.reason_codes
                or self.repair_refs
                or self.issued_at >= self.valid_until
            ):
                raise ValueError("admitted execution requires complete current evidence")
            if (
                self.authority_trust_query is None
                or self.authority_trust_envelope is None
                or self.authority_trust_envelope.query
                != ContentAddress(
                    ref=self.authority_trust_query.query_ref,
                    sha256=self.authority_trust_query.query_hash,
                )
                or self.authority_trust_envelope.decision != "trusted"
                or self.issued_at != self.authority_trust_query.queried_at
                or self.valid_until > self.authority_trust_envelope.stale_after
            ):
                raise ValueError("admitted execution requires exact current authority trust")
        elif (
            self.lease_eligible
            or not self.reason_codes
            or not self.repair_refs
            or len(self.reason_codes) != len(self.repair_refs)
        ):
            raise ValueError("held/refused execution must carry a non-authorizing repair set")
        if self.repair_refs != tuple(f"repair:{reason}" for reason in self.reason_codes):
            raise ValueError("execution admission repairs must correspond exactly to reasons")
        body = self.model_dump(
            mode="json", by_alias=True, exclude={"admission_ref", "admission_hash"}
        )
        expected = _self_hash(EXECUTION_ADMISSION_SCHEMA, body)
        if (
            self.admission_hash != expected
            or self.admission_ref != f"execution-admission@sha256:{expected}"
        ):
            raise ValueError("execution admission reference/hash do not bind its body")
        return self


def _admission_content(
    *,
    intent: ActionIntent,
    authority: ValidAuthorityGrant | AuthorityHold,
    authority_trust_query: ExecutionTrustQuery | None,
    authority_trust_envelope: ExecutionTrustEnvelope | None,
    frame: ContextFrame,
    trace: EpistemicImpingementTrace,
    task_note: ContentAddress,
    fact_frontier: ContentAddress,
    context_selection: ContextSelection,
    audience_seal_receipt: ContentAddress,
    claim_publication_intent: ContentAddress,
    demand_derivation_receipt: ContentAddress | None,
    supply_refresh_receipt: ContentAddress | None,
    request: DispatchRequest,
    decision: RouteDecision,
    dependency_closure: DependencyClosureEvidence | None,
    quota_reservation: QuotaReservationEvidence | None,
    execution_target: ExecutionTargetEvidence | None,
) -> dict[str, object]:
    position = frame.position
    route_ref = content_address(decision.decision_id, decision)
    demand_ref = (
        content_address(
            f"demand-vector:{request.demand_vector.work_item.task_id}",
            request.demand_vector,
        )
        if request.demand_vector is not None
        else None
    )
    supply_ref = (
        content_address(
            f"supply-vector:{request.supply_vector.route.route_id}",
            request.supply_vector,
        )
        if request.supply_vector is not None
        else None
    )
    return {
        "task_ref": frame.task_ref,
        "lane": request.lane,
        "session_ref": frame.session_ref,
        "authority_case": position.authority_case,
        "intent": ContentAddress(ref=intent.intent_ref, sha256=intent.intent_hash),
        "effect_manifest": intent.effect_manifest,
        "authority_grant": (
            ContentAddress(ref=authority.grant_ref, sha256=authority.grant_hash)
            if isinstance(authority, ValidAuthorityGrant)
            else None
        ),
        "authority_trust_query": (
            None
            if authority_trust_query is None
            else authority_trust_query.model_dump(mode="json", by_alias=True)
        ),
        "authority_trust_envelope": (
            None
            if authority_trust_envelope is None
            else authority_trust_envelope.model_dump(mode="json", by_alias=True)
        ),
        "task_note": task_note,
        "parent_spec": intent.parent_spec,
        "decomposition": intent.decomposition,
        "context_frame": ContentAddress(ref=frame.frame_ref, sha256=frame.frame_hash),
        "context_position": ContentAddress(
            ref=position.position_ref, sha256=position.position_hash
        ),
        "canon_bundle": ContentAddress(
            ref=position.canon_bundle_ref, sha256=position.canon_bundle_hash
        ),
        "canon_image": ContentAddress(
            ref=f"canon-image:{frame.canon_image.canon_id}",
            sha256=frame.canon_image.image_hash,
        ),
        "impingement_trace": ContentAddress(ref=trace.trace_ref, sha256=trace.trace_hash),
        "fact_frontier": fact_frontier,
        "context_selection": ContentAddress(
            ref=context_selection.selection_ref,
            sha256=context_selection.selection_hash,
        ),
        "audience_seal_receipt": audience_seal_receipt,
        "claim_publication_intent": claim_publication_intent,
        "demand_vector": demand_ref,
        "demand_derivation_receipt": demand_derivation_receipt,
        "supply_vector": supply_ref,
        "supply_refresh_receipt": supply_refresh_receipt,
        "route_decision": route_ref,
        "selected_descriptor_leaf": (
            decision.selected_descriptor_leaf or f"{decision.route_id}#base"
        ),
        "dependency_closure": (
            ContentAddress(
                ref=dependency_closure.closure_ref, sha256=dependency_closure.closure_hash
            )
            if dependency_closure is not None
            else None
        ),
        "quota_reservation": (
            ContentAddress(
                ref=quota_reservation.reservation_ref,
                sha256=quota_reservation.reservation_hash,
            )
            if quota_reservation is not None
            else None
        ),
        "execution_target": (
            ContentAddress(ref=execution_target.target_ref, sha256=execution_target.target_hash)
            if execution_target is not None
            else None
        ),
        "authorized_flags": (
            authority.authorized_flags if isinstance(authority, ValidAuthorityGrant) else ()
        ),
        "immutable_scope_refs": intent.requested_scope_refs,
    }


def admit_execution(
    intent: ActionIntent,
    authority: ValidAuthorityGrant | AuthorityHold,
    frame: ContextFrame,
    trace: EpistemicImpingementTrace,
    *,
    task_note: ContentAddress,
    fact_frontier: ContentAddress,
    context_selection: ContextSelection,
    audience_seal_receipt: ContentAddress,
    claim_publication_intent: ContentAddress,
    demand_derivation_receipt: ContentAddress | None,
    supply_refresh_receipt: ContentAddress | None,
    request: DispatchRequest,
    decision: RouteDecision,
    dependency_closure: DependencyClosureEvidence | None,
    quota_reservation: QuotaReservationEvidence | None,
    execution_target: ExecutionTargetEvidence | None,
    dispatch_message_id: str,
    idempotency_key: str,
    supersession_frontier_ref: str,
    now: str | datetime,
    supersedes_refs: Sequence[str] = (),
    trust_resolver: ExecutionTrustResolver | None = None,
    manifest_resolver: EffectManifestResolver | None = None,
) -> ExecutionAdmission:
    """Evaluate one action without granting authority or issuing a lease."""

    try:
        intent = ActionIntent.model_validate(intent.model_dump(mode="json", by_alias=True))
        if isinstance(authority, ValidAuthorityGrant):
            authority = ValidAuthorityGrant.model_validate(
                authority.model_dump(mode="json", by_alias=True)
            )
        elif isinstance(authority, AuthorityHold):
            authority = AuthorityHold.model_validate(
                authority.model_dump(mode="json", by_alias=True)
            )
        else:
            raise TypeError("authority must be a typed grant or hold")
        frame = ContextFrame.model_validate(frame.model_dump(mode="json", by_alias=True))
        trace = EpistemicImpingementTrace.model_validate(
            trace.model_dump(mode="json", by_alias=True)
        )
        context_selection = ContextSelection.model_validate(
            context_selection.model_dump(mode="json", by_alias=True)
        )
        decision = RouteDecision.model_validate(decision.model_dump(mode="json"))
        request = DispatchRequest.model_validate(request.model_dump(mode="json"))
        task_note = ContentAddress.model_validate(task_note.model_dump(mode="json"))
        fact_frontier = ContentAddress.model_validate(fact_frontier.model_dump(mode="json"))
        audience_seal_receipt = ContentAddress.model_validate(
            audience_seal_receipt.model_dump(mode="json")
        )
        claim_publication_intent = ContentAddress.model_validate(
            claim_publication_intent.model_dump(mode="json")
        )
        if demand_derivation_receipt is not None:
            demand_derivation_receipt = ContentAddress.model_validate(
                demand_derivation_receipt.model_dump(mode="json")
            )
        if supply_refresh_receipt is not None:
            supply_refresh_receipt = ContentAddress.model_validate(
                supply_refresh_receipt.model_dump(mode="json")
            )
        if dependency_closure is not None:
            dependency_closure = DependencyClosureEvidence.model_validate(
                dependency_closure.model_dump(mode="json", by_alias=True)
            )
        if quota_reservation is not None:
            quota_reservation = QuotaReservationEvidence.model_validate(
                quota_reservation.model_dump(mode="json", by_alias=True)
            )
        if execution_target is not None:
            execution_target = ExecutionTargetEvidence.model_validate(
                execution_target.model_dump(mode="json", by_alias=True)
            )
    except Exception as exc:
        raise ExecutionAdmissionError(
            "execution_admission_input_malformed",
            "restore the exact self-validating intent, frame, ContextSelection, route request, "
            "and decision",
            type(exc).__name__,
        ) from exc
    checked_at = _canonical_timestamp(now)
    position = frame.position
    reasons: list[str] = []
    admission_authority_trust_query: ExecutionTrustQuery | None = None
    admission_authority_trust_envelope: ExecutionTrustEnvelope | None = None
    if isinstance(authority, AuthorityHold):
        reasons.extend(f"authority:{reason}" for reason in authority.reason_codes)
    else:
        if (
            authority.intent_ref != intent.intent_ref
            or authority.intent_hash != intent.intent_hash
            or authority.position_ref != position.position_ref
            or authority.position_hash != position.position_hash
            or authority.task_ref != frame.task_ref
            or authority.authority_case != position.authority_case
            or authority.acting_subject != intent.acting_subject
            or authority.supersession_frontier_ref != supersession_frontier_ref
            or not authority.issued_at <= checked_at < authority.valid_until
        ):
            reasons.append("valid_authority_grant_mismatch_or_stale")
        try:
            admission_authority_trust_query = build_execution_trust_query(
                trust_class=authority.authority_trust_query.trust_class,
                subject_roots=authority.authority_trust_query.subject_roots,
                presented_receipt=authority.authority_trust_query.presented_receipt,
                required_roots=authority.authority_trust_query.required_roots,
                supersession_frontier_ref=authority.supersession_frontier_ref,
                queried_at=checked_at,
            )
            admission_authority_trust_envelope = _seal_execution_trust_resolver(
                trust_resolver
            ).require_trusted(admission_authority_trust_query)
        except ExecutionAdmissionError as exc:
            reasons.append(f"authority:{exc.reason_code}")
    if (
        intent.task_ref != frame.task_ref
        or intent.position_ref != position.position_ref
        or intent.position_hash != position.position_hash
    ):
        reasons.append("action_intent_position_mismatch")
    exact_position_flags = tuple(
        sorted(item.name for item in position.authorized_flags if item.authorized)
    )
    if intent.required_authorization_flags != exact_position_flags:
        reasons.append("action_intent_authorization_flags_not_exact")
    try:
        admitted_manifest = _seal_effect_manifest_resolver(manifest_resolver).resolve(
            intent.effect_manifest
        )
        if (
            admitted_manifest.operation != intent.operation
            or admitted_manifest.capability_role != intent.capability_role
            or admitted_manifest.execution_host != intent.execution_host
            or admitted_manifest.mutating != intent.mutating
            or admitted_manifest.scope_refs != intent.requested_scope_refs
            or admitted_manifest.effect_targets != intent.requested_effect_targets
        ):
            reasons.append("action_intent_effect_manifest_not_exact")
    except ExecutionAdmissionError as exc:
        reasons.append(exc.reason_code)
    if not frame.checked_at <= checked_at < frame.stale_after:
        reasons.append("context_frame_stale")
    try:
        require_current_epistemic_trace(trace, position, now=checked_at)
    except EpistemicImpingementError as exc:
        reasons.append(exc.reason_code)
    if trace.fact_frontier_ref != fact_frontier.ref:
        reasons.append("fact_frontier_mismatch")
    selection_checked_at = _canonical_timestamp(context_selection.checked_at)
    selection_stale_after = _canonical_timestamp(context_selection.stale_after)
    if (
        context_selection.position_ref != position.position_ref
        or context_selection.position_hash != position.position_hash
    ):
        reasons.append("context_selection_position_mismatch")
    if (
        context_selection.fact_frontier_ref != fact_frontier.ref
        or context_selection.fact_frontier_hash != fact_frontier.sha256
    ):
        reasons.append("context_selection_fact_frontier_mismatch")
    if (
        context_selection.frontier_fact_refs != trace.fact_refs
        or context_selection.event_frontier_refs != trace.source_event_refs
    ):
        reasons.append("context_selection_trace_frontier_mismatch")
    if (
        context_selection.audience_seal_receipt_ref != audience_seal_receipt.ref
        or context_selection.audience_seal_receipt_hash != audience_seal_receipt.sha256
    ):
        reasons.append("context_selection_audience_seal_mismatch")
    if (
        context_selection.audience_policy_generation != frame.audience_policy_generation
        or context_selection.privacy_policy_generation != frame.privacy_policy_generation
    ):
        reasons.append("context_selection_policy_generation_mismatch")
    if context_selection.audience != "hapax_substrate":
        reasons.append("context_selection_wrong_audience")
    if context_selection.state.value_state != "present":
        reasons.append("context_selection_hold")
    if not (
        max(_canonical_timestamp(frame.checked_at), trace.checked_at)
        <= selection_checked_at
        <= checked_at
        < selection_stale_after
    ):
        reasons.append("context_selection_stale")
    action = next((item for item in frame.actions if item.action_id == intent.action_id), None)
    if (
        action is None
        or action.disposition != "legal"
        or action.position_ref != position.position_ref
        or action.action_class != intent.action_class
        or action.operation != intent.operation
        or action.admission_ref != intent.lifecycle_admission_ref
        or action.transition_to != intent.lifecycle_transition_to
        or action.transition_edge != intent.lifecycle_transition_edge
    ):
        reasons.append("context_action_not_legal_for_position")
    if position.claim_ref != claim_publication_intent.ref:
        reasons.append("claim_publication_intent_mismatch")
    if (
        request.task_id != frame.task_ref
        or request.lane != decision.lane
        or request.platform != decision.platform
        or request.mode != decision.mode
        or request.profile != decision.profile
        or request.route_id != decision.route_id
        or request.authority_case != position.authority_case
        or decision.task_id != frame.task_ref
        or decision.decision_id != position.route_decision_ref
        or (
            decision.local_execution_target is not None
            and decision.local_execution_target != intent.execution_host
        )
    ):
        reasons.append("route_decision_position_mismatch")
    if decision.action is not DispatchAction.LAUNCH or not decision.launch_allowed:
        reasons.append("route_decision_not_launch")
    selected_leaf = decision.selected_descriptor_leaf or f"{decision.route_id}#base"
    if request.demand_vector is None:
        reasons.append("demand_vector_missing")
    elif (
        set(request.demand_vector.mutation_scope_refs) != set(intent.requested_scope_refs)
        or request.demand_vector.work_item.task_id != frame.task_ref
    ):
        reasons.append("demand_vector_intent_mismatch")
    if demand_derivation_receipt is None:
        reasons.append("demand_derivation_receipt_missing")
    if request.supply_vector is None:
        reasons.append("supply_vector_missing")
    elif request.supply_vector.route.route_id != decision.route_id:
        reasons.append("supply_vector_route_mismatch")
    if supply_refresh_receipt is None:
        reasons.append("supply_refresh_receipt_missing")
    if dependency_closure is None:
        reasons.append("dependency_closure_missing")
    else:
        if dependency_closure.selected_descriptor_leaf != selected_leaf:
            reasons.append("dependency_closure_leaf_mismatch")
        if (
            not dependency_closure.redundancy_satisfied
            or not dependency_closure.checked_at <= checked_at < dependency_closure.stale_after
        ):
            reasons.append("dependency_closure_unsatisfied_or_stale")
    if quota_reservation is None:
        reasons.append("quota_reservation_missing")
    else:
        if (
            quota_reservation.route_leaf != selected_leaf
            or quota_reservation.idempotency_key != idempotency_key
            or not quota_reservation.reserved_at <= checked_at < quota_reservation.expires_at
        ):
            reasons.append("quota_reservation_mismatch_or_stale")
    if execution_target is None:
        reasons.append("execution_target_missing")
    else:
        if (
            execution_target.execution_host != intent.execution_host
            or execution_target.selected_descriptor_leaf != selected_leaf
            or execution_target.effect_manifest != intent.effect_manifest
            or not execution_target.checked_at <= checked_at < execution_target.stale_after
        ):
            reasons.append("execution_target_mismatch_or_stale")

    values = _admission_content(
        intent=intent,
        authority=authority,
        authority_trust_query=admission_authority_trust_query,
        authority_trust_envelope=admission_authority_trust_envelope,
        frame=frame,
        trace=trace,
        task_note=task_note,
        fact_frontier=fact_frontier,
        context_selection=context_selection,
        audience_seal_receipt=audience_seal_receipt,
        claim_publication_intent=claim_publication_intent,
        demand_derivation_receipt=demand_derivation_receipt,
        supply_refresh_receipt=supply_refresh_receipt,
        request=request,
        decision=decision,
        dependency_closure=dependency_closure,
        quota_reservation=quota_reservation,
        execution_target=execution_target,
    )
    horizons = [
        frame.stale_after,
        trace.stale_after,
        selection_stale_after,
        *([authority.valid_until] if isinstance(authority, ValidAuthorityGrant) else []),
        *(
            [admission_authority_trust_envelope.stale_after]
            if admission_authority_trust_envelope is not None
            else []
        ),
        *([dependency_closure.stale_after] if dependency_closure is not None else []),
        *([quota_reservation.expires_at] if quota_reservation is not None else []),
        *([execution_target.stale_after] if execution_target is not None else []),
    ]
    decision_value = "admit" if not reasons else "hold"
    reason_set = tuple(sorted(set(reasons)))
    body: dict[str, object] = {
        "schema": EXECUTION_ADMISSION_SCHEMA,
        "decision": decision_value,
        "lease_eligible": not reason_set,
        **values,
        "dispatch_message_id": _nonblank(dispatch_message_id),
        "idempotency_key": _nonblank(idempotency_key),
        "issued_at": checked_at,
        "valid_until": min(horizons) if horizons else checked_at,
        "supersession_frontier_ref": _nonblank(supersession_frontier_ref),
        "supersedes_refs": tuple(sorted(set(supersedes_refs))),
        "reason_codes": reason_set,
        "repair_refs": tuple(f"repair:{reason}" for reason in reason_set),
        "may_authorize": False,
        "authorizes_operator": False,
    }
    digest = _self_hash(EXECUTION_ADMISSION_SCHEMA, body)
    return ExecutionAdmission.model_validate(
        {
            **body,
            "admission_ref": f"execution-admission@sha256:{digest}",
            "admission_hash": digest,
        }
    )


class HistoricalExecutionLeaseV1(_FrozenModel):
    """Non-authorizing reader for historical v1 lease receipts."""

    schema_id: Literal["hapax.execution-lease.v1"] = Field(alias="schema")
    lease_ref: str
    lease_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    admission: ContentAddress
    authority_grant: ContentAddress
    applied_claim: ContentAddress
    task_ref: str
    lane: str
    session_ref: str
    claim_epoch: int = Field(gt=0, strict=True)
    capability_role: str
    selected_descriptor_leaf: str
    execution_target: ContentAddress
    runtime_identity: ContentAddress
    active_generation_roots: tuple[ContentAddress, ...] = Field(min_length=1)
    invocation_id: str
    idempotency_key: str
    attempt_fence: str = Field(pattern=r"^[0-9a-f]{64}$")
    effect_manifest: ContentAddress
    issuer_receipt: ContentAddress
    observation_contract: ContentAddress
    idempotence_class: Literal["idempotent", "reconcilable", "non_idempotent"]
    reconciliation_class: Literal["exact_observation", "process_identity", "none"]
    compensation: ContentAddress | None
    issued_at: str
    not_before: str
    expires_at: str
    supersession_frontier_ref: str
    supersedes_refs: tuple[str, ...]
    authorizes_machine_adapter: Literal[True]
    authorizes_operator: Literal[False]
    may_mint_sovereign_act: Literal[False]

    @field_validator(
        "lease_ref",
        "task_ref",
        "lane",
        "session_ref",
        "capability_role",
        "selected_descriptor_leaf",
        "invocation_id",
        "idempotency_key",
        "supersession_frontier_ref",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("supersedes_refs")
    @classmethod
    def validate_supersedes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _string_set(value, allow_empty=True)

    @field_validator("issued_at", "not_before", "expires_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_historical_lease(self) -> Self:
        if not self.issued_at <= self.not_before < self.expires_at:
            raise ValueError("historical lease has an invalid invocation interval")
        body = self.model_dump(mode="json", by_alias=True, exclude={"lease_ref", "lease_hash"})
        expected = _self_hash("hapax.execution-lease.v1", body)
        if self.lease_hash != expected or self.lease_ref != (f"execution-lease@sha256:{expected}"):
            raise ValueError("historical lease reference/hash do not bind its body")
        return self


class HistoricalBoundExecutionCallV1(_FrozenModel):
    """Historical call carrier retained for exact lease-v2 inspection."""

    schema_id: Literal["hapax.bound-execution-call.v1"] = Field(alias="schema")
    call_ref: str
    call_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    admission: ContentAddress
    admitted_claim: ContentAddress
    action_intent: ContentAddress
    authority_grant: ContentAddress
    route_decision: ContentAddress
    execution_target: ContentAddress
    task_ref: str
    lane: str
    session_ref: str
    claim_epoch: int = Field(gt=0, strict=True)
    authority_case: str
    dispatch_message_id: str
    idempotency_key: str
    invocation_id: str
    attempt_fence: str = Field(pattern=r"^[0-9a-f]{64}$")
    platform: str
    mode: str
    profile: str
    route_id: str
    selected_descriptor_leaf: str
    capability_role: str
    operation: str
    effect_manifest: ContentAddress
    executor_descriptor: ContentAddress
    executor_registry_projection: ContentAddress
    execution_host: str
    acting_subject: ContentAddress
    executor: ContentAddress
    adapter: ContentAddress
    harness: ContentAddress
    runtime_identity: ContentAddress
    active_generation_roots: tuple[ContentAddress, ...] = Field(min_length=1)
    requested_effect_targets: tuple[ContentAddress, ...]
    requested_scope_refs: tuple[str, ...]
    required_authorization_flags: tuple[str, ...] = Field(min_length=1)
    control_operations: tuple[str, ...]
    may_authorize: Literal[False]

    @field_validator(
        "call_ref",
        "task_ref",
        "lane",
        "session_ref",
        "authority_case",
        "dispatch_message_id",
        "idempotency_key",
        "invocation_id",
        "platform",
        "mode",
        "profile",
        "route_id",
        "selected_descriptor_leaf",
        "capability_role",
        "operation",
        "execution_host",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator(
        "requested_effect_targets",
    )
    @classmethod
    def validate_effect_targets(
        cls,
        value: tuple[ContentAddress, ...],
    ) -> tuple[ContentAddress, ...]:
        return _content_address_set(value, allow_empty=True)

    @field_validator("active_generation_roots")
    @classmethod
    def validate_generation_roots(
        cls,
        value: tuple[ContentAddress, ...],
    ) -> tuple[ContentAddress, ...]:
        return _content_address_set(value)

    @field_validator(
        "requested_scope_refs",
        "required_authorization_flags",
        "control_operations",
    )
    @classmethod
    def validate_sets(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _string_set(
            value,
            allow_empty=info.field_name in {"requested_scope_refs", "control_operations"},
        )

    @model_validator(mode="after")
    def validate_call(self) -> Self:
        if "lane.lifecycle.reactivate" in self.control_operations:
            lane_scope = f"lane:{self.lane.strip().lower().replace('_', '-')}"
            if (
                "lane_reactivation_authorized" not in self.required_authorization_flags
                or lane_scope not in self.requested_scope_refs
            ):
                raise ValueError(
                    "lane reactivation requires its authority flag and exact lane scope"
                )
        body = self.model_dump(mode="json", by_alias=True, exclude={"call_ref", "call_hash"})
        expected = _self_hash(HISTORICAL_BOUND_EXECUTION_CALL_SCHEMA, body)
        if self.call_hash != expected or self.call_ref != (
            f"bound-execution-call@sha256:{expected}"
        ):
            raise ValueError("bound execution call reference/hash do not bind its body")
        return self


class BoundExecutionCall(_FrozenModel):
    """Current call carrier for either prospective publication or applied ownership."""

    schema_id: Literal["hapax.bound-execution-call.v2"] = Field(alias="schema")
    call_ref: str
    call_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    admission: ContentAddress
    claim_basis: ContentAddress
    claim_coordinates: ProtectedClaimCoordinates
    protected_action_request: ContentAddress
    task_note: ContentAddress
    action_intent: ContentAddress
    authority_grant: ContentAddress
    route_decision: ContentAddress
    execution_target: ContentAddress
    task_ref: str
    lane: str
    session_ref: str
    claim_epoch: int = Field(gt=0, strict=True)
    authority_case: str
    dispatch_message_id: str
    idempotency_key: str
    invocation_id: str
    attempt_fence: str = Field(pattern=r"^[0-9a-f]{64}$")
    platform: str
    mode: str
    profile: str
    route_id: str
    selected_descriptor_leaf: str
    capability_role: str
    action_class: str
    operation: str
    effect_manifest: ContentAddress
    executor_descriptor: ContentAddress
    executor_registry_projection: ContentAddress
    execution_host: str
    acting_subject: ContentAddress
    executor: ContentAddress
    adapter: ContentAddress
    harness: ContentAddress
    runtime_identity: ContentAddress
    active_generation_roots: tuple[ContentAddress, ...] = Field(min_length=1)
    requested_effect_targets: tuple[ContentAddress, ...]
    requested_scope_refs: tuple[str, ...]
    required_authorization_flags: tuple[str, ...] = Field(min_length=1)
    control_operations: tuple[str, ...]
    may_authorize: Literal[False]

    @field_validator(
        "call_ref",
        "task_ref",
        "lane",
        "session_ref",
        "authority_case",
        "dispatch_message_id",
        "idempotency_key",
        "invocation_id",
        "platform",
        "mode",
        "profile",
        "route_id",
        "selected_descriptor_leaf",
        "capability_role",
        "action_class",
        "operation",
        "execution_host",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("requested_effect_targets")
    @classmethod
    def validate_effect_targets(
        cls,
        value: tuple[ContentAddress, ...],
    ) -> tuple[ContentAddress, ...]:
        return _content_address_set(value, allow_empty=True)

    @field_validator("active_generation_roots")
    @classmethod
    def validate_generation_roots(
        cls,
        value: tuple[ContentAddress, ...],
    ) -> tuple[ContentAddress, ...]:
        return _content_address_set(value)

    @field_validator(
        "requested_scope_refs",
        "required_authorization_flags",
        "control_operations",
    )
    @classmethod
    def validate_sets(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _string_set(
            value,
            allow_empty=info.field_name in {"requested_scope_refs", "control_operations"},
        )

    @model_validator(mode="after")
    def validate_call(self) -> Self:
        if self.claim_basis != self.claim_coordinates.claim_basis:
            raise ValueError("bound call basis differs from its claim coordinates")
        prospective = self.claim_coordinates.state == "prospective"
        if prospective != (self.operation == "claim.publish"):
            raise ValueError("bound call operation differs from its claim branch")
        if prospective != (self.action_class == "claim_publication"):
            raise ValueError("bound call action class differs from its claim branch")
        if "lane.lifecycle.reactivate" in self.control_operations:
            lane_scope = f"lane:{self.lane.strip().lower().replace('_', '-')}"
            if (
                "lane_reactivation_authorized" not in self.required_authorization_flags
                or lane_scope not in self.requested_scope_refs
            ):
                raise ValueError(
                    "lane reactivation requires its authority flag and exact lane scope"
                )
        body = self.model_dump(mode="json", by_alias=True, exclude={"call_ref", "call_hash"})
        expected = _self_hash(BOUND_EXECUTION_CALL_SCHEMA, body)
        if self.call_hash != expected or self.call_ref != (
            f"bound-execution-call@sha256:{expected}"
        ):
            raise ValueError("bound execution call reference/hash do not bind its body")
        return self


def build_bound_execution_call(
    admission: ExecutionAdmission,
    intent: ActionIntent,
    grant: ValidAuthorityGrant,
    claim_basis: ProspectiveClaimPublicationBasis | AppliedClaimOwnershipProof,
    claim_coordinates: ProtectedClaimCoordinates,
    protected_request: ProtectedActionRequest,
    task_note: ContentAddress,
    target: ExecutionTargetEvidence,
    decision: RouteDecision,
    effect_manifest: EffectManifest,
    executor_descriptor: ExecutorDescriptor,
    executor_registry_projection: ExecutorRegistryProjection,
    *,
    invocation_id: str,
    attempt_fence: str | None = None,
    control_operations: Sequence[str] = (),
) -> BoundExecutionCall:
    """Bind one exact admitted action to one registry-resolved executor call."""

    try:
        admission = ExecutionAdmission.model_validate(
            admission.model_dump(mode="json", by_alias=True)
        )
        intent = ActionIntent.model_validate(intent.model_dump(mode="json", by_alias=True))
        grant = ValidAuthorityGrant.model_validate(grant.model_dump(mode="json", by_alias=True))
        if isinstance(claim_basis, ProspectiveClaimPublicationBasis):
            claim_basis = ProspectiveClaimPublicationBasis.model_validate(
                claim_basis.model_dump(mode="json", by_alias=True)
            )
        elif isinstance(claim_basis, AppliedClaimOwnershipProof):
            claim_basis = AppliedClaimOwnershipProof.model_validate(
                claim_basis.model_dump(mode="json", by_alias=True)
            )
        else:
            raise TypeError("unsupported claim basis")
        claim_coordinates = ProtectedClaimCoordinates.model_validate(
            claim_coordinates.model_dump(mode="json", by_alias=True)
        )
        protected_request = ProtectedActionRequest.model_validate(
            protected_request.model_dump(mode="json", by_alias=True)
        )
        task_note = ContentAddress.model_validate(task_note.model_dump(mode="json"))
        target = ExecutionTargetEvidence.model_validate(
            target.model_dump(mode="json", by_alias=True)
        )
        decision = RouteDecision.model_validate(decision.model_dump(mode="json"))
        effect_manifest = EffectManifest.model_validate(
            effect_manifest.model_dump(mode="json", by_alias=True)
        )
        executor_descriptor = ExecutorDescriptor.model_validate(
            executor_descriptor.model_dump(mode="json", by_alias=True)
        )
        executor_registry_projection = ExecutorRegistryProjection.model_validate(
            executor_registry_projection.model_dump(mode="json", by_alias=True)
        )
    except Exception as exc:
        raise ExecutionAdmissionError(
            "bound_execution_call_input_malformed",
            "restore the exact self-validating admitted call inputs",
            type(exc).__name__,
        ) from exc
    fence = attempt_fence or secrets.token_hex(32)
    if len(fence) != 64 or any(char not in "0123456789abcdef" for char in fence):
        raise ExecutionAdmissionError(
            "execution_attempt_fence_invalid",
            "supply one unpredictable 32-byte lowercase-hex attempt fence",
        )
    admission_address = ContentAddress(ref=admission.admission_ref, sha256=admission.admission_hash)
    intent_address = ContentAddress(ref=intent.intent_ref, sha256=intent.intent_hash)
    grant_address = ContentAddress(ref=grant.grant_ref, sha256=grant.grant_hash)
    if isinstance(claim_basis, ProspectiveClaimPublicationBasis):
        basis_address = ContentAddress(
            ref=claim_basis.basis_ref,
            sha256=claim_basis.basis_hash,
        )
        prospective = True
    else:
        basis_address = ContentAddress(
            ref=claim_basis.proof_ref,
            sha256=claim_basis.proof_hash,
        )
        prospective = False
    coordinates_address = ContentAddress(
        ref=claim_coordinates.coordinates_ref,
        sha256=claim_coordinates.coordinates_hash,
    )
    request_address = ContentAddress(
        ref=protected_request.request_ref,
        sha256=protected_request.request_hash,
    )
    target_address = ContentAddress(ref=target.target_ref, sha256=target.target_hash)
    manifest_address = ContentAddress(
        ref=effect_manifest.manifest_ref,
        sha256=effect_manifest.manifest_hash,
    )
    descriptor_address = ContentAddress(
        ref=executor_descriptor.descriptor_ref,
        sha256=executor_descriptor.descriptor_hash,
    )
    registry_address = ContentAddress(
        ref=executor_registry_projection.projection_ref,
        sha256=executor_registry_projection.projection_hash,
    )
    decision_address = content_address(decision.decision_id, decision)
    selected_leaf = decision.selected_descriptor_leaf or f"{decision.route_id}#base"
    mismatches: list[str] = []
    if admission.decision != "admit" or not admission.lease_eligible:
        mismatches.append("admission")
    if admission.intent != intent_address:
        mismatches.append("intent")
    if admission.authority_grant != grant_address:
        mismatches.append("authority_grant")
    if grant.acting_subject != intent.acting_subject:
        mismatches.append("authority_subject")
    if (
        claim_coordinates.claim_basis != basis_address
        or claim_coordinates.claim_publication_intent != claim_basis.claim_publication_intent
        or admission.claim_publication_intent != claim_basis.claim_publication_intent
    ):
        mismatches.append("claim_basis")
    if (
        protected_request.claim_coordinates != coordinates_address
        or intent.protected_action_request != request_address
        or protected_request.operation != intent.operation
        or protected_request.task_ref != admission.task_ref
        or protected_request.lane != admission.lane
        or protected_request.session_ref != admission.session_ref
    ):
        mismatches.append("protected_action_request")
    if admission.task_note != task_note:
        mismatches.append("task_note")
    if admission.route_decision != decision_address:
        mismatches.append("route_decision")
    if admission.execution_target != target_address:
        mismatches.append("execution_target")
    if (
        admission.effect_manifest != manifest_address
        or intent.effect_manifest != manifest_address
        or target.effect_manifest != manifest_address
        or intent.requested_effect_targets != effect_manifest.effect_targets
    ):
        mismatches.append("effect_manifest")
    if (
        target.executor_descriptor != descriptor_address
        or target.executor_registry_projection != registry_address
        or descriptor_address not in executor_registry_projection.descriptors
        or target.executor != executor_descriptor.executor
        or target.adapter != executor_descriptor.adapter
        or target.harness != executor_descriptor.harness
        or target.runtime_identity != executor_descriptor.runtime_identity
        or target.active_generation_roots != executor_descriptor.active_generation_roots
        or target.execution_host != executor_descriptor.execution_host
        or executor_descriptor.execution_host != intent.execution_host
        or executor_descriptor.platform != decision.platform
        or executor_descriptor.mode != decision.mode
        or executor_descriptor.profile != decision.profile
    ):
        mismatches.append("executor_registry")
    if (
        admission.task_ref != claim_basis.task_ref
        or admission.lane != claim_basis.lane
        or admission.session_ref != claim_basis.session_ref
        or admission.authority_case != claim_basis.authority_case
        or claim_coordinates.task_ref != claim_basis.task_ref
        or claim_coordinates.lane != claim_basis.lane
        or claim_coordinates.session_ref != claim_basis.session_ref
        or claim_coordinates.claim_epoch != claim_basis.claim_epoch
    ):
        mismatches.append("claim_identity")
    if (
        decision.task_id != admission.task_ref
        or decision.lane != admission.lane
        or selected_leaf != admission.selected_descriptor_leaf
        or selected_leaf != target.selected_descriptor_leaf
        or selected_leaf != executor_descriptor.selected_descriptor_leaf
    ):
        mismatches.append("route_identity")
    if admission.dispatch_message_id != claim_basis.dispatch_message_id:
        mismatches.append("dispatch_root")
    if prospective:
        if (
            not isinstance(claim_basis, ProspectiveClaimPublicationBasis)
            or claim_coordinates.state != "prospective"
            or intent.operation != "claim.publish"
            or intent.action_class != "claim_publication"
            or not intent.mutating
            or admission.idempotency_key != claim_basis.coord_dispatch_idempotency_key
            or task_note.sha256 != claim_basis.task_note_before_sha256
        ):
            mismatches.append("prospective_claim_publication")
    else:
        assert isinstance(claim_basis, AppliedClaimOwnershipProof)
        reused = tuple(
            label
            for label, current, publication in (
                ("action_intent", intent_address, claim_basis.publication_action_intent),
                (
                    "execution_admission",
                    admission_address,
                    claim_basis.publication_execution_admission,
                ),
                (
                    "valid_authority_grant",
                    grant_address,
                    claim_basis.publication_valid_authority_grant,
                ),
            )
            if current == publication
        )
        if reused:
            raise ExecutionAdmissionError(
                "publication_authority_reuse_prohibited",
                "mint a distinct current action intent, admission, and narrowed grant",
                ",".join(reused),
            )
        if (
            claim_coordinates.state != "applied"
            or intent.operation == "claim.publish"
            or intent.action_class == "claim_publication"
        ):
            mismatches.append("applied_claim_ownership")
    controls = tuple(sorted(set(control_operations)))
    if "lane.lifecycle.reactivate" in controls and (
        "lane_reactivation_authorized" not in admission.authorized_flags
        or f"lane:{admission.lane.strip().lower().replace('_', '-')}"
        not in admission.immutable_scope_refs
    ):
        mismatches.append("lane_reactivation_authority")
    if mismatches:
        raise ExecutionAdmissionError(
            "bound_execution_call_input_mismatch",
            "rebuild the call from one exact admitted action and execution target",
            ",".join(sorted(set(mismatches))),
        )
    body: dict[str, object] = {
        "schema": BOUND_EXECUTION_CALL_SCHEMA,
        "admission": admission_address,
        "claim_basis": basis_address,
        "claim_coordinates": claim_coordinates.model_dump(mode="json", by_alias=True),
        "protected_action_request": request_address,
        "task_note": task_note,
        "action_intent": intent_address,
        "authority_grant": grant_address,
        "route_decision": decision_address,
        "execution_target": target_address,
        "task_ref": admission.task_ref,
        "lane": admission.lane,
        "session_ref": admission.session_ref,
        "claim_epoch": claim_basis.claim_epoch,
        "authority_case": admission.authority_case,
        "dispatch_message_id": admission.dispatch_message_id,
        "idempotency_key": admission.idempotency_key,
        "invocation_id": _nonblank(invocation_id),
        "attempt_fence": fence,
        "platform": decision.platform,
        "mode": decision.mode,
        "profile": decision.profile,
        "route_id": decision.route_id,
        "selected_descriptor_leaf": selected_leaf,
        "capability_role": intent.capability_role,
        "action_class": intent.action_class,
        "operation": intent.operation,
        "effect_manifest": intent.effect_manifest,
        "executor_descriptor": descriptor_address,
        "executor_registry_projection": registry_address,
        "execution_host": intent.execution_host,
        "acting_subject": intent.acting_subject,
        "executor": executor_descriptor.executor,
        "adapter": executor_descriptor.adapter,
        "harness": executor_descriptor.harness,
        "runtime_identity": executor_descriptor.runtime_identity,
        "active_generation_roots": executor_descriptor.active_generation_roots,
        "requested_effect_targets": intent.requested_effect_targets,
        "requested_scope_refs": intent.requested_scope_refs,
        "required_authorization_flags": intent.required_authorization_flags,
        "control_operations": controls,
        "may_authorize": False,
    }
    digest = _self_hash(BOUND_EXECUTION_CALL_SCHEMA, body)
    return BoundExecutionCall.model_validate(
        {
            **body,
            "call_ref": f"bound-execution-call@sha256:{digest}",
            "call_hash": digest,
        }
    )


class ExecutionExecutorError(RuntimeError):
    """Typed refusal before a bound call reaches an executor."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        self.detail = detail
        message = reason_code if not detail else f"{reason_code}:{detail}"
        super().__init__(message)


def _bound_call_executor_key(call: BoundExecutionCall) -> ContentAddress:
    return call.executor_descriptor


@dataclass(frozen=True)
class ExecutionExecutorBinding:
    """One immutable executor identity selected by exact target evidence."""

    descriptor: ExecutorDescriptor

    def __post_init__(self) -> None:
        _require_exact_type(self.descriptor, ExecutorDescriptor, "executor descriptor")
        object.__setattr__(
            self,
            "descriptor",
            ExecutorDescriptor.model_validate(
                self.descriptor.model_dump(mode="json", by_alias=True)
            ),
        )

    @property
    def key(self) -> ContentAddress:
        return ContentAddress(
            ref=self.descriptor.descriptor_ref,
            sha256=self.descriptor.descriptor_hash,
        )

    def invoke(
        self,
        lease: ExecutionLease,
        start_event: ContentAddress,
    ) -> EffectObservation:
        checked = require_admitted_execution_lease(lease)
        ContentAddress.model_validate(start_event.model_dump(mode="json"))
        raise ExecutionExecutorError(
            "execution_composition_activation_unvalidated",
            checked.lease_ref,
        )


class ExecutionExecutorRegistry:
    """Immutable exact-match registry; it has no ambient registration API."""

    def __init__(
        self,
        projection: ExecutorRegistryProjection | None = None,
        bindings: Iterable[ExecutionExecutorBinding] = (),
        *,
        descriptor: ContentAddress | None = None,
    ) -> None:
        indexed: dict[tuple[str, str], ExecutionExecutorBinding] = {}
        for binding in bindings:
            _require_exact_type(binding, ExecutionExecutorBinding, "executor registry binding")
            key = _content_address_key(binding.key)
            if key in indexed:
                raise ValueError("executor registry binding collision")
            indexed[key] = binding
        if projection is None and indexed:
            raise ValueError("executor bindings require an exact registry projection")
        if projection is not None:
            _require_exact_type(
                projection,
                ExecutorRegistryProjection,
                "executor registry projection",
            )
        self._projection = (
            None
            if projection is None
            else ExecutorRegistryProjection.model_validate(
                projection.model_dump(mode="json", by_alias=True)
            )
        )
        if self._projection is not None and set(indexed) != {
            _content_address_key(item) for item in self._projection.descriptors
        }:
            raise ValueError("executor bindings must equal the registry projection")
        projection_descriptor = (
            None
            if self._projection is None
            else ContentAddress(
                ref=self._projection.projection_ref,
                sha256=self._projection.projection_hash,
            )
        )
        if descriptor is not None:
            _require_exact_type(descriptor, ContentAddress, "executor registry descriptor")
            descriptor = ContentAddress.model_validate(descriptor.model_dump(mode="json"))
        if (
            descriptor is not None
            and projection_descriptor is not None
            and descriptor != projection_descriptor
        ):
            raise ValueError("executor registry descriptor differs from its projection")
        self.descriptor = descriptor or projection_descriptor
        self._bindings = indexed

    def resolve(
        self,
        lease: ExecutionLease,
        currentness_query: ExecutionCurrentnessQuery,
        currentness: ExecutionCurrentnessEnvelope,
    ) -> ExecutionExecutorBinding:
        _require_exact_type(lease, ExecutionLease, "execution lease")
        _require_exact_type(
            currentness_query,
            ExecutionCurrentnessQuery,
            "execution currentness query",
        )
        _require_exact_type(
            currentness,
            ExecutionCurrentnessEnvelope,
            "execution currentness envelope",
        )
        checked = require_admitted_execution_lease(lease)
        query = ExecutionCurrentnessQuery.model_validate(
            currentness_query.model_dump(mode="json", by_alias=True)
        )
        envelope = ExecutionCurrentnessEnvelope.model_validate(
            currentness.model_dump(mode="json", by_alias=True)
        )
        if self._projection is None:
            raise ExecutionExecutorError("bound_executor_unavailable", checked.lease_ref)
        projection_address = ContentAddress(
            ref=self._projection.projection_ref,
            sha256=self._projection.projection_hash,
        )
        current_roots = {
            _content_address_key(item.root)
            for item in envelope.root_dispositions
            if item.disposition == "current"
        }
        support_roots = {
            _content_address_key(item.root)
            for item in envelope.historical_support_dispositions
            if item.disposition == "present"
        }
        expected_lease = ContentAddress(ref=checked.lease_ref, sha256=checked.lease_hash)
        expected_call = ContentAddress(
            ref=checked.bound_call.call_ref,
            sha256=checked.bound_call.call_hash,
        )
        if (
            envelope.query != ContentAddress(ref=query.query_ref, sha256=query.query_hash)
            or envelope.decision != "current"
            or envelope.idempotency_state != "available"
            or tuple(item.root for item in envelope.root_dispositions) != query.required_roots
            or any(item.disposition != "current" for item in envelope.root_dispositions)
            or tuple(item.root for item in envelope.historical_support_dispositions)
            != query.historical_support_roots
            or any(
                item.disposition != "present" for item in envelope.historical_support_dispositions
            )
            or support_roots
            != {_content_address_key(item) for item in query.historical_support_roots}
            or query.execution_lease != expected_lease
            or query.bound_execution_call != expected_call
            or query.effect_manifest != checked.effect_manifest
            or query.executor_descriptor != checked.executor_descriptor
            or query.executor_registry_projection != checked.executor_registry_projection
            or query.task_ref != checked.task_ref
            or query.lane != checked.lane
            or query.session_ref != checked.session_ref
            or query.claim_epoch != checked.claim_epoch
            or query.invocation_id != checked.invocation_id
            or query.attempt_fence != checked.attempt_fence
            or query.idempotency_key != checked.idempotency_key
            or checked.executor_registry_projection != projection_address
            or _content_address_key(projection_address) not in current_roots
            or _content_address_key(checked.executor_descriptor) not in current_roots
            or _content_address_key(checked.executor_descriptor)
            not in {_content_address_key(item) for item in self._projection.descriptors}
        ):
            raise ExecutionExecutorError(
                "bound_executor_registry_not_current",
                checked.lease_ref,
            )
        binding = self._bindings.get(_content_address_key(checked.executor_descriptor))
        if binding is None:
            raise ExecutionExecutorError(
                "bound_executor_unavailable",
                checked.bound_call.call_ref,
            )
        return binding


# Activation remains held until a governed registry projection installs exact,
# attested executor bindings. Callers cannot supply a substitute registry.
DEFAULT_EXECUTOR_REGISTRY = ExecutionExecutorRegistry()


class HistoricalExecutionLeaseV2(_FrozenModel):
    """Historical admitted-claim lease retained for exact inspection."""

    schema_id: Literal["hapax.execution-lease.v2"] = Field(alias="schema")
    lease_ref: str
    lease_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    admission: ContentAddress
    authority_grant: ContentAddress
    applied_claim: AdmittedAppliedClaimProof
    bound_call: HistoricalBoundExecutionCallV1
    task_ref: str
    lane: str
    session_ref: str
    claim_epoch: int = Field(gt=0, strict=True)
    capability_role: str
    selected_descriptor_leaf: str
    execution_target: ContentAddress
    runtime_identity: ContentAddress
    active_generation_roots: tuple[ContentAddress, ...] = Field(min_length=1)
    invocation_id: str
    idempotency_key: str
    attempt_fence: str = Field(pattern=r"^[0-9a-f]{64}$")
    effect_manifest: ContentAddress
    executor_descriptor: ContentAddress
    executor_registry_projection: ContentAddress
    executor: ContentAddress
    issuer_receipt: ContentAddress
    issuer_trust_query: ExecutionTrustQuery
    issuer_trust_envelope: ExecutionTrustEnvelope
    observation_contract: ContentAddress
    completion_predicate: ContentAddress
    idempotence_class: Literal["idempotent", "non_idempotent"]
    reconciliation_contract: ContentAddress | None
    compensation: ContentAddress | None
    issued_at: str
    not_before: str
    expires_at: str
    supersession_frontier_ref: str
    supersedes_refs: tuple[str, ...]
    authorizes_machine_adapter: Literal[True]
    authorizes_operator: Literal[False]
    may_mint_sovereign_act: Literal[False]

    @field_validator(
        "lease_ref",
        "task_ref",
        "lane",
        "session_ref",
        "capability_role",
        "selected_descriptor_leaf",
        "invocation_id",
        "idempotency_key",
        "supersession_frontier_ref",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("supersedes_refs")
    @classmethod
    def validate_supersedes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _string_set(value, allow_empty=True)

    @field_validator("active_generation_roots")
    @classmethod
    def validate_generation_roots(
        cls,
        value: tuple[ContentAddress, ...],
    ) -> tuple[ContentAddress, ...]:
        return _content_address_set(value)

    @field_validator("issued_at", "not_before", "expires_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_lease(self) -> Self:
        if not self.issued_at <= self.not_before < self.expires_at:
            raise ValueError("execution lease requires a non-empty invocation interval")
        if self.idempotence_class == "non_idempotent" and self.reconciliation_contract is None:
            raise ValueError("non-idempotent effects require authoritative reconciliation")
        if self.reconciliation_contract is None and self.compensation is not None:
            raise ValueError("compensation requires a reconciliation contract")
        if self.applied_claim.execution_admission != self.admission:
            raise ValueError("lease admission must equal the admitted claim root")
        if self.applied_claim.valid_authority_grant != self.authority_grant:
            raise ValueError("lease authority grant must equal the admitted claim root")
        if (
            self.task_ref != self.applied_claim.task_ref
            or self.lane != self.applied_claim.lane
            or self.session_ref != self.applied_claim.session_ref
            or self.claim_epoch != self.applied_claim.claim_epoch
        ):
            raise ValueError("lease identity must equal the admitted claim identity")
        if self.idempotency_key != self.applied_claim.coord_dispatch_idempotency_key:
            raise ValueError("lease idempotency key must equal the admitted claim root")
        if self.supersession_frontier_ref != self.applied_claim.supersession_frontier_ref:
            raise ValueError("lease frontier must equal the admitted claim frontier")
        if self.expires_at > self.applied_claim.admission_valid_until:
            raise ValueError("lease cannot outlive the admitted claim proof")
        if self.issued_at < self.applied_claim.admission_checked_at:
            raise ValueError("lease cannot predate the admitted claim proof")
        if self.bound_call.admission != self.admission:
            raise ValueError("lease bound call must consume its admission")
        if self.bound_call.admitted_claim != ContentAddress(
            ref=self.applied_claim.proof_ref,
            sha256=self.applied_claim.proof_hash,
        ):
            raise ValueError("lease bound call must consume its admitted claim")
        if self.bound_call.authority_grant != self.authority_grant:
            raise ValueError("lease bound call must consume its authority grant")
        if self.bound_call.execution_target != self.execution_target:
            raise ValueError("lease bound call must consume its execution target")
        if (
            self.bound_call.task_ref != self.task_ref
            or self.bound_call.lane != self.lane
            or self.bound_call.session_ref != self.session_ref
            or self.bound_call.claim_epoch != self.claim_epoch
            or self.bound_call.invocation_id != self.invocation_id
            or self.bound_call.idempotency_key != self.idempotency_key
            or self.bound_call.attempt_fence != self.attempt_fence
        ):
            raise ValueError("lease bound call identity mismatch")
        if (
            self.bound_call.capability_role != self.capability_role
            or self.bound_call.selected_descriptor_leaf != self.selected_descriptor_leaf
            or self.bound_call.effect_manifest != self.effect_manifest
            or self.bound_call.executor_descriptor != self.executor_descriptor
            or self.bound_call.executor_registry_projection != self.executor_registry_projection
            or self.bound_call.executor != self.executor
            or self.bound_call.runtime_identity != self.runtime_identity
            or self.bound_call.active_generation_roots != self.active_generation_roots
        ):
            raise ValueError("lease bound call effect or target mismatch")
        expected_query = ContentAddress(
            ref=self.issuer_trust_query.query_ref,
            sha256=self.issuer_trust_query.query_hash,
        )
        issuer_anchor_keys = {
            _content_address_key(self.issuer_receipt),
            _content_address_key(self.admission),
            _content_address_key(self.authority_grant),
            _content_address_key(self.execution_target),
            _content_address_key(self.effect_manifest),
            _content_address_key(self.executor_descriptor),
            _content_address_key(self.executor_registry_projection),
            _content_address_key(
                ContentAddress(
                    ref=self.bound_call.call_ref,
                    sha256=self.bound_call.call_hash,
                )
            ),
        }
        if (
            self.issuer_trust_query.trust_class != "execution_lease_issuer"
            or self.issuer_trust_query.presented_receipt != self.issuer_receipt
            or not issuer_anchor_keys.issubset(
                {_content_address_key(item) for item in self.issuer_trust_query.required_roots}
            )
            or self.issuer_trust_query.supersession_frontier_ref != self.supersession_frontier_ref
            or self.issuer_trust_envelope.query != expected_query
            or self.issuer_trust_envelope.decision != "trusted"
            or self.issued_at != self.issuer_trust_query.queried_at
            or self.expires_at > self.issuer_trust_envelope.stale_after
        ):
            raise ValueError("lease issuer trust projection binding mismatch")
        body = self.model_dump(mode="json", by_alias=True, exclude={"lease_ref", "lease_hash"})
        expected = _self_hash(HISTORICAL_EXECUTION_LEASE_V2_SCHEMA, body)
        if self.lease_hash != expected or self.lease_ref != f"execution-lease@sha256:{expected}":
            raise ValueError("execution lease reference/hash do not bind its body")
        return self


class ExecutionLease(_FrozenModel):
    """Current short-lived machine lease for one typed claim-basis branch."""

    schema_id: Literal["hapax.execution-lease.v3"] = Field(alias="schema")
    lease_ref: str
    lease_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    admission: ContentAddress
    authority_grant: ContentAddress
    claim_basis: ProspectiveClaimPublicationBasis | AppliedClaimOwnershipProof
    claim_coordinates: ProtectedClaimCoordinates
    bound_call: BoundExecutionCall
    task_ref: str
    lane: str
    session_ref: str
    claim_epoch: int = Field(gt=0, strict=True)
    capability_role: str
    selected_descriptor_leaf: str
    execution_target: ContentAddress
    runtime_identity: ContentAddress
    active_generation_roots: tuple[ContentAddress, ...] = Field(min_length=1)
    invocation_id: str
    idempotency_key: str
    attempt_fence: str = Field(pattern=r"^[0-9a-f]{64}$")
    effect_manifest: ContentAddress
    executor_descriptor: ContentAddress
    executor_registry_projection: ContentAddress
    executor: ContentAddress
    issuer_receipt: ContentAddress
    issuer_trust_query: ExecutionTrustQuery
    issuer_trust_envelope: ExecutionTrustEnvelope
    observation_contract: ContentAddress
    completion_predicate: ContentAddress
    idempotence_class: Literal["idempotent", "non_idempotent"]
    reconciliation_contract: ContentAddress | None
    compensation: ContentAddress | None
    issued_at: str
    not_before: str
    expires_at: str
    supersession_frontier_ref: str
    supersedes_refs: tuple[str, ...]
    authorizes_machine_adapter: Literal[True]
    authorizes_operator: Literal[False]
    may_mint_sovereign_act: Literal[False]

    @field_validator(
        "lease_ref",
        "task_ref",
        "lane",
        "session_ref",
        "capability_role",
        "selected_descriptor_leaf",
        "invocation_id",
        "idempotency_key",
        "supersession_frontier_ref",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("supersedes_refs")
    @classmethod
    def validate_supersedes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _string_set(value, allow_empty=True)

    @field_validator("active_generation_roots")
    @classmethod
    def validate_generation_roots(
        cls,
        value: tuple[ContentAddress, ...],
    ) -> tuple[ContentAddress, ...]:
        return _content_address_set(value)

    @field_validator("issued_at", "not_before", "expires_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_lease(self) -> Self:
        if not self.issued_at <= self.not_before < self.expires_at:
            raise ValueError("execution lease requires a non-empty invocation interval")
        if self.idempotence_class == "non_idempotent" and self.reconciliation_contract is None:
            raise ValueError("non-idempotent effects require authoritative reconciliation")
        if self.reconciliation_contract is None and self.compensation is not None:
            raise ValueError("compensation requires a reconciliation contract")
        basis_address = (
            ContentAddress(ref=self.claim_basis.basis_ref, sha256=self.claim_basis.basis_hash)
            if isinstance(self.claim_basis, ProspectiveClaimPublicationBasis)
            else ContentAddress(ref=self.claim_basis.proof_ref, sha256=self.claim_basis.proof_hash)
        )
        prospective = isinstance(self.claim_basis, ProspectiveClaimPublicationBasis)
        if self.claim_coordinates.claim_basis != basis_address:
            raise ValueError("lease claim coordinates differ from its embedded basis")
        if prospective != (self.claim_coordinates.state == "prospective"):
            raise ValueError("lease claim basis differs from its coordinate branch")
        if (
            self.claim_coordinates.claim_publication_intent
            != self.claim_basis.claim_publication_intent
            or self.claim_coordinates.task_ref != self.claim_basis.task_ref
            or self.claim_coordinates.lane != self.claim_basis.lane
            or self.claim_coordinates.session_ref != self.claim_basis.session_ref
            or self.claim_coordinates.claim_epoch != self.claim_basis.claim_epoch
        ):
            raise ValueError("lease claim coordinates differ from its basis identity")
        if (
            self.task_ref != self.claim_basis.task_ref
            or self.lane != self.claim_basis.lane
            or self.session_ref != self.claim_basis.session_ref
            or self.claim_epoch != self.claim_basis.claim_epoch
        ):
            raise ValueError("lease identity must equal its claim basis identity")
        if not prospective and self.issued_at < self.claim_basis.publication_outcome_committed_at:
            raise ValueError("lease cannot predate applied ownership outcome evidence")
        if prospective:
            if (
                self.bound_call.operation != "claim.publish"
                or self.bound_call.action_class != "claim_publication"
            ):
                raise ValueError("prospective lease must carry only claim publication")
        else:
            publication_roots = self.claim_basis
            if (
                self.bound_call.operation == "claim.publish"
                or self.bound_call.action_intent == publication_roots.publication_action_intent
                or self.admission == publication_roots.publication_execution_admission
                or self.authority_grant == publication_roots.publication_valid_authority_grant
            ):
                raise ValueError("applied ownership cannot reuse publication authority")
        if self.bound_call.admission != self.admission:
            raise ValueError("lease bound call must consume its admission")
        if self.bound_call.claim_basis != basis_address:
            raise ValueError("lease bound call must consume its claim basis")
        if self.bound_call.claim_coordinates != self.claim_coordinates:
            raise ValueError("lease bound call must consume its claim coordinates")
        if self.bound_call.authority_grant != self.authority_grant:
            raise ValueError("lease bound call must consume its authority grant")
        if self.bound_call.execution_target != self.execution_target:
            raise ValueError("lease bound call must consume its execution target")
        if (
            self.bound_call.task_ref != self.task_ref
            or self.bound_call.lane != self.lane
            or self.bound_call.session_ref != self.session_ref
            or self.bound_call.claim_epoch != self.claim_epoch
            or self.bound_call.invocation_id != self.invocation_id
            or self.bound_call.idempotency_key != self.idempotency_key
            or self.bound_call.attempt_fence != self.attempt_fence
        ):
            raise ValueError("lease bound call identity mismatch")
        if (
            self.bound_call.capability_role != self.capability_role
            or self.bound_call.selected_descriptor_leaf != self.selected_descriptor_leaf
            or self.bound_call.effect_manifest != self.effect_manifest
            or self.bound_call.executor_descriptor != self.executor_descriptor
            or self.bound_call.executor_registry_projection != self.executor_registry_projection
            or self.bound_call.executor != self.executor
            or self.bound_call.runtime_identity != self.runtime_identity
            or self.bound_call.active_generation_roots != self.active_generation_roots
        ):
            raise ValueError("lease bound call effect or target mismatch")
        expected_query = ContentAddress(
            ref=self.issuer_trust_query.query_ref,
            sha256=self.issuer_trust_query.query_hash,
        )
        issuer_anchor_keys = {
            _content_address_key(self.issuer_receipt),
            _content_address_key(self.admission),
            _content_address_key(self.authority_grant),
            _content_address_key(basis_address),
            _content_address_key(self.execution_target),
            _content_address_key(self.effect_manifest),
            _content_address_key(self.executor_descriptor),
            _content_address_key(self.executor_registry_projection),
            _content_address_key(
                ContentAddress(
                    ref=self.bound_call.call_ref,
                    sha256=self.bound_call.call_hash,
                )
            ),
        }
        issuer_required_root_keys = {
            _content_address_key(item) for item in self.issuer_trust_query.required_roots
        }
        if prospective:
            publication_intent_key = _content_address_key(self.claim_basis.claim_publication_intent)
            if publication_intent_key not in issuer_required_root_keys:
                raise ValueError(
                    "prospective lease issuer trust omits the claim publication intent"
                )
        else:
            publication_provenance_root_keys = {
                _content_address_key(item)
                for item in (
                    self.claim_basis.claim_publication_intent,
                    self.claim_basis.receipt,
                    self.claim_basis.manifest,
                    self.claim_basis.admission_consumption,
                    self.claim_basis.publication_action_intent,
                    self.claim_basis.publication_execution_admission,
                    self.claim_basis.publication_valid_authority_grant,
                    self.claim_basis.publication_authority_evidence,
                    self.claim_basis.publication_authenticated_authority_receipt,
                    self.claim_basis.publication_context_position,
                    self.claim_basis.publication_execution_lease,
                    self.claim_basis.publication_bound_execution_call,
                    self.claim_basis.publication_outcome_projection,
                    self.claim_basis.publication_outcome_receipt,
                    ContentAddress(
                        ref=self.claim_basis.publication_completion_evidence.evidence_ref,
                        sha256=self.claim_basis.publication_completion_evidence.evidence_hash,
                    ),
                )
            }
            if issuer_required_root_keys.intersection(publication_provenance_root_keys):
                raise ValueError(
                    "applied ownership issuer trust cannot require publication provenance"
                )
        if (
            self.issuer_trust_query.trust_class != "execution_lease_issuer"
            or self.issuer_trust_query.presented_receipt != self.issuer_receipt
            or not issuer_anchor_keys.issubset(issuer_required_root_keys)
            or self.issuer_trust_query.supersession_frontier_ref != self.supersession_frontier_ref
            or self.issuer_trust_envelope.query != expected_query
            or self.issuer_trust_envelope.decision != "trusted"
            or self.issued_at != self.issuer_trust_query.queried_at
            or self.expires_at > self.issuer_trust_envelope.stale_after
        ):
            raise ValueError("lease issuer trust projection binding mismatch")
        body = self.model_dump(mode="json", by_alias=True, exclude={"lease_ref", "lease_hash"})
        expected = _self_hash(EXECUTION_LEASE_SCHEMA, body)
        if self.lease_hash != expected or self.lease_ref != f"execution-lease@sha256:{expected}":
            raise ValueError("execution lease reference/hash do not bind its body")
        return self


def require_admitted_execution_lease(lease: ExecutionLease) -> ExecutionLease:
    """Structurally require an active v3 lease without asserting effect currentness."""

    try:
        _require_exact_type(lease, ExecutionLease, "execution lease")
        return ExecutionLease.model_validate(lease.model_dump(mode="json", by_alias=True))
    except Exception as exc:
        raise ExecutionAdmissionError(
            "admitted_execution_lease_required",
            "supply one self-hashed v3 lease embedding a typed claim basis",
            type(exc).__name__,
        ) from exc


def parse_bound_execution_call_record(
    value: Mapping[str, object],
) -> HistoricalBoundExecutionCallV1 | BoundExecutionCall:
    """Parse exact historical-v1 or active-v2 call bytes without upgrading."""

    schema = value.get("schema")
    if schema == HISTORICAL_BOUND_EXECUTION_CALL_SCHEMA:
        return HistoricalBoundExecutionCallV1.model_validate(value)
    if schema == BOUND_EXECUTION_CALL_SCHEMA:
        return BoundExecutionCall.model_validate(value)
    raise ExecutionAdmissionError(
        "bound_execution_call_schema_unknown",
        "supply exact historical-v1 or active-v2 call bytes",
        str(schema),
    )


def parse_execution_lease_record(
    value: Mapping[str, object],
) -> HistoricalExecutionLeaseV1 | HistoricalExecutionLeaseV2 | ExecutionLease:
    """Parse v1/v2 for history or v3 for execution without upgrading."""

    schema = value.get("schema")
    if schema == "hapax.execution-lease.v1":
        return HistoricalExecutionLeaseV1.model_validate(value)
    if schema == HISTORICAL_EXECUTION_LEASE_V2_SCHEMA:
        return HistoricalExecutionLeaseV2.model_validate(value)
    if schema == EXECUTION_LEASE_SCHEMA:
        return ExecutionLease.model_validate(value)
    raise ExecutionAdmissionError(
        "execution_lease_schema_unknown",
        "supply exact historical-v1/v2 or active-v3 lease bytes",
        str(schema),
    )


class EffectObservation(_FrozenModel):
    """Raw post-invocation facts; this object never decides semantic success."""

    schema_id: Literal["hapax.effect-observation.v1"] = Field(alias="schema")
    observation_ref: str
    observation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_lease: ContentAddress
    bound_execution_call: ContentAddress
    effect_manifest: ContentAddress
    executor_descriptor: ContentAddress
    executor_registry_projection: ContentAddress
    executor: ContentAddress
    runtime_identity: ContentAddress
    start_event: ContentAddress
    invocation_id: str
    attempt_fence: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str
    observation_contract: ContentAddress
    completion_predicate: ContentAddress
    returncode: int | None
    evidence_refs: tuple[ContentAddress, ...] = Field(min_length=1)
    observed_at: str
    may_authorize: Literal[False]

    @field_validator("observation_ref", "invocation_id", "idempotency_key")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence(
        cls,
        value: tuple[ContentAddress, ...],
    ) -> tuple[ContentAddress, ...]:
        return _content_address_set(value)

    @field_validator("observed_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"observation_ref", "observation_hash"},
        )
        expected = _self_hash(EFFECT_OBSERVATION_SCHEMA, body)
        if self.observation_hash != expected or self.observation_ref != (
            f"effect-observation@sha256:{expected}"
        ):
            raise ValueError("effect observation reference/hash do not bind its body")
        return self


def build_effect_observation(
    lease: ExecutionLease,
    *,
    start_event: ContentAddress,
    returncode: int | None,
    evidence_refs: Sequence[ContentAddress],
    observed_at: str | datetime,
) -> EffectObservation:
    checked = require_admitted_execution_lease(lease)
    observed = _canonical_timestamp(observed_at)
    if observed < checked.not_before:
        raise ExecutionAdmissionError(
            "effect_observation_predates_lease",
            "observe the effect only after its admitted invocation begins",
        )
    body: dict[str, object] = {
        "schema": EFFECT_OBSERVATION_SCHEMA,
        "execution_lease": ContentAddress(ref=checked.lease_ref, sha256=checked.lease_hash),
        "bound_execution_call": ContentAddress(
            ref=checked.bound_call.call_ref,
            sha256=checked.bound_call.call_hash,
        ),
        "effect_manifest": checked.effect_manifest,
        "executor_descriptor": checked.executor_descriptor,
        "executor_registry_projection": checked.executor_registry_projection,
        "executor": checked.executor,
        "runtime_identity": checked.runtime_identity,
        "start_event": start_event,
        "invocation_id": checked.invocation_id,
        "attempt_fence": checked.attempt_fence,
        "idempotency_key": checked.idempotency_key,
        "observation_contract": checked.observation_contract,
        "completion_predicate": checked.completion_predicate,
        "returncode": returncode,
        "evidence_refs": tuple(
            sorted(
                {_content_address_key(item): item for item in evidence_refs}.values(),
                key=_content_address_key,
            )
        ),
        "observed_at": observed,
        "may_authorize": False,
    }
    digest = _self_hash(EFFECT_OBSERVATION_SCHEMA, body)
    return EffectObservation.model_validate(
        {
            **body,
            "observation_ref": f"effect-observation@sha256:{digest}",
            "observation_hash": digest,
        }
    )


class CompletionEvaluationQuery(_FrozenModel):
    schema_id: Literal["hapax.completion-evaluation-query.v1"] = Field(alias="schema")
    query_ref: str
    query_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_lease: ContentAddress
    bound_execution_call: ContentAddress
    effect_observation: ContentAddress
    effect_manifest: ContentAddress
    observation_contract: ContentAddress
    completion_predicate: ContentAddress
    evidence_refs: tuple[ContentAddress, ...] = Field(min_length=1)
    queried_at: str
    may_authorize: Literal[False]

    @field_validator("query_ref")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence(
        cls,
        value: tuple[ContentAddress, ...],
    ) -> tuple[ContentAddress, ...]:
        return _content_address_set(value)

    @field_validator("queried_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_query(self) -> Self:
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"query_ref", "query_hash"},
        )
        expected = _self_hash(COMPLETION_EVALUATION_QUERY_SCHEMA, body)
        if self.query_hash != expected or self.query_ref != (
            f"completion-evaluation-query@sha256:{expected}"
        ):
            raise ValueError("completion query reference/hash do not bind its body")
        return self


def build_completion_evaluation_query(
    lease: ExecutionLease,
    observation: EffectObservation,
    *,
    queried_at: str | datetime,
) -> CompletionEvaluationQuery:
    checked = require_admitted_execution_lease(lease)
    observed = EffectObservation.model_validate(observation.model_dump(mode="json", by_alias=True))
    lease_address = ContentAddress(ref=checked.lease_ref, sha256=checked.lease_hash)
    call_address = ContentAddress(
        ref=checked.bound_call.call_ref,
        sha256=checked.bound_call.call_hash,
    )
    observation_address = ContentAddress(
        ref=observed.observation_ref,
        sha256=observed.observation_hash,
    )
    if (
        observed.execution_lease != lease_address
        or observed.bound_execution_call != call_address
        or observed.effect_manifest != checked.effect_manifest
        or observed.executor_descriptor != checked.executor_descriptor
        or observed.executor_registry_projection != checked.executor_registry_projection
        or observed.executor != checked.executor
        or observed.runtime_identity != checked.runtime_identity
        or observed.invocation_id != checked.invocation_id
        or observed.attempt_fence != checked.attempt_fence
        or observed.idempotency_key != checked.idempotency_key
        or observed.observation_contract != checked.observation_contract
        or observed.completion_predicate != checked.completion_predicate
    ):
        raise ExecutionAdmissionError(
            "completion_observation_lease_mismatch",
            "evaluate only the raw observation from the exact invoking lease",
        )
    queried = _canonical_timestamp(queried_at)
    if queried < observed.observed_at:
        raise ExecutionAdmissionError(
            "completion_query_predates_observation",
            "evaluate completion only after the raw observation",
        )
    body: dict[str, object] = {
        "schema": COMPLETION_EVALUATION_QUERY_SCHEMA,
        "execution_lease": lease_address,
        "bound_execution_call": call_address,
        "effect_observation": observation_address,
        "effect_manifest": observed.effect_manifest,
        "observation_contract": observed.observation_contract,
        "completion_predicate": observed.completion_predicate,
        "evidence_refs": observed.evidence_refs,
        "queried_at": queried,
        "may_authorize": False,
    }
    digest = _self_hash(COMPLETION_EVALUATION_QUERY_SCHEMA, body)
    return CompletionEvaluationQuery.model_validate(
        {
            **body,
            "query_ref": f"completion-evaluation-query@sha256:{digest}",
            "query_hash": digest,
        }
    )


class CompletionEvaluation(_FrozenModel):
    schema_id: Literal["hapax.completion-evaluation.v1"] = Field(alias="schema")
    evaluation_ref: str
    evaluation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    query: CompletionEvaluationQuery
    evaluator: ContentAddress
    event_frontier: ContentAddress
    decision: Literal["satisfied", "unsatisfied", "unknown"]
    effect_disposition: Literal[
        "applied",
        "not_applied",
        "partial",
        "not_applicable",
        "unknown",
    ]
    evidence_refs: tuple[ContentAddress, ...] = Field(min_length=1)
    reason_codes: tuple[str, ...]
    repair_refs: tuple[str, ...]
    evaluated_at: str
    may_authorize: Literal[False]

    @field_validator("evaluation_ref")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence(
        cls,
        value: tuple[ContentAddress, ...],
    ) -> tuple[ContentAddress, ...]:
        return _content_address_set(value)

    @field_validator("reason_codes", "repair_refs")
    @classmethod
    def validate_sets(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _string_set(value, allow_empty=True)

    @field_validator("evaluated_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_evaluation(self) -> Self:
        if self.evaluated_at < self.query.queried_at:
            raise ValueError("completion evaluation predates its exact query")
        if self.decision == "unknown":
            if not self.reason_codes or self.repair_refs != tuple(
                f"repair:{item}" for item in self.reason_codes
            ):
                raise ValueError("unknown completion requires exact reason/repair pairs")
        elif self.reason_codes or self.repair_refs:
            raise ValueError("known completion decisions cannot carry HOLD repairs")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"evaluation_ref", "evaluation_hash"},
        )
        expected = _self_hash(COMPLETION_EVALUATION_SCHEMA, body)
        if self.evaluation_hash != expected or self.evaluation_ref != (
            f"completion-evaluation@sha256:{expected}"
        ):
            raise ValueError("completion evaluation reference/hash do not bind its body")
        return self


@dataclass(frozen=True)
class CompletionEvaluator:
    """Data-only predicate result catalog; evaluation executes only after Gate-0B."""

    evaluator: ContentAddress | None = None
    evaluations: tuple[CompletionEvaluation, ...] = ()

    def __post_init__(self) -> None:
        if self.evaluator is not None:
            _require_exact_type(self.evaluator, ContentAddress, "completion evaluator descriptor")
            object.__setattr__(
                self,
                "evaluator",
                ContentAddress.model_validate(self.evaluator.model_dump(mode="json")),
            )
        checked = tuple(
            CompletionEvaluation.model_validate(
                _require_exact_type(
                    item,
                    CompletionEvaluation,
                    "completion evaluation",
                ).model_dump(mode="json", by_alias=True)
            )
            for item in self.evaluations
        )
        keys = tuple((item.query.query_ref, item.query.query_hash) for item in checked)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("completion catalog must be sorted and query-unique")
        if self.evaluator is not None and any(item.evaluator != self.evaluator for item in checked):
            raise ValueError("completion catalog differs from its evaluator descriptor")
        object.__setattr__(self, "evaluations", checked)

    def require_configured(self) -> ContentAddress:
        if self.evaluator is None:
            raise ExecutionAdmissionError(
                "completion_evaluator_unavailable",
                "install the accepted predicate evaluator before effects",
            )
        return self.evaluator

    def evaluate(self, query: CompletionEvaluationQuery) -> CompletionEvaluation:
        _require_exact_type(query, CompletionEvaluationQuery, "completion evaluation query")
        checked = CompletionEvaluationQuery.model_validate(
            query.model_dump(mode="json", by_alias=True)
        )
        self.require_configured()
        evaluation = next(
            (
                item
                for item in self.evaluations
                if item.query.query_ref == checked.query_ref
                and item.query.query_hash == checked.query_hash
            ),
            None,
        )
        if evaluation is None:
            raise ExecutionAdmissionError(
                "completion_projection_missing",
                "install the exact sealed completion result for this query",
                checked.query_ref,
            )
        reasons: list[str] = []
        if evaluation.evaluator != self.evaluator:
            reasons.append("completion_evaluator_identity_mismatch")
        if evaluation.query != checked:
            reasons.append("completion_evaluation_query_mismatch")
        if evaluation.evidence_refs != checked.evidence_refs:
            reasons.append("completion_evidence_coverage_mismatch")
        if evaluation.evaluated_at < checked.queried_at:
            reasons.append("completion_evaluation_predates_query")
        if reasons:
            raise ExecutionAdmissionError(
                "completion_evaluation_mismatch",
                "evaluate the exact predicate query through the installed evaluator",
                ",".join(sorted(set(reasons))),
            )
        return evaluation


DEFAULT_COMPLETION_EVALUATOR = CompletionEvaluator()


class OutcomePipelineReadinessQuery(_FrozenModel):
    schema_id: Literal["hapax.outcome-pipeline-readiness-query.v1"] = Field(alias="schema")
    query_ref: str
    query_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_lease: ContentAddress
    bound_execution_call: ContentAddress
    effect_manifest: ContentAddress
    executor_descriptor: ContentAddress
    executor_registry_projection: ContentAddress
    currentness_query: ContentAddress
    currentness_envelope: ContentAddress
    completion_predicate: ContentAddress
    evaluator: ContentAddress
    committer: ContentAddress
    event_plane: ContentAddress
    expected_event_frontier: ContentAddress
    invocation_id: str
    attempt_fence: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str
    queried_at: str
    may_authorize: Literal[False]

    @field_validator("query_ref", "invocation_id", "idempotency_key")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("queried_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_query(self) -> Self:
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"query_ref", "query_hash"},
        )
        expected = _self_hash(OUTCOME_PIPELINE_READINESS_QUERY_SCHEMA, body)
        if self.query_hash != expected or self.query_ref != (
            f"outcome-pipeline-readiness-query@sha256:{expected}"
        ):
            raise ValueError("outcome readiness query reference/hash do not bind its body")
        return self


class OutcomePipelineReadinessEnvelope(_FrozenModel):
    schema_id: Literal["hapax.outcome-pipeline-readiness-envelope.v1"] = Field(alias="schema")
    envelope_ref: str
    envelope_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    query: OutcomePipelineReadinessQuery
    resolver: ContentAddress
    decision: Literal["ready", "hold"]
    event_frontier: ContentAddress
    reason_codes: tuple[str, ...]
    repair_refs: tuple[str, ...]
    checked_at: str
    stale_after: str
    may_authorize: Literal[False]

    @field_validator("envelope_ref")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("reason_codes", "repair_refs")
    @classmethod
    def validate_sets(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _string_set(value, allow_empty=True)

    @field_validator("checked_at", "stale_after")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        if self.checked_at >= self.stale_after:
            raise ValueError("outcome readiness requires a future freshness horizon")
        if self.decision == "ready":
            if self.reason_codes or self.repair_refs:
                raise ValueError("ready outcome pipelines cannot carry repairs")
        elif not self.reason_codes or self.repair_refs != tuple(
            f"repair:{item}" for item in self.reason_codes
        ):
            raise ValueError("held outcome readiness requires exact reason/repair pairs")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"envelope_ref", "envelope_hash"},
        )
        expected = _self_hash(OUTCOME_PIPELINE_READINESS_ENVELOPE_SCHEMA, body)
        if self.envelope_hash != expected or self.envelope_ref != (
            f"outcome-pipeline-readiness-envelope@sha256:{expected}"
        ):
            raise ValueError("outcome readiness envelope reference/hash do not bind its body")
        return self


@dataclass(frozen=True)
class OutcomePipelineReadinessResolver:
    resolver: ContentAddress | None = None
    envelopes: tuple[OutcomePipelineReadinessEnvelope, ...] = ()

    def __post_init__(self) -> None:
        if self.resolver is not None:
            _require_exact_type(
                self.resolver,
                ContentAddress,
                "outcome readiness resolver descriptor",
            )
            object.__setattr__(
                self,
                "resolver",
                ContentAddress.model_validate(self.resolver.model_dump(mode="json")),
            )
        checked = tuple(
            OutcomePipelineReadinessEnvelope.model_validate(
                _require_exact_type(
                    item,
                    OutcomePipelineReadinessEnvelope,
                    "outcome readiness envelope",
                ).model_dump(mode="json", by_alias=True)
            )
            for item in self.envelopes
        )
        keys = tuple((item.query.query_ref, item.query.query_hash) for item in checked)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("readiness catalog must be sorted and query-unique")
        if self.resolver is not None and any(item.resolver != self.resolver for item in checked):
            raise ValueError("readiness catalog differs from its resolver descriptor")
        object.__setattr__(self, "envelopes", checked)

    def resolve(
        self,
        query: OutcomePipelineReadinessQuery,
    ) -> OutcomePipelineReadinessEnvelope:
        _require_exact_type(
            query,
            OutcomePipelineReadinessQuery,
            "outcome readiness query",
        )
        checked = OutcomePipelineReadinessQuery.model_validate(
            query.model_dump(mode="json", by_alias=True)
        )
        if self.resolver is None:
            raise ExecutionAdmissionError(
                "outcome_pipeline_readiness_unavailable",
                "install the accepted Spine-backed outcome readiness projection before effects",
            )
        envelope = next(
            (
                item
                for item in self.envelopes
                if item.query.query_ref == checked.query_ref
                and item.query.query_hash == checked.query_hash
            ),
            None,
        )
        if envelope is None:
            raise ExecutionAdmissionError(
                "outcome_readiness_projection_missing",
                "install the exact sealed readiness result for this query",
                checked.query_ref,
            )
        reasons: list[str] = []
        if envelope.query != checked:
            reasons.append("outcome_readiness_query_mismatch")
        if envelope.resolver != self.resolver:
            reasons.append("outcome_readiness_resolver_mismatch")
        if envelope.event_frontier != checked.expected_event_frontier:
            reasons.append("outcome_readiness_frontier_mismatch")
        if not envelope.checked_at <= checked.queried_at < envelope.stale_after:
            reasons.append("outcome_readiness_stale")
        if envelope.decision != "ready":
            reasons.extend(envelope.reason_codes or ("outcome_pipeline_held",))
        if reasons:
            raise ExecutionAdmissionError(
                "outcome_pipeline_not_ready",
                "hold effects and refresh the exact outcome pipeline readiness proof",
                ",".join(sorted(set(reasons))),
            )
        return envelope


DEFAULT_OUTCOME_PIPELINE_READINESS_RESOLVER = OutcomePipelineReadinessResolver()


def build_outcome_pipeline_readiness_query(
    lease: ExecutionLease,
    currentness_query: ExecutionCurrentnessQuery,
    currentness_envelope: ExecutionCurrentnessEnvelope,
    *,
    evaluator: ContentAddress,
    committer: ContentAddress,
    event_plane: ContentAddress,
    expected_event_frontier: ContentAddress,
    queried_at: str | datetime,
) -> OutcomePipelineReadinessQuery:
    checked = require_admitted_execution_lease(lease)
    current_query = ExecutionCurrentnessQuery.model_validate(
        currentness_query.model_dump(mode="json", by_alias=True)
    )
    current_envelope = ExecutionCurrentnessEnvelope.model_validate(
        currentness_envelope.model_dump(mode="json", by_alias=True)
    )
    lease_address = ContentAddress(ref=checked.lease_ref, sha256=checked.lease_hash)
    call_address = ContentAddress(
        ref=checked.bound_call.call_ref,
        sha256=checked.bound_call.call_hash,
    )
    if (
        current_query.execution_lease != lease_address
        or current_query.bound_execution_call != call_address
        or current_envelope.query
        != ContentAddress(ref=current_query.query_ref, sha256=current_query.query_hash)
        or current_envelope.decision != "current"
    ):
        raise ExecutionAdmissionError(
            "outcome_readiness_currentness_mismatch",
            "build readiness from the exact current lease query and envelope",
        )
    body: dict[str, object] = {
        "schema": OUTCOME_PIPELINE_READINESS_QUERY_SCHEMA,
        "execution_lease": lease_address,
        "bound_execution_call": call_address,
        "effect_manifest": checked.effect_manifest,
        "executor_descriptor": checked.executor_descriptor,
        "executor_registry_projection": checked.executor_registry_projection,
        "currentness_query": ContentAddress(
            ref=current_query.query_ref,
            sha256=current_query.query_hash,
        ),
        "currentness_envelope": ContentAddress(
            ref=current_envelope.envelope_ref,
            sha256=current_envelope.envelope_hash,
        ),
        "completion_predicate": checked.completion_predicate,
        "evaluator": evaluator,
        "committer": committer,
        "event_plane": event_plane,
        "expected_event_frontier": expected_event_frontier,
        "invocation_id": checked.invocation_id,
        "attempt_fence": checked.attempt_fence,
        "idempotency_key": checked.idempotency_key,
        "queried_at": _canonical_timestamp(queried_at),
        "may_authorize": False,
    }
    digest = _self_hash(OUTCOME_PIPELINE_READINESS_QUERY_SCHEMA, body)
    return OutcomePipelineReadinessQuery.model_validate(
        {
            **body,
            "query_ref": f"outcome-pipeline-readiness-query@sha256:{digest}",
            "query_hash": digest,
        }
    )


class OutcomeEvent(_FrozenModel):
    schema_id: Literal["hapax.outcome-event.v1"] = Field(alias="schema")
    event_ref: str
    event_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_lease: ContentAddress
    bound_execution_call: ContentAddress
    effect_observation: ContentAddress
    completion_evaluation: ContentAddress
    outcome_readiness: ContentAddress
    effect_manifest: ContentAddress
    executor_descriptor: ContentAddress
    executor_registry_projection: ContentAddress
    executor: ContentAddress
    observation_contract: ContentAddress
    completion_predicate: ContentAddress
    invocation_id: str
    attempt_fence: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str
    outcome: Literal["succeeded", "failed", "indeterminate"]
    effect_disposition: Literal[
        "applied",
        "not_applied",
        "partial",
        "not_applicable",
        "unknown",
    ]
    closure_state: Literal["closed", "open"]
    reconciliation_contract: ContentAddress
    occurred_at: str
    may_authorize: Literal[False]

    @field_validator("event_ref", "invocation_id", "idempotency_key")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("occurred_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_event(self) -> Self:
        expected_outcome_key = _self_hash(
            "hapax.outcome-attempt-key.v1",
            {
                "idempotency_key": self.idempotency_key,
                "attempt_fence": self.attempt_fence,
            },
        )
        open_loop = self.outcome == "indeterminate" or self.effect_disposition in {
            "partial",
            "unknown",
        }
        if self.outcome_key != expected_outcome_key:
            raise ValueError("outcome key does not bind the exact attempt")
        if (self.closure_state == "open") != open_loop:
            raise ValueError("outcome closure differs from evaluation certainty")
        body = self.model_dump(mode="json", by_alias=True, exclude={"event_ref", "event_hash"})
        expected = _self_hash(OUTCOME_EVENT_SCHEMA, body)
        if self.event_hash != expected or self.event_ref != (
            f"outcome-event:{self.outcome_key}@sha256:{expected}"
        ):
            raise ValueError("outcome event reference/hash do not bind its body")
        return self


def build_outcome_event(
    lease: ExecutionLease,
    observation: EffectObservation,
    evaluation: CompletionEvaluation,
    readiness: OutcomePipelineReadinessEnvelope,
    *,
    occurred_at: str | datetime,
) -> OutcomeEvent:
    checked = require_admitted_execution_lease(lease)
    observed = EffectObservation.model_validate(observation.model_dump(mode="json", by_alias=True))
    evaluated = CompletionEvaluation.model_validate(
        evaluation.model_dump(mode="json", by_alias=True)
    )
    ready = OutcomePipelineReadinessEnvelope.model_validate(
        readiness.model_dump(mode="json", by_alias=True)
    )
    lease_address = ContentAddress(ref=checked.lease_ref, sha256=checked.lease_hash)
    call_address = ContentAddress(
        ref=checked.bound_call.call_ref,
        sha256=checked.bound_call.call_hash,
    )
    observation_address = ContentAddress(
        ref=observed.observation_ref,
        sha256=observed.observation_hash,
    )
    evaluation_address = ContentAddress(
        ref=evaluated.evaluation_ref,
        sha256=evaluated.evaluation_hash,
    )
    if (
        observed.execution_lease != lease_address
        or observed.bound_execution_call != call_address
        or evaluated.query.execution_lease != lease_address
        or evaluated.query.bound_execution_call != call_address
        or evaluated.query.effect_observation != observation_address
        or evaluated.query.effect_manifest != observed.effect_manifest
        or evaluated.query.observation_contract != observed.observation_contract
        or evaluated.query.completion_predicate != observed.completion_predicate
        or evaluated.query.evidence_refs != observed.evidence_refs
        or ready.decision != "ready"
        or ready.query.execution_lease != lease_address
        or ready.query.bound_execution_call != call_address
        or ready.query.effect_manifest != checked.effect_manifest
        or ready.query.executor_descriptor != checked.executor_descriptor
        or ready.query.executor_registry_projection != checked.executor_registry_projection
        or ready.query.completion_predicate != checked.completion_predicate
        or ready.query.evaluator != evaluated.evaluator
        or ready.query.invocation_id != checked.invocation_id
        or ready.query.attempt_fence != checked.attempt_fence
        or ready.query.idempotency_key != checked.idempotency_key
    ):
        raise ExecutionAdmissionError(
            "outcome_event_input_mismatch",
            "build the outcome event from one exact observed and evaluated attempt",
        )
    occurred = _canonical_timestamp(occurred_at)
    if occurred < max(observed.observed_at, evaluated.evaluated_at):
        raise ExecutionAdmissionError(
            "outcome_event_predates_evidence",
            "append the outcome only after observation and completion evaluation",
        )
    if occurred >= ready.stale_after:
        raise ExecutionAdmissionError(
            "outcome_readiness_expired_before_commit",
            "refresh readiness before committing the canonical outcome event",
        )
    outcome = {
        "satisfied": "succeeded",
        "unsatisfied": "failed",
        "unknown": "indeterminate",
    }[evaluated.decision]
    closure_state = (
        "open"
        if outcome == "indeterminate" or evaluated.effect_disposition in {"partial", "unknown"}
        else "closed"
    )
    reconciliation = checked.reconciliation_contract
    if reconciliation is None:
        raise ExecutionAdmissionError(
            "outcome_reconciliation_contract_missing",
            "bind every effect-bearing manifest to a reconciliation contract",
        )
    outcome_key = _self_hash(
        "hapax.outcome-attempt-key.v1",
        {"idempotency_key": checked.idempotency_key, "attempt_fence": checked.attempt_fence},
    )
    body: dict[str, object] = {
        "schema": OUTCOME_EVENT_SCHEMA,
        "outcome_key": outcome_key,
        "execution_lease": lease_address,
        "bound_execution_call": call_address,
        "effect_observation": observation_address,
        "completion_evaluation": evaluation_address,
        "outcome_readiness": ContentAddress(
            ref=ready.envelope_ref,
            sha256=ready.envelope_hash,
        ),
        "effect_manifest": checked.effect_manifest,
        "executor_descriptor": checked.executor_descriptor,
        "executor_registry_projection": checked.executor_registry_projection,
        "executor": checked.executor,
        "observation_contract": checked.observation_contract,
        "completion_predicate": checked.completion_predicate,
        "invocation_id": checked.invocation_id,
        "attempt_fence": checked.attempt_fence,
        "idempotency_key": checked.idempotency_key,
        "outcome": outcome,
        "effect_disposition": evaluated.effect_disposition,
        "closure_state": closure_state,
        "reconciliation_contract": reconciliation,
        "occurred_at": occurred,
        "may_authorize": False,
    }
    digest = _self_hash(OUTCOME_EVENT_SCHEMA, body)
    return OutcomeEvent.model_validate(
        {
            **body,
            "event_ref": f"outcome-event:{outcome_key}@sha256:{digest}",
            "event_hash": digest,
        }
    )


class EventAppendReceipt(_FrozenModel):
    schema_id: Literal["hapax.event-append-receipt.v1"] = Field(alias="schema")
    receipt_ref: str
    receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome_event: ContentAddress
    committer: ContentAddress
    event_plane: ContentAddress
    expected_frontier: ContentAddress
    committed_frontier: ContentAddress
    append_status: Literal["appended", "duplicate"]
    committed_at: str
    may_authorize: Literal[False]

    @field_validator("receipt_ref")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("committed_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        body = self.model_dump(mode="json", by_alias=True, exclude={"receipt_ref", "receipt_hash"})
        expected = _self_hash(EVENT_APPEND_RECEIPT_SCHEMA, body)
        if self.receipt_hash != expected or self.receipt_ref != (
            f"event-append-receipt@sha256:{expected}"
        ):
            raise ValueError("append receipt reference/hash do not bind its body")
        return self


class OutcomeReceipt(_FrozenModel):
    """Canonical closure/open-loop receipt built only after event-plane append."""

    schema_id: Literal["hapax.outcome-receipt.v1"] = Field(alias="schema")
    receipt_ref: str
    receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_lease: ContentAddress
    bound_execution_call: ContentAddress
    effect_observation: ContentAddress
    completion_evaluation: ContentAddress
    outcome_readiness: ContentAddress
    effect_manifest: ContentAddress
    executor_descriptor: ContentAddress
    executor_registry_projection: ContentAddress
    executor: ContentAddress
    observation_contract: ContentAddress
    completion_predicate: ContentAddress
    invocation_id: str
    attempt_fence: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str
    committer: ContentAddress
    append_receipt: ContentAddress
    outcome_event: ContentAddress
    event_frontier: ContentAddress
    outcome: Literal["succeeded", "failed", "indeterminate"]
    effect_disposition: Literal[
        "applied",
        "not_applied",
        "partial",
        "not_applicable",
        "unknown",
    ]
    closure_state: Literal["closed", "open"]
    reconciliation_contract: ContentAddress
    committed_at: str
    may_authorize: Literal[False]

    @field_validator("receipt_ref", "invocation_id", "idempotency_key")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("committed_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        open_loop = self.outcome == "indeterminate" or self.effect_disposition in {
            "partial",
            "unknown",
        }
        if (self.closure_state == "open") != open_loop:
            raise ValueError("outcome receipt closure differs from its semantic evidence")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"receipt_ref", "receipt_hash"},
        )
        expected = _self_hash(OUTCOME_RECEIPT_SCHEMA, body)
        if self.receipt_hash != expected or self.receipt_ref != (
            f"outcome-receipt@sha256:{expected}"
        ):
            raise ValueError("outcome receipt reference/hash do not bind its body")
        return self


def build_outcome_receipt(
    event: OutcomeEvent,
    append_receipt: EventAppendReceipt,
) -> OutcomeReceipt:
    """Project a canonical outcome receipt from one exact committed event."""

    checked_event = OutcomeEvent.model_validate(event.model_dump(mode="json", by_alias=True))
    checked_append = EventAppendReceipt.model_validate(
        append_receipt.model_dump(mode="json", by_alias=True)
    )
    event_address = ContentAddress(
        ref=checked_event.event_ref,
        sha256=checked_event.event_hash,
    )
    if (
        checked_append.outcome_key != checked_event.outcome_key
        or checked_append.outcome_event != event_address
        or checked_append.committed_at < checked_event.occurred_at
    ):
        raise ExecutionAdmissionError(
            "outcome_append_binding_mismatch",
            "build the receipt from the append acknowledgement for the exact outcome event",
        )
    body: dict[str, object] = {
        "schema": OUTCOME_RECEIPT_SCHEMA,
        "execution_lease": checked_event.execution_lease,
        "bound_execution_call": checked_event.bound_execution_call,
        "effect_observation": checked_event.effect_observation,
        "completion_evaluation": checked_event.completion_evaluation,
        "outcome_readiness": checked_event.outcome_readiness,
        "effect_manifest": checked_event.effect_manifest,
        "executor_descriptor": checked_event.executor_descriptor,
        "executor_registry_projection": checked_event.executor_registry_projection,
        "executor": checked_event.executor,
        "observation_contract": checked_event.observation_contract,
        "completion_predicate": checked_event.completion_predicate,
        "invocation_id": checked_event.invocation_id,
        "attempt_fence": checked_event.attempt_fence,
        "idempotency_key": checked_event.idempotency_key,
        "committer": checked_append.committer,
        "append_receipt": ContentAddress(
            ref=checked_append.receipt_ref,
            sha256=checked_append.receipt_hash,
        ),
        "outcome_event": event_address,
        "event_frontier": checked_append.committed_frontier,
        "outcome": checked_event.outcome,
        "effect_disposition": checked_event.effect_disposition,
        "closure_state": checked_event.closure_state,
        "reconciliation_contract": checked_event.reconciliation_contract,
        "committed_at": checked_append.committed_at,
        "may_authorize": False,
    }
    digest = _self_hash(OUTCOME_RECEIPT_SCHEMA, body)
    return OutcomeReceipt.model_validate(
        {
            **body,
            "receipt_ref": f"outcome-receipt@sha256:{digest}",
            "receipt_hash": digest,
        }
    )


class OutcomeProjectionSnapshot(_FrozenModel):
    """Data-only, content-addressed replay of one complete event-plane outcome chain."""

    schema_id: Literal["hapax.outcome-projection-snapshot.v1"] = Field(alias="schema")
    snapshot_ref: str
    snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    committer: ContentAddress
    event_plane: ContentAddress
    event_frontier: ContentAddress
    activation_generation_roots: tuple[ContentAddress, ...] = Field(min_length=1)
    effect_observation: EffectObservation
    completion_evaluation: CompletionEvaluation
    outcome_readiness: OutcomePipelineReadinessEnvelope
    outcome_event: OutcomeEvent
    append_receipt: EventAppendReceipt
    outcome_receipt: OutcomeReceipt
    may_authorize: Literal[False]

    @field_validator("snapshot_ref")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("activation_generation_roots")
    @classmethod
    def validate_roots(
        cls,
        value: tuple[ContentAddress, ...],
    ) -> tuple[ContentAddress, ...]:
        return _content_address_set(value)

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        observation_address = ContentAddress(
            ref=self.effect_observation.observation_ref,
            sha256=self.effect_observation.observation_hash,
        )
        evaluation_address = ContentAddress(
            ref=self.completion_evaluation.evaluation_ref,
            sha256=self.completion_evaluation.evaluation_hash,
        )
        readiness_address = ContentAddress(
            ref=self.outcome_readiness.envelope_ref,
            sha256=self.outcome_readiness.envelope_hash,
        )
        event_address = ContentAddress(
            ref=self.outcome_event.event_ref,
            sha256=self.outcome_event.event_hash,
        )
        append_address = ContentAddress(
            ref=self.append_receipt.receipt_ref,
            sha256=self.append_receipt.receipt_hash,
        )
        expected_outcome = {
            "satisfied": "succeeded",
            "unsatisfied": "failed",
            "unknown": "indeterminate",
        }[self.completion_evaluation.decision]
        mismatches: list[str] = []
        if not (
            self.effect_observation.execution_lease
            == self.completion_evaluation.query.execution_lease
            == self.outcome_readiness.query.execution_lease
            == self.outcome_event.execution_lease
        ):
            mismatches.append("execution_lease")
        if not (
            self.effect_observation.bound_execution_call
            == self.completion_evaluation.query.bound_execution_call
            == self.outcome_readiness.query.bound_execution_call
            == self.outcome_event.bound_execution_call
        ):
            mismatches.append("bound_execution_call")
        if not (
            self.effect_observation.effect_manifest
            == self.completion_evaluation.query.effect_manifest
            == self.outcome_readiness.query.effect_manifest
            == self.outcome_event.effect_manifest
        ):
            mismatches.append("effect_manifest")
        if not (
            self.effect_observation.executor_descriptor
            == self.outcome_readiness.query.executor_descriptor
            == self.outcome_event.executor_descriptor
        ):
            mismatches.append("executor_descriptor")
        if not (
            self.effect_observation.executor_registry_projection
            == self.outcome_readiness.query.executor_registry_projection
            == self.outcome_event.executor_registry_projection
        ):
            mismatches.append("executor_registry")
        if not (
            self.effect_observation.observation_contract
            == self.completion_evaluation.query.observation_contract
            == self.outcome_event.observation_contract
        ):
            mismatches.append("observation_contract")
        if not (
            self.effect_observation.completion_predicate
            == self.completion_evaluation.query.completion_predicate
            == self.outcome_readiness.query.completion_predicate
            == self.outcome_event.completion_predicate
        ):
            mismatches.append("completion_predicate")
        if (
            self.outcome_readiness.query.committer != self.committer
            or self.outcome_readiness.query.event_plane != self.event_plane
        ):
            mismatches.append("readiness_event_plane")
        if self.completion_evaluation.query.effect_observation != observation_address:
            mismatches.append("completion_observation")
        if self.completion_evaluation.query.evidence_refs != self.effect_observation.evidence_refs:
            mismatches.append("completion_evidence")
        if self.outcome_event.effect_observation != observation_address:
            mismatches.append("event_observation")
        if self.outcome_event.completion_evaluation != evaluation_address:
            mismatches.append("event_evaluation")
        if self.outcome_event.outcome_readiness != readiness_address:
            mismatches.append("event_readiness")
        if self.outcome_event.outcome != expected_outcome:
            mismatches.append("event_outcome")
        if self.outcome_event.effect_disposition != self.completion_evaluation.effect_disposition:
            mismatches.append("event_effect_disposition")
        if self.append_receipt.outcome_event != event_address:
            mismatches.append("append_event")
        if self.append_receipt.outcome_key != self.outcome_event.outcome_key:
            mismatches.append("append_key")
        if self.append_receipt.committer != self.committer:
            mismatches.append("append_committer")
        if self.append_receipt.event_plane != self.event_plane:
            mismatches.append("append_event_plane")
        if self.append_receipt.expected_frontier != self.outcome_readiness.event_frontier:
            mismatches.append("append_expected_frontier")
        if self.append_receipt.committed_frontier != self.event_frontier:
            mismatches.append("append_committed_frontier")
        if not (
            self.outcome_event.occurred_at
            <= self.append_receipt.committed_at
            < self.outcome_readiness.stale_after
        ):
            mismatches.append("append_time")
        if self.outcome_receipt != build_outcome_receipt(
            self.outcome_event,
            self.append_receipt,
        ):
            mismatches.append("outcome_receipt")
        if self.outcome_receipt.append_receipt != append_address:
            mismatches.append("receipt_append")
        if mismatches:
            raise ValueError("outcome projection chain mismatch: " + ",".join(mismatches))
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"snapshot_ref", "snapshot_hash"},
        )
        expected = _self_hash(OUTCOME_PROJECTION_SNAPSHOT_SCHEMA, body)
        if self.snapshot_hash != expected or self.snapshot_ref != (
            f"outcome-projection-snapshot@sha256:{expected}"
        ):
            raise ValueError("outcome projection reference/hash do not bind its body")
        return self


def build_outcome_projection_snapshot(
    *,
    committer: ContentAddress,
    event_plane: ContentAddress,
    activation_generation_roots: Sequence[ContentAddress],
    observation: EffectObservation,
    evaluation: CompletionEvaluation,
    readiness: OutcomePipelineReadinessEnvelope,
    event: OutcomeEvent,
    append_receipt: EventAppendReceipt,
) -> OutcomeProjectionSnapshot:
    outcome_receipt = build_outcome_receipt(event, append_receipt)
    body: dict[str, object] = {
        "schema": OUTCOME_PROJECTION_SNAPSHOT_SCHEMA,
        "committer": committer,
        "event_plane": event_plane,
        "event_frontier": append_receipt.committed_frontier,
        "activation_generation_roots": tuple(
            sorted(
                {_content_address_key(item): item for item in activation_generation_roots}.values(),
                key=_content_address_key,
            )
        ),
        "effect_observation": observation,
        "completion_evaluation": evaluation,
        "outcome_readiness": readiness,
        "outcome_event": event,
        "append_receipt": append_receipt,
        "outcome_receipt": outcome_receipt,
        "may_authorize": False,
    }
    digest = _self_hash(OUTCOME_PROJECTION_SNAPSHOT_SCHEMA, body)
    return OutcomeProjectionSnapshot.model_validate(
        {
            **body,
            "snapshot_ref": f"outcome-projection-snapshot@sha256:{digest}",
            "snapshot_hash": digest,
        }
    )


def _claim_publication_artifacts(
    snapshot: AppliedClaimPublicationSnapshot,
) -> tuple[ClaimPublicationArtifact, ...]:
    from shared.sdlc_claim import (
        AppliedClaimPublicationSnapshot as SnapshotType,
    )
    from shared.sdlc_claim import (
        ClaimAdmissionConsumption,
        ClaimPublicationIntent,
        ClaimPublicationReceipt,
    )
    from shared.sdlc_task_store import claim_dispatch_binding_path

    checked = _require_exact_type(snapshot, SnapshotType, "applied claim publication snapshot")
    receipt = _require_exact_type(
        checked.receipt,
        ClaimPublicationReceipt,
        "claim publication receipt",
    )
    intent = _require_exact_type(
        checked.intent,
        ClaimPublicationIntent,
        "claim publication intent",
    )
    _require_exact_type(
        checked.admission_consumption,
        ClaimAdmissionConsumption,
        "claim admission consumption",
    )
    role_session_key = f"{receipt.role}-{receipt.session_id}"
    if (
        intent.task_id != receipt.task_id
        or intent.role != receipt.role
        or intent.session_id != receipt.session_id
        or intent.claim_epoch != receipt.claim_epoch
    ):
        raise ExecutionAdmissionError(
            "claim_publication_artifact_vector_mismatch",
            "resolve the exact publication intent and receipt postimages",
            receipt.publication_id,
        )

    def artifact(
        kind: ClaimPublicationArtifactKind,
        key: str,
        path: Path,
        content: bytes,
        mode: int,
    ) -> ClaimPublicationArtifact:
        normalized = str(_normalized_path(path))
        digest = _sha256(content)
        return ClaimPublicationArtifact(
            kind=kind,
            key=key,
            path=normalized,
            content_sha256=digest,
            mode=mode,
            file_address=ContentAddress(
                ref=f"file:{normalized}@sha256:{digest}",
                sha256=digest,
            ),
        )

    return (
        artifact(
            "receipt",
            receipt.publication_id,
            receipt.receipt_path,
            checked.receipt_content,
            checked.receipt_mode,
        ),
        artifact(
            "manifest",
            receipt.publication_id,
            receipt.manifest_path,
            checked.manifest_content,
            checked.manifest_mode,
        ),
        artifact(
            "task_note",
            receipt.task_id,
            intent.note_path,
            intent.note_after,
            intent.note_mode,
        ),
        *(
            artifact(kind, key, path, content, mode)
            for key in (receipt.role, role_session_key)
            for kind, path, content, mode in (
                (
                    "claim",
                    intent.cache_dir / f"cc-active-task-{key}",
                    f"{intent.task_id}\n".encode("ascii"),
                    0o644,
                ),
                (
                    "epoch",
                    intent.cache_dir / f"cc-claim-epoch-{key}",
                    f"{intent.claim_epoch} {intent.task_id}\n".encode("ascii"),
                    0o644,
                ),
                (
                    "dispatch_binding",
                    claim_dispatch_binding_path(intent.cache_dir, key),
                    json.dumps(
                        intent.binding.to_record(),
                        allow_nan=False,
                        ensure_ascii=True,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("ascii")
                    + b"\n",
                    0o600,
                ),
            )
        ),
    )


def claim_publication_effect_evidence_refs(
    snapshot: AppliedClaimPublicationSnapshot,
) -> tuple[ContentAddress, ...]:
    """Return the exact effect postimages an observation must cover."""

    artifacts = _claim_publication_artifacts(snapshot)
    projection_vector = ContentAddress(
        ref=(
            "claim-publication-projection-vector@sha256:"
            f"{snapshot.receipt.projection_vector_sha256}"
        ),
        sha256=snapshot.receipt.projection_vector_sha256,
    )
    return tuple(
        sorted(
            {
                _content_address_key(item): item
                for item in (
                    *tuple(artifact.file_address for artifact in artifacts),
                    projection_vector,
                )
            }.values(),
            key=_content_address_key,
        )
    )


def build_claim_publication_completion_evidence(
    snapshot: AppliedClaimPublicationSnapshot,
    projection: OutcomeProjectionSnapshot,
    *,
    outcome_validity_resolver: ContentAddress,
) -> ClaimPublicationCompletionEvidence:
    """Bind a successful outcome to every exact claim publication postimage."""

    from shared.sdlc_claim import AppliedClaimPublicationSnapshot as SnapshotType
    from shared.sdlc_claim import ClaimAdmissionConsumption

    checked_snapshot = _require_exact_type(
        snapshot,
        SnapshotType,
        "applied claim publication snapshot",
    )

    checked_projection = OutcomeProjectionSnapshot.model_validate(
        _require_exact_type(
            projection,
            OutcomeProjectionSnapshot,
            "outcome projection snapshot",
        ).model_dump(mode="json", by_alias=True)
    )
    checked_validity_resolver = ContentAddress.model_validate(
        _require_exact_type(
            outcome_validity_resolver,
            ContentAddress,
            "outcome validity resolver",
        ).model_dump(mode="json")
    )
    artifacts = _claim_publication_artifacts(checked_snapshot)
    consumption = _require_exact_type(
        checked_snapshot.admission_consumption,
        ClaimAdmissionConsumption,
        "claim admission consumption",
    )
    receipt = checked_snapshot.receipt
    outcome = checked_projection.outcome_receipt
    required_evidence = {
        _content_address_key(item)
        for item in claim_publication_effect_evidence_refs(checked_snapshot)
    }
    observed_evidence = {
        _content_address_key(item) for item in checked_projection.effect_observation.evidence_refs
    }
    if not required_evidence.issubset(observed_evidence):
        raise ExecutionAdmissionError(
            "claim_publication_effect_evidence_incomplete",
            "observe the receipt, manifest, task postimage, sidecars, and projection vector",
            receipt.publication_id,
        )
    expected_lease = consumption.execution_lease
    expected_call = consumption.bound_execution_call
    if (
        receipt.task_id != consumption.task_id
        or receipt.role != consumption.lane
        or receipt.session_id != consumption.session_id
        or receipt.claim_epoch != consumption.claim_epoch
        or checked_projection.effect_observation.execution_lease != expected_lease
        or checked_projection.effect_observation.bound_execution_call != expected_call
        or outcome.execution_lease != expected_lease
        or outcome.bound_execution_call != expected_call
        or outcome.outcome != "succeeded"
        or outcome.effect_disposition != "applied"
        or outcome.closure_state != "closed"
    ):
        raise ExecutionAdmissionError(
            "claim_publication_completion_binding_mismatch",
            "bind completion to the exact successful applied publication attempt",
            receipt.publication_id,
        )
    body: dict[str, object] = {
        "schema": CLAIM_PUBLICATION_COMPLETION_EVIDENCE_SCHEMA,
        "publication_id": receipt.publication_id,
        "task_ref": receipt.task_id,
        "lane": receipt.role,
        "session_ref": receipt.session_id,
        "claim_epoch": receipt.claim_epoch,
        "claim_publication_intent": ContentAddress(
            ref=checked_snapshot.intent.intent_ref,
            sha256=checked_snapshot.intent.intent_sha256,
        ),
        "admission_consumption": ContentAddress(
            ref=consumption.consumption_ref,
            sha256=consumption.consumption_hash,
        ),
        "execution_lease": expected_lease,
        "bound_execution_call": expected_call,
        "claim_note_postimage_sha256": receipt.claim_note_postimage_sha256,
        "dispatch_binding_postimage_sha256": artifacts[5].content_sha256,
        "artifacts": artifacts,
        "projection_vector": ContentAddress(
            ref=(f"claim-publication-projection-vector@sha256:{receipt.projection_vector_sha256}"),
            sha256=receipt.projection_vector_sha256,
        ),
        "effect_observation": ContentAddress(
            ref=checked_projection.effect_observation.observation_ref,
            sha256=checked_projection.effect_observation.observation_hash,
        ),
        "outcome_projection": ContentAddress(
            ref=checked_projection.snapshot_ref,
            sha256=checked_projection.snapshot_hash,
        ),
        "outcome_receipt": ContentAddress(
            ref=outcome.receipt_ref,
            sha256=outcome.receipt_hash,
        ),
        "committer": checked_projection.committer,
        "event_plane": checked_projection.event_plane,
        "outcome_validity_resolver": checked_validity_resolver,
        "source_event_frontier": checked_projection.event_frontier,
        "outcome": "succeeded",
        "effect_disposition": "applied",
        "closure_state": "closed",
        "observed_at": checked_projection.effect_observation.observed_at,
        "committed_at": outcome.committed_at,
        "may_authorize": False,
    }
    digest = _self_hash(CLAIM_PUBLICATION_COMPLETION_EVIDENCE_SCHEMA, body)
    return ClaimPublicationCompletionEvidence.model_validate(
        {
            **body,
            "evidence_ref": f"claim-publication-completion-evidence@sha256:{digest}",
            "evidence_hash": digest,
        }
    )


def outcome_projection_validity_roots(
    projection: OutcomeProjectionSnapshot,
    *,
    checked_frontier: ContentAddress,
) -> tuple[ContentAddress, ...]:
    """Return exact immutable roots a query-time outcome validity must cover."""

    checked = OutcomeProjectionSnapshot.model_validate(
        _require_exact_type(
            projection,
            OutcomeProjectionSnapshot,
            "outcome projection snapshot",
        ).model_dump(mode="json", by_alias=True)
    )
    frontier = ContentAddress.model_validate(
        _require_exact_type(
            checked_frontier,
            ContentAddress,
            "checked outcome frontier",
        ).model_dump(mode="json")
    )
    addresses = (
        ContentAddress(ref=checked.snapshot_ref, sha256=checked.snapshot_hash),
        checked.committer,
        checked.event_plane,
        checked.event_frontier,
        frontier,
        ContentAddress(
            ref=checked.effect_observation.observation_ref,
            sha256=checked.effect_observation.observation_hash,
        ),
        ContentAddress(
            ref=checked.completion_evaluation.evaluation_ref,
            sha256=checked.completion_evaluation.evaluation_hash,
        ),
        ContentAddress(
            ref=checked.outcome_readiness.envelope_ref,
            sha256=checked.outcome_readiness.envelope_hash,
        ),
        ContentAddress(
            ref=checked.outcome_event.event_ref, sha256=checked.outcome_event.event_hash
        ),
        ContentAddress(
            ref=checked.append_receipt.receipt_ref,
            sha256=checked.append_receipt.receipt_hash,
        ),
        ContentAddress(
            ref=checked.outcome_receipt.receipt_ref,
            sha256=checked.outcome_receipt.receipt_hash,
        ),
        *checked.activation_generation_roots,
    )
    return tuple(
        sorted(
            {_content_address_key(item): item for item in addresses}.values(),
            key=_content_address_key,
        )
    )


class OutcomeReplayCatalogSnapshot(_FrozenModel):
    """One immutable read of moving outcome and frontier-validity state."""

    schema_id: Literal["hapax.outcome-replay-catalog-snapshot.v1"] = Field(alias="schema")
    snapshot_ref: str
    snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    committer: ContentAddress
    event_plane: ContentAddress
    projection_resolver: ContentAddress
    validity_resolver: ContentAddress
    checked_frontier: ContentAddress
    projections: tuple[OutcomeProjectionSnapshot, ...]
    validity_envelopes: tuple[FrontierValidityEnvelope, ...]
    source_receipt: ContentAddress
    observed_at: str
    may_authorize: Literal[False]

    @field_validator("snapshot_ref")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("observed_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        stable = (
            self.committer,
            self.event_plane,
            self.projection_resolver,
            self.validity_resolver,
            self.checked_frontier,
            self.source_receipt,
        )
        if any(not item.ref.endswith(f"@sha256:{item.sha256}") for item in stable):
            raise ValueError("outcome replay catalog roots must be content addressed")
        projection_keys = tuple(
            (item.outcome_receipt.idempotency_key, item.outcome_receipt.attempt_fence)
            for item in self.projections
        )
        if projection_keys != tuple(sorted(set(projection_keys))):
            raise ValueError("outcome replay projections must be sorted and attempt-unique")
        if any(
            item.committer != self.committer or item.event_plane != self.event_plane
            for item in self.projections
        ):
            raise ValueError("outcome replay projections differ from stable catalog roots")
        validity_keys = tuple(
            (
                item.subject_projection.ref,
                item.subject_projection.sha256,
                item.checked_at,
            )
            for item in self.validity_envelopes
        )
        if validity_keys != tuple(sorted(set(validity_keys))):
            raise ValueError("outcome validity envelopes must be sorted and interval-unique")
        subjects = {
            (item.snapshot_ref, item.snapshot_hash) for item in self.projections
        }
        projection_by_subject = {
            (item.snapshot_ref, item.snapshot_hash): item for item in self.projections
        }
        if any(
            item.resolver != self.validity_resolver
            or item.event_plane != self.event_plane
            or item.checked_frontier != self.checked_frontier
            or (item.subject_projection.ref, item.subject_projection.sha256) not in subjects
            for item in self.validity_envelopes
        ):
            raise ValueError("outcome validity envelopes differ from their catalog snapshot")
        if any(
            item.checked_at
            < projection_by_subject[
                (item.subject_projection.ref, item.subject_projection.sha256)
            ].outcome_receipt.committed_at
            for item in self.validity_envelopes
        ):
            raise ValueError("outcome validity cannot predate its outcome commit")
        for index, first in enumerate(self.validity_envelopes):
            for second in self.validity_envelopes[index + 1 :]:
                if (
                    first.subject_projection == second.subject_projection
                    and max(first.checked_at, second.checked_at)
                    < min(first.stale_after, second.stale_after)
                ):
                    raise ValueError("outcome validity intervals must not overlap")
        if any(item.checked_at > self.observed_at for item in self.validity_envelopes):
            raise ValueError("catalog observation cannot predate frontier validation")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"snapshot_ref", "snapshot_hash"},
        )
        expected = _self_hash(OUTCOME_REPLAY_CATALOG_SCHEMA, body)
        if self.snapshot_hash != expected or self.snapshot_ref != (
            f"outcome-replay-catalog-snapshot@sha256:{expected}"
        ):
            raise ValueError("outcome replay catalog reference/hash do not bind its body")
        return self


def build_outcome_replay_catalog_snapshot(
    *,
    committer: ContentAddress,
    event_plane: ContentAddress,
    projection_resolver: ContentAddress,
    validity_resolver: ContentAddress,
    checked_frontier: ContentAddress,
    projections: Sequence[OutcomeProjectionSnapshot],
    validity_envelopes: Sequence[FrontierValidityEnvelope],
    source_receipt: ContentAddress,
    observed_at: str | datetime,
) -> OutcomeReplayCatalogSnapshot:
    checked_addresses = {
        name: ContentAddress.model_validate(
            _require_exact_type(value, ContentAddress, name).model_dump(mode="json")
        )
        for name, value in (
            ("committer", committer),
            ("event plane", event_plane),
            ("projection resolver", projection_resolver),
            ("validity resolver", validity_resolver),
            ("checked frontier", checked_frontier),
            ("source receipt", source_receipt),
        )
    }
    checked_projections = tuple(
        OutcomeProjectionSnapshot.model_validate(
            _require_exact_type(
                item,
                OutcomeProjectionSnapshot,
                "outcome projection snapshot",
            ).model_dump(mode="json", by_alias=True)
        )
        for item in projections
    )
    checked_validity = tuple(
        FrontierValidityEnvelope.model_validate(
            _require_exact_type(
                item,
                FrontierValidityEnvelope,
                "outcome frontier validity envelope",
            ).model_dump(mode="json", by_alias=True)
        )
        for item in validity_envelopes
    )
    body: dict[str, object] = {
        "schema": OUTCOME_REPLAY_CATALOG_SCHEMA,
        "committer": checked_addresses["committer"],
        "event_plane": checked_addresses["event plane"],
        "projection_resolver": checked_addresses["projection resolver"],
        "validity_resolver": checked_addresses["validity resolver"],
        "checked_frontier": checked_addresses["checked frontier"],
        "projections": checked_projections,
        "validity_envelopes": checked_validity,
        "source_receipt": checked_addresses["source receipt"],
        "observed_at": _canonical_timestamp(observed_at),
        "may_authorize": False,
    }
    digest = _self_hash(OUTCOME_REPLAY_CATALOG_SCHEMA, body)
    return OutcomeReplayCatalogSnapshot.model_validate(
        {
            **body,
            "snapshot_ref": f"outcome-replay-catalog-snapshot@sha256:{digest}",
            "snapshot_hash": digest,
        }
    )


class OutcomeReplayResult(_FrozenModel):
    """Query-time selection of one current outcome from one catalog snapshot."""

    schema_id: Literal["hapax.outcome-replay-result.v1"] = Field(alias="schema")
    result_ref: str
    result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog_snapshot: ContentAddress
    projection: OutcomeProjectionSnapshot
    validity: FrontierValidityEnvelope
    queried_at: str
    may_authorize: Literal[False]

    @field_validator("result_ref")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("queried_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        return _checked_timestamp(value)

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.catalog_snapshot.ref != (
            f"outcome-replay-catalog-snapshot@sha256:{self.catalog_snapshot.sha256}"
        ):
            raise ValueError("outcome replay result requires a canonical catalog snapshot")
        subject = ContentAddress(
            ref=self.projection.snapshot_ref,
            sha256=self.projection.snapshot_hash,
        )
        if (
            self.validity.subject_projection != subject
            or not (self.validity.checked_at <= self.queried_at < self.validity.stale_after)
        ):
            raise ValueError("outcome replay result is outside its exact validity interval")
        expected_roots = outcome_projection_validity_roots(
            self.projection,
            checked_frontier=self.validity.checked_frontier,
        )
        observed_roots = tuple(item.root for item in self.validity.root_dispositions)
        if (
            self.validity.decision != "valid"
            or self.validity.event_plane != self.projection.event_plane
            or self.validity.source_frontier != self.projection.event_frontier
            or self.validity.checked_at < self.projection.outcome_receipt.committed_at
            or observed_roots != expected_roots
        ):
            raise ValueError("outcome replay result lacks exact current projection coverage")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"result_ref", "result_hash"},
        )
        expected = _self_hash(OUTCOME_REPLAY_RESULT_SCHEMA, body)
        if self.result_hash != expected or self.result_ref != (
            f"outcome-replay-result@sha256:{expected}"
        ):
            raise ValueError("outcome replay result reference/hash do not bind its body")
        return self


@dataclass(frozen=True)
class OutcomeCommitter:
    """Data-only event-plane replay catalog; append remains a Gate-0B effect."""

    committer: ContentAddress | None = None
    event_plane: ContentAddress | None = None
    projection_resolver: ContentAddress | None = None
    validity_resolver: ContentAddress | None = None
    catalog_snapshot: OutcomeReplayCatalogSnapshot | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "committer",
            "event_plane",
            "projection_resolver",
            "validity_resolver",
        ):
            value = getattr(self, field_name)
            if value is None:
                continue
            _require_exact_type(value, ContentAddress, f"outcome {field_name}")
            object.__setattr__(
                self,
                field_name,
                ContentAddress.model_validate(value.model_dump(mode="json")),
            )
        if self.catalog_snapshot is None:
            return
        snapshot = OutcomeReplayCatalogSnapshot.model_validate(
            _require_exact_type(
                self.catalog_snapshot,
                OutcomeReplayCatalogSnapshot,
                "outcome replay catalog snapshot",
            ).model_dump(mode="json", by_alias=True)
        )
        expected = (
            self.committer,
            self.event_plane,
            self.projection_resolver,
            self.validity_resolver,
        )
        observed = (
            snapshot.committer,
            snapshot.event_plane,
            snapshot.projection_resolver,
            snapshot.validity_resolver,
        )
        if expected != observed:
            raise ValueError("outcome catalog snapshot differs from stable resolver identities")
        object.__setattr__(self, "catalog_snapshot", snapshot)

    def catalog_address(self) -> ContentAddress:
        if self.catalog_snapshot is None:
            raise ExecutionAdmissionError(
                "outcome_replay_catalog_unavailable",
                "read one immutable outcome catalog snapshot before replay",
            )
        return ContentAddress(
            ref=self.catalog_snapshot.snapshot_ref,
            sha256=self.catalog_snapshot.snapshot_hash,
        )

    def require_configured(self) -> tuple[ContentAddress, ContentAddress]:
        if (
            self.committer is None
            or self.event_plane is None
            or self.projection_resolver is None
            or self.validity_resolver is None
        ):
            raise ExecutionAdmissionError(
                "outcome_committer_unavailable",
                "install the accepted Spine event-plane appender before effects",
            )
        return self.committer, self.event_plane

    def current_frontier(
        self,
        *,
        queried_at: str | datetime,
    ) -> ContentAddress:
        self.require_configured()
        snapshot = self.catalog_snapshot
        if snapshot is None:
            raise ExecutionAdmissionError(
                "outcome_replay_catalog_unavailable",
                "read one immutable outcome catalog snapshot before frontier inspection",
            )
        query_time = _canonical_timestamp(queried_at)
        if query_time < snapshot.observed_at:
            raise ExecutionAdmissionError(
                "outcome_replay_time_rewound",
                "query at or after the catalog observation time",
                query_time,
            )
        return ContentAddress.model_validate(
            snapshot.checked_frontier.model_dump(mode="json")
        )

    def replay(
        self,
        lease: ExecutionLease,
        *,
        queried_at: str | datetime,
    ) -> OutcomeReplayResult | None:
        _require_exact_type(lease, ExecutionLease, "execution lease")
        self.require_configured()
        checked = require_admitted_execution_lease(lease)
        query_time = _canonical_timestamp(queried_at)
        snapshot = self.catalog_snapshot
        if snapshot is None:
            raise ExecutionAdmissionError(
                "outcome_replay_catalog_unavailable",
                "read one immutable outcome catalog snapshot before replay",
            )
        if query_time < snapshot.observed_at:
            raise ExecutionAdmissionError(
                "outcome_replay_time_rewound",
                "query at or after the catalog observation time",
                query_time,
            )
        projection = next(
            (
                item
                for item in snapshot.projections
                if item.outcome_receipt.idempotency_key == checked.idempotency_key
                and item.outcome_receipt.attempt_fence == checked.attempt_fence
            ),
            None,
        )
        if projection is None:
            return None
        resolved = projection.outcome_receipt
        if (
            resolved.execution_lease
            != ContentAddress(ref=checked.lease_ref, sha256=checked.lease_hash)
            or resolved.bound_execution_call
            != ContentAddress(
                ref=checked.bound_call.call_ref,
                sha256=checked.bound_call.call_hash,
            )
            or resolved.effect_manifest != checked.effect_manifest
            or resolved.executor_descriptor != checked.executor_descriptor
            or resolved.executor_registry_projection != checked.executor_registry_projection
            or resolved.executor != checked.executor
            or resolved.observation_contract != checked.observation_contract
            or resolved.completion_predicate != checked.completion_predicate
            or resolved.reconciliation_contract != checked.reconciliation_contract
            or resolved.invocation_id != checked.invocation_id
            or resolved.attempt_fence != checked.attempt_fence
            or resolved.idempotency_key != checked.idempotency_key
            or resolved.committer != self.committer
            or projection.event_plane != self.event_plane
            or projection.activation_generation_roots != checked.active_generation_roots
        ):
            raise ExecutionAdmissionError(
                "outcome_replay_binding_mismatch",
                "replay only the canonical receipt for the exact admitted attempt",
            )
        subject = ContentAddress(ref=projection.snapshot_ref, sha256=projection.snapshot_hash)
        subject_envelopes = tuple(
            item
            for item in snapshot.validity_envelopes
            if item.subject_projection == subject
            and item.checked_frontier == snapshot.checked_frontier
        )
        if not subject_envelopes:
            raise ExecutionAdmissionError(
                "outcome_projection_validity_missing",
                "install validity for the exact immutable outcome projection",
                projection.snapshot_ref,
            )
        candidates = tuple(
            item for item in subject_envelopes if item.checked_at <= query_time < item.stale_after
        )
        if len(candidates) != 1:
            raise ExecutionAdmissionError(
                "outcome_projection_validity_stale",
                "refresh the exact projection validity at the query frontier",
                projection.snapshot_ref,
            )
        envelope = candidates[0]
        expected_roots = outcome_projection_validity_roots(
            projection,
            checked_frontier=snapshot.checked_frontier,
        )
        observed_roots = tuple(item.root for item in envelope.root_dispositions)
        reasons: list[str] = []
        if envelope.resolver != self.validity_resolver:
            reasons.append("outcome_validity_resolver_mismatch")
        if envelope.event_plane != self.event_plane:
            reasons.append("outcome_validity_event_plane_mismatch")
        if envelope.source_frontier != projection.event_frontier:
            reasons.append("outcome_validity_source_frontier_mismatch")
        if envelope.checked_frontier != snapshot.checked_frontier:
            reasons.append("outcome_validity_checked_frontier_mismatch")
        if envelope.checked_at < projection.outcome_receipt.committed_at:
            reasons.append("outcome_validity_predates_outcome_commit")
        if observed_roots != expected_roots:
            reasons.append("outcome_validity_root_coverage_mismatch")
        if envelope.decision != "valid":
            reasons.extend(envelope.reason_codes or ("outcome_validity_held",))
        if reasons:
            raise ExecutionAdmissionError(
                "outcome_projection_not_current",
                "hold terminal use and refresh the exact Spine frontier validity",
                ",".join(sorted(set(reasons))),
            )
        body: dict[str, object] = {
            "schema": OUTCOME_REPLAY_RESULT_SCHEMA,
            "catalog_snapshot": self.catalog_address(),
            "projection": projection,
            "validity": envelope,
            "queried_at": query_time,
            "may_authorize": False,
        }
        digest = _self_hash(OUTCOME_REPLAY_RESULT_SCHEMA, body)
        return OutcomeReplayResult.model_validate(
            {
                **body,
                "result_ref": f"outcome-replay-result@sha256:{digest}",
                "result_hash": digest,
            }
        )

    def commit(
        self,
        lease: ExecutionLease,
        observation: EffectObservation,
        evaluation: CompletionEvaluation,
        readiness: OutcomePipelineReadinessEnvelope,
        *,
        completion_evaluator: CompletionEvaluator | None = None,
        readiness_resolver: OutcomePipelineReadinessResolver | None = None,
    ) -> OutcomeReceipt:
        """Gate-0A HOLD: outcome append requires activated universal dispatch."""

        del (
            lease,
            observation,
            evaluation,
            readiness,
            completion_evaluator,
            readiness_resolver,
        )
        raise ExecutionAdmissionError(
            "execution_composition_activation_unvalidated",
            "commit through a Gate-0B activated universal executor",
            None if self.committer is None else self.committer.ref,
        )


DEFAULT_OUTCOME_COMMITTER = OutcomeCommitter()


@dataclass(frozen=True)
class ExecutionCompositionPorts:
    """Data-only Gate-0A projections proven equal to one descriptor set."""

    descriptors: ExecutionCompositionPortDescriptors
    trust: ExecutionTrustResolver
    manifests: EffectManifestResolver
    currentness: ExecutionCurrentnessResolver
    executors: ExecutionExecutorRegistry
    completion: CompletionEvaluator
    readiness: OutcomePipelineReadinessResolver
    outcomes: OutcomeCommitter

    def __post_init__(self) -> None:
        for value, expected, label in (
            (
                self.descriptors,
                ExecutionCompositionPortDescriptors,
                "execution composition port descriptors",
            ),
            (self.trust, ExecutionTrustResolver, "execution trust resolver"),
            (self.manifests, EffectManifestResolver, "effect manifest resolver"),
            (
                self.currentness,
                ExecutionCurrentnessResolver,
                "execution currentness resolver",
            ),
            (self.executors, ExecutionExecutorRegistry, "execution executor registry"),
            (self.completion, CompletionEvaluator, "completion evaluator"),
            (
                self.readiness,
                OutcomePipelineReadinessResolver,
                "outcome readiness resolver",
            ),
            (self.outcomes, OutcomeCommitter, "outcome committer"),
        ):
            _require_exact_type(value, expected, label)
        descriptors = ExecutionCompositionPortDescriptors.model_validate(
            self.descriptors.model_dump(mode="json", by_alias=True)
        )
        object.__setattr__(self, "descriptors", descriptors)
        observed = {
            "trust_resolver": self.trust.resolver,
            "effect_manifest_resolver": self.manifests.resolver,
            "currentness_resolver": self.currentness.resolver,
            "executor_registry": self.executors.descriptor,
            "completion_evaluator": self.completion.evaluator,
            "readiness_resolver": self.readiness.resolver,
            "outcome_committer": self.outcomes.committer,
            "event_plane": self.outcomes.event_plane,
            "outcome_projection_resolver": self.outcomes.projection_resolver,
            "outcome_validity_resolver": self.outcomes.validity_resolver,
        }
        mismatches = tuple(
            name
            for name, address in observed.items()
            if address is None or address != getattr(descriptors, name)
        )
        if mismatches:
            raise ValueError(
                "composition projection ports differ from descriptors: "
                + ",".join(sorted(mismatches))
            )


def _seal_execution_trust_resolver(
    value: ExecutionTrustResolver | None,
) -> ExecutionTrustResolver:
    candidate = ExecutionTrustResolver() if value is None else value
    _require_exact_type(candidate, ExecutionTrustResolver, "execution trust resolver")
    return ExecutionTrustResolver(resolver=candidate.resolver, envelopes=candidate.envelopes)


def _seal_effect_manifest_resolver(
    value: EffectManifestResolver | None,
) -> EffectManifestResolver:
    candidate = EffectManifestResolver() if value is None else value
    _require_exact_type(candidate, EffectManifestResolver, "effect manifest resolver")
    return EffectManifestResolver(
        tuple(candidate._manifests.values()),
        resolver=candidate.resolver,
    )


def _seal_execution_currentness_resolver(
    value: ExecutionCurrentnessResolver | None,
) -> ExecutionCurrentnessResolver:
    candidate = ExecutionCurrentnessResolver() if value is None else value
    _require_exact_type(
        candidate,
        ExecutionCurrentnessResolver,
        "execution currentness resolver",
    )
    return ExecutionCurrentnessResolver(
        resolver=candidate.resolver,
        envelopes=candidate.envelopes,
    )


def _seal_execution_executor_registry(
    value: ExecutionExecutorRegistry,
) -> ExecutionExecutorRegistry:
    _require_exact_type(value, ExecutionExecutorRegistry, "execution executor registry")
    return ExecutionExecutorRegistry(
        projection=value._projection,
        bindings=tuple(value._bindings.values()),
        descriptor=value.descriptor,
    )


def _seal_completion_evaluator(value: CompletionEvaluator | None) -> CompletionEvaluator:
    candidate = CompletionEvaluator() if value is None else value
    _require_exact_type(candidate, CompletionEvaluator, "completion evaluator")
    return CompletionEvaluator(
        evaluator=candidate.evaluator,
        evaluations=candidate.evaluations,
    )


def _seal_outcome_readiness_resolver(
    value: OutcomePipelineReadinessResolver | None,
) -> OutcomePipelineReadinessResolver:
    candidate = OutcomePipelineReadinessResolver() if value is None else value
    _require_exact_type(
        candidate,
        OutcomePipelineReadinessResolver,
        "outcome readiness resolver",
    )
    return OutcomePipelineReadinessResolver(
        resolver=candidate.resolver,
        envelopes=candidate.envelopes,
    )


def _seal_outcome_committer(value: OutcomeCommitter | None) -> OutcomeCommitter:
    candidate = OutcomeCommitter() if value is None else value
    _require_exact_type(candidate, OutcomeCommitter, "outcome committer")
    return OutcomeCommitter(
        committer=candidate.committer,
        event_plane=candidate.event_plane,
        projection_resolver=candidate.projection_resolver,
        validity_resolver=candidate.validity_resolver,
        catalog_snapshot=candidate.catalog_snapshot,
    )


def _seal_execution_composition_ports(
    value: ExecutionCompositionPorts,
) -> ExecutionCompositionPorts:
    _require_exact_type(value, ExecutionCompositionPorts, "execution composition ports")
    return ExecutionCompositionPorts(
        descriptors=value.descriptors,
        trust=_seal_execution_trust_resolver(value.trust),
        manifests=_seal_effect_manifest_resolver(value.manifests),
        currentness=_seal_execution_currentness_resolver(value.currentness),
        executors=_seal_execution_executor_registry(value.executors),
        completion=_seal_completion_evaluator(value.completion),
        readiness=_seal_outcome_readiness_resolver(value.readiness),
        outcomes=_seal_outcome_committer(value.outcomes),
    )


def build_execution_trust_envelope(
    query: ExecutionTrustQuery,
    *,
    resolver: ContentAddress,
    decision: Literal["trusted", "hold"],
    event_frontier: ContentAddress,
    root_dispositions: Sequence[RootDisposition],
    checked_at: str | datetime,
    stale_after: str | datetime,
    reason_codes: Sequence[str] = (),
) -> ExecutionTrustEnvelope:
    checked_query = ExecutionTrustQuery.model_validate(query.model_dump(mode="json", by_alias=True))
    reasons = tuple(sorted(set(reason_codes)))
    body: dict[str, object] = {
        "schema": EXECUTION_TRUST_ENVELOPE_SCHEMA,
        "query": ContentAddress(
            ref=checked_query.query_ref,
            sha256=checked_query.query_hash,
        ),
        "resolver": resolver,
        "decision": decision,
        "event_frontier": event_frontier,
        "supersession_frontier_ref": checked_query.supersession_frontier_ref,
        "root_dispositions": tuple(
            sorted(root_dispositions, key=lambda item: _content_address_key(item.root))
        ),
        "reason_codes": reasons,
        "repair_refs": tuple(f"repair:{item}" for item in reasons),
        "checked_at": _canonical_timestamp(checked_at),
        "stale_after": _canonical_timestamp(stale_after),
        "may_authorize": False,
    }
    digest = _self_hash(EXECUTION_TRUST_ENVELOPE_SCHEMA, body)
    return ExecutionTrustEnvelope.model_validate(
        {
            **body,
            "envelope_ref": f"execution-trust-envelope@sha256:{digest}",
            "envelope_hash": digest,
        }
    )


def build_execution_currentness_envelope(
    query: ExecutionCurrentnessQuery,
    *,
    resolver: ContentAddress,
    decision: Literal["current", "hold"],
    event_frontier: ContentAddress,
    root_dispositions: Sequence[RootDisposition],
    idempotency_state: Literal[
        "available",
        "completed",
        "in_progress",
        "conflicted",
        "unknown",
    ],
    checked_at: str | datetime,
    stale_after: str | datetime,
    historical_support_dispositions: Sequence[HistoricalSupportDisposition] = (),
    reason_codes: Sequence[str] = (),
) -> ExecutionCurrentnessEnvelope:
    checked_query = ExecutionCurrentnessQuery.model_validate(
        query.model_dump(mode="json", by_alias=True)
    )
    reasons = tuple(sorted(set(reason_codes)))
    body: dict[str, object] = {
        "schema": EXECUTION_CURRENTNESS_ENVELOPE_SCHEMA,
        "query": ContentAddress(
            ref=checked_query.query_ref,
            sha256=checked_query.query_hash,
        ),
        "resolver": resolver,
        "decision": decision,
        "event_frontier": event_frontier,
        "supersession_frontier_ref": checked_query.supersession_frontier_ref,
        "root_dispositions": tuple(
            sorted(root_dispositions, key=lambda item: _content_address_key(item.root))
        ),
        "historical_support_dispositions": tuple(
            sorted(
                historical_support_dispositions,
                key=lambda item: _content_address_key(item.root),
            )
        ),
        "idempotency_state": idempotency_state,
        "reason_codes": reasons,
        "repair_refs": tuple(f"repair:{item}" for item in reasons),
        "checked_at": _canonical_timestamp(checked_at),
        "stale_after": _canonical_timestamp(stale_after),
        "may_authorize": False,
    }
    digest = _self_hash(EXECUTION_CURRENTNESS_ENVELOPE_SCHEMA, body)
    return ExecutionCurrentnessEnvelope.model_validate(
        {
            **body,
            "envelope_ref": f"execution-currentness-envelope@sha256:{digest}",
            "envelope_hash": digest,
        }
    )


def build_frontier_validity_envelope(
    *,
    subject_projection: ContentAddress,
    resolver: ContentAddress,
    event_plane: ContentAddress,
    source_frontier: ContentAddress,
    checked_frontier: ContentAddress,
    root_dispositions: Sequence[RootDisposition],
    decision: Literal["valid", "hold"],
    checked_at: str | datetime,
    stale_after: str | datetime,
    reason_codes: Sequence[str] = (),
) -> FrontierValidityEnvelope:
    """Build one query-time validity answer without changing its subject."""

    addresses = tuple(
        ContentAddress.model_validate(
            _require_exact_type(value, ContentAddress, label).model_dump(mode="json")
        )
        for value, label in (
            (subject_projection, "validity subject projection"),
            (resolver, "validity resolver"),
            (event_plane, "validity event plane"),
            (source_frontier, "validity source frontier"),
            (checked_frontier, "validity checked frontier"),
        )
    )
    checked_dispositions = tuple(
        RootDisposition.model_validate(
            _require_exact_type(
                item,
                RootDisposition,
                "frontier root disposition",
            ).model_dump(mode="json")
        )
        for item in root_dispositions
    )
    reasons = tuple(sorted(set(reason_codes)))
    body: dict[str, object] = {
        "schema": FRONTIER_VALIDITY_ENVELOPE_SCHEMA,
        "subject_projection": addresses[0],
        "resolver": addresses[1],
        "event_plane": addresses[2],
        "source_frontier": addresses[3],
        "checked_frontier": addresses[4],
        "root_dispositions": tuple(
            sorted(checked_dispositions, key=lambda item: _content_address_key(item.root))
        ),
        "decision": decision,
        "reason_codes": reasons,
        "repair_refs": tuple(f"repair:{item}" for item in reasons),
        "checked_at": _canonical_timestamp(checked_at),
        "stale_after": _canonical_timestamp(stale_after),
        "may_authorize": False,
    }
    digest = _self_hash(FRONTIER_VALIDITY_ENVELOPE_SCHEMA, body)
    return FrontierValidityEnvelope.model_validate(
        {
            **body,
            "envelope_ref": f"frontier-validity-envelope@sha256:{digest}",
            "envelope_hash": digest,
        }
    )


def build_completion_evaluation(
    query: CompletionEvaluationQuery,
    *,
    evaluator: ContentAddress,
    event_frontier: ContentAddress,
    decision: Literal["satisfied", "unsatisfied", "unknown"],
    effect_disposition: Literal[
        "applied",
        "not_applied",
        "partial",
        "not_applicable",
        "unknown",
    ],
    evaluated_at: str | datetime,
    reason_codes: Sequence[str] = (),
) -> CompletionEvaluation:
    checked_query = CompletionEvaluationQuery.model_validate(
        query.model_dump(mode="json", by_alias=True)
    )
    reasons = tuple(sorted(set(reason_codes)))
    body: dict[str, object] = {
        "schema": COMPLETION_EVALUATION_SCHEMA,
        "query": checked_query.model_dump(mode="json", by_alias=True),
        "evaluator": evaluator,
        "event_frontier": event_frontier,
        "decision": decision,
        "effect_disposition": effect_disposition,
        "evidence_refs": checked_query.evidence_refs,
        "reason_codes": reasons,
        "repair_refs": tuple(f"repair:{item}" for item in reasons),
        "evaluated_at": _canonical_timestamp(evaluated_at),
        "may_authorize": False,
    }
    digest = _self_hash(COMPLETION_EVALUATION_SCHEMA, body)
    return CompletionEvaluation.model_validate(
        {
            **body,
            "evaluation_ref": f"completion-evaluation@sha256:{digest}",
            "evaluation_hash": digest,
        }
    )


def build_outcome_pipeline_readiness_envelope(
    query: OutcomePipelineReadinessQuery,
    *,
    resolver: ContentAddress,
    decision: Literal["ready", "hold"],
    event_frontier: ContentAddress,
    checked_at: str | datetime,
    stale_after: str | datetime,
    reason_codes: Sequence[str] = (),
) -> OutcomePipelineReadinessEnvelope:
    checked_query = OutcomePipelineReadinessQuery.model_validate(
        query.model_dump(mode="json", by_alias=True)
    )
    reasons = tuple(sorted(set(reason_codes)))
    body: dict[str, object] = {
        "schema": OUTCOME_PIPELINE_READINESS_ENVELOPE_SCHEMA,
        "query": checked_query.model_dump(mode="json", by_alias=True),
        "resolver": resolver,
        "decision": decision,
        "event_frontier": event_frontier,
        "reason_codes": reasons,
        "repair_refs": tuple(f"repair:{item}" for item in reasons),
        "checked_at": _canonical_timestamp(checked_at),
        "stale_after": _canonical_timestamp(stale_after),
        "may_authorize": False,
    }
    digest = _self_hash(OUTCOME_PIPELINE_READINESS_ENVELOPE_SCHEMA, body)
    return OutcomePipelineReadinessEnvelope.model_validate(
        {
            **body,
            "envelope_ref": f"outcome-pipeline-readiness-envelope@sha256:{digest}",
            "envelope_hash": digest,
        }
    )


def build_event_append_receipt(
    event: OutcomeEvent,
    *,
    committer: ContentAddress,
    event_plane: ContentAddress,
    expected_frontier: ContentAddress,
    committed_frontier: ContentAddress,
    append_status: Literal["appended", "duplicate"],
    committed_at: str | datetime,
) -> EventAppendReceipt:
    checked_event = OutcomeEvent.model_validate(event.model_dump(mode="json", by_alias=True))
    body: dict[str, object] = {
        "schema": EVENT_APPEND_RECEIPT_SCHEMA,
        "outcome_key": checked_event.outcome_key,
        "outcome_event": ContentAddress(
            ref=checked_event.event_ref,
            sha256=checked_event.event_hash,
        ),
        "committer": committer,
        "event_plane": event_plane,
        "expected_frontier": expected_frontier,
        "committed_frontier": committed_frontier,
        "append_status": append_status,
        "committed_at": _canonical_timestamp(committed_at),
        "may_authorize": False,
    }
    digest = _self_hash(EVENT_APPEND_RECEIPT_SCHEMA, body)
    return EventAppendReceipt.model_validate(
        {
            **body,
            "receipt_ref": f"event-append-receipt@sha256:{digest}",
            "receipt_hash": digest,
        }
    )


def evaluate_completion(
    lease: ExecutionLease,
    observation: EffectObservation,
    *,
    queried_at: str | datetime,
    completion_evaluator: CompletionEvaluator | None = None,
) -> tuple[CompletionEvaluationQuery, CompletionEvaluation]:
    query = build_completion_evaluation_query(
        lease,
        observation,
        queried_at=queried_at,
    )
    return query, _seal_completion_evaluator(completion_evaluator).evaluate(query)


def require_outcome_pipeline_ready(
    lease: ExecutionLease,
    currentness_query: ExecutionCurrentnessQuery,
    currentness_envelope: ExecutionCurrentnessEnvelope,
    *,
    queried_at: str | datetime,
    completion_evaluator: CompletionEvaluator | None = None,
    outcome_committer: OutcomeCommitter | None = None,
    readiness_resolver: OutcomePipelineReadinessResolver | None = None,
) -> tuple[OutcomePipelineReadinessQuery, OutcomePipelineReadinessEnvelope]:
    configured_evaluator = _seal_completion_evaluator(completion_evaluator)
    configured_committer = _seal_outcome_committer(outcome_committer)
    configured_readiness = _seal_outcome_readiness_resolver(readiness_resolver)
    evaluator = configured_evaluator.require_configured()
    committer, event_plane = configured_committer.require_configured()
    expected_event_frontier = configured_committer.current_frontier(
        queried_at=queried_at,
    )
    query = build_outcome_pipeline_readiness_query(
        lease,
        currentness_query,
        currentness_envelope,
        evaluator=evaluator,
        committer=committer,
        event_plane=event_plane,
        expected_event_frontier=expected_event_frontier,
        queried_at=queried_at,
    )
    return query, configured_readiness.resolve(query)


def build_execution_lease_issuer_trust_query(
    admission: ExecutionAdmission,
    grant: ValidAuthorityGrant,
    claim_basis: ProspectiveClaimPublicationBasis | AppliedClaimOwnershipProof,
    target: ExecutionTargetEvidence,
    bound_call: BoundExecutionCall,
    effect_manifest: EffectManifest,
    executor_descriptor: ExecutorDescriptor,
    executor_registry_projection: ExecutorRegistryProjection,
    *,
    issuer_receipt: ContentAddress,
    queried_at: str | datetime,
) -> ExecutionTrustQuery:
    """Build the exact non-authorizing issuer question shared by mint and replay."""

    authority_trust_query = admission.authority_trust_query
    authority_trust_envelope = admission.authority_trust_envelope
    if authority_trust_query is None or authority_trust_envelope is None:
        raise ExecutionAdmissionError(
            "execution_lease_authority_trust_missing",
            "reissue admission with an exact current authority trust projection",
        )
    basis_address = (
        ContentAddress(ref=claim_basis.basis_ref, sha256=claim_basis.basis_hash)
        if isinstance(claim_basis, ProspectiveClaimPublicationBasis)
        else ContentAddress(ref=claim_basis.proof_ref, sha256=claim_basis.proof_hash)
    )
    claim_support_roots = (
        (claim_basis.claim_publication_intent,)
        if isinstance(claim_basis, ProspectiveClaimPublicationBasis)
        else ()
    )
    bound_call_address = ContentAddress(ref=bound_call.call_ref, sha256=bound_call.call_hash)
    return build_execution_trust_query(
        trust_class="execution_lease_issuer",
        subject_roots=(bound_call_address,),
        presented_receipt=issuer_receipt,
        required_roots=(
            issuer_receipt,
            ContentAddress(ref=admission.admission_ref, sha256=admission.admission_hash),
            ContentAddress(ref=grant.grant_ref, sha256=grant.grant_hash),
            basis_address,
            bound_call_address,
            ContentAddress(ref=target.target_ref, sha256=target.target_hash),
            ContentAddress(ref=effect_manifest.manifest_ref, sha256=effect_manifest.manifest_hash),
            ContentAddress(
                ref=executor_descriptor.descriptor_ref,
                sha256=executor_descriptor.descriptor_hash,
            ),
            ContentAddress(
                ref=executor_registry_projection.projection_ref,
                sha256=executor_registry_projection.projection_hash,
            ),
            executor_registry_projection.registry_source,
            executor_registry_projection.event_frontier,
            ContentAddress(
                ref=authority_trust_query.query_ref,
                sha256=authority_trust_query.query_hash,
            ),
            ContentAddress(
                ref=authority_trust_envelope.envelope_ref,
                sha256=authority_trust_envelope.envelope_hash,
            ),
            executor_descriptor.executor,
            executor_descriptor.adapter,
            executor_descriptor.harness,
            executor_descriptor.runtime_identity,
            *executor_descriptor.active_generation_roots,
            *claim_support_roots,
        ),
        supersession_frontier_ref=admission.supersession_frontier_ref,
        queried_at=queried_at,
    )


def mint_execution_lease(
    admission: ExecutionAdmission,
    intent: ActionIntent,
    grant: ValidAuthorityGrant,
    claim_basis: ProspectiveClaimPublicationBasis | AppliedClaimOwnershipProof,
    target: ExecutionTargetEvidence,
    bound_call: BoundExecutionCall,
    effect_manifest: EffectManifest,
    executor_descriptor: ExecutorDescriptor,
    executor_registry_projection: ExecutorRegistryProjection,
    *,
    issuer_receipt: ContentAddress,
    now: str | datetime,
    current_claim_position: CurrentClaimPosition | None = None,
    current_claim_resolution: AppliedClaimResolution | None = None,
    expires_at: str | datetime | None = None,
    supersedes_refs: Sequence[str] = (),
    trust_resolver: ExecutionTrustResolver | None = None,
) -> ExecutionLease:
    """Issue one lease for either prospective claim publication or applied ownership."""

    issued_at = _canonical_timestamp(now)
    try:
        admission = ExecutionAdmission.model_validate(
            admission.model_dump(mode="json", by_alias=True)
        )
        intent = ActionIntent.model_validate(intent.model_dump(mode="json", by_alias=True))
        grant = ValidAuthorityGrant.model_validate(grant.model_dump(mode="json", by_alias=True))
        if isinstance(claim_basis, ProspectiveClaimPublicationBasis):
            claim_basis = ProspectiveClaimPublicationBasis.model_validate(
                claim_basis.model_dump(mode="json", by_alias=True)
            )
        elif isinstance(claim_basis, AppliedClaimOwnershipProof):
            claim_basis = AppliedClaimOwnershipProof.model_validate(
                claim_basis.model_dump(mode="json", by_alias=True)
            )
        else:
            raise TypeError("unsupported claim basis")
        target = ExecutionTargetEvidence.model_validate(
            target.model_dump(mode="json", by_alias=True)
        )
        bound_call = BoundExecutionCall.model_validate(
            bound_call.model_dump(mode="json", by_alias=True)
        )
        effect_manifest = EffectManifest.model_validate(
            effect_manifest.model_dump(mode="json", by_alias=True)
        )
        executor_descriptor = ExecutorDescriptor.model_validate(
            executor_descriptor.model_dump(mode="json", by_alias=True)
        )
        executor_registry_projection = ExecutorRegistryProjection.model_validate(
            executor_registry_projection.model_dump(mode="json", by_alias=True)
        )
    except Exception as exc:
        raise ExecutionAdmissionError(
            "execution_lease_input_malformed",
            "restore the exact self-validating admission, intent, grant, claim, and target",
            type(exc).__name__,
        ) from exc
    if admission.decision != "admit" or not admission.lease_eligible:
        raise ExecutionAdmissionError(
            "execution_admission_not_lease_eligible",
            "repair and reissue an admitted decision before minting a lease",
            admission.admission_ref,
        )
    expected_admission = ContentAddress(
        ref=admission.admission_ref, sha256=admission.admission_hash
    )
    expected_grant = ContentAddress(ref=grant.grant_ref, sha256=grant.grant_hash)
    expected_target = ContentAddress(ref=target.target_ref, sha256=target.target_hash)
    expected_manifest = ContentAddress(
        ref=effect_manifest.manifest_ref,
        sha256=effect_manifest.manifest_hash,
    )
    expected_descriptor = ContentAddress(
        ref=executor_descriptor.descriptor_ref,
        sha256=executor_descriptor.descriptor_hash,
    )
    expected_registry = ContentAddress(
        ref=executor_registry_projection.projection_ref,
        sha256=executor_registry_projection.projection_hash,
    )
    if isinstance(claim_basis, ProspectiveClaimPublicationBasis):
        basis_address = ContentAddress(
            ref=claim_basis.basis_ref,
            sha256=claim_basis.basis_hash,
        )
        prospective = True
    else:
        basis_address = ContentAddress(
            ref=claim_basis.proof_ref,
            sha256=claim_basis.proof_hash,
        )
        prospective = False
    mismatches: list[str] = []
    if admission.intent != ContentAddress(ref=intent.intent_ref, sha256=intent.intent_hash):
        mismatches.append("intent")
    if admission.authority_grant != expected_grant:
        mismatches.append("authority_grant")
    if grant.acting_subject != intent.acting_subject:
        mismatches.append("authority_subject")
    if (
        admission.task_ref != claim_basis.task_ref
        or admission.lane != claim_basis.lane
        or admission.session_ref != claim_basis.session_ref
        or admission.authority_case != claim_basis.authority_case
    ):
        mismatches.append("claim_identity")
    if admission.claim_publication_intent != claim_basis.claim_publication_intent:
        mismatches.append("claim_publication_intent")
    if admission.dispatch_message_id != claim_basis.dispatch_message_id:
        mismatches.append("dispatch_root")
    if prospective:
        if (
            not isinstance(claim_basis, ProspectiveClaimPublicationBasis)
            or bound_call.claim_coordinates.state != "prospective"
            or intent.operation != "claim.publish"
            or intent.action_class != "claim_publication"
            or admission.idempotency_key != claim_basis.coord_dispatch_idempotency_key
        ):
            mismatches.append("prospective_claim_publication")
    else:
        assert isinstance(claim_basis, AppliedClaimOwnershipProof)
        _require_current_claim_position(
            claim_basis,
            admission.task_note,
            target,
            current_claim_position,
            claim_resolution=current_claim_resolution,
            queried_at=issued_at,
        )
        reused = tuple(
            label
            for label, current, publication in (
                (
                    "action_intent",
                    ContentAddress(ref=intent.intent_ref, sha256=intent.intent_hash),
                    claim_basis.publication_action_intent,
                ),
                (
                    "execution_admission",
                    expected_admission,
                    claim_basis.publication_execution_admission,
                ),
                (
                    "valid_authority_grant",
                    expected_grant,
                    claim_basis.publication_valid_authority_grant,
                ),
            )
            if current == publication
        )
        if reused:
            raise ExecutionAdmissionError(
                "publication_authority_reuse_prohibited",
                "mint a distinct current action intent, admission, and narrowed grant",
                ",".join(reused),
            )
        if bound_call.claim_coordinates.state != "applied" or intent.operation == "claim.publish":
            mismatches.append("applied_claim_ownership")
    if admission.execution_target != expected_target:
        mismatches.append("execution_target")
    if (
        admission.effect_manifest != expected_manifest
        or intent.effect_manifest != expected_manifest
        or target.effect_manifest != expected_manifest
        or bound_call.effect_manifest != expected_manifest
    ):
        mismatches.append("effect_manifest")
    if (
        target.executor_descriptor != expected_descriptor
        or bound_call.executor_descriptor != expected_descriptor
        or target.executor_registry_projection != expected_registry
        or bound_call.executor_registry_projection != expected_registry
        or expected_descriptor not in executor_registry_projection.descriptors
        or target.executor != executor_descriptor.executor
        or target.adapter != executor_descriptor.adapter
        or target.harness != executor_descriptor.harness
        or target.runtime_identity != executor_descriptor.runtime_identity
        or target.active_generation_roots != executor_descriptor.active_generation_roots
    ):
        mismatches.append("executor_registry")
    if admission.selected_descriptor_leaf != target.selected_descriptor_leaf:
        mismatches.append("target_harness_leaf")
    if grant.valid_until <= issued_at or admission.valid_until <= issued_at:
        mismatches.append("admission_or_grant_stale")
    evidence_floor = max(admission.issued_at, grant.issued_at, target.checked_at)
    if isinstance(claim_basis, AppliedClaimOwnershipProof):
        evidence_floor = max(
            evidence_floor,
            claim_basis.publication_checked_at,
            claim_basis.publication_outcome_committed_at,
        )
    if issued_at < evidence_floor:
        mismatches.append("lease_backdated_before_evidence")
    if (
        bound_call.admission != expected_admission
        or bound_call.claim_basis != basis_address
        or bound_call.action_intent
        != ContentAddress(ref=intent.intent_ref, sha256=intent.intent_hash)
        or bound_call.authority_grant != expected_grant
        or bound_call.execution_target != expected_target
        or bound_call.selected_descriptor_leaf != admission.selected_descriptor_leaf
    ):
        mismatches.append("bound_execution_call")
    if mismatches:
        raise ExecutionAdmissionError(
            "execution_lease_input_mismatch",
            "rebuild the lease from one exact admitted action and typed claim basis",
            ",".join(mismatches),
        )

    issuer_trust_query = build_execution_lease_issuer_trust_query(
        admission,
        grant,
        claim_basis,
        target,
        bound_call,
        effect_manifest,
        executor_descriptor,
        executor_registry_projection,
        issuer_receipt=issuer_receipt,
        queried_at=issued_at,
    )
    issuer_trust_envelope = _seal_execution_trust_resolver(trust_resolver).require_trusted(
        issuer_trust_query
    )

    requested_expiry = (
        _canonical_timestamp(expires_at) if expires_at is not None else admission.valid_until
    )
    effective_expiry = min(
        requested_expiry,
        admission.valid_until,
        grant.valid_until,
        target.stale_after,
        executor_registry_projection.stale_after,
        issuer_trust_envelope.stale_after,
    )
    if effective_expiry <= issued_at:
        raise ExecutionAdmissionError(
            "execution_lease_empty_validity_interval",
            "refresh admission, authority, and target evidence before issuing a lease",
        )
    body: dict[str, object] = {
        "schema": EXECUTION_LEASE_SCHEMA,
        "admission": expected_admission,
        "authority_grant": expected_grant,
        "claim_basis": claim_basis.model_dump(mode="json", by_alias=True),
        "claim_coordinates": bound_call.claim_coordinates.model_dump(
            mode="json",
            by_alias=True,
        ),
        "bound_call": bound_call.model_dump(mode="json", by_alias=True),
        "task_ref": claim_basis.task_ref,
        "lane": claim_basis.lane,
        "session_ref": claim_basis.session_ref,
        "claim_epoch": claim_basis.claim_epoch,
        "capability_role": intent.capability_role,
        "selected_descriptor_leaf": admission.selected_descriptor_leaf,
        "execution_target": expected_target,
        "runtime_identity": target.runtime_identity,
        "active_generation_roots": target.active_generation_roots,
        "invocation_id": bound_call.invocation_id,
        "idempotency_key": admission.idempotency_key,
        "attempt_fence": bound_call.attempt_fence,
        "effect_manifest": expected_manifest,
        "executor_descriptor": expected_descriptor,
        "executor_registry_projection": expected_registry,
        "executor": executor_descriptor.executor,
        "issuer_receipt": issuer_receipt,
        "issuer_trust_query": issuer_trust_query.model_dump(mode="json", by_alias=True),
        "issuer_trust_envelope": issuer_trust_envelope.model_dump(
            mode="json",
            by_alias=True,
        ),
        "observation_contract": effect_manifest.observation_contract,
        "completion_predicate": effect_manifest.completion_predicate,
        "idempotence_class": effect_manifest.idempotence_class,
        "reconciliation_contract": effect_manifest.reconciliation_contract,
        "compensation": effect_manifest.compensation,
        "issued_at": issued_at,
        "not_before": issued_at,
        "expires_at": effective_expiry,
        "supersession_frontier_ref": admission.supersession_frontier_ref,
        "supersedes_refs": tuple(sorted(set(supersedes_refs))),
        "authorizes_machine_adapter": True,
        "authorizes_operator": False,
        "may_mint_sovereign_act": False,
    }
    digest = _self_hash(EXECUTION_LEASE_SCHEMA, body)
    return ExecutionLease.model_validate(
        {**body, "lease_ref": f"execution-lease@sha256:{digest}", "lease_hash": digest}
    )


def build_execution_currentness_query(
    lease: ExecutionLease,
    admission: ExecutionAdmission,
    intent: ActionIntent,
    grant: ValidAuthorityGrant,
    claim_basis: ProspectiveClaimPublicationBasis | AppliedClaimOwnershipProof,
    frame: ContextFrame,
    trace: EpistemicImpingementTrace,
    target: ExecutionTargetEvidence,
    route_decision: RouteDecision,
    effect_manifest: EffectManifest,
    executor_descriptor: ExecutorDescriptor,
    executor_registry_projection: ExecutorRegistryProjection,
    authority_trust_query: ExecutionTrustQuery,
    authority_trust_envelope: ExecutionTrustEnvelope,
    issuer_trust_query: ExecutionTrustQuery,
    issuer_trust_envelope: ExecutionTrustEnvelope,
    *,
    queried_at: str | datetime,
    current_claim_position: CurrentClaimPosition | None = None,
    current_claim_resolution: AppliedClaimResolution | None = None,
) -> ExecutionCurrentnessQuery:
    checked = require_admitted_execution_lease(lease)
    basis_address = (
        ContentAddress(ref=claim_basis.basis_ref, sha256=claim_basis.basis_hash)
        if isinstance(claim_basis, ProspectiveClaimPublicationBasis)
        else ContentAddress(ref=claim_basis.proof_ref, sha256=claim_basis.proof_hash)
    )
    live_claim: AppliedClaimBasisResolution | None = None
    if isinstance(claim_basis, AppliedClaimOwnershipProof):
        live_claim = _require_current_claim_position(
            claim_basis,
            admission.task_note,
            target,
            current_claim_position,
            claim_resolution=current_claim_resolution,
            queried_at=queried_at,
        )
    route_address = content_address(route_decision.decision_id, route_decision)
    authority_query_address = ContentAddress(
        ref=authority_trust_query.query_ref,
        sha256=authority_trust_query.query_hash,
    )
    authority_envelope_address = ContentAddress(
        ref=authority_trust_envelope.envelope_ref,
        sha256=authority_trust_envelope.envelope_hash,
    )
    issuer_query_address = ContentAddress(
        ref=issuer_trust_query.query_ref,
        sha256=issuer_trust_query.query_hash,
    )
    issuer_envelope_address = ContentAddress(
        ref=issuer_trust_envelope.envelope_ref,
        sha256=issuer_trust_envelope.envelope_hash,
    )
    roots = [
        ContentAddress(ref=checked.lease_ref, sha256=checked.lease_hash),
        ContentAddress(
            ref=checked.bound_call.call_ref,
            sha256=checked.bound_call.call_hash,
        ),
        ContentAddress(ref=admission.admission_ref, sha256=admission.admission_hash),
        ContentAddress(ref=intent.intent_ref, sha256=intent.intent_hash),
        intent.protected_action_request,
        ContentAddress(ref=grant.grant_ref, sha256=grant.grant_hash),
        ContentAddress(ref=frame.frame_ref, sha256=frame.frame_hash),
        ContentAddress(
            ref=frame.position.position_ref,
            sha256=frame.position.position_hash,
        ),
        ContentAddress(ref=trace.trace_ref, sha256=trace.trace_hash),
        ContentAddress(ref=target.target_ref, sha256=target.target_hash),
        route_address,
        ContentAddress(
            ref=effect_manifest.manifest_ref,
            sha256=effect_manifest.manifest_hash,
        ),
        ContentAddress(
            ref=executor_descriptor.descriptor_ref,
            sha256=executor_descriptor.descriptor_hash,
        ),
        ContentAddress(
            ref=executor_registry_projection.projection_ref,
            sha256=executor_registry_projection.projection_hash,
        ),
        executor_registry_projection.registry_source,
        executor_registry_projection.event_frontier,
        grant.authority_source,
        grant.authenticated_receipt,
        grant.authority_issuer,
        grant.acting_subject,
        ContentAddress(
            ref=grant.authority_trust_query.query_ref,
            sha256=grant.authority_trust_query.query_hash,
        ),
        ContentAddress(
            ref=grant.authority_trust_envelope.envelope_ref,
            sha256=grant.authority_trust_envelope.envelope_hash,
        ),
        ContentAddress(
            ref=checked.issuer_trust_query.query_ref,
            sha256=checked.issuer_trust_query.query_hash,
        ),
        ContentAddress(
            ref=checked.issuer_trust_envelope.envelope_ref,
            sha256=checked.issuer_trust_envelope.envelope_hash,
        ),
        authority_query_address,
        authority_envelope_address,
        issuer_query_address,
        issuer_envelope_address,
        grant.authority_trust_envelope.event_frontier,
        checked.issuer_trust_envelope.event_frontier,
        authority_trust_envelope.event_frontier,
        issuer_trust_envelope.event_frontier,
        checked.issuer_receipt,
        checked.observation_contract,
        checked.completion_predicate,
        checked.executor,
        checked.bound_call.adapter,
        checked.bound_call.harness,
        checked.runtime_identity,
        target.host_scoped_claim,
        target.environment_observation,
        admission.task_note,
        admission.parent_spec,
        admission.decomposition,
        admission.canon_bundle,
        admission.canon_image,
        admission.fact_frontier,
        admission.context_selection,
        admission.audience_seal_receipt,
        *checked.active_generation_roots,
        *effect_manifest.effect_targets,
    ]
    if isinstance(claim_basis, AppliedClaimOwnershipProof):
        assert current_claim_position is not None
        assert live_claim is not None
        replay = live_claim.outcome_replay_result
        roots.extend(
            (
                ContentAddress(ref=replay.result_ref, sha256=replay.result_hash),
                replay.catalog_snapshot,
                ContentAddress(
                    ref=replay.validity.envelope_ref,
                    sha256=replay.validity.envelope_hash,
                ),
                replay.validity.checked_frontier,
            )
        )
        roots.extend(
            ContentAddress(
                ref=f"file:{item.path}@sha256:{item.content_sha256}",
                sha256=item.content_sha256,
            )
            for item in current_claim_position.lease_files
        )
    historical_support_roots: tuple[ContentAddress, ...]
    if isinstance(claim_basis, ProspectiveClaimPublicationBasis):
        roots.extend((basis_address, claim_basis.claim_publication_intent))
        historical_support_roots = ()
    else:
        historical_support_roots = tuple(
            sorted(
                {
                    _content_address_key(item): item
                    for item in (
                        basis_address,
                        claim_basis.claim_publication_intent,
                        claim_basis.receipt,
                        claim_basis.manifest,
                        claim_basis.admission_consumption,
                        claim_basis.publication_action_intent,
                        claim_basis.publication_execution_admission,
                        claim_basis.publication_valid_authority_grant,
                        claim_basis.publication_authority_evidence,
                        claim_basis.publication_authenticated_authority_receipt,
                        claim_basis.publication_context_position,
                        claim_basis.publication_execution_lease,
                        claim_basis.publication_bound_execution_call,
                        claim_basis.publication_outcome_projection,
                        claim_basis.publication_outcome_receipt,
                        ContentAddress(
                            ref=claim_basis.publication_completion_evidence.evidence_ref,
                            sha256=claim_basis.publication_completion_evidence.evidence_hash,
                        ),
                    )
                }.values(),
                key=_content_address_key,
            )
        )
    roots.extend(
        item
        for item in (
            admission.demand_vector,
            admission.demand_derivation_receipt,
            admission.supply_vector,
            admission.supply_refresh_receipt,
            admission.dependency_closure,
            admission.quota_reservation,
            admission.authority_grant,
            admission.authority_trust_query
            and ContentAddress(
                ref=admission.authority_trust_query.query_ref,
                sha256=admission.authority_trust_query.query_hash,
            ),
            admission.authority_trust_envelope
            and ContentAddress(
                ref=admission.authority_trust_envelope.envelope_ref,
                sha256=admission.authority_trust_envelope.envelope_hash,
            ),
        )
        if item is not None
    )
    if checked.reconciliation_contract is not None:
        roots.append(checked.reconciliation_contract)
    if checked.compensation is not None:
        roots.append(checked.compensation)
    required_roots = tuple(
        sorted(
            {_content_address_key(item): item for item in roots}.values(),
            key=_content_address_key,
        )
    )
    current_root_keys = {_content_address_key(item) for item in required_roots}
    historical_support_roots = tuple(
        item
        for item in historical_support_roots
        if _content_address_key(item) not in current_root_keys
    )
    body: dict[str, object] = {
        "schema": EXECUTION_CURRENTNESS_QUERY_SCHEMA,
        "task_ref": checked.task_ref,
        "lane": checked.lane,
        "session_ref": checked.session_ref,
        "claim_epoch": checked.claim_epoch,
        "invocation_id": checked.invocation_id,
        "attempt_fence": checked.attempt_fence,
        "idempotency_key": checked.idempotency_key,
        "supersession_frontier_ref": checked.supersession_frontier_ref,
        "execution_lease": ContentAddress(
            ref=checked.lease_ref,
            sha256=checked.lease_hash,
        ),
        "bound_execution_call": ContentAddress(
            ref=checked.bound_call.call_ref,
            sha256=checked.bound_call.call_hash,
        ),
        "effect_manifest": checked.effect_manifest,
        "executor_descriptor": checked.executor_descriptor,
        "executor_registry_projection": checked.executor_registry_projection,
        "authority_trust_query": authority_query_address,
        "authority_trust_envelope": authority_envelope_address,
        "issuer_trust_query": issuer_query_address,
        "issuer_trust_envelope": issuer_envelope_address,
        "required_roots": required_roots,
        "historical_support_roots": historical_support_roots,
        "queried_at": _canonical_timestamp(queried_at),
        "may_authorize": False,
    }
    digest = _self_hash(EXECUTION_CURRENTNESS_QUERY_SCHEMA, body)
    return ExecutionCurrentnessQuery.model_validate(
        {
            **body,
            "query_ref": f"execution-currentness-query@sha256:{digest}",
            "query_hash": digest,
        }
    )


def require_current_execution_lease(
    lease: ExecutionLease,
    admission: ExecutionAdmission,
    intent: ActionIntent,
    grant: ValidAuthorityGrant,
    claim_basis: ProspectiveClaimPublicationBasis | AppliedClaimOwnershipProof,
    current_task_note: ContentAddress,
    frame: ContextFrame,
    trace: EpistemicImpingementTrace,
    target: ExecutionTargetEvidence,
    route_decision: RouteDecision,
    effect_manifest: EffectManifest,
    executor_descriptor: ExecutorDescriptor,
    executor_registry_projection: ExecutorRegistryProjection,
    *,
    trust_resolver: ExecutionTrustResolver | None = None,
    manifest_resolver: EffectManifestResolver | None = None,
    currentness_resolver: ExecutionCurrentnessResolver | None = None,
    current_claim_position: CurrentClaimPosition | None = None,
    current_claim_resolution: AppliedClaimResolution | None = None,
    queried_at: str | datetime,
) -> tuple[ExecutionLease, ExecutionCurrentnessQuery, ExecutionCurrentnessEnvelope]:
    """Revalidate every mutable/current root immediately before adapter invocation."""

    checked = require_admitted_execution_lease(lease)
    try:
        admission = ExecutionAdmission.model_validate(
            admission.model_dump(mode="json", by_alias=True)
        )
        intent = ActionIntent.model_validate(intent.model_dump(mode="json", by_alias=True))
        grant = ValidAuthorityGrant.model_validate(grant.model_dump(mode="json", by_alias=True))
        if isinstance(claim_basis, ProspectiveClaimPublicationBasis):
            claim_basis = ProspectiveClaimPublicationBasis.model_validate(
                claim_basis.model_dump(mode="json", by_alias=True)
            )
        elif isinstance(claim_basis, AppliedClaimOwnershipProof):
            claim_basis = AppliedClaimOwnershipProof.model_validate(
                claim_basis.model_dump(mode="json", by_alias=True)
            )
        else:
            raise TypeError("unsupported claim basis")
        current_task_note = ContentAddress.model_validate(current_task_note.model_dump(mode="json"))
        frame = ContextFrame.model_validate(frame.model_dump(mode="json", by_alias=True))
        trace = EpistemicImpingementTrace.model_validate(
            trace.model_dump(mode="json", by_alias=True)
        )
        target = ExecutionTargetEvidence.model_validate(
            target.model_dump(mode="json", by_alias=True)
        )
        route_decision = RouteDecision.model_validate(route_decision.model_dump(mode="json"))
        effect_manifest = EffectManifest.model_validate(
            effect_manifest.model_dump(mode="json", by_alias=True)
        )
        executor_descriptor = ExecutorDescriptor.model_validate(
            executor_descriptor.model_dump(mode="json", by_alias=True)
        )
        executor_registry_projection = ExecutorRegistryProjection.model_validate(
            executor_registry_projection.model_dump(mode="json", by_alias=True)
        )
    except Exception as exc:
        raise ExecutionAdmissionError(
            "execution_lease_current_input_malformed",
            "restore the exact self-validating current admission inputs",
            type(exc).__name__,
        ) from exc
    checked_at = _canonical_timestamp(queried_at)
    if isinstance(claim_basis, AppliedClaimOwnershipProof):
        _require_current_claim_position(
            claim_basis,
            current_task_note,
            target,
            current_claim_position,
            claim_resolution=current_claim_resolution,
            queried_at=checked_at,
        )
    authority_trust_query = build_execution_trust_query(
        trust_class=grant.authority_trust_query.trust_class,
        subject_roots=grant.authority_trust_query.subject_roots,
        presented_receipt=grant.authority_trust_query.presented_receipt,
        required_roots=grant.authority_trust_query.required_roots,
        supersession_frontier_ref=grant.supersession_frontier_ref,
        queried_at=checked_at,
    )
    configured_trust = _seal_execution_trust_resolver(trust_resolver)
    authority_trust_envelope = configured_trust.require_trusted(authority_trust_query)
    issuer_trust_query = build_execution_trust_query(
        trust_class=checked.issuer_trust_query.trust_class,
        subject_roots=checked.issuer_trust_query.subject_roots,
        presented_receipt=checked.issuer_trust_query.presented_receipt,
        required_roots=checked.issuer_trust_query.required_roots,
        supersession_frontier_ref=checked.supersession_frontier_ref,
        queried_at=checked_at,
    )
    issuer_trust_envelope = configured_trust.require_trusted(issuer_trust_query)
    reasons: list[str] = []
    if not checked.not_before <= checked_at < checked.expires_at:
        reasons.append("execution_lease_stale")
    if checked.admission != ContentAddress(
        ref=admission.admission_ref, sha256=admission.admission_hash
    ):
        reasons.append("execution_lease_admission_mismatch")
    if admission.decision != "admit" or not admission.lease_eligible:
        reasons.append("execution_admission_not_current")
    if checked.authority_grant != ContentAddress(ref=grant.grant_ref, sha256=grant.grant_hash):
        reasons.append("execution_lease_authority_mismatch")
    if checked.claim_basis != claim_basis:
        reasons.append("execution_lease_claim_basis_mismatch")
    if (
        checked.task_ref != claim_basis.task_ref
        or checked.lane != claim_basis.lane
        or checked.session_ref != claim_basis.session_ref
        or checked.claim_epoch != claim_basis.claim_epoch
    ):
        reasons.append("execution_lease_claim_identity_mismatch")
    if (
        admission.task_note != current_task_note
        or checked.bound_call.task_note != current_task_note
    ):
        reasons.append("execution_lease_task_note_mismatch")
    if admission.intent != ContentAddress(ref=intent.intent_ref, sha256=intent.intent_hash):
        reasons.append("execution_lease_intent_mismatch")
    if (
        checked.effect_manifest != intent.effect_manifest
        or checked.capability_role != intent.capability_role
        or checked.bound_call.acting_subject != intent.acting_subject
        or checked.bound_call.requested_effect_targets != intent.requested_effect_targets
    ):
        reasons.append("execution_lease_effect_or_role_mismatch")
    manifest_address = ContentAddress(
        ref=effect_manifest.manifest_ref,
        sha256=effect_manifest.manifest_hash,
    )
    descriptor_address = ContentAddress(
        ref=executor_descriptor.descriptor_ref,
        sha256=executor_descriptor.descriptor_hash,
    )
    registry_address = ContentAddress(
        ref=executor_registry_projection.projection_ref,
        sha256=executor_registry_projection.projection_hash,
    )
    if (
        checked.effect_manifest != manifest_address
        or checked.observation_contract != effect_manifest.observation_contract
        or checked.completion_predicate != effect_manifest.completion_predicate
        or checked.idempotence_class != effect_manifest.idempotence_class
        or checked.reconciliation_contract != effect_manifest.reconciliation_contract
        or checked.compensation != effect_manifest.compensation
        or effect_manifest.effect_targets != intent.requested_effect_targets
    ):
        reasons.append("execution_lease_manifest_mismatch")
    if (
        checked.executor_descriptor != descriptor_address
        or checked.executor_registry_projection != registry_address
        or descriptor_address not in executor_registry_projection.descriptors
        or checked.executor != executor_descriptor.executor
        or not executor_registry_projection.checked_at
        <= checked_at
        < executor_registry_projection.stale_after
    ):
        reasons.append("execution_lease_executor_registry_mismatch")
    if (
        admission.claim_publication_intent != claim_basis.claim_publication_intent
        or frame.position.claim_ref != claim_basis.claim_publication_intent.ref
    ):
        reasons.append("execution_lease_claim_position_mismatch")
    if (
        frame.frame_ref != admission.context_frame.ref
        or frame.frame_hash != admission.context_frame.sha256
        or frame.position.position_ref != admission.context_position.ref
        or frame.position.position_hash != admission.context_position.sha256
        or intent.position_ref != frame.position.position_ref
    ):
        reasons.append("execution_lease_context_position_mismatch")
    if not frame.checked_at <= checked_at < frame.stale_after:
        reasons.append("execution_lease_context_stale")
    try:
        require_current_epistemic_trace(trace, frame.position, now=checked_at)
    except EpistemicImpingementError as exc:
        reasons.append(exc.reason_code)
    if checked.execution_target != ContentAddress(ref=target.target_ref, sha256=target.target_hash):
        reasons.append("execution_lease_target_mismatch")
    if admission.route_decision != content_address(route_decision.decision_id, route_decision):
        reasons.append("execution_lease_route_decision_mismatch")
    observed_descriptor_leaf = (
        route_decision.selected_descriptor_leaf or f"{route_decision.route_id}#base"
    )
    if (
        checked.runtime_identity != target.runtime_identity
        or checked.active_generation_roots != target.active_generation_roots
        or target.execution_host != intent.execution_host
        or (
            route_decision.local_execution_target is not None
            and route_decision.local_execution_target != target.execution_host
        )
        or target.selected_descriptor_leaf != checked.selected_descriptor_leaf
        or not target.checked_at <= checked_at < target.stale_after
    ):
        reasons.append("execution_lease_generation_or_host_mismatch")
    if checked.selected_descriptor_leaf != observed_descriptor_leaf:
        reasons.append("execution_lease_descriptor_leaf_mismatch")
    if reasons:
        raise ExecutionAdmissionError(
            "execution_lease_not_current",
            "hold effects and reissue from the exact current Gate-0 position",
            ",".join(sorted(set(reasons))),
        )
    resolved_manifest = _seal_effect_manifest_resolver(manifest_resolver).resolve(
        checked.effect_manifest
    )
    if resolved_manifest != effect_manifest:
        raise ExecutionAdmissionError(
            "execution_manifest_resolution_mismatch",
            "resolve the lease manifest from the exact installed immutable manifest set",
        )
    query = build_execution_currentness_query(
        checked,
        admission,
        intent,
        grant,
        claim_basis,
        frame,
        trace,
        target,
        route_decision,
        effect_manifest,
        executor_descriptor,
        executor_registry_projection,
        authority_trust_query,
        authority_trust_envelope,
        issuer_trust_query,
        issuer_trust_envelope,
        queried_at=checked_at,
        current_claim_position=current_claim_position,
        current_claim_resolution=current_claim_resolution,
    )
    envelope = _seal_execution_currentness_resolver(currentness_resolver).resolve(query)
    return checked, query, envelope


@dataclass(frozen=True)
class ProspectiveClaimResolution:
    """Exact pre-publication basis and task-note preimage for structural evaluation."""

    vault_root: Path
    cache_dir: Path
    transaction_root: Path
    receipt_root: Path
    lock_root: Path
    carrier: ProspectiveClaimPublicationCarrier
    current_task_note: ContentAddress

    def __post_init__(self) -> None:
        for field_name in (
            "vault_root",
            "cache_dir",
            "transaction_root",
            "receipt_root",
            "lock_root",
        ):
            _require_exact_type(
                getattr(self, field_name),
                type(Path()),
                f"prospective claim {field_name}",
            )
            object.__setattr__(
                self,
                field_name,
                Path(getattr(self, field_name)).expanduser().resolve(strict=False),
            )
        _require_exact_type(
            self.carrier,
            ProspectiveClaimPublicationCarrier,
            "prospective claim carrier",
        )
        _require_exact_type(
            self.current_task_note,
            ContentAddress,
            "prospective current task note",
        )
        object.__setattr__(
            self,
            "carrier",
            ProspectiveClaimPublicationCarrier.model_validate(
                self.carrier.model_dump(mode="json", by_alias=True)
            ),
        )
        object.__setattr__(
            self,
            "current_task_note",
            ContentAddress.model_validate(self.current_task_note.model_dump(mode="json")),
        )
        if self.current_task_note.sha256 != self.carrier.basis.task_note_before_sha256:
            raise ValueError("prospective resolution differs from its task-note preimage")

    def resolve_basis(self) -> tuple[ProspectiveClaimPublicationBasis, ContentAddress]:
        return self.carrier.basis, self.current_task_note


@dataclass(frozen=True)
class AppliedClaimBasisResolution:
    """Ephemeral live claim position and the moving replay that justified it."""

    ownership: AppliedClaimOwnershipProof
    current_task_note: ContentAddress
    current_position: CurrentClaimPosition
    outcome_replay_result: OutcomeReplayResult

    def __post_init__(self) -> None:
        for field_name, expected, label in (
            ("ownership", AppliedClaimOwnershipProof, "applied claim ownership"),
            ("current_task_note", ContentAddress, "current task note"),
            ("current_position", CurrentClaimPosition, "current claim position"),
            ("outcome_replay_result", OutcomeReplayResult, "outcome replay result"),
        ):
            value = _require_exact_type(getattr(self, field_name), expected, label)
            object.__setattr__(
                self,
                field_name,
                expected.model_validate(value.model_dump(mode="json", by_alias=True)),
            )


@dataclass(frozen=True)
class AppliedClaimResolution:
    """Exact live resolution coordinates for one applied claim publication."""

    vault_root: Path
    cache_dir: Path
    role: str
    session_id: str
    task_id: str
    transaction_root: Path | None = None
    receipt_root: Path | None = None
    lock_root: Path | None = None
    outcome_committer: OutcomeCommitter | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        for field_name in (
            "vault_root",
            "cache_dir",
            "transaction_root",
            "receipt_root",
            "lock_root",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _require_exact_type(value, type(Path()), f"applied claim {field_name}")
                object.__setattr__(
                    self,
                    field_name,
                    Path(value).expanduser().resolve(strict=False),
                )
        for value in (self.role, self.session_id, self.task_id):
            _nonblank(value)
        if self.outcome_committer is not None:
            object.__setattr__(
                self,
                "outcome_committer",
                _seal_outcome_committer(self.outcome_committer),
            )

    def resolve(self) -> AppliedClaimPublicationSnapshot:
        from shared.sdlc_claim import resolve_applied_claim_publication

        return resolve_applied_claim_publication(
            vault_root=self.vault_root,
            cache_dir=self.cache_dir,
            role=self.role,
            session_id=self.session_id,
            task_id=self.task_id,
            transaction_root=self.transaction_root,
            receipt_root=self.receipt_root,
            lock_root=self.lock_root,
        )

    def resolve_basis(
        self,
        *,
        queried_at: str | datetime,
    ) -> AppliedClaimBasisResolution:
        from shared.sdlc_claim import resolve_claim_publication_admission_provenance

        snapshot = self.resolve()
        provenance = resolve_claim_publication_admission_provenance(snapshot)
        publication_lease = provenance.execution_lease
        if publication_lease is None:
            raise ExecutionAdmissionError(
                "claim_publication_execution_lease_missing",
                "restore the receipt-bound publication execution lease",
                snapshot.receipt.publication_id,
            )
        if self.outcome_committer is None:
            raise ExecutionAdmissionError(
                "claim_publication_outcome_resolver_unavailable",
                "install the composition-owned immutable outcome projection catalog",
                snapshot.receipt.publication_id,
            )
        ownership, replay = _applied_claim_ownership_resolution(
            snapshot,
            outcome_committer=self.outcome_committer,
            queried_at=queried_at,
        )
        current_task_note = ContentAddress(
            ref=str(_normalized_path(snapshot.current_task.path)),
            sha256=snapshot.current_task.sha256,
        )
        position = build_current_claim_position(
            snapshot,
            ownership,
            outcome_replay=replay,
        )
        return AppliedClaimBasisResolution(
            ownership=ownership,
            current_task_note=current_task_note,
            current_position=position,
            outcome_replay_result=replay,
        )


AdmittedClaimResolution = AppliedClaimResolution


@dataclass(frozen=True)
class ExecutionInvocationContext:
    """Ephemeral current-state inputs consumed at the adapter chokepoint."""

    lease: ExecutionLease
    admission: ExecutionAdmission
    intent: ActionIntent
    grant: ValidAuthorityGrant
    claim_resolution: ProspectiveClaimResolution | AppliedClaimResolution
    frame: ContextFrame
    trace: EpistemicImpingementTrace
    target: ExecutionTargetEvidence
    route_decision: RouteDecision
    effect_manifest: EffectManifest
    executor_descriptor: ExecutorDescriptor
    executor_registry_projection: ExecutorRegistryProjection
    protected_request: ProtectedActionRequest
    aperture_decision: ProtectedApertureDecision
    claim_coordinates: ProtectedClaimCoordinates
    ports: ExecutionCompositionPorts | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self.ports is not None:
            object.__setattr__(
                self,
                "ports",
                _seal_execution_composition_ports(self.ports),
            )

    def require_composition_ports(self) -> ExecutionCompositionPorts:
        if self.ports is None:
            raise ExecutionAdmissionError(
                "execution_composition_ports_unavailable",
                "resolve the invocation through one installed composition root",
            )
        return _seal_execution_composition_ports(self.ports)

    def require_admitted(self, *, queried_at: str | datetime) -> ExecutionLease:
        """Validate structural v3 proof for replay and reconciliation reads."""

        _require_exact_type(self, ExecutionInvocationContext, "execution invocation context")
        for value, expected, label in (
            (self.lease, ExecutionLease, "execution lease"),
            (self.admission, ExecutionAdmission, "execution admission"),
            (self.intent, ActionIntent, "action intent"),
            (self.grant, ValidAuthorityGrant, "valid authority grant"),
            (self.frame, ContextFrame, "context frame"),
            (self.trace, EpistemicImpingementTrace, "epistemic impingement trace"),
            (self.target, ExecutionTargetEvidence, "execution target"),
            (self.route_decision, RouteDecision, "route decision"),
            (self.effect_manifest, EffectManifest, "effect manifest"),
            (self.executor_descriptor, ExecutorDescriptor, "executor descriptor"),
            (
                self.executor_registry_projection,
                ExecutorRegistryProjection,
                "executor registry projection",
            ),
            (self.protected_request, ProtectedActionRequest, "protected action request"),
            (self.aperture_decision, ProtectedApertureDecision, "protected aperture decision"),
            (self.claim_coordinates, ProtectedClaimCoordinates, "protected claim coordinates"),
        ):
            _require_exact_type(value, expected, label)
        checked = require_admitted_execution_lease(self.lease)
        intent = ActionIntent.model_validate(self.intent.model_dump(mode="json", by_alias=True))
        admission = ExecutionAdmission.model_validate(
            self.admission.model_dump(mode="json", by_alias=True)
        )
        grant = ValidAuthorityGrant.model_validate(
            self.grant.model_dump(mode="json", by_alias=True)
        )
        target = ExecutionTargetEvidence.model_validate(
            self.target.model_dump(mode="json", by_alias=True)
        )
        decision = RouteDecision.model_validate(self.route_decision.model_dump(mode="json"))
        manifest = EffectManifest.model_validate(
            self.effect_manifest.model_dump(mode="json", by_alias=True)
        )
        descriptor = ExecutorDescriptor.model_validate(
            self.executor_descriptor.model_dump(mode="json", by_alias=True)
        )
        registry = ExecutorRegistryProjection.model_validate(
            self.executor_registry_projection.model_dump(mode="json", by_alias=True)
        )
        protected_request = ProtectedActionRequest.model_validate(
            self.protected_request.model_dump(mode="json", by_alias=True)
        )
        aperture = ProtectedApertureDecision.model_validate(
            self.aperture_decision.model_dump(mode="json", by_alias=True)
        )
        claim_coordinates = ProtectedClaimCoordinates.model_validate(
            self.claim_coordinates.model_dump(mode="json", by_alias=True)
        )
        reasons: list[str] = []
        if (
            type(checked.claim_basis) is AppliedClaimOwnershipProof
            and type(self.claim_resolution) is AppliedClaimResolution
        ):
            live = self.claim_resolution.resolve_basis(queried_at=queried_at)
            if live.ownership != checked.claim_basis:
                reasons.append("execution_invocation_live_claim_mismatch")
            if (
                live.current_task_note != admission.task_note
                or live.current_task_note != checked.bound_call.task_note
            ):
                reasons.append("execution_invocation_live_task_note_mismatch")
            if target.host_scoped_claim != _current_claim_position_address(
                live.current_position
            ):
                reasons.append("execution_invocation_current_claim_position_mismatch")
        elif (
            type(checked.claim_basis) is ProspectiveClaimPublicationBasis
            and type(self.claim_resolution) is ProspectiveClaimResolution
        ):
            live_basis, live_task_note = self.claim_resolution.resolve_basis()
            if live_basis != checked.claim_basis:
                reasons.append("execution_invocation_live_claim_mismatch")
            if (
                live_task_note != admission.task_note
                or live_task_note != checked.bound_call.task_note
            ):
                reasons.append("execution_invocation_live_task_note_mismatch")
        if checked.admission != ContentAddress(
            ref=admission.admission_ref,
            sha256=admission.admission_hash,
        ):
            reasons.append("execution_invocation_admission_mismatch")
        if checked.authority_grant != ContentAddress(
            ref=grant.grant_ref,
            sha256=grant.grant_hash,
        ):
            reasons.append("execution_invocation_authority_mismatch")
        if checked.effect_manifest != intent.effect_manifest:
            reasons.append("execution_invocation_effect_mismatch")
        if checked.effect_manifest != ContentAddress(
            ref=manifest.manifest_ref,
            sha256=manifest.manifest_hash,
        ):
            reasons.append("execution_invocation_manifest_mismatch")
        if checked.executor_descriptor != ContentAddress(
            ref=descriptor.descriptor_ref,
            sha256=descriptor.descriptor_hash,
        ):
            reasons.append("execution_invocation_executor_mismatch")
        if checked.executor_registry_projection != ContentAddress(
            ref=registry.projection_ref,
            sha256=registry.projection_hash,
        ):
            reasons.append("execution_invocation_registry_mismatch")
        if checked.capability_role != intent.capability_role:
            reasons.append("execution_invocation_capability_role_mismatch")
        if checked.execution_target != ContentAddress(
            ref=target.target_ref,
            sha256=target.target_hash,
        ):
            reasons.append("execution_invocation_target_mismatch")
        if checked.selected_descriptor_leaf != (
            decision.selected_descriptor_leaf or f"{decision.route_id}#base"
        ):
            reasons.append("execution_invocation_descriptor_leaf_mismatch")
        if admission.route_decision != content_address(decision.decision_id, decision):
            reasons.append("execution_invocation_route_decision_mismatch")
        call = checked.bound_call
        if call.action_intent != ContentAddress(ref=intent.intent_ref, sha256=intent.intent_hash):
            reasons.append("execution_invocation_bound_call_intent_mismatch")
        if call.route_decision != content_address(decision.decision_id, decision):
            reasons.append("execution_invocation_bound_call_route_mismatch")
        if (
            call.execution_target
            != ContentAddress(ref=target.target_ref, sha256=target.target_hash)
            or call.adapter != target.adapter
            or call.harness != target.harness
            or call.runtime_identity != target.runtime_identity
            or call.active_generation_roots != target.active_generation_roots
            or call.executor != target.executor
            or call.executor_descriptor != target.executor_descriptor
            or call.executor_registry_projection != target.executor_registry_projection
        ):
            reasons.append("execution_invocation_bound_call_target_mismatch")
        if (
            call.operation != intent.operation
            or call.execution_host != intent.execution_host
            or call.acting_subject != intent.acting_subject
            or call.requested_effect_targets != intent.requested_effect_targets
            or call.requested_scope_refs != intent.requested_scope_refs
            or call.required_authorization_flags != intent.required_authorization_flags
        ):
            reasons.append("execution_invocation_bound_call_effect_mismatch")
        request_address = ContentAddress(
            ref=protected_request.request_ref,
            sha256=protected_request.request_hash,
        )
        aperture_address = ContentAddress(
            ref=aperture.decision_ref,
            sha256=aperture.decision_hash,
        )
        claim_coordinates_address = ContentAddress(
            ref=claim_coordinates.coordinates_ref,
            sha256=claim_coordinates.coordinates_hash,
        )
        basis_address = (
            ContentAddress(
                ref=checked.claim_basis.basis_ref,
                sha256=checked.claim_basis.basis_hash,
            )
            if isinstance(checked.claim_basis, ProspectiveClaimPublicationBasis)
            else ContentAddress(
                ref=checked.claim_basis.proof_ref,
                sha256=checked.claim_basis.proof_hash,
            )
        )
        if (
            intent.protected_action_request != request_address
            or protected_request.aperture_decision != aperture_address
            or protected_request.raw_invocation != aperture.raw_invocation
            or protected_request.claim_coordinates != claim_coordinates_address
        ):
            reasons.append("execution_invocation_protected_request_mismatch")
        if (
            protected_request.task_ref != checked.task_ref
            or protected_request.lane != checked.lane
            or protected_request.session_ref != checked.session_ref
            or protected_request.claim_epoch != checked.claim_epoch
            or claim_coordinates.task_ref != checked.task_ref
            or claim_coordinates.lane != checked.lane
            or claim_coordinates.session_ref != checked.session_ref
            or claim_coordinates.claim_epoch != checked.claim_epoch
            or claim_coordinates.claim_publication_intent
            != checked.claim_basis.claim_publication_intent
            or claim_coordinates.claim_basis != basis_address
            or claim_coordinates != checked.claim_coordinates
            or call.claim_coordinates != claim_coordinates
            or call.claim_basis != basis_address
            or call.protected_action_request != request_address
            or call.task_note != admission.task_note
        ):
            reasons.append("execution_invocation_claim_coordinates_mismatch")
        if (type(checked.claim_basis) is ProspectiveClaimPublicationBasis) != (
            type(self.claim_resolution) is ProspectiveClaimResolution
        ):
            reasons.append("execution_invocation_claim_resolution_branch_mismatch")
        if (
            protected_request.operation != call.operation
            or protected_request.execution_host != call.execution_host
            or protected_request.platform != call.platform
            or protected_request.mode != call.mode
            or protected_request.profile != call.profile
            or protected_request.runtime_identity != checked.runtime_identity
            or protected_request.active_generation_roots != checked.active_generation_roots
            or protected_request.effect_manifest != checked.effect_manifest
            or protected_request.requested_effect_targets != intent.requested_effect_targets
            or protected_request.requested_scope_refs != intent.requested_scope_refs
            or protected_request.mutating != manifest.mutating
        ):
            reasons.append("execution_invocation_protected_effect_mismatch")
        if reasons:
            raise ExecutionAdmissionError(
                "execution_invocation_not_admitted",
                "rebuild the invocation from one exact admitted claim bundle",
                ",".join(reasons),
            )
        _require_current_module_address(protected_request.ingress_module)
        _require_current_module_address(protected_request.admission_module)
        if module_file_address(Path(__file__)) != protected_request.admission_module:
            raise ExecutionAdmissionError(
                "execution_invocation_admission_module_mismatch",
                "evaluate with the exact admission module bound by the request",
                str(Path(__file__).resolve()),
            )
        return checked

    def require_current(
        self,
        *,
        queried_at: str | datetime,
    ) -> tuple[ExecutionLease, ExecutionCurrentnessQuery, ExecutionCurrentnessEnvelope]:
        self.require_admitted(queried_at=queried_at)
        raise ExecutionAdmissionError(
            "execution_composition_activation_unvalidated",
            "obtain a Gate-0B validated install receipt before any effect path",
        )


def _require_current_module_address(address: ContentAddress) -> None:
    suffix = f"@sha256:{address.sha256}"
    if not address.ref.startswith("file:") or not address.ref.endswith(suffix):
        raise ExecutionAdmissionError(
            "protected_action_module_address_invalid",
            "bind executing modules to resolved file bytes",
            address.ref,
        )
    raw_path = address.ref[len("file:") : -len(suffix)]
    try:
        observed = module_file_address(Path(raw_path))
    except (OSError, ValueError) as exc:
        raise ExecutionAdmissionError(
            "protected_action_module_unavailable",
            "restore the exact resolved module bytes before ingress evaluation",
            raw_path,
        ) from exc
    if observed != address:
        raise ExecutionAdmissionError(
            "protected_action_module_generation_mismatch",
            "rebuild the request from the exact executing generation",
            raw_path,
        )


def project_execution_invocation_context(
    request: ProtectedActionRequest,
    aperture: ProtectedApertureDecision,
    claim: ProtectedClaimCoordinates,
    invocation: ExecutionInvocationContext,
    *,
    queried_at: str | datetime,
) -> ExecutionInvocationEnvelope:
    """Bind one ingress request to the structurally admitted invocation roots."""

    _require_exact_type(request, ProtectedActionRequest, "protected action request")
    _require_exact_type(aperture, ProtectedApertureDecision, "protected aperture decision")
    _require_exact_type(claim, ProtectedClaimCoordinates, "protected claim coordinates")
    _require_exact_type(invocation, ExecutionInvocationContext, "execution invocation context")
    checked_request = ProtectedActionRequest.model_validate(
        request.model_dump(mode="json", by_alias=True)
    )
    checked_aperture = ProtectedApertureDecision.model_validate(
        aperture.model_dump(mode="json", by_alias=True)
    )
    checked_claim = ProtectedClaimCoordinates.model_validate(
        claim.model_dump(mode="json", by_alias=True)
    )
    lease = invocation.require_admitted(queried_at=queried_at)
    request_address = ContentAddress(
        ref=checked_request.request_ref,
        sha256=checked_request.request_hash,
    )
    aperture_address = ContentAddress(
        ref=checked_aperture.decision_ref,
        sha256=checked_aperture.decision_hash,
    )
    claim_address = ContentAddress(
        ref=checked_claim.coordinates_ref,
        sha256=checked_claim.coordinates_hash,
    )
    basis_address = (
        ContentAddress(
            ref=lease.claim_basis.basis_ref,
            sha256=lease.claim_basis.basis_hash,
        )
        if isinstance(lease.claim_basis, ProspectiveClaimPublicationBasis)
        else ContentAddress(
            ref=lease.claim_basis.proof_ref,
            sha256=lease.claim_basis.proof_hash,
        )
    )
    mismatches: list[str] = []
    if checked_request.aperture_decision != aperture_address:
        mismatches.append("aperture_decision")
    if checked_request.raw_invocation != checked_aperture.raw_invocation:
        mismatches.append("raw_invocation")
    if checked_request.claim_coordinates != claim_address:
        mismatches.append("claim_coordinates")
    if checked_request.operation != checked_aperture.operation:
        mismatches.append("operation_aperture")
    if invocation.intent.protected_action_request != request_address:
        mismatches.append("action_intent_request")
    if (
        checked_request.task_ref != lease.task_ref
        or checked_request.lane != lease.lane
        or checked_request.session_ref != lease.session_ref
        or checked_request.claim_epoch != lease.claim_epoch
        or checked_claim.task_ref != lease.task_ref
        or checked_claim.lane != lease.lane
        or checked_claim.session_ref != lease.session_ref
        or checked_claim.claim_epoch != lease.claim_epoch
    ):
        mismatches.append("claim_identity")
    if checked_claim.claim_publication_intent != lease.claim_basis.claim_publication_intent:
        mismatches.append("claim_publication_intent")
    if checked_claim.claim_basis != basis_address or checked_claim != lease.claim_coordinates:
        mismatches.append("claim_basis")
    if (
        checked_request.operation != invocation.intent.operation
        or checked_request.operation != lease.bound_call.operation
        or checked_request.execution_host != invocation.intent.execution_host
        or checked_request.execution_host != lease.bound_call.execution_host
        or checked_request.platform != lease.bound_call.platform
        or checked_request.mode != lease.bound_call.mode
        or checked_request.profile != lease.bound_call.profile
    ):
        mismatches.append("operation_or_route")
    if (
        checked_request.runtime_identity != lease.runtime_identity
        or checked_request.active_generation_roots != lease.active_generation_roots
        or checked_request.effect_manifest != lease.effect_manifest
        or checked_request.requested_effect_targets != invocation.intent.requested_effect_targets
        or checked_request.requested_scope_refs != invocation.intent.requested_scope_refs
        or checked_request.mutating != invocation.effect_manifest.mutating
    ):
        mismatches.append("effect_or_generation")
    if mismatches:
        raise ExecutionAdmissionError(
            "protected_action_invocation_mismatch",
            "rebuild the ingress and invocation from one exact action root",
            ",".join(sorted(set(mismatches))),
        )
    _require_current_module_address(checked_request.ingress_module)
    _require_current_module_address(checked_request.admission_module)
    admission_module = module_file_address(Path(__file__))
    if admission_module != checked_request.admission_module:
        raise ExecutionAdmissionError(
            "protected_action_admission_module_mismatch",
            "evaluate the request with the exact bound admission module",
            str(Path(__file__).resolve()),
        )
    body: dict[str, object] = {
        "schema": EXECUTION_INVOCATION_ENVELOPE_SCHEMA,
        "protected_action_request": request_address,
        "execution_lease": ContentAddress(ref=lease.lease_ref, sha256=lease.lease_hash),
        "bound_execution_call": ContentAddress(
            ref=lease.bound_call.call_ref,
            sha256=lease.bound_call.call_hash,
        ),
        "execution_admission": ContentAddress(
            ref=invocation.admission.admission_ref,
            sha256=invocation.admission.admission_hash,
        ),
        "action_intent": ContentAddress(
            ref=invocation.intent.intent_ref,
            sha256=invocation.intent.intent_hash,
        ),
        "authority_grant": ContentAddress(
            ref=invocation.grant.grant_ref,
            sha256=invocation.grant.grant_hash,
        ),
        "claim_coordinates": claim_address,
        "claim_basis": basis_address,
        "task_note": invocation.admission.task_note,
        "context_frame": ContentAddress(
            ref=invocation.frame.frame_ref,
            sha256=invocation.frame.frame_hash,
        ),
        "epistemic_trace": ContentAddress(
            ref=invocation.trace.trace_ref,
            sha256=invocation.trace.trace_hash,
        ),
        "execution_target": ContentAddress(
            ref=invocation.target.target_ref,
            sha256=invocation.target.target_hash,
        ),
        "route_decision": content_address(
            invocation.route_decision.decision_id,
            invocation.route_decision,
        ),
        "effect_manifest": ContentAddress(
            ref=invocation.effect_manifest.manifest_ref,
            sha256=invocation.effect_manifest.manifest_hash,
        ),
        "executor_descriptor": ContentAddress(
            ref=invocation.executor_descriptor.descriptor_ref,
            sha256=invocation.executor_descriptor.descriptor_hash,
        ),
        "executor_registry_projection": ContentAddress(
            ref=invocation.executor_registry_projection.projection_ref,
            sha256=invocation.executor_registry_projection.projection_hash,
        ),
        "may_authorize": False,
    }
    digest = _self_hash(EXECUTION_INVOCATION_ENVELOPE_SCHEMA, body)
    return ExecutionInvocationEnvelope.model_validate(
        {
            **body,
            "envelope_ref": f"execution-invocation-envelope@sha256:{digest}",
            "envelope_hash": digest,
        }
    )


class ExecutionCompositionPortDescriptors(_FrozenModel):
    """Content identities for every runtime port; these do not install a port."""

    schema_id: Literal["hapax.execution-composition-port-descriptors.v3"] = Field(alias="schema")
    descriptors_ref: str
    descriptors_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    trust_resolver: ContentAddress
    effect_manifest_resolver: ContentAddress
    currentness_resolver: ContentAddress
    executor_registry: ContentAddress
    completion_evaluator: ContentAddress
    readiness_resolver: ContentAddress
    outcome_committer: ContentAddress
    event_plane: ContentAddress
    outcome_projection_resolver: ContentAddress
    outcome_validity_resolver: ContentAddress
    may_authorize: Literal[False]

    @field_validator("descriptors_ref")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @model_validator(mode="after")
    def validate_descriptors(self) -> Self:
        addresses = (
            self.trust_resolver,
            self.effect_manifest_resolver,
            self.currentness_resolver,
            self.executor_registry,
            self.completion_evaluator,
            self.readiness_resolver,
            self.outcome_committer,
            self.event_plane,
            self.outcome_projection_resolver,
            self.outcome_validity_resolver,
        )
        if any(not address.ref.endswith(f"@sha256:{address.sha256}") for address in addresses):
            raise ValueError("composition port descriptors must be content addressed")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"descriptors_ref", "descriptors_hash"},
        )
        expected = _self_hash(EXECUTION_COMPOSITION_PORT_DESCRIPTORS_SCHEMA, body)
        if self.descriptors_hash != expected or self.descriptors_ref != (
            f"execution-composition-ports@sha256:{expected}"
        ):
            raise ValueError("composition port descriptors do not bind their body")
        return self


def build_execution_composition_port_descriptors(
    *,
    trust_resolver: ContentAddress,
    effect_manifest_resolver: ContentAddress,
    currentness_resolver: ContentAddress,
    executor_registry: ContentAddress,
    completion_evaluator: ContentAddress,
    readiness_resolver: ContentAddress,
    outcome_committer: ContentAddress,
    event_plane: ContentAddress,
    outcome_projection_resolver: ContentAddress,
    outcome_validity_resolver: ContentAddress,
) -> ExecutionCompositionPortDescriptors:
    body: dict[str, object] = {
        "schema": EXECUTION_COMPOSITION_PORT_DESCRIPTORS_SCHEMA,
        "trust_resolver": trust_resolver,
        "effect_manifest_resolver": effect_manifest_resolver,
        "currentness_resolver": currentness_resolver,
        "executor_registry": executor_registry,
        "completion_evaluator": completion_evaluator,
        "readiness_resolver": readiness_resolver,
        "outcome_committer": outcome_committer,
        "event_plane": event_plane,
        "outcome_projection_resolver": outcome_projection_resolver,
        "outcome_validity_resolver": outcome_validity_resolver,
        "may_authorize": False,
    }
    digest = _self_hash(EXECUTION_COMPOSITION_PORT_DESCRIPTORS_SCHEMA, body)
    return ExecutionCompositionPortDescriptors.model_validate(
        {
            **body,
            "descriptors_ref": f"execution-composition-ports@sha256:{digest}",
            "descriptors_hash": digest,
        }
    )


def _bounded_absolute_path(value: Path | str, *, label: str) -> Path:
    raw = Path(value).expanduser()
    if not raw.is_absolute() or raw == Path("/"):
        raise ValueError(f"{label} must be an absolute bounded path")
    return _normalized_path(raw)


class ExecutionCompositionManifest(_FrozenModel):
    """Installed composition identity; integrity alone never authorizes activation."""

    schema_id: Literal["hapax.execution-composition-manifest.v2"] = Field(alias="schema")
    manifest_ref: str
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    activation_generation: ContentAddress
    invocation_store_root: str
    max_bundle_bytes: int = Field(
        gt=0,
        le=_MAX_EXECUTION_INVOCATION_BUNDLE_BYTES,
        strict=True,
    )
    claim_vault_root: str
    claim_cache_dir: str
    claim_transaction_root: str
    claim_receipt_root: str
    claim_lock_root: str
    port_descriptors: ExecutionCompositionPortDescriptors
    attempt_journal: ContentAddress
    activation_receipt: ContentAddress | None
    may_authorize: Literal[False]

    @field_validator(
        "manifest_ref",
        "invocation_store_root",
        "claim_vault_root",
        "claim_cache_dir",
        "claim_transaction_root",
        "claim_receipt_root",
        "claim_lock_root",
    )
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        path_values = {
            "invocation_store_root": self.invocation_store_root,
            "claim_vault_root": self.claim_vault_root,
            "claim_cache_dir": self.claim_cache_dir,
            "claim_transaction_root": self.claim_transaction_root,
            "claim_receipt_root": self.claim_receipt_root,
            "claim_lock_root": self.claim_lock_root,
        }
        paths = {
            name: _bounded_absolute_path(value, label=name) for name, value in path_values.items()
        }
        if any(str(paths[name]) != value for name, value in path_values.items()):
            raise ValueError("composition paths must use normalized absolute spelling")
        store = paths["invocation_store_root"]
        claim_names = tuple(name for name in paths if name != "invocation_store_root")
        for name in claim_names:
            claim_path = paths[name]
            if (
                store == claim_path
                or store.is_relative_to(claim_path)
                or claim_path.is_relative_to(store)
            ):
                raise ValueError("invocation store must not overlap claim roots")
        for index, left_name in enumerate(claim_names):
            left = paths[left_name]
            for right_name in claim_names[index + 1 :]:
                right = paths[right_name]
                if left != right and not (left.is_relative_to(right) or right.is_relative_to(left)):
                    continue
                receipt_cache_pair = {left_name, right_name} == {
                    "claim_cache_dir",
                    "claim_receipt_root",
                }
                receipt_under_cache = (
                    paths["claim_receipt_root"].is_relative_to(paths["claim_cache_dir"])
                    and paths["claim_receipt_root"] != paths["claim_cache_dir"]
                )
                if not (receipt_cache_pair and receipt_under_cache):
                    raise ValueError("composition claim roots overlap without declaration")
        addresses = (
            self.activation_generation,
            self.attempt_journal,
            *(() if self.activation_receipt is None else (self.activation_receipt,)),
        )
        if any(not address.ref.endswith(f"@sha256:{address.sha256}") for address in addresses):
            raise ValueError("composition manifest roots must be content addressed")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"manifest_ref", "manifest_hash"},
        )
        expected = _self_hash(EXECUTION_COMPOSITION_MANIFEST_SCHEMA, body)
        if self.manifest_hash != expected or self.manifest_ref != (
            f"execution-composition-manifest@sha256:{expected}"
        ):
            raise ValueError("execution composition manifest does not bind its body")
        return self


def build_execution_composition_manifest(
    *,
    activation_generation: ContentAddress,
    invocation_store_root: Path,
    max_bundle_bytes: int,
    claim_vault_root: Path,
    claim_cache_dir: Path,
    claim_transaction_root: Path,
    claim_receipt_root: Path,
    claim_lock_root: Path,
    port_descriptors: ExecutionCompositionPortDescriptors,
    attempt_journal: ContentAddress,
    activation_receipt: ContentAddress | None = None,
) -> ExecutionCompositionManifest:
    paths = {
        "invocation_store_root": str(
            _bounded_absolute_path(invocation_store_root, label="invocation_store_root")
        ),
        "claim_vault_root": str(_bounded_absolute_path(claim_vault_root, label="claim_vault_root")),
        "claim_cache_dir": str(_bounded_absolute_path(claim_cache_dir, label="claim_cache_dir")),
        "claim_transaction_root": str(
            _bounded_absolute_path(claim_transaction_root, label="claim_transaction_root")
        ),
        "claim_receipt_root": str(
            _bounded_absolute_path(claim_receipt_root, label="claim_receipt_root")
        ),
        "claim_lock_root": str(_bounded_absolute_path(claim_lock_root, label="claim_lock_root")),
    }
    body: dict[str, object] = {
        "schema": EXECUTION_COMPOSITION_MANIFEST_SCHEMA,
        "activation_generation": activation_generation,
        **paths,
        "max_bundle_bytes": max_bundle_bytes,
        "port_descriptors": port_descriptors,
        "attempt_journal": attempt_journal,
        "activation_receipt": activation_receipt,
        "may_authorize": False,
    }
    digest = _self_hash(EXECUTION_COMPOSITION_MANIFEST_SCHEMA, body)
    return ExecutionCompositionManifest.model_validate(
        {
            **body,
            "manifest_ref": f"execution-composition-manifest@sha256:{digest}",
            "manifest_hash": digest,
        }
    )


def execution_composition_manifest_bytes(
    manifest: ExecutionCompositionManifest,
) -> bytes:
    checked = ExecutionCompositionManifest.model_validate(
        manifest.model_dump(mode="json", by_alias=True)
    )
    return (
        json.dumps(
            checked.model_dump(mode="json", by_alias=True),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        + b"\n"
    )


class HistoricalExecutionInvocationBundleV2(_FrozenModel):
    """Historical v2 reconstruction carrier retained for exact inspection only."""

    schema_id: Literal["hapax.execution-invocation-bundle.v2"] = Field(alias="schema")
    bundle_ref: str
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_role: str
    composition_manifest: ContentAddress
    invocation_envelope: HistoricalExecutionInvocationEnvelopeV1
    protected_action_request: ProtectedActionRequest
    aperture_decision: ProtectedApertureDecision
    claim_coordinates: HistoricalProtectedClaimCoordinatesV1
    execution_lease: HistoricalExecutionLeaseV2
    admitted_claim: AdmittedAppliedClaimProof
    execution_admission: ExecutionAdmission
    action_intent: ActionIntent
    authority_grant: ValidAuthorityGrant
    context_frame: ContextFrame
    epistemic_trace: EpistemicImpingementTrace
    execution_target: ExecutionTargetEvidence
    route_decision: RouteDecision
    effect_manifest: EffectManifest
    executor_descriptor: ExecutorDescriptor
    executor_registry_projection: ExecutorRegistryProjection
    may_authorize: Literal[False]
    authorizes_direct_fallthrough: Literal[False]

    @field_validator("bundle_ref", "claim_role")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @model_validator(mode="after")
    def validate_bundle(self) -> Self:
        if self.composition_manifest.ref != (
            f"execution-composition-manifest@sha256:{self.composition_manifest.sha256}"
        ):
            raise ValueError("bundle composition manifest address is not canonical")
        lease = self.execution_lease
        admitted = self.admitted_claim
        request = self.protected_action_request
        aperture = self.aperture_decision
        claim = self.claim_coordinates
        admission = self.execution_admission
        intent = self.action_intent
        grant = self.authority_grant
        envelope = self.invocation_envelope
        expected_roots = {
            "protected_action_request": ContentAddress(
                ref=request.request_ref,
                sha256=request.request_hash,
            ),
            "execution_lease": ContentAddress(
                ref=lease.lease_ref,
                sha256=lease.lease_hash,
            ),
            "execution_admission": ContentAddress(
                ref=admission.admission_ref,
                sha256=admission.admission_hash,
            ),
            "action_intent": ContentAddress(
                ref=intent.intent_ref,
                sha256=intent.intent_hash,
            ),
            "authority_grant": ContentAddress(
                ref=grant.grant_ref,
                sha256=grant.grant_hash,
            ),
            "admitted_claim": ContentAddress(
                ref=admitted.proof_ref,
                sha256=admitted.proof_hash,
            ),
            "context_frame": ContentAddress(
                ref=self.context_frame.frame_ref,
                sha256=self.context_frame.frame_hash,
            ),
            "epistemic_trace": ContentAddress(
                ref=self.epistemic_trace.trace_ref,
                sha256=self.epistemic_trace.trace_hash,
            ),
            "execution_target": ContentAddress(
                ref=self.execution_target.target_ref,
                sha256=self.execution_target.target_hash,
            ),
            "route_decision": content_address(
                self.route_decision.decision_id,
                self.route_decision,
            ),
            "effect_manifest": ContentAddress(
                ref=self.effect_manifest.manifest_ref,
                sha256=self.effect_manifest.manifest_hash,
            ),
            "executor_descriptor": ContentAddress(
                ref=self.executor_descriptor.descriptor_ref,
                sha256=self.executor_descriptor.descriptor_hash,
            ),
            "executor_registry_projection": ContentAddress(
                ref=self.executor_registry_projection.projection_ref,
                sha256=self.executor_registry_projection.projection_hash,
            ),
        }
        mismatches = [
            name for name, expected in expected_roots.items() if getattr(envelope, name) != expected
        ]
        request_address = expected_roots["protected_action_request"]
        aperture_address = ContentAddress(
            ref=aperture.decision_ref,
            sha256=aperture.decision_hash,
        )
        claim_address = ContentAddress(
            ref=claim.coordinates_ref,
            sha256=claim.coordinates_hash,
        )
        admitted_address = expected_roots["admitted_claim"]
        if lease.applied_claim != admitted:
            mismatches.append("lease_admitted_claim")
        if (
            request.aperture_decision != aperture_address
            or request.raw_invocation != aperture.raw_invocation
            or request.operation != aperture.operation
            or request.ingress_module != aperture.classifier_module
        ):
            mismatches.append("aperture_request")
        if request.claim_coordinates != claim_address:
            mismatches.append("request_claim_coordinates")
        if intent.protected_action_request != request_address:
            mismatches.append("intent_request")
        if claim.state == "prospective" or (
            claim.admitted_claim is not None and claim.admitted_claim != admitted_address
        ):
            mismatches.append("ordinary_bundle_requires_nonprospective_claim")
        if claim.claim_publication_intent != admitted.claim_publication_intent:
            mismatches.append("claim_publication_intent")
        identity = (lease.task_ref, lease.lane, lease.session_ref, lease.claim_epoch)
        if any(
            candidate != identity
            for candidate in (
                (request.task_ref, request.lane, request.session_ref, request.claim_epoch),
                (claim.task_ref, claim.lane, claim.session_ref, claim.claim_epoch),
                (admitted.task_ref, admitted.lane, admitted.session_ref, admitted.claim_epoch),
            )
        ):
            mismatches.append("claim_identity")
        if (
            admission.task_ref != lease.task_ref
            or admission.lane != lease.lane
            or admission.session_ref != lease.session_ref
            or intent.task_ref != lease.task_ref
            or grant.task_ref != lease.task_ref
            or self.context_frame.position.task_ref != lease.task_ref
            or self.claim_role != lease.lane
        ):
            mismatches.append("admission_identity")
        if (
            admitted.execution_admission != expected_roots["execution_admission"]
            or admitted.valid_authority_grant != expected_roots["authority_grant"]
            or admitted.context_position
            != ContentAddress(
                ref=self.context_frame.position.position_ref,
                sha256=self.context_frame.position.position_hash,
            )
            or admission.claim_publication_intent != admitted.claim_publication_intent
        ):
            mismatches.append("admitted_claim_roots")
        if mismatches:
            raise ValueError(
                "historical execution invocation bundle roots differ: "
                + ",".join(sorted(set(mismatches)))
            )
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"bundle_ref", "bundle_hash"},
        )
        expected_hash = _self_hash(HISTORICAL_EXECUTION_INVOCATION_BUNDLE_SCHEMA, body)
        if self.bundle_hash != expected_hash or self.bundle_ref != (
            f"execution-invocation-bundle@sha256:{expected_hash}"
        ):
            raise ValueError("historical execution invocation bundle does not bind its body")
        return self


class ExecutionInvocationBundle(_FrozenModel):
    """Immutable admission-time reconstruction carrier for one admitted invocation."""

    schema_id: Literal["hapax.execution-invocation-bundle.v3"] = Field(alias="schema")
    bundle_ref: str
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_role: str
    composition_manifest: ContentAddress
    invocation_envelope: ExecutionInvocationEnvelope
    protected_action_request: ProtectedActionRequest
    aperture_decision: ProtectedApertureDecision
    claim_coordinates: ProtectedClaimCoordinates
    execution_lease: ExecutionLease
    prospective_claim: ProspectiveClaimPublicationCarrier | None
    claim_basis: ProspectiveClaimPublicationBasis | AppliedClaimOwnershipProof
    execution_admission: ExecutionAdmission
    action_intent: ActionIntent
    authority_grant: ValidAuthorityGrant
    context_frame: ContextFrame
    epistemic_trace: EpistemicImpingementTrace
    execution_target: ExecutionTargetEvidence
    route_decision: RouteDecision
    effect_manifest: EffectManifest
    executor_descriptor: ExecutorDescriptor
    executor_registry_projection: ExecutorRegistryProjection
    may_authorize: Literal[False]
    authorizes_direct_fallthrough: Literal[False]

    @field_validator("bundle_ref", "claim_role")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @model_validator(mode="after")
    def validate_bundle(self) -> Self:
        if self.composition_manifest.ref != (
            f"execution-composition-manifest@sha256:{self.composition_manifest.sha256}"
        ):
            raise ValueError("bundle composition manifest address is not canonical")
        lease = self.execution_lease
        basis = self.claim_basis
        request = self.protected_action_request
        aperture = self.aperture_decision
        claim = self.claim_coordinates
        admission = self.execution_admission
        intent = self.action_intent
        grant = self.authority_grant
        envelope = self.invocation_envelope
        expected_roots = {
            "protected_action_request": ContentAddress(
                ref=request.request_ref, sha256=request.request_hash
            ),
            "execution_lease": ContentAddress(ref=lease.lease_ref, sha256=lease.lease_hash),
            "bound_execution_call": ContentAddress(
                ref=lease.bound_call.call_ref,
                sha256=lease.bound_call.call_hash,
            ),
            "execution_admission": ContentAddress(
                ref=admission.admission_ref, sha256=admission.admission_hash
            ),
            "action_intent": ContentAddress(ref=intent.intent_ref, sha256=intent.intent_hash),
            "authority_grant": ContentAddress(ref=grant.grant_ref, sha256=grant.grant_hash),
            "claim_coordinates": ContentAddress(
                ref=claim.coordinates_ref,
                sha256=claim.coordinates_hash,
            ),
            "claim_basis": (
                ContentAddress(ref=basis.basis_ref, sha256=basis.basis_hash)
                if isinstance(basis, ProspectiveClaimPublicationBasis)
                else ContentAddress(ref=basis.proof_ref, sha256=basis.proof_hash)
            ),
            "task_note": admission.task_note,
            "context_frame": ContentAddress(
                ref=self.context_frame.frame_ref, sha256=self.context_frame.frame_hash
            ),
            "epistemic_trace": ContentAddress(
                ref=self.epistemic_trace.trace_ref, sha256=self.epistemic_trace.trace_hash
            ),
            "execution_target": ContentAddress(
                ref=self.execution_target.target_ref,
                sha256=self.execution_target.target_hash,
            ),
            "route_decision": content_address(self.route_decision.decision_id, self.route_decision),
            "effect_manifest": ContentAddress(
                ref=self.effect_manifest.manifest_ref,
                sha256=self.effect_manifest.manifest_hash,
            ),
            "executor_descriptor": ContentAddress(
                ref=self.executor_descriptor.descriptor_ref,
                sha256=self.executor_descriptor.descriptor_hash,
            ),
            "executor_registry_projection": ContentAddress(
                ref=self.executor_registry_projection.projection_ref,
                sha256=self.executor_registry_projection.projection_hash,
            ),
        }
        mismatches = [
            name for name, expected in expected_roots.items() if getattr(envelope, name) != expected
        ]
        request_address = expected_roots["protected_action_request"]
        aperture_address = ContentAddress(ref=aperture.decision_ref, sha256=aperture.decision_hash)
        claim_address = ContentAddress(ref=claim.coordinates_ref, sha256=claim.coordinates_hash)
        basis_address = expected_roots["claim_basis"]
        if lease.claim_basis != basis:
            mismatches.append("lease_claim_basis")
        if (
            request.aperture_decision != aperture_address
            or request.raw_invocation != aperture.raw_invocation
            or request.operation != aperture.operation
            or request.ingress_module != aperture.classifier_module
        ):
            mismatches.append("aperture_request")
        if request.claim_coordinates != claim_address:
            mismatches.append("request_claim_coordinates")
        if intent.protected_action_request != request_address:
            mismatches.append("intent_request")
        prospective = isinstance(basis, ProspectiveClaimPublicationBasis)
        if prospective != (claim.state == "prospective"):
            mismatches.append("claim_branch")
        if prospective != (self.prospective_claim is not None):
            mismatches.append("prospective_carrier_branch")
        if self.prospective_claim is not None and self.prospective_claim.basis != basis:
            mismatches.append("prospective_carrier_basis")
        if claim.claim_basis != basis_address:
            mismatches.append("claim_basis")
        if claim.claim_publication_intent != basis.claim_publication_intent:
            mismatches.append("claim_publication_intent")
        identity = (lease.task_ref, lease.lane, lease.session_ref, lease.claim_epoch)
        if any(
            candidate != identity
            for candidate in (
                (request.task_ref, request.lane, request.session_ref, request.claim_epoch),
                (claim.task_ref, claim.lane, claim.session_ref, claim.claim_epoch),
                (basis.task_ref, basis.lane, basis.session_ref, basis.claim_epoch),
            )
        ):
            mismatches.append("claim_identity")
        if (
            admission.task_ref != lease.task_ref
            or admission.lane != lease.lane
            or admission.session_ref != lease.session_ref
            or intent.task_ref != lease.task_ref
            or grant.task_ref != lease.task_ref
            or self.context_frame.position.task_ref != lease.task_ref
            or self.claim_role != lease.lane
        ):
            mismatches.append("admission_identity")
        if admission.claim_publication_intent != basis.claim_publication_intent:
            mismatches.append("claim_basis_roots")
        if mismatches:
            raise ValueError(
                "execution invocation bundle roots differ: " + ",".join(sorted(set(mismatches)))
            )
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"bundle_ref", "bundle_hash"},
        )
        expected_hash = _self_hash(EXECUTION_INVOCATION_BUNDLE_SCHEMA, body)
        if self.bundle_hash != expected_hash or self.bundle_ref != (
            f"execution-invocation-bundle@sha256:{expected_hash}"
        ):
            raise ValueError("execution invocation bundle does not bind its body")
        return self


def parse_execution_invocation_bundle_record(
    value: Mapping[str, object],
) -> HistoricalExecutionInvocationBundleV2 | ExecutionInvocationBundle:
    """Parse exact historical-v2 or active-v3 bytes without upgrading either."""

    schema = value.get("schema")
    if schema == HISTORICAL_EXECUTION_INVOCATION_BUNDLE_SCHEMA:
        return HistoricalExecutionInvocationBundleV2.model_validate(value)
    if schema == EXECUTION_INVOCATION_BUNDLE_SCHEMA:
        return ExecutionInvocationBundle.model_validate(value)
    raise ExecutionAdmissionError(
        "execution_invocation_bundle_schema_unknown",
        "supply exact historical-v2 or active-v3 invocation bundle bytes",
        str(schema),
    )


def build_execution_invocation_bundle(
    invocation: ExecutionInvocationContext,
    *,
    composition_manifest: ExecutionCompositionManifest,
    queried_at: str | datetime,
) -> ExecutionInvocationBundle:
    """Freeze all structural roots required to reconstruct one invocation."""

    _require_exact_type(invocation, ExecutionInvocationContext, "execution invocation context")
    _require_exact_type(
        composition_manifest,
        ExecutionCompositionManifest,
        "execution composition manifest",
    )
    lease = invocation.require_admitted(queried_at=queried_at)
    checked_manifest = ExecutionCompositionManifest.model_validate(
        composition_manifest.model_dump(mode="json", by_alias=True)
    )
    envelope = project_execution_invocation_context(
        invocation.protected_request,
        invocation.aperture_decision,
        invocation.claim_coordinates,
        invocation,
        queried_at=queried_at,
    )
    body: dict[str, object] = {
        "schema": EXECUTION_INVOCATION_BUNDLE_SCHEMA,
        "claim_role": lease.lane,
        "composition_manifest": ContentAddress(
            ref=checked_manifest.manifest_ref,
            sha256=checked_manifest.manifest_hash,
        ),
        "invocation_envelope": envelope,
        "protected_action_request": invocation.protected_request,
        "aperture_decision": invocation.aperture_decision,
        "claim_coordinates": invocation.claim_coordinates,
        "execution_lease": lease,
        "prospective_claim": (
            invocation.claim_resolution.carrier
            if isinstance(invocation.claim_resolution, ProspectiveClaimResolution)
            else None
        ),
        "claim_basis": lease.claim_basis,
        "execution_admission": invocation.admission,
        "action_intent": invocation.intent,
        "authority_grant": invocation.grant,
        "context_frame": invocation.frame,
        "epistemic_trace": invocation.trace,
        "execution_target": invocation.target,
        "route_decision": invocation.route_decision,
        "effect_manifest": invocation.effect_manifest,
        "executor_descriptor": invocation.executor_descriptor,
        "executor_registry_projection": invocation.executor_registry_projection,
        "may_authorize": False,
        "authorizes_direct_fallthrough": False,
    }
    digest = _self_hash(EXECUTION_INVOCATION_BUNDLE_SCHEMA, body)
    return ExecutionInvocationBundle.model_validate(
        {
            **body,
            "bundle_ref": f"execution-invocation-bundle@sha256:{digest}",
            "bundle_hash": digest,
        }
    )


class ExecutionInvocationBundlePointer(_FrozenModel):
    """Path-free address for a bundle in the composition-owned immutable store."""

    schema_id: Literal["hapax.execution-invocation-bundle-pointer.v2"] = Field(alias="schema")
    pointer_ref: str
    pointer_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    composition_manifest: ContentAddress
    bundle: ContentAddress
    canonical_bytes: ContentAddress
    may_authorize: Literal[False]
    authorizes_direct_fallthrough: Literal[False]

    @field_validator("pointer_ref")
    @classmethod
    def validate_string(cls, value: str) -> str:
        return _nonblank(value)

    @model_validator(mode="after")
    def validate_pointer(self) -> Self:
        if self.composition_manifest.ref != (
            f"execution-composition-manifest@sha256:{self.composition_manifest.sha256}"
        ):
            raise ValueError("pointer composition manifest address is not canonical")
        if self.bundle.ref != f"execution-invocation-bundle@sha256:{self.bundle.sha256}":
            raise ValueError("bundle pointer must use the semantic bundle address")
        if self.canonical_bytes.ref != (
            f"execution-invocation-bundle-bytes@sha256:{self.canonical_bytes.sha256}"
        ):
            raise ValueError("bundle pointer must bind exact canonical storage bytes")
        body = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"pointer_ref", "pointer_hash"},
        )
        expected_hash = _self_hash(EXECUTION_INVOCATION_BUNDLE_POINTER_SCHEMA, body)
        if self.pointer_hash != expected_hash or self.pointer_ref != (
            f"execution-invocation-bundle-pointer@sha256:{expected_hash}"
        ):
            raise ValueError("execution invocation bundle pointer does not bind its body")
        return self


def _execution_invocation_bundle_bytes(
    bundle: HistoricalExecutionInvocationBundleV2 | ExecutionInvocationBundle,
) -> bytes:
    checked = parse_execution_invocation_bundle_record(
        bundle.model_dump(mode="json", by_alias=True)
    )
    payload = checked.model_dump(mode="json", by_alias=True)
    return (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        + b"\n"
    )


def build_execution_invocation_bundle_pointer(
    bundle: ExecutionInvocationBundle,
) -> ExecutionInvocationBundlePointer:
    checked = ExecutionInvocationBundle.model_validate(
        bundle.model_dump(mode="json", by_alias=True)
    )
    payload = _execution_invocation_bundle_bytes(checked)
    payload_hash = _sha256(payload)
    body: dict[str, object] = {
        "schema": EXECUTION_INVOCATION_BUNDLE_POINTER_SCHEMA,
        "composition_manifest": checked.composition_manifest,
        "bundle": ContentAddress(ref=checked.bundle_ref, sha256=checked.bundle_hash),
        "canonical_bytes": ContentAddress(
            ref=f"execution-invocation-bundle-bytes@sha256:{payload_hash}",
            sha256=payload_hash,
        ),
        "may_authorize": False,
        "authorizes_direct_fallthrough": False,
    }
    digest = _self_hash(EXECUTION_INVOCATION_BUNDLE_POINTER_SCHEMA, body)
    return ExecutionInvocationBundlePointer.model_validate(
        {
            **body,
            "pointer_ref": f"execution-invocation-bundle-pointer@sha256:{digest}",
            "pointer_hash": digest,
        }
    )


@dataclass(frozen=True)
class ExecutionInvocationBundleStore:
    """Private content-addressed store; it never owns an ambient latest pointer."""

    root: Path
    composition_manifest: ExecutionCompositionManifest

    def __post_init__(self) -> None:
        _require_exact_type(self.root, type(Path()), "execution invocation store root")
        _require_exact_type(
            self.composition_manifest,
            ExecutionCompositionManifest,
            "execution composition manifest",
        )
        root = _bounded_absolute_path(self.root, label="execution invocation store root")
        manifest = ExecutionCompositionManifest.model_validate(
            self.composition_manifest.model_dump(mode="json", by_alias=True)
        )
        if str(root) != manifest.invocation_store_root:
            raise ValueError("store root must equal the composition manifest root")
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "composition_manifest", manifest)

    @property
    def activation_generation(self) -> ContentAddress:
        return self.composition_manifest.activation_generation

    @property
    def max_bundle_bytes(self) -> int:
        return self.composition_manifest.max_bundle_bytes

    @property
    def objects_root(self) -> Path:
        return self.root / "objects"

    @property
    def manifest_path(self) -> Path:
        return self.root / "composition-manifest.json"

    def _object_path(self, canonical_bytes_hash: str) -> Path:
        if len(canonical_bytes_hash) != 64 or any(
            character not in "0123456789abcdef" for character in canonical_bytes_hash
        ):
            raise ExecutionAdmissionError(
                "execution_invocation_store_address_invalid",
                "resolve one exact SHA-256-addressed invocation bundle",
            )
        return self.objects_root / f"{canonical_bytes_hash}.json"

    def _read_private(self, path: Path) -> bytes | None:
        try:
            with ReadOnlyFsSnapshot(
                max_total_bytes=(self.max_bundle_bytes + _MAX_EXECUTION_COMPOSITION_MANIFEST_BYTES),
                change_scope="observed_paths",
            ) as snapshot:
                store = snapshot.pin_absolute_dir(self.root, private_final=True)
                if store is None:  # pragma: no cover - allow_missing is false
                    raise AssertionError("required invocation store root disappeared")
                manifest_observation = snapshot.observe_file_at(
                    store,
                    "composition-manifest.json",
                    private=True,
                    max_bytes=_MAX_EXECUTION_COMPOSITION_MANIFEST_BYTES,
                )
                objects = snapshot.pin_dir_at(store, "objects", private=True)
                observed = snapshot.observe_file_at(
                    objects,
                    path.name,
                    private=True,
                    max_bytes=self.max_bundle_bytes,
                )
                snapshot.seal()
        except ReadOnlySnapshotError as exc:
            raise ExecutionAdmissionError(
                "execution_invocation_store_object_unsafe",
                "restore one stable euid-owned private invocation store and object",
                f"{exc.reason_code}:{path}",
            ) from exc
        if not manifest_observation.present or manifest_observation.captured is None:
            raise ExecutionAdmissionError(
                "execution_composition_manifest_missing",
                "install the exact immutable composition manifest before store use",
                str(self.manifest_path),
            )
        manifest_content = manifest_observation.captured.content
        try:
            manifest_payload = _load_private_manifest_payload(
                self.manifest_path,
                content=manifest_content,
            )
            installed_manifest = ExecutionCompositionManifest.model_validate(manifest_payload)
        except (LifecycleTransitionError, ValueError) as exc:
            raise ExecutionAdmissionError(
                "execution_composition_manifest_invalid",
                "restore the exact canonical installed composition manifest",
                str(self.manifest_path),
            ) from exc
        if (
            installed_manifest != self.composition_manifest
            or execution_composition_manifest_bytes(installed_manifest) != manifest_content
        ):
            raise ExecutionAdmissionError(
                "execution_composition_manifest_mismatch",
                "use only the store installed for the exact composition manifest",
                installed_manifest.manifest_ref,
            )
        if not observed.present:
            return None
        if observed.captured is None:  # pragma: no cover - model invariant
            raise AssertionError("present invocation object lacks captured bytes")
        return observed.captured.content

    def put(self, bundle: ExecutionInvocationBundle) -> ExecutionInvocationBundlePointer:
        """Gate-0A HOLD: persistence is an effect and requires activated dispatch."""

        del bundle
        raise ExecutionAdmissionError(
            "execution_invocation_store_activation_unvalidated",
            "persist through a Gate-0B activated universal executor",
            self.composition_manifest.manifest_ref,
        )

    def inspect(
        self,
        pointer: ExecutionInvocationBundlePointer,
    ) -> HistoricalExecutionInvocationBundleV2 | ExecutionInvocationBundle:
        """Read and validate exact stored bytes without making them executable."""

        _require_exact_type(
            pointer,
            ExecutionInvocationBundlePointer,
            "execution invocation bundle pointer",
        )
        checked_pointer = ExecutionInvocationBundlePointer.model_validate(
            pointer.model_dump(mode="json", by_alias=True)
        )
        manifest_address = ContentAddress(
            ref=self.composition_manifest.manifest_ref,
            sha256=self.composition_manifest.manifest_hash,
        )
        if checked_pointer.composition_manifest != manifest_address:
            raise ExecutionAdmissionError(
                "execution_invocation_composition_manifest_mismatch",
                "resolve the bundle through its exact installed composition",
                checked_pointer.composition_manifest.ref,
            )
        path = self._object_path(checked_pointer.canonical_bytes.sha256)
        content = self._read_private(path)
        if content is None:
            raise ExecutionAdmissionError(
                "execution_invocation_bundle_missing",
                "restore the exact immutable invocation object before execution",
                str(path),
            )
        if _sha256(content) != checked_pointer.canonical_bytes.sha256:
            raise ExecutionAdmissionError(
                "execution_invocation_bundle_storage_hash_mismatch",
                "restore or quarantine the corrupted invocation object",
                str(path),
            )
        try:
            payload = _load_private_manifest_payload(path, content=content)
        except LifecycleTransitionError as exc:
            reason_code = (
                "execution_invocation_bundle_noncanonical"
                if exc.reason_code == "transition_manifest_noncanonical"
                else "execution_invocation_bundle_malformed"
            )
            raise ExecutionAdmissionError(
                reason_code,
                "restore the exact canonical ASCII invocation object",
                f"{exc.reason_code}:{path}",
            ) from exc
        try:
            bundle = parse_execution_invocation_bundle_record(payload)
        except (ExecutionAdmissionError, ValueError) as exc:
            raise ExecutionAdmissionError(
                "execution_invocation_bundle_invalid",
                "restore a structurally complete self-hashed invocation bundle",
                str(path),
            ) from exc
        if checked_pointer.bundle != ContentAddress(
            ref=bundle.bundle_ref, sha256=bundle.bundle_hash
        ):
            raise ExecutionAdmissionError(
                "execution_invocation_bundle_semantic_address_mismatch",
                "resolve the pointer's exact semantic invocation bundle",
                str(path),
            )
        if bundle.composition_manifest != manifest_address:
            raise ExecutionAdmissionError(
                "execution_invocation_bundle_composition_mismatch",
                "restore the bundle created for the installed composition manifest",
                bundle.composition_manifest.ref,
            )
        if _execution_invocation_bundle_bytes(bundle) != content:
            raise ExecutionAdmissionError(
                "execution_invocation_bundle_noncanonical",
                "restore the exact canonical invocation bundle bytes",
                str(path),
            )
        return bundle

    def resolve(
        self,
        pointer: ExecutionInvocationBundlePointer,
    ) -> ExecutionInvocationBundle:
        bundle = self.inspect(pointer)
        if isinstance(bundle, HistoricalExecutionInvocationBundleV2):
            raise ExecutionAdmissionError(
                "execution_invocation_bundle_history_only",
                "inspect historical v2 bytes but rebuild an active v3 invocation before execution",
                bundle.bundle_ref,
            )
        return bundle


@dataclass(frozen=True)
class ExecutionCompositionRoot:
    """Frozen installation composition; the checked-in default is dormant."""

    composition_manifest: ExecutionCompositionManifest | None = None
    invocation_store: ExecutionInvocationBundleStore | None = None
    claim_vault_root: Path | None = None
    claim_cache_dir: Path | None = None
    claim_transaction_root: Path | None = None
    claim_receipt_root: Path | None = None
    claim_lock_root: Path | None = None
    ports: ExecutionCompositionPorts | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "claim_vault_root",
            "claim_cache_dir",
            "claim_transaction_root",
            "claim_receipt_root",
            "claim_lock_root",
        ):
            value = getattr(self, field_name)
            if value is None:
                continue
            _require_exact_type(value, type(Path()), f"composition {field_name}")
            object.__setattr__(
                self,
                field_name,
                _bounded_absolute_path(value, label=field_name),
            )
        installed = (
            self.composition_manifest is not None,
            self.invocation_store is not None,
            self.ports is not None,
        )
        if any(installed) and not all(installed):
            raise ValueError(
                "composition manifest, invocation store, and ports must be installed together"
            )
        if self.composition_manifest is None:
            return
        _require_exact_type(
            self.composition_manifest,
            ExecutionCompositionManifest,
            "execution composition manifest",
        )
        _require_exact_type(
            self.invocation_store,
            ExecutionInvocationBundleStore,
            "execution invocation bundle store",
        )
        _require_exact_type(
            self.ports,
            ExecutionCompositionPorts,
            "execution composition ports",
        )
        manifest = ExecutionCompositionManifest.model_validate(
            self.composition_manifest.model_dump(mode="json", by_alias=True)
        )
        object.__setattr__(self, "composition_manifest", manifest)
        if self.invocation_store is None:  # pragma: no cover - paired above
            raise AssertionError("composition store disappeared")
        if self.ports is None:  # pragma: no cover - paired above
            raise AssertionError("composition ports disappeared")
        if self.invocation_store.composition_manifest != manifest:
            raise ValueError("composition store manifest differs from root manifest")
        if self.ports.descriptors != manifest.port_descriptors:
            raise ValueError("composition projection ports differ from manifest descriptors")
        expected_paths = (
            manifest.claim_vault_root,
            manifest.claim_cache_dir,
            manifest.claim_transaction_root,
            manifest.claim_receipt_root,
            manifest.claim_lock_root,
        )
        observed_paths = tuple(
            None if item is None else str(item)
            for item in (
                self.claim_vault_root,
                self.claim_cache_dir,
                self.claim_transaction_root,
                self.claim_receipt_root,
                self.claim_lock_root,
            )
        )
        if observed_paths != expected_paths:
            raise ValueError("composition claim roots differ from installed manifest")

    @property
    def activation_generation(self) -> ContentAddress | None:
        if self.composition_manifest is None:
            return None
        return self.composition_manifest.activation_generation

    def _claim_roots(self) -> tuple[Path, Path, Path, Path, Path]:
        roots = (
            self.claim_vault_root,
            self.claim_cache_dir,
            self.claim_transaction_root,
            self.claim_receipt_root,
            self.claim_lock_root,
        )
        if any(item is None for item in roots):
            raise ExecutionAdmissionError(
                "execution_composition_claim_roots_unavailable",
                "install every trusted claim resolution root before bundle resolution",
            )
        for item in roots:
            _require_exact_type(item, type(Path()), "execution composition claim root")
        return tuple(_normalized_path(item) for item in roots if item is not None)  # type: ignore[return-value]

    def require_composition_ports(self) -> ExecutionCompositionPorts:
        _require_exact_type(self, ExecutionCompositionRoot, "execution composition root")
        if self.composition_manifest is None or self.ports is None:
            raise ExecutionAdmissionError(
                "execution_composition_unavailable",
                "install one exact composition manifest and projection port catalog",
            )
        manifest = ExecutionCompositionManifest.model_validate(
            _require_exact_type(
                self.composition_manifest,
                ExecutionCompositionManifest,
                "execution composition manifest",
            ).model_dump(mode="json", by_alias=True)
        )
        ports = _seal_execution_composition_ports(
            _require_exact_type(
                self.ports,
                ExecutionCompositionPorts,
                "execution composition ports",
            )
        )
        if ports.descriptors != manifest.port_descriptors:
            raise ExecutionAdmissionError(
                "execution_composition_ports_mismatch",
                "bind projection ports to the exact installed composition manifest",
            )
        return ports

    def require_bundle_resolution(self) -> ExecutionInvocationBundleStore:
        _require_exact_type(self, ExecutionCompositionRoot, "execution composition root")
        if self.composition_manifest is None or self.invocation_store is None:
            raise ExecutionAdmissionError(
                "execution_composition_unavailable",
                "install one exact composition manifest and immutable invocation store",
            )
        manifest = ExecutionCompositionManifest.model_validate(
            _require_exact_type(
                self.composition_manifest,
                ExecutionCompositionManifest,
                "execution composition manifest",
            ).model_dump(mode="json", by_alias=True)
        )
        supplied_store = _require_exact_type(
            self.invocation_store,
            ExecutionInvocationBundleStore,
            "execution invocation bundle store",
        )
        store = ExecutionInvocationBundleStore(
            root=supplied_store.root,
            composition_manifest=supplied_store.composition_manifest,
        )
        if store.composition_manifest != manifest:
            raise ExecutionAdmissionError(
                "execution_composition_manifest_mismatch",
                "bind the invocation store to the exact composition manifest",
            )
        self._claim_roots()
        self.require_composition_ports()
        return store

    def require_effect_activation(self) -> None:
        """Gate-0A has no authority to validate or activate an installed generation."""

        detail = (
            "composition-uninstalled"
            if self.composition_manifest is None
            else self.composition_manifest.manifest_ref
        )
        raise ExecutionAdmissionError(
            "execution_composition_activation_unvalidated",
            "obtain a Gate-0B validated install receipt before any effect path",
            detail,
        )

    def persist_invocation(
        self,
        invocation: ExecutionInvocationContext,
    ) -> ExecutionInvocationBundlePointer:
        """Gate-0A HOLD: persistence is an effect and requires activated dispatch."""

        del invocation
        self.require_effect_activation()
        raise AssertionError("effect activation unexpectedly returned")  # pragma: no cover

    def resolve_structural_invocation(
        self,
        pointer: ExecutionInvocationBundlePointer,
        *,
        queried_at: str | datetime,
    ) -> ExecutionInvocationContext:
        """Rebuild the admitted bundle without asserting runtime effect readiness."""

        store = self.require_bundle_resolution()
        ports = self.require_composition_ports()
        vault, cache, transactions, receipts, locks = self._claim_roots()
        bundle = store.resolve(pointer)
        if isinstance(bundle.claim_basis, ProspectiveClaimPublicationBasis):
            from shared.sdlc_task_store import resolve_task_note

            if bundle.prospective_claim is None:
                raise ExecutionAdmissionError(
                    "prospective_claim_carrier_missing",
                    "restore the exact path-free publication carrier",
                    bundle.bundle_ref,
                )
            task = resolve_task_note(
                vault,
                bundle.execution_lease.task_ref,
                require_no_other_state=True,
            )
            current_task_note = ContentAddress(ref=str(task.path), sha256=task.sha256)
            if task.frontmatter.get("claimable") is not True:
                raise ExecutionAdmissionError(
                    "prospective_claim_not_claimable",
                    "advance the S0 task through a lawful claimable lifecycle projection",
                    task.task_id,
                )
            if not _private_file_is_absent(
                receipts / f"{bundle.claim_basis.dispatch_binding_receipt_hash}.json"
            ):
                raise ExecutionAdmissionError(
                    "prospective_claim_already_published",
                    "reconcile the exact existing publication receipt",
                    task.task_id,
                )
            claim_resolution: ProspectiveClaimResolution | AppliedClaimResolution = (
                ProspectiveClaimResolution(
                    vault_root=vault,
                    cache_dir=cache,
                    transaction_root=transactions,
                    receipt_root=receipts,
                    lock_root=locks,
                    carrier=bundle.prospective_claim,
                    current_task_note=current_task_note,
                )
            )
        else:
            claim_resolution = AppliedClaimResolution(
                vault_root=vault,
                cache_dir=cache,
                role=bundle.claim_role,
                session_id=bundle.execution_lease.session_ref,
                task_id=bundle.execution_lease.task_ref,
                transaction_root=transactions,
                receipt_root=receipts,
                lock_root=locks,
                outcome_committer=ports.outcomes,
            )
            live = claim_resolution.resolve_basis(queried_at=queried_at)
            if (
                live.ownership != bundle.claim_basis
                or live.current_task_note != bundle.execution_admission.task_note
                or bundle.execution_target.host_scoped_claim
                != _current_claim_position_address(live.current_position)
            ):
                raise ExecutionAdmissionError(
                    "execution_invocation_live_claim_mismatch",
                    "rebuild the bundle from the exact current claim position",
                    bundle.execution_lease.task_ref,
                )
        invocation = ExecutionInvocationContext(
            lease=bundle.execution_lease,
            admission=bundle.execution_admission,
            intent=bundle.action_intent,
            grant=bundle.authority_grant,
            claim_resolution=claim_resolution,
            frame=bundle.context_frame,
            trace=bundle.epistemic_trace,
            target=bundle.execution_target,
            route_decision=bundle.route_decision,
            effect_manifest=bundle.effect_manifest,
            executor_descriptor=bundle.executor_descriptor,
            executor_registry_projection=bundle.executor_registry_projection,
            protected_request=bundle.protected_action_request,
            aperture_decision=bundle.aperture_decision,
            claim_coordinates=bundle.claim_coordinates,
            ports=ports,
        )
        invocation.require_admitted(queried_at=queried_at)
        rebuilt = project_execution_invocation_context(
            invocation.protected_request,
            invocation.aperture_decision,
            invocation.claim_coordinates,
            invocation,
            queried_at=queried_at,
        )
        if rebuilt != bundle.invocation_envelope:
            raise ExecutionAdmissionError(
                "execution_invocation_envelope_reconstruction_mismatch",
                "restore the exact complete invocation bundle",
                bundle.bundle_ref,
            )
        return invocation

    def resolve_invocation(
        self,
        pointer: ExecutionInvocationBundlePointer,
        *,
        queried_at: str | datetime,
    ) -> ExecutionInvocationContext:
        """Compatibility spelling for structural, non-activating resolution."""

        return self.resolve_structural_invocation(pointer, queried_at=queried_at)


DEFAULT_EXECUTION_COMPOSITION_ROOT = ExecutionCompositionRoot()


def _build_protected_action_decision(
    request: ProtectedActionRequest,
    *,
    checked_at: str | datetime,
    disposition: Literal["hold", "dispatch_to_executor"],
    invocation_envelope: ExecutionInvocationEnvelope | None = None,
    currentness_query: ExecutionCurrentnessQuery | None = None,
    currentness_envelope: ExecutionCurrentnessEnvelope | None = None,
    readiness_query: OutcomePipelineReadinessQuery | None = None,
    readiness_envelope: OutcomePipelineReadinessEnvelope | None = None,
    executor_descriptor: ContentAddress | None = None,
    reason_codes: Sequence[str] = (),
) -> ProtectedActionDecision:
    reasons = tuple(sorted(set(reason_codes)))
    body: dict[str, object] = {
        "schema": PROTECTED_ACTION_DECISION_SCHEMA,
        "request": ContentAddress(ref=request.request_ref, sha256=request.request_hash),
        "invocation_envelope": (
            None
            if invocation_envelope is None
            else ContentAddress(
                ref=invocation_envelope.envelope_ref,
                sha256=invocation_envelope.envelope_hash,
            )
        ),
        "disposition": disposition,
        "currentness_query": (
            None
            if currentness_query is None
            else ContentAddress(
                ref=currentness_query.query_ref,
                sha256=currentness_query.query_hash,
            )
        ),
        "currentness_envelope": (
            None
            if currentness_envelope is None
            else ContentAddress(
                ref=currentness_envelope.envelope_ref,
                sha256=currentness_envelope.envelope_hash,
            )
        ),
        "outcome_readiness_query": (
            None
            if readiness_query is None
            else ContentAddress(ref=readiness_query.query_ref, sha256=readiness_query.query_hash)
        ),
        "outcome_readiness_envelope": (
            None
            if readiness_envelope is None
            else ContentAddress(
                ref=readiness_envelope.envelope_ref,
                sha256=readiness_envelope.envelope_hash,
            )
        ),
        "executor_descriptor": executor_descriptor,
        "checked_at": _canonical_timestamp(checked_at),
        "reason_codes": reasons,
        "repair_refs": tuple(f"repair:{item}" for item in reasons),
        "may_authorize": False,
        "authorizes_direct_fallthrough": False,
    }
    digest = _self_hash(PROTECTED_ACTION_DECISION_SCHEMA, body)
    return ProtectedActionDecision.model_validate(
        {
            **body,
            "decision_ref": f"protected-action-decision@sha256:{digest}",
            "decision_hash": digest,
        }
    )


def evaluate_protected_action(
    request: ProtectedActionRequest,
    aperture: ProtectedApertureDecision,
    claim: ProtectedClaimCoordinates,
    invocation: ExecutionInvocationContext | None = None,
    *,
    now: str | datetime | None = None,
) -> ProtectedActionDecision:
    """Evaluate ingress proofs without authorizing the caller to run an effect body."""

    _require_exact_type(request, ProtectedActionRequest, "protected action request")
    checked_at = _canonical_timestamp(now or _utc_now())
    checked_request = ProtectedActionRequest.model_validate(
        request.model_dump(mode="json", by_alias=True)
    )
    if invocation is None:
        return _build_protected_action_decision(
            checked_request,
            checked_at=checked_at,
            disposition="hold",
            reason_codes=("execution_admission_prerequisites_unavailable",),
        )
    _require_exact_type(invocation, ExecutionInvocationContext, "execution invocation context")
    try:
        projected = project_execution_invocation_context(
            checked_request,
            aperture,
            claim,
            invocation,
            queried_at=checked_at,
        )
        lease, current_query, current_envelope = invocation.require_current(queried_at=checked_at)
        ports = invocation.require_composition_ports()
        readiness_query, readiness_envelope = require_outcome_pipeline_ready(
            lease,
            current_query,
            current_envelope,
            queried_at=checked_at,
            completion_evaluator=ports.completion,
            outcome_committer=ports.outcomes,
            readiness_resolver=ports.readiness,
        )
        binding = ports.executors.resolve(
            lease,
            current_query,
            current_envelope,
        )
    except (ExecutionAdmissionError, ExecutionExecutorError, ValueError) as exc:
        return _build_protected_action_decision(
            checked_request,
            checked_at=checked_at,
            disposition="hold",
            reason_codes=(getattr(exc, "reason_code", "protected_action_input_invalid"),),
        )
    return _build_protected_action_decision(
        checked_request,
        checked_at=checked_at,
        disposition="dispatch_to_executor",
        invocation_envelope=projected,
        currentness_query=current_query,
        currentness_envelope=current_envelope,
        readiness_query=readiness_query,
        readiness_envelope=readiness_envelope,
        executor_descriptor=binding.key,
    )


def execution_admission_schema() -> Mapping[str, Any]:
    schema = TypeAdapter(
        EffectManifest
        | ProtectedApertureDecision
        | ProspectiveClaimPublicationBasis
        | ProspectiveClaimPublicationCarrier
        | ProtectedClaimCoordinates
        | ProtectedActionRequest
        | ExecutionInvocationEnvelope
        | ExecutionCompositionPortDescriptors
        | ExecutionCompositionManifest
        | ExecutionInvocationBundle
        | ExecutionInvocationBundlePointer
        | ProtectedActionHold
        | ProtectedActionDecision
        | ExecutionTrustQuery
        | ExecutionTrustEnvelope
        | ExecutorDescriptor
        | ExecutorRegistryProjection
        | ExecutionCurrentnessQuery
        | ExecutionCurrentnessEnvelope
        | FrontierValidityEnvelope
        | ActionIntent
        | AuthorityEvidence
        | ValidAuthorityGrant
        | AuthorityHold
        | AppliedClaimOwnershipProof
        | ClaimPublicationCompletionEvidence
        | CurrentClaimPosition
        | DependencyClosureEvidence
        | QuotaReservationEvidence
        | ExecutionTargetEvidence
        | ExecutionAdmission
        | BoundExecutionCall
        | ExecutionLease
        | EffectObservation
        | CompletionEvaluationQuery
        | CompletionEvaluation
        | OutcomePipelineReadinessQuery
        | OutcomePipelineReadinessEnvelope
        | OutcomeEvent
        | EventAppendReceipt
        | OutcomeReceipt
        | OutcomeProjectionSnapshot
        | OutcomeReplayCatalogSnapshot
        | OutcomeReplayResult
    ).json_schema(by_alias=True, ref_template="#/$defs/{model}")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        **schema,
    }


def require_protected_action(
    request: ProtectedActionRequest | str,
    aperture: ProtectedApertureDecision | None = None,
    claim: ProtectedClaimCoordinates | None = None,
    invocation: ExecutionInvocationContext | None = None,
) -> None:
    """Refuse direct fall-through; effects must be invoked by the bound executor.

    Gate-0A has no production invocation resolver. Even a caller holding an
    in-memory context must enter through the registry/outcome pipeline rather
    than treating this check as a Boolean authorization latch.
    """

    if not isinstance(request, ProtectedActionRequest):
        checked_operation = _nonblank(request)
        raise ExecutionAdmissionError(
            "execution_admission_prerequisites_unavailable",
            "resolve one exact ProtectedActionRequest and invoke through the executor pipeline",
            checked_operation,
        )
    if not isinstance(aperture, ProtectedApertureDecision) or not isinstance(
        claim, ProtectedClaimCoordinates
    ):
        raise ExecutionAdmissionError(
            "protected_action_components_unavailable",
            "resolve the exact aperture and claim coordinates for the protected request",
            request.request_ref,
        )
    decision = evaluate_protected_action(request, aperture, claim, invocation)
    if decision.disposition == "hold":
        raise ExecutionAdmissionError(
            decision.reason_codes[0],
            "hold the effect and resolve the complete current protected-action pipeline",
            request.request_ref,
        )
    raise ExecutionAdmissionError(
        "direct_protected_action_fallthrough_prohibited",
        "dispatch the evaluated request to the registry-bound executor and outcome pipeline",
        request.request_ref,
    )


__all__ = [
    "ActionIntent",
    "AdmittedClaimResolution",
    "AdmittedAppliedClaimProof",
    "AppliedClaimResolution",
    "AppliedClaimBasisResolution",
    "AppliedClaimOwnershipProof",
    "AppliedClaimProof",
    "AuthorityEvidence",
    "AuthorityHold",
    "BoundExecutionCall",
    "ContentAddress",
    "ClaimPublicationArtifact",
    "ClaimPublicationCompletionEvidence",
    "CurrentClaimLeaseFile",
    "CurrentClaimPosition",
    "CompletionEvaluation",
    "CompletionEvaluationQuery",
    "CompletionEvaluator",
    "DEFAULT_COMPLETION_EVALUATOR",
    "DEFAULT_EFFECT_MANIFEST_RESOLVER",
    "DEFAULT_EXECUTION_COMPOSITION_ROOT",
    "DEFAULT_EXECUTION_CURRENTNESS_RESOLVER",
    "DEFAULT_EXECUTION_TRUST_RESOLVER",
    "DEFAULT_EXECUTOR_REGISTRY",
    "DEFAULT_OUTCOME_COMMITTER",
    "DEFAULT_OUTCOME_PIPELINE_READINESS_RESOLVER",
    "DependencyClosureEvidence",
    "ExecutionAdmission",
    "ExecutionAdmissionError",
    "ExecutionCurrentnessEnvelope",
    "ExecutionCurrentnessQuery",
    "ExecutionCurrentnessResolver",
    "FrontierValidityEnvelope",
    "ExecutionCompositionRoot",
    "ExecutionCompositionManifest",
    "ExecutionCompositionPorts",
    "ExecutionCompositionPortDescriptors",
    "ExecutionExecutorBinding",
    "ExecutionExecutorError",
    "ExecutionExecutorRegistry",
    "ExecutionLease",
    "HistoricalExecutionLeaseV1",
    "ExecutionInvocationContext",
    "ExecutionInvocationBundle",
    "ExecutionInvocationBundlePointer",
    "ExecutionInvocationBundleStore",
    "ExecutionInvocationEnvelope",
    "ExecutionTargetEvidence",
    "ExecutionTrustResolver",
    "ExecutionTrustEnvelope",
    "ExecutionTrustQuery",
    "EffectManifest",
    "EffectManifestResolver",
    "EffectObservation",
    "ExecutorDescriptor",
    "ExecutorRegistryProjection",
    "HistoricalAppliedClaimOwnershipProofV3",
    "HistoricalBoundExecutionCallV1",
    "HistoricalExecutionInvocationBundleV2",
    "HistoricalExecutionInvocationEnvelopeV1",
    "OutcomeCommitter",
    "OutcomeReplayCatalogSnapshot",
    "OutcomeReplayResult",
    "OutcomeEvent",
    "EventAppendReceipt",
    "OutcomePipelineReadinessEnvelope",
    "OutcomePipelineReadinessQuery",
    "OutcomePipelineReadinessResolver",
    "OutcomeReceipt",
    "OutcomeProjectionSnapshot",
    "ProtectedActionDecision",
    "ProtectedActionHold",
    "ProtectedActionRequest",
    "ProtectedApertureDecision",
    "ProtectedClaimCoordinates",
    "ProspectiveClaimPublicationBasis",
    "ProspectiveClaimPublicationCarrier",
    "ProspectiveClaimResolution",
    "QuotaReservationEvidence",
    "HistoricalProtectedClaimCoordinatesV1",
    "HistoricalExecutionLeaseV2",
    "HistoricalSupportDisposition",
    "RootDisposition",
    "ValidAuthorityGrant",
    "admit_execution",
    "applied_claim_proof",
    "applied_claim_ownership_proof",
    "build_action_intent",
    "build_authority_evidence",
    "build_bound_execution_call",
    "build_completion_evaluation_query",
    "build_completion_evaluation",
    "build_claim_publication_completion_evidence",
    "build_current_claim_position",
    "build_dependency_closure_evidence",
    "build_execution_target_evidence",
    "build_execution_currentness_envelope",
    "build_frontier_validity_envelope",
    "build_execution_composition_manifest",
    "build_execution_composition_port_descriptors",
    "build_execution_invocation_bundle",
    "build_execution_invocation_bundle_pointer",
    "build_execution_trust_query",
    "build_execution_trust_envelope",
    "build_execution_lease_issuer_trust_query",
    "build_effect_manifest",
    "build_effect_observation",
    "build_execution_currentness_query",
    "build_executor_descriptor",
    "build_executor_registry_projection",
    "build_outcome_event",
    "build_outcome_pipeline_readiness_query",
    "build_outcome_pipeline_readiness_envelope",
    "build_event_append_receipt",
    "build_outcome_receipt",
    "build_outcome_projection_snapshot",
    "build_outcome_replay_catalog_snapshot",
    "build_quota_reservation_evidence",
    "build_protected_action_hold",
    "build_protected_action_request",
    "build_protected_aperture_decision",
    "build_protected_claim_coordinates",
    "build_prospective_claim_publication_basis",
    "build_prospective_claim_publication_carrier",
    "content_address",
    "claim_publication_effect_evidence_refs",
    "execution_admission_schema",
    "execution_composition_manifest_bytes",
    "evaluate_completion",
    "evaluate_protected_action",
    "mint_execution_lease",
    "module_file_address",
    "parse_applied_claim_ownership_record",
    "parse_bound_execution_call_record",
    "parse_execution_lease_record",
    "parse_execution_invocation_bundle_record",
    "parse_execution_invocation_envelope_record",
    "parse_protected_claim_coordinates_record",
    "outcome_projection_validity_roots",
    "project_execution_invocation_context",
    "protected_raw_invocation_address",
    "require_admitted_applied_claim_proof",
    "require_applied_claim_ownership_proof",
    "require_admitted_execution_lease",
    "require_current_execution_lease",
    "require_outcome_pipeline_ready",
    "require_protected_action",
    "validate_authority",
]


def _strict_cli_json(raw: bytes) -> dict[str, object]:
    def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        output: dict[str, object] = {}
        for key, value in pairs:
            if key in output:
                raise ValueError(f"duplicate key: {key}")
            output[key] = value
        return output

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON value: {value}")

    value = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=unique_pairs,
        parse_constant=reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("protected ingress transport must be one JSON object")
    return value


def _emit_transport_hold(raw: bytes) -> int:
    raw_bytes_hash = _sha256(raw)
    raw_address = ContentAddress(
        ref=f"protected-raw-bytes@sha256:{raw_bytes_hash}",
        sha256=raw_bytes_hash,
    )
    operation = "unknown"
    surface = "unknown"
    ingress_module: ContentAddress | None = None
    reasons = ["execution_admission_prerequisites_unavailable"]
    try:
        payload = _strict_cli_json(raw)
        operation = _nonblank(str(payload.get("operation") or "unknown"))
        surface = _nonblank(str(payload.get("ingress_surface") or "unknown"))
        raw_invocation = payload.get("raw_invocation")
        if isinstance(raw_invocation, dict | list):
            raw_address = protected_raw_invocation_address(raw_invocation)
        else:
            reasons.append("protected_raw_invocation_missing")
        ingress_path = payload.get("ingress_module_path")
        if isinstance(ingress_path, str) and ingress_path:
            ingress_module = module_file_address(Path(ingress_path))
        else:
            reasons.append("protected_ingress_module_missing")
    except (OSError, TypeError, ValueError, json.JSONDecodeError, UnicodeError):
        reasons.append("protected_ingress_transport_malformed")
    admission_module = module_file_address(Path(__file__))
    hold = build_protected_action_hold(
        raw_invocation=raw_address,
        operation=operation,
        ingress_surface=surface,
        ingress_module=ingress_module,
        admission_module=admission_module,
        checked_at=_utc_now(),
        reason_codes=tuple(sorted(set(reasons))),
    )
    print(
        json.dumps(
            hold.model_dump(mode="json", by_alias=True),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 10


def _main(argv: Sequence[str]) -> int:
    if not argv:
        print(json.dumps(execution_admission_schema(), ensure_ascii=True, indent=2, sort_keys=True))
        return 0
    if argv[0] == "verify-protected-action":
        operation = argv[1] if len(argv) > 1 else "unknown"
        raw = json.dumps(
            {
                "ingress_surface": "compatibility",
                "operation": operation,
                "raw_invocation": {"argv": list(argv)},
            },
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        return _emit_transport_hold(raw)
    if argv[0] == "execute-protected-action" and len(argv) == 1:
        return _emit_transport_hold(sys.stdin.buffer.read())
    print(
        "usage: python -m shared.execution_admission "
        "[execute-protected-action|verify-protected-action OPERATION]"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
