from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.outbound_executor import (
    OutboundExecutionRefusal,
    OutboundExecutionRequest,
    OutboundExecutor,
)
from shared.resource_capability import (
    AccountFederationRegistry,
    AuthorityCeiling,
)


@pytest.fixture
def base_registry() -> AccountFederationRegistry:
    return AccountFederationRegistry(
        schema_version=1,
        registry_id="account-federation:test-fixture",
        provider="gmail",
        account_id="account:test-fixture",
        address_or_alias="alias:test",
        source_of_truth="account-boundary-record",
        pass_or_secret_key="pass:valid-secret-key-path",
        read_scopes=["metadata_only"],
        send_scopes=["gmail_send_outside_expected_correspondence", "gmail_send_internal"],
        allowed_labels=["test-label"],
        allowed_templates=[],
        forbidden_actions=["forward"],
        purpose_boundary="testing",
        no_fallback_to_default_token=True,
        proton_forwarding_policy="not_configured",
        gmail_forwarding_policy="no_cross_account_reply",
        operator_boundary="operator_required_for_send",
    )


def test_executor_strictness() -> None:
    # Ensure models forbid extra fields
    request_data = {
        "scope": "gmail_send_internal",
        "venue": "internal",
        "amount": 10.0,
        "unexpected_field": True,
    }
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        OutboundExecutionRequest.model_validate(request_data)


def test_successful_admit(base_registry: AccountFederationRegistry) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal", "internal:logs"},
        notional_cap=100.0,
        position_cap=500.0,
        current_position=50.0,
        kill_switch=False,
        registry=base_registry,
    )

    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=25.0,
    )

    receipt = executor.execute(request)
    assert receipt.status == "admitted"
    assert receipt.verdict == "Outbound execution admitted under governed checks"
    assert receipt.current_position_before == 50.0
    assert receipt.current_position_after == 75.0
    assert executor.current_position == 75.0


def test_executor_configuration_fails_closed(base_registry: AccountFederationRegistry) -> None:
    with pytest.raises(ValueError, match="venue_allowlist"):
        OutboundExecutor(
            authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
            venue_allowlist=set(),
            notional_cap=100.0,
            position_cap=500.0,
            registry=base_registry,
        )

    with pytest.raises(ValueError, match="notional_cap"):
        OutboundExecutor(
            authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
            venue_allowlist={"internal"},
            notional_cap=-1.0,
            position_cap=500.0,
            registry=base_registry,
        )

    with pytest.raises(ValueError, match="position_cap"):
        OutboundExecutor(
            authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
            venue_allowlist={"internal"},
            notional_cap=100.0,
            position_cap=-1.0,
            registry=base_registry,
        )


def test_require_execution_success(base_registry: AccountFederationRegistry) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        current_position=50.0,
        registry=base_registry,
    )

    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=10.0,
    )

    receipt = executor.require_execution(request)
    assert receipt.status == "admitted"
    assert executor.current_position == 60.0


def test_require_execution_refused(base_registry: AccountFederationRegistry) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        kill_switch=True,
        registry=base_registry,
    )

    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=10.0,
    )

    with pytest.raises(OutboundExecutionRefusal, match="kill switch is active"):
        executor.require_execution(request)


def test_kill_switch_blocks(base_registry: AccountFederationRegistry) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        kill_switch=True,
        registry=base_registry,
    )

    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=10.0,
    )

    receipt = executor.execute(request)
    assert receipt.status == "refused"
    assert receipt.refusal_reason == "kill_switch_active"
    assert executor.current_position == 0.0  # Position remains unchanged


def test_receive_only_rail_blocks(base_registry: AccountFederationRegistry) -> None:
    # Modify registry provider to a receive-only rail
    receive_only_registry = base_registry.model_copy(update={"provider": "stripe"})
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        registry=receive_only_registry,
    )

    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=10.0,
    )

    receipt = executor.execute(request)
    assert receipt.status == "refused"
    assert receipt.refusal_reason == "receive_only_rail"


def test_missing_scope_blocks(base_registry: AccountFederationRegistry) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        registry=base_registry,
    )

    # scope "gmail_send_public" is not in send_scopes
    request = OutboundExecutionRequest(
        scope="gmail_send_public",
        venue="internal",
        amount=10.0,
    )

    receipt = executor.execute(request)
    assert receipt.status == "refused"
    assert receipt.refusal_reason == "missing_scope"


