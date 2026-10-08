"""Publication completion joins use isolated receipts and a fake HTTP boundary."""

import hashlib
import json
import socket
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from shared import glm_review_execution as transport
from shared.dispatcher_policy import build_route_authority_receipt
from shared.execution_admission import (
    ContentAddress,
    build_executor_descriptor,
    build_executor_registry_projection,
)
from shared.platform_capability_registry import ExecutionDescriptor
from shared.publication_hardening import execution
from shared.publication_hardening import review as review_module
from shared.publication_hardening.admission import PublicationAdmissionError
from shared.publication_hardening.execution import AdmittedPublicationCompletion
from shared.publication_hardening.review import ReviewPass
from shared.quota_spend_ledger import PaidRouteRequest, SpendReason, load_quota_spend_ledger
from tests.publication_admission_fixtures import install_publication_admission

ROOT = Path(__file__).resolve().parents[2]


def address(path):
    return ContentAddress(
        ref="source:" + path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest()
    )


@pytest.fixture
def bound(monkeypatch, tmp_path):
    route_path, receipt_path, row, receipt = install_publication_admission(monkeypatch, tmp_path)
    now = datetime.now(UTC)
    descriptor = ExecutionDescriptor(model_id="z_ai-glm-5.3", effort="none")
    registry = json.loads((ROOT / "config/platform-capability-registry.json").read_text())
    for route in registry["routes"]:
        if route["route_id"] == row["route_id"]:
            route["execution_descriptor"] = descriptor.model_dump(mode="json")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry))
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_REGISTRY", str(registry_path))
    ledger_path = tmp_path / "ledger.json"
    ledger = json.loads((ROOT / "config/quota-spend-ledger-fixtures.json").read_text())
    ledger["captured_at"] = now.isoformat()
    budget = next(
        b
        for b in ledger["transition_budgets"]
        if b["budget_id"] == "tb-20260706-zai-glmcp-payg-review"
    )
    budget.update(
        budget_id="tb-20261008-synthetic-publication",
        authority_case="CASE-SYNTHETIC",
        profiles_allowed=["synthetic-publication"],
        task_classes_allowed=["publication-review"],
        created_at=(now - timedelta(hours=1)).isoformat(),
        expires_at=(now + timedelta(hours=1)).isoformat(),
        subscription_path_checked_at=now.isoformat(),
        total_cap_usd="1",
        daily_cap_usd="1",
        per_task_cap_usd="1",
    )
    ledger["transition_budgets"] = [budget]
    ledger["spend_receipts"] = []
    ledger["spend_gate_decisions"] = []
    ledger["provider_dependencies"] = []
    ledger["artifact_provenance"] = []
    ledger["renewal_records"] = []
    ledger_path.write_text(json.dumps(ledger))
    executor = build_executor_descriptor(
        executor=address(Path(transport.__file__)),
        adapter=address(Path(execution.__file__)),
        harness=address(Path(review_module.__file__)),
        runtime_identity=address(Path(sys.executable).resolve()),
        active_generation_roots=[address(registry_path)],
        execution_host=socket.gethostname(),
        platform="api",
        mode="headless",
        profile="synthetic-publication",
        selected_descriptor_leaf=row["route_id"],
        entrypoint="shared.publication_hardening.execution.AdmittedPublicationCompletion",
    )
    projection = build_executor_registry_projection(
        execution_host=socket.gethostname(),
        registry_source=address(registry_path),
        event_frontier=address(route_path),
        descriptors=[executor],
        observed_at=now,
        checked_at=now,
        stale_after=now + timedelta(minutes=10),
    )
    qualified = build_route_authority_receipt(
        receipt_type=receipt.receipt_type,
        route_id=receipt.route_id,
        task_ids=receipt.task_ids,
        mutation_surfaces=receipt.mutation_surfaces,
        quality_floors=["frontier_review_required"],
        evidence_refs=[
            "authority-case:CASE-SYNTHETIC",
            "budget:" + budget["budget_id"],
            executor.descriptor_ref,
            projection.projection_ref,
        ],
        issued_at=now,
    )
    receipt_path.write_text(qualified.model_dump_json())
    binding = AdmittedPublicationCompletion(
        request=PaidRouteRequest(
            route_id=row["route_id"],
            task_id=row["task_id"],
            provider="z_ai",
            profile="synthetic-publication",
            task_class="publication-review",
            quality_floor="frontier_review_required",
            estimated_cost_usd=Decimal("0.02"),
        ),
        descriptor=descriptor,
        authority_case="CASE-SYNTHETIC",
        budget_id=budget["budget_id"],
        task_hash="sha256:" + "a" * 64,
        ledger_path=ledger_path,
        base_url="https://api.z.ai/api/paas/v4",
        thinking="enabled",
        timeout_seconds=10,
        spend_reason=SpendReason.BURST_CAPACITY,
        quality_preservation_reason="synthetic explicitly admitted publication completion",
        api_key="synthetic-secret",  # pragma: allowlist secret - isolated fake transport
        executor=executor,
        projection=projection,
    )
    return binding, route_path, receipt_path, row


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self):
        return json.dumps(self.body).encode()


