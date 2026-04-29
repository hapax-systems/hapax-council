#!/usr/bin/env python3
"""Verify the research-corpus export ledger.

The ledger is intentionally YAML so dataset-card, grant-packet, replay-kit, and
artifact-bundle composers can consume it without a database. This verifier pins
the high-risk invariants that matter before any public corpus export:

* the required corpus classes are present;
* each corpus declares per-field export statuses and rights posture;
* baseline redaction/filter tests are referenced;
* recurring operator review is forbidden; and
* uncertain fields fail closed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = REPO_ROOT / "config" / "research-corpus-export-ledger.yaml"

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

REQUIRED_CONSUMERS = {
    "dataset_cards",
    "grant_packets",
    "replay_kits",
    "artifact_bundles",
}

ALLOWED_STATUSES = {
    "public",
    "anonymized",
    "hash_only",
    "aggregate_only",
    "private",
    "forbidden",
}

BASELINE_FILTERS = {
    "legal_name_to_operator_referent",
    "email_address_redaction",
    "secret_value_block",
    "employer_material_path_block",
    "non_operator_person_state_block",
    "private_vault_body_drop",
}

REQUIRED_FORBIDDEN_EXPORTS = {
    "credential_values",
    "employer_material",
    "non_operator_person_identifiable_state",
    "private_vault_body",
    "third_party_uncleared_media",
    "platform_private_token_or_cookie",
}


def load_ledger(path: Path = DEFAULT_LEDGER) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level YAML must be a mapping")
    return data


def _as_mapping(value: Any, label: str, errors: list[str]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    errors.append(f"{label}: expected mapping")
    return {}


def _as_list(value: Any, label: str, errors: list[str]) -> list[Any]:
    if isinstance(value, list):
        return value
    errors.append(f"{label}: expected list")
    return []


def _require_subset(
    actual: set[str],
    required: set[str],
    label: str,
    errors: list[str],
) -> None:
    missing = sorted(required - actual)
    if missing:
        errors.append(f"{label}: missing {missing}")


def validate_ledger(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    if data.get("schema_version") != 1:
        errors.append("schema_version must be 1")

    policy = _as_mapping(data.get("global_policy"), "global_policy", errors)
    if policy.get("single_operator_only") is not True:
        errors.append("global_policy.single_operator_only must be true")
    if policy.get("no_recurring_operator_review") is not True:
        errors.append("global_policy.no_recurring_operator_review must be true")
    if policy.get("operator_review_boundary") != "bootstrap_legal_attestation_only":
        errors.append("operator_review_boundary must be bootstrap_legal_attestation_only")
    if policy.get("fail_closed_on_uncertain_status") is not True:
        errors.append("global_policy.fail_closed_on_uncertain_status must be true")
    if policy.get("default_export_status") != "private":
        errors.append("global_policy.default_export_status must be private")

    consumers = set(_as_list(policy.get("machine_consumers"), "machine_consumers", errors))
    _require_subset(consumers, REQUIRED_CONSUMERS, "machine_consumers", errors)

    forbidden_exports = set(_as_list(policy.get("forbidden_exports"), "forbidden_exports", errors))
    _require_subset(
        forbidden_exports,
        REQUIRED_FORBIDDEN_EXPORTS,
        "forbidden_exports",
        errors,
    )

    status_defs = _as_list(data.get("export_status_definitions"), "status definitions", errors)
    defined_statuses = {
        entry.get("status")
        for entry in status_defs
        if isinstance(entry, dict) and isinstance(entry.get("status"), str)
    }
    if defined_statuses != ALLOWED_STATUSES:
        errors.append(f"export_status_definitions must be exactly {sorted(ALLOWED_STATUSES)}")

    filters = _as_list(data.get("redaction_filter_catalog"), "redaction filters", errors)
    filter_ids = {
        entry.get("filter_id")
        for entry in filters
        if isinstance(entry, dict) and isinstance(entry.get("filter_id"), str)
    }
    _require_subset(filter_ids, BASELINE_FILTERS, "redaction_filter_catalog", errors)

    corpora = _as_list(data.get("corpora"), "corpora", errors)
    records: dict[str, dict[str, Any]] = {}
    for index, raw_record in enumerate(corpora):
        record = _as_mapping(raw_record, f"corpora[{index}]", errors)
        corpus_id = record.get("corpus_id")
        if isinstance(corpus_id, str):
            records[corpus_id] = record
        else:
            errors.append(f"corpora[{index}].corpus_id must be a string")

    _require_subset(set(records), REQUIRED_CORPORA, "corpora", errors)

    seen_statuses: set[str] = set()
    seen_consumers: set[str] = set()
    for corpus_id, record in records.items():
        default_status = record.get("default_export_status")
        if default_status not in ALLOWED_STATUSES:
            errors.append(f"{corpus_id}: invalid default_export_status {default_status!r}")

        field_statuses = _as_list(
            record.get("field_statuses"),
            f"{corpus_id}.field_statuses",
            errors,
        )
        if len(field_statuses) < 3:
            errors.append(f"{corpus_id}: must declare at least three field statuses")
        for field_record in field_statuses:
            if not isinstance(field_record, dict):
                errors.append(f"{corpus_id}: field_statuses entry is not a mapping")
                continue
            status = field_record.get("status")
            if status not in ALLOWED_STATUSES:
                errors.append(f"{corpus_id}: invalid field status {status!r}")
            else:
                seen_statuses.add(status)

        rights = _as_mapping(
            record.get("rights_posture"),
            f"{corpus_id}.rights_posture",
            errors,
        )
        for key in (
            "rights_class",
            "license_basis",
            "attribution_required",
            "monetization_allowed",
            "public_release_allowed",
        ):
            if key not in rights:
                errors.append(f"{corpus_id}.rights_posture missing {key}")
        if rights.get("attribution_required") is not True:
            errors.append(f"{corpus_id}: attribution_required must be true")

        test_refs = set(_as_list(record.get("automated_test_refs"), f"{corpus_id}.tests", errors))
        _require_subset(test_refs, BASELINE_FILTERS, f"{corpus_id}.automated_test_refs", errors)
        unknown_tests = sorted(test_refs - filter_ids)
        if unknown_tests:
            errors.append(f"{corpus_id}: automated_test_refs not in catalog: {unknown_tests}")

        release_gate = _as_mapping(
            record.get("release_gate"),
            f"{corpus_id}.release_gate",
            errors,
        )
        if release_gate.get("recurring_operator_review_required") is not False:
            errors.append(f"{corpus_id}: recurring operator review must be false")
        if release_gate.get("blocks_on_uncertain_fields") is not True:
            errors.append(f"{corpus_id}: uncertain fields must block release")

        record_consumers = set(
            _as_list(record.get("consumer_modes"), f"{corpus_id}.consumer_modes", errors)
        )
        seen_consumers.update(str(consumer) for consumer in record_consumers)

    _require_subset(seen_statuses, ALLOWED_STATUSES, "field_status coverage", errors)
    _require_subset(seen_consumers, REQUIRED_CONSUMERS, "corpus consumer coverage", errors)

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify research corpus export ledger")
    parser.add_argument(
        "--ledger",
        type=Path,
        default=DEFAULT_LEDGER,
        help="Path to research-corpus export ledger YAML",
    )
    args = parser.parse_args()

    try:
        ledger = load_ledger(args.ledger)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    errors = validate_ledger(ledger)
    if errors:
        print(f"FAIL: {len(errors)} research corpus ledger issue(s):", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"OK: research corpus export ledger validated: {args.ledger}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
