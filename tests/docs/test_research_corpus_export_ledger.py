"""Regression pins for the research-corpus export ledger."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER = REPO_ROOT / "config" / "research-corpus-export-ledger.yaml"
SCHEMA = REPO_ROOT / "schemas" / "research-corpus-export-ledger.schema.json"
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "verify-research-corpus-export-ledger.py"
MSR_ARCHITECTURE = (
    REPO_ROOT / "docs" / "applications" / "2026-msr-dataset-paper" / "architecture.md"
)
HF_ARCHITECTURE = REPO_ROOT / "docs" / "applications" / "hf-paper-dataset-cards" / "architecture.md"

REQUIRED_CORPORA = {
    "cc_tasks",
    "refusal_briefs",
    "relay_yaml",
    "research_drops",
    "publication_bus_events",
    "public_event_records",
    "velocity_evidence",
    "archive_sidecars",
    "identifier_graph",
}

BASELINE_FILTERS = {
    "legal_name_to_operator_referent",
    "email_address_redaction",
    "secret_value_block",
    "employer_material_path_block",
    "non_operator_person_state_block",
    "private_vault_body_drop",
}

EXPORT_STATUSES = {"public", "anonymized", "hash_only", "aggregate_only", "private", "forbidden"}


def _ledger() -> dict[str, Any]:
    data = yaml.safe_load(LEDGER.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def _verifier() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "verify_research_corpus_export_ledger", VERIFY_SCRIPT
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_schema_defines_statuses_consumers_and_fail_closed_policy() -> None:
    schema = _schema()
    defs = schema["$defs"]

    assert set(defs["export_status"]["enum"]) == EXPORT_STATUSES
    assert set(defs["machine_consumer"]["enum"]) >= {
        "dataset_cards",
        "grant_packets",
        "replay_kits",
        "artifact_bundles",
        "msr_dataset_paper",
        "hf_dataset_card",
        "openai_safety_fellowship_packet",
    }

    global_policy = defs["global_policy"]["properties"]
    assert global_policy["single_operator_only"]["const"] is True
    assert global_policy["no_recurring_operator_review"]["const"] is True
    assert global_policy["fail_closed_on_uncertain_status"]["const"] is True
    assert global_policy["public_release_requires_ledger_record"]["const"] is True

    release_gate = defs["release_gate"]["properties"]
    assert release_gate["recurring_operator_review_required"]["const"] is False
    assert release_gate["blocks_on_uncertain_fields"]["const"] is True


def test_ledger_covers_required_corpora_consumers_and_statuses() -> None:
    ledger = _ledger()
    corpora = {record["corpus_id"]: record for record in ledger["corpora"]}
    status_defs = {record["status"] for record in ledger["export_status_definitions"]}

    assert ledger["schema_version"] == 1
    assert status_defs == EXPORT_STATUSES
    assert set(corpora) >= REQUIRED_CORPORA
    assert set(ledger["global_policy"]["machine_consumers"]) >= {
        "dataset_cards",
        "grant_packets",
        "replay_kits",
        "artifact_bundles",
    }

    seen_statuses = {
        field["status"] for record in corpora.values() for field in record["field_statuses"]
    }
    assert seen_statuses >= EXPORT_STATUSES


def test_each_corpus_declares_rights_field_statuses_tests_and_review_boundary() -> None:
    ledger = _ledger()
    filter_ids = {record["filter_id"] for record in ledger["redaction_filter_catalog"]}
    assert filter_ids >= BASELINE_FILTERS

    for record in ledger["corpora"]:
        corpus_id = record["corpus_id"]
        assert len(record["field_statuses"]) >= 3, corpus_id
        assert set(record["automated_test_refs"]) >= BASELINE_FILTERS, corpus_id
        assert set(record["automated_test_refs"]) <= filter_ids, corpus_id

        rights = record["rights_posture"]
        assert rights["license_basis"], corpus_id
        assert rights["attribution_required"] is True, corpus_id
        assert rights["public_release_allowed"] is True, corpus_id

        release_gate = record["release_gate"]
        assert release_gate["recurring_operator_review_required"] is False, corpus_id
        assert release_gate["bootstrap_attestation_required"] is True, corpus_id
        assert release_gate["blocks_on_uncertain_fields"] is True, corpus_id


def test_required_filters_and_forbidden_exports_pin_acceptance_criteria() -> None:
    ledger = _ledger()
    filter_ids = {record["filter_id"] for record in ledger["redaction_filter_catalog"]}
    forbidden = set(ledger["global_policy"]["forbidden_exports"])

    assert filter_ids >= BASELINE_FILTERS | {
        "third_party_media_rights_block",
        "local_path_root_redaction",
        "public_url_token_strip",
        "private_identifier_hash",
    }
    assert forbidden >= {
        "credential_values",
        "employer_material",
        "third_party_pii",
        "non_operator_person_identifiable_state",
        "private_vault_body",
        "consent_required_media_without_contract",
        "third_party_uncleared_media",
        "platform_private_token_or_cookie",
    }


def test_verifier_accepts_repository_ledger() -> None:
    verifier = _verifier()
    assert verifier.validate_ledger(_ledger()) == []


def test_application_docs_route_downstream_consumers_through_ledger() -> None:
    msr = MSR_ARCHITECTURE.read_text(encoding="utf-8")
    hf = HF_ARCHITECTURE.read_text(encoding="utf-8")

    for body in (msr, hf):
        assert "config/research-corpus-export-ledger.yaml" in body
        assert "schemas/research-corpus-export-ledger.schema.json" in body
        assert "scripts/verify-research-corpus-export-ledger.py" in body

    for consumer in ("dataset cards", "grant packets", "replay kits", "artifact bundles"):
        assert consumer in msr

    assert "hf_dataset_card" in hf