def response_body():
    return dict(
        model="glm-5.3",
        choices=[
            dict(
                finish_reason="stop",
                message=dict(
                    content=json.dumps(
                        {
                            "overall_confidence": 0.93,
                            "claims": [{"text": "Clean draft.", "confidence": 0.93}],
                        }
                    )
                ),
            )
        ],
        usage=dict(
            prompt_tokens=50,
            completion_tokens=30,
            prompt_tokens_details={"cached_tokens": 10},
            completion_tokens_details={"reasoning_tokens": 10},
        ),
    )


def use(binding):
    return ReviewPass(model=binding.descriptor.model_id, completion=binding).review_text(
        "Clean draft."
    )


def receipts(binding):
    return load_quota_spend_ledger(binding.ledger_path).spend_receipts


def test_publication_json_preserves_messages_and_accounts_before_parse(bound, monkeypatch):
    binding, *_ = bound
    seen = []

    def send(request, **kwargs):
        [pending] = receipts(binding)
        assert pending.reconciliation_state.value == "pending"
        assert pending.task_id == binding.request.task_id
        assert pending.authority_case == binding.authority_case
        assert pending.model_id == binding.descriptor.model_id
        seen.append(json.loads(request.data))
        assert request.full_url == binding.base_url + "/chat/completions"
        return Response(response_body())

    monkeypatch.setattr(transport, "open_no_redirect", send)
    parse = review_module.parse_review_response

    def parse_after_commit(*args, **kwargs):
        [r] = receipts(binding)
        assert r.reconciliation_state.value == "reconciled"
        assert r.actual_cost_usd == transport.glmcp_payg_usage_cost_usd(
            model="glm-5.3", prompt_tokens=50, cached_tokens=10, completion_tokens=30
        )
        return parse(*args, **kwargs)

    monkeypatch.setattr(review_module, "parse_review_response", parse_after_commit)
    result = use(binding)
    assert result.passes() and result.overall_confidence == 0.93
    assert len(seen) == 1
    assert seen[0]["model"] == "glm-5.3"
    assert "JSON" in seen[0]["messages"][0]["content"]
    assert "Clean draft." in seen[0]["messages"][1]["content"]
    assert "stop" not in seen[0]


@pytest.mark.parametrize(
    "defect",
    [
        "task",
        "route",
        "task_class",
        "profile",
        "budget",
        "authority",
        "estimate",
        "endpoint",
        "descriptor",
        "executor",
        "projection",
        "source",
        "quality",
        "receipt",
        "expired",
        "ledger-stale",
        "foreign-route-receipt",
    ],
)
def test_pre_call_refusals_have_no_transport_or_reservation(bound, monkeypatch, defect):
    binding, route_path, receipt_path, row = bound
    if defect in {"task", "route", "task_class", "profile", "estimate"}:
        fields = {
            "task": "task_id",
            "route": "route_id",
            "task_class": "task_class",
            "profile": "profile",
            "estimate": "estimated_cost_usd",
        }
        values = {
            "task": "cc-task-foreign",
            "route": "api.headless.foreign",
            "task_class": "independent-review",
            "profile": "foreign",
            "estimate": Decimal("0.000001"),
        }
        binding = replace(
            binding, request=binding.request.model_copy(update={fields[defect]: values[defect]})
        )
    elif defect == "budget":
        binding = replace(binding, budget_id="tb-20261008-foreign")
    elif defect == "authority":
        binding = replace(binding, authority_case="CASE-FOREIGN")
    elif defect == "endpoint":
        binding = replace(binding, base_url="https://example.invalid/api")
    elif defect == "descriptor":
        binding = replace(
            binding, descriptor=binding.descriptor.model_copy(update={"fast_mode": "on"})
        )
    elif defect == "executor":
        binding = replace(binding, executor=None)
    elif defect == "projection":
        binding = replace(binding, projection=None)
    elif defect == "source":
        monkeypatch.setattr(execution.sys, "executable", str(receipt_path))
    elif defect == "quality":
        binding = replace(
            binding, request=binding.request.model_copy(update={"quality_floor": "unqualified"})
        )
    elif defect == "receipt":
        receipt_path.unlink()
    elif defect == "expired":
        row["created_at"] = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        route_path.write_text(json.dumps(row) + "\n")
    elif defect == "ledger-stale":
        d = json.loads(binding.ledger_path.read_text())
        d["captured_at"] = "2020-01-01T00:00:00Z"
        binding.ledger_path.write_text(json.dumps(d))
    elif defect == "foreign-route-receipt":
        r = json.loads(receipt_path.read_text())
        r["task_ids"] = ["cc-task-foreign"]
        receipt_path.write_text(json.dumps(r))
    calls = []
    monkeypatch.setattr(
        transport, "open_no_redirect", lambda *a, **kw: calls.append(a) or Response(response_body())
    )
    with pytest.raises(PublicationAdmissionError):
        use(binding)
    assert calls == [] and receipts(binding) == ()


