from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml

from shared.hkp_bundle_schema import HkpProjectionEvent, validate_bundle

HASH = "sha256:" + "a" * 64
TREE_HASH = "sha256:" + "b" * 64
PREV_HASH = "sha256:" + "c" * 64


def test_valid_hkp_bundle_passes(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)

    result = validate_bundle(bundle)

    assert result.ok is True
    assert result.findings == ()


def test_reserved_concept_id_and_provenance_fail(tmp_path: Path) -> None:
    bundle = write_bundle(
        tmp_path,
        concept_updates={
            "concept_id": "old/path",
            "provenance": {"producer": "wrong-field"},
        },
    )

    result = validate_bundle(bundle)

    assert result.ok is False
    assert {finding.code for finding in result.findings} >= {"reserved_field_misuse"}


def test_authority_source_refs_require_hash_and_times(tmp_path: Path) -> None:
    source_ref = valid_source_ref()
    source_ref.pop("content_hash")
    bundle = write_bundle(tmp_path, concept_updates={"source_refs": [source_ref]})

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "authority/evidence source ref requires" in _messages(result)


def test_authority_classed_source_refs_require_hash_even_with_non_authority_role(
    tmp_path: Path,
) -> None:
    source_ref = valid_source_ref()
    source_ref["data_role"] = "projection"
    source_ref["source_authority_class"] = "source_mutation"
    source_ref.pop("content_hash")
    bundle = write_bundle(tmp_path, concept_updates={"source_refs": [source_ref]})

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "authority/evidence source ref requires content_hash" in _messages(result)


def test_stale_authority_source_refs_fail_closed(tmp_path: Path) -> None:
    source_ref = valid_source_ref()
    source_ref["freshness_state"] = "stale"
    bundle = write_bundle(tmp_path, concept_updates={"source_refs": [source_ref]})

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "authority/evidence source ref cannot be stale" in _messages(result)


def test_source_ref_uri_path_leaks_fail(tmp_path: Path) -> None:
    source_ref = valid_source_ref()
    source_ref["uri"] = "file:///home/hapax/projects/hapax-council/task.md"
    bundle = write_bundle(tmp_path, concept_updates={"source_refs": [source_ref]})

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "source ref uri must not expose a local path" in _messages(result)


def test_source_ref_uri_parent_traversal_fails(tmp_path: Path) -> None:
    source_ref = valid_source_ref()
    source_ref["uri"] = "../../private/task.md"
    bundle = write_bundle(tmp_path, concept_updates={"source_refs": [source_ref]})

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "source ref uri must not expose a local path or .." in _messages(result)


def test_privacy_ambiguity_fails_closed(tmp_path: Path) -> None:
    posture = valid_posture()
    posture["privacy_class"] = "unknown"
    bundle = write_bundle(tmp_path, concept_updates={"posture": posture})

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "privacy_class cannot be unknown" in _messages(result)


def test_public_export_posture_fails_closed(tmp_path: Path) -> None:
    posture = valid_posture()
    posture["public_export_allowed"] = True
    posture["allowed_consumers"] = ["public_export"]
    bundle = write_bundle(tmp_path, concept_updates={"posture": posture})

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "validator-first HKP cannot allow public export" in _messages(result)


def test_forbidden_consumer_in_posture_fails_closed(tmp_path: Path) -> None:
    posture = valid_posture()
    posture["allowed_consumers"] = ["dispatcher"]
    bundle = write_bundle(tmp_path, concept_updates={"posture": posture})

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "validator-first posture cannot allow blocked consumers" in _messages(result)


def test_unknown_consumer_in_posture_allowed_list_fails(tmp_path: Path) -> None:
    posture = valid_posture()
    posture["allowed_consumers"] = ["external_llm", "unknown"]
    bundle = write_bundle(tmp_path, concept_updates={"posture": posture})

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "validator-first posture cannot allow unknown consumers" in _messages(result)


def test_authority_may_authorize_fails(tmp_path: Path) -> None:
    authority = dict(valid_concept("task")["authority"])
    authority["may_authorize"] = True
    bundle = write_bundle(tmp_path, concept_updates={"authority": authority})

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "HKP records may not authorize" in _messages(result)


