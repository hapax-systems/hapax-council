"""Tests for the archive replay sidecar index contract."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest
from prometheus_client import CollectorRegistry
from pydantic import ValidationError

from shared.archive_replay_sidecar_index import (
    ARCHIVE_REPLAY_SIDECAR_INDEX_FIXTURES,
    FAIL_CLOSED_POLICY,
    PRODUCER,
    REQUIRED_ARTIFACT_KINDS,
    REQUIRED_INDEX_STATES,
    REQUIRED_METRIC_STATES,
    TASK_ANCHOR,
    ArchiveReplaySidecarIndex,
    ArchiveReplaySidecarIndexEntry,
    ArchiveReplaySidecarIndexError,
    ArchiveReplaySidecarIndexMetrics,
    build_archive_replay_sidecar_index,
    load_archive_replay_sidecar_index_fixtures,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "schemas" / "archive-replay-sidecar-index.schema.json"


def _payload() -> dict[str, Any]:
    return cast(
        "dict[str, Any]",
        json.loads(ARCHIVE_REPLAY_SIDECAR_INDEX_FIXTURES.read_text(encoding="utf-8")),
    )


def _schema() -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(SCHEMA.read_text(encoding="utf-8")))


def _index() -> ArchiveReplaySidecarIndex:
    return load_archive_replay_sidecar_index_fixtures()


def _public_entry_payload() -> dict[str, Any]:
    return copy.deepcopy(_payload()["entries"][0])


def test_schema_validates_fixture_file_and_pins_fail_closed_policy() -> None:
    schema = _schema()
    payload = _payload()

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(payload)
    assert set(schema["x-required_artifact_kinds"]) == REQUIRED_ARTIFACT_KINDS
    assert set(schema["x-required_index_states"]) == REQUIRED_INDEX_STATES
    assert set(schema["x-required_metric_states"]) == REQUIRED_METRIC_STATES
    assert schema["x-fail_closed_policy"] == FAIL_CLOSED_POLICY


def test_loader_covers_artifact_kinds_states_and_metric_states() -> None:
    index = _index()

    assert index.producer == PRODUCER
    assert {entry.artifact_kind for entry in index.entries} == REQUIRED_ARTIFACT_KINDS
    assert {entry.state for entry in index.entries} == REQUIRED_INDEX_STATES
    assert set(index.metric_counts()) == REQUIRED_METRIC_STATES
    assert len(index.public_safe_entries()) == 1


def test_public_safe_entry_has_all_citable_replay_refs() -> None:
    entry = _index().require_entry("archive-replay-index:public-safe-run:segment00042")

    assert entry.public_safe_replay_claim_allowed is True
    assert entry.state == "public"
    assert entry.fail_closed_blockers() == ()
    assert entry.metric_states() == ("available", "public_safe")
    assert entry.run_refs
    assert entry.public_event_refs
    assert entry.archive_refs
    assert entry.sidecar_refs
    assert entry.frame_refs
    assert entry.chapter_refs
    assert entry.caption_refs
    assert entry.temporal_span_refs
    assert entry.provenance.token == "archive-replay-token:segment00042"
    assert entry.provenance.evidence_refs
    assert entry.rights_class == "operator_original"
    assert entry.privacy_class == "public_safe"


def test_non_public_entries_remain_addressable_but_fail_closed() -> None:
    index = _index()
    refusal = index.require_entry("archive-replay-index:refusal-artifact:segment00043")
    correction = index.require_entry("archive-replay-index:correction-artifact:segment00044")
    rights = index.require_entry("archive-replay-index:rights-blocked-run:segment00045")

    assert refusal.state == "dry-run"
    assert refusal.metric_states() == ("stale", "blocked")
    assert refusal.fail_closed_blockers() == ("dry_run_only", "archive_refs_stale")

    assert correction.state == "private"
    assert correction.public_safe_replay_claim_allowed is False
    assert correction.fail_closed_blockers() == (
        "private_state",
        "archive_refs_private",
        "privacy_blocked",
    )

    assert rights.state == "blocked"
    assert rights.public_safe_replay_claim_allowed is False
    assert rights.fail_closed_blockers() == (
        "blocked_state",
        "archive_refs_rights_held",
        "rights_blocked",
    )


@pytest.mark.parametrize(
    ("mutations", "reason"),
    [
        ({"archive_refs": []}, "archive_refs_missing"),
        ({"archive_ref_state": "stale"}, "archive_refs_stale"),
        ({"archive_ref_state": "private"}, "archive_refs_private"),
        ({"archive_ref_state": "rights_held"}, "archive_refs_rights_held"),
        ({"archive_verified": False}, "archive_refs_unverified"),
        ({"rights_class": "third_party_uncleared"}, "rights_blocked"),
        ({"provenance": {"token": None, "evidence_refs": []}}, "provenance_unverified"),
    ],
)
def test_public_claim_fails_closed_when_required_archive_evidence_drifts(
    mutations: dict[str, Any],
    reason: str,
) -> None:
    payload = _public_entry_payload()
    for key, value in mutations.items():
        if key == "provenance":
            payload["provenance"].update(value)
        else:
            payload[key] = value

    with pytest.raises(ValidationError, match=reason):
        ArchiveReplaySidecarIndexEntry.model_validate(payload)


def test_declared_blocker_does_not_unlock_public_safe_claim() -> None:
    payload = _public_entry_payload()
    payload["archive_ref_state"] = "stale"
    payload["blocker_reasons"] = ["archive_refs_stale"]

    with pytest.raises(ValidationError, match="public-safe replay cannot pass"):
        ArchiveReplaySidecarIndexEntry.model_validate(payload)


def test_index_loader_rejects_missing_required_artifact_kind(tmp_path: Path) -> None:
    payload = _payload()
    payload["entries"] = [
        entry for entry in payload["entries"] if entry["artifact_kind"] != "refusal_artifact"
    ]
    path = tmp_path / "bad-index.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ArchiveReplaySidecarIndexError, match="refusal_artifact"):
        load_archive_replay_sidecar_index_fixtures(path)


def test_metrics_emit_available_blocked_stale_and_public_safe_objects() -> None:
    registry = CollectorRegistry()
    metrics = ArchiveReplaySidecarIndexMetrics(registry)

    metrics.record_index(_index())

    assert (
        registry.get_sample_value(
            "hapax_archive_replay_sidecar_index_objects_total",
            {
                "object_state": "available",
                "index_state": "public",
                "artifact_kind": "public_safe_run",
            },
        )
        == 1.0
    )
    assert (
        registry.get_sample_value(
            "hapax_archive_replay_sidecar_index_objects_total",
            {
                "object_state": "public_safe",
                "index_state": "public",
                "artifact_kind": "public_safe_run",
            },
        )
        == 1.0
    )
    assert (
        registry.get_sample_value(
            "hapax_archive_replay_sidecar_index_objects_total",
            {
                "object_state": "stale",
                "index_state": "dry-run",
                "artifact_kind": "refusal_artifact",
            },
        )
        == 1.0
    )
    assert (
        registry.get_sample_value(
            "hapax_archive_replay_sidecar_index_objects_total",
            {
                "object_state": "blocked",
                "index_state": "blocked",
                "artifact_kind": "rights_blocked_run",
            },
        )
        == 1.0
    )


def test_builder_and_run_lookup_preserve_index_contract() -> None:
    source = _index()
    rebuilt = build_archive_replay_sidecar_index(
        source.entries,
        index_id="rebuilt-archive-replay-sidecar-index",
        declared_at="2026-05-10T12:01:00Z",
        generated_from=(f"task:{TASK_ANCHOR}",),
    )

    matches = rebuilt.entries_for_run("ContentProgrammeRunEnvelope:run-public-safe-0042")

    assert rebuilt.schema_ref == "schemas/archive-replay-sidecar-index.schema.json"
    assert matches == (source.entries[0],)
