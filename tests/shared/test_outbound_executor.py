from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError

from agents.payment_processors.usdc_receiver import RAIL_LABEL as X402_USDC_RAIL_LABEL
from shared.license_request_price_class_router import ReceiveOnlyRail as LicenseReceiveOnlyRail
from shared.outbound_executor import (
    OutboundExecutionReceipt,
    OutboundExecutionRefusal,
    OutboundExecutionRequest,
    OutboundExecutor,
)
from shared.payment_aggregator_v2_support_normalizer import Rail as SupportRail
from shared.resource_capability import (
    AccountFederationRegistry,
    AuthorityCeiling,
)

_SOURCE_RECEIVE_ONLY_INVENTORY_PROVIDERS = tuple(
    sorted(
        {rail.value for rail in SupportRail}
        | {
            rail.value
            for rail in LicenseReceiveOnlyRail
            if rail is not LicenseReceiveOnlyRail.NO_RAIL
        }
        | {X402_USDC_RAIL_LABEL, "usdc"}
    )
)
_SHARED_RECEIVE_ONLY_RAIL_MODULE_PROVIDERS = tuple(
    sorted(
        path.name.removesuffix("_receive_only_rail.py")
        for path in (Path(__file__).resolve().parents[2] / "shared").glob("*_receive_only_rail.py")
    )
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


def _assert_receive_only_provider_refused(
    base_registry: AccountFederationRegistry,
    provider: str,
) -> None:
    receive_only_registry = base_registry.model_copy(update={"provider": provider})
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        kill_switch=False,
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
            kill_switch=False,
            registry=base_registry,
        )

    with pytest.raises(ValueError, match="notional_cap"):
        OutboundExecutor(
            authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
            venue_allowlist={"internal"},
            notional_cap=-1.0,
            position_cap=500.0,
            kill_switch=False,
            registry=base_registry,
        )

    with pytest.raises(ValueError, match="notional_cap must be finite"):
        OutboundExecutor(
            authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
            venue_allowlist={"internal"},
            notional_cap=float("nan"),
            position_cap=500.0,
            kill_switch=False,
            registry=base_registry,
        )

    with pytest.raises(ValueError, match="notional_cap must be finite"):
        OutboundExecutor(
            authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
            venue_allowlist={"internal"},
            notional_cap=float("inf"),
            position_cap=500.0,
            kill_switch=False,
            registry=base_registry,
        )

    with pytest.raises(ValueError, match="position_cap"):
        OutboundExecutor(
            authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
            venue_allowlist={"internal"},
            notional_cap=100.0,
            position_cap=-1.0,
            kill_switch=False,
            registry=base_registry,
        )

    with pytest.raises(ValueError, match="current_position"):
        OutboundExecutor(
            authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
            venue_allowlist={"internal"},
            notional_cap=100.0,
            position_cap=500.0,
            current_position=-1.0,
            kill_switch=False,
            registry=base_registry,
        )


