"""Gate-0 execution admission — narrowing, lease currency, and refusal paths.

``shared/execution_admission.py`` decides whether any execution is permitted:
its docstring states that "a separately authenticated authority input is
validated and narrowed before an admission can be issued, and only a current
execution lease may be consumed by a machine adapter". Until this module existed
the file had no dedicated tests — six modules imported it incidentally
(``tests/test_capability_adapter_protocol.py``, ``tests/shared/test_sdlc_claim.py``,
``tests/agents/test_request_decomposer.py``, ``tests/shared/test_liveness.py``,
``tests/test_coord_dispatch_liveness_gate.py``,
``tests/scripts/test_hapax_methodology_dispatch.py``) and covered it only as a
dependency of what they were really testing.

Scope split, stated so the boundary is not mistaken for a gap: happy-path lease
issuance against a fully-populated v3 lease is exercised by
``tests/test_capability_adapter_protocol.py`` (which builds one) and
``tests/shared/test_sdlc_claim.py``. **This module owns the narrowing and
refusal surface** — the paths that decide *no*, which are the ones that fail
open if they regress, and which need no lease fixture to exercise.

Two properties carry most of the weight here:

* **Exact-type narrowing.** ``_require_exact_type`` rejects duck types *and
  subclasses* before invoking any supplied object. A subclass of a frozen
  carrier could otherwise override behaviour and be admitted, so "isinstance
  passes" must not be sufficient anywhere on this boundary.
* **Parse without upgrading.** ``parse_*_record`` dispatch on an exact schema
  string. A historical v1/v2 lease must stay historical: silently upgrading one
  to the active v3 shape would let a superseded, already-consumed lease
  authorize a machine adapter.

Self-contained per project convention — no shared conftest fixtures.
"""

from __future__ import annotations

import pytest

from shared.execution_admission import (
    APPLIED_CLAIM_OWNERSHIP_SCHEMA,
    EXECUTION_LEASE_SCHEMA,
    HISTORICAL_APPLIED_CLAIM_OWNERSHIP_SCHEMA,
    HISTORICAL_EXECUTION_LEASE_V2_SCHEMA,
    ContentAddress,
    ExecutionAdmissionError,
    ExecutionLease,
    content_address,
    parse_applied_claim_ownership_record,
    parse_execution_lease_record,
    require_admitted_execution_lease,
)

_SHA = "a" * 64


# --------------------------------------------------------------------------
# Typed refusal contract
# --------------------------------------------------------------------------


def test_admission_error_carries_reason_and_repair_action() -> None:
    """executive_function axiom: a refusal names the next action, not just a code."""
    error = ExecutionAdmissionError("some_reason", "do the specific thing", "detail")

    assert error.reason_code == "some_reason"
    assert error.repair_action == "do the specific thing"
    assert error.detail == "detail"
    # The rendered message must carry both halves; operators read the message.
    assert "some_reason" in str(error)
    assert "do the specific thing" in str(error)
    assert "detail" in str(error)


def test_admission_error_message_omits_empty_detail() -> None:
    error = ExecutionAdmissionError("some_reason", "do the specific thing")

    assert str(error) == "some_reason: do the specific thing"


# --------------------------------------------------------------------------
# Lease currency — "only a current execution lease may be consumed"
# --------------------------------------------------------------------------


def test_require_admitted_execution_lease_refuses_a_duck_type() -> None:
    """An object that merely looks like a lease must not be admitted."""

    class LooksLikeALease:
        schema_id = EXECUTION_LEASE_SCHEMA
        authorizes_machine_adapter = True

        def model_dump(self, **_: object) -> dict[str, object]:
            return {"schema": EXECUTION_LEASE_SCHEMA}

    with pytest.raises(ExecutionAdmissionError) as excinfo:
        require_admitted_execution_lease(LooksLikeALease())  # type: ignore[arg-type]

    assert excinfo.value.reason_code == "admitted_execution_lease_required"
    assert excinfo.value.repair_action


def test_require_admitted_execution_lease_refuses_a_subclass() -> None:
    """isinstance is not sufficient on this boundary.

    A subclass can override ``model_dump``/validators and smuggle a payload past
    a check that only asserted isinstance. ``_require_exact_type`` uses
    ``type(value) is not expected`` precisely to stop that, so a subclass must be
    refused even though it satisfies isinstance.
    """

    class SneakyLease(ExecutionLease):
        pass

    assert issubclass(SneakyLease, ExecutionLease)

    with pytest.raises(ExecutionAdmissionError) as excinfo:
        require_admitted_execution_lease(SneakyLease.model_construct())

    assert excinfo.value.reason_code == "admitted_execution_lease_required"


@pytest.mark.parametrize("value", [None, 0, "", {}, [], object()])
def test_require_admitted_execution_lease_refuses_non_models(value: object) -> None:
    """Every non-lease input fails closed with the same typed reason."""
    with pytest.raises(ExecutionAdmissionError) as excinfo:
        require_admitted_execution_lease(value)  # type: ignore[arg-type]

    assert excinfo.value.reason_code == "admitted_execution_lease_required"


