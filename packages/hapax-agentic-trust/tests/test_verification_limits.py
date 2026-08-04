from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import fields, replace
from pathlib import Path

import pytest

import hapax_agentic_trust.run_graph as run_graph_module
from hapax_agentic_trust import (
    DEFAULT_VERIFICATION_LIMITS,
    AgenticRunGraph,
    AgenticTrustEvidenceReceiptV1,
    AgenticTrustVerificationError,
    VerificationLimits,
    custody,
    terminal,
    verify_terminal_projection,
)
from hapax_agentic_trust.custody import EvidenceInventoryEntry, EvidenceInventoryExpectation
from hapax_agentic_trust.limits import validate_json_resource_envelope

ZERO_SHA = "0" * 64

# Exact observed maxima for the frozen 53-object evidence store plus terminal
# bundle. These values are evidence-fixture facts, not package-wide policy.
GOLDEN_EXACT_LIMITS = VerificationLimits(
    terminal_bundle_bytes=29_297,
    inventory_bytes=18_906,
    inventory_entries=54,
    evidence_object_bytes=258_214,
    total_evidence_bytes=473_232,
    retained_evidence_bytes=376_263,
    artifact_rows=55,
    receipt_rows=55,
    canonical_json_bytes=258_214,
    json_nesting_depth=23,
    relative_path_bytes=117,
    relative_path_components=6,
    scheduled_pairs=1,
    terminal_attempts=3,
)


def _verify(
    root: Path,
    anchors: dict[str, str],
    limits: VerificationLimits,
):
    return verify_terminal_projection(
        root,
        "terminal/bundle.json",
        expected_bundle_sha256=anchors["bundle_sha256"],
        expected_evidence_root_sha256=anchors["evidence_root_sha256"],
        expected_manifest_snapshot_artifact_sha256=(anchors["manifest_snapshot_artifact_sha256"]),
        limits=limits,
    )


def test_exact_default_and_generous_limits_preserve_identical_evidence(
    golden_terminal: tuple[Path, dict[str, str]],
) -> None:
    root, anchors = golden_terminal
    generous = VerificationLimits(
        **{
            field.name: getattr(DEFAULT_VERIFICATION_LIMITS, field.name) * 2
            for field in fields(VerificationLimits)
        }
    )

    projections = tuple(
        _verify(root, anchors, limits)
        for limits in (GOLDEN_EXACT_LIMITS, DEFAULT_VERIFICATION_LIMITS, generous)
    )

    assert len({projection.bundle.bundle_sha256 for projection in projections}) == 1
    assert len({projection.graph.digest for projection in projections}) == 1
    assert len({projection.summary_sha256 for projection in projections}) == 1


@pytest.mark.parametrize(
    ("field_name", "required"),
    [
        ("terminal_bundle_bytes", 29_297),
        ("inventory_bytes", 18_906),
        ("inventory_entries", 54),
        ("evidence_object_bytes", 258_214),
        ("total_evidence_bytes", 473_232),
        ("retained_evidence_bytes", 376_263),
        ("artifact_rows", 55),
        ("receipt_rows", 55),
        ("canonical_json_bytes", 258_214),
        ("json_nesting_depth", 23),
        ("relative_path_bytes", 117),
        ("relative_path_components", 6),
        ("terminal_attempts", 3),
    ],
)
def test_one_below_observed_requirement_fails_with_named_limit_and_next_action(
    golden_terminal: tuple[Path, dict[str, str]],
    field_name: str,
    required: int,
) -> None:
    root, anchors = golden_terminal
    limits = replace(GOLDEN_EXACT_LIMITS, **{field_name: required - 1})

    with pytest.raises(ValueError, match=rf"{field_name}=?.*next action"):
        _verify(root, anchors, limits)


