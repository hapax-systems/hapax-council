"""Closed, universal, non-authorizing carrier for governed dispatch intake."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping

METHODOLOGY_DISPATCH_CARRIER_SCHEMA = "hapax.methodology-dispatch-carrier.v1"
METHODOLOGY_DISPATCH_CARRIER_HASH_BASIS = "canonical-json-without-carrier-ref-and-carrier-hash"
DISPATCH_CORRELATION_SCHEMA = "hapax.dispatch-correlation.v1"
DISPATCH_SUPPORT_FACT_SCHEMA = "hapax.dispatch-support-fact.v1"

_IDENTITY_FIELDS = ("task_id", "lane", "platform", "mode", "profile")
_RESERVED_FIELDS = frozenset({"carrier_hash", "carrier_ref"})
_ALLOWED_TOP_LEVEL_FIELDS = frozenset(
    {
        "carrier_hash",
        "carrier_hash_basis",
        "carrier_ref",
        "correlation",
        "created_at",
        "effect_state",
        "event",
        "lane",
        "launched",
        "materialization_state",
        "may_authorize",
        "mode",
        "platform",
        "profile",
        "receipt_is_admission",
        "requested_operation",
        "schema",
        "schema_version",
        "support",
        "task_id",
    }
)
_CORRELATION_FIELDS = frozenset({"schema", "mq_message_id", "idempotency_key"})
_SUPPORT_FACT_FIELDS = frozenset(
    {
        "claim_ceiling",
        "code",
        "freshness_state",
        "kind",
        "loss_state",
        "observed_at",
        "schema",
        "source_ref",
        "source_sha256",
        "value",
        "value_type",
    }
)
_SUPPORT_KINDS = frozenset({"candidate", "diagnostic", "evidence"})
_FRESHNESS_STATES = frozenset({"current", "stale", "unknown", "not_applicable"})
_LOSS_STATES = frozenset({"lossless", "bounded", "unknown"})
_VALUE_TYPES = frozenset({"null", "bool", "integer", "decimal", "string", "scalar_list"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._:-]{0,255}$", re.ASCII)
_OPERATION_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$", re.ASCII)
_MAX_RAW_BYTES = 262_144
_MAX_SUPPORT_FACTS = 128
_MAX_SCALAR_LIST_ITEMS = 128
_MAX_JSON_DEPTH = 32
_MAX_CONTAINER_MEMBERS = 4_096
_MAX_JSON_NODES = 16_384

# Closed semantic vocabulary. Each support code fixes its permitted epistemic
# kind and scalar representation; code-name membership alone is insufficient.
_EVIDENCE = frozenset({"evidence"})
_CANDIDATE = frozenset({"candidate"})
_DIAGNOSTIC = frozenset({"diagnostic"})
_CANDIDATE_OR_DIAGNOSTIC = frozenset({"candidate", "diagnostic"})
_NULL = frozenset({"null"})
_BOOL = frozenset({"bool"})
_INTEGER = frozenset({"integer"})
_STRING = frozenset({"string"})
_OPTIONAL_STRING = frozenset({"null", "string"})
_STRING_LIST = frozenset({"scalar_list"})

_SUPPORT_CODE_CONTRACTS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "capacity.invariant": (_EVIDENCE, _STRING),
    "capability.blocker_reasons": (_DIAGNOSTIC, _STRING_LIST),
    "capability.checked_at": (_EVIDENCE, _OPTIONAL_STRING),
    "capability.evidence_refs": (_EVIDENCE, _STRING_LIST),
    "capability.name": (_EVIDENCE, _STRING),
    "capability.reason": (_DIAGNOSTIC, _STRING),
    "capability.route_id": (_EVIDENCE, _STRING),
    "capability.state": (_CANDIDATE, _STRING),
    "canon.binding": (_EVIDENCE, _NULL),
    "canon.failure_code": (_DIAGNOSTIC, _OPTIONAL_STRING),
    "canon.image_sha256": (_EVIDENCE, _STRING),
    "canon.payload_sha256": (_EVIDENCE, _STRING),
    "canon.position": (_EVIDENCE, _NULL),
    "canon.repair_action": (_DIAGNOSTIC, _OPTIONAL_STRING),
    "coord_dispatch.cleanup_state": (_DIAGNOSTIC, _OPTIONAL_STRING),
    "coord_dispatch.event_ref": (_EVIDENCE, _OPTIONAL_STRING),
    "coord_dispatch.reason": (_DIAGNOSTIC, _OPTIONAL_STRING),
    "coord_dispatch.replayed": (_EVIDENCE, _BOOL),
    "dimensional.candidate_count": (_EVIDENCE, _INTEGER),
    "dimensional.degraded_mode": (_DIAGNOSTIC, _BOOL),
    "dimensional.evidence_refs": (_EVIDENCE, _STRING_LIST),
    "dimensional.route_receipt_schema": (_EVIDENCE, _INTEGER),
    "dimensional.selected_route_id": (_CANDIDATE, _OPTIONAL_STRING),
    "durable_mq.advisory_only": (_EVIDENCE, _BOOL),
    "durable_mq.bound": (_EVIDENCE, _BOOL),
    "durable_mq.reason": (_DIAGNOSTIC, _STRING),
    "gate.candidate": (_CANDIDATE, frozenset({"null", "bool", "string"})),
    "prompt.bytes": (_DIAGNOSTIC, frozenset({"null", "integer"})),
    "prompt.sha256": (_EVIDENCE, _OPTIONAL_STRING),
    "request.advisory_only": (_CANDIDATE, _BOOL),
    "request.preview_only": (_CANDIDATE, _BOOL),
    "request.route_mode": (_CANDIDATE, _STRING),
    "request.route_platform": (_CANDIDATE, _STRING),
    "request.route_profile": (_CANDIDATE, _STRING),
    "route.decision": (_CANDIDATE, _STRING),
    "route.path_summary": (_EVIDENCE, _OPTIONAL_STRING),
    "route.target_host_candidate": (_CANDIDATE, _STRING),
    "route_policy.action": (_CANDIDATE, _STRING),
    "route_policy.authority_allowed": (_CANDIDATE, _BOOL),
    "route_policy.cloud_burst_eligible": (_CANDIDATE, _BOOL),
    "route_policy.cloud_burst_guard_reasons": (_DIAGNOSTIC, _STRING_LIST),
    "route_policy.cloud_burst_guard_state": (_DIAGNOSTIC, _STRING),
    "route_policy.cloud_burst_spike_reasons": (_DIAGNOSTIC, _STRING_LIST),
    "route_policy.clog_state": (_DIAGNOSTIC, _STRING),
    "route_policy.compatibility_mode": (_DIAGNOSTIC, _STRING),
    "route_policy.degraded_state": (_DIAGNOSTIC, _OPTIONAL_STRING),
    "route_policy.green": (_CANDIDATE, _BOOL),
    "route_policy.launch_allowed": (_CANDIDATE, _BOOL),
    "route_policy.outcome": (_CANDIDATE, _STRING),
    "route_policy.quality_floor_satisfied": (_EVIDENCE, _BOOL),
    "route_policy.quota_evidence_refs": (_EVIDENCE, _STRING_LIST),
    "route_policy.quota_freshness_green": (_EVIDENCE, _BOOL),
    "route_policy.reason_codes": (_DIAGNOSTIC, _STRING_LIST),
    "route_policy.registry_freshness_green": (_EVIDENCE, _BOOL),
    "route_policy.resource_freshness_green": (_EVIDENCE, _BOOL),
    "route_policy.route_selection_authority": (_CANDIDATE, _BOOL),
    "task.parent_spec": (_EVIDENCE, _NULL),
    "task.source": (_EVIDENCE, _NULL),
    "task.validation_state": (_CANDIDATE_OR_DIAGNOSTIC, _STRING),
    "validation.exempt_read_only": (_EVIDENCE, _BOOL),
    "validation.ok": (_EVIDENCE, _BOOL),
    "validation.reason": (_DIAGNOSTIC, _STRING),
}
REGISTERED_DISPATCH_SUPPORT_CODES = frozenset(_SUPPORT_CODE_CONTRACTS)

_STRING_LIST_CODES = frozenset(
    code
    for code, (_kinds, value_types) in _SUPPORT_CODE_CONTRACTS.items()
    if value_types == _STRING_LIST
)
_SHA_VALUE_CODES = frozenset({"canon.image_sha256", "canon.payload_sha256", "prompt.sha256"})

_GATE0A_INVARIANTS: dict[str, object] = {
    "effect_state": "held_not_admitted",
    "event": "methodology_dispatch",
    "launched": False,
    "materialization_state": "not_materialized",
    "may_authorize": False,
    "receipt_is_admission": False,
    "schema": METHODOLOGY_DISPATCH_CARRIER_SCHEMA,
    "schema_version": 1,
}


class MethodologyDispatchCarrierError(ValueError):
    """Typed refusal raised for an unsealed or semantically unsafe carrier."""

    def __init__(
        self,
        reason_code: str,
        repair_action: str,
        detail: str | None = None,
    ) -> None:
        self.reason_code = reason_code
        self.repair_action = repair_action
        self.detail = detail
        message = f"{reason_code}: {repair_action}"
        if detail:
            message += f" ({detail})"
        super().__init__(message)


def canonical_dispatch_carrier_bytes(value: object) -> bytes:
    """Encode exact canonical JSON without invoking user-provided serialization."""

    _require_bounded_builtin_json(value)
    try:
        rendered = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_noncanonical_value",
            "provide only finite canonical JSON values in the dispatch carrier",
        ) from exc
    encoded = rendered.encode("ascii")
    if len(encoded) > _MAX_RAW_BYTES:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_size_exceeded",
            "reduce the carrier to bounded intent, correlation, and support facts",
        )
    return encoded


def _require_bounded_builtin_json(value: object) -> None:
    stack: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES or depth > _MAX_JSON_DEPTH:
            raise MethodologyDispatchCarrierError(
                "dispatch_carrier_structure_exceeded",
                "reduce JSON depth and aggregate node count",
            )
        if item is None or type(item) in {bool, int, str}:
            continue
        if type(item) is float:
            if math.isfinite(item):
                continue
            raise MethodologyDispatchCarrierError(
                "dispatch_carrier_noncanonical_value",
                "provide only finite canonical JSON values in the dispatch carrier",
            )
        if type(item) is dict:
            if len(item) > _MAX_CONTAINER_MEMBERS:
                raise MethodologyDispatchCarrierError(
                    "dispatch_carrier_structure_exceeded",
                    "reduce JSON container membership",
                )
            for key, child in item.items():
                if type(key) is not str:
                    raise MethodologyDispatchCarrierError(
                        "dispatch_carrier_noncanonical_value",
                        "use exact string keys in built-in JSON objects",
                    )
                stack.append((child, depth + 1))
            continue
        if type(item) is list:
            if len(item) > _MAX_CONTAINER_MEMBERS:
                raise MethodologyDispatchCarrierError(
                    "dispatch_carrier_structure_exceeded",
                    "reduce JSON container membership",
                )
            stack.extend((child, depth + 1) for child in item)
            continue
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_noncanonical_value",
            "provide only exact built-in JSON values",
            type(item).__name__,
        )


def _detached_record(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_type_invalid",
            "provide one exact built-in dict carrier",
            type(value).__name__,
        )
    parsed = json.loads(canonical_dispatch_carrier_bytes(value))
    if type(parsed) is not dict:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_type_invalid",
            "provide one exact JSON object carrier",
        )
    return parsed


def _require_nonempty_string(value: object, *, pointer: str) -> str:
    if type(value) is not str or not value:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_field_invalid",
            "provide the required non-empty string",
            pointer,
        )
    return value


def _require_identity(record: Mapping[str, object]) -> None:
    for field in _IDENTITY_FIELDS:
        identity = _require_nonempty_string(record.get(field), pointer=f"/{field}")
        if _IDENTIFIER_RE.fullmatch(identity) is None:
            raise MethodologyDispatchCarrierError(
                "dispatch_carrier_identity_invalid",
                "use a bounded ASCII dispatch identifier without whitespace or controls",
                f"/{field}",
            )
    operation = _require_nonempty_string(
        record.get("requested_operation"), pointer="/requested_operation"
    )
    if _OPERATION_RE.fullmatch(operation) is None:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_operation_invalid",
            "use a lowercase namespaced operation identifier",
            "/requested_operation",
        )


def _unknown_fields(record: Mapping[str, object], allowed: frozenset[str], *, pointer: str) -> None:
    unknown = sorted(set(record).difference(allowed))
    if unknown:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_unknown_field",
            "remove fields outside the closed universal carrier schema",
            f"{pointer}/{unknown[0]}" if pointer else f"/{unknown[0]}",
        )


def _validate_correlation(value: object) -> None:
    if type(value) is not dict:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_correlation_invalid",
            "provide the closed typed correlation object",
            "/correlation",
        )
    _unknown_fields(value, _CORRELATION_FIELDS, pointer="/correlation")
    if value.get("schema") != DISPATCH_CORRELATION_SCHEMA:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_correlation_invalid",
            "bind the exact correlation schema",
            "/correlation/schema",
        )
    for field in ("mq_message_id", "idempotency_key"):
        item = value.get(field)
        if item is not None and (type(item) is not str or _IDENTIFIER_RE.fullmatch(item) is None):
            raise MethodologyDispatchCarrierError(
                "dispatch_carrier_correlation_invalid",
                "use null or a bounded ASCII correlation identifier",
                f"/correlation/{field}",
            )


def _actual_value_type(value: object) -> str | None:
    if value is None:
        return "null"
    if type(value) is bool:
        return "bool"
    if type(value) is int:
        return "integer"
    if type(value) is float:
        return "decimal"
    if type(value) is str:
        return "string"
    if type(value) is list and len(value) <= _MAX_SCALAR_LIST_ITEMS:
        if all(item is None or type(item) in {bool, int, float, str} for item in value):
            return "scalar_list"
    return None


def _validate_support_fact(value: object, *, index: int) -> None:
    pointer = f"/support/{index}"
    if type(value) is not dict:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_support_fact_invalid",
            "provide a closed typed scalar support fact",
            pointer,
        )
    _unknown_fields(value, _SUPPORT_FACT_FIELDS, pointer=pointer)
    if value.get("schema") != DISPATCH_SUPPORT_FACT_SCHEMA:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_support_fact_invalid",
            "bind the exact support-fact schema",
            f"{pointer}/schema",
        )
    if value.get("kind") not in _SUPPORT_KINDS:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_support_fact_invalid",
            "use evidence, diagnostic, or candidate support kind",
            f"{pointer}/kind",
        )
    code = value.get("code")
    if code not in REGISTERED_DISPATCH_SUPPORT_CODES:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_support_code_unregistered",
            "register and validate the support code before carriage",
            f"{pointer}/code",
        )
    value_type = value.get("value_type")
    if value_type not in _VALUE_TYPES or _actual_value_type(value.get("value")) != value_type:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_support_value_invalid",
            "bind a scalar value to its exact declared type",
            f"{pointer}/value",
        )
    allowed_kinds, allowed_value_types = _SUPPORT_CODE_CONTRACTS[code]
    if value.get("kind") not in allowed_kinds or value_type not in allowed_value_types:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_support_contract_invalid",
            "bind the registered support code to its exact epistemic kind and scalar type",
            f"{pointer}/code",
        )
    support_value = value.get("value")
    if code in _STRING_LIST_CODES and (
        type(support_value) is not list or any(type(item) is not str for item in support_value)
    ):
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_support_contract_invalid",
            "use a homogeneous string list for this registered support code",
            f"{pointer}/value",
        )
    if (
        code in _SHA_VALUE_CODES
        and support_value is not None
        and (type(support_value) is not str or _SHA256_RE.fullmatch(support_value) is None)
    ):
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_support_contract_invalid",
            "use a lowercase SHA-256 value for this registered support code",
            f"{pointer}/value",
        )
    if code == "route_policy.route_selection_authority" and support_value is not False:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_support_contract_invalid",
            "keep route selection authority explicitly false in support carriage",
            f"{pointer}/value",
        )
    if value.get("claim_ceiling") != "support_non_authoritative":
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_support_ceiling_invalid",
            "fix every support fact at the non-authorizing claim ceiling",
            f"{pointer}/claim_ceiling",
        )
    if value.get("freshness_state") not in _FRESHNESS_STATES:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_support_fact_invalid",
            "declare a supported freshness state",
            f"{pointer}/freshness_state",
        )
    if value.get("loss_state") not in _LOSS_STATES:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_support_fact_invalid",
            "declare lossless, bounded, or unknown support loss",
            f"{pointer}/loss_state",
        )
    for field in ("source_ref", "observed_at"):
        item = value.get(field)
        if item is not None and (type(item) is not str or not item):
            raise MethodologyDispatchCarrierError(
                "dispatch_carrier_support_fact_invalid",
                "use null or a non-empty support provenance string",
                f"{pointer}/{field}",
            )
    source_sha256 = value.get("source_sha256")
    if source_sha256 is not None and (
        type(source_sha256) is not str or _SHA256_RE.fullmatch(source_sha256) is None
    ):
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_support_fact_invalid",
            "use null or a lowercase SHA-256 source digest",
            f"{pointer}/source_sha256",
        )


def _require_closed_shape(record: Mapping[str, object]) -> None:
    _unknown_fields(record, _ALLOWED_TOP_LEVEL_FIELDS, pointer="")
    created_at = record.get("created_at")
    if created_at is not None and (type(created_at) is not str or not created_at):
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_field_invalid",
            "use null or a non-empty observation time",
            "/created_at",
        )
    if "correlation" in record:
        _validate_correlation(record["correlation"])
    support = record.get("support", [])
    if type(support) is not list or len(support) > _MAX_SUPPORT_FACTS:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_support_invalid",
            "provide a bounded list of typed support facts",
            "/support",
        )
    observed_codes: set[object] = set()
    ordered_codes: list[str] = []
    for index, fact in enumerate(support):
        _validate_support_fact(fact, index=index)
        assert isinstance(fact, dict)
        code = fact.get("code")
        if code in observed_codes:
            raise MethodologyDispatchCarrierError(
                "dispatch_carrier_support_code_duplicate",
                "emit one exact value per registered support code",
                f"/support/{index}/code",
            )
        observed_codes.add(code)
        assert isinstance(code, str)
        ordered_codes.append(code)
    if ordered_codes != sorted(ordered_codes):
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_support_order_invalid",
            "sort registered support facts by code",
            "/support",
        )


def _require_gate0a_invariants(record: Mapping[str, object]) -> None:
    for field, expected in _GATE0A_INVARIANTS.items():
        observed = record.get(field)
        if type(observed) is not type(expected) or observed != expected:
            raise MethodologyDispatchCarrierError(
                "dispatch_carrier_gate0a_invariant_invalid",
                "restore the exact non-authorizing, non-materialized Gate-0A carrier",
                field,
            )
    if record.get("carrier_hash_basis") != METHODOLOGY_DISPATCH_CARRIER_HASH_BASIS:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_hash_basis_invalid",
            "bind the canonical carrier hash basis",
        )


def build_dispatch_support_fact(
    *,
    kind: str,
    code: str,
    value: object,
    source_ref: str | None = None,
    source_sha256: str | None = None,
    observed_at: str | None = None,
    freshness_state: str = "not_applicable",
    loss_state: str = "lossless",
) -> dict[str, object]:
    """Build one closed scalar support fact at a fixed non-authorizing ceiling."""

    normalized_value = list(value) if type(value) is tuple else value
    value_type = _actual_value_type(normalized_value)
    if value_type is None:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_support_value_invalid",
            "carry complex support by content reference plus selected scalar facts",
            code,
        )
    fact: dict[str, object] = {
        "schema": DISPATCH_SUPPORT_FACT_SCHEMA,
        "kind": kind,
        "code": code,
        "value_type": value_type,
        "value": normalized_value,
        "source_ref": source_ref,
        "source_sha256": source_sha256,
        "observed_at": observed_at,
        "freshness_state": freshness_state,
        "claim_ceiling": "support_non_authoritative",
        "loss_state": loss_state,
    }
    _validate_support_fact(fact, index=0)
    return fact


def seal_methodology_dispatch_carrier(
    payload: dict[str, object],
) -> dict[str, object]:
    """Seal one universal Gate-0A carrier without materializing any effect."""

    record = _detached_record(payload)
    conflicts = sorted(_RESERVED_FIELDS.intersection(record))
    if conflicts:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_reserved_field_present",
            "remove precomputed carrier identity before sealing",
            ",".join(conflicts),
        )
    for field, expected in _GATE0A_INVARIANTS.items():
        if field in record:
            observed = record[field]
            if type(observed) is not type(expected) or observed != expected:
                raise MethodologyDispatchCarrierError(
                    "dispatch_carrier_gate0a_invariant_invalid",
                    "do not escalate authority or materialization while sealing intake",
                    field,
                )
        record[field] = expected
    record["carrier_hash_basis"] = METHODOLOGY_DISPATCH_CARRIER_HASH_BASIS
    _require_identity(record)
    support = record.get("support")
    if type(support) is list and all(
        type(fact) is dict and type(fact.get("code")) is str for fact in support
    ):
        record["support"] = sorted(support, key=lambda fact: fact["code"])
    _require_closed_shape(record)
    digest = hashlib.sha256(canonical_dispatch_carrier_bytes(record)).hexdigest()
    return {
        **record,
        "carrier_hash": digest,
        "carrier_ref": f"methodology-dispatch-carrier@sha256:{digest}",
    }


def validate_methodology_dispatch_carrier(
    value: object,
    *,
    task_id: str | None = None,
    lane: str | None = None,
    platform: str | None = None,
    mode: str | None = None,
    profile: str | None = None,
) -> dict[str, object]:
    """Rehash and identity-check one exact universal Gate-0A carrier."""

    record = _detached_record(value)
    _require_identity(record)
    carrier_hash = record.get("carrier_hash")
    carrier_ref = record.get("carrier_ref")
    if type(carrier_hash) is not str or type(carrier_ref) is not str:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_identity_missing",
            "restore the carrier hash and content-addressed reference",
        )
    body = {key: item for key, item in record.items() if key not in _RESERVED_FIELDS}
    observed_hash = hashlib.sha256(canonical_dispatch_carrier_bytes(body)).hexdigest()
    if (
        carrier_hash != observed_hash
        or carrier_ref != f"methodology-dispatch-carrier@sha256:{observed_hash}"
    ):
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_hash_mismatch",
            "restore the exact canonical carrier bytes and content address",
        )
    _require_gate0a_invariants(record)
    _require_closed_shape(record)
    expected_identity = {
        "task_id": task_id,
        "lane": lane,
        "platform": platform,
        "mode": mode,
        "profile": profile,
    }
    for field, expected in expected_identity.items():
        if expected is not None and record[field] != expected:
            raise MethodologyDispatchCarrierError(
                "dispatch_carrier_invocation_mismatch",
                "consume only the carrier bound to the exact dispatch invocation",
                field,
            )
    return record


def validate_methodology_dispatch_carrier_line(
    raw_line: bytes,
    **expected_identity: str | None,
) -> dict[str, object]:
    """Reject duplicate keys and noncanonical bytes before object validation."""

    if type(raw_line) is not bytes:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_raw_line_invalid",
            "provide one exact built-in bytes record",
        )
    if (
        not raw_line.endswith(b"\n")
        or not raw_line[:-1]
        or b"\n" in raw_line[:-1]
        or b"\r" in raw_line
    ):
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_raw_line_invalid",
            "provide exactly one canonical JSON carrier terminated by one LF",
        )
    if len(raw_line) > _MAX_RAW_BYTES + 1:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_size_exceeded",
            "reduce the carrier to bounded intent, correlation, and support facts",
        )
    payload = raw_line[:-1]
    try:
        raw_text = payload.decode("ascii")
    except UnicodeDecodeError as exc:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_raw_noncanonical",
            "encode the carrier as canonical ASCII JSON",
        ) from exc

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise MethodologyDispatchCarrierError(
                    "dispatch_carrier_duplicate_key",
                    "remove duplicate JSON object keys",
                    key,
                )
            result[key] = value
        return result

    try:
        parsed = json.loads(
            raw_text,
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                MethodologyDispatchCarrierError(
                    "dispatch_carrier_noncanonical_value",
                    "reject non-finite JSON constants",
                    value,
                )
            ),
        )
    except MethodologyDispatchCarrierError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_raw_json_invalid",
            "provide valid canonical JSON",
        ) from exc
    if canonical_dispatch_carrier_bytes(parsed) != payload:
        raise MethodologyDispatchCarrierError(
            "dispatch_carrier_raw_noncanonical",
            "use sorted compact canonical ASCII JSON bytes",
        )
    return validate_methodology_dispatch_carrier(parsed, **expected_identity)


__all__ = [
    "DISPATCH_CORRELATION_SCHEMA",
    "DISPATCH_SUPPORT_FACT_SCHEMA",
    "METHODOLOGY_DISPATCH_CARRIER_HASH_BASIS",
    "METHODOLOGY_DISPATCH_CARRIER_SCHEMA",
    "REGISTERED_DISPATCH_SUPPORT_CODES",
    "MethodologyDispatchCarrierError",
    "build_dispatch_support_fact",
    "canonical_dispatch_carrier_bytes",
    "seal_methodology_dispatch_carrier",
    "validate_methodology_dispatch_carrier",
    "validate_methodology_dispatch_carrier_line",
]
