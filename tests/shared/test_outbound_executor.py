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

    with pytest.raises(ValueError, match="notional_cap"):
        OutboundExecutor(
            authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
            venue_allowlist={"internal"},
            notional_cap=2**53 + 1,
            position_cap=500.0,
            kill_switch=False,
            registry=base_registry,
        )

    with pytest.raises(ValueError, match="notional_cap"):
        OutboundExecutor(
            authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
            venue_allowlist={"internal"},
            notional_cap=10**400,
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

    with pytest.raises(TypeError, match="public_gate_receipts"):
        OutboundExecutor(
            authority_ceiling=AuthorityCeiling.PUBLIC_GATE_REQUIRED,
            venue_allowlist={"internal"},
            notional_cap=100.0,
            position_cap=500.0,
            kill_switch=False,
            public_gate_receipts="public-gate:receipt-1",  # type: ignore[arg-type]
            registry=base_registry,
        )

    with pytest.raises(TypeError, match="public_gate_receipts entries"):
        OutboundExecutor(
            authority_ceiling=AuthorityCeiling.PUBLIC_GATE_REQUIRED,
            venue_allowlist={"internal"},
            notional_cap=100.0,
            position_cap=500.0,
            kill_switch=False,
            public_gate_receipts={"public-gate:receipt-1", 1},  # type: ignore[list-item]
            registry=base_registry,
        )

    with pytest.raises(ValueError, match="public_gate_receipts entries must be nonblank"):
        OutboundExecutor(
            authority_ceiling=AuthorityCeiling.PUBLIC_GATE_REQUIRED,
            venue_allowlist={"internal"},
            notional_cap=100.0,
            position_cap=500.0,
            kill_switch=False,
            public_gate_receipts={"public-gate:receipt-1", "   "},
            registry=base_registry,
        )

    with pytest.raises(ValueError, match="public-gate evidence refs"):
        OutboundExecutor(
            authority_ceiling=AuthorityCeiling.PUBLIC_GATE_REQUIRED,
            venue_allowlist={"internal"},
            notional_cap=100.0,
            position_cap=500.0,
            kill_switch=False,
            public_gate_receipts={"evidence:audit-log-1"},
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
    for amount in (float("nan"), float("inf"), float("-inf"), -1.0, 2**53 + 1, 10**400):
        with pytest.raises(ValidationError, match="next action"):
            OutboundExecutionRequest(
                scope="gmail_send_internal",
                venue="internal",
                amount=amount,
            )


def test_request_rejects_non_numeric_amount() -> None:
    for amount in (True, "10"):
        with pytest.raises(ValidationError, match="next action"):
            OutboundExecutionRequest(
                scope="gmail_send_internal",
                venue="internal",
                amount=amount,
            )


def test_request_rejects_forged_public_gate_flag() -> None:
    for public_gate_passed in ("yes", 1):
        with pytest.raises(ValidationError, match="public_gate_passed"):
            OutboundExecutionRequest(
                scope="gmail_send_internal",
                venue="internal",
                amount=1.0,
                public_gate_passed=public_gate_passed,
            )


def test_request_rejects_coerced_default_token_flag() -> None:
    for use_default_token in ("false", 0, "off"):
        with pytest.raises(ValidationError, match="use_default_token"):
            OutboundExecutionRequest(
                scope="gmail_send_internal",
                venue="internal",
                amount=1.0,
                use_default_token=use_default_token,
            )


@pytest.mark.parametrize("field", ("scope", "venue"))
def test_request_rejects_blank_scope_or_venue(field: str) -> None:
    request_data = {
        "scope": "gmail_send_internal",
        "venue": "internal",
        "amount": 1.0,
    }
    request_data[field] = "   "

    with pytest.raises(ValidationError, match=field):
        OutboundExecutionRequest(**request_data)


def test_request_is_immutable_after_validation() -> None:
    source_payload = {"nested": {"refs": ["evidence:original"]}}
    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=1.0,
        evidence_refs=["public-gate:receipt-1"],
        payload=source_payload,
    )
    source_payload["nested"]["refs"].append("evidence:source-mutated")

    with pytest.raises(ValidationError, match="frozen"):
        request.amount = -100.0  # type: ignore[misc]
    with pytest.raises(AttributeError):
        request.evidence_refs.append("public-gate:forged")  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        request.payload["forged"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        request.payload["nested"]["forged"] = True  # type: ignore[index]
    with pytest.raises(AttributeError):
        request.payload["nested"]["refs"].append("evidence:forged")  # type: ignore[attr-defined]
    assert request.to_dict()["payload"] == {"nested": {"refs": ["evidence:original"]}}


@pytest.mark.parametrize(
    "payload",
    (
        {"ids": {"mutable-set-leaf"}},
        {"blob": bytearray(b"mutable-bytearray-leaf")},
        {"score": float("nan")},
    ),
)
def test_request_rejects_mutable_or_non_json_payload_values(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="payload values"):
        OutboundExecutionRequest(
            scope="gmail_send_internal",
            venue="internal",
            amount=1.0,
            payload=payload,
        )


@pytest.mark.parametrize(
    "metadata",
    (
        {"ids": {"mutable-set-leaf"}},
        {"blob": bytearray(b"mutable-bytearray-leaf")},
        {"score": float("nan")},
    ),
)
def test_receipt_rejects_mutable_or_non_json_metadata_values(
    metadata: dict[str, object],
) -> None:
    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=1.0,
    )

    with pytest.raises(ValidationError, match="metadata values"):
        OutboundExecutionReceipt(
            receipt_id="receipt:test",
            status="refused",
            request=request,
            verdict="test refusal",
            notional_cap=100.0,
            position_cap=500.0,
            current_position_before=0.0,
            current_position_after=0.0,
            metadata=metadata,
        )


def test_executor_resnapshots_model_copy_mutated_request(
    base_registry: AccountFederationRegistry,
) -> None:
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
        amount=1.0,
    )
    copied_request = request.model_copy(update={"payload": {"ids": {"mutable-set-leaf"}}})

    with pytest.raises(ValidationError, match="payload values"):
        executor.execute(copied_request)
    assert executor.current_position == 0.0