def test_executor_configuration_rejects_invalid_types(
    base_registry: AccountFederationRegistry,
) -> None:
    with pytest.raises(TypeError, match="authority_ceiling"):
        OutboundExecutor(
            authority_ceiling="internal_only",  # type: ignore[arg-type]
            venue_allowlist={"internal"},
            notional_cap=100.0,
            position_cap=500.0,
            kill_switch=False,
            registry=base_registry,
        )

    with pytest.raises(TypeError, match="venue_allowlist"):
        OutboundExecutor(
            authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
            venue_allowlist="external",  # type: ignore[arg-type]
            notional_cap=100.0,
            position_cap=500.0,
            kill_switch=False,
            registry=base_registry,
        )

    with pytest.raises(TypeError, match="venue_allowlist entries"):
        OutboundExecutor(
            authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
            venue_allowlist={"internal", 1},  # type: ignore[list-item]
            notional_cap=100.0,
            position_cap=500.0,
            kill_switch=False,
            registry=base_registry,
        )

    with pytest.raises(ValueError, match="nonblank"):
        OutboundExecutor(
            authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
            venue_allowlist={"internal", "   "},
            notional_cap=100.0,
            position_cap=500.0,
            kill_switch=False,
            registry=base_registry,
        )

    with pytest.raises(TypeError, match="kill_switch"):
        OutboundExecutor(
            authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
            venue_allowlist={"internal"},
            notional_cap=100.0,
            position_cap=500.0,
            registry=base_registry,
        )

    with pytest.raises(TypeError, match="kill_switch"):
        OutboundExecutor(
            authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
            venue_allowlist={"internal"},
            notional_cap=100.0,
            position_cap=500.0,
            kill_switch=None,
            registry=base_registry,
        )

    with pytest.raises(TypeError, match="registry"):
        OutboundExecutor(
            authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
            venue_allowlist={"internal"},
            notional_cap=100.0,
            position_cap=500.0,
            kill_switch=False,
            registry="registry",  # type: ignore[arg-type]
        )

    with pytest.raises(TypeError, match="position_cap"):
        OutboundExecutor(
            authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
            venue_allowlist={"internal"},
            notional_cap=100.0,
            position_cap="500",  # type: ignore[arg-type]
            kill_switch=False,
            registry=base_registry,
        )


def test_request_rejects_non_finite_amount() -> None:
    for amount in (float("nan"), float("inf"), float("-inf"), -1.0):
        with pytest.raises(ValidationError, match="next action"):
            OutboundExecutionRequest(
                scope="gmail_send_internal",
                venue="internal",
                amount=amount,
            )


def test_require_execution_success(base_registry: AccountFederationRegistry) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        current_position=50.0,
        kill_switch=False,
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

    with pytest.raises(OutboundExecutionRefusal, match="kill switch is active") as exc_info:
        executor.require_execution(request)
    assert exc_info.value.receipt.refusal_reason == "kill_switch_active"
    assert exc_info.value.receipt.status == "refused"


def test_validate_request_is_dry_run(base_registry: AccountFederationRegistry) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        current_position=50.0,
        kill_switch=False,
        registry=base_registry,
    )

    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=10.0,
    )

    receipt = executor.validate_request(request)
    assert receipt.status == "admitted"
    assert receipt.current_position_after == 60.0
    assert executor.current_position == 50.0


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
    assert "Next action:" in receipt.verdict
    assert receipt.metadata["next_action"]
    assert executor.current_position == 0.0  # Position remains unchanged


def test_no_claim_refuses_before_route_specific_checks(
    base_registry: AccountFederationRegistry,
) -> None:
    receive_only_registry = base_registry.model_copy(update={"provider": "stripe"})
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.NO_CLAIM,
        venue_allowlist={"internal"},
        notional_cap=1.0,
        position_cap=1.0,
        kill_switch=False,
        registry=receive_only_registry,
    )

    request = OutboundExecutionRequest(
        scope="not_in_registry",
        venue="internal",
        amount=2.0,
        use_default_token=True,
    )

    receipt = executor.execute(request)
    assert receipt.refusal_reason == "authority_ceiling_exceeded"
    assert "NO_CLAIM" in receipt.verdict


def test_receive_only_rail_blocks(base_registry: AccountFederationRegistry) -> None:
    _assert_receive_only_provider_refused(base_registry, "stripe")


@pytest.mark.parametrize(
    "provider",
    (
        "ko_fi",
        "Ko-fi",
        "kofi",
        "omg.lol Pay",
        "BMaC",
        "BuyMeACoffee",
        "Open Collective",
        "Stripe Payment Link",
        "GitHub Sponsors",
        "Treasury Prime",
        "Modern Treasury",
    ),
)
def test_receive_only_provider_aliases_block(
    base_registry: AccountFederationRegistry,
    provider: str,
) -> None:
    _assert_receive_only_provider_refused(base_registry, provider)


