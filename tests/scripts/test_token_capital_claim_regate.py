from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "token_capital_claim_regate.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("_token_capital_claim_regate", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_report_cites_dependency_prs_and_has_no_missing_evidence() -> None:
    module = _load_module()

    report = module.build_report(generated_at="2026-05-13T00:00:00Z")

    prs = {row["artifact_id"]: row["pr"] for row in report["evidence_artifacts"]}
    assert prs["documents-v2-full-backfill"] == 3211
    assert prs["answer-faithfulness"] == 3212
    assert prs["corpus-utilization-denominator"] == 3213
    assert prs["public-surface-source-of-truth"] == 3214
    assert report["missing_evidence_artifacts"] == []
    assert report["gate_predicates"]["all_dependency_receipts_present"] is True


def test_claim_upgrade_denied_for_unsupported_claim_classes() -> None:
    module = _load_module()
    report = module.build_report(generated_at="2026-05-13T00:00:00Z")

    for claim_id in (
        "token_capital_existence_proof",
        "answer_faithfulness",
        "downstream_contribution",
        "compounding_value",
    ):
        assert module.claim_upgrade_allowed(report, claim_id) is False

    assert report["gate_predicates"]["claim_upgrade_allowed"] is False
    assert report["gate_predicates"]["token_capital_exists_proof_allowed"] is False
    assert report["gate_predicates"]["answer_faithfulness_upgrade_allowed"] is False
    assert report["gate_predicates"]["downstream_contribution_upgrade_allowed"] is False
    assert report["gate_predicates"]["compounding_value_upgrade_allowed"] is False
    assert module.claim_upgrade_allowed(report, "unknown_claim") is False


def test_bounded_repair_claims_are_allowed_but_not_global_upgrade() -> None:
    module = _load_module()
    report = module.build_report(generated_at="2026-05-13T00:00:00Z")

    assert module.claim_upgrade_allowed(report, "nomic_embedding_availability") is True
    assert module.claim_upgrade_allowed(report, "documents_v2_repair") is True
    assert module.claim_upgrade_allowed(report, "retrieval_improvement") is True
    assert report["overall_decision"] == "claim_upgrade_denied"


def test_default_generated_at_is_deterministic() -> None:
    module = _load_module()

    first = module.build_report()
    second = module.build_report()

    assert first["generated_at"] == "2026-05-13T00:00:00Z"
    assert second["generated_at"] == first["generated_at"]


def test_render_markdown_exposes_forbidden_patterns_and_predicates() -> None:
    module = _load_module()
    report = module.build_report(generated_at="2026-05-13T00:00:00Z")

    markdown = module.render_markdown(report)

    assert "claim_upgrade_denied" in markdown
    assert "token_capital_existence_proof" in markdown
    assert "answer_faithfulness_upgrade_allowed" in markdown
    assert "downstream_contribution_upgrade_allowed" in markdown
    assert "existence[-\\s]+proof" in markdown


def test_write_report_writes_json_markdown_and_vault_mirror(tmp_path: Path) -> None:
    module = _load_module()
    report = module.build_report(generated_at="2026-05-13T00:00:00Z")
    json_path = tmp_path / "receipt.json"
    markdown_path = tmp_path / "receipt.md"
    vault_path = tmp_path / "vault.md"

    written = module.write_report(
        report,
        json_path=json_path,
        markdown_path=markdown_path,
        vault_markdown_path=vault_path,
    )

    assert written == (json_path, markdown_path, vault_path)
    parsed_json = json.loads(json_path.read_text())
    assert parsed_json["overall_decision"] == "claim_upgrade_denied"
    assert "Token Capital Claim Re-Gate V2" in markdown_path.read_text()
    assert vault_path.read_text() == markdown_path.read_text()
