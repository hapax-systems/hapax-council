"""Publication effects require route admission even when content checks pass."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from prometheus_client import CollectorRegistry

from agents.publication_bus.publisher_kit import (
    AllowlistGate,
    Publisher,
    PublisherPayload,
    PublisherResult,
)
from agents.publish_orchestrator.orchestrator import Orchestrator
from shared.preprint_artifact import PreprintArtifact
from shared.publication_hardening.admission import (
    PublicationAdmissionError,
    evaluate_publication_admission,
)
from shared.publication_hardening.gate import (
    PublicationGateChildResult,
    PublicationGateDecision,
    PublicationGateResult,
)
from shared.publication_hardening.review import ReviewPass
from tests.publication_admission_fixtures import install_publication_admission


def test_unadmitted_review_never_calls_completion(monkeypatch, tmp_path):
    monkeypatch.setenv("HAPAX_ROUTE_DECISION_LEDGER", str(tmp_path / "absent.jsonl"))
    completion = Mock(return_value='{"overall_confidence": 0.99}')
    review = ReviewPass(completion=completion)
    try:
        review.review_text("A draft with clean content.")
    except RuntimeError:
        pass
    completion.assert_not_called()


def test_unadmitted_publisher_never_emits(monkeypatch, tmp_path):
    monkeypatch.setenv("HAPAX_ROUTE_DECISION_LEDGER", str(tmp_path / "absent.jsonl"))

    class CleanPublisher(Publisher):
        surface_name = "test-surface"
        allowlist = AllowlistGate(surface_name=surface_name, permitted=frozenset({"allowed"}))
        _emit = Mock(return_value=PublisherResult(ok=True))

    result = CleanPublisher().publish(PublisherPayload(target="allowed", text="Clean text."))
    CleanPublisher._emit.assert_not_called()
    assert result.refused
    assert "route" in result.detail


def test_content_pass_does_not_admit_fanout(monkeypatch, tmp_path):
    monkeypatch.setenv("HAPAX_ROUTE_DECISION_LEDGER", str(tmp_path / "absent.jsonl"))
    passing = PublicationGateResult(
        decision=PublicationGateDecision.PASS, generated_at="2026-10-08T00:00:00Z", child_results=()
    )
    gate = Mock()
    gate.evaluate.return_value = passing
    orchestrator = Orchestrator(
        state_root=tmp_path,
        hardening_gate=gate,
        public_event_path=None,
        registry=CollectorRegistry(),
    )
    monkeypatch.setattr(
        orchestrator,
        "_public_gate_receipts_child",
        lambda _: PublicationGateChildResult(
            name="public_gate_receipts", decision=PublicationGateDecision.PASS
        ),
    )
    emit = Mock(return_value="ok")
    monkeypatch.setattr(orchestrator, "_resolve_entry_point", lambda _: emit)
    artifact = PreprintArtifact(
        slug="clean", title="Clean", body_md="Clean text.", surfaces_targeted=["omg-weblog"]
    )
    artifact.mark_approved(by_referent="Oudepode")
    with ThreadPoolExecutor() as pool:
        orchestrator._dispatch(artifact, pool=pool)
    emit.assert_not_called()
    gate.evaluate.assert_not_called()


@pytest.mark.parametrize(
    "key,value,reason",
    [
        ("action", "hold", "route_launch_not_allowed"),
        ("launch_allowed", False, "route_launch_not_allowed"),
        ("authority_allowed", False, "route_authority_not_allowed"),
        ("route_policy_green", False, "route_policy_not_green"),
        ("quota_freshness_green", False, "quota_freshness_not_green"),
        ("quota_evidence_refs", [], "quota_evidence_refs_absent"),
        ("resource_freshness_green", False, "resource_freshness_not_green"),
        ("resource_state_refs", [], "resource_state_refs_absent"),
        ("registry_freshness_green", False, "registry_freshness_not_green"),
        ("quality_floor_satisfied", False, "quality_floor_not_satisfied"),
        ("route_id", "codex.headless.full", "publication_route_identity_mismatch"),
        ("lane", "", "publication_route_identity_mismatch"),
        ("task_id", "wrong-task", "route_decision_absent"),
    ],
)
def test_route_refusal_has_no_positive_admission(monkeypatch, tmp_path, key, value, reason):
    ledger, _, row, _ = install_publication_admission(monkeypatch, tmp_path)
    assert evaluate_publication_admission("omg-weblog").allowed
    row[key] = value
    ledger.write_text(json.dumps(row) + "\n")
    result = evaluate_publication_admission("omg-weblog")
    assert not result.allowed
    assert result.reason_code == reason


@pytest.mark.parametrize(
    "age,reason", [(25, "route_decision_stale"), (-1, "route_decision_from_future")]
)
def test_expired_or_future_route_holds(monkeypatch, tmp_path, age, reason):
    ledger, _, row, _ = install_publication_admission(monkeypatch, tmp_path)
    row["created_at"] = (datetime.now(UTC) - timedelta(hours=age)).isoformat()
    ledger.write_text(json.dumps(row) + "\n")
    assert evaluate_publication_admission("omg-weblog").reason_code == reason


@pytest.mark.parametrize("payload", ["{", "[]", "null", '"text"'])
def test_malformed_route_held_without_throwing(monkeypatch, tmp_path, payload):
    ledger, _, _, _ = install_publication_admission(monkeypatch, tmp_path)
    ledger.write_text(payload + "\n")
    result = evaluate_publication_admission("omg-weblog")
    assert not result.allowed


def test_scope_is_specific_to_surface(monkeypatch, tmp_path):
    install_publication_admission(monkeypatch, tmp_path)
    result = evaluate_publication_admission("unadmitted-surface")
    assert not result.allowed
    assert result.reason_code == "connector_mutation_surface_mismatch"


def test_missing_authority_receipt_holds(monkeypatch, tmp_path):
    _, receipt, _, _ = install_publication_admission(monkeypatch, tmp_path)
    receipt.unlink()
    result = evaluate_publication_admission("omg-weblog")
    assert not result.allowed
    assert result.reason_code == "connector_mutation_receipt_absent"


def test_later_refusal_supersedes_green(monkeypatch, tmp_path):
    ledger, _, row, _ = install_publication_admission(monkeypatch, tmp_path)
    row["action"] = "hold"
    with ledger.open("a") as stream:
        stream.write(json.dumps(row) + "\n")
    assert not evaluate_publication_admission("omg-weblog").allowed


def test_alias_is_not_served_identity(monkeypatch, tmp_path):
    install_publication_admission(monkeypatch, tmp_path)
    completion = Mock(return_value='{"overall_confidence": 0.99}')
    with pytest.raises(PublicationAdmissionError) as held:
        ReviewPass(completion=completion).review_text("Clean draft.")
    assert held.value.result.reason_code == "review_model_identity_mismatch"
    completion.assert_not_called()


@pytest.mark.parametrize("leaf", ["claude.headless.full", "api.headless.api_frontier", ""])
def test_selected_descriptor_must_belong_to_admitted_route(monkeypatch, tmp_path, leaf):
    ledger, _, row, _ = install_publication_admission(monkeypatch, tmp_path)
    row["selected_descriptor_leaf"] = leaf
    ledger.write_text(json.dumps(row) + "\n")
    result = evaluate_publication_admission("review", review_model="claude-opus-4-8")
    assert not result.allowed
    assert result.reason_code == "review_descriptor_route_mismatch"


def test_receipts_do_not_qualify_the_legacy_gateway(monkeypatch, tmp_path):
    install_publication_admission(monkeypatch, tmp_path)
    with pytest.raises(PublicationAdmissionError) as held:
        ReviewPass(model="claude-opus-4-8").review_text("Clean draft.")
    assert held.value.result.reason_code == "review_execution_binding_absent"


def test_route_hold_is_not_editorial_review_or_overridable(monkeypatch, tmp_path):
    from shared.publication_hardening.codebase import CodebaseDecision, CodebaseVerificationReport
    from shared.publication_hardening.gate import PublicationHardeningGate

    monkeypatch.delenv("HAPAX_PUBLICATION_TASK_ID", raising=False)
    gate = PublicationHardeningGate(
        lint_runner=lambda *_: (),
        entity_checker=lambda *_: (),
        codebase_verifier=lambda *_: CodebaseVerificationReport(decision=CodebaseDecision.PASS),
    )
    artifact = PreprintArtifact(
        slug="clean",
        title="Clean",
        body_md="Clean.",
        surfaces_targeted=["omg-weblog"],
        publication_gate_override={"by_referent": "Oudepode", "reason": "content accepted"},
    )
    result = gate.evaluate(artifact)
    assert result.decision == PublicationGateDecision.HOLD
    assert result.review_report is None
    route = next(child for child in result.child_results if child.name == "route_resource")
    assert route.report["allowed"] is False
    assert not any(child.name == "review" for child in result.child_results)


def test_future_authority_receipt_holds(monkeypatch, tmp_path):
    from shared.dispatcher_policy import build_route_authority_receipt

    _, path, _, receipt = install_publication_admission(monkeypatch, tmp_path)
    future = build_route_authority_receipt(
        receipt_type=receipt.receipt_type,
        route_id=receipt.route_id,
        task_ids=receipt.task_ids,
        mutation_surfaces=receipt.mutation_surfaces,
        evidence_refs=receipt.evidence_refs,
        issued_at=datetime.now(UTC) + timedelta(hours=1),
    )
    path.write_text(future.model_dump_json())
    assert not evaluate_publication_admission("omg-weblog").allowed


def test_per_surface_recheck_holds_expired_admission(monkeypatch, tmp_path):
    ledger, _, row, _ = install_publication_admission(monkeypatch, tmp_path)
    gate = Mock()

    def pass_content(_):
        row["action"] = "hold"
        ledger.write_text(json.dumps(row) + "\n")
        return PublicationGateResult(
            decision=PublicationGateDecision.PASS,
            generated_at="2026-10-08T00:00:00Z",
            child_results=(),
        )

    gate.evaluate.side_effect = pass_content
    orchestrator = Orchestrator(
        state_root=tmp_path,
        hardening_gate=gate,
        public_event_path=None,
        registry=CollectorRegistry(),
    )
    monkeypatch.setattr(
        orchestrator,
        "_public_gate_receipts_child",
        lambda _: PublicationGateChildResult(
            name="public_gate_receipts", decision=PublicationGateDecision.PASS
        ),
    )
    emit = Mock(return_value="ok")
    monkeypatch.setattr(orchestrator, "_resolve_entry_point", lambda _: emit)
    artifact = PreprintArtifact(
        slug="expired", title="Clean", body_md="Clean.", surfaces_targeted=["omg-weblog"]
    )
    artifact.mark_approved(by_referent="Oudepode")
    with ThreadPoolExecutor() as pool:
        orchestrator._dispatch(artifact, pool=pool)
    gate.evaluate.assert_called_once()
    emit.assert_not_called()
    record = json.loads((tmp_path / "publish/log/expired.omg-weblog.json").read_text())
    assert record["result"] == "route_resource_hold"


def test_review_needs_spend_authority_scope(monkeypatch, tmp_path):
    from shared.dispatcher_policy import build_route_authority_receipt

    _, path, _, receipt = install_publication_admission(monkeypatch, tmp_path)
    without_spend = build_route_authority_receipt(
        receipt_type=receipt.receipt_type,
        route_id=receipt.route_id,
        task_ids=receipt.task_ids,
        mutation_surfaces=[s for s in receipt.mutation_surfaces if s != "provider_spend"],
        evidence_refs=receipt.evidence_refs,
        issued_at=datetime.now(UTC),
    )
    path.write_text(without_spend.model_dump_json())
    completion = Mock(return_value='{"overall_confidence": 0.99}')
    with pytest.raises(PublicationAdmissionError) as held:
        ReviewPass(model="claude-opus-4-8", completion=completion).review_text("Clean draft.")
    assert held.value.result.reason_code == "connector_mutation_surface_mismatch"
    completion.assert_not_called()


def test_direct_community_submit_requires_admission(monkeypatch, tmp_path):
    from agents.publication_bus import community_submitter as module

    monkeypatch.delenv("HAPAX_PUBLICATION_TASK_ID", raising=False)
    request = Mock()
    request.post.return_value = Mock(status_code=202)
    monkeypatch.setattr(module, "requests", request)
    outcome = module.ZenodoCommunitySubmitter(zenodo_token="synthetic").submit_to_community(
        deposit_id="123", community="single-operator-systems"
    )
    assert not outcome.ok
    assert "route/resource hold" in outcome.detail
    request.post.assert_not_called()


def test_direct_graph_mint_requires_admission(monkeypatch, tmp_path):
    from agents.publication_bus import graph_publisher as module

    monkeypatch.delenv("HAPAX_PUBLICATION_TASK_ID", raising=False)
    emit = Mock(return_value=(123, "10.123/test", "10.123/test"))
    monkeypatch.setattr(module, "_create_first_version", emit)
    monkeypatch.setattr(module, "_build_deposit_metadata", lambda **_: {})
    with pytest.raises(module.GraphPublisherError, match="route/resource hold"):
        module.mint_or_version(
            zenodo_token="synthetic",
            graph_dir=tmp_path,
            snapshot_path=tmp_path / "snapshot",
            fingerprint="test",
            metadata={},
        )
    emit.assert_not_called()


def test_author_metadata_cannot_supply_route_authority(monkeypatch, tmp_path):
    monkeypatch.delenv("HAPAX_PUBLICATION_TASK_ID", raising=False)
    completion = Mock(return_value='{"overall_confidence":0.99}')
    with pytest.raises(PublicationAdmissionError):
        ReviewPass(completion=completion).review_text(
            "Clean.",
            metadata={
                "task_id": "cc-task-synthetic-publication",
                "route_id": "api.headless.api_frontier",
                "allowed": True,
            },
        )
    completion.assert_not_called()
