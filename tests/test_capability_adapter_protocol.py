"""Tests for the CapabilityAdapter protocol + type hierarchy (capability-adapter-protocol-module)."""

from __future__ import annotations

import ast
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from hapax.context_canon import (
    ContextFrame,
    ContextSelection,
    ContextSelectionEntry,
    build_context_selection,
)
from hapax.context_canon.contract import (
    _domain_hash,
    signal_constellation_loss_manifest_ref,
)

import shared.execution_admission as execution_admission
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
from shared.coord_dispatch import DispatchLaunchRequest
from shared.dispatcher_policy import DispatchAction, DispatchRequest, RouteDecision
from shared.epistemic_impingement import build_epistemic_impingement_trace
from shared.execution_admission import (
    DEFAULT_EXECUTION_COMPOSITION_ROOT,
    AuthorityHold,
    CompletionEvaluator,
    ContentAddress,
    EffectManifestResolver,
    ExecutionAdmissionError,
    ExecutionCompositionManifest,
    ExecutionCompositionPorts,
    ExecutionCompositionRoot,
    ExecutionCurrentnessResolver,
    ExecutionExecutorBinding,
    ExecutionExecutorError,
    ExecutionExecutorRegistry,
    ExecutionInvocationBundle,
    ExecutionInvocationBundlePointer,
    ExecutionInvocationBundleStore,
    ExecutionInvocationContext,
    ExecutionLease,
    ExecutionTrustResolver,
    HistoricalSupportDisposition,
    OutcomeCommitter,
    OutcomePipelineReadinessResolver,
    ProspectiveClaimResolution,
    ProtectedActionRequest,
    RootDisposition,
    ValidAuthorityGrant,
    admit_execution,
    build_action_intent,
    build_authority_evidence,
    build_bound_execution_call,
    build_dependency_closure_evidence,
    build_effect_manifest,
    build_execution_composition_manifest,
    build_execution_composition_port_descriptors,
    build_execution_currentness_envelope,
    build_execution_currentness_query,
    build_execution_invocation_bundle,
    build_execution_invocation_bundle_pointer,
    build_execution_lease_issuer_trust_query,
    build_execution_target_evidence,
    build_execution_trust_envelope,
    build_execution_trust_query,
    build_executor_descriptor,
    build_executor_registry_projection,
    build_outcome_replay_catalog_snapshot,
    build_prospective_claim_publication_basis,
    build_prospective_claim_publication_carrier,
    build_protected_action_request,
    build_protected_aperture_decision,
    build_protected_claim_coordinates,
    build_quota_reservation_evidence,
    content_address,
    evaluate_protected_action,
    execution_admission_schema,
    execution_composition_manifest_bytes,
    mint_execution_lease,
    module_file_address,
    parse_execution_lease_record,
    project_execution_invocation_context,
    protected_raw_invocation_address,
    require_admitted_execution_lease,
    require_current_execution_lease,
    require_protected_action,
    validate_authority,
)
from shared.failure_classification import (
    ZAI_ERROR_CLASS_BY_CODE,
    FailureCode,
    failure_code_for_zai,
)
from shared.platform_capability_registry import (
    Platform,
    PlatformCapabilityRegistry,
    build_supply_vector,
)
from shared.route_metadata_schema import build_demand_vector
from shared.sdlc_claim import (
    ClaimAdmissionConsumption,
    ClaimPublicationError,
    ClaimPublicationIntent,
    claim_publication_task_note_address,
    prospective_claim_publication_basis,
    publish_admitted_claim,
    publish_claim,
)
from shared.sdlc_task_store import ClaimDispatchBinding, resolve_task_note

_MOD = "shared.capability_adapter_protocol"
QUERY_TIME = datetime(2026, 7, 10, 16, 8, tzinfo=UTC)


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
    req = _execution_admission_fixture().policy_request
    with mock.patch(f"{_MOD}.evaluate_dispatch_policy", return_value=sentinel) as ev:
        result = ClaudeAdapter().admit(req, now=QUERY_TIME)
    assert result is sentinel  # identical object — zero re-wrapping, zero added reason_codes
    called = ev.call_args.kwargs
    assert ev.call_args.args[0] == req
    assert ev.call_args.args[0] is not req
    assert called == {"now": QUERY_TIME, "candidate_requests": None}


def test_admit_passes_through_kwargs_verbatim() -> None:
    calls: list[str] = []
    duck = SimpleNamespace(model_dump=lambda **_kwargs: calls.append("model_dump"))
    with mock.patch(f"{_MOD}.evaluate_dispatch_policy") as ev:
        with pytest.raises(TypeError, match="exact dispatch request"):
            BudgetAuthorityAdapter().admit(duck, now=QUERY_TIME)  # type: ignore[arg-type]
    assert calls == []
    ev.assert_not_called()


# --- criterion 2: FINAL delegations are non-overridable (runtime guard, not just @final) -------


@pytest.mark.parametrize("final_method", ["describe", "admit", "observe", "collect_receipts"])
def test_final_delegations_cannot_be_overridden(final_method: str) -> None:
    with pytest.raises(TypeError, match="FINAL"):
        type("BadAdapter", (CapabilityAdapter,), {final_method: lambda self, *a, **k: None})


def test_overriding_a_non_final_hook_is_allowed() -> None:
    # preflight/classify_failure are the overridable surface — defining them must NOT raise.
    klass = type("OkAdapter", (CapabilityAdapter,), {"preflight": lambda self, request: ("hint",)})
    assert klass is not None


def test_public_effect_gates_cannot_be_overridden() -> None:
    with pytest.raises(TypeError, match="may not override WorkerAdapter.launch"):
        type("BadWorker", (CodexAdapter,), {"launch": lambda self, *a, **k: None})
    with pytest.raises(TypeError, match="may not override SendCapableAdapter.send"):
        type("BadSender", (CodexAdapter,), {"send": lambda self, *a, **k: None})


def test_describe_rejects_duck_registry_before_method_dispatch() -> None:
    calls: list[str] = []
    registry = SimpleNamespace(require=lambda _rid: calls.append("require"))
    with pytest.raises(TypeError, match="exact platform capability registry"):
        ClaudeAdapter().describe(registry, "claude.headless.opus")  # type: ignore[arg-type]
    assert calls == []


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
    with mock.patch(f"{_MOD}.run_atomic_dispatch_launch") as spawn:
        with pytest.raises(AuthorityViolation, match="not authorized"):
            ClaudeAdapter().launch(  # type: ignore[arg-type]
                decision,
                object(),
                composition=object(),
                invocation_pointer=object(),
                queried_at=QUERY_TIME,
            )
    spawn.assert_not_called()


def test_launch_raises_when_action_launch_but_not_allowed() -> None:
    # defends the decoupled case: action LAUNCH yet launch_allowed False must still refuse.
    decision = _decision(action=DispatchAction.LAUNCH, launch_allowed=False)
    with mock.patch(f"{_MOD}.run_atomic_dispatch_launch") as spawn:
        with pytest.raises(AuthorityViolation):
            ClaudeAdapter().launch(  # type: ignore[arg-type]
                decision,
                object(),
                composition=object(),
                invocation_pointer=object(),
                queried_at=QUERY_TIME,
            )
    spawn.assert_not_called()


def test_launch_transports_exact_composition_pointer_to_coord_dispatch(
    tmp_path: Path,
) -> None:
    fixture = _real_execution_invocation(tmp_path)
    manifest, store, composition = _configured_execution_composition(fixture, tmp_path)
    _, pointer, _ = _materialize_read_only_bundle_fixture(fixture, manifest, store)
    sentinel_result = object()
    with mock.patch(f"{_MOD}.run_atomic_dispatch_launch", return_value=sentinel_result) as spawn:
        result = CodexAdapter().launch(
            fixture.decision,
            fixture.request,
            composition=composition,
            invocation_pointer=pointer,
            queried_at=QUERY_TIME,
        )
    assert result is sentinel_result
    spawn.assert_called_once_with(
        fixture.request,
        composition=composition,
        invocation_pointer=pointer,
        queried_at=QUERY_TIME,
    )


def test_launch_requires_composition_pointer_before_coord_dispatch() -> None:
    decision = _decision(action=DispatchAction.LAUNCH, launch_allowed=True)
    with mock.patch(f"{_MOD}.run_atomic_dispatch_launch") as spawn:
        with pytest.raises(AuthorityViolation, match="exact dispatch request"):
            CodexAdapter().launch(  # type: ignore[arg-type]
                decision,
                object(),
                composition=object(),
                invocation_pointer=object(),
                queried_at=QUERY_TIME,
            )
    spawn.assert_not_called()


@pytest.mark.parametrize("adapter_cls", [AgyAdapter, VibeAdapter])
def test_worker_adapters_refuse_another_platforms_admitted_invocation(
    adapter_cls: type[WorkerAdapter],
    tmp_path: Path,
) -> None:
    fixture = _real_execution_invocation(tmp_path)
    with mock.patch(f"{_MOD}.run_atomic_dispatch_launch") as spawn:
        with pytest.raises(AuthorityViolation, match="request binding mismatch"):
            adapter_cls().launch(
                fixture.decision,
                fixture.request,
                composition=object(),  # type: ignore[arg-type]
                invocation_pointer=object(),  # type: ignore[arg-type]
                queried_at=QUERY_TIME,
            )
    spawn.assert_not_called()


def test_vibe_adapter_marks_registered_send_surface() -> None:
    assert issubclass(VibeAdapter, SendCapableAdapter)


def test_send_asserts_authority_and_holds_before_gate0b_activation(
    tmp_path: Path,
) -> None:
    # send gates authority just like launch; the relay itself is a glue-slice concern.
    refuse = _decision(action=DispatchAction.REFUSE, launch_allowed=False)
    with pytest.raises(AuthorityViolation):
        ClaudeAdapter().send(  # type: ignore[arg-type]
            refuse,
            _execution_address("message:test"),
            composition=object(),
            invocation_pointer=object(),
            queried_at=QUERY_TIME,
        )
    allow = _decision(action=DispatchAction.LAUNCH, launch_allowed=True)
    with pytest.raises(AuthorityViolation, match="exact execution composition"):
        ClaudeAdapter().send(  # type: ignore[arg-type]
            allow,
            _execution_address("message:test"),
            composition=object(),
            invocation_pointer=object(),
            queried_at=QUERY_TIME,
        )
    fixture = _real_execution_invocation(tmp_path)
    manifest, store, composition = _configured_execution_composition(fixture, tmp_path)
    _, pointer, _ = _materialize_read_only_bundle_fixture(fixture, manifest, store)
    with pytest.raises(AuthorityViolation, match="route binding mismatch"):
        CodexAdapter().send(
            fixture.decision,
            _execution_address("message:test"),
            composition=composition,
            invocation_pointer=pointer,
            queried_at=QUERY_TIME,
        )


# --- collect_receipts delegation ---------------------------------------------------------------


def test_collect_receipts_delegates_with_default_key() -> None:
    request = SimpleNamespace(effective_idempotency_key="k-default")
    sentinel = object()
    with mock.patch(f"{_MOD}.replay_terminal_result", return_value=sentinel) as replay:
        result = ClaudeAdapter().collect_receipts(
            request,  # type: ignore[arg-type]
            composition=object(),  # type: ignore[arg-type]
            invocation_pointer=object(),  # type: ignore[arg-type]
            queried_at=QUERY_TIME,
        )
    assert result is sentinel
    replay.assert_called_once_with(
        request,
        composition=mock.ANY,
        invocation_pointer=mock.ANY,
        queried_at=QUERY_TIME,
        idempotency_key=None,
    )


def test_collect_receipts_honors_explicit_key_and_none_result() -> None:
    request = SimpleNamespace(effective_idempotency_key="k-default")
    with mock.patch(f"{_MOD}.replay_terminal_result", return_value=None) as replay:
        result = ClaudeAdapter().collect_receipts(
            request,  # type: ignore[arg-type]
            composition=object(),  # type: ignore[arg-type]
            invocation_pointer=object(),  # type: ignore[arg-type]
            queried_at=QUERY_TIME,
            idempotency_key="k-explicit",
        )
    assert result is None
    replay.assert_called_once_with(
        request,
        composition=mock.ANY,
        invocation_pointer=mock.ANY,
        queried_at=QUERY_TIME,
        idempotency_key="k-explicit",
    )


