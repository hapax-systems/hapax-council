from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

import hapax_agentic_trust.custody as custody
import hapax_agentic_trust.terminal as terminal_module
from hapax_agentic_trust import AgenticTrustVerificationError, verify_terminal_projection


def _canonical_terminal_bytes(document: dict[str, object]) -> bytes:
    core = {key: value for key, value in document.items() if key != "evidence_root_sha256"}
    document["evidence_root_sha256"] = hashlib.sha256(
        json.dumps(
            core,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()
    return (
        json.dumps(
            document,
            allow_nan=False,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("ascii")


def _terminal_document(root: Path) -> dict[str, object]:
    return json.loads((root / "terminal" / "bundle.json").read_bytes())


def _inventory_from_terminal(
    root: Path,
) -> tuple[dict[str, object], custody.SealedEvidenceInventory]:
    document = _terminal_document(root)
    inventory_path = root / str(document["evidence_store_inventory_relative_path"])
    return document, custody.SealedEvidenceInventory.from_bytes(inventory_path.read_bytes())


def _open_root_fd(root: Path) -> int:
    return os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )


def _tree_snapshot(root: Path) -> tuple[tuple[str, int, int, int, int, str], ...]:
    rows: list[tuple[str, int, int, int, int, str]] = []
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        info = path.stat(follow_symlinks=False)
        rows.append(
            (
                path.relative_to(root).as_posix(),
                info.st_ino,
                info.st_mode,
                info.st_size,
                info.st_mtime_ns,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
    return tuple(rows)


def test_frozen_terminal_matches_exact_hardened_projection(
    golden_terminal: tuple[Path, dict[str, str]],
) -> None:
    root, anchors = golden_terminal
    before = _tree_snapshot(root)

    projection = verify_terminal_projection(
        root,
        "terminal/bundle.json",
        expected_bundle_sha256=anchors["bundle_sha256"],
        expected_evidence_root_sha256=anchors["evidence_root_sha256"],
        expected_manifest_snapshot_artifact_sha256=anchors["manifest_snapshot_artifact_sha256"],
    )

    assert projection.graph.digest == anchors["graph_digest"]
    assert projection.summary_sha256 == anchors["summary_digest"]
    assert projection.graph.run_id == anchors["run_id"]
    assert projection.caller_anchor_match is True
    assert projection.anchor_status == "caller_supplied_three_anchor_values_matched"
    assert projection.may_authorize_external_action is False
    assert _tree_snapshot(root) == before


@pytest.mark.parametrize(
    "supplied",
    [
        (True, False, False),
        (False, True, False),
        (False, False, True),
        (True, True, False),
        (True, False, True),
        (False, True, True),
    ],
)
def test_caller_digest_pins_are_all_or_nothing(
    golden_terminal: tuple[Path, dict[str, str]],
    supplied: tuple[bool, bool, bool],
) -> None:
    root, anchors = golden_terminal
    values = (
        anchors["bundle_sha256"],
        anchors["evidence_root_sha256"],
        anchors["manifest_snapshot_artifact_sha256"],
    )
    with pytest.raises(AgenticTrustVerificationError) as raised:
        verify_terminal_projection(
            root,
            "terminal/bundle.json",
            expected_bundle_sha256=values[0] if supplied[0] else None,
            expected_evidence_root_sha256=values[1] if supplied[1] else None,
            expected_manifest_snapshot_artifact_sha256=(values[2] if supplied[2] else None),
        )
    assert raised.value.reason_code == "caller_anchor_verification_failed"
    assert "origin, custody, and chronology" in raised.value.next_action


@pytest.mark.parametrize("anchor_name", ["bundle", "evidence_root", "manifest"])
def test_any_alternate_valid_digest_rejects_without_writing(
    golden_terminal: tuple[Path, dict[str, str]],
    anchor_name: str,
) -> None:
    root, anchors = golden_terminal
    before = _tree_snapshot(root)
    values = {
        "bundle": anchors["bundle_sha256"],
        "evidence_root": anchors["evidence_root_sha256"],
        "manifest": anchors["manifest_snapshot_artifact_sha256"],
    }
    values[anchor_name] = hashlib.sha256(anchor_name.encode()).hexdigest()
    with pytest.raises(AgenticTrustVerificationError) as raised:
        verify_terminal_projection(
            root,
            "terminal/bundle.json",
            expected_bundle_sha256=values["bundle"],
            expected_evidence_root_sha256=values["evidence_root"],
            expected_manifest_snapshot_artifact_sha256=values["manifest"],
        )
    assert raised.value.reason_code == "caller_anchor_verification_failed"
    assert "differs from caller-supplied digest values" in raised.value.detail
    assert _tree_snapshot(root) == before


def test_unanchored_projection_is_explicitly_non_authoritative(
    golden_terminal: tuple[Path, dict[str, str]],
) -> None:
    root, _ = golden_terminal
    projection = verify_terminal_projection(root, "terminal/bundle.json")
    assert projection.caller_anchor_match is False
    assert projection.anchor_status == "caller_anchor_values_absent"
    assert projection.may_authorize_external_action is False


def test_projection_rejects_cross_binding_mutation(
    golden_terminal: tuple[Path, dict[str, str]],
) -> None:
    root, anchors = golden_terminal
    projection = verify_terminal_projection(
        root,
        "terminal/bundle.json",
        expected_bundle_sha256=anchors["bundle_sha256"],
        expected_evidence_root_sha256=anchors["evidence_root_sha256"],
        expected_manifest_snapshot_artifact_sha256=anchors["manifest_snapshot_artifact_sha256"],
    )
    poisoned_binding = replace(
        projection.evidence_store_binding,
        inventory_size=projection.evidence_store_binding.inventory_size + 1,
    )

    with pytest.raises(ValueError, match="evidence-store binding differs"):
        replace(projection, evidence_store_binding=poisoned_binding)


def test_missing_bundle_root_is_classified_as_custody_failure(tmp_path: Path) -> None:
    with pytest.raises(AgenticTrustVerificationError) as raised:
        verify_terminal_projection(tmp_path / "absent", "terminal/bundle.json")

    assert raised.value.reason_code == "custody_verification_failed"
    assert "immutable custody" in raised.value.next_action


def test_terminal_hardlink_is_rejected(
    golden_terminal: tuple[Path, dict[str, str]],
) -> None:
    root, _ = golden_terminal
    os.link(root / "terminal" / "bundle.json", root / "terminal" / "bundle-alias.json")
    with pytest.raises(AgenticTrustVerificationError, match="exactly one hard link") as raised:
        verify_terminal_projection(root, "terminal/bundle.json")
    assert raised.value.reason_code == "custody_verification_failed"
    assert raised.value.target == "terminal/bundle.json"
    assert raised.value.next_action == (
        "quarantine the evidence store and restore it from immutable custody"
    )


def test_symlinked_root_ancestor_is_rejected(
    golden_terminal: tuple[Path, dict[str, str]],
    tmp_path: Path,
) -> None:
    root, _ = golden_terminal
    alias = tmp_path / "root-alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        verify_terminal_projection(alias, "terminal/bundle.json")


def test_symlinked_terminal_is_rejected(
    golden_terminal: tuple[Path, dict[str, str]],
) -> None:
    root, _ = golden_terminal
    terminal = root / "terminal" / "bundle.json"
    payload = terminal.read_bytes()
    terminal.chmod(0o600)
    terminal.unlink()
    target = root / "terminal" / "real-bundle.json"
    target.write_bytes(payload)
    target.chmod(0o400)
    terminal.symlink_to(target.name)
    with pytest.raises(ValueError, match="symlink"):
        verify_terminal_projection(root, "terminal/bundle.json")


@pytest.mark.parametrize(
    "relative_path",
    ["../terminal/bundle.json", "/terminal/bundle.json", "terminal/../bundle.json"],
)
def test_terminal_path_must_be_confined(
    golden_terminal: tuple[Path, dict[str, str]],
    relative_path: str,
) -> None:
    root, _ = golden_terminal
    with pytest.raises(ValueError):
        verify_terminal_projection(root, relative_path)


def test_non_directory_root_rejects(tmp_path: Path) -> None:
    root = tmp_path / "not-a-directory"
    root.write_bytes(b"x")
    with pytest.raises(ValueError, match="directory"):
        verify_terminal_projection(root, "terminal/bundle.json")


def test_terminal_mode_must_be_read_only(
    golden_terminal: tuple[Path, dict[str, str]],
) -> None:
    root, _ = golden_terminal
    terminal = root / "terminal" / "bundle.json"
    terminal.chmod(0o600)
    with pytest.raises(ValueError, match="0400"):
        verify_terminal_projection(root, "terminal/bundle.json")


def test_custodied_object_drift_is_rejected_without_touching_other_objects(
    golden_terminal: tuple[Path, dict[str, str]],
) -> None:
    root, _ = golden_terminal
    object_path = next((root / "objects" / "sha256").glob("*/*"))
    object_path.chmod(0o600)
    object_path.write_bytes(object_path.read_bytes() + b"drift")
    object_path.chmod(0o400)
    before = _tree_snapshot(root)
    with pytest.raises((ValueError, RuntimeError)):
        verify_terminal_projection(root, "terminal/bundle.json")
    assert _tree_snapshot(root) == before


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("expected_sha256", "f" * 64, "path digest"),
        ("expected_root_sha256", "f" * 64, "expected root"),
        ("expected_size", 1, "expected size"),
        ("expected_entry_count", 1, "expected count"),
    ],
)
def test_inventory_loader_rejects_each_external_pin_drift(
    golden_terminal: tuple[Path, dict[str, str]],
    field: str,
    replacement: str | int,
    message: str,
) -> None:
    root, _ = golden_terminal
    document, inventory = _inventory_from_terminal(root)
    arguments: dict[str, str | int] = {
        "expected_sha256": str(document["evidence_store_inventory_sha256"]),
        "expected_root_sha256": str(document["evidence_store_inventory_root_sha256"]),
        "expected_size": int(document["evidence_store_inventory_size"]),
        "expected_entry_count": int(document["evidence_store_inventory_entry_count"]),
    }
    assert len(inventory.entries) == arguments["expected_entry_count"]
    arguments[field] = replacement
    root_fd = _open_root_fd(root)
    try:
        with pytest.raises(ValueError, match=message):
            custody.load_evidence_inventory_with_root_fd(
                root_fd,
                str(document["evidence_store_inventory_relative_path"]),
                **arguments,
            )
    finally:
        os.close(root_fd)


def test_held_root_fd_survives_source_path_rename_without_reopening(
    golden_terminal: tuple[Path, dict[str, str]],
) -> None:
    root, _ = golden_terminal
    document, expected = _inventory_from_terminal(root)
    root_fd = _open_root_fd(root)
    moved = root.with_name(f"{root.name}-held")
    root.rename(moved)
    try:
        observed = custody.load_evidence_inventory_with_root_fd(
            root_fd,
            str(document["evidence_store_inventory_relative_path"]),
            expected_sha256=str(document["evidence_store_inventory_sha256"]),
            expected_root_sha256=str(document["evidence_store_inventory_root_sha256"]),
            expected_size=int(document["evidence_store_inventory_size"]),
            expected_entry_count=int(document["evidence_store_inventory_entry_count"]),
        )
        assert observed == expected
        assert stat_is_directory(os.fstat(root_fd).st_mode)
    finally:
        os.close(root_fd)


def stat_is_directory(mode: int) -> bool:
    return (mode & 0o170000) == 0o040000


def test_object_reader_rejects_detached_shard_rebinding(
    golden_terminal: tuple[Path, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = golden_terminal
    _, inventory = _inventory_from_terminal(root)
    entry = inventory.entries[0]
    shard = (root / entry.object_relative_path).parent
    held_shard = shard.with_name(f"{shard.name}-held")
    real_observe = custody._observe_named_regular_file
    replaced = False

    def observe_then_rebind(*args: object, **kwargs: object) -> object:
        nonlocal replaced
        result = real_observe(*args, **kwargs)
        if not replaced and kwargs.get("display_name") == entry.object_relative_path:
            replaced = True
            shard.rename(held_shard)
            shard.mkdir()
            forged = shard / entry.sha256
            forged.write_bytes(b"forged replacement")
            forged.chmod(0o400)
        return result

    monkeypatch.setattr(custody, "_observe_named_regular_file", observe_then_rebind)
    root_fd = _open_root_fd(root)
    try:
        with pytest.raises(ValueError, match="failed verification"):
            custody.read_verified_evidence_object_with_root_fd(root_fd, entry)
    finally:
        os.close(root_fd)


def test_inventory_loader_rejects_detached_inventory_shard_rebinding(
    golden_terminal: tuple[Path, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = golden_terminal
    document, _ = _inventory_from_terminal(root)
    relative_path = str(document["evidence_store_inventory_relative_path"])
    shard = (root / relative_path).parent
    held_shard = shard.with_name(f"{shard.name}-held")
    real_observe = custody._observe_named_regular_file
    replaced = False

    def observe_then_rebind(*args: object, **kwargs: object) -> object:
        nonlocal replaced
        result = real_observe(*args, **kwargs)
        if not replaced and kwargs.get("display_name") == relative_path:
            replaced = True
            shard.rename(held_shard)
            shard.mkdir()
            forged = shard / str(document["evidence_store_inventory_sha256"])
            forged.write_bytes(b"forged inventory")
            forged.chmod(0o400)
        return result

    monkeypatch.setattr(custody, "_observe_named_regular_file", observe_then_rebind)
    root_fd = _open_root_fd(root)
    try:
        with pytest.raises((ValueError, RuntimeError), match="inventory|absent|verification"):
            custody.load_evidence_inventory_with_root_fd(
                root_fd,
                relative_path,
                expected_sha256=str(document["evidence_store_inventory_sha256"]),
                expected_root_sha256=str(document["evidence_store_inventory_root_sha256"]),
                expected_size=int(document["evidence_store_inventory_size"]),
                expected_entry_count=int(document["evidence_store_inventory_entry_count"]),
            )
    finally:
        os.close(root_fd)


def test_public_verifier_rejects_root_path_replacement_after_held_fd_analysis(
    golden_terminal: tuple[Path, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = golden_terminal
    moved = root.with_name(f"{root.name}-held")
    real_verify = terminal_module._verify_artifact_inventory

    def verify_then_rebind(*args: object, **kwargs: object) -> object:
        result = real_verify(*args, **kwargs)
        root.rename(moved)
        root.mkdir()
        return result

    monkeypatch.setattr(terminal_module, "_verify_artifact_inventory", verify_then_rebind)
    with pytest.raises(AgenticTrustVerificationError, match="root path changed") as raised:
        verify_terminal_projection(root, "terminal/bundle.json")
    assert raised.value.reason_code == "custody_verification_failed"


def test_final_revalidation_rejects_terminal_replacement_after_semantic_analysis(
    golden_terminal: tuple[Path, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = golden_terminal
    terminal = root / "terminal" / "bundle.json"
    real_verify = terminal_module._verify_artifact_inventory

    def verify_then_replace(*args: object, **kwargs: object) -> object:
        result = real_verify(*args, **kwargs)
        terminal.unlink()
        terminal.write_bytes(b"forged terminal replacement")
        terminal.chmod(0o400)
        return result

    monkeypatch.setattr(terminal_module, "_verify_artifact_inventory", verify_then_replace)

    with pytest.raises(AgenticTrustVerificationError) as raised:
        verify_terminal_projection(root, "terminal/bundle.json")
    assert raised.value.reason_code == "custody_verification_failed"


def test_final_revalidation_rejects_object_replacement_after_bootstrap_load(
    golden_terminal: tuple[Path, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = golden_terminal
    real_load = terminal_module._load_custodied_observed_inventory

    def load_then_replace(*args: object, **kwargs: object) -> object:
        result = real_load(*args, **kwargs)
        _observed, inventory = result
        summary_entry = next(
            entry
            for entry in inventory.entries
            if entry.logical_path == "evidence/run/summary.json"
        )
        object_path = root / summary_entry.object_relative_path
        object_path.unlink()
        object_path.write_bytes(b"forged summary replacement")
        object_path.chmod(0o400)
        return result

    monkeypatch.setattr(
        terminal_module,
        "_load_custodied_observed_inventory",
        load_then_replace,
    )

    with pytest.raises(AgenticTrustVerificationError) as raised:
        verify_terminal_projection(root, "terminal/bundle.json")
    assert raised.value.reason_code == "custody_verification_failed"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("authority_status", "execution_authorized", "execution authority"),
        ("terminal_closure_law", "weaker-law", "closure law"),
        ("temporal_anchor_status", "self_anchored", "temporal-anchor"),
    ],
)
def test_semantically_resealed_terminal_cannot_poison_authority_or_closure(
    golden_terminal: tuple[Path, dict[str, str]],
    field: str,
    value: str,
    message: str,
) -> None:
    root, _ = golden_terminal
    terminal = root / "terminal" / "bundle.json"
    document = _terminal_document(root)
    document[field] = value
    terminal.chmod(0o600)
    terminal.write_bytes(_canonical_terminal_bytes(document))
    terminal.chmod(0o400)

    with pytest.raises(AgenticTrustVerificationError, match=message) as raised:
        verify_terminal_projection(root, "terminal/bundle.json")
    assert raised.value.reason_code == "terminal_closure_invalid"


def test_semantically_resealed_terminal_cannot_change_closure_cardinality(
    golden_terminal: tuple[Path, dict[str, str]],
) -> None:
    root, _ = golden_terminal
    terminal = root / "terminal" / "bundle.json"
    document = _terminal_document(root)
    document["evidence_store_inventory_entry_count"] = (
        int(document["evidence_store_inventory_entry_count"]) + 1
    )
    terminal.chmod(0o600)
    terminal.write_bytes(_canonical_terminal_bytes(document))
    terminal.chmod(0o400)

    with pytest.raises(AgenticTrustVerificationError, match="cardinality"):
        verify_terminal_projection(root, "terminal/bundle.json")