def test_scheduled_pair_limit_rejects_before_recursive_graph_decode(
    golden_terminal: tuple[Path, dict[str, str]],
) -> None:
    root, _ = golden_terminal
    graph_path = next(
        path
        for path in (root / "objects" / "sha256").glob("*/*")
        if json.loads(path.read_bytes()).get("document_type") == "agentic_run_graph"
    )
    document = json.loads(graph_path.read_bytes())
    scheduled_pairs = document["payload"]["graph"]["fields"]["scheduled_pairs"]
    document["payload"]["graph"]["fields"]["scheduled_pairs"] = scheduled_pairs * 2
    raw = json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")

    with pytest.raises(ValueError, match=r"scheduled_pairs.*next action"):
        AgenticRunGraph.from_bytes(
            raw,
            limits=replace(DEFAULT_VERIFICATION_LIMITS, scheduled_pairs=1),
        )


@pytest.mark.parametrize(
    ("field_name", "mutation"),
    (
        ("run_artifact_bindings", lambda rows: rows * 2),
        ("persisted_summary", lambda rows: rows * 2),
    ),
)
def test_fixed_graph_arrays_reject_before_recursive_decode(
    golden_terminal: tuple[Path, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
    mutation: Callable[[list[object]], list[object]],
) -> None:
    root, _ = golden_terminal
    graph_path = next(
        path
        for path in (root / "objects" / "sha256").glob("*/*")
        if json.loads(path.read_bytes()).get("document_type") == "agentic_run_graph"
    )
    document = json.loads(graph_path.read_bytes())
    if field_name == "run_artifact_bindings":
        fields_row = document["payload"]["graph"]["fields"]
        fields_row["run_artifact_bindings"] = mutation(fields_row["run_artifact_bindings"])
        expected = "run_artifact_bindings"
    else:
        fields_row = document["payload"]["summary"]["fields"]
        fields_row["initial_outcome_counts"] = mutation(fields_row["initial_outcome_counts"])
        expected = "initial_outcome_counts"
    raw = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("ascii")

    def forbidden_decode(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("recursive decoder must not run past fixed cardinality checks")

    monkeypatch.setattr(run_graph_module, "_decode_registered", forbidden_decode)
    with pytest.raises(ValueError, match=expected):
        AgenticRunGraph.from_bytes(raw)


def test_witness_pack_cardinality_rejects_before_base64_construction(
    golden_terminal: tuple[Path, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = golden_terminal
    witness_path = next(
        path
        for path in (root / "objects" / "sha256").glob("*/*")
        if b'"document_type"' in path.read_bytes()
        and b"agentic_attempt_witness_pack" in path.read_bytes()
    )
    document = json.loads(witness_path.read_bytes())
    document["witnesses"] = document["witnesses"] * 2
    assert len(document["witnesses"]) > terminal.MAX_ATTEMPT_WITNESS_COUNT
    raw = json.dumps(document, separators=(",", ":"), sort_keys=True).encode("ascii")

    class ForbiddenWitness:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("witness rows must not be constructed past the role ceiling")

    monkeypatch.setattr(terminal, "WitnessBlob", ForbiddenWitness)
    with pytest.raises(ValueError, match="between 1 and 9"):
        terminal.AttemptWitnessPack.from_bytes(raw)


def test_expected_projection_stops_bounded_iteration() -> None:
    entry = EvidenceInventoryExpectation("evidence/a", ZERO_SHA, 0)
    yielded = 0

    def unbounded_entries():
        nonlocal yielded
        while True:
            yielded += 1
            yield entry

    with pytest.raises(ValueError, match="more rows than expected_entry_count"):
        custody._validate_expected_projection(
            unbounded_entries(),
            expected_entry_count=1,
            limits=DEFAULT_VERIFICATION_LIMITS,
        )
    assert yielded == 2


def test_terminal_bundle_size_is_rejected_from_fstat_before_read(
    golden_terminal: tuple[Path, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _ = golden_terminal

    def forbidden_read(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("os.read must not run after an oversized fstat")

    monkeypatch.setattr(terminal.os, "read", forbidden_read)
    with pytest.raises(ValueError, match=r"terminal_bundle_bytes=1.*next action"):
        verify_terminal_projection(
            root,
            "terminal/bundle.json",
            limits=replace(DEFAULT_VERIFICATION_LIMITS, terminal_bundle_bytes=1),
        )


def test_inventory_cardinality_rejects_before_entry_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = {
        "logical_path": "evidence/x",
        "object_relative_path": f"objects/sha256/{ZERO_SHA[:2]}/{ZERO_SHA}",
        "sha256": ZERO_SHA,
        "size": 0,
    }
    raw = json.dumps(
        {
            "authority_status": custody.AUTHORITY_STATUS,
            "entries": [row, {**row, "logical_path": "evidence/y"}],
            "hash_algorithm": custody.HASH_ALGORITHM,
            "inventory_root_sha256": ZERO_SHA,
            "may_authorize_external_action": False,
            "object_layout": custody.OBJECT_LAYOUT,
            "schema_version": custody.EVIDENCE_INVENTORY_SCHEMA_VERSION,
        }
    ).encode()

    class ForbiddenEntry:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("inventory entries must not be constructed past the row limit")

    monkeypatch.setattr(custody, "EvidenceInventoryEntry", ForbiddenEntry)
    with pytest.raises(ValueError, match=r"inventory_entries=1.*next action"):
        custody._validate_inventory_bytes(
            raw,
            limits=replace(DEFAULT_VERIFICATION_LIMITS, inventory_entries=1),
        )


def test_operational_limits_do_not_redefine_evidence_value_objects() -> None:
    entry = EvidenceInventoryEntry(
        logical_path="evidence/large.bin",
        object_relative_path=f"objects/sha256/{ZERO_SHA[:2]}/{ZERO_SHA}",
        sha256=ZERO_SHA,
        size=DEFAULT_VERIFICATION_LIMITS.evidence_object_bytes + 1,
    )
    assert entry.size > DEFAULT_VERIFICATION_LIMITS.evidence_object_bytes


def test_json_depth_guard_handles_strings_and_never_leaks_recursion_error() -> None:
    limits = replace(DEFAULT_VERIFICATION_LIMITS, json_nesting_depth=3)
    validate_json_resource_envelope(b'{"value":"[[[{{{"}', label="quoted", limits=limits)
    validate_json_resource_envelope(b"[[[0]]]", label="exact", limits=limits)

    with pytest.raises(ValueError, match=r"json_nesting_depth=3.*next action"):
        validate_json_resource_envelope(b"[[[[0]]]]", label="deep", limits=limits)


def test_json_structural_token_guard_precedes_json_decode() -> None:
    limits = replace(DEFAULT_VERIFICATION_LIMITS, json_structural_tokens=3)

    with pytest.raises(ValueError, match=r"json_structural_tokens=3.*next action"):
        validate_json_resource_envelope(b'{"a":[1,2]}', label="wide", limits=limits)


def test_public_terminal_attempt_limit_has_typed_reason_and_matching_next_action(
    golden_terminal: tuple[Path, dict[str, str]],
) -> None:
    root, anchors = golden_terminal
    limits = replace(GOLDEN_EXACT_LIMITS, terminal_attempts=2)

    with pytest.raises(AgenticTrustVerificationError) as raised:
        _verify(root, anchors, limits)

    assert raised.value.reason_code == "verification_resource_limit_exceeded"
    assert "higher limit policy" in raised.value.next_action


def test_standalone_receipt_parser_honors_caller_limit(
    anchored_projection,
) -> None:
    receipt = AgenticTrustEvidenceReceiptV1.from_verified_projection(anchored_projection)
    raw = receipt.to_bytes()
    limits = replace(DEFAULT_VERIFICATION_LIMITS, canonical_json_bytes=len(raw) - 1)

    with pytest.raises(ValueError, match=r"canonical_json_bytes=.*next action"):
        AgenticTrustEvidenceReceiptV1.parse_unverified(raw, limits=limits)
