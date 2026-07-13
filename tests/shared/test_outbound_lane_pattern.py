from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.outbound_lane_pattern import (
    YOUTUBE_PUBLIC_UPLOAD_SCOPE,
    YOUTUBE_PUBLIC_VENUE,
    YOUTUBE_SCOPED_TOKEN_REF,
    BoundedOutboundLane,
    OutboundLaneActReceipt,
    OutboundLaneActRequest,
    OutboundRateLimit,
    ScopedOutboundToken,
    build_youtube_public_upload_lane_template,
)
from shared.resource_capability import AccountFederationRegistry, AuthorityCeiling


@pytest.fixture
def youtube_registry() -> AccountFederationRegistry:
    return AccountFederationRegistry(
        schema_version=1,
        registry_id="account-federation:youtube-template",
        provider="youtube",
        account_id="account:youtube-brand-channel",
        address_or_alias="@legomena-live",
        source_of_truth="account-boundary-record",
        pass_or_secret_key=YOUTUBE_SCOPED_TOKEN_REF,
        read_scopes=["youtube.readonly"],
        send_scopes=[YOUTUBE_PUBLIC_UPLOAD_SCOPE],
        allowed_labels=[],
        allowed_templates=["youtube-public-upload-template"],
        forbidden_actions=["payment_payout"],
        purpose_boundary="public egress template only; no live upload wiring",
        no_fallback_to_default_token=True,
        proton_forwarding_policy="not_applicable",
        gmail_forwarding_policy="not_applicable",
        operator_boundary="operator_required_for_live_provider_execution",
    )


def _request(
    *,
    action_id: str = "youtube-act-1",
    evidence_refs: tuple[str, ...] = ("public-gate:youtube-template-1", "evidence:clip"),
    public_gate_passed: bool = True,
    amount: float = 0.0,
    public_egress_requested: bool = True,
    money_movement_requested: bool = False,
    scope: str = YOUTUBE_PUBLIC_UPLOAD_SCOPE,
) -> OutboundLaneActRequest:
    return OutboundLaneActRequest(
        action_id=action_id,
        scope=scope,
        venue=YOUTUBE_PUBLIC_VENUE,
        amount=amount,
        evidence_refs=evidence_refs,
        public_gate_passed=public_gate_passed,
        public_egress_requested=public_egress_requested,
        money_movement_requested=money_movement_requested,
        payload={"video_ref": "artifact:clip-1"},
    )


def test_youtube_template_admits_with_scoped_token_rate_limit_receipt_and_kill_switch(
    youtube_registry: AccountFederationRegistry,
) -> None:
    lane = build_youtube_public_upload_lane_template(
        registry=youtube_registry,
        public_gate_receipts={"public-gate:youtube-template-1"},
        max_actions=1,
        window_seconds=60,
        kill_switch=False,
    )

    receipt = lane.execute_act(_request())

    assert receipt.status == "admitted"
    assert receipt.refusal_reason is None
    assert receipt.action_id == "youtube-act-1"
    assert receipt.scoped_token_ref == YOUTUBE_SCOPED_TOKEN_REF
    assert receipt.rate_limit_remaining == 0
    assert receipt.public_egress_authorized is True
    assert receipt.money_movement_authorized is False
    assert receipt.outbound_receipt is not None
    assert receipt.outbound_receipt.status == "admitted"
    assert receipt.outbound_receipt.request.amount == 0.0
    assert receipt.metadata["implementation_template"] is True
    assert receipt.metadata["provider_execution_wired"] is False