def test_default_token_fallback_blocks(base_registry: AccountFederationRegistry) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        registry=base_registry,
    )

    # Case A: Request explicitly wants default token
    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=10.0,
        use_default_token=True,
    )
    receipt = executor.execute(request)
    assert receipt.status == "refused"
    assert receipt.refusal_reason == "default_token_fallback"

    # Case B: Registry secret key is a placeholder
    placeholder_registry = base_registry.model_copy(
        update={"pass_or_secret_key": "pass:placeholder/no-value"}
    )
    executor_placeholder = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        registry=placeholder_registry,
    )
    request_normal = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=10.0,
    )
    receipt_placeholder = executor_placeholder.execute(request_normal)
    assert receipt_placeholder.status == "refused"
    assert receipt_placeholder.refusal_reason == "default_token_fallback"


def test_forbidden_action_blocks(base_registry: AccountFederationRegistry) -> None:
    # Request has scope "forward", which is in base_registry.forbidden_actions
    request = OutboundExecutionRequest(
        scope="forward",
        venue="internal",
        amount=10.0,
    )
    # Even if "forward" is not in send_scopes (which would refuse with missing_scope first),
    # let's add it to send_scopes in registry copy to specifically test forbidden_action block.
    registry_with_forward = base_registry.model_copy(update={"send_scopes": ["forward"]})
    executor_forward = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        registry=registry_with_forward,
    )

    receipt = executor_forward.execute(request)
    assert receipt.status == "refused"
    assert receipt.refusal_reason == "forbidden_action"


def test_venue_allowlist_blocks(base_registry: AccountFederationRegistry) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        registry=base_registry,
    )

    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="external_untrusted",
        amount=10.0,
    )

    receipt = executor.execute(request)
    assert receipt.status == "refused"
    assert receipt.refusal_reason == "venue_not_allowed"


def test_notional_cap_blocks(base_registry: AccountFederationRegistry) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=50.0,
        position_cap=500.0,
        registry=base_registry,
    )

    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=50.01,
    )

    receipt = executor.execute(request)
    assert receipt.status == "refused"
    assert receipt.refusal_reason == "notional_cap_exceeded"


def test_position_cap_blocks(base_registry: AccountFederationRegistry) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=150.0,
        current_position=140.0,
        registry=base_registry,
    )

    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=15.0,
    )

    receipt = executor.execute(request)
    assert receipt.status == "refused"
    assert receipt.refusal_reason == "position_cap_exceeded"


def test_authority_ceilings(base_registry: AccountFederationRegistry) -> None:
    # A. NO_CLAIM
    exec_no_claim = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.NO_CLAIM,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        registry=base_registry,
    )
    req = OutboundExecutionRequest(scope="gmail_send_internal", venue="internal", amount=10.0)
    assert exec_no_claim.execute(req).refusal_reason == "authority_ceiling_exceeded"

    # B. INTERNAL_ONLY with external venue
    exec_internal = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"external_venue"},
        notional_cap=100.0,
        position_cap=500.0,
        registry=base_registry,
    )
    req_external = OutboundExecutionRequest(
        scope="gmail_send_internal", venue="external_venue", amount=10.0
    )
    assert exec_internal.execute(req_external).refusal_reason == "authority_ceiling_exceeded"

    # C. EVIDENCE_BOUND with missing evidence_refs
    exec_evidence = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.EVIDENCE_BOUND,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        registry=base_registry,
    )
    assert exec_evidence.execute(req).refusal_reason == "authority_ceiling_exceeded"
    # Admitted when evidence is provided
    req_with_evidence = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=10.0,
        evidence_refs=["evidence:audit-log-1"],
    )
    assert exec_evidence.execute(req_with_evidence).status == "admitted"

    # D. PUBLIC_GATE_REQUIRED with public_gate_passed=False
    exec_public = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.PUBLIC_GATE_REQUIRED,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        registry=base_registry,
    )
    assert exec_public.execute(req).refusal_reason == "authority_ceiling_exceeded"
    # Admitted when public_gate_passed=True
    req_public = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=10.0,
        public_gate_passed=True,
    )
    assert exec_public.execute(req_public).status == "admitted"


def test_receipt_to_dict(base_registry: AccountFederationRegistry) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        registry=base_registry,
    )
    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=10.0,
    )
    receipt = executor.execute(request)
    receipt_dict = receipt.to_dict()
    assert receipt_dict["status"] == "admitted"
    assert receipt_dict["notional_cap"] == 100.0
    assert receipt_dict["position_cap"] == 500.0
