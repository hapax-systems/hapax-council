from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROVENANCE_PATH = PACKAGE_ROOT / "PROVENANCE.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checksum_manifest(path: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, relative_path = line.split("  ", 1)
        parsed = PurePosixPath(relative_path)
        assert not parsed.is_absolute()
        assert parsed.as_posix() == relative_path
        assert all(part not in {"", ".", ".."} for part in parsed.parts)
        assert len(digest) == 64
        assert relative_path not in rows
        rows[relative_path] = digest
    return rows


def _provenance() -> dict[str, object]:
    document = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def test_machine_provenance_keeps_the_no_authority_claim_ceiling() -> None:
    document = _provenance()

    assert document["record_type"] == "unsigned_local_source_transformation_record"
    assert document["attestation_status"] == "not_signed_not_slsa_not_in_toto"
    assert document["repository"]["worktree_state"] == "committed_feature_branch_not_released"
    assert document["scope"] == {
        "role": "evidence_only_non_supply",
        "activation": False,
        "route_id": None,
        "demand_eligible": False,
        "may_execute": False,
        "may_authorize_external_action": False,
        "may_authorize_spend": False,
        "may_authorize_public_egress": False,
    }
    ceiling = document["claim_ceiling"]
    assert ceiling["run_result_asserted_by_this_record"] is False
    assert (
        ceiling["maximum_positive_run_claim"]
        == "caller_digest_values_matched_observed_content_only"
    )
    assert ceiling["maximum_positive_run_claim_applies_per_verified_receipt_only"] is True
    assert all(
        value is False
        for name, value in ceiling.items()
        if name
        not in {
            "maximum_positive_run_claim",
            "maximum_positive_run_claim_applies_per_verified_receipt_only",
        }
    )


def test_archived_recovery_inputs_match_the_recorded_source_bytes() -> None:
    document = _provenance()
    lineage = document["lineage"]
    for source in lineage["inputs"]:
        archived = PACKAGE_ROOT / source["archived_path"]
        assert archived.is_file()
        assert archived.stat().st_size == source["size"]
        assert _sha256(archived) == source["sha256"]
        assert source["transformation_class"] != "exact"

    handoff = lineage["preserved_handoff"]
    handoff_path = PACKAGE_ROOT / handoff["path"]
    assert handoff_path.stat().st_size == handoff["size"]
    assert _sha256(handoff_path) == handoff["sha256"] == lineage["recovery_handoff_sha256"]


def test_payload_manifest_and_machine_rows_match_every_declared_output() -> None:
    document = _provenance()
    payload = document["payload"]
    manifest_path = PACKAGE_ROOT / payload["manifest_path"]
    manifest = _checksum_manifest(manifest_path)
    rows = {row["path"]: row for row in payload["files"]}

    assert _sha256(manifest_path) == payload["manifest_sha256"]
    assert list(rows) == sorted(rows)
    assert set(rows) == set(manifest)
    assert len(rows) == payload["file_count"]
    assert sum(row["size"] for row in rows.values()) == payload["total_bytes"]
    assert "PROVENANCE.json" not in rows
    for relative_path, row in rows.items():
        output = PACKAGE_ROOT / relative_path
        assert output.is_file()
        assert output.stat().st_size == row["size"]
        assert _sha256(output) == row["sha256"] == manifest[relative_path]


def test_synthetic_fixture_manifest_is_complete_but_not_an_external_anchor() -> None:
    document = _provenance()
    fixture = document["fixture"]
    fixture_root = PACKAGE_ROOT / fixture["path"]
    manifest_path = PACKAGE_ROOT / fixture["manifest_path"]
    manifest = _checksum_manifest(manifest_path)
    actual_paths = {
        path.relative_to(fixture_root).as_posix()
        for path in fixture_root.rglob("*")
        if path.is_file()
    }

    assert fixture["kind"] == "synthetic_known_answer"
    assert fixture["empirical_evidence"] is False
    assert fixture["independent_anchor"] is False
    assert fixture["generation_reproducible"] is False
    assert _sha256(manifest_path) == fixture["manifest_sha256"]
    assert set(manifest) == actual_paths
    assert len(manifest) == fixture["file_count"] == 54
    assert sum((fixture_root / path).stat().st_size for path in manifest) == fixture["total_bytes"]
    for relative_path, digest in manifest.items():
        assert _sha256(fixture_root / relative_path) == digest
    assert _sha256(fixture_root / "anchors.json") == fixture["anchors_json_sha256"]
    assert (
        _sha256(fixture_root / "store" / "terminal" / "bundle.json")
        == fixture["terminal_bundle_sha256"]
    )
