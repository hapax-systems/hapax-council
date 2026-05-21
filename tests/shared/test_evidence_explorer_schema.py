"""Tests for the private Evidence Explorer record schema."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from shared.evidence_explorer_schema import (
    EvidenceExplorerPrivacyClass,
    EvidenceExplorerRecord,
    EvidenceExplorerRecordKind,
    FreshnessState,
)

REQUIRED_FIELDS = {
    "source_path",
    "record_kind",
    "timestamp",
    "authority_case",
    "parent_spec",
    "task_id",
    "request_id",
    "route",
    "platform",
    "privacy_class",
    "freshness_state",
    "hashes",
    "links",
    "facets",
    "redacted_summary",
}


def _sample_record(record_kind: EvidenceExplorerRecordKind) -> dict[str, object]:
    return {
        "source_path": "/home/hapax/.cache/hapax/orchestration/sample-dispatch.yaml",
        "record_kind": record_kind.value,
        "timestamp": "2026-05-21T16:32:31Z",
        "authority_case": "CASE-EVIDENCE-ADMISSION-20260521",
        "parent_spec": (
            "/home/hapax/Documents/Personal/20-projects/hapax-requests/active/"
            "REQ-20260521160220-hapax-evidence-explorer.md"
        ),
        "task_id": "20260521160220-hapax-evidence-phase0-define-schema",
        "request_id": "REQ-20260521160220-hapax-evidence-explorer",
        "route": "cx-evidence-explorer",
        "platform": "codex",
        "privacy_class": EvidenceExplorerPrivacyClass.PRIVATE.value,
        "freshness_state": FreshnessState.FRESH.value,
        "hashes": {
            "source_sha256": "sha256:"
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        },
        "links": [
            {
                "rel": "source",
                "target": "/home/hapax/.cache/hapax/orchestration/sample-dispatch.yaml",
                "label": "sample dispatch trace",
            }
        ],
        "facets": {
            "authority_case": "CASE-EVIDENCE-ADMISSION-20260521",
            "task_id": "20260521160220-hapax-evidence-phase0-define-schema",
            "record_kind": record_kind.value,
            "tags": ("evidence-explorer", "phase0"),
        },
        "redacted_summary": "Redacted private evidence artifact summary for explorer indexing.",
    }


@pytest.mark.parametrize("record_kind", list(EvidenceExplorerRecordKind))
def test_accepts_well_formed_records_for_each_record_kind(
    record_kind: EvidenceExplorerRecordKind,
) -> None:
    record = EvidenceExplorerRecord.model_validate(_sample_record(record_kind))

    assert record.record_kind is record_kind
    assert record.privacy_class is EvidenceExplorerPrivacyClass.PRIVATE
    assert record.freshness_state is FreshnessState.FRESH


@pytest.mark.parametrize(
    "missing_field",
    ("source_path", "record_kind", "redacted_summary"),
)
def test_rejects_records_missing_required_fields(missing_field: str) -> None:
    payload = _sample_record(EvidenceExplorerRecordKind.DISPATCH_TRACE)
    del payload[missing_field]

    with pytest.raises(ValidationError):
        EvidenceExplorerRecord.model_validate(payload)


def test_schema_declares_all_required_top_level_fields() -> None:
    schema = EvidenceExplorerRecord.model_json_schema()

    assert set(schema["required"]) == REQUIRED_FIELDS
    assert set(schema["properties"]) >= REQUIRED_FIELDS


def test_record_kind_and_privacy_class_are_machine_readable_enums() -> None:
    schema = EvidenceExplorerRecord.model_json_schema()

    assert set(schema["$defs"]["EvidenceExplorerRecordKind"]["enum"]) == {
        "dispatch_trace",
        "grounding_receipt",
        "eval_receipt",
        "evidence_card",
        "qdrant_metadata_summary",
        "cc_task_close_dossier",
    }
    assert set(schema["$defs"]["EvidenceExplorerPrivacyClass"]["enum"]) >= {
        "private",
        "redacted_public",
    }


def test_every_required_field_has_schema_documentation() -> None:
    properties = EvidenceExplorerRecord.model_json_schema()["properties"]

    for field_name in REQUIRED_FIELDS:
        assert properties[field_name]["description"]


def test_schema_has_no_authority_release_or_publication_status_fields() -> None:
    properties = set(EvidenceExplorerRecord.model_json_schema()["properties"])

    assert properties.isdisjoint(
        {
            "authority_status",
            "authorization_status",
            "authorized",
            "release_status",
            "released",
            "publication_status",
            "public_safe",
        }
    )

    payload = deepcopy(_sample_record(EvidenceExplorerRecordKind.DISPATCH_TRACE))
    payload["release_status"] = "released"
    with pytest.raises(ValidationError):
        EvidenceExplorerRecord.model_validate(payload)


def test_rejects_naive_timestamps() -> None:
    payload = _sample_record(EvidenceExplorerRecordKind.DISPATCH_TRACE)
    payload["timestamp"] = "2026-05-21T16:32:31"

    with pytest.raises(ValidationError, match="timezone-aware"):
        EvidenceExplorerRecord.model_validate(payload)


def test_rejects_blank_link_targets_after_trimming() -> None:
    payload = _sample_record(EvidenceExplorerRecordKind.DISPATCH_TRACE)
    payload["links"] = [{"rel": "source", "target": "   "}]

    with pytest.raises(ValidationError, match="field must not be blank"):
        EvidenceExplorerRecord.model_validate(payload)