def test_request_rejects_blank_evidence_refs() -> None:
    with pytest.raises(ValidationError, match="evidence_refs"):
        OutboundExecutionRequest(
            scope="gmail_send_internal",
            venue="internal",
            amount=1.0,
            evidence_refs=[""],
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


def test_receive_only_provider_is_snapshotted_at_construction(
    base_registry: AccountFederationRegistry,
) -> None:
    receive_only_registry = base_registry.model_copy(update={"provider": "stripe"})
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        kill_switch=False,
        registry=receive_only_registry,
    )
    receive_only_registry.provider = "gmail"
    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=10.0,
    )

    receipt = executor.execute(request)

    assert receipt.status == "refused"
    assert receipt.refusal_reason == "receive_only_rail"
    assert executor.current_position == 0.0


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
        "github-sponsors-receiver",
        "Treasury Prime",
        "treasury-prime-receiver",
        "Modern Treasury",
        "modern-treasury-receiver",
        "stripe-payment-link-receiver",
        "open-collective-receiver",
        "ko-fi-receiver",
        "patreon-receiver",
        "buy-me-a-coffee-receiver",
        "mercury-receiver",
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


@pytest.mark.parametrize(
    "send_scopes",
    (
        "gmail_send_internal",
        [""],
        ["gmail_send_internal", "   "],
        [1],
    ),
)
def test_malformed_registry_send_scopes_fail_closed(
    base_registry: AccountFederationRegistry,
    send_scopes: object,
) -> None:
    malformed_registry = base_registry.model_copy(update={"send_scopes": send_scopes})

    with pytest.raises((TypeError, ValueError), match="registry.send_scopes"):
        OutboundExecutor(
            authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
            venue_allowlist={"internal"},
            notional_cap=100.0,
            position_cap=500.0,
            kill_switch=False,
            registry=malformed_registry,
        )


def test_padded_global_forbidden_scope_refuses(
    base_registry: AccountFederationRegistry,
) -> None:
    padded_forbidden_scope = " gmail_send_outside_expected_correspondence "
    malformed_registry = base_registry.model_copy(update={"send_scopes": [padded_forbidden_scope]})
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        kill_switch=False,
        registry=malformed_registry,
    )
    request = OutboundExecutionRequest(
        scope=padded_forbidden_scope,
        venue="internal",
        amount=10.0,
    )

    receipt = executor.execute(request)

    assert receipt.status == "refused"
    assert receipt.refusal_reason == "forbidden_action"
    assert executor.current_position == 0.0


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

    # Case C: Literal placeholder, empty, plaintext, and default token values are also blocked.
    for secret_value in ("placeholder", "   ", "default", "plaintext-token", "sk-live-fixture"):
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


