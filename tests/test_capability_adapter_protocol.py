"""Tests for the CapabilityAdapter protocol + type hierarchy (capability-adapter-protocol-module)."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from unittest import mock

import pytest

from shared.capability_adapter_protocol import (
    AgyAdapter,
    AuthorityViolation,
    BudgetAuthorityAdapter,
    CapabilityAdapter,
    ClaudeAdapter,
    CodexAdapter,
    RetiredAntigravFailureClassifier,
    ReviewSeatAdapter,
    SendCapableAdapter,
    VibeAdapter,
    WorkerAdapter,
)
from shared.dispatcher_policy import DispatchAction, RouteDecision
from shared.failure_classification import (
    ZAI_ERROR_CLASS_BY_CODE,
    FailureCode,
    failure_code_for_zai,
)
from shared.platform_capability_registry import Platform

_MOD = "shared.capability_adapter_protocol"


def _decision(
    *,
    action: DispatchAction,
    launch_allowed: bool,
    route_id: str = "claude.headless.opus",
    reason_codes: tuple[str, ...] = (),
    platform: str = "claude",
    lane: str = "cc-sdlc",
) -> RouteDecision:
    """Build a REAL RouteDecision (the type the dispatcher returns) for the authority tests."""

    return RouteDecision(
        decision_id="d-test",
        created_at=datetime(2026, 6, 20, tzinfo=UTC),
        task_id="t",
        lane=lane,
        route_id=route_id,
        platform=platform,
        mode="headless",
        profile="opus",
        action=action,
        policy_outcome="test",
        launch_allowed=launch_allowed,
        prompt_allowed=False,
        quality_floor_satisfied=True,
        authority_allowed=True,
        reason_codes=reason_codes,
        message="test",
    )


# --- criterion 1: admit() returns evaluate_dispatch_policy output UNCHANGED -------------------


def test_admit_returns_decision_unchanged_no_widening() -> None:
    sentinel = object()
    req = object()
    with mock.patch(f"{_MOD}.evaluate_dispatch_policy", return_value=sentinel) as ev:
        result = ClaudeAdapter().admit(req)  # type: ignore[arg-type]
    assert result is sentinel  # identical object — zero re-wrapping, zero added reason_codes
    ev.assert_called_once_with(req, now=None, candidate_requests=None)


def test_admit_passes_through_kwargs_verbatim() -> None:
    req = object()
    now = datetime(2026, 6, 20, tzinfo=UTC)
    cands = (object(), object())
    with mock.patch(f"{_MOD}.evaluate_dispatch_policy", return_value=object()) as ev:
        BudgetAuthorityAdapter().admit(req, now=now, candidate_requests=cands)  # type: ignore[arg-type]
    ev.assert_called_once_with(req, now=now, candidate_requests=cands)


# --- criterion 2: FINAL delegations are non-overridable (runtime guard, not just @final) -------


@pytest.mark.parametrize("final_method", ["describe", "admit", "observe", "collect_receipts"])
def test_final_delegations_cannot_be_overridden(final_method: str) -> None:
    with pytest.raises(TypeError, match="FINAL"):
        type("BadAdapter", (CapabilityAdapter,), {final_method: lambda self, *a, **k: None})


def test_overriding_a_non_final_hook_is_allowed() -> None:
    # preflight/classify_failure are the overridable surface — defining them must NOT raise.
    klass = type("OkAdapter", (CapabilityAdapter,), {"preflight": lambda self, request: ("hint",)})
    assert klass is not None


def test_describe_rejects_platform_mismatch() -> None:
    registry = SimpleNamespace(require=lambda rid: SimpleNamespace(platform=Platform.CODEX))
    with pytest.raises(ValueError, match="mismatch"):
        ClaudeAdapter().describe(registry, "codex.headless.full")  # type: ignore[arg-type]


def test_describe_returns_route_on_platform_match() -> None:
    route = SimpleNamespace(platform=Platform.CLAUDE, route_id="claude.headless.opus")
    registry = SimpleNamespace(require=lambda rid: route)
    assert ClaudeAdapter().describe(registry, "claude.headless.opus") is route  # type: ignore[arg-type]


# --- criterion 4: capability differences are TYPE-level (presence/absence, not flags) ----------


def test_worker_has_launch_and_sendcapable_has_send() -> None:
    assert hasattr(AgyAdapter, "launch")
    assert not hasattr(AgyAdapter, "send")
    assert hasattr(ClaudeAdapter, "launch")
    assert hasattr(ClaudeAdapter, "send")
    assert hasattr(CodexAdapter, "launch")
    assert hasattr(CodexAdapter, "send")
    assert hasattr(VibeAdapter, "launch")
    assert hasattr(VibeAdapter, "send")


def test_no_runtime_supports_send_flag_anywhere() -> None:
    # Capability is MRO presence, never a mutable boolean: no adapter (send-capable or not) may
    # grow a runtime supports_send flag — that is exactly the boutique-flag drift the type
    # hierarchy exists to prevent.
    for cls in (
        AgyAdapter,
        ClaudeAdapter,
        CodexAdapter,
        VibeAdapter,
        BudgetAuthorityAdapter,
        ReviewSeatAdapter,
        RetiredAntigravFailureClassifier,
    ):
        assert not hasattr(cls, "supports_send"), cls.__name__
    assert not issubclass(AgyAdapter, SendCapableAdapter)
    assert not issubclass(BudgetAuthorityAdapter, SendCapableAdapter)
    assert not issubclass(ReviewSeatAdapter, SendCapableAdapter)
    assert issubclass(ClaudeAdapter, SendCapableAdapter)
    assert issubclass(CodexAdapter, SendCapableAdapter)
    assert issubclass(VibeAdapter, SendCapableAdapter)


def test_budget_authority_has_no_launch_or_send() -> None:
    assert not hasattr(BudgetAuthorityAdapter, "launch")
    assert not hasattr(BudgetAuthorityAdapter, "send")
    with pytest.raises(AttributeError):
        BudgetAuthorityAdapter().launch  # type: ignore[attr-defined]


def test_review_seat_has_no_launch_or_send() -> None:
    assert not hasattr(ReviewSeatAdapter, "launch")
    assert not hasattr(ReviewSeatAdapter, "send")


def test_retired_antigrav_has_no_adapter_launch_or_send_surface() -> None:
    adapter_protocol = sys.modules[_MOD]
    assert "AntigravAdapter" not in adapter_protocol.__all__
    assert not hasattr(adapter_protocol, "AntigravAdapter")
    assert not hasattr(RetiredAntigravFailureClassifier, "launch")
    assert not hasattr(RetiredAntigravFailureClassifier, "send")
    assert not issubclass(RetiredAntigravFailureClassifier, CapabilityAdapter)
    assert not issubclass(RetiredAntigravFailureClassifier, WorkerAdapter)
    assert not issubclass(RetiredAntigravFailureClassifier, SendCapableAdapter)


def test_platform_classvars_are_pinned() -> None:
    assert AgyAdapter.PLATFORM is Platform.AGY
    assert ClaudeAdapter.PLATFORM is Platform.CLAUDE
    assert CodexAdapter.PLATFORM is Platform.CODEX
    assert VibeAdapter.PLATFORM is Platform.VIBE
    assert BudgetAuthorityAdapter.PLATFORM is Platform.API
    assert ReviewSeatAdapter.PLATFORM is Platform.GLMCP
    assert RetiredAntigravFailureClassifier.PLATFORM is Platform.ANTIGRAV


# --- criterion 5: launch() FIRST asserts authority, else AuthorityViolation --------------------


@pytest.mark.parametrize(
    "action",
    [DispatchAction.REFUSE, DispatchAction.HOLD, DispatchAction.SUPPORT_ONLY],
)
def test_launch_raises_authority_violation_before_side_effect(action: DispatchAction) -> None:
    decision = _decision(action=action, launch_allowed=False, reason_codes=("blocked",))
    launch_callable = mock.Mock(return_value=0)
    with mock.patch(f"{_MOD}.run_atomic_dispatch_launch") as spawn:
        with pytest.raises(AuthorityViolation, match="not authorized"):
            ClaudeAdapter().launch(decision, object(), launch_callable)  # type: ignore[arg-type]
    launch_callable.assert_not_called()  # gate fired BEFORE any side effect
    spawn.assert_not_called()


def test_launch_raises_when_action_launch_but_not_allowed() -> None:
    # defends the decoupled case: action LAUNCH yet launch_allowed False must still refuse.
    decision = _decision(action=DispatchAction.LAUNCH, launch_allowed=False)
    with mock.patch(f"{_MOD}.run_atomic_dispatch_launch") as spawn:
        with pytest.raises(AuthorityViolation):
            ClaudeAdapter().launch(decision, object(), lambda: 0)  # type: ignore[arg-type]
    spawn.assert_not_called()


def test_launch_happy_path_delegates_to_coord_dispatch() -> None:
    decision = _decision(action=DispatchAction.LAUNCH, launch_allowed=True)
    request = object()
    launch_callable = lambda: 0  # noqa: E731
    sentinel_result = object()
    with mock.patch(f"{_MOD}.run_atomic_dispatch_launch", return_value=sentinel_result) as spawn:
        result = CodexAdapter().launch(decision, request, launch_callable)  # type: ignore[arg-type]
    assert result is sentinel_result
    spawn.assert_called_once_with(request, launch_callable)


@pytest.mark.parametrize("adapter_cls", [AgyAdapter, VibeAdapter])
def test_new_worker_adapters_inherit_launch_gate(adapter_cls: type[WorkerAdapter]) -> None:
    decision = _decision(action=DispatchAction.LAUNCH, launch_allowed=True)
    request = object()
    launch_callable = lambda: 0  # noqa: E731
    sentinel_result = object()
    with mock.patch(f"{_MOD}.run_atomic_dispatch_launch", return_value=sentinel_result) as spawn:
        result = adapter_cls().launch(decision, request, launch_callable)  # type: ignore[arg-type]
    assert result is sentinel_result
    spawn.assert_called_once_with(request, launch_callable)


# --- SESSION gate: send() is the authority-checked egress boundary ------------------------------


def test_send_asserts_authority_before_any_egress_side_effect(tmp_path) -> None:
    refuse = _decision(action=DispatchAction.REFUSE, launch_allowed=False)
    runner = mock.Mock(return_value=0)
    receipts = tmp_path / "receipts.jsonl"
    with pytest.raises(AuthorityViolation, match="not authorized"):
        ClaudeAdapter().send(refuse, "hello", relay_runner=runner, receipts_path=receipts)
    runner.assert_not_called()  # authority fired BEFORE the relay
    assert not receipts.exists()  # ... and BEFORE any receipt side effect


@pytest.mark.parametrize(
    ("adapter_cls", "platform", "lane", "wrapper"),
    [
        (ClaudeAdapter, "claude", "eta", "hapax-claude-send"),
        (CodexAdapter, "codex", "cx-cap", "hapax-codex-send"),
        (VibeAdapter, "vibe", "vbe-1", "hapax-vibe-send"),
    ],
)
def test_send_routes_through_canonical_relay_and_mints_receipt(
    adapter_cls, platform: str, lane: str, wrapper: str, tmp_path
) -> None:
    decision = _decision(
        action=DispatchAction.LAUNCH,
        launch_allowed=True,
        platform=platform,
        lane=lane,
        route_id=f"{platform}.headless.full",
    )
    seen: list[tuple[str, ...]] = []

    def runner(argv: tuple[str, ...]) -> int:
        seen.append(argv)
        return 0

    receipts = tmp_path / "receipts.jsonl"
    now = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)
    receipt = adapter_cls().send(
        decision, "do the thing", relay_runner=runner, now=now, receipts_path=receipts
    )
    # canonical relay only: the argv targets scripts/hapax-<platform>-send with the decision lane
    assert len(seen) == 1
    argv = seen[0]
    assert argv[0].endswith(f"scripts/{wrapper}")
    assert argv[1:3] == ("--session", lane)
    assert argv[-2:] == ("--", "do the thing")
    # the receipt is the SESSION-gate authority result the reins consumer lights up on
    assert receipt.outcome == "sent" and receipt.exit_code == 0
    assert receipt.relay_wrapper == f"scripts/{wrapper}"
    assert receipt.platform == platform and receipt.lane == lane
    assert receipt.route_id == f"{platform}.headless.full"
    assert receipt.authority_action == "launch" and receipt.authority_launch_allowed is True
    assert receipt.message_sha256 == sha256(b"do the thing").hexdigest()
    assert receipt.message_chars == len("do the thing")
    # ... and it was appended to the evidence bus as one JSON line
    lines = receipts.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["receipt_id"] == receipt.receipt_id


def test_send_receipt_carries_no_message_body(tmp_path) -> None:
    # privacy_or_secret_sensitive route: the evidence bus must never persist message content.
    decision = _decision(action=DispatchAction.LAUNCH, launch_allowed=True, lane="eta")
    receipts = tmp_path / "receipts.jsonl"
    secret = "hunter2-super-secret-payload"
    ClaudeAdapter().send(decision, secret, relay_runner=lambda argv: 0, receipts_path=receipts)
    on_disk = receipts.read_text(encoding="utf-8")
    assert secret not in on_disk
    assert sha256(secret.encode("utf-8")).hexdigest() in on_disk


def test_send_failed_relay_mints_failed_receipt(tmp_path) -> None:
    decision = _decision(action=DispatchAction.LAUNCH, launch_allowed=True, lane="eta")
    receipts = tmp_path / "receipts.jsonl"
    receipt = ClaudeAdapter().send(
        decision, "msg", relay_runner=lambda argv: 3, receipts_path=receipts
    )
    assert receipt.outcome == "failed" and receipt.exit_code == 3
    # a failed relay still leaves lossless evidence — but it is NOT a "sent" light-up signal
    assert json.loads(receipts.read_text(encoding="utf-8"))["outcome"] == "failed"


def test_send_platform_mismatch_is_wiring_bug_not_authority_breach(tmp_path) -> None:
    codex_decision = _decision(
        action=DispatchAction.LAUNCH, launch_allowed=True, platform="codex", lane="cx-cap"
    )
    runner = mock.Mock(return_value=0)
    receipts = tmp_path / "receipts.jsonl"
    with pytest.raises(ValueError, match="mismatch"):
        ClaudeAdapter().send(codex_decision, "x", relay_runner=runner, receipts_path=receipts)
    runner.assert_not_called()
    assert not receipts.exists()


def test_send_cannot_be_overridden_no_boutique_paths() -> None:
    # the __init_subclass__ guard: a per-engine send override IS the boutique-path failure mode.
    with pytest.raises(TypeError, match="boutique"):
        type("BadSendAdapter", (ClaudeAdapter,), {"send": lambda self, d, m: "hijacked"})
    with pytest.raises(TypeError, match="boutique"):
        type("BadMixinSub", (SendCapableAdapter,), {"send": lambda self, d, m: "hijacked"})


def test_send_on_bare_mixin_fails_closed() -> None:
    # a bare mixin has no PLATFORM, hence no governed relay target: fail closed AFTER authority.
    allow = _decision(action=DispatchAction.LAUNCH, launch_allowed=True)
    with pytest.raises(TypeError, match="PLATFORM"):
        SendCapableAdapter().send(allow, "x", relay_runner=lambda argv: 0)


# --- collect_receipts delegation ---------------------------------------------------------------


def test_collect_receipts_delegates_with_default_key() -> None:
    request = SimpleNamespace(effective_idempotency_key="k-default")
    sentinel = object()
    with mock.patch(f"{_MOD}.replay_terminal_result", return_value=sentinel) as replay:
        result = ClaudeAdapter().collect_receipts(request)  # type: ignore[arg-type]
    assert result is sentinel
    replay.assert_called_once_with(request, idempotency_key="k-default")


def test_collect_receipts_honors_explicit_key_and_none_result() -> None:
    request = SimpleNamespace(effective_idempotency_key="k-default")
    with mock.patch(f"{_MOD}.replay_terminal_result", return_value=None) as replay:
        result = ClaudeAdapter().collect_receipts(request, idempotency_key="k-explicit")  # type: ignore[arg-type]
    assert result is None
    replay.assert_called_once_with(request, idempotency_key="k-explicit")


# --- observe delegation ------------------------------------------------------------------------


def test_observe_delegates_to_registry_freshness() -> None:
    registry = object()
    now = datetime(2026, 6, 20, tzinfo=UTC)
    sentinel = object()
    with mock.patch(f"{_MOD}.check_registry_freshness", return_value=sentinel) as chk:
        result = BudgetAuthorityAdapter().observe(registry, now=now)  # type: ignore[arg-type]
    assert result is sentinel
    chk.assert_called_once_with(registry, now=now)


# --- criterion 6 + classify_failure -------------------------------------------------------------


def test_base_classify_failure_defaults_unknown_no_degrade() -> None:
    r = BudgetAuthorityAdapter().classify_failure("ambiguous prose mentioning quota")
    assert r.code is FailureCode.UNKNOWN
    assert r.raw_signal == "ambiguous prose mentioning quota"  # lossless
    assert r.platform == Platform.API.value


def test_review_seat_classify_failure_uses_shared_zai_table() -> None:
    error_class = ZAI_ERROR_CLASS_BY_CODE["1310"][0]  # 1310 -> QUOTA_EXHAUSTION
    r = ReviewSeatAdapter().classify_failure("boom", error_class=error_class)
    assert r.code is failure_code_for_zai(error_class)
    assert r.code is FailureCode.QUOTA_EXHAUSTION
    assert r.error_class == error_class and r.platform == Platform.GLMCP.value
    # no structured error_class -> UNKNOWN (never auto-degrades on ambiguous text)
    assert ReviewSeatAdapter().classify_failure("boom").code is FailureCode.UNKNOWN


def test_claude_classify_failure_table() -> None:
    adapter = ClaudeAdapter()
    assert (
        adapter.classify_failure("You've hit your weekly limit").code
        is FailureCode.QUOTA_EXHAUSTION
    )
    assert adapter.classify_failure("usage limit reached").code is FailureCode.QUOTA_EXHAUSTION
    # the actual Claude Code phrasing (verb before 'limit') — the common case the old pattern missed
    assert (
        adapter.classify_failure("You've hit your usage limit · resets 5pm").code
        is FailureCode.QUOTA_EXHAUSTION
    )
    assert (
        adapter.classify_failure("Error: RESOURCE_EXHAUSTED").code is FailureCode.QUOTA_EXHAUSTION
    )
    assert adapter.classify_failure("invalid x-api-key provided").code is FailureCode.AUTH_FAILURE
    assert adapter.classify_failure("Error: overloaded_error (529)").code is FailureCode.TRANSIENT
    unknown = adapter.classify_failure("a perfectly ordinary review of some code")
    assert unknown.code is FailureCode.UNKNOWN
    assert unknown.platform == Platform.CLAUDE.value and unknown.raw_signal.startswith(
        "a perfectly"
    )


def test_codex_classify_failure_shares_the_cli_table() -> None:
    adapter = CodexAdapter()
    assert adapter.classify_failure("service unavailable").code is FailureCode.TRANSIENT
    assert adapter.classify_failure("nothing notable").code is FailureCode.UNKNOWN
    assert adapter.classify_failure("x").platform == Platform.CODEX.value


def test_agy_classify_failure_shares_the_cli_table() -> None:
    adapter = AgyAdapter()
    assert (
        adapter.classify_failure("HTTP 429 Too Many Requests").code is FailureCode.QUOTA_EXHAUSTION
    )
    assert adapter.classify_failure("service unavailable").code is FailureCode.TRANSIENT
    assert adapter.classify_failure("nothing notable").code is FailureCode.UNKNOWN
    assert adapter.classify_failure("x").platform == Platform.AGY.value


def test_vibe_classify_failure_shares_the_cli_table() -> None:
    adapter = VibeAdapter()
    assert adapter.classify_failure("service unavailable").code is FailureCode.TRANSIENT
    assert adapter.classify_failure("nothing notable").code is FailureCode.UNKNOWN
    assert adapter.classify_failure("x").platform == Platform.VIBE.value


def test_retired_antigrav_failure_classifier_maps_historical_launcher_exit_codes() -> None:
    a = RetiredAntigravFailureClassifier()
    # the two codes with a genuine availability/claim meaning map; everything else stays UNKNOWN
    assert a.classify_failure("agy not found", exit_code=4).code is FailureCode.ROUTE_UNAVAILABLE
    assert a.classify_failure("cc-claim failed", exit_code=8).code is FailureCode.CLAIM_CONFLICT
    for ec in (2, 3, 5, 6, 9, 99):  # usage/env/setup + unmapped -> no auto-degrade
        assert a.classify_failure("x", exit_code=ec).code is FailureCode.UNKNOWN
    assert a.classify_failure("no exit code given").code is FailureCode.UNKNOWN
    receipt = a.classify_failure("Antigravity CLI not found", exit_code=4)
    assert receipt.platform == Platform.ANTIGRAV.value
    assert receipt.raw_signal == "Antigravity CLI not found"  # lossless
    # neither mapped code degrades family availability (not in the witness allowlist)
    from shared.worker_failure_witness import WORKER_AVAILABILITY_DEGRADE_CODES

    assert FailureCode.ROUTE_UNAVAILABLE not in WORKER_AVAILABILITY_DEGRADE_CODES
    assert FailureCode.CLAIM_CONFLICT not in WORKER_AVAILABILITY_DEGRADE_CODES


# --- mixin hygiene -----------------------------------------------------------------------------


def test_sendcapable_is_not_a_capability_adapter_subclass() -> None:
    # The mixin must NOT inherit CapabilityAdapter (else defining it would trip the FINAL guard).
    assert not issubclass(SendCapableAdapter, CapabilityAdapter)
    assert issubclass(ClaudeAdapter, CapabilityAdapter)
    assert issubclass(ClaudeAdapter, WorkerAdapter)
    assert issubclass(ClaudeAdapter, SendCapableAdapter)
