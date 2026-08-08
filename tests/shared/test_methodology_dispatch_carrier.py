from __future__ import annotations

import hashlib

import pytest

from shared.methodology_dispatch_carrier import (
    METHODOLOGY_DISPATCH_CARRIER_SCHEMA,
    MethodologyDispatchCarrierError,
    build_dispatch_support_fact,
    canonical_dispatch_carrier_bytes,
    seal_methodology_dispatch_carrier,
    validate_methodology_dispatch_carrier,
    validate_methodology_dispatch_carrier_line,
)


def _payload() -> dict[str, object]:
    return {
        "event": "methodology_dispatch",
        "lane": "cx-green",
        "launched": False,
        "may_authorize": False,
        "mode": "headless",
        "platform": "codex",
        "profile": "full",
        "receipt_is_admission": False,
        "requested_operation": "launch",
        "support": [
            build_dispatch_support_fact(
                kind="candidate",
                code="route_policy.launch_allowed",
                value=True,
                freshness_state="current",
            )
        ],
        "task_id": "task-test",
    }


def _wire(carrier: dict[str, object]) -> bytes:
    return canonical_dispatch_carrier_bytes(carrier) + b"\n"


def _rehash(body: dict[str, object]) -> dict[str, object]:
    digest = hashlib.sha256(canonical_dispatch_carrier_bytes(body)).hexdigest()
    return {
        **body,
        "carrier_hash": digest,
        "carrier_ref": f"methodology-dispatch-carrier@sha256:{digest}",
    }


def test_shared_carrier_round_trips_with_exact_gate0a_invariants() -> None:
    carrier = seal_methodology_dispatch_carrier(_payload())

    assert carrier["schema"] == METHODOLOGY_DISPATCH_CARRIER_SCHEMA
    assert carrier["effect_state"] == "held_not_admitted"
    assert carrier["materialization_state"] == "not_materialized"
    assert carrier["may_authorize"] is False
    assert carrier["receipt_is_admission"] is False
    assert carrier["launched"] is False
    assert carrier["support"][0]["claim_ceiling"] == "support_non_authoritative"
    assert (
        validate_methodology_dispatch_carrier(
            carrier,
            task_id="task-test",
            lane="cx-green",
            platform="codex",
            mode="headless",
            profile="full",
        )
        == carrier
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("launched", True),
        ("may_authorize", True),
        ("receipt_is_admission", True),
        ("effect_state", "admitted"),
        ("materialization_state", "materialized"),
    ],
)
def test_shared_carrier_rejects_authority_or_materialization_escalation(
    field: str, value: object
) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises(
        MethodologyDispatchCarrierError,
        match="dispatch_carrier_gate0a_invariant_invalid",
    ):
        seal_methodology_dispatch_carrier(payload)


@pytest.mark.parametrize(
    "field",
    [
        "authority_grant",
        "admission_decision",
        "execution_lease",
        "materialized_outcome",
        "extensions",
        "AuthorityGrant",
        "authority-grant",
        "executionLease",
        "аuthority_grant",
    ],
)
def test_closed_carrier_rejects_unknown_authority_and_extension_fields(field: str) -> None:
    payload = _payload()
    payload[field] = {"valid": True}
    with pytest.raises(
        MethodologyDispatchCarrierError,
        match="dispatch_carrier_unknown_field",
    ):
        seal_methodology_dispatch_carrier(payload)


def test_closed_support_fact_rejects_nested_unknown_authority_field() -> None:
    payload = _payload()
    fact = payload["support"][0]
    assert isinstance(fact, dict)
    fact["authority"] = {"authorized": True}

    with pytest.raises(MethodologyDispatchCarrierError) as exc_info:
        seal_methodology_dispatch_carrier(payload)
    assert exc_info.value.reason_code == "dispatch_carrier_unknown_field"
    assert exc_info.value.detail == "/support/0/authority"


def test_unregistered_support_code_fails_closed() -> None:
    with pytest.raises(
        MethodologyDispatchCarrierError,
        match="dispatch_carrier_support_code_unregistered",
    ):
        build_dispatch_support_fact(
            kind="candidate",
            code="valid_authority_grant",
            value=True,
        )


def test_self_rehashed_support_reordering_fails_closed() -> None:
    payload = _payload()
    support = payload["support"]
    assert isinstance(support, list)
    support.append(
        build_dispatch_support_fact(
            kind="candidate",
            code="capability.state",
            value="available",
        )
    )
    carrier = seal_methodology_dispatch_carrier(payload)
    body = {
        key: value for key, value in carrier.items() if key not in {"carrier_hash", "carrier_ref"}
    }
    body["support"] = list(reversed(body["support"]))

    with pytest.raises(
        MethodologyDispatchCarrierError,
        match="dispatch_carrier_support_order_invalid",
    ):
        validate_methodology_dispatch_carrier(_rehash(body))


def test_self_rehashed_unknown_field_still_fails_semantic_validation() -> None:
    carrier = seal_methodology_dispatch_carrier(_payload())
    body = {
        key: value for key, value in carrier.items() if key not in {"carrier_hash", "carrier_ref"}
    }
    body["execution_lease"] = {"executor": "/bin/sh"}

    with pytest.raises(
        MethodologyDispatchCarrierError,
        match="dispatch_carrier_unknown_field",
    ):
        validate_methodology_dispatch_carrier(_rehash(body))


