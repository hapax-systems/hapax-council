from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "downstream_contribution_measurement_design.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("_downstream_contribution_design", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_design_cites_required_evidence_and_methodology() -> None:
    module = _load_module()

    report = module.build_design(generated_at="2026-05-13T00:00:00Z")

    evidence = {row["artifact_id"]: row for row in report["evidence_artifacts"]}
    assert evidence["answer-faithfulness-ablation"]["pr"] == 3212
    assert evidence["corpus-utilization-denominator"]["pr"] == 3213
    assert evidence["claim-regate-v2"]["pr"] == 3215
    assert evidence["public-surface-scrutiny-gate-v2"]["pr"] == 3216
    assert report["missing_evidence_artifacts"] == []

    references = {row["reference_id"] for row in report["methodology_references"]}
    assert {
        "w3c-prov-dm",
        "rubin-1974-potential-outcomes",
        "pearl-2009-causal-inference-overview",
        "mackinlay-1997-event-studies",
        "koh-liang-2017-influence-functions",
    }.issubset(references)


def test_metric_layers_keep_retrieval_answer_and_downstream_separate() -> None:
    module = _load_module()

    report = module.build_design(generated_at="2026-05-13T00:00:00Z")

    layers = {layer["layer_id"]: layer for layer in report["metric_layers"]}
    assert set(layers) == {"retrieval_substrate", "answer_support", "downstream_contribution"}
    assert layers["retrieval_substrate"]["claim_status"] == "substrate_only_not_value"
    assert layers["answer_support"]["claim_status"] == "answer_quality_not_downstream_value"
    assert layers["downstream_contribution"]["claim_status"] == "not_measured_until_ledger_run"

    excluded = set(report["excluded_signals"])
    assert "raw retrieval hit" in excluded
    assert "answer-context exposure without a later artifact" in excluded
    assert "unpersisted chat output" in excluded


def test_event_classes_define_artifacts_windows_counterfactuals_and_negative_results() -> None:
    module = _load_module()

    report = module.build_design(generated_at="2026-05-13T00:00:00Z")

    assert len(report["contribution_event_classes"]) >= 5
    for event_class in report["contribution_event_classes"]:
        assert event_class["event_class_id"]
        assert event_class["eligible_artifacts"]
        assert event_class["minimum_evidence"]
        assert "counterfactual" in event_class
        assert event_class["negative_results"]

    window_ids = {window["window_id"] for window in report["attribution_windows"]}
    assert {"same_task_or_request", "default_short_window", "extended_bridge_window"} <= window_ids

    negative_statuses = {row["status"] for row in report["negative_result_statuses"]}
    assert {
        "no_downstream_artifact",
        "no_attribution_edge",
        "counterfactual_no_effect",
        "privacy_or_consent_blocked",
        "answer_unfaithful",
    } <= negative_statuses


def test_claim_upgrade_fails_closed_until_future_ledger_and_public_gate() -> None:
    module = _load_module()

    report = module.build_design(generated_at="2026-05-13T00:00:00Z")

    assert module.claim_upgrade_allowed(report) is False
    assert report["gate_predicates"]["claim_upgrade_allowed_now"] is False
    assert report["gate_predicates"]["future_ledger_run_receipt_consumed"] is False
    assert (
        report["gate_predicates"]["future_public_claim_gate_permits_downstream_language"] is False
    )
    assert report["current_claim_ceiling"]["status"] == "downstream_contribution_not_measured"

    malformed_report = {"gate_predicates": {"future_ledger_run_receipt_consumed": True}}
    assert module.claim_upgrade_allowed(malformed_report) is False


def test_followup_task_is_filed_only_because_event_stream_is_identified() -> None:
    module = _load_module()

    report = module.build_design(generated_at="2026-05-13T00:00:00Z")

    assert report["instrumentable_event_stream"]["status"] == "identified"
    followup = report["first_followup_task"]
    assert followup["task_id"] == "downstream-contribution-ledger-v0-instrumentation"
    assert "downstream-contribution-measurement-design" in followup["depends_on"]
    assert "public-surface-scrutiny-gate-v2" in followup["depends_on"]
    assert any("Token Capital claim upgrade" in item for item in followup["acceptance"])


def test_write_design_writes_json_markdown_vault_and_followup_task(tmp_path: Path) -> None:
    module = _load_module()
    report = module.build_design(generated_at="2026-05-13T00:00:00Z")
    json_path = tmp_path / "design.json"
    markdown_path = tmp_path / "design.md"
    vault_path = tmp_path / "vault.md"
    followup_path = tmp_path / "followup.md"

    written = module.write_design(
        report,
        json_path=json_path,
        markdown_path=markdown_path,
        vault_markdown_path=vault_path,
        followup_task_path=followup_path,
    )

    assert written == (json_path, markdown_path, vault_path, followup_path)
    parsed_json = json.loads(json_path.read_text())
    assert parsed_json["overall_decision"] == "measurement_design_only_no_claim_upgrade"
    assert "Downstream Contribution Measurement Design" in markdown_path.read_text()
    assert vault_path.read_text() == markdown_path.read_text()
    followup_text = followup_path.read_text()
    assert "task_id: downstream-contribution-ledger-v0-instrumentation" in followup_text
    assert "no Token Capital claim upgrade" in followup_text