@pytest.mark.parametrize("provider", _SOURCE_RECEIVE_ONLY_INVENTORY_PROVIDERS)
def test_receive_only_source_inventory_blocks_provider_with_send_scope(
    base_registry: AccountFederationRegistry,
    provider: str,
) -> None:
    _assert_receive_only_provider_refused(base_registry, provider)


@pytest.mark.parametrize("provider", _SHARED_RECEIVE_ONLY_RAIL_MODULE_PROVIDERS)
def test_shared_receive_only_rail_module_inventory_blocks_provider_with_send_scope(
    base_registry: AccountFederationRegistry,
    provider: str,
) -> None:
    _assert_receive_only_provider_refused(base_registry, provider)


@pytest.mark.parametrize(
    "provider",
    (
        "Lightning",
        "nostr-zap",
        "Nostr Zap",
        "Ko-fi Guarded",
        "x402-usdc-base",
        "USDC",
        "Base USDC",
    ),
)
def test_receive_only_payment_processor_aliases_block(
    base_registry: AccountFederationRegistry,
    provider: str,
) -> None:
    _assert_receive_only_provider_refused(base_registry, provider)


def test_missing_scope_blocks(base_registry: AccountFederationRegistry) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        kill_switch=False,
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
        kill_switch=False,
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
        kill_switch=False,
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

    # Case C: Literal placeholder and empty values are also blocked.
    for secret_value in ("placeholder", "   "):
        placeholder_registry = base_registry.model_copy(update={"pass_or_secret_key": secret_value})
        executor_placeholder = OutboundExecutor(
            authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
            venue_allowlist={"internal"},
            notional_cap=100.0,
            position_cap=500.0,
            kill_switch=False,
            registry=placeholder_registry,
        )
        receipt_placeholder = executor_placeholder.execute(request_normal)
        assert receipt_placeholder.status == "refused"
        assert receipt_placeholder.refusal_reason == "default_token_fallback"

    # Case D: malformed registries that disable the no-fallback contract are refused.
    unsafe_registry = base_registry.model_copy(update={"no_fallback_to_default_token": False})
    executor_unsafe = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        kill_switch=False,
        registry=unsafe_registry,
    )
    receipt_unsafe = executor_unsafe.execute(request_normal)
    assert receipt_unsafe.status == "refused"
    assert receipt_unsafe.refusal_reason == "default_token_fallback"


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
        kill_switch=False,
        registry=registry_with_forward,
    )

    receipt = executor_forward.execute(request)
    assert receipt.status == "refused"
    assert receipt.refusal_reason == "forbidden_action"


def test_global_forbidden_write_scope_blocks(base_registry: AccountFederationRegistry) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        kill_switch=False,
        registry=base_registry,
    )

    # This scope is deliberately in send_scopes and the global forbidden set, so
    # the test proves forbidden_action wins after the missing-scope check.
    request = OutboundExecutionRequest(
        scope="gmail_send_outside_expected_correspondence",
        venue="internal",
        amount=10.0,
    )

    receipt = executor.execute(request)
    assert receipt.status == "refused"
    assert receipt.refusal_reason == "forbidden_action"


def test_venue_allowlist_blocks(base_registry: AccountFederationRegistry) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        kill_switch=False,
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
        kill_switch=False,
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


def test_notional_cap_boundary_admits_equal_amount(
    base_registry: AccountFederationRegistry,
) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=50.0,
        position_cap=500.0,
        kill_switch=False,
        registry=base_registry,
    )

    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=50.0,
    )

    receipt = executor.execute(request)
    assert receipt.status == "admitted"
    assert receipt.current_position_after == 50.0


def test_notional_cap_just_over_fractional_boundary_refuses(
    base_registry: AccountFederationRegistry,
) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=0.3,
        position_cap=1.0,
        kill_switch=False,
        registry=base_registry,
    )

    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=0.3000000000001,
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
        kill_switch=False,
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