def test_current_position_is_read_only_after_construction(
    base_registry: AccountFederationRegistry,
) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=100.0,
        current_position=90.0,
        kill_switch=False,
        registry=base_registry,
    )

    with pytest.raises(AttributeError):
        executor.current_position = -100.0  # type: ignore[misc]

    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=20.0,
    )
    receipt = executor.execute(request)

    assert receipt.status == "refused"
    assert receipt.refusal_reason == "position_cap_exceeded"
    assert executor.current_position == 90.0


def test_executor_gate_configuration_is_read_only(
    base_registry: AccountFederationRegistry,
) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=100.0,
        current_position=90.0,
        kill_switch=False,
        registry=base_registry,
    )

    for attribute, value in (
        ("authority_ceiling", AuthorityCeiling.PUBLIC_GATE_REQUIRED),
        ("venue_allowlist", {"internal", "external"}),
        ("notional_cap", 10_000.0),
        ("position_cap", 10_000.0),
        ("kill_switch", True),
        ("send_scopes", frozenset({"forged_scope"})),
    ):
        with pytest.raises(AttributeError):
            setattr(executor, attribute, value)

    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=20.0,
    )
    receipt = executor.execute(request)

    assert receipt.status == "refused"
    assert receipt.refusal_reason == "position_cap_exceeded"
    assert executor.current_position == 90.0


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


def test_position_cap_refuses_unrepresentable_admitted_position(
    base_registry: AccountFederationRegistry,
) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.INTERNAL_ONLY,
        venue_allowlist={"internal"},
        notional_cap=2.0,
        position_cap=1.0000000000000002e16,
        current_position=1e16,
        kill_switch=False,
        registry=base_registry,
    )

    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=1.0,
    )

    receipt = executor.execute(request)
    assert receipt.status == "refused"
    assert receipt.refusal_reason == "position_precision_loss"
    assert executor.current_position == 1e16


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
    req_public_without_gate_evidence = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=10.0,
        public_gate_passed=True,
        evidence_refs=["evidence:audit-log-1"],
    )
    assert (
        exec_public.execute(req_public_without_gate_evidence).refusal_reason
        == "authority_ceiling_exceeded"
    )
    # Admitted when public_gate_passed=True and public-gate evidence is attached.
    req_public = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=10.0,
        public_gate_passed=True,
        evidence_refs=["public-gate:receipt-1"],
    )
    assert exec_public.execute(req_public).refusal_reason == "authority_ceiling_exceeded"

    # Admitted only when the route independently binds the public-gate receipt.
    exec_public_bound = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.PUBLIC_GATE_REQUIRED,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        kill_switch=False,
        public_gate_receipts={"public-gate:receipt-1"},
        registry=base_registry,
    )
    receipt = exec_public_bound.execute(req_public)
    assert receipt.status == "admitted"
    assert receipt.metadata["public_gate_evidence_ref"] == "public-gate:receipt-1"


def test_receipt_payload_and_metadata_are_durable_snapshots(
    base_registry: AccountFederationRegistry,
) -> None:
    executor = OutboundExecutor(
        authority_ceiling=AuthorityCeiling.PUBLIC_GATE_REQUIRED,
        venue_allowlist={"internal"},
        notional_cap=100.0,
        position_cap=500.0,
        kill_switch=False,
        public_gate_receipts={"public-gate:receipt-1"},
        registry=base_registry,
    )
    request = OutboundExecutionRequest(
        scope="gmail_send_internal",
        venue="internal",
        amount=10.0,
        public_gate_passed=True,
        evidence_refs=["public-gate:receipt-1"],
        payload={"audit": {"refs": ["request:original"]}},
    )

    receipt = executor.execute(request)

    with pytest.raises(TypeError):
        receipt.request.payload["audit"]["forged"] = True  # type: ignore[index]
    with pytest.raises(AttributeError):
        receipt.request.payload["audit"]["refs"].append("request:forged")  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        receipt.metadata["public_gate_evidence_ref"] = "public-gate:forged"  # type: ignore[index]

    receipt_dict = receipt.to_dict()
    assert receipt_dict["request"]["payload"] == {"audit": {"refs": ["request:original"]}}
    assert receipt_dict["metadata"] == {"public_gate_evidence_ref": "public-gate:receipt-1"}


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
