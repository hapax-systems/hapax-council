from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "downstream_contribution_ledger_v0.py"
DESIGN = (
    REPO_ROOT / "docs/research/evidence/2026-05-13-downstream-contribution-measurement-design.json"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("_downstream_contribution_ledger_v0", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_report_uses_design_schema_and_denies_claim_upgrade() -> None:
    module = _load_module()

    report = module.build_report(generated_at="2026-05-13T00:00:00Z")
    design = json.loads(DESIGN.read_text(encoding="utf-8"))

    assert report["measurement_record_schema"] == design["measurement_record_schema"]
    assert report["overall_decision"] == "ledger_v0_instrumented_no_claim_upgrade"
    assert report["summary"]["invalid_record_count"] == 0
    assert report["gate_predicates"]["future_ledger_run_receipt_consumed"] is True
    assert (
        report["gate_predicates"]["future_public_claim_gate_permits_downstream_language"] is False
    )
    assert report["gate_predicates"]["claim_upgrade_allowed_now"] is False
    assert module.claim_upgrade_allowed(report) is False


def test_fixture_run_contains_positive_negative_and_privacy_blocked_records() -> None:
    module = _load_module()

    report = module.build_report(generated_at="2026-05-13T00:00:00Z")

    assert report["summary"]["fixture_valence_counts"] == {
        "positive": 1,
        "negative": 1,
        "privacy_blocked": 1,
    }
    assert report["gate_predicates"]["fixture_run_contains_required_valences"] is True
    assert {record["negative_result_status"] for record in report["records"]} >= {
        "not_negative",
        "answer_unfaithful",
        "privacy_or_consent_blocked",
    }


def test_validator_rejects_missing_schema_required_evidence() -> None:
    module = _load_module()
    design = json.loads(DESIGN.read_text(encoding="utf-8"))
    valid = module.default_records()[0]

    cases = {
        "source_token_sha256": "invalid_sha256:source_token_sha256",
        "downstream_artifact_sha256": "invalid_sha256:downstream_artifact_sha256",
        "provenance_edges": "missing_attribution_edge:provenance_edges",
        "privacy_label": "missing_privacy_label",
        "counterfactual_method": "missing_counterfactual_method",
        "negative_result_status": "missing_negative_result_status",
    }
    for field, expected_error in cases.items():
        record = dict(valid)
        record.pop(field)
        normalized = module.normalize_record(record, design)
        if field == "privacy_label":
            normalized[field] = ""
        if field == "negative_result_status":
            normalized[field] = ""
        errors = module.validate_record(normalized, design)
        assert expected_error in errors, field


def test_read_only_ingest_records_metadata_without_private_content(tmp_path: Path) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    vault_root = tmp_path / "vault"
    evidence = repo_root / "docs" / "research" / "evidence"
    runbooks = repo_root / "docs" / "runbooks"
    closed = vault_root / "hapax-cc-tasks" / "closed"
    evidence.mkdir(parents=True)
    runbooks.mkdir(parents=True)
    closed.mkdir(parents=True)

    (evidence / "receipt.json").write_text('{"ok": true}\n', encoding="utf-8")
    (evidence / "receipt.md").write_text(
        "private phrase should not appear in output\n", encoding="utf-8"
    )
    (runbooks / "public-surface-scrutiny-gate-v2.md").write_text("gate\n", encoding="utf-8")
    (closed / "task.md").write_text(
        "---\ntask_id: task\nstatus: done\npr: 123\n---\nprivate task body\n",
        encoding="utf-8",
    )

    inventory = module.build_input_inventory(repo_root=repo_root, vault_root=vault_root)
    serialized = json.dumps(inventory, sort_keys=True)

    assert inventory["counts"]["source_receipts"] == 2
    assert inventory["counts"]["closed_cc_tasks"] == 1
    assert "private phrase" not in serialized
    assert "private task body" not in serialized
    assert '"artifact_id":"task"' not in serialized.replace(" ", "")
    assert "task.md" not in serialized
    assert inventory["closed_cc_tasks"]["status_counts"] == {"done": 1}
    assert inventory["closed_cc_tasks"]["tasks_with_pr"] == 1
    assert inventory["closed_cc_tasks"]["emitted_metadata"] == [
        "count",
        "status_counts",
        "tasks_with_pr",
        "aggregate_sha256",
    ]


def test_privacy_blocked_record_uses_redacted_paths_and_hashes() -> None:
    module = _load_module()

    report = module.build_report(generated_at="2026-05-13T00:00:00Z")
    privacy_record = {record["event_id"]: record for record in report["records"]}[
        "fixture-privacy-blocked-operator-decision-record"
    ]

    assert privacy_record["source_token_path"].startswith("redacted://")
    assert privacy_record["source_token_sha256"] == module.sha256_text(
        "redacted://operator-private-decision-record"
    )
    assert privacy_record["privacy_label"] == "privacy_or_consent_blocked"
    assert privacy_record["claim_upgrade_allowed"] is False


def test_write_report_writes_json_markdown_and_vault_mirror(tmp_path: Path) -> None:
    module = _load_module()
    report = module.build_report(generated_at="2026-05-13T00:00:00Z")
    json_path = tmp_path / "ledger.json"
    markdown_path = tmp_path / "ledger.md"
    vault_path = tmp_path / "vault.md"

    written = module.write_report(
        report,
        json_path=json_path,
        markdown_path=markdown_path,
        vault_markdown_path=vault_path,
    )

    assert written == (json_path, markdown_path, vault_path)
    parsed = json.loads(json_path.read_text(encoding="utf-8"))
    assert parsed["overall_decision"] == "ledger_v0_instrumented_no_claim_upgrade"
    assert "Downstream Contribution Ledger V0" in markdown_path.read_text(encoding="utf-8")
    assert "No Token Capital claim upgrade is allowed" in markdown_path.read_text(encoding="utf-8")
    assert vault_path.read_text(encoding="utf-8") == markdown_path.read_text(encoding="utf-8")