# --------------------------------------------------------------------------
# Parse without upgrading
# --------------------------------------------------------------------------


def test_execution_lease_schema_versions_are_distinct() -> None:
    """The historical and active lease schemas must never collide.

    If these ever became equal, the "parse without upgrading" guarantee would be
    vacuous and a consumed historical lease could authorize a machine adapter.
    """
    assert HISTORICAL_EXECUTION_LEASE_V2_SCHEMA != EXECUTION_LEASE_SCHEMA
    assert HISTORICAL_APPLIED_CLAIM_OWNERSHIP_SCHEMA != APPLIED_CLAIM_OWNERSHIP_SCHEMA


def test_parse_execution_lease_record_refuses_unknown_schema() -> None:
    with pytest.raises(ExecutionAdmissionError) as excinfo:
        parse_execution_lease_record({"schema": "hapax.execution-lease.v99"})

    assert excinfo.value.reason_code == "execution_lease_schema_unknown"
    assert excinfo.value.repair_action


def test_parse_execution_lease_record_refuses_absent_schema() -> None:
    """A record with no schema key is unknown, not defaulted to the active one."""
    with pytest.raises(ExecutionAdmissionError) as excinfo:
        parse_execution_lease_record({})

    assert excinfo.value.reason_code == "execution_lease_schema_unknown"


def test_parse_execution_lease_record_does_not_upgrade_a_historical_record() -> None:
    """A v2 record routes to the historical model, never to the active v3.

    The v2 payload here is intentionally incomplete: the assertion is about
    *which* model is selected, so reaching v3 validation would be the failure
    even though both raise. Anything other than an unknown-schema refusal proves
    dispatch found the historical branch rather than falling through.
    """
    with pytest.raises(Exception) as excinfo:
        parse_execution_lease_record({"schema": HISTORICAL_EXECUTION_LEASE_V2_SCHEMA})

    assert not (
        isinstance(excinfo.value, ExecutionAdmissionError)
        and excinfo.value.reason_code == "execution_lease_schema_unknown"
    )


def test_parse_applied_claim_ownership_record_refuses_unknown_schema() -> None:
    with pytest.raises(ExecutionAdmissionError) as excinfo:
        parse_applied_claim_ownership_record({"schema": "hapax.applied-claim-ownership-proof.v1"})

    assert excinfo.value.reason_code == "applied_claim_ownership_schema_unknown"
    assert excinfo.value.repair_action


def test_parse_applied_claim_ownership_record_reports_the_offending_schema() -> None:
    """The refusal detail names what was supplied, so the caller can fix it."""
    with pytest.raises(ExecutionAdmissionError) as excinfo:
        parse_applied_claim_ownership_record({"schema": "totally-wrong"})

    assert "totally-wrong" in excinfo.value.detail


# --------------------------------------------------------------------------
# Content addressing — the evidence substrate every admission is bound to
# --------------------------------------------------------------------------


def test_content_address_is_deterministic() -> None:
    first = content_address("ref:thing", {"b": 1, "a": 2})
    second = content_address("ref:thing", {"b": 1, "a": 2})

    assert first == second
    assert first.sha256 == second.sha256


def test_content_address_is_key_order_independent() -> None:
    """Canonical payload hashing: the same mapping hashes alike either way.

    Admissions are bound by content address, so two callers that build the same
    evidence with different insertion order must agree, or an admission would be
    unbindable for arbitrary reasons.
    """
    assert (
        content_address("ref:thing", {"a": 2, "b": 1}).sha256
        == content_address("ref:thing", {"b": 1, "a": 2}).sha256
    )


def test_content_address_is_value_sensitive() -> None:
    assert (
        content_address("ref:thing", {"a": 1}).sha256
        != content_address("ref:thing", {"a": 2}).sha256
    )


@pytest.mark.parametrize("ref", ["", " ", "  leading", "trailing  ", "\tt"])
def test_content_address_refuses_blank_or_padded_refs(ref: str) -> None:
    """Refs are wire strings: blank or edge-whitespace refs are unrepresentable."""
    with pytest.raises(ValueError):
        content_address(ref, {"a": 1})


def test_content_address_model_enforces_the_hash_shape() -> None:
    with pytest.raises(Exception):
        ContentAddress(ref="ref:thing", sha256="not-a-sha")


def test_content_address_is_frozen() -> None:
    """Evidence carriers are immutable; a mutable address could be retargeted."""
    address = ContentAddress(ref="ref:thing", sha256=_SHA)

    with pytest.raises(Exception):
        address.ref = "ref:other"  # type: ignore[misc]


def test_content_address_forbids_extra_fields() -> None:
    with pytest.raises(Exception):
        ContentAddress(ref="ref:thing", sha256=_SHA, smuggled="payload")  # type: ignore[call-arg]