@pytest.mark.parametrize(
    "defect",
    [
        "missing-model",
        "wrong-model",
        "missing-usage",
        "cached-over-prompt",
        "output-bound",
        "reasoning-bound",
        "cost-bound",
        "unknown-finish",
        "truncated",
        "empty",
        "network",
        "http1210",
        "foreign-reservation",
    ],
)
def test_ambiguous_or_foreign_completion_holds_before_content(bound, monkeypatch, defect):
    binding, *_ = bound
    body = response_body()
    calls = []
    if defect == "missing-model":
        body.pop("model")
    elif defect == "wrong-model":
        body["model"] = "glm-5.2"
    elif defect == "missing-usage":
        body.pop("usage")
    elif defect == "cached-over-prompt":
        body["usage"]["prompt_tokens_details"]["cached_tokens"] = 51
    elif defect == "output-bound":
        body["usage"]["completion_tokens"] = 901
    elif defect == "reasoning-bound":
        body["usage"]["completion_tokens_details"]["reasoning_tokens"] = 31
    elif defect == "cost-bound":
        body["usage"]["prompt_tokens"] = 1_000_000
    elif defect == "unknown-finish":
        body["choices"][0]["finish_reason"] = "unknown"
    elif defect == "truncated":
        body["choices"][0]["finish_reason"] = "length"
    elif defect == "empty":
        body["choices"][0]["message"]["content"] = ""

    def send(*args, **kwargs):
        calls.append(1)
        if defect == "network":
            raise TimeoutError()
        if defect == "http1210":
            import io
            import urllib.error

            raise urllib.error.HTTPError(
                binding.base_url,
                400,
                "forced thinking",
                {},
                io.BytesIO(b'{"error":{"code":"1210"}}'),
            )
        if defect == "foreign-reservation":
            d = json.loads(binding.ledger_path.read_text())
            d["spend_receipts"][0]["task_id"] = "cc-task-foreign"
            binding.ledger_path.write_text(json.dumps(d))
        return Response(body)

    monkeypatch.setattr(transport, "open_no_redirect", send)
    monkeypatch.setattr(
        review_module,
        "parse_review_response",
        lambda *a, **kw: pytest.fail("unaccounted content reached parser"),
    )
    with pytest.raises(PublicationAdmissionError):
        use(binding)
    assert calls == [1]
    [r] = receipts(binding)
    assert r.reconciliation_state.value == (
        "pending" if defect == "foreign-reservation" else "frozen_refused"
    )
    assert r.actual_cost_usd is None


def test_full_messages_and_output_ceiling_are_priced(bound, monkeypatch):
    binding, *_ = bound
    seen = []
    monkeypatch.setattr(
        transport, "open_no_redirect", lambda *a, **kw: seen.append(a) or Response(response_body())
    )
    # A short user message cannot hide a much larger system prompt from pricing.
    with pytest.raises(PublicationAdmissionError):
        binding(
            model=binding.descriptor.model_id,
            messages=(
                {"role": "system", "content": "x" * 100_000},
                {"role": "user", "content": "ok"},
            ),
            temperature=0,
            max_tokens=900,
        )
    assert seen == [] and receipts(binding) == ()


def test_durable_reservation_failure_prevents_request(bound, monkeypatch):
    binding, *_ = bound
    seen = []
    monkeypatch.setattr(
        transport, "open_no_redirect", lambda *a, **kw: seen.append(a) or Response(response_body())
    )
    monkeypatch.setattr(
        transport,
        "_write_json_atomic",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("synthetic write failure")),
    )
    with pytest.raises(PublicationAdmissionError):
        use(binding)
    assert seen == [] and receipts(binding) == ()


def test_reconciliation_failure_holds_content_and_retains_pending(bound, monkeypatch):
    binding, *_ = bound

    def send(*a, **kw):
        monkeypatch.setattr(
            transport,
            "_write_json_atomic",
            lambda *a, **kw: (_ for _ in ()).throw(OSError("synthetic write failure")),
        )
        return Response(response_body())

    monkeypatch.setattr(transport, "open_no_redirect", send)
    monkeypatch.setattr(
        review_module, "parse_review_response", lambda *a, **kw: pytest.fail("content escaped")
    )
    with pytest.raises(PublicationAdmissionError):
        use(binding)
    assert receipts(binding)[0].reconciliation_state.value == "pending"