def test_duplicate_concept_uid_fails(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    second = valid_concept("task", concept_path="duplicate")
    _write_markdown(bundle / "concepts" / "duplicate.md", second)

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "duplicate_concept_uid" in {finding.code for finding in result.findings}


def test_concept_path_leaks_fail(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path, concept_updates={"concept_path": "../../private"})

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "concept_path must be bundle-local" in _messages(result)


def test_invalid_edge_relation_fails(tmp_path: Path) -> None:
    edge = valid_edge()
    edge["rel"] = "magically_authorizes"
    bundle = write_bundle(tmp_path, edges=[edge])

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "rel is not in HKP relation vocabulary" in _messages(result)


def test_edge_target_path_leaks_fail(tmp_path: Path) -> None:
    edge = valid_edge()
    edge["to_uid"] = None
    edge["target_path"] = "/home/hapax/projects/hapax-council/task.md"
    bundle = write_bundle(tmp_path, edges=[edge])

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "target_path must be bundle-local and non-leaking" in _messages(result)


def test_edge_multiple_targets_fail(tmp_path: Path) -> None:
    edge = valid_edge()
    edge["target_path"] = "concepts/other.md"
    bundle = write_bundle(tmp_path, edges=[edge])

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "edge must name exactly one target form" in _messages(result)


def test_malformed_yaml_fails(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    (bundle / "_hkp" / "manifest.yaml").write_text("hkp_schema: [unterminated\n")

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "manifest_invalid" in {finding.code for finding in result.findings}


def test_required_path_type_mismatch_fails(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    (bundle / "concepts" / "task.md").unlink()
    (bundle / "concepts").rmdir()
    (bundle / "concepts").write_text("not a directory\n", encoding="utf-8")

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "required_path_wrong_type" in {finding.code for finding in result.findings}


def test_reserved_file_name_fails(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    (bundle / "concepts" / ".env").write_text("SECRET=value\n", encoding="utf-8")

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "reserved_file_name" in {finding.code for finding in result.findings}


def test_missing_type_and_schema_fail(tmp_path: Path) -> None:
    missing_type = valid_concept("task")
    missing_type.pop("type")
    bundle = write_bundle(tmp_path / "missing_type", concept=missing_type)

    missing_type_result = validate_bundle(bundle)

    assert missing_type_result.ok is False
    assert "type" in _messages(missing_type_result)

    missing_schema = valid_concept("task")
    missing_schema.pop("hkp_schema")
    bundle = write_bundle(tmp_path / "missing_schema", concept=missing_schema)

    missing_schema_result = validate_bundle(bundle)

    assert missing_schema_result.ok is False
    assert "hkp_schema" in _messages(missing_schema_result)


def test_unknown_concept_type_warns_in_research_and_fails_in_governed(
    tmp_path: Path,
) -> None:
    bundle = write_bundle(tmp_path, concept_updates={"type": "future-local-type"})

    research = validate_bundle(bundle, mode="research")
    governed = validate_bundle(bundle, mode="governed")

    assert research.ok is True
    assert [(finding.severity.value, finding.code) for finding in research.findings] == [
        ("warning", "unknown_concept_type")
    ]
    assert governed.ok is False
    assert [(finding.severity.value, finding.code) for finding in governed.findings] == [
        ("error", "unknown_concept_type")
    ]


def test_broken_links_warn_in_research_and_fail_in_governed(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path, body="Broken [link](missing.md).\n")

    research = validate_bundle(bundle, mode="research")
    governed = validate_bundle(bundle, mode="governed")

    assert research.ok is True
    assert [(finding.severity.value, finding.code) for finding in research.findings] == [
        ("warning", "broken_markdown_link")
    ]
    assert governed.ok is False
    assert [(finding.severity.value, finding.code) for finding in governed.findings] == [
        ("error", "broken_markdown_link")
    ]


def test_unknown_key_containment_under_extensions_is_allowed(tmp_path: Path) -> None:
    bundle = write_bundle(
        tmp_path,
        concept_updates={
            "extensions": {"future_owner": {"field": "value"}},
            "x_hkp": {"experimental": True},
        },
    )

    result = validate_bundle(bundle)

    assert result.ok is True
    assert result.findings == ()


def test_tombstone_rejects_bare_hash_commitment(tmp_path: Path) -> None:
    tombstone = valid_concept(
        "erased",
        concept_path="erased",
        extra={
            "type": "Tombstone",
            "title": "Tombstone",
            "description": "Removed concept.",
            "tombstone": {
                "commitment": HASH,
                "commitment_kind": "hmac_sha256",
                "erasure_ref": "receipt:1",
                "purge_receipt_refs": [],
            },
        },
    )
    bundle = write_bundle(tmp_path, concept=tombstone)

    result = validate_bundle(bundle)

    assert result.ok is False
    messages = _messages(result)
    assert "bare hashes are not allowed" in messages


def test_tombstone_requires_generic_title(tmp_path: Path) -> None:
    tombstone = valid_concept(
        "erased",
        concept_path="erased",
        extra={
            "type": "Tombstone",
            "title": "Original private title",
            "description": "Removed concept.",
            "tombstone": {
                "commitment": "hmac-sha256:" + "d" * 64,
                "commitment_kind": "hmac_sha256",
                "erasure_ref": "receipt:1",
                "purge_receipt_refs": [],
            },
        },
    )
    bundle = write_bundle(tmp_path, concept=tombstone)

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "Tombstone title must be generic" in _messages(result)


def test_unknown_top_level_keys_must_be_namespaced(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path, concept_updates={"authority_class": "authority"})

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "unknown_top_level_field" in {finding.code for finding in result.findings}


def test_manifest_rejects_local_path_leaks(tmp_path: Path) -> None:
    manifest = valid_manifest()
    manifest["source_root"] = "/home/hapax/projects/hapax-council"
    bundle = write_bundle(tmp_path, manifest=manifest)

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "source_root must be a logical source id" in _messages(result)


def test_manifest_rejects_parent_traversal_source_root(tmp_path: Path) -> None:
    manifest = valid_manifest()
    manifest["source_root"] = "../../private"
    bundle = write_bundle(tmp_path, manifest=manifest)

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "source_root must be a logical source id without local paths or .." in _messages(result)


def test_invalid_event_row_fails(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    _write_jsonl(bundle / "_hkp" / "events.jsonl", [{"schema_version": 1}])

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "event_invalid" in {finding.code for finding in result.findings}


def test_invalid_checksum_record_fails(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    checksums = valid_checksums()
    checksums["artifacts"]["concepts/task.md"]["hash"] = "sha256:not-hex"
    (bundle / "_hkp" / "checksums.json").write_text(
        json.dumps(checksums, indent=2),
        encoding="utf-8",
    )

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "checksums_invalid" in {finding.code for finding in result.findings}


def test_checksum_hash_mismatch_fails(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    checksums = valid_checksums(bundle)
    checksums["artifacts"]["index.md"]["hash"] = HASH
    (bundle / "_hkp" / "checksums.json").write_text(
        json.dumps(checksums, indent=2),
        encoding="utf-8",
    )

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "checksums_hash_mismatch" in {finding.code for finding in result.findings}


def test_checksum_non_full_content_scope_fails(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    checksums = valid_checksums(bundle)
    checksums["artifacts"]["index.md"]["hash_scope"] = "frontmatter"
    checksums["artifacts"]["index.md"]["hash"] = HASH
    (bundle / "_hkp" / "checksums.json").write_text(
        json.dumps(checksums, indent=2),
        encoding="utf-8",
    )

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "checksums_invalid" in {finding.code for finding in result.findings}


def test_checksum_required_artifact_missing_fails(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    checksums = valid_checksums(bundle)
    checksums["artifacts"].pop("index.md")
    (bundle / "_hkp" / "checksums.json").write_text(
        json.dumps(checksums, indent=2),
        encoding="utf-8",
    )

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "checksums_missing_artifact" in {finding.code for finding in result.findings}


def test_reference_files_require_checksum_entries(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    (bundle / "references" / "source.md").write_text("reference\n", encoding="utf-8")

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "checksums_missing_artifact" in {finding.code for finding in result.findings}


def test_checksum_artifact_key_path_leak_fails(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    checksums = valid_checksums()
    checksums["artifacts"]["/home/hapax/private.md"] = checksums["artifacts"].pop(
        "concepts/task.md"
    )
    (bundle / "_hkp" / "checksums.json").write_text(
        json.dumps(checksums, indent=2),
        encoding="utf-8",
    )

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "checksum artifact keys must be bundle-local" in _messages(result)


def test_invalid_snapshot_record_fails(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    (bundle / "_hkp" / "snapshot.json").write_text("{}\n", encoding="utf-8")

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "snapshot_invalid" in {finding.code for finding in result.findings}


def test_markdown_absolute_path_leaks_fail(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path, body="Leak [source](/home/hapax/projects).\n")

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "markdown link target must not expose a local path" in _messages(result)


def test_markdown_reference_definition_path_leaks_fail(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path, body="[secret]: /home/hapax/private.md\n")

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "markdown link target must not expose a local path" in _messages(result)


def test_markdown_parent_traversal_outside_bundle_fails(tmp_path: Path) -> None:
    (tmp_path / "outside.md").write_text("outside\n", encoding="utf-8")
    bundle = write_bundle(tmp_path, body="Leak [outside](../../outside.md).\n")

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "markdown link target escapes bundle" in _messages(result)


def test_markdown_reference_definition_broken_target_warns_or_fails(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path, body="[missing]: missing.md\n")

    research = validate_bundle(bundle, mode="research")
    governed = validate_bundle(bundle, mode="governed")

    assert research.ok is True
    assert [(finding.severity.value, finding.code) for finding in research.findings] == [
        ("warning", "broken_markdown_link")
    ]
    assert governed.ok is False
    assert [(finding.severity.value, finding.code) for finding in governed.findings] == [
        ("error", "broken_markdown_link")
    ]


def test_qdrant_resource_is_blocked_in_validator_first_slice(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path, concept_updates={"resource": "qdrant"})

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "validator-first HKP cannot reference qdrant resources" in _messages(result)


def test_manifest_rejects_qdrant_and_public_export_allowed_consumers(
    tmp_path: Path,
) -> None:
    manifest = valid_manifest()
    manifest["allowed_consumers"] = ["research_viewer", "qdrant_rag", "public_export"]
    bundle = write_bundle(tmp_path, manifest=manifest)

    result = validate_bundle(bundle)

    assert result.ok is False
    messages = _messages(result)
    assert "qdrant_rag" in messages
    assert "public_export" in messages


def test_manifest_rejects_unknown_allowed_consumers(tmp_path: Path) -> None:
    manifest = valid_manifest()
    manifest["allowed_consumers"] = ["research_viewer", "external_llm", "unknown"]
    bundle = write_bundle(tmp_path, manifest=manifest)

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "manifest allowed_consumers includes unknown consumers" in _messages(result)


def test_consumer_policy_must_fail_closed_for_unknown_consumers(tmp_path: Path) -> None:
    policy = valid_consumer_policy()
    policy["consumers"] = [row for row in policy["consumers"] if row["consumer"] != "unknown"]
    bundle = write_bundle(tmp_path, consumer_policy=policy)

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "consumer policy missing rows" in _messages(result)


def test_consumer_policy_denied_consumers_cannot_allow_fields_or_retrieval(
    tmp_path: Path,
) -> None:
    policy = valid_consumer_policy()
    for row in policy["consumers"]:
        if row["consumer"] == "qdrant_rag":
            row["default"] = "allow_read_only"
            row["allowed_fields"] = ["body"]
            row["embedding_allowed"] = True
            row["retrieval_allowed"] = True
    bundle = write_bundle(tmp_path, consumer_policy=policy)

    result = validate_bundle(bundle)

    assert result.ok is False
    messages = _messages(result)
    assert "qdrant_rag must default deny" in messages
    assert "qdrant_rag may not expose allowed_fields" in messages
    assert "qdrant_rag may not allow embedding/retrieval" in messages


def test_manifest_output_tree_hash_mismatch_fails(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    (bundle / "index.md").write_text("# Changed after manifest\n", encoding="utf-8")

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "manifest_output_tree_hash_mismatch" in {finding.code for finding in result.findings}


def test_manifest_input_ref_hash_mismatch_fails(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    manifest = valid_manifest()
    manifest["output_tree_hash"] = _tree_hash(bundle)
    manifest["input_ref_hash"] = "sha256:" + "d" * 64
    _write_yaml(bundle / "_hkp" / "manifest.yaml", manifest)

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "manifest_input_ref_hash_mismatch" in {finding.code for finding in result.findings}


def test_manifest_input_ref_hash_requires_hashed_source_refs(tmp_path: Path) -> None:
    concept = valid_concept("task")
    concept["source_refs"] = []
    bundle = write_bundle(tmp_path, concept=concept)

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "manifest_input_ref_hash_mismatch" in {finding.code for finding in result.findings}


def test_event_hash_chain_break_fails(tmp_path: Path) -> None:
    event_0 = valid_event(sequence=0, event_type="bundle_generated", subject_uid="hkp:test:bundle")
    event_1 = valid_event(
        sequence=1,
        event_type="concept_emitted",
        subject_uid="hkp:test:task",
        previous_event_hash="sha256:" + "d" * 64,
    )
    bundle = write_bundle(tmp_path, events=[event_0, event_1])

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "event_hash_chain_broken" in {finding.code for finding in result.findings}


def test_event_sequence_gap_fails(tmp_path: Path) -> None:
    event = valid_event(sequence=2, event_type="bundle_generated", subject_uid="hkp:test:bundle")
    bundle = write_bundle(tmp_path, events=[event])

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "event_sequence_not_contiguous" in {finding.code for finding in result.findings}


def test_event_id_derivation_mismatch_fails(tmp_path: Path) -> None:
    event = valid_event()
    event["event_id"] = "event:not-derived"
    bundle = write_bundle(tmp_path, events=[event])

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "event_id_mismatch" in {finding.code for finding in result.findings}


def test_valid_multi_event_hash_chain_passes(tmp_path: Path) -> None:
    event_0 = valid_event(sequence=0, event_type="bundle_generated", subject_uid="hkp:test:bundle")
    event_1 = valid_event(
        sequence=1,
        event_type="concept_emitted",
        subject_uid="hkp:test:task",
        previous_event_hash=_event_hash(event_0),
    )
    bundle = write_bundle(tmp_path, events=[event_0, event_1])

    result = validate_bundle(bundle)

    assert result.ok is True
    assert "event_hash_chain_broken" not in {finding.code for finding in result.findings}
    assert "event_id_mismatch" not in {finding.code for finding in result.findings}


def test_snapshot_count_mismatch_fails(tmp_path: Path) -> None:
    snapshot = valid_snapshot()
    snapshot["edge_count"] = 2
    bundle = write_bundle(tmp_path, snapshot=snapshot)

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "snapshot_edge_count_mismatch" in {finding.code for finding in result.findings}


def test_snapshot_bundle_uid_mismatch_fails(tmp_path: Path) -> None:
    snapshot = valid_snapshot()
    snapshot["bundle_uid"] = "hkp:test:other-bundle"
    bundle = write_bundle(tmp_path, snapshot=snapshot)

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "snapshot_bundle_uid_mismatch" in {finding.code for finding in result.findings}


def test_snapshot_concept_count_mismatch_fails(tmp_path: Path) -> None:
    snapshot = valid_snapshot()
    snapshot["concept_count"] = 2
    bundle = write_bundle(tmp_path, snapshot=snapshot)

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "snapshot_concept_count_mismatch" in {finding.code for finding in result.findings}


def test_duplicate_event_id_fails(tmp_path: Path) -> None:
    event_0 = valid_event(sequence=0, event_type="bundle_generated", subject_uid="hkp:test:bundle")
    event_1 = valid_event(
        sequence=1,
        event_type="concept_emitted",
        subject_uid="hkp:test:task",
    )
    event_1["event_id"] = event_0["event_id"]
    bundle = write_bundle(tmp_path, events=[event_0, event_1])

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "duplicate_event_id" in {finding.code for finding in result.findings}


def test_concept_projection_event_ref_must_exist(tmp_path: Path) -> None:
    concept = valid_concept("task")
    concept["projection_provenance"]["projection_event_ids"] = ["event:missing"]
    bundle = write_bundle(tmp_path, concept=concept)

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "concept_projection_event_missing" in {finding.code for finding in result.findings}


def test_concept_projection_event_ids_must_not_be_empty(tmp_path: Path) -> None:
    concept = valid_concept("task")
    concept["projection_provenance"]["projection_event_ids"] = []
    bundle = write_bundle(tmp_path, concept=concept)

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "concept_projection_event_missing" in {finding.code for finding in result.findings}


def test_concept_evidence_refs_must_exist(tmp_path: Path) -> None:
    concept = valid_concept("task")
    concept["projection_provenance"]["evidence_refs"] = ["src:missing"]
    bundle = write_bundle(tmp_path, concept=concept)

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "concept_evidence_ref_missing" in {finding.code for finding in result.findings}


def test_edge_refs_must_exist(tmp_path: Path) -> None:
    edge = valid_edge()
    edge["source_refs"] = ["src:missing"]
    bundle = write_bundle(tmp_path, edges=[edge])

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "edge_source_ref_missing" in {finding.code for finding in result.findings}


def test_edge_to_uid_must_exist(tmp_path: Path) -> None:
    edge = valid_edge()
    edge["to_uid"] = "hkp:test:missing"
    edge["target_ref"] = None
    bundle = write_bundle(tmp_path, edges=[edge])

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "edge_to_uid_missing" in {finding.code for finding in result.findings}


def test_edge_from_uid_must_exist(tmp_path: Path) -> None:
    edge = valid_edge()
    edge["from_uid"] = "hkp:test:missing"
    bundle = write_bundle(tmp_path, edges=[edge])

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "edge_from_uid_missing" in {finding.code for finding in result.findings}


def test_edge_target_path_must_exist(tmp_path: Path) -> None:
    edge = valid_edge()
    edge["to_uid"] = None
    edge["target_ref"] = None
    edge["target_path"] = "concepts/missing.md"
    bundle = write_bundle(tmp_path, edges=[edge])

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "edge_target_path_missing" in {finding.code for finding in result.findings}


def test_edge_target_path_symlink_is_not_a_bundle_file(tmp_path: Path) -> None:
    edge = valid_edge()
    edge["to_uid"] = None
    edge["target_ref"] = None
    edge["target_path"] = "concepts/target.md"
    bundle = write_bundle(tmp_path, edges=[edge])
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    (bundle / "concepts" / "target.md").symlink_to(outside)

    result = validate_bundle(bundle)

    assert result.ok is False
    codes = {finding.code for finding in result.findings}
    assert "edge_target_path_missing" in codes
    assert "manifest_output_tree_hash_mismatch" not in codes


def test_edge_generated_from_event_must_exist(tmp_path: Path) -> None:
    edge = valid_edge()
    edge["generated_from"]["projection_event_id"] = "event:missing"
    bundle = write_bundle(tmp_path, edges=[edge])

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "edge_generated_from_event_missing" in {finding.code for finding in result.findings}


def test_rogue_bundle_file_fails(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    (bundle / "_hkp" / "private.json").write_text("{}", encoding="utf-8")

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "bundle_unexpected_path" in {finding.code for finding in result.findings}


def test_rogue_bundle_directory_fails(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    (bundle / "private").mkdir()

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "bundle_unexpected_path" in {finding.code for finding in result.findings}


def test_rogue_bundle_symlink_fails_whitelist(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    target = tmp_path / "private.md"
    target.write_text("private\n", encoding="utf-8")
    (bundle / "private-link").symlink_to(target)

    result = validate_bundle(bundle)

    assert result.ok is False
    codes = {finding.code for finding in result.findings}
    assert "bundle_unexpected_path" in codes
    assert "manifest_output_tree_hash_mismatch" not in codes


def test_rogue_bundle_directory_symlink_is_not_hashed(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    outside = tmp_path / "outside-dir"
    outside.mkdir()
    (outside / "secret.md").write_text("private\n", encoding="utf-8")
    (bundle / "private-dir").symlink_to(outside, target_is_directory=True)

    result = validate_bundle(bundle)

    assert result.ok is False
    codes = {finding.code for finding in result.findings}
    assert "bundle_unexpected_path" in codes
    assert "manifest_output_tree_hash_mismatch" not in codes


def test_bundle_root_symlink_is_not_validated(tmp_path: Path) -> None:
    real_bundle = write_bundle(tmp_path / "real")
    symlink_bundle = tmp_path / "bundle-link"
    symlink_bundle.symlink_to(real_bundle, target_is_directory=True)

    result = validate_bundle(symlink_bundle)

    assert result.ok is False
    assert {finding.code for finding in result.findings} == {"bundle_root_symlink"}


def test_required_concepts_directory_symlink_is_not_traversed(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    (bundle / "concepts" / "task.md").unlink()
    (bundle / "concepts").rmdir()
    outside = tmp_path / "outside-concepts"
    outside.mkdir()
    (outside / "task.md").write_text("not frontmatter\n", encoding="utf-8")
    (bundle / "concepts").symlink_to(outside, target_is_directory=True)
    manifest = valid_manifest()
    manifest["output_tree_hash"] = _tree_hash(bundle)
    _write_yaml(bundle / "_hkp" / "manifest.yaml", manifest)

    result = validate_bundle(bundle)

    assert result.ok is False
    codes = {finding.code for finding in result.findings}
    assert "required_path_wrong_type" in codes
    assert "concept_frontmatter_invalid" not in codes
    assert "manifest_output_tree_hash_mismatch" not in codes


def test_required_hkp_file_symlink_is_not_read(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    outside = tmp_path / "manifest.yaml"
    outside.write_text("source_root: /home/hapax/private\n", encoding="utf-8")
    manifest = bundle / "_hkp" / "manifest.yaml"
    manifest.unlink()
    manifest.symlink_to(outside)

    result = validate_bundle(bundle)

    assert result.ok is False
    codes = {finding.code for finding in result.findings}
    assert "manifest_invalid" in codes
    assert "manifest_output_tree_hash_mismatch" not in codes
    assert "source_root must be a logical source id" not in _messages(result)


def test_required_hkp_directory_symlink_is_not_read(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    for child in (bundle / "_hkp").iterdir():
        child.unlink()
    (bundle / "_hkp").rmdir()
    outside = tmp_path / "outside-hkp"
    outside.mkdir()
    (outside / "manifest.yaml").write_text("source_root: /home/hapax/private\n", encoding="utf-8")
    (bundle / "_hkp").symlink_to(outside, target_is_directory=True)

    result = validate_bundle(bundle)

    assert result.ok is False
    codes = {finding.code for finding in result.findings}
    assert "required_path_wrong_type" in codes
    assert "manifest_invalid" in codes
    assert "source_root must be a logical source id" not in _messages(result)


def test_checksum_symlink_artifact_is_not_read(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)
    target = tmp_path / "private.md"
    target.write_text("private\n", encoding="utf-8")
    (bundle / "references" / "private.md").symlink_to(target)
    checksums = valid_checksums(bundle)
    checksums["artifacts"]["references/private.md"] = {
        "hash": HASH,
        "hash_scope": "full_content",
        "hash_algorithm": "sha256",
    }
    (bundle / "_hkp" / "checksums.json").write_text(
        json.dumps(checksums, indent=2),
        encoding="utf-8",
    )

    result = validate_bundle(bundle)

    assert result.ok is False
    codes = {finding.code for finding in result.findings}
    assert "checksums_artifact_missing" in codes
    assert "checksums_hash_mismatch" not in codes


def test_duplicate_source_ref_id_fails(tmp_path: Path) -> None:
    concept = valid_concept("task")
    concept["source_refs"] = [valid_source_ref(), valid_source_ref()]
    bundle = write_bundle(tmp_path, concept=concept)

    result = validate_bundle(bundle)

    assert result.ok is False
    assert "duplicate_source_ref_id" in {finding.code for finding in result.findings}


def test_validator_version_is_exposed_in_json_result(tmp_path: Path) -> None:
    bundle = write_bundle(tmp_path)

    payload = validate_bundle(bundle).as_dict()

    assert payload["validator_version"] == "0.2.0"


def write_bundle(
    tmp_path: Path,
    *,
    concept: dict[str, Any] | None = None,
    concept_updates: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
    consumer_policy: dict[str, Any] | None = None,
    edges: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
    snapshot: dict[str, Any] | None = None,
    body: str = "",
) -> Path:
    bundle = tmp_path / "bundle"
    (bundle / "concepts").mkdir(parents=True)
    (bundle / "references").mkdir()
    (bundle / "_hkp").mkdir()
    (bundle / "index.md").write_text("# HKP bundle\n", encoding="utf-8")
    (bundle / "log.md").write_text("# Log\n", encoding="utf-8")

    concept_payload = dict(concept or valid_concept("task"))
    if concept_updates:
        concept_payload.update(concept_updates)
    _write_markdown(bundle / "concepts" / "task.md", concept_payload, body=body)

    _write_yaml(
        bundle / "_hkp" / "consumer_policy.yaml", consumer_policy or valid_consumer_policy()
    )
    edge_rows = edges or [valid_edge()]
    event_rows = events or [valid_event()]
    snapshot_payload = snapshot or valid_snapshot(edge_count=len(edge_rows))
    _write_jsonl(bundle / "_hkp" / "edges.jsonl", edge_rows)
    _write_jsonl(bundle / "_hkp" / "events.jsonl", event_rows)
    (bundle / "_hkp" / "snapshot.json").write_text(
        json.dumps(snapshot_payload, indent=2),
        encoding="utf-8",
    )
    manifest_payload = dict(manifest or valid_manifest())
    if manifest is None or manifest.get("output_tree_hash") == TREE_HASH:
        manifest_payload["output_tree_hash"] = _tree_hash(bundle)
    if manifest is None or manifest.get("input_ref_hash") == HASH:
        manifest_payload["input_ref_hash"] = _input_ref_hash([concept_payload])
    _write_yaml(bundle / "_hkp" / "manifest.yaml", manifest_payload)
    (bundle / "_hkp" / "checksums.json").write_text(
        json.dumps(valid_checksums(bundle), indent=2),
        encoding="utf-8",
    )
    return bundle


def valid_concept(
    uid_tail: str,
    *,
    concept_path: str = "task",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "hkp_schema": 1,
        "type": "cc-task",
        "concept_uid": f"hkp:test:{uid_tail}",
        "concept_path": concept_path,
        "title": "Task",
        "description": "A task projection.",
        "resource": "file",
        "tags": ["hkp"],
        "source_refs": [valid_source_ref()],
        "posture": valid_posture(),
        "authority": {
            "level": "support_non_authoritative",
            "may_authorize": False,
            "ceiling_family": "task",
            "ceiling": "support_only",
            "promotion_required": "cc-task-with-authority-case",
        },
        "freshness": {
            "state": "fresh",
            "valid_from": None,
            "valid_until": None,
            "checked_at": "2026-06-18T16:43:11Z",
        },
        "projection_provenance": {
            "producer": "hkp-projector",
            "generated_at": "2026-06-18T16:43:11Z",
            "projection_event_ids": [
                _projection_event_id(
                    bundle_uid="hkp:test:bundle",
                    sequence=0,
                    event_type="bundle_generated",
                    subject_uid="hkp:test:bundle",
                )
            ],
            "evidence_refs": [],
            "citation_refs": [],
        },
        "summary_invariants": {
            "preserve_authority_ceiling": True,
            "preserve_cannot_prove": True,
            "preserve_source_refs": True,
            "preserve_public_private_posture": True,
        },
    }
    if extra:
        payload.update(extra)
    return payload


def valid_source_ref() -> dict[str, Any]:
    return {
        "ref_id": "src:task",
        "data_role": "authority_source",
        "source_authority_class": "planning",
        "uri": "repo:hapax-council/task.md",
        "content_hash": HASH,
        "hash_scope": "frontmatter",
        "hash_algorithm": "sha256",
        "observed_at": "2026-06-18T16:43:11Z",
        "checked_at": "2026-06-18T16:43:11Z",
        "stale_after": "P7D",
        "freshness_state": "fresh",
    }


def valid_posture() -> dict[str, Any]:
    return {
        "privacy_class": "internal",
        "consent_label_ref": None,
        "provenance_expr": None,
        "rights_state": "operator_controlled",
        "egress_state": "private",
        "public_export_allowed": False,
        "redaction_policy": "local_path_root_redaction",
        "allowed_consumers": ["research_viewer"],
        "forbidden_consumers": [
            "dispatcher",
            "close_gate",
            "release_gate",
            "runtime_loader",
            "provider_spend_gate",
        ],
    }


def valid_manifest() -> dict[str, Any]:
    return {
        "bundle_uid": "hkp:test:bundle",
        "hkp_schema": 1,
        "profile_version": "hkp-v1",
        "generator_id": "hkp-projector",
        "generator_version": "0.1.0",
        "source_root": "repo:hapax-council",
        "source_commit": None,
        "input_ref_hash": HASH,
        "output_tree_hash": TREE_HASH,
        "cache_only": True,
        "allowed_consumers": ["research_viewer"],
        "forbidden_consumers": [
            "dispatcher",
            "close_gate",
            "release_gate",
            "runtime_loader",
            "provider_spend_gate",
        ],
        "created_at": "2026-06-18T16:43:11Z",
        "generated_at": "2026-06-18T16:43:11Z",
    }


def valid_consumer_policy() -> dict[str, Any]:
    rows = []
    defaults = {
        "research_viewer": "allow_read_only",
        "local_prompt_context": "allow_with_ceiling",
        "dashboard": "allow_after_explicit_row",
        "qdrant_rag": "deny",
        "public_export": "deny",
        "release_gate": "deny",
        "dispatcher": "deny",
        "close_gate": "deny",
        "runtime_loader": "deny",
        "provider_spend_gate": "deny",
        "unknown": "deny",
    }
    for consumer, default in defaults.items():
        rows.append(
            {
                "consumer": consumer,
                "default": default,
                "allowed_fields": ["title"] if default != "deny" else [],
                "forbidden_fields": ["body"],
                "title_leak_policy": "generic",
                "body_leak_policy": "drop_private",
                "path_redaction_policy": "local_path_root_redaction",
                "embedding_allowed": False,
                "retrieval_allowed": False,
            }
        )
    return {"hkp_schema": 1, "consumers": rows}


def valid_edge() -> dict[str, Any]:
    return {
        "hkp_schema": 1,
        "edge_id": "hkp-edge:test:1",
        "from_uid": "hkp:test:task",
        "rel_family": "dependency",
        "rel": "depends_on",
        "direction": "outbound",
        "to_uid": None,
        "target_ref": "cc-task:upstream",
        "target_path": None,
        "source_refs": ["src:task"],
        "authority_ceiling": "evidence_bound",
        "freshness": {"state": "fresh"},
        "generated_from": {
            "projection_event_id": _projection_event_id(
                bundle_uid="hkp:test:bundle",
                sequence=0,
                event_type="bundle_generated",
                subject_uid="hkp:test:bundle",
            ),
            "generator_id": "hkp-projector",
        },
    }


def valid_event(
    *,
    sequence: int = 0,
    event_type: str = "bundle_generated",
    subject_uid: str = "hkp:test:bundle",
    previous_event_hash: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "event_id": _projection_event_id(
            bundle_uid="hkp:test:bundle",
            sequence=sequence,
            event_type=event_type,
            subject_uid=subject_uid,
        ),
        "sequence": sequence,
        "timestamp": "2026-06-18T16:43:11Z",
        "event_type": event_type,
        "actor": "hkp-projector",
        "subject_uid": subject_uid,
        "payload": {},
        "previous_event_hash": previous_event_hash,
    }


def valid_checksums(bundle: Path | None = None) -> dict[str, Any]:
    if bundle is None:
        return {
            "hkp_schema": 1,
            "artifacts": {
                "concepts/task.md": {
                    "hash": HASH,
                    "hash_scope": "full_content",
                    "hash_algorithm": "sha256",
                }
            },
        }
    relative_paths = [
        "index.md",
        "log.md",
        "_hkp/manifest.yaml",
        "_hkp/consumer_policy.yaml",
        "_hkp/edges.jsonl",
        "_hkp/events.jsonl",
        "_hkp/snapshot.json",
    ]
    relative_paths.extend(
        str(path.relative_to(bundle)) for path in sorted((bundle / "concepts").rglob("*.md"))
    )
    relative_paths.extend(
        str(path.relative_to(bundle))
        for path in sorted((bundle / "references").rglob("*"))
        if path.is_file()
    )
    return {
        "hkp_schema": 1,
        "artifacts": {
            relative_path: {
                "hash": "sha256:" + sha256((bundle / relative_path).read_bytes()).hexdigest(),
                "hash_scope": "full_content",
                "hash_algorithm": "sha256",
            }
            for relative_path in relative_paths
        },
    }


def valid_snapshot(*, edge_count: int = 1) -> dict[str, Any]:
    return {
        "hkp_schema": 1,
        "bundle_uid": "hkp:test:bundle",
        "generated_at": "2026-06-18T16:43:11Z",
        "concept_count": 1,
        "edge_count": edge_count,
    }


def _tree_hash(bundle: Path) -> str:
    excluded = {"_hkp/checksums.json", "_hkp/manifest.yaml"}
    rows: list[dict[str, str]] = []
    for path in _iter_paths(bundle):
        relative_path = path.relative_to(bundle).as_posix()
        if path.is_symlink() or not path.is_file() or relative_path in excluded:
            continue
        rows.append(
            {
                "path": relative_path,
                "hash": "sha256:" + sha256(path.read_bytes()).hexdigest(),
            }
        )
    return "sha256:" + sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def _iter_paths(root: Path) -> list[Path]:
    if root.is_symlink():
        return [root]
    paths: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        entries = [current / name for name in [*dirnames, *filenames]]
        paths.extend(entries)
        dirnames[:] = [name for name in dirnames if not (current / name).is_symlink()]
    return sorted(paths)


def _input_ref_hash(concepts: list[dict[str, Any]]) -> str:
    rows = [
        {"uri": source_ref["uri"], "content_hash": source_ref["content_hash"]}
        for concept in concepts
        for source_ref in concept.get("source_refs", [])
        if source_ref.get("content_hash")
    ]
    rows.sort(key=lambda row: row["uri"])
    return "sha256:" + sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def _json_hash(payload: dict[str, Any]) -> str:
    return "sha256:" + sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _event_hash(payload: dict[str, Any]) -> str:
    event = HkpProjectionEvent.model_validate(payload)
    return _json_hash(event.model_dump(mode="json"))


def _projection_event_id(
    *,
    bundle_uid: str,
    sequence: int,
    event_type: str,
    subject_uid: str,
) -> str:
    seed = f"{bundle_uid}:{sequence}:{event_type}:{subject_uid}"
    return f"event:{sha256(seed.encode()).hexdigest()[:24]}"


def _write_markdown(path: Path, frontmatter: dict[str, Any], body: str = "") -> None:
    path.write_text(
        "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n\n" + body,
        encoding="utf-8",
    )


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _messages(result: Any) -> str:
    return "\n".join(finding.message for finding in result.findings)