def test_position_cap_boundary_admits_equal_total(
    base_registry: AccountFederationRegistry,
) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=150.0,
        current_position=140.0,
        kill_switch=False,
        registry=base_registry,
    )

    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=10.0,
    )

    receipt = executor.execute(request)
    assert receipt.status == "admitted"
    assert receipt.current_position_before == 140.0
    assert receipt.current_position_after == 150.0
    assert executor.current_position == 150.0


def test_position_cap_boundary_admits_direct_cap_amount(
    base_registry: AccountFederationRegistry,
) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=150.0,
        position_cap=150.0,
        kill_switch=False,
        registry=base_registry,
    )

    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=150.0,
    )

    receipt = executor.execute(request)
    assert receipt.status == "admitted"
    assert receipt.current_position_after == 150.0


def test_position_cap_fractional_boundary_admits_close_total(
    base_registry: AccountFederationRegistry,
) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=1.0,
        position_cap=0.3,
        current_position=0.1,
        kill_switch=False,
        registry=base_registry,
    )

    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=0.2,
    )

    receipt = executor.execute(request)
    assert receipt.status == "admitted"
    assert receipt.current_position_after == 0.3
    assert executor.current_position == 0.3

    follow_up = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=0.0,
    )
    follow_up_receipt = executor.execute(follow_up)
    assert follow_up_receipt.status == "admitted"
    assert follow_up_receipt.current_position_after == 0.3


def test_position_cap_just_over_fractional_boundary_refuses(
    base_registry: AccountFederationRegistry,
) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=1.0,
        position_cap=0.3,
        current_position=0.1,
        kill_switch=False,
        registry=base_registry,
    )

    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=0.2000000000001,
    )

    receipt = executor.execute(request)
    assert receipt.status == "refused"
    assert receipt.refusal_reason == "position_cap_exceeded"


def test_execute_position_admission_is_atomic(
    base_registry: AccountFederationRegistry,
) -> None:
    class SlowAdmitExecutor(OutboundExecutor):
        def _validate_request_locked(
            self,
            request: OutboundExecutionRequest,
        ) -> OutboundExecutionReceipt:
            receipt = super()._validate_request_locked(request)
            if receipt.status == "admitted":
                time.sleep(0.05)
            return receipt

    executor = SlowAdmitExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=1.0,
        position_cap=1.0,
        kill_switch=False,
        registry=base_registry,
    )
    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=1.0,
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(executor.execute, (request, request)))

    assert [receipt.status for receipt in receipts].count("admitted") == 1
    refused = [receipt for receipt in receipts if receipt.status == "refused"]
    assert len(refused) == 1
    assert refused[0].refusal_reason == "position_cap_exceeded"
    assert executor.current_position == 1.0


def test_authority_ceilings(base_registry: AccountFederationRegistry) -> None:
    # A. NO_CLAIM
    exec_no_claim = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.NO_CLAIM,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        kill_switch=False,
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
        kill_switch=False,
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
        kill_switch=False,
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
        kill_switch=False,
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


def test_internal_only_accepts_internal_venue_prefixes(
    base_registry: AccountFederationRegistry,
) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal:logs", "private_internal_runner"},
        notional_cap=100.0,
        position_cap=500.0,
        kill_switch=False,
        registry=base_registry,
    )

    for venue in ("internal:logs", "private_internal_runner"):
        request = OutboundExecutionRequest(
            scope="gmail_send_internal",
            venue=venue,
            amount=1.0,
        )
        assert executor.validate_request(request).status == "admitted"


def test_receipt_to_dict(base_registry: AccountFederationRegistry) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        kill_switch=False,
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


def test_request_to_dict() -> None:
    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=10.0,
        evidence_refs=["evidence:fixture"],
    )

    request_dict = request.to_dict()
    assert request_dict == {
        "scope": "gmail_send_internal",
        "venue": "internal",
        "amount": 10.0,
        "use_default_token": False,
        "evidence_refs": ["evidence:fixture"],
        "public_gate_passed": False,
        "payload": {},
    }