def test_concurrent_calls_cannot_both_spend_last_budget(bound, monkeypatch):
    binding, *_ = bound
    d = json.loads(binding.ledger_path.read_text())
    for key in ("total_cap_usd", "daily_cap_usd", "per_task_cap_usd"):
        d["transition_budgets"][0][key] = "0.025"
    binding.ledger_path.write_text(json.dumps(d))
    entered = threading.Event()
    release = threading.Event()
    evaluating = threading.Event()
    second_started = threading.Event()
    counter_lock = threading.Lock()
    count = 0
    calls = []
    original_evaluate = transport.evaluate_paid_route_eligibility

    def evaluate(ledger, request):
        nonlocal count
        with counter_lock:
            count += 1
            ordinal = count
        if ordinal == 1:
            evaluating.set()
            assert second_started.wait(5)
            # Expose the read/reserve race if the cross-process ledger lock is removed.
            threading.Event().wait(0.2)
        return original_evaluate(ledger, request)

    def send(*a, **kw):
        calls.append(1)
        assert any(r.reconciliation_state.value == "pending" for r in receipts(binding))
        entered.set()
        assert release.wait(10)
        return Response(response_body())

    def second_call():
        second_started.set()
        return use(binding)

    monkeypatch.setattr(transport, "open_no_redirect", send)
    monkeypatch.setattr(transport, "evaluate_paid_route_eligibility", evaluate)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(use, binding)
        assert evaluating.wait(5)
        second = pool.submit(second_call)
        try:
            assert entered.wait(5)
            threading.Event().wait(0.3)
        finally:
            release.set()
        outcomes = []
        for future in (first, second):
            try:
                outcomes.append(future.result(timeout=10).passes())
            except PublicationAdmissionError:
                outcomes.append(False)
    assert sorted(outcomes) == [False, True]
    assert calls == [1] and len(receipts(binding)) == 1


def test_plain_completion_callback_cannot_qualify_execution(monkeypatch, tmp_path):
    install_publication_admission(monkeypatch, tmp_path)
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        return json.dumps({"overall_confidence": 0.99})

    with pytest.raises(PublicationAdmissionError, match="review_executor_unqualified"):
        ReviewPass(model="claude-opus-4-8", completion=completion).review_text("Clean draft.")
    assert calls == []


@pytest.mark.parametrize(
    "defect",
    ["no-budget", "ledger-authority", "cap-exhausted", "unqualified-receipt", "stale-executor"],
)
def test_qualification_and_budget_cannot_be_borrowed(bound, monkeypatch, defect):
    binding, _, receipt_path, _ = bound
    if defect in {"no-budget", "ledger-authority", "cap-exhausted"}:
        data = json.loads(binding.ledger_path.read_text())
        if defect == "no-budget":
            data["transition_budgets"] = []
        elif defect == "ledger-authority":
            data["transition_budgets"][0]["authority_case"] = "CASE-FOREIGN"
        else:
            data["transition_budgets"][0]["per_task_cap_usd"] = "0.001"
        binding.ledger_path.write_text(json.dumps(data))
    else:
        evidence = ["authority-case:CASE-SYNTHETIC", "budget:" + binding.budget_id]
        if defect == "stale-executor":
            now = datetime.now(UTC)
            projection = build_executor_registry_projection(
                execution_host=binding.projection.execution_host,
                registry_source=binding.projection.registry_source,
                event_frontier=binding.projection.event_frontier,
                descriptors=[binding.executor],
                observed_at=now - timedelta(hours=2),
                checked_at=now - timedelta(hours=2),
                stale_after=now - timedelta(hours=1),
            )
            binding = replace(binding, projection=projection)
            evidence += [binding.executor.descriptor_ref, projection.projection_ref]
        old = json.loads(receipt_path.read_text())
        receipt = build_route_authority_receipt(
            receipt_type="connector_mutation",
            route_id=binding.request.route_id,
            task_ids=[binding.request.task_id],
            mutation_surfaces=old["mutation_surfaces"],
            evidence_refs=evidence,
            quality_floors=[binding.request.quality_floor],
            issued_at=datetime.now(UTC),
        )
        receipt_path.write_text(receipt.model_dump_json())
    calls = []
    monkeypatch.setattr(
        transport, "open_no_redirect", lambda *a, **kw: calls.append(a) or Response(response_body())
    )
    with pytest.raises(PublicationAdmissionError):
        use(binding)
    assert calls == [] and receipts(binding) == ()