def test_shared_carrier_rejects_rehashed_invocation_tamper() -> None:
    carrier = seal_methodology_dispatch_carrier(_payload())
    body = {
        key: value for key, value in carrier.items() if key not in {"carrier_hash", "carrier_ref"}
    }
    body["task_id"] = "other-task"

    with pytest.raises(
        MethodologyDispatchCarrierError,
        match="dispatch_carrier_invocation_mismatch",
    ):
        validate_methodology_dispatch_carrier(_rehash(body), task_id="task-test")


def test_shared_carrier_rejects_hostile_mapping_before_attribute_dispatch() -> None:
    calls: list[str] = []

    class Hostile(dict[str, object]):
        def items(self):
            calls.append("items")
            raise AssertionError("hostile mapping reached")

    with pytest.raises(
        MethodologyDispatchCarrierError,
        match="dispatch_carrier_type_invalid",
    ):
        validate_methodology_dispatch_carrier(Hostile())
    assert calls == []


def test_shared_carrier_requires_complete_invocation_identity_and_operation() -> None:
    for field in ("profile", "requested_operation"):
        payload = _payload()
        payload[field] = ""
        with pytest.raises(MethodologyDispatchCarrierError):
            seal_methodology_dispatch_carrier(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("lane", "cx-red\nforged"),
        ("task_id", "task/escape"),
        ("profile", "x" * 257),
        ("platform", "codex\u202egemini"),
    ],
)
def test_shared_carrier_rejects_unsafe_or_oversized_identity(field: str, value: str) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises(
        MethodologyDispatchCarrierError,
        match="dispatch_carrier_identity_invalid",
    ):
        seal_methodology_dispatch_carrier(payload)


@pytest.mark.parametrize(
    ("kind", "value"),
    [("diagnostic", True), ("candidate", "not-a-bool")],
)
def test_registered_support_code_enforces_kind_and_value_type(kind: str, value: object) -> None:
    with pytest.raises(
        MethodologyDispatchCarrierError,
        match="dispatch_carrier_support_contract_invalid",
    ):
        build_dispatch_support_fact(
            kind=kind,
            code="route_policy.launch_allowed",
            value=value,
        )


def test_registered_support_code_enforces_domain_and_list_grain() -> None:
    with pytest.raises(
        MethodologyDispatchCarrierError,
        match="dispatch_carrier_support_contract_invalid",
    ):
        build_dispatch_support_fact(
            kind="candidate",
            code="route_policy.route_selection_authority",
            value=True,
        )
    with pytest.raises(
        MethodologyDispatchCarrierError,
        match="dispatch_carrier_support_contract_invalid",
    ):
        build_dispatch_support_fact(
            kind="diagnostic",
            code="route_policy.reason_codes",
            value=["held", 1],
        )
    with pytest.raises(
        MethodologyDispatchCarrierError,
        match="dispatch_carrier_support_contract_invalid",
    ):
        build_dispatch_support_fact(
            kind="evidence",
            code="prompt.sha256",
            value="not-a-sha",
        )


def test_raw_codec_accepts_only_exact_canonical_lf_terminated_bytes() -> None:
    carrier = seal_methodology_dispatch_carrier(_payload())
    assert (
        validate_methodology_dispatch_carrier_line(_wire(carrier), task_id="task-test") == carrier
    )

    for hostile in (
        canonical_dispatch_carrier_bytes(carrier),
        _wire(carrier).replace(b"\n", b"\r\n"),
        b"diagnostic\n" + _wire(carrier),
        _wire(carrier) + _wire(carrier),
        b" " + _wire(carrier),
        canonical_dispatch_carrier_bytes(carrier) + b" \n",
    ):
        with pytest.raises(MethodologyDispatchCarrierError):
            validate_methodology_dispatch_carrier_line(hostile)


def test_raw_codec_rejects_duplicate_keys_at_every_depth() -> None:
    carrier = seal_methodology_dispatch_carrier(_payload())
    canonical = canonical_dispatch_carrier_bytes(carrier)
    root_duplicate = (
        canonical.replace(
            b'"task_id":"task-test"',
            b'"task_id":"hostile","task_id":"task-test"',
        )
        + b"\n"
    )
    nested = (
        canonical.replace(
            b'"claim_ceiling":"support_non_authoritative"',
            b'"claim_ceiling":"hostile","claim_ceiling":"support_non_authoritative"',
        )
        + b"\n"
    )

    for hostile in (root_duplicate, nested):
        with pytest.raises(
            MethodologyDispatchCarrierError,
            match="dispatch_carrier_duplicate_key",
        ):
            validate_methodology_dispatch_carrier_line(hostile)


def test_raw_codec_rejects_noncanonical_unicode_nonfinite_and_excess_depth() -> None:
    carrier = seal_methodology_dispatch_carrier(_payload())
    unicode_wire = _wire(carrier).replace(b"task-test", "task-tést".encode())
    nonfinite = b'{"value":NaN}\n'
    deeply_nested = b"[" * 40 + b"0" + b"]" * 40 + b"\n"

    for hostile in (unicode_wire, nonfinite, deeply_nested):
        with pytest.raises(MethodologyDispatchCarrierError):
            validate_methodology_dispatch_carrier_line(hostile)