def test_youtube_template_rate_limit_blocks_second_action_with_per_act_receipt(
    youtube_registry: AccountFederationRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane = build_youtube_public_upload_lane_template(
        registry=youtube_registry,
        public_gate_receipts={"public-gate:youtube-template-1"},
        max_actions=1,
        window_seconds=60,
        kill_switch=False,
        now_fn=lambda: 100.0,
    )

    first = lane.execute_act(_request(action_id="youtube-act-1"))

    def _fail_execute(_: object) -> object:
        raise AssertionError("final OutboundExecutor.execute must not run when rate-limited")

    monkeypatch.setattr(lane._executor, "execute", _fail_execute)  # noqa: SLF001
    second = lane.execute_act(_request(action_id="youtube-act-2"))

    assert first.status == "admitted"
    assert second.status == "refused"
    assert second.action_id == "youtube-act-2"
    assert second.refusal_reason == "rate_limit_exceeded"
    assert second.outbound_receipt is not None
    assert second.outbound_receipt.status == "admitted"
    assert second.metadata["max_actions"] == 1
    assert second.metadata["outbound_execute_reached"] is False
    assert second.metadata["provider_execution_wired"] is False


def test_lane_constructor_requires_scoped_token_rate_limit_and_explicit_kill_switch(
    youtube_registry: AccountFederationRegistry,
) -> None:
    base_kwargs = {
        "lane_id": "template:youtube",
        "registry": youtube_registry,
        "authority_ceiling": AuthorityCeiling.PUBLIC_GATE_REQUIRED,
        "venue_allowlist": {YOUTUBE_PUBLIC_VENUE},
        "notional_cap": 0.0,
        "position_cap": 0.0,
        "scoped_token": ScopedOutboundToken(
            token_ref=YOUTUBE_SCOPED_TOKEN_REF,
            scopes=(YOUTUBE_PUBLIC_UPLOAD_SCOPE,),
        ),
        "rate_limit": OutboundRateLimit(max_actions=1, window_seconds=60),
        "kill_switch": False,
        "public_gate_receipts": {"public-gate:youtube-template-1"},
        "public_egress_authorized": True,
        "money_movement_authorized": False,
    }

    for field, bad_value, error in (
        ("registry", None, TypeError),
        ("scoped_token", None, TypeError),
        ("rate_limit", None, TypeError),
        ("kill_switch", None, TypeError),
    ):
        kwargs = dict(base_kwargs)
        kwargs[field] = bad_value
        with pytest.raises(error, match="next action"):
            BoundedOutboundLane(**kwargs)  # type: ignore[arg-type]


def test_scoped_token_must_match_registry_and_cover_send_scope(
    youtube_registry: AccountFederationRegistry,
) -> None:
    with pytest.raises(ValueError, match="registry.pass_or_secret_key"):
        BoundedOutboundLane(
            lane_id="template:youtube",
            registry=youtube_registry,
            authority_ceiling=AuthorityCeiling.PUBLIC_GATE_REQUIRED,
            venue_allowlist={YOUTUBE_PUBLIC_VENUE},
            notional_cap=0.0,
            position_cap=0.0,
            scoped_token=ScopedOutboundToken(
                token_ref="pass:google/other-youtube-token",
                scopes=(YOUTUBE_PUBLIC_UPLOAD_SCOPE,),
            ),
            rate_limit=OutboundRateLimit(max_actions=1, window_seconds=60),
            kill_switch=False,
            public_gate_receipts={"public-gate:youtube-template-1"},
            public_egress_authorized=True,
            money_movement_authorized=False,
        )

    lane = BoundedOutboundLane(
        lane_id="template:youtube",
        registry=youtube_registry,
        authority_ceiling=AuthorityCeiling.PUBLIC_GATE_REQUIRED,
        venue_allowlist={YOUTUBE_PUBLIC_VENUE},
        notional_cap=0.0,
        position_cap=0.0,
        scoped_token=ScopedOutboundToken(
            token_ref=YOUTUBE_SCOPED_TOKEN_REF,
            scopes=(YOUTUBE_PUBLIC_UPLOAD_SCOPE,),
        ),
        rate_limit=OutboundRateLimit(max_actions=1, window_seconds=60),
        kill_switch=False,
        public_gate_receipts={"public-gate:youtube-template-1"},
        public_egress_authorized=True,
        money_movement_authorized=False,
    )

    receipt = lane.execute_act(_request(scope="youtube_live_chat_message"))

    assert receipt.status == "refused"
    assert receipt.refusal_reason == "token_scope_missing"
    assert receipt.outbound_receipt is None


def test_constructor_rejects_token_scopes_outside_registry(
    youtube_registry: AccountFederationRegistry,
) -> None:
    with pytest.raises(ValueError, match="registry.send_scopes"):
        BoundedOutboundLane(
            lane_id="template:youtube",
            registry=youtube_registry,
            authority_ceiling=AuthorityCeiling.PUBLIC_GATE_REQUIRED,
            venue_allowlist={YOUTUBE_PUBLIC_VENUE},
            notional_cap=0.0,
            position_cap=0.0,
            scoped_token=ScopedOutboundToken(
                token_ref=YOUTUBE_SCOPED_TOKEN_REF,
                scopes=(YOUTUBE_PUBLIC_UPLOAD_SCOPE, "youtube_live_chat_message"),
            ),
            rate_limit=OutboundRateLimit(max_actions=1, window_seconds=60),
            kill_switch=False,
            public_gate_receipts={"public-gate:youtube-template-1"},
            public_egress_authorized=True,
            money_movement_authorized=False,
        )


def test_registry_token_ref_is_stripped_before_match(
    youtube_registry: AccountFederationRegistry,
) -> None:
    padded_registry = youtube_registry.model_copy(
        update={"pass_or_secret_key": f"  {YOUTUBE_SCOPED_TOKEN_REF}  "}
    )

    lane = build_youtube_public_upload_lane_template(
        registry=padded_registry,
        public_gate_receipts={"public-gate:youtube-template-1"},
        max_actions=1,
        window_seconds=60,
        kill_switch=False,
    )

    assert lane.execute_act(_request()).status == "admitted"


def test_secret_ref_and_rate_limit_validation_errors_include_next_actions() -> None:
    with pytest.raises(ValidationError, match="next action"):
        ScopedOutboundToken(token_ref="google/token-youtube-streaming", scopes=("x",))

    for kwargs in (
        {"max_actions": 0, "window_seconds": 60},
        {"max_actions": 1, "window_seconds": 0},
    ):
        with pytest.raises(ValidationError, match="next action"):
            OutboundRateLimit(**kwargs)


def test_request_and_receipt_payload_validators_reject_non_json_shapes(
    youtube_registry: AccountFederationRegistry,
) -> None:
    for request_kwargs in (
        {"amount": -1.0},
        {"amount": float("nan")},
        {"public_gate_passed": "yes"},
        {"public_egress_requested": 1},
        {"money_movement_requested": "false"},
        {"evidence_refs": [""]},
        {"evidence_refs": "public-gate:youtube-template-1"},
    ):
        with pytest.raises(ValidationError, match="next action"):
            OutboundLaneActRequest(
                action_id="bad-request",
                scope=YOUTUBE_PUBLIC_UPLOAD_SCOPE,
                venue=YOUTUBE_PUBLIC_VENUE,
                **request_kwargs,
            )

    lane = build_youtube_public_upload_lane_template(
        registry=youtube_registry,
        public_gate_receipts={"public-gate:youtube-template-1"},
        max_actions=1,
        window_seconds=60,
        kill_switch=False,
    )
    with pytest.raises(TypeError, match="next action"):
        lane.execute_act("not-a-request")  # type: ignore[arg-type]

    with pytest.raises(ValidationError, match="next action"):
        OutboundLaneActRequest(
            action_id="bad-payload",
            scope=YOUTUBE_PUBLIC_UPLOAD_SCOPE,
            venue=YOUTUBE_PUBLIC_VENUE,
            payload={"bad": {"mutable-set"}},
        )

    with pytest.raises(ValidationError, match="next action"):
        OutboundLaneActReceipt(
            receipt_id="receipt:bad",
            lane_id="template:youtube",
            action_id="bad-metadata",
            status="refused",
            refusal_reason="test",
            scoped_token_ref=YOUTUBE_SCOPED_TOKEN_REF,
            rate_limit_remaining=0,
            public_egress_authorized=True,
            money_movement_authorized=False,
            metadata={"bad": {"mutable-set"}},
        )

    for receipt_kwargs in (
        {"receipt_id": ""},
        {"lane_id": " "},
        {"action_id": ""},
        {"scoped_token_ref": ""},
        {"rate_limit_remaining": -1},
        {"status": "refused", "refusal_reason": None},
        {"status": "admitted", "refusal_reason": "unexpected"},
    ):
        kwargs = {
            "receipt_id": "receipt:good",
            "lane_id": "template:youtube",
            "action_id": "receipt-action",
            "status": "refused",
            "refusal_reason": "test_refusal",
            "scoped_token_ref": YOUTUBE_SCOPED_TOKEN_REF,
            "rate_limit_remaining": 0,
            "public_egress_authorized": True,
            "money_movement_authorized": False,
        }
        kwargs.update(receipt_kwargs)
        with pytest.raises(ValidationError, match="next action"):
            OutboundLaneActReceipt(**kwargs)


def test_public_egress_and_money_movement_are_separate_authorities(
    youtube_registry: AccountFederationRegistry,
) -> None:
    lane = build_youtube_public_upload_lane_template(
        registry=youtube_registry,
        public_gate_receipts={"public-gate:youtube-template-1"},
        max_actions=2,
        window_seconds=60,
        kill_switch=False,
    )

    public_only = lane.execute_act(_request(action_id="public-egress"))
    money_attempt = lane.execute_act(
        _request(
            action_id="money-attempt",
            amount=1.0,
            money_movement_requested=True,
        )
    )

    assert public_only.status == "admitted"
    assert money_attempt.status == "refused"
    assert money_attempt.refusal_reason == "money_movement_not_authorized"
    assert money_attempt.outbound_receipt is None


def test_public_egress_request_refuses_when_public_authority_absent(
    youtube_registry: AccountFederationRegistry,
) -> None:
    lane = BoundedOutboundLane(
        lane_id="template:youtube",
        registry=youtube_registry,
        authority_ceiling=AuthorityCeiling.PUBLIC_GATE_REQUIRED,
        venue_allowlist={YOUTUBE_PUBLIC_VENUE},
        notional_cap=0.0,
        position_cap=0.0,
        scoped_token=ScopedOutboundToken(
            token_ref=YOUTUBE_SCOPED_TOKEN_REF,
            scopes=(YOUTUBE_PUBLIC_UPLOAD_SCOPE,),
        ),
        rate_limit=OutboundRateLimit(max_actions=1, window_seconds=60),
        kill_switch=False,
        public_gate_receipts={"public-gate:youtube-template-1"},
        public_egress_authorized=False,
        money_movement_authorized=False,
    )

    receipt = lane.execute_act(_request())

    assert receipt.status == "refused"
    assert receipt.refusal_reason == "public_egress_not_authorized"
    assert receipt.outbound_receipt is None
    assert receipt.metadata["provider_execution_wired"] is False

    cleared_flag_receipt = lane.execute_act(
        _request(
            action_id="public-egress-cleared-flag",
            public_egress_requested=False,
        )
    )

    assert cleared_flag_receipt.status == "refused"
    assert cleared_flag_receipt.refusal_reason == "public_egress_not_authorized"
    assert cleared_flag_receipt.outbound_receipt is None
    assert cleared_flag_receipt.metadata["provider_execution_wired"] is False


def test_youtube_public_egress_requires_public_gate_receipt(
    youtube_registry: AccountFederationRegistry,
) -> None:
    lane = build_youtube_public_upload_lane_template(
        registry=youtube_registry,
        public_gate_receipts={"public-gate:youtube-template-1"},
        max_actions=1,
        window_seconds=60,
        kill_switch=False,
    )

    receipt = lane.execute_act(
        _request(
            evidence_refs=("evidence:clip",),
            public_gate_passed=False,
        )
    )

    assert receipt.status == "refused"
    assert receipt.refusal_reason == "authority_ceiling_exceeded"
    assert receipt.outbound_receipt is not None
    assert receipt.outbound_receipt.refusal_reason == "authority_ceiling_exceeded"
    assert lane.current_position == 0.0


def test_youtube_kill_switch_blocks_with_per_act_receipt(
    youtube_registry: AccountFederationRegistry,
) -> None:
    lane = build_youtube_public_upload_lane_template(
        registry=youtube_registry,
        public_gate_receipts={"public-gate:youtube-template-1"},
        max_actions=1,
        window_seconds=60,
        kill_switch=True,
    )

    receipt = lane.execute_act(_request())

    assert receipt.status == "refused"
    assert receipt.refusal_reason == "kill_switch_active"
    assert receipt.outbound_receipt is not None
    assert receipt.outbound_receipt.refusal_reason == "kill_switch_active"
    assert receipt.rate_limit_remaining == 1


def test_rate_limit_remaining_resets_after_window_for_refusal_receipts(
    youtube_registry: AccountFederationRegistry,
) -> None:
    now = 100.0

    def _now() -> float:
        return now

    lane = build_youtube_public_upload_lane_template(
        registry=youtube_registry,
        public_gate_receipts={"public-gate:youtube-template-1"},
        max_actions=1,
        window_seconds=10,
        kill_switch=False,
        now_fn=_now,
    )

    first = lane.execute_act(_request(action_id="first"))
    now = 111.0
    expired_refusal = lane.execute_act(
        _request(action_id="wrong-scope", scope="youtube_live_chat_message")
    )
    second = lane.execute_act(_request(action_id="second"))

    assert first.rate_limit_remaining == 0
    assert expired_refusal.refusal_reason == "token_scope_missing"
    assert expired_refusal.rate_limit_remaining == 1
    assert second.status == "admitted"
    assert second.rate_limit_remaining == 0