# --- observe delegation ------------------------------------------------------------------------


def test_observe_rejects_duck_registry_before_freshness_dispatch() -> None:
    registry = object()
    with mock.patch(f"{_MOD}.check_registry_freshness") as chk:
        with pytest.raises(TypeError, match="exact platform capability registry"):
            BudgetAuthorityAdapter().observe(registry, now=QUERY_TIME)  # type: ignore[arg-type]
    chk.assert_not_called()


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
    assert (
        adapter.classify_failure("HTTP 429 Too Many Requests").code is FailureCode.QUOTA_EXHAUSTION
    )
    assert adapter.classify_failure("invalid api key").code is FailureCode.AUTH_FAILURE
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
    assert issubclass(VibeAdapter, CapabilityAdapter)
    assert issubclass(VibeAdapter, WorkerAdapter)
    assert issubclass(VibeAdapter, SendCapableAdapter)


# --- Gate-0 authority validation and execution admission --------------------------------------


def _frame_for_claim_intent(
    frame: ContextFrame,
    claim_intent_ref: str,
    mutation_scope_ref: str,
) -> ContextFrame:
    payload = frame.model_dump(mode="json", by_alias=True)

    def replace(value: object, old: str, new: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if item == old:
                    value[key] = new
                else:
                    replace(item, old, new)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if item == old:
                    value[index] = new
                else:
                    replace(item, old, new)

    def rehash(
        record: dict[str, object],
        *,
        domain: str,
        ref_field: str,
        hash_field: str,
        prefix: str,
    ) -> tuple[str, str]:
        old_ref = str(record[ref_field])
        body = {key: value for key, value in record.items() if key not in {ref_field, hash_field}}
        digest = _domain_hash(domain, body)
        new_ref = f"{prefix}@sha256:{digest}"
        record[hash_field] = digest
        record[ref_field] = new_ref
        return old_ref, new_ref

    position = payload["position"]
    assert isinstance(position, dict)
    position["claim_ref"] = claim_intent_ref
    position["mutation_scope_refs"] = [mutation_scope_ref]
    position["effective_constraint_digest"] = _domain_hash(
        "hapax.effective-constraints.v1",
        {
            "authority_case": position["authority_case"],
            "authorized_flags": position["authorized_flags"],
            "mutation_scope_refs": position["mutation_scope_refs"],
        },
    )

    actions = payload["actions"]
    assert isinstance(actions, list)
    publication = next(
        item
        for item in actions
        if isinstance(item, dict) and item.get("action_id") == "action:inspect"
    )
    publication.update(
        {
            "action_class": "claim_publication",
            "operation": "claim.publish",
            "label": "Publish exact governed claim",
            "predicted_effect": "The exact claim postimage is applied by the universal executor.",
            "recovery": "Retain the prospective carrier and reconcile before any retry.",
            "why": "Claim publication has an exact prospective basis and remains effect-gated.",
        }
    )
    old_position, new_position = rehash(
        position,
        domain="hapax.context-position.v1",
        ref_field="position_ref",
        hash_field="position_hash",
        prefix="context-position",
    )
    replace(payload, old_position, new_position)

    estimate = payload["signal_estimates"][0]
    old_estimate, new_estimate = rehash(
        estimate,
        domain="hapax.signal-estimate.v1",
        ref_field="estimate_ref",
        hash_field="estimate_hash",
        prefix="signal-estimate",
    )
    replace(payload, old_estimate, new_estimate)

    constellation = payload["signal_constellations"][0]
    constellation["loss_manifest_ref"] = signal_constellation_loss_manifest_ref(
        target_ref=constellation["target_ref"],
        lens_ref=constellation["lens_ref"],
        scope_ref=constellation["scope_ref"],
        resolution_ref=constellation["resolution_ref"],
        member_estimate_refs=tuple(constellation["member_estimate_refs"]),
        relation_refs=tuple(constellation["relation_refs"]),
        uncovered_source_refs=tuple(constellation["uncovered_source_refs"]),
        aggregation_ref=constellation["aggregation_ref"],
    )
    old_constellation, new_constellation = rehash(
        constellation,
        domain="hapax.signal-constellation.v1",
        ref_field="constellation_ref",
        hash_field="constellation_hash",
        prefix="signal-constellation",
    )
    replace(payload, old_constellation, new_constellation)

    signal = payload["orienting_signals"][0]
    rehash(
        signal,
        domain="hapax.orienting-signal.v1",
        ref_field="signal_ref",
        hash_field="signal_hash",
        prefix="orienting-signal",
    )

    learning = payload["signal_learning_receipts"][0]
    old_learning, new_learning = rehash(
        learning,
        domain="hapax.signal-learning-receipt.v1",
        ref_field="learning_ref",
        hash_field="learning_hash",
        prefix="signal-learning",
    )
    replace(payload, old_learning, new_learning)

    for event in sorted(payload["events"], key=lambda item: item["derivation_depth"]):
        old_event, new_event = rehash(
            event,
            domain="hapax.epistemic-flow-event.v1",
            ref_field="event_ref",
            hash_field="event_hash",
            prefix="epistemic-event",
        )
        replace(payload, old_event, new_event)

    orientation = payload["orientation_facets"][0]
    rehash(
        orientation,
        domain="hapax.boundary-orientation-facet.v1",
        ref_field="facet_ref",
        hash_field="facet_hash",
        prefix="boundary-orientation",
    )

    rehash(
        payload,
        domain="hapax.context-frame.v1",
        ref_field="frame_ref",
        hash_field="frame_hash",
        prefix="context-frame",
    )
    return ContextFrame.model_validate(payload)


def _execution_address(ref: str, value: object | None = None) -> ContentAddress:
    addressed = content_address(ref, value if value is not None else {"fixture": ref})
    return ContentAddress(ref=f"{ref}@sha256:{addressed.sha256}", sha256=addressed.sha256)


def _trust_resolver(
    *queries: object,
    authority_trusted: bool = True,
    resolver_address: ContentAddress | None = None,
) -> ExecutionTrustResolver:
    resolver_address = resolver_address or _execution_address("resolver:execution-trust")
    envelopes = []
    for query in queries:
        dispositions = []
        for index, root in enumerate(query.required_roots):
            untrusted_receipt = (
                not authority_trusted
                and query.trust_class == "authenticated_authority_receipt"
                and root == query.presented_receipt
            )
            dispositions.append(
                RootDisposition(
                    root=root,
                    disposition="revoked" if untrusted_receipt else "current",
                    superseding_roots=(),
                    reason_codes=("authority_receipt_untrusted",) if untrusted_receipt else (),
                    source_event_refs=(f"event:trust:{index}",),
                )
            )
        envelopes.append(
            build_execution_trust_envelope(
                query,
                resolver=resolver_address,
                decision="hold"
                if not authority_trusted and query.trust_class == "authenticated_authority_receipt"
                else "trusted",
                event_frontier=_execution_address("event-frontier:trust"),
                root_dispositions=dispositions,
                reason_codes=("authority_receipt_untrusted",)
                if not authority_trusted and query.trust_class == "authenticated_authority_receipt"
                else (),
                checked_at=query.queried_at,
                stale_after=datetime.fromisoformat(query.queried_at.replace("Z", "+00:00"))
                + timedelta(minutes=15),
            )
        )
    return ExecutionTrustResolver(
        resolver=resolver_address,
        envelopes=tuple(sorted(envelopes, key=lambda item: (item.query.ref, item.query.sha256))),
    )


def _currentness_resolver(
    query: object,
    *,
    noncurrent_ref: str | None = None,
) -> ExecutionCurrentnessResolver:
    resolver_address = _execution_address("resolver:execution-currentness")
    dispositions = []
    historical_dispositions = []
    held = False
    for index, root in enumerate(query.required_roots):
        noncurrent = root.ref == noncurrent_ref
        held = held or noncurrent
        dispositions.append(
            RootDisposition(
                root=root,
                disposition="revoked" if noncurrent else "current",
                superseding_roots=(),
                reason_codes=("root_revoked",) if noncurrent else (),
                source_event_refs=(f"event:currentness:{index}",),
            )
        )
    for index, root in enumerate(query.historical_support_roots):
        historical_dispositions.append(
            HistoricalSupportDisposition(
                root=root,
                disposition="present",
                reason_codes=(),
                source_event_refs=(f"event:historical-support:{index}",),
            )
        )
    envelope = build_execution_currentness_envelope(
        query,
        resolver=resolver_address,
        decision="hold" if held else "current",
        event_frontier=_execution_address("event-frontier:currentness"),
        root_dispositions=dispositions,
        historical_support_dispositions=historical_dispositions,
        idempotency_state="available",
        reason_codes=("root_revoked",) if held else (),
        checked_at=query.queried_at,
        stale_after=datetime.fromisoformat(query.queried_at.replace("Z", "+00:00"))
        + timedelta(minutes=10),
    )
    return ExecutionCurrentnessResolver(resolver=resolver_address, envelopes=(envelope,))


def _fixture_ports(
    fixture: SimpleNamespace,
    *,
    noncurrent_ref: str | None = None,
) -> ExecutionCompositionPorts:
    del noncurrent_ref
    currentness = ExecutionCurrentnessResolver(
        resolver=_execution_address("resolver:execution-currentness")
    )
    assert fixture.trust_resolver.resolver is not None
    assert fixture.manifest_resolver.resolver is not None
    assert currentness.resolver is not None
    outcome_committer = _execution_address("port:outcome-committer")
    event_plane = _execution_address("port:event-plane")
    outcome_projection_resolver = _execution_address("port:outcome-projection-resolver")
    outcome_validity_resolver = _execution_address("port:outcome-validity-resolver")
    empty_catalog = build_outcome_replay_catalog_snapshot(
        committer=outcome_committer,
        event_plane=event_plane,
        projection_resolver=outcome_projection_resolver,
        validity_resolver=outcome_validity_resolver,
        checked_frontier=_execution_address("event-frontier:empty"),
        projections=(),
        validity_envelopes=(),
        source_receipt=_execution_address("outcome-catalog-read:empty"),
        observed_at=fixture.now,
    )
    outcomes = OutcomeCommitter(
        committer=outcome_committer,
        event_plane=event_plane,
        projection_resolver=outcome_projection_resolver,
        validity_resolver=outcome_validity_resolver,
        catalog_snapshot=empty_catalog,
    )
    descriptors = build_execution_composition_port_descriptors(
        trust_resolver=fixture.trust_resolver.resolver,
        effect_manifest_resolver=fixture.manifest_resolver.resolver,
        currentness_resolver=currentness.resolver,
        executor_registry=_execution_address("port:executor-registry"),
        completion_evaluator=_execution_address("port:completion-evaluator"),
        readiness_resolver=_execution_address("port:readiness-resolver"),
        outcome_committer=outcome_committer,
        event_plane=event_plane,
        outcome_projection_resolver=outcome_projection_resolver,
        outcome_validity_resolver=outcome_validity_resolver,
    )
    return ExecutionCompositionPorts(
        descriptors=descriptors,
        trust=fixture.trust_resolver,
        manifests=fixture.manifest_resolver,
        currentness=currentness,
        executors=ExecutionExecutorRegistry(descriptor=descriptors.executor_registry),
        completion=CompletionEvaluator(evaluator=descriptors.completion_evaluator),
        readiness=OutcomePipelineReadinessResolver(
            resolver=descriptors.readiness_resolver,
        ),
        outcomes=outcomes,
    )


def _execution_admission_fixture(
    *,
    include_demand_receipt: bool = True,
    trusted_authority: bool = True,
    publication_intent: ClaimPublicationIntent | None = None,
    selection_case: str | None = None,
    local_execution_target: str = "appendix",
) -> SimpleNamespace:
    root = Path(__file__).resolve().parents[1]
    now = datetime(2026, 7, 10, 16, 6, tzinfo=UTC)
    frame_payload = json.loads(
        (
            root / "packages" / "hapax-context-canon" / "tests" / "fixtures" / "gate0-frame.json"
        ).read_text(encoding="utf-8")
    )
    for action in frame_payload["actions"]:
        action.setdefault(
            "operation",
            (
                action["lifecycle_operation"]
                if action["action_class"] == "lifecycle_operation"
                else "context.inspect"
            ),
        )
    frame_body = {
        key: value for key, value in frame_payload.items() if key not in {"frame_ref", "frame_hash"}
    }
    frame_digest = _domain_hash("hapax.context-frame.v1", frame_body)
    frame_payload["frame_ref"] = f"context-frame@sha256:{frame_digest}"
    frame_payload["frame_hash"] = frame_digest
    base_frame = ContextFrame.model_validate(frame_payload)
    if publication_intent is None:
        note_before = b"synthetic governed task note before publication\n"
        note_after = b"synthetic governed task note after publication\n"
        claim_intent_sha256 = execution_admission._sha256(b"synthetic claim publication intent")
        claim_publication_intent = ContentAddress(
            ref=f"claim-publication-intent@sha256:{claim_intent_sha256}",
            sha256=claim_intent_sha256,
        )
        task_note = ContentAddress(
            ref="/virtual/active/task:rich.md",
            sha256=execution_admission._sha256(note_before),
        )
        prospective_basis = build_prospective_claim_publication_basis(
            claim_publication_intent=claim_publication_intent,
            task_ref=base_frame.task_ref,
            lane="cx-test",
            session_ref="session:test",
            claim_epoch=1_720_629_960,
            authority_case=base_frame.position.authority_case,
            dispatch_message_id="dispatch-message:test",
            dispatch_binding_hash="b" * 64,
            dispatch_binding_receipt_hash="d" * 64,
            coord_dispatch_idempotency_key="idempotency:test",
            claim_mode="claim",
            from_status="offered",
            to_status="claimed",
            task_note_before_sha256=task_note.sha256,
            task_note_after_sha256=execution_admission._sha256(note_after),
            task_note_mode=0o600,
            mutation_scope_hash=execution_admission._sha256(
                b"synthetic claim publication mutation scope"
            ),
        )
    else:
        claim_publication_intent = ContentAddress(
            ref=publication_intent.intent_ref,
            sha256=publication_intent.intent_sha256,
        )
        prospective_basis = prospective_claim_publication_basis(publication_intent)
        task_note = claim_publication_task_note_address(publication_intent)
        note_after = publication_intent.note_after
    prospective_carrier = build_prospective_claim_publication_carrier(
        prospective_basis,
        note_after=note_after,
    )
    mutation_scope = ContentAddress(
        ref=(f"claim-publication-mutation-scope@sha256:{prospective_basis.mutation_scope_hash}"),
        sha256=prospective_basis.mutation_scope_hash,
    )
    frame = _frame_for_claim_intent(
        base_frame,
        claim_publication_intent.ref,
        mutation_scope.ref,
    )
    position = frame.position
    fact_refs = tuple(sorted(item.fact_id for item in frame.facts))
    event_refs = tuple(sorted(item.event_ref for item in frame.events))
    fact_frontier = _execution_address(
        "fact-frontier:fixture",
        {"event_refs": event_refs, "fact_refs": fact_refs},
    )
    trace = build_epistemic_impingement_trace(
        position,
        session_ref=frame.session_ref,
        fact_frontier_ref=fact_frontier.ref,
        fact_refs=fact_refs,
        source_event_refs=event_refs,
        impingements=frame.impingements,
        portal_offers=frame.portal_offers,
        method_ref="method:test-gate0-admission",
        observed_at=now,
        checked_at=now,
        stale_after=now + timedelta(minutes=30),
    )
    audience_seal = _execution_address(
        "audience-seal:fixture",
        {
            "audience": "hapax_substrate",
            "audience_policy_generation": frame.audience_policy_generation,
            "privacy_policy_generation": frame.privacy_policy_generation,
        },
    )
    selection_policy = _execution_address(
        "context-selection-policy:fixture",
        {"generation": "selection-policy:g1"},
    )
    selection_position = position
    selection_frontier = fact_frontier
    selection_fact_refs = fact_refs
    selection_event_refs = event_refs
    selection_audience = "hapax_substrate"
    selection_seal = audience_seal
    selection_audience_generation = frame.audience_policy_generation
    selection_privacy_generation = frame.privacy_policy_generation
    selection_checked_at = "2026-07-10T16:06:00Z"
    selection_stale_after = "2026-07-10T16:26:00Z"
    selection_entries = tuple(
        sorted(
            (
                ContextSelectionEntry(
                    fact_ref=fact_ref,
                    requiredness=(
                        "optional"
                        if fact_ref in {"fact:capability-gap", "fact:private-canary"}
                        else "required"
                    ),
                    classes=(
                        ("loss_bearing", "selected")
                        if fact_ref == "fact:capability-gap"
                        else ("redacted",)
                        if fact_ref == "fact:private-canary"
                        else ("selected",)
                    ),
                    reason_codes=(
                        ("independent_measurement_missing",)
                        if fact_ref == "fact:capability-gap"
                        else ("audience_policy_redaction",)
                        if fact_ref == "fact:private-canary"
                        else ()
                    ),
                )
                for fact_ref in fact_refs
            ),
            key=lambda entry: entry.fact_ref,
        )
    )
    if selection_case == "position_mismatch":
        selection_position = _frame_for_claim_intent(
            frame,
            "claim-publication-intent:alternate",
            mutation_scope.ref,
        ).position
    elif selection_case == "fact_frontier_mismatch":
        selection_frontier = _execution_address("fact-frontier:other")
    elif selection_case == "trace_frontier_mismatch":
        selection_fact_refs = (*fact_refs, "fact:extra")
        selection_entries = (
            *selection_entries,
            ContextSelectionEntry(
                fact_ref="fact:extra",
                requiredness="optional",
                classes=("selected",),
                reason_codes=(),
            ),
        )
    elif selection_case == "audience_seal_mismatch":
        selection_seal = _execution_address("audience-seal:other")
    elif selection_case == "policy_generation_mismatch":
        selection_audience_generation = "audience:other"
        selection_privacy_generation = "privacy:other"
    elif selection_case == "wrong_audience":
        selection_audience = "operator_private"
    elif selection_case == "hold":
        selection_entries = (
            *selection_entries,
            ContextSelectionEntry(
                fact_ref="fact:required-missing",
                requiredness="required",
                classes=("missing",),
                reason_codes=("source_unavailable",),
            ),
        )
    elif selection_case == "stale":
        selection_checked_at = "2026-07-10T16:04:00Z"
        selection_stale_after = "2026-07-10T16:05:00Z"
    selection = build_context_selection(
        selection_position,
        fact_frontier_ref=selection_frontier.ref,
        fact_frontier_hash=selection_frontier.sha256,
        frontier_fact_refs=selection_fact_refs,
        event_frontier_refs=selection_event_refs,
        audience=selection_audience,
        audience_seal_receipt_ref=selection_seal.ref,
        audience_seal_receipt_hash=selection_seal.sha256,
        audience_policy_generation=selection_audience_generation,
        privacy_policy_generation=selection_privacy_generation,
        selection_policy_ref=selection_policy.ref,
        selection_policy_hash=selection_policy.sha256,
        selection_policy_generation="selection-policy:g1",
        entries=selection_entries,
        checked_at=selection_checked_at,
        stale_after=selection_stale_after,
    )
    selection_input: ContextSelection | ContentAddress = selection
    if selection_case == "legacy_address":
        selection_input = _execution_address("context-selection:legacy")

    effect_scope = (mutation_scope.ref,)
    effect_targets = (mutation_scope,)
    manifest = build_effect_manifest(
        operation="claim.publish",
        capability_role="worker",
        execution_host="appendix",
        mutating=True,
        external_effect=False,
        effect_classes=("claim_publication",),
        effect_targets=effect_targets,
        scope_refs=effect_scope,
        observation_contract=_execution_address("observation-contract:test"),
        completion_predicate=_execution_address("completion-predicate:test"),
        idempotence_class="idempotent",
        reconciliation_contract=_execution_address("reconciliation-contract:test"),
        compensation=None,
    )
    acting_subject = _execution_address("subject:test")
    admission_module = module_file_address(Path(execution_admission.__file__))
    ingress_module = module_file_address(Path(__file__))
    runtime_identity = _execution_address("runtime:test")
    raw_invocation = protected_raw_invocation_address(
        {
            "argv": ["claim", "publish"],
            "cwd": str(root),
            "tool_name": "fixture",
        }
    )
    aperture = build_protected_aperture_decision(
        raw_invocation=raw_invocation,
        disposition="protected",
        aperture_id=None,
        surface="launcher",
        operation="claim.publish",
        classifier_module=ingress_module,
        tool_name="fixture",
    )
    protected_claim = build_protected_claim_coordinates(
        state="prospective",
        task_ref=position.task_ref,
        lane="cx-test",
        session_ref="session:test",
        claim_epoch=1_720_629_960,
        claim_publication_intent=claim_publication_intent,
        claim_basis=ContentAddress(
            ref=prospective_basis.basis_ref,
            sha256=prospective_basis.basis_hash,
        ),
    )
    protected_request = build_protected_action_request(
        aperture,
        protected_claim,
        platform="codex",
        mode="headless",
        profile="full",
        execution_host="appendix",
        runtime_identity=runtime_identity,
        ingress_module=ingress_module,
        admission_module=admission_module,
        claim_mode=prospective_basis.claim_mode,
        effect_manifest=ContentAddress(
            ref=manifest.manifest_ref,
            sha256=manifest.manifest_hash,
        ),
        active_generation_roots=(ingress_module, admission_module),
        requested_effect_targets=effect_targets,
        requested_scope_refs=effect_scope,
        supersession_frontier_ref="supersession-frontier:test",
        requested_at=now,
        mutating=True,
    )
    intent = build_action_intent(
        position,
        action_id="action:inspect",
        action_class="claim_publication",
        operation="claim.publish",
        capability_role="worker",
        execution_host="appendix",
        acting_subject=acting_subject,
        protected_action_request=ContentAddress(
            ref=protected_request.request_ref,
            sha256=protected_request.request_hash,
        ),
        effect_manifest=manifest,
        requested_effect_targets=effect_targets,
        parent_spec=_execution_address("spec:test"),
        decomposition=_execution_address("decomposition:test"),
        requested_scope_refs=effect_scope,
        mutating=True,
    )
    authority = build_authority_evidence(
        authority_source=_execution_address("sovereign-act:test"),
        authenticated_receipt=_execution_address("authority-receipt:test"),
        issuer=_execution_address("issuer:test"),
        subject=acting_subject,
        authority_case=position.authority_case,
        authority_ceiling="bounded_machine_execution",
        authorized_action_classes=("claim_publication",),
        authorized_operations=("claim.publish",),
        authorized_flags=("implementation_authorized",),
        scope_refs=effect_scope,
        not_before=now - timedelta(minutes=1),
        valid_until=now + timedelta(minutes=20),
        supersession_frontier_ref="supersession-frontier:test",
    )
    trust_query = build_execution_trust_query(
        trust_class="authenticated_authority_receipt",
        subject_roots=(
            ContentAddress(ref=intent.intent_ref, sha256=intent.intent_hash),
            ContentAddress(ref=authority.evidence_ref, sha256=authority.evidence_hash),
            ContentAddress(ref=position.position_ref, sha256=position.position_hash),
            authority.authority_source,
            authority.issuer,
            intent.acting_subject,
        ),
        presented_receipt=authority.authenticated_receipt,
        required_roots=(
            ContentAddress(ref=intent.intent_ref, sha256=intent.intent_hash),
            ContentAddress(ref=authority.evidence_ref, sha256=authority.evidence_hash),
            ContentAddress(ref=position.position_ref, sha256=position.position_hash),
            authority.authority_source,
            authority.authenticated_receipt,
            authority.issuer,
            intent.acting_subject,
        ),
        supersession_frontier_ref=authority.supersession_frontier_ref,
        queried_at=now,
    )
    trust_resolver = _trust_resolver(
        trust_query,
        authority_trusted=trusted_authority,
    )
    manifest_resolver = EffectManifestResolver(
        (manifest,),
        resolver=_execution_address("port:effect-manifest-resolver"),
    )
    grant = validate_authority(
        intent,
        authority,
        position,
        now=now,
        trust_resolver=trust_resolver,
    )

    demand = build_demand_vector(
        {
            "route_metadata_schema": 1,
            "quality_floor": "frontier_review_required",
            "authority_level": "support_non_authoritative",
            "mutation_surface": "vault_docs",
            "mutation_scope_refs": list(effect_scope),
            "risk_flags": {},
            "context_shape": {},
            "verification_surface": {},
            "route_constraints": {},
            "review_requirement": {
                "support_artifact_allowed": True,
                "independent_review_required": True,
                "authoritative_acceptor_profile": "frontier_full",
            },
            "task_id": frame.task_ref,
            "authority_case": position.authority_case,
        },
        observed_at=now,
    )
    registry = PlatformCapabilityRegistry.model_validate(
        json.loads((root / "config" / "platform-capability-registry.json").read_text())
    )
    route = registry.require("codex.headless.full")
    supply = build_supply_vector(route, lane_id="cx-test", now=now)
    request = DispatchRequest(
        task_id=frame.task_ref,
        lane="cx-test",
        platform="codex",
        mode="headless",
        profile="full",
        route_id=route.route_id,
        authority_case=position.authority_case,
        route_metadata_status="explicit",
        quality_floor="frontier_review_required",
        authority_level="support_non_authoritative",
        mutation_surface="vault_docs",
        mutation_scope_refs=effect_scope,
        demand_vector=demand,
        supply_vector=supply,
    )
    leaf = f"{route.route_id}#base"
    decision = RouteDecision(
        decision_id=position.route_decision_ref,
        created_at=now,
        task_id=frame.task_ref,
        lane=request.lane,
        route_id=route.route_id,
        platform=request.platform,
        mode=request.mode,
        profile=request.profile,
        action=DispatchAction.LAUNCH,
        policy_outcome="test",
        launch_allowed=True,
        prompt_allowed=True,
        quality_floor_satisfied=True,
        authority_allowed=True,
        selected_descriptor_leaf=leaf,
        local_execution_target=local_execution_target,
        message="test",
    )
    descriptor = build_executor_descriptor(
        executor=_execution_address("executor:test"),
        adapter=_execution_address("adapter:test"),
        harness=_execution_address("harness:test"),
        runtime_identity=runtime_identity,
        active_generation_roots=protected_request.active_generation_roots,
        execution_host="appendix",
        platform="codex",
        mode="headless",
        profile="full",
        selected_descriptor_leaf=leaf,
        entrypoint="entrypoint:test",
    )
    executor_registry = build_executor_registry_projection(
        execution_host="appendix",
        registry_source=_execution_address("executor-registry:test"),
        event_frontier=_execution_address("executor-event-frontier:test"),
        descriptors=(descriptor,),
        observed_at=now,
        checked_at=now,
        stale_after=now + timedelta(minutes=20),
    )
    target = build_execution_target_evidence(
        host_scoped_claim=_execution_address("host-claim:test"),
        effect_manifest=manifest,
        executor_descriptor=descriptor,
        executor_registry_projection=executor_registry,
        environment_observation=_execution_address("environment:test"),
        observed_at=now,
        checked_at=now,
        stale_after=now + timedelta(minutes=20),
    )
    dependency = build_dependency_closure_evidence(
        selected_descriptor_leaf=leaf,
        dependency_refs=("dependency:route",),
        independent_failure_domain_refs=("failure-domain:one",),
        required_independent_fulfillments=1,
        provisioned_independent_fulfillments=1,
        source_receipt_refs=("receipt:dependency",),
        observed_at=now,
        checked_at=now,
        stale_after=now + timedelta(minutes=20),
    )
    quota = build_quota_reservation_evidence(
        status="not_applicable",
        route_leaf=leaf,
        idempotency_key="idempotency:test",
        source_receipt_refs=("receipt:quota",),
        reason_refs=("reason:subscription-capacity",),
        reserved_at=now,
        expires_at=now + timedelta(minutes=20),
    )
    admission = admit_execution(
        intent,
        grant,
        frame,
        trace,
        task_note=task_note,
        fact_frontier=fact_frontier,
        context_selection=selection_input,  # type: ignore[arg-type]
        audience_seal_receipt=audience_seal,
        claim_publication_intent=claim_publication_intent,
        demand_derivation_receipt=(
            _execution_address("demand-derivation:test") if include_demand_receipt else None
        ),
        supply_refresh_receipt=_execution_address("supply-refresh:test"),
        request=request,
        decision=decision,
        dependency_closure=dependency,
        quota_reservation=quota,
        execution_target=target,
        dispatch_message_id="dispatch-message:test",
        idempotency_key=prospective_basis.coord_dispatch_idempotency_key,
        supersession_frontier_ref="supersession-frontier:test",
        now=now,
        trust_resolver=trust_resolver,
        manifest_resolver=manifest_resolver,
    )
    fixture = SimpleNamespace(
        aperture=aperture,
        protected_claim=protected_claim,
        protected_request=protected_request,
        prospective_basis=prospective_basis,
        prospective_carrier=prospective_carrier,
        task_note=task_note,
        authority=authority,
        grant=grant,
        admission=admission,
        intent=intent,
        frame=frame,
        trace=trace,
        target=target,
        decision=decision,
        policy_request=request,
        manifest=manifest,
        descriptor=descriptor,
        executor_registry=executor_registry,
        trust_resolver=trust_resolver,
        manifest_resolver=manifest_resolver,
        now=now,
    )
    fixture.ports = _fixture_ports(fixture)
    return fixture


def _prepared_execution_claim(tmp_path: Path) -> SimpleNamespace:
    vault = tmp_path / "vault"
    active = vault / "active"
    (vault / "closed").mkdir(parents=True)
    active.mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    before = b"""---
task_id: task:rich
status: offered
assigned_to: unassigned
claimed_at: null
claimable: true
updated_at: 2026-07-10T16:00:00Z
authority_case: authority:fixture
parent_spec: spec:test
---
# Execution fixture
"""
    after = (
        before.replace(b"status: offered", b"status: claimed")
        .replace(b"assigned_to: unassigned", b"assigned_to: cx-test")
        .replace(b"claimed_at: null", b"claimed_at: 2026-07-10T16:06:00Z")
    )
    (active / "task:rich.md").write_bytes(before)
    task = resolve_task_note(vault, "task:rich", require_no_other_state=True)
    binding = ClaimDispatchBinding.create(
        task_id="task:rich",
        lane="cx-test",
        session_id="session:test",
        claim_epoch=1_720_629_960,
        dispatch_message_id="dispatch-message:test",
        platform="codex",
        mode="headless",
        profile="full",
        authority_case="authority:fixture",
        binding_hash="b" * 64,
        coord_dispatch_idempotency_key="idempotency:test",
    )
    intent = ClaimPublicationIntent.create(
        task=task,
        cache_dir=cache,
        note_after=after,
        binding=binding,
    )
    return SimpleNamespace(
        intent=intent,
        vault=vault,
        cache=cache,
        transactions=tmp_path / "transactions",
        receipts=cache / "claim-publication-receipts",
        locks=tmp_path / "locks",
    )


def _claim_admission_consumption(
    prepared: SimpleNamespace,
    fixture: SimpleNamespace,
    lease: ExecutionLease,
) -> ClaimAdmissionConsumption:
    proof_root = prepared.vault.parent / "admission-proofs"
    proof_root.mkdir()

    def write_proof(name: str, model: object) -> Path:
        path = proof_root / name
        payload = model.model_dump(mode="json", by_alias=True)  # type: ignore[attr-defined]
        path.write_text(
            json.dumps(
                payload,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n",
            encoding="ascii",
        )
        path.chmod(0o600)
        return path

    consumption = ClaimAdmissionConsumption.create(
        prepared.intent,
        action_intent_path=write_proof("action-intent.json", fixture.intent),
        execution_admission_path=write_proof("execution-admission.json", fixture.admission),
        valid_authority_grant_path=write_proof("valid-authority-grant.json", fixture.grant),
        authority_evidence_path=write_proof("authority-evidence.json", fixture.authority),
        execution_lease_path=write_proof("execution-lease.json", lease),
        checked_at=lease.issued_at,
    )
    return consumption


def _lease_for_fixture(fixture: SimpleNamespace):
    bound_call = build_bound_execution_call(
        fixture.admission,
        fixture.intent,
        fixture.grant,
        fixture.prospective_basis,
        fixture.protected_claim,
        fixture.protected_request,
        fixture.task_note,
        fixture.target,
        fixture.decision,
        fixture.manifest,
        fixture.descriptor,
        fixture.executor_registry,
        invocation_id="invocation:test",
        attempt_fence="c" * 64,
    )
    issuer = _execution_address("lease-issuer:test")
    assert fixture.ports.trust.resolver is not None
    issuer_query = build_execution_lease_issuer_trust_query(
        fixture.admission,
        fixture.grant,
        fixture.prospective_basis,
        fixture.target,
        bound_call,
        fixture.manifest,
        fixture.descriptor,
        fixture.executor_registry,
        issuer_receipt=issuer,
        queried_at=fixture.now + timedelta(minutes=1),
    )
    mint_trust = _trust_resolver(
        issuer_query,
        resolver_address=fixture.ports.trust.resolver,
    )
    lease = mint_execution_lease(
        fixture.admission,
        fixture.intent,
        fixture.grant,
        fixture.prospective_basis,
        fixture.target,
        bound_call,
        fixture.manifest,
        fixture.descriptor,
        fixture.executor_registry,
        issuer_receipt=issuer,
        now=fixture.now + timedelta(minutes=1),
        trust_resolver=mint_trust,
    )
    checked_at = fixture.now + timedelta(minutes=2)

    def refreshed(query):  # type: ignore[no-untyped-def]
        return build_execution_trust_query(
            trust_class=query.trust_class,
            subject_roots=query.subject_roots,
            presented_receipt=query.presented_receipt,
            required_roots=query.required_roots,
            supersession_frontier_ref=query.supersession_frontier_ref,
            queried_at=checked_at,
        )

    authority_query = refreshed(fixture.grant.authority_trust_query)
    refreshed_issuer_query = refreshed(lease.issuer_trust_query)
    current_trust = _trust_resolver(
        authority_query,
        refreshed_issuer_query,
        resolver_address=fixture.ports.trust.resolver,
    )
    authority_envelope = current_trust.require_trusted(authority_query)
    issuer_envelope = current_trust.require_trusted(refreshed_issuer_query)
    currentness_query = build_execution_currentness_query(
        lease,
        fixture.admission,
        fixture.intent,
        fixture.grant,
        fixture.prospective_basis,
        fixture.frame,
        fixture.trace,
        fixture.target,
        fixture.decision,
        fixture.manifest,
        fixture.descriptor,
        fixture.executor_registry,
        authority_query,
        authority_envelope,
        refreshed_issuer_query,
        issuer_envelope,
        queried_at=checked_at,
    )
    fixture.ports = replace(
        fixture.ports,
        trust=current_trust,
        currentness=_currentness_resolver(currentness_query),
    )
    return lease


def _real_execution_invocation(tmp_path: Path) -> SimpleNamespace:
    prepared = _prepared_execution_claim(tmp_path)
    fixture = _execution_admission_fixture(
        publication_intent=prepared.intent,
    )
    lease = _lease_for_fixture(fixture)
    invocation = ExecutionInvocationContext(
        lease=lease,
        admission=fixture.admission,
        intent=fixture.intent,
        grant=fixture.grant,
        claim_resolution=ProspectiveClaimResolution(
            vault_root=prepared.vault,
            cache_dir=prepared.cache,
            transaction_root=prepared.transactions,
            receipt_root=prepared.receipts,
            lock_root=prepared.locks,
            carrier=fixture.prospective_carrier,
            current_task_note=fixture.task_note,
        ),
        frame=fixture.frame,
        trace=fixture.trace,
        target=fixture.target,
        route_decision=fixture.decision,
        effect_manifest=fixture.manifest,
        executor_descriptor=fixture.descriptor,
        executor_registry_projection=fixture.executor_registry,
        protected_request=fixture.protected_request,
        aperture_decision=fixture.aperture,
        claim_coordinates=fixture.protected_claim,
        ports=fixture.ports,
    )
    request = DispatchLaunchRequest(
        task_id=fixture.admission.task_ref,
        lane=fixture.admission.lane,
        platform=fixture.decision.platform,
        mode=fixture.decision.mode,
        profile=fixture.decision.profile,
        authority_case=fixture.admission.authority_case,
        parent_spec=fixture.intent.parent_spec.ref,
        message_id=fixture.admission.dispatch_message_id,
        idempotency_key=fixture.admission.idempotency_key,
    )
    return SimpleNamespace(
        **fixture.__dict__,
        invocation=invocation,
        lease=lease,
        request=request,
        prepared=prepared,
    )


def test_protected_action_request_hash_covers_every_field() -> None:
    fixture = _execution_admission_fixture()
    payload = fixture.protected_request.model_dump(mode="json", by_alias=True)
    payload["operation"] = "different-operation"
    with pytest.raises(ValueError, match="does not bind its body"):
        ProtectedActionRequest.model_validate(payload)


def test_same_operation_with_different_raw_invocation_has_different_request_root() -> None:
    fixture = _execution_admission_fixture()
    raw = protected_raw_invocation_address({"argv": ["claim", "publish", "different"]})
    aperture = build_protected_aperture_decision(
        raw_invocation=raw,
        disposition="protected",
        aperture_id=None,
        surface="launcher",
        operation=fixture.protected_request.operation,
        classifier_module=fixture.protected_request.ingress_module,
        tool_name="fixture",
    )
    rebuilt = build_protected_action_request(
        aperture,
        fixture.protected_claim,
        platform=fixture.protected_request.platform,
        mode=fixture.protected_request.mode,
        profile=fixture.protected_request.profile,
        execution_host=fixture.protected_request.execution_host,
        runtime_identity=fixture.protected_request.runtime_identity,
        ingress_module=fixture.protected_request.ingress_module,
        admission_module=fixture.protected_request.admission_module,
        claim_mode=fixture.protected_request.claim_mode,
        effect_manifest=fixture.protected_request.effect_manifest,
        active_generation_roots=fixture.protected_request.active_generation_roots,
        requested_effect_targets=fixture.protected_request.requested_effect_targets,
        requested_scope_refs=fixture.protected_request.requested_scope_refs,
        supersession_frontier_ref=fixture.protected_request.supersession_frontier_ref,
        requested_at=fixture.protected_request.requested_at,
        mutating=fixture.protected_request.mutating,
    )
    assert rebuilt.request_hash != fixture.protected_request.request_hash
    assert rebuilt.raw_invocation != fixture.protected_request.raw_invocation


def test_prospective_publication_a_cannot_masquerade_as_applied_ownership_b() -> None:
    fixture = _execution_admission_fixture()
    with pytest.raises(ValueError, match="state differs from its typed basis"):
        build_protected_claim_coordinates(
            state="applied",
            task_ref=fixture.prospective_basis.task_ref,
            lane=fixture.prospective_basis.lane,
            session_ref=fixture.prospective_basis.session_ref,
            claim_epoch=fixture.prospective_basis.claim_epoch,
            claim_publication_intent=fixture.prospective_basis.claim_publication_intent,
            claim_basis=ContentAddress(
                ref=fixture.prospective_basis.basis_ref,
                sha256=fixture.prospective_basis.basis_hash,
            ),
        )

    ordinary_aperture = build_protected_aperture_decision(
        raw_invocation=protected_raw_invocation_address({"argv": ["inspection"]}),
        disposition="protected",
        aperture_id=None,
        surface="launcher",
        operation="inspection",
        classifier_module=fixture.protected_request.ingress_module,
        tool_name="fixture",
    )
    with pytest.raises(ExecutionAdmissionError, match="prospective_claim_operation_forbidden"):
        build_protected_action_request(
            ordinary_aperture,
            fixture.protected_claim,
            platform=fixture.protected_request.platform,
            mode=fixture.protected_request.mode,
            profile=fixture.protected_request.profile,
            execution_host=fixture.protected_request.execution_host,
            runtime_identity=fixture.protected_request.runtime_identity,
            ingress_module=fixture.protected_request.ingress_module,
            admission_module=fixture.protected_request.admission_module,
            claim_mode=fixture.protected_request.claim_mode,
            effect_manifest=fixture.protected_request.effect_manifest,
            active_generation_roots=fixture.protected_request.active_generation_roots,
            requested_effect_targets=fixture.protected_request.requested_effect_targets,
            requested_scope_refs=fixture.protected_request.requested_scope_refs,
            supersession_frontier_ref=fixture.protected_request.supersession_frontier_ref,
            requested_at=fixture.now,
            mutating=True,
        )


def test_protected_action_default_is_typed_hold_and_direct_fallthrough_is_impossible() -> None:
    fixture = _execution_admission_fixture()
    decision = evaluate_protected_action(
        fixture.protected_request,
        fixture.aperture,
        fixture.protected_claim,
    )
    assert decision.disposition == "hold"
    assert decision.reason_codes == ("execution_admission_prerequisites_unavailable",)
    assert decision.authorizes_direct_fallthrough is False
    with pytest.raises(ExecutionAdmissionError, match="prerequisites_unavailable"):
        require_protected_action("inspection")


def test_protected_action_projects_exact_invocation_but_effect_gate_holds(
    tmp_path: Path,
) -> None:
    fixture = _real_execution_invocation(tmp_path)
    projected = project_execution_invocation_context(
        fixture.protected_request,
        fixture.aperture,
        fixture.protected_claim,
        fixture.invocation,
        queried_at=QUERY_TIME,
    )
    assert projected.protected_action_request == ContentAddress(
        ref=fixture.protected_request.request_ref,
        sha256=fixture.protected_request.request_hash,
    )
    with pytest.raises(ExecutionAdmissionError) as raised:
        fixture.invocation.require_current(queried_at=QUERY_TIME)
    assert raised.value.reason_code == "execution_composition_activation_unvalidated"


def test_protected_action_rejects_attached_same_operation_with_other_raw_payload(
    tmp_path: Path,
) -> None:
    fixture = _real_execution_invocation(tmp_path)
    different = build_protected_aperture_decision(
        raw_invocation=protected_raw_invocation_address({"argv": ["claim", "publish", "other"]}),
        disposition="protected",
        aperture_id=None,
        surface="launcher",
        operation=fixture.protected_request.operation,
        classifier_module=fixture.protected_request.ingress_module,
        tool_name="fixture",
    )
    with pytest.raises(ExecutionAdmissionError, match="invocation_mismatch"):
        project_execution_invocation_context(
            fixture.protected_request,
            different,
            fixture.protected_claim,
            fixture.invocation,
            queried_at=QUERY_TIME,
        )


def test_module_address_detects_bytes_changed_after_request(tmp_path: Path) -> None:
    module = tmp_path / "ingress.py"
    module.write_text("value = 1\n", encoding="utf-8")
    address = module_file_address(module)
    module.write_text("value = 2\n", encoding="utf-8")
    with pytest.raises(ExecutionAdmissionError, match="module_generation_mismatch"):
        execution_admission._require_current_module_address(address)


def test_authority_validation_uses_module_owned_trust_and_never_authorizes_operator() -> None:
    fixture = _execution_admission_fixture()
    assert isinstance(fixture.grant, ValidAuthorityGrant)
    assert fixture.grant.authorizes_machine_admission is True
    assert fixture.grant.authorizes_operator is False
    assert fixture.grant.may_mint_sovereign_act is False

    held = _execution_admission_fixture(trusted_authority=False)
    assert isinstance(held.grant, AuthorityHold)
    assert held.grant.reason_codes == ("authority_receipt_untrusted",)
    assert held.admission.decision == "hold"
    assert held.admission.authority_grant is None


def test_execution_admission_is_complete_content_addressed_and_non_authorizing() -> None:
    fixture = _execution_admission_fixture()
    admission = fixture.admission
    assert admission.decision == "admit"
    assert admission.lease_eligible is True
    assert admission.admission_ref.endswith(admission.admission_hash)
    assert admission.authority_trust_query is not None
    assert admission.authority_trust_envelope is not None
    assert admission.authority_trust_envelope.decision == "trusted"
    assert admission.may_authorize is False
    assert admission.authorizes_operator is False


@pytest.mark.parametrize(
    ("selection_case", "reason_code"),
    [
        ("position_mismatch", "context_selection_position_mismatch"),
        ("fact_frontier_mismatch", "context_selection_fact_frontier_mismatch"),
        ("trace_frontier_mismatch", "context_selection_trace_frontier_mismatch"),
        ("audience_seal_mismatch", "context_selection_audience_seal_mismatch"),
        ("policy_generation_mismatch", "context_selection_policy_generation_mismatch"),
        ("wrong_audience", "context_selection_wrong_audience"),
        ("hold", "context_selection_hold"),
        ("stale", "context_selection_stale"),
    ],
)
def test_execution_admission_holds_on_context_selection_drift_or_loss(
    selection_case: str,
    reason_code: str,
) -> None:
    admission = _execution_admission_fixture(selection_case=selection_case).admission
    assert admission.decision == "hold"
    assert admission.lease_eligible is False
    assert reason_code in admission.reason_codes


def test_execution_admission_rejects_legacy_opaque_context_selection_address() -> None:
    with pytest.raises(ExecutionAdmissionError, match="execution_admission_input_malformed"):
        _execution_admission_fixture(selection_case="legacy_address")


def test_missing_proof_derived_demand_receipt_holds_instead_of_defaulting() -> None:
    admission = _execution_admission_fixture(include_demand_receipt=False).admission
    assert admission.decision == "hold"
    assert "demand_derivation_receipt_missing" in admission.reason_codes


def test_route_host_drift_holds_before_lease() -> None:
    admission = _execution_admission_fixture(local_execution_target="podium").admission
    assert admission.decision == "hold"
    assert "route_decision_position_mismatch" in admission.reason_codes


def test_public_claim_publishers_hold_without_mutation_in_gate0a(tmp_path: Path) -> None:
    prepared = _prepared_execution_claim(tmp_path)
    fixture = _execution_admission_fixture(
        publication_intent=prepared.intent,
    )
    lease = _lease_for_fixture(fixture)
    consumption = _claim_admission_consumption(prepared, fixture, lease)
    note_before = prepared.intent.note_path.read_bytes()

    with pytest.raises(ClaimPublicationError, match="unadmitted_claim_publication_forbidden"):
        publish_claim(
            prepared.intent,
            transaction_root=prepared.transactions,
            lock_root=prepared.locks,
        )
    with pytest.raises(
        ClaimPublicationError,
        match="claim_publication_effect_activation_unvalidated",
    ):
        publish_admitted_claim(
            prepared.intent,
            consumption,
            transaction_root=prepared.transactions,
            lock_root=prepared.locks,
            now=fixture.now,
        )

    assert prepared.intent.note_path.read_bytes() == note_before
    assert not prepared.transactions.exists()
    assert not prepared.receipts.exists()


def test_lease_and_currentness_bind_every_root_and_fail_closed(tmp_path: Path) -> None:
    prepared = _prepared_execution_claim(tmp_path)
    fixture = _execution_admission_fixture(
        publication_intent=prepared.intent,
    )
    lease = _lease_for_fixture(fixture)
    assert lease.authorizes_machine_adapter is True
    assert lease.authorizes_operator is False
    assert lease.issuer_trust_envelope.decision == "trusted"

    with mock.patch(
        "shared.execution_admission._utc_now",
        side_effect=AssertionError("explicit currentness query reached ambient clock"),
    ):
        current_lease, query, envelope = require_current_execution_lease(
            lease,
            fixture.admission,
            fixture.intent,
            fixture.grant,
            fixture.prospective_basis,
            fixture.task_note,
            fixture.frame,
            fixture.trace,
            fixture.target,
            fixture.decision,
            fixture.manifest,
            fixture.descriptor,
            fixture.executor_registry,
            trust_resolver=fixture.ports.trust,
            manifest_resolver=fixture.ports.manifests,
            currentness_resolver=fixture.ports.currentness,
            queried_at=fixture.now + timedelta(minutes=2),
        )
    assert current_lease == lease
    assert envelope.query.ref == query.query_ref
    root_refs = {item.ref for item in query.required_roots}
    assert fixture.admission.demand_vector.ref in root_refs
    assert fixture.admission.demand_derivation_receipt.ref in root_refs
    assert lease.issuer_trust_envelope.event_frontier.ref in root_refs
    assert query.historical_support_roots == ()
    assert envelope.historical_support_dispositions == ()

    with mock.patch(
        "shared.execution_admission._utc_now",
        side_effect=AssertionError("explicit currentness query reached ambient clock"),
    ):
        with pytest.raises(ExecutionAdmissionError, match="execution_currentness_not_current"):
            require_current_execution_lease(
                lease,
                fixture.admission,
                fixture.intent,
                fixture.grant,
                fixture.prospective_basis,
                fixture.task_note,
                fixture.frame,
                fixture.trace,
                fixture.target,
                fixture.decision,
                fixture.manifest,
                fixture.descriptor,
                fixture.executor_registry,
                trust_resolver=fixture.ports.trust,
                manifest_resolver=fixture.ports.manifests,
                currentness_resolver=_currentness_resolver(
                    query, noncurrent_ref=lease.executor_descriptor.ref
                ),
                queried_at=fixture.now + timedelta(minutes=2),
            )


def test_default_ports_hold_without_effect_or_lease(tmp_path: Path) -> None:
    prepared = _prepared_execution_claim(tmp_path)
    fixture = _execution_admission_fixture(
        publication_intent=prepared.intent,
    )
    bound_call = build_bound_execution_call(
        fixture.admission,
        fixture.intent,
        fixture.grant,
        fixture.prospective_basis,
        fixture.protected_claim,
        fixture.protected_request,
        fixture.task_note,
        fixture.target,
        fixture.decision,
        fixture.manifest,
        fixture.descriptor,
        fixture.executor_registry,
        invocation_id="invocation:test",
        attempt_fence="c" * 64,
    )
    with pytest.raises(ExecutionAdmissionError, match="execution_trust_resolver_unavailable"):
        mint_execution_lease(
            fixture.admission,
            fixture.intent,
            fixture.grant,
            fixture.prospective_basis,
            fixture.target,
            bound_call,
            fixture.manifest,
            fixture.descriptor,
            fixture.executor_registry,
            issuer_receipt=_execution_address("lease-issuer:test"),
            now=fixture.now + timedelta(minutes=1),
        )


def test_currentness_keeps_historical_support_out_of_action_current_roots(
    tmp_path: Path,
) -> None:
    fixture = _real_execution_invocation(tmp_path)
    with mock.patch(
        "shared.execution_admission._utc_now",
        side_effect=AssertionError("explicit currentness query reached ambient clock"),
    ):
        _, query, _ = require_current_execution_lease(
            fixture.lease,
            fixture.admission,
            fixture.intent,
            fixture.grant,
            fixture.prospective_basis,
            fixture.task_note,
            fixture.frame,
            fixture.trace,
            fixture.target,
            fixture.decision,
            fixture.manifest,
            fixture.descriptor,
            fixture.executor_registry,
            trust_resolver=fixture.ports.trust,
            manifest_resolver=fixture.ports.manifests,
            currentness_resolver=fixture.ports.currentness,
            queried_at=fixture.now + timedelta(minutes=2),
        )
    historical_root = _execution_address("historical-support:test")
    payload = query.model_dump(mode="json", by_alias=True)
    payload["historical_support_roots"] = [historical_root.model_dump(mode="json")]
    body = {key: value for key, value in payload.items() if key not in {"query_ref", "query_hash"}}
    digest = execution_admission._self_hash(
        execution_admission.EXECUTION_CURRENTNESS_QUERY_SCHEMA,
        body,
    )
    historical_query = type(query).model_validate(
        {
            **body,
            "query_ref": f"execution-currentness-query@sha256:{digest}",
            "query_hash": digest,
        }
    )

    envelope = _currentness_resolver(historical_query).resolve(historical_query)

    assert historical_root not in historical_query.required_roots
    assert historical_query.historical_support_roots == (historical_root,)
    assert envelope.historical_support_dispositions == (
        HistoricalSupportDisposition(
            root=historical_root,
            disposition="present",
            reason_codes=(),
            source_event_refs=("event:historical-support:0",),
        ),
    )


def test_executor_binding_invoke_holds_without_calling_effect_in_gate0a(
    tmp_path: Path,
) -> None:
    fixture = _real_execution_invocation(tmp_path)
    binding = ExecutionExecutorBinding(fixture.descriptor)

    with pytest.raises(ExecutionExecutorError) as raised:
        binding.invoke(fixture.lease, _execution_address("execution-start:test"))

    assert raised.value.reason_code == "execution_composition_activation_unvalidated"
    assert not hasattr(binding, "_invoke")


def test_gate0a_execution_module_contains_no_effect_callable_slots() -> None:
    source = Path(execution_admission.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {
        "_invoke",
        "_append",
        "_resolve",
        "_evaluate",
        "_frontier",
        "_lookup",
        "outcome_replay",
        "effect_activation_gate",
    }
    assert "Callable" not in source
    assert not {
        node.target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }.intersection(forbidden)

    with pytest.raises(TypeError):
        ExecutionTrustResolver(  # type: ignore[call-arg]
            resolver=_execution_address("resolver:hostile"),
            _resolve=lambda _query: (_ for _ in ()).throw(AssertionError("called")),
        )


@pytest.mark.parametrize(
    "sealer",
    [
        execution_admission._seal_execution_trust_resolver,
        execution_admission._seal_effect_manifest_resolver,
        execution_admission._seal_execution_currentness_resolver,
        execution_admission._seal_execution_executor_registry,
        execution_admission._seal_completion_evaluator,
        execution_admission._seal_outcome_readiness_resolver,
        execution_admission._seal_outcome_committer,
        execution_admission._seal_execution_composition_ports,
    ],
)
def test_gate0a_port_sealers_reject_ducks_before_attribute_or_method_dispatch(
    sealer: object,
) -> None:
    calls: list[str] = []

    class Hostile:
        def __getattr__(self, name: str) -> object:
            calls.append(name)
            raise AssertionError(f"hostile attribute reached: {name}")

    with pytest.raises(ExecutionAdmissionError, match="execution_projection_type_invalid"):
        sealer(Hostile())  # type: ignore[operator]
    assert calls == []


def test_gate0a_port_sealers_reject_subclasses_before_overridden_methods() -> None:
    calls: list[str] = []

    class HostileTrust(ExecutionTrustResolver):
        def evaluate(self, _query: object) -> object:
            calls.append("evaluate")
            raise AssertionError("hostile trust resolver reached")

    class HostileManifests(EffectManifestResolver):
        def resolve(self, _address: object) -> object:
            calls.append("resolve")
            raise AssertionError("hostile manifest resolver reached")

    for sealer, candidate in (
        (execution_admission._seal_execution_trust_resolver, HostileTrust()),
        (execution_admission._seal_effect_manifest_resolver, HostileManifests()),
    ):
        with pytest.raises(ExecutionAdmissionError, match="execution_projection_type_invalid"):
            sealer(candidate)
    assert calls == []


def test_gate0a_dynamic_ports_have_no_unsealed_fallback_spelling() -> None:
    source = Path(execution_admission.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "trust_resolver or ExecutionTrustResolver",
        "manifest_resolver or EffectManifestResolver",
        "currentness_resolver or ExecutionCurrentnessResolver",
        "completion_evaluator or CompletionEvaluator",
        "outcome_committer or OutcomeCommitter",
        "readiness_resolver or OutcomePipelineReadinessResolver",
    ):
        assert forbidden not in source


def test_prospective_invocation_rejects_a_substituted_live_basis(tmp_path: Path) -> None:
    fixture = _real_execution_invocation(tmp_path)
    resolution = fixture.invocation.claim_resolution
    assert isinstance(resolution, ProspectiveClaimResolution)
    basis = resolution.carrier.basis
    alternate_basis = build_prospective_claim_publication_basis(
        claim_publication_intent=basis.claim_publication_intent,
        task_ref=basis.task_ref,
        lane=basis.lane,
        session_ref=basis.session_ref,
        claim_epoch=basis.claim_epoch + 1,
        authority_case=basis.authority_case,
        dispatch_message_id=basis.dispatch_message_id,
        dispatch_binding_hash=basis.dispatch_binding_hash,
        dispatch_binding_receipt_hash=basis.dispatch_binding_receipt_hash,
        coord_dispatch_idempotency_key=basis.coord_dispatch_idempotency_key,
        claim_mode=basis.claim_mode,
        from_status=basis.from_status,
        to_status=basis.to_status,
        task_note_before_sha256=basis.task_note_before_sha256,
        task_note_after_sha256=basis.task_note_after_sha256,
        task_note_mode=basis.task_note_mode,
        mutation_scope_hash=basis.mutation_scope_hash,
    )
    alternate_resolution = ProspectiveClaimResolution(
        vault_root=resolution.vault_root,
        cache_dir=resolution.cache_dir,
        transaction_root=resolution.transaction_root,
        receipt_root=resolution.receipt_root,
        lock_root=resolution.lock_root,
        carrier=build_prospective_claim_publication_carrier(
            alternate_basis,
            note_after=resolution.carrier.note_after.encode("utf-8"),
        ),
        current_task_note=resolution.current_task_note,
    )

    with pytest.raises(ExecutionAdmissionError) as raised:
        replace(
            fixture.invocation,
            claim_resolution=alternate_resolution,
        ).require_admitted(queried_at=QUERY_TIME)

    assert "execution_invocation_live_claim_mismatch" in raised.value.detail


def test_active_v3_prospective_lease_round_trips_without_history_coercion(
    tmp_path: Path,
) -> None:
    fixture = _real_execution_invocation(tmp_path)
    lease = fixture.lease
    parsed = parse_execution_lease_record(lease.model_dump(mode="json", by_alias=True))

    assert parsed == lease
    assert require_admitted_execution_lease(parsed) == lease
    assert parsed.claim_coordinates.state == "prospective"


def _execution_composition_manifest(
    fixture: SimpleNamespace,
    store_root: Path,
    *,
    activation_generation: ContentAddress | None = None,
    activation_receipt: ContentAddress | None = None,
    max_bundle_bytes: int = 16 * 1024 * 1024,
) -> ExecutionCompositionManifest:
    prepared = fixture.prepared
    return build_execution_composition_manifest(
        activation_generation=(
            activation_generation or _execution_address("activation-generation:test")
        ),
        invocation_store_root=store_root,
        max_bundle_bytes=max_bundle_bytes,
        claim_vault_root=prepared.vault,
        claim_cache_dir=prepared.cache,
        claim_transaction_root=prepared.transactions,
        claim_receipt_root=prepared.receipts,
        claim_lock_root=prepared.locks,
        port_descriptors=fixture.ports.descriptors,
        attempt_journal=_execution_address("attempt-journal:test"),
        activation_receipt=activation_receipt,
    )


def _install_execution_composition_manifest(
    manifest: ExecutionCompositionManifest,
) -> None:
    store_root = Path(manifest.invocation_store_root)
    store_root.mkdir(mode=0o700)
    (store_root / "objects").mkdir(mode=0o700)
    manifest_path = store_root / "composition-manifest.json"
    manifest_path.write_bytes(execution_composition_manifest_bytes(manifest))
    manifest_path.chmod(0o600)


def _execution_composition_ports(
    manifest: ExecutionCompositionManifest,
    *,
    fixture: SimpleNamespace | None = None,
    trust_descriptor: ContentAddress | None = None,
) -> ExecutionCompositionPorts:
    descriptors = manifest.port_descriptors
    if fixture is not None and trust_descriptor is None:
        assert fixture.ports.descriptors == descriptors
        return fixture.ports
    empty_catalog = build_outcome_replay_catalog_snapshot(
        committer=descriptors.outcome_committer,
        event_plane=descriptors.event_plane,
        projection_resolver=descriptors.outcome_projection_resolver,
        validity_resolver=descriptors.outcome_validity_resolver,
        checked_frontier=_execution_address("event-frontier:empty"),
        projections=(),
        validity_envelopes=(),
        source_receipt=_execution_address("outcome-catalog-read:empty"),
        observed_at=QUERY_TIME,
    )
    outcomes = OutcomeCommitter(
        committer=descriptors.outcome_committer,
        event_plane=descriptors.event_plane,
        projection_resolver=descriptors.outcome_projection_resolver,
        validity_resolver=descriptors.outcome_validity_resolver,
        catalog_snapshot=empty_catalog,
    )
    return ExecutionCompositionPorts(
        descriptors=descriptors,
        trust=ExecutionTrustResolver(
            resolver=trust_descriptor or descriptors.trust_resolver,
        ),
        manifests=EffectManifestResolver(
            resolver=descriptors.effect_manifest_resolver,
        ),
        currentness=ExecutionCurrentnessResolver(
            resolver=descriptors.currentness_resolver,
        ),
        executors=ExecutionExecutorRegistry(
            descriptor=descriptors.executor_registry,
        ),
        completion=CompletionEvaluator(
            evaluator=descriptors.completion_evaluator,
        ),
        readiness=OutcomePipelineReadinessResolver(
            resolver=descriptors.readiness_resolver,
        ),
        outcomes=outcomes,
    )


def _configured_execution_composition(
    fixture: SimpleNamespace,
    tmp_path: Path,
) -> tuple[
    ExecutionCompositionManifest,
    ExecutionInvocationBundleStore,
    ExecutionCompositionRoot,
]:
    prepared = fixture.prepared
    manifest = _execution_composition_manifest(
        fixture,
        tmp_path / "execution-invocations",
    )
    _install_execution_composition_manifest(manifest)
    store = ExecutionInvocationBundleStore(
        root=Path(manifest.invocation_store_root),
        composition_manifest=manifest,
    )
    composition = ExecutionCompositionRoot(
        composition_manifest=manifest,
        invocation_store=store,
        ports=_execution_composition_ports(manifest, fixture=fixture),
        claim_vault_root=prepared.vault,
        claim_cache_dir=prepared.cache,
        claim_transaction_root=prepared.transactions,
        claim_receipt_root=prepared.receipts,
        claim_lock_root=prepared.locks,
    )
    return manifest, store, composition


def _materialize_read_only_bundle_fixture(
    fixture: SimpleNamespace,
    manifest: ExecutionCompositionManifest,
    store: ExecutionInvocationBundleStore,
) -> tuple[
    ExecutionInvocationBundle,
    ExecutionInvocationBundlePointer,
    Path,
]:
    """Install exact test-owned bytes; the operational persistence APIs stay dormant."""

    bundle = build_execution_invocation_bundle(
        fixture.invocation,
        composition_manifest=manifest,
        queried_at=QUERY_TIME,
    )
    pointer = build_execution_invocation_bundle_pointer(bundle)
    object_path = store.objects_root / f"{pointer.canonical_bytes.sha256}.json"
    payload = execution_admission._execution_invocation_bundle_bytes(bundle)
    assert execution_admission._sha256(payload) == pointer.canonical_bytes.sha256
    assert not object_path.exists()
    object_path.write_bytes(payload)
    object_path.chmod(0o600)
    return bundle, pointer, object_path


def _pointer_for_storage_bytes(
    pointer: ExecutionInvocationBundlePointer,
    payload: bytes,
) -> ExecutionInvocationBundlePointer:
    payload_hash = execution_admission._sha256(payload)
    body = pointer.model_dump(
        mode="json",
        by_alias=True,
        exclude={"pointer_ref", "pointer_hash"},
    )
    body["canonical_bytes"] = ContentAddress(
        ref=f"execution-invocation-bundle-bytes@sha256:{payload_hash}",
        sha256=payload_hash,
    )
    digest = execution_admission._self_hash(
        execution_admission.EXECUTION_INVOCATION_BUNDLE_POINTER_SCHEMA,
        body,
    )
    return ExecutionInvocationBundlePointer.model_validate(
        {
            **body,
            "pointer_ref": f"execution-invocation-bundle-pointer@sha256:{digest}",
            "pointer_hash": digest,
        }
    )


def test_execution_invocation_bundle_store_inspects_preexisting_bytes_idempotently(
    tmp_path: Path,
) -> None:
    fixture = _real_execution_invocation(tmp_path)
    manifest, store, composition = _configured_execution_composition(fixture, tmp_path)
    _, pointer, object_path = _materialize_read_only_bundle_fixture(
        fixture,
        manifest,
        store,
    )
    first_bytes = object_path.read_bytes()
    first_stat = object_path.stat()

    assert store.resolve(pointer) == store.resolve(pointer)
    assert object_path.read_bytes() == first_bytes
    assert object_path.stat().st_ino == first_stat.st_ino
    assert first_stat.st_mode & 0o777 == 0o600
    assert store.root.stat().st_mode & 0o777 == 0o700
    assert store.objects_root.stat().st_mode & 0o777 == 0o700
    assert pointer.composition_manifest == ContentAddress(
        ref=manifest.manifest_ref,
        sha256=manifest.manifest_hash,
    )

    reconstructed = composition.resolve_invocation(pointer, queried_at=QUERY_TIME)
    assert reconstructed.lease == fixture.lease
    assert reconstructed.protected_request == fixture.protected_request
    assert reconstructed.claim_resolution.receipt_root == fixture.prepared.receipts
    assert reconstructed.ports is not composition.ports
    assert reconstructed.ports is not None
    assert composition.ports is not None
    assert reconstructed.ports.descriptors == composition.ports.descriptors
    assert type(reconstructed.ports) is ExecutionCompositionPorts


def test_execution_invocation_persistence_apis_hold_without_writing(
    tmp_path: Path,
) -> None:
    fixture = _real_execution_invocation(tmp_path)
    manifest, store, composition = _configured_execution_composition(fixture, tmp_path)
    bundle = build_execution_invocation_bundle(
        fixture.invocation,
        composition_manifest=manifest,
        queried_at=QUERY_TIME,
    )
    pointer = build_execution_invocation_bundle_pointer(bundle)
    object_path = store.objects_root / f"{pointer.canonical_bytes.sha256}.json"

    with pytest.raises(ExecutionAdmissionError) as store_hold:
        store.put(bundle)
    with pytest.raises(ExecutionAdmissionError) as root_hold:
        composition.persist_invocation(fixture.invocation)

    assert store_hold.value.reason_code == "execution_invocation_store_activation_unvalidated"
    assert root_hold.value.reason_code == "execution_composition_activation_unvalidated"
    assert not object_path.exists()


def test_dormant_execution_composition_has_no_filesystem_effect(tmp_path: Path) -> None:
    fixture = _real_execution_invocation(tmp_path / "fixture")
    dormant_root = tmp_path / "dormant-store"
    dormant = ExecutionCompositionRoot()

    with pytest.raises(ExecutionAdmissionError) as raised:
        dormant.persist_invocation(fixture.invocation)

    assert raised.value.reason_code == "execution_composition_activation_unvalidated"
    assert not dormant_root.exists()
    assert DEFAULT_EXECUTION_COMPOSITION_ROOT.activation_generation is None
    assert DEFAULT_EXECUTION_COMPOSITION_ROOT.composition_manifest is None
    assert DEFAULT_EXECUTION_COMPOSITION_ROOT.invocation_store is None


def test_operational_code_never_loads_ambient_default_ports() -> None:
    source = Path(execution_admission.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    loads = sorted(
        (node.lineno, node.id)
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and node.id.startswith("DEFAULT_")
    )
    assert loads == []


def test_execution_invocation_store_resolution_is_zero_write_when_missing(
    tmp_path: Path,
) -> None:
    fixture = _real_execution_invocation(tmp_path / "fixture")
    missing_root = tmp_path / "missing-store"
    manifest = _execution_composition_manifest(
        fixture,
        missing_root,
        activation_generation=_execution_address("activation-generation:missing"),
    )
    bundle = build_execution_invocation_bundle(
        fixture.invocation,
        composition_manifest=manifest,
        queried_at=QUERY_TIME,
    )
    pointer = build_execution_invocation_bundle_pointer(bundle)
    store = ExecutionInvocationBundleStore(
        root=missing_root,
        composition_manifest=manifest,
    )

    with pytest.raises(ExecutionAdmissionError) as raised:
        store.resolve(pointer)

    assert raised.value.reason_code == "execution_invocation_store_object_unsafe"
    assert not missing_root.exists()


@pytest.mark.parametrize("target", ("store", "claim"))
def test_execution_composition_rejects_relative_roots(target: str) -> None:
    fixture_root = Path("/tmp/execution-composition-relative-fixture")
    if target == "store":
        outcome_committer = _execution_address("port:outcome")
        event_plane = _execution_address("port:event")
        outcome_projection_resolver = _execution_address("port:outcome-projection")
        outcome_validity_resolver = _execution_address("port:outcome-validity")
        with pytest.raises(ValueError, match="absolute bounded"):
            build_execution_composition_manifest(
                activation_generation=_execution_address("activation-generation:relative"),
                invocation_store_root=Path("relative-store"),
                max_bundle_bytes=1024,
                claim_vault_root=fixture_root / "vault",
                claim_cache_dir=fixture_root / "cache",
                claim_transaction_root=fixture_root / "transactions",
                claim_receipt_root=fixture_root / "cache" / "receipts",
                claim_lock_root=fixture_root / "locks",
                port_descriptors=build_execution_composition_port_descriptors(
                    trust_resolver=_execution_address("port:trust"),
                    effect_manifest_resolver=_execution_address("port:manifest"),
                    currentness_resolver=_execution_address("port:currentness"),
                    executor_registry=_execution_address("port:registry"),
                    completion_evaluator=_execution_address("port:completion"),
                    readiness_resolver=_execution_address("port:readiness"),
                    outcome_committer=outcome_committer,
                    event_plane=event_plane,
                    outcome_projection_resolver=outcome_projection_resolver,
                    outcome_validity_resolver=outcome_validity_resolver,
                ),
                attempt_journal=_execution_address("attempt-journal:relative"),
            )
    else:
        with pytest.raises(ValueError, match="absolute bounded"):
            ExecutionCompositionRoot(claim_vault_root=Path("relative-vault"))


def test_execution_invocation_store_rejects_wrong_composition_manifest(
    tmp_path: Path,
) -> None:
    fixture = _real_execution_invocation(tmp_path)
    manifest, store, composition = _configured_execution_composition(fixture, tmp_path)
    _, pointer, _ = _materialize_read_only_bundle_fixture(fixture, manifest, store)
    other = _execution_composition_manifest(
        fixture,
        Path(manifest.invocation_store_root),
        activation_generation=_execution_address("activation-generation:other"),
    )
    other_store = ExecutionInvocationBundleStore(
        root=Path(other.invocation_store_root),
        composition_manifest=other,
    )

    with pytest.raises(ExecutionAdmissionError) as raised:
        other_store.resolve(pointer)

    assert raised.value.reason_code == "execution_invocation_composition_manifest_mismatch"
    assert store.resolve(pointer).composition_manifest == ContentAddress(
        ref=manifest.manifest_ref,
        sha256=manifest.manifest_hash,
    )


def test_execution_composition_refuses_claim_root_substitution(tmp_path: Path) -> None:
    fixture = _real_execution_invocation(tmp_path)
    manifest, store, _ = _configured_execution_composition(fixture, tmp_path)
    with pytest.raises(ValueError, match="claim roots differ"):
        ExecutionCompositionRoot(
            composition_manifest=manifest,
            invocation_store=store,
            ports=_execution_composition_ports(manifest),
            claim_vault_root=fixture.prepared.vault,
            claim_cache_dir=fixture.prepared.cache,
            claim_transaction_root=fixture.prepared.transactions,
            claim_receipt_root=tmp_path / "substituted-receipts",
            claim_lock_root=fixture.prepared.locks,
        )


def test_execution_composition_refuses_missing_or_substituted_ports(tmp_path: Path) -> None:
    fixture = _real_execution_invocation(tmp_path)
    manifest, store, composition = _configured_execution_composition(fixture, tmp_path)
    prepared = fixture.prepared

    with pytest.raises(ValueError, match="must be installed together"):
        ExecutionCompositionRoot(
            composition_manifest=manifest,
            invocation_store=store,
            claim_vault_root=prepared.vault,
            claim_cache_dir=prepared.cache,
            claim_transaction_root=prepared.transactions,
            claim_receipt_root=prepared.receipts,
            claim_lock_root=prepared.locks,
        )
    with pytest.raises(ValueError, match="trust_resolver"):
        _execution_composition_ports(
            manifest,
            trust_descriptor=_execution_address("port:substituted-trust"),
        )

    assert composition.ports is not None
    assert composition.ports.descriptors == manifest.port_descriptors


def test_execution_invocation_store_put_holds_and_preserves_existing_bytes(
    tmp_path: Path,
) -> None:
    fixture = _real_execution_invocation(tmp_path)
    manifest, store, _ = _configured_execution_composition(fixture, tmp_path)
    bundle, _, object_path = _materialize_read_only_bundle_fixture(
        fixture,
        manifest,
        store,
    )
    before = object_path.read_bytes()

    with pytest.raises(ExecutionAdmissionError) as raised:
        store.put(bundle)

    assert raised.value.reason_code == "execution_invocation_store_activation_unvalidated"
    assert object_path.read_bytes() == before


@pytest.mark.parametrize("unsafe_kind", ("symlink", "mode", "hardlink", "fifo"))
def test_execution_invocation_store_refuses_unsafe_objects_without_blocking(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    fixture = _real_execution_invocation(tmp_path)
    manifest, store, _ = _configured_execution_composition(fixture, tmp_path)
    _, pointer, object_path = _materialize_read_only_bundle_fixture(
        fixture,
        manifest,
        store,
    )
    target = store.objects_root / "target"

    if unsafe_kind == "symlink":
        target.write_bytes(b"payload\n")
        target.chmod(0o600)
        object_path.unlink()
        object_path.symlink_to(target)
    elif unsafe_kind == "mode":
        object_path.chmod(0o640)
    elif unsafe_kind == "hardlink":
        os.link(object_path, target)
    else:
        object_path.unlink()
        os.mkfifo(object_path, 0o600)

    with pytest.raises(ExecutionAdmissionError) as raised:
        store.resolve(pointer)

    assert raised.value.reason_code == "execution_invocation_store_object_unsafe"


@pytest.mark.parametrize(
    ("payload", "reason_code"),
    (
        (b'{"schema":"one","schema":"two"}\n', "execution_invocation_bundle_malformed"),
        (b'{"value":NaN}\n', "execution_invocation_bundle_malformed"),
    ),
)
def test_execution_invocation_store_refuses_ambiguous_json(
    tmp_path: Path,
    payload: bytes,
    reason_code: str,
) -> None:
    fixture = _real_execution_invocation(tmp_path)
    manifest, store, _ = _configured_execution_composition(fixture, tmp_path)
    _, pointer, _ = _materialize_read_only_bundle_fixture(fixture, manifest, store)
    hostile_pointer = _pointer_for_storage_bytes(pointer, payload)
    hostile_path = store.objects_root / f"{hostile_pointer.canonical_bytes.sha256}.json"
    hostile_path.write_bytes(payload)
    hostile_path.chmod(0o600)

    with pytest.raises(ExecutionAdmissionError) as raised:
        store.resolve(hostile_pointer)

    assert raised.value.reason_code == reason_code


def test_execution_invocation_store_refuses_noncanonical_json(tmp_path: Path) -> None:
    fixture = _real_execution_invocation(tmp_path)
    manifest, store, _ = _configured_execution_composition(fixture, tmp_path)
    _, pointer, _ = _materialize_read_only_bundle_fixture(fixture, manifest, store)
    bundle = store.resolve(pointer)
    payload = (
        json.dumps(
            bundle.model_dump(mode="json", by_alias=True),
            allow_nan=False,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        ).encode("ascii")
        + b"\n"
    )
    hostile_pointer = _pointer_for_storage_bytes(pointer, payload)
    hostile_path = store.objects_root / f"{hostile_pointer.canonical_bytes.sha256}.json"
    hostile_path.write_bytes(payload)
    hostile_path.chmod(0o600)

    with pytest.raises(ExecutionAdmissionError) as raised:
        store.resolve(hostile_pointer)

    assert raised.value.reason_code == "execution_invocation_bundle_noncanonical"


def test_execution_invocation_store_detects_same_size_aba_before_seal(
    tmp_path: Path,
) -> None:
    fixture = _real_execution_invocation(tmp_path)
    manifest, store, _ = _configured_execution_composition(fixture, tmp_path)
    _, pointer, object_path = _materialize_read_only_bundle_fixture(
        fixture,
        manifest,
        store,
    )
    original = object_path.read_bytes()
    original_seal = execution_admission.ReadOnlyFsSnapshot.seal

    def race_before_seal(snapshot: execution_admission.ReadOnlyFsSnapshot):
        object_path.write_bytes(original[::-1])
        object_path.write_bytes(original)
        return original_seal(snapshot)

    with (
        mock.patch.object(
            execution_admission.ReadOnlyFsSnapshot,
            "seal",
            race_before_seal,
        ),
        pytest.raises(ExecutionAdmissionError) as raised,
    ):
        store.resolve(pointer)

    assert raised.value.reason_code == "execution_invocation_store_object_unsafe"


def test_execution_invocation_store_ignores_unrelated_object_churn(
    tmp_path: Path,
) -> None:
    fixture = _real_execution_invocation(tmp_path)
    manifest, store, _ = _configured_execution_composition(fixture, tmp_path)
    _, pointer, _ = _materialize_read_only_bundle_fixture(fixture, manifest, store)
    original_seal = execution_admission.ReadOnlyFsSnapshot.seal
    unrelated = store.objects_root / ("f" * 64 + ".json")
    injected = False

    def churn_before_seal(snapshot: execution_admission.ReadOnlyFsSnapshot):
        nonlocal injected
        if not injected:
            injected = True
            unrelated.write_bytes(b"unrelated\n")
            unrelated.chmod(0o600)
            unrelated.unlink()
        return original_seal(snapshot)

    with mock.patch.object(
        execution_admission.ReadOnlyFsSnapshot,
        "seal",
        churn_before_seal,
    ):
        resolved = store.resolve(pointer)

    assert resolved.bundle_ref == pointer.bundle.ref


def test_execution_invocation_store_concurrent_exact_reads_are_idempotent(
    tmp_path: Path,
) -> None:
    fixture = _real_execution_invocation(tmp_path)
    manifest, store, _ = _configured_execution_composition(fixture, tmp_path)
    bundle, pointer, object_path = _materialize_read_only_bundle_fixture(
        fixture,
        manifest,
        store,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = tuple(executor.submit(store.resolve, pointer) for _ in range(2))
        bundles = tuple(future.result(timeout=5) for future in futures)

    assert bundles == (bundle, bundle)
    assert object_path.stat().st_nlink == 1


def test_execution_invocation_store_put_hold_does_not_create_absent_object(
    tmp_path: Path,
) -> None:
    fixture = _real_execution_invocation(tmp_path)
    manifest, store, _ = _configured_execution_composition(fixture, tmp_path)
    bundle = build_execution_invocation_bundle(
        fixture.invocation,
        composition_manifest=manifest,
        queried_at=QUERY_TIME,
    )
    pointer = build_execution_invocation_bundle_pointer(bundle)
    object_path = store.objects_root / f"{pointer.canonical_bytes.sha256}.json"

    with pytest.raises(ExecutionAdmissionError) as raised:
        store.put(bundle)

    assert raised.value.reason_code == "execution_invocation_store_activation_unvalidated"
    assert not object_path.exists()


@pytest.mark.parametrize(
    ("unsafe_kind", "reason_code"),
    (
        ("missing", "execution_composition_manifest_missing"),
        ("mode", "execution_invocation_store_object_unsafe"),
        ("symlink", "execution_invocation_store_object_unsafe"),
        ("hardlink", "execution_invocation_store_object_unsafe"),
        ("tamper", "execution_composition_manifest_invalid"),
    ),
)
def test_execution_store_refuses_unsafe_installed_composition_manifest(
    tmp_path: Path,
    unsafe_kind: str,
    reason_code: str,
) -> None:
    fixture = _real_execution_invocation(tmp_path)
    manifest, store, _ = _configured_execution_composition(fixture, tmp_path)
    _, pointer, _ = _materialize_read_only_bundle_fixture(fixture, manifest, store)
    manifest_path = store.manifest_path
    target = store.root / "manifest-target.json"

    if unsafe_kind == "missing":
        manifest_path.unlink()
    elif unsafe_kind == "mode":
        manifest_path.chmod(0o640)
    elif unsafe_kind == "symlink":
        target.write_bytes(manifest_path.read_bytes())
        target.chmod(0o600)
        manifest_path.unlink()
        manifest_path.symlink_to(target)
    elif unsafe_kind == "hardlink":
        os.link(manifest_path, target)
    else:
        manifest_path.write_bytes(b'{"schema":"tampered"}\n')
        manifest_path.chmod(0o600)

    with pytest.raises(ExecutionAdmissionError) as raised:
        store.resolve(pointer)

    assert raised.value.reason_code == reason_code


@pytest.mark.parametrize("value", (0, True, 16 * 1024 * 1024 + 1))
def test_execution_composition_manifest_rejects_unsafe_bundle_bounds(
    tmp_path: Path,
    value: object,
) -> None:
    fixture = _real_execution_invocation(tmp_path)

    with pytest.raises(ValueError):
        _execution_composition_manifest(
            fixture,
            tmp_path / "bounded-store",
            max_bundle_bytes=value,  # type: ignore[arg-type]
        )


def test_execution_composition_manifest_rejects_store_claim_overlap(
    tmp_path: Path,
) -> None:
    fixture = _real_execution_invocation(tmp_path)

    with pytest.raises(ValueError, match="must not overlap claim roots"):
        _execution_composition_manifest(fixture, fixture.prepared.cache)


def test_bundle_semantics_bind_the_installed_composition_manifest(tmp_path: Path) -> None:
    fixture = _real_execution_invocation(tmp_path)
    manifest, store, _ = _configured_execution_composition(fixture, tmp_path)
    _, pointer, _ = _materialize_read_only_bundle_fixture(fixture, manifest, store)
    bundle = store.resolve(pointer)
    other = _execution_composition_manifest(
        fixture,
        tmp_path / "other-store",
        activation_generation=_execution_address("activation-generation:other"),
    )
    payload = bundle.model_dump(mode="json", by_alias=True)
    payload["composition_manifest"] = {
        "ref": other.manifest_ref,
        "sha256": other.manifest_hash,
    }

    with pytest.raises(ValueError, match="does not bind its body"):
        ExecutionInvocationBundle.model_validate(payload)

    assert bundle.composition_manifest == ContentAddress(
        ref=manifest.manifest_ref,
        sha256=manifest.manifest_hash,
    )


def test_activation_receipt_presence_does_not_activate_composition(tmp_path: Path) -> None:
    fixture = _real_execution_invocation(tmp_path)
    prepared = fixture.prepared
    manifest = _execution_composition_manifest(
        fixture,
        tmp_path / "receipt-store",
        activation_receipt=_execution_address("activation-receipt:unvalidated"),
    )
    _install_execution_composition_manifest(manifest)
    store = ExecutionInvocationBundleStore(
        root=Path(manifest.invocation_store_root),
        composition_manifest=manifest,
    )
    composition = ExecutionCompositionRoot(
        composition_manifest=manifest,
        invocation_store=store,
        ports=_execution_composition_ports(manifest),
        claim_vault_root=prepared.vault,
        claim_cache_dir=prepared.cache,
        claim_transaction_root=prepared.transactions,
        claim_receipt_root=prepared.receipts,
        claim_lock_root=prepared.locks,
    )

    with pytest.raises(ExecutionAdmissionError) as raised:
        composition.require_effect_activation()

    assert manifest.may_authorize is False
    assert raised.value.reason_code == "execution_composition_activation_unvalidated"


def test_execution_admission_schema_is_the_checked_in_generated_schema() -> None:
    root = Path(__file__).resolve().parents[1]
    checked_in = json.loads(
        (root / "schemas" / "execution-admission.schema.json").read_text(encoding="utf-8")
    )
    assert checked_in == execution_admission_schema()
