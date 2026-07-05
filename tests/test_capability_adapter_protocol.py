"""Tests for the CapabilityAdapter protocol + type hierarchy (capability-adapter-protocol-module)."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
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
) -> RouteDecision:
    """Build a REAL RouteDecision (the type the dispatcher returns) for the authority tests."""

    return RouteDecision(
        decision_id="d-test",
        created_at=datetime(2026, 6, 20, tzinfo=UTC),
        task_id="t",
        lane="cc-sdlc",
        route_id=route_id,
        platform="claude",
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


def test_send_asserts_authority_then_is_not_yet_wired() -> None:
    # send gates authority just like launch; the relay itself is a glue-slice concern.
    refuse = _decision(action=DispatchAction.REFUSE, launch_allowed=False)
    with pytest.raises(AuthorityViolation):
        ClaudeAdapter().send(refuse, "hello")
    allow = _decision(action=DispatchAction.LAUNCH, launch_allowed=True)
    with pytest.raises(NotImplementedError):
        ClaudeAdapter().send(allow, "hello")


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
