"""Tests for durable public-gate receipt validation."""

from __future__ import annotations

from pathlib import Path

from shared.public_gate_receipts import public_gate_receipt_value_present

GATE = "rights_privacy_redaction_pass"


def _write(root: Path, name: str, text: str) -> None:
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def test_accepts_passed_yaml_receipt_with_extension_inferred(tmp_path: Path) -> None:
    _write(tmp_path, "receipt-1.yaml", f"gate_id: {GATE}\nstatus: passed\n")

    assert public_gate_receipt_value_present(
        "public-gate:receipt-1",
        expected_gate=GATE,
        roots=(tmp_path,),
    )


def test_accepts_receipt_with_matching_artifact_binding(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "receipt-1.yaml",
        f"gate_id: {GATE}\n"
        "status: passed\n"
        "artifact_slug: demo\n"
        "artifact_fingerprint: abc123\n"
        "target_surfaces:\n"
        "  - fake\n",
    )

    assert public_gate_receipt_value_present(
        "public-gate:receipt-1.yaml",
        expected_gate=GATE,
        roots=(tmp_path,),
        bindings={
            "artifact_slug": "demo",
            "artifact_fingerprint": "abc123",
            "target_surfaces": ("fake",),
        },
    )


def test_rejects_replayed_receipt_with_wrong_artifact_binding(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "receipt-1.yaml",
        f"gate_id: {GATE}\n"
        "status: passed\n"
        "artifact_slug: demo\n"
        "artifact_fingerprint: old-fingerprint\n"
        "target_surfaces:\n"
        "  - fake\n",
    )

    assert not public_gate_receipt_value_present(
        "public-gate:receipt-1.yaml",
        expected_gate=GATE,
        roots=(tmp_path,),
        bindings={
            "artifact_slug": "demo",
            "artifact_fingerprint": "new-fingerprint",
            "target_surfaces": ("fake",),
        },
    )


def test_rejects_spliced_gate_and_binding_records(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "receipt-1.yaml",
        f"old_gate_record:\n"
        f"  gate_id: {GATE}\n"
        "  status: passed\n"
        "current_binding_record:\n"
        "  artifact_slug: demo\n"
        "  artifact_fingerprint: abc123\n"
        "  target_surfaces:\n"
        "    - fake\n",
    )

    assert not public_gate_receipt_value_present(
        "public-gate:receipt-1.yaml",
        expected_gate=GATE,
        roots=(tmp_path,),
        bindings={
            "artifact_slug": "demo",
            "artifact_fingerprint": "abc123",
            "target_surfaces": ("fake",),
        },
    )


def test_rejects_list_sibling_gate_and_binding_records(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "receipt-1.yaml",
        "receipt_records:\n"
        f"  - gate_id: {GATE}\n"
        "    status: passed\n"
        "  - artifact_slug: demo\n"
        "    artifact_fingerprint: abc123\n"
        "    target_surfaces:\n"
        "      - fake\n",
    )

    assert not public_gate_receipt_value_present(
        "public-gate:receipt-1.yaml",
        expected_gate=GATE,
        roots=(tmp_path,),
        bindings={
            "artifact_slug": "demo",
            "artifact_fingerprint": "abc123",
            "target_surfaces": ("fake",),
        },
    )


def test_rejects_root_gate_with_nested_unrelated_binding_record(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "receipt-1.yaml",
        f"gate_id: {GATE}\n"
        "status: passed\n"
        "current_binding_record:\n"
        "  artifact_slug: demo\n"
        "  artifact_fingerprint: abc123\n"
        "  target_surfaces:\n"
        "    - fake\n",
    )

    assert not public_gate_receipt_value_present(
        "public-gate:receipt-1.yaml",
        expected_gate=GATE,
        roots=(tmp_path,),
        bindings={
            "artifact_slug": "demo",
            "artifact_fingerprint": "abc123",
            "target_surfaces": ("fake",),
        },
    )


def test_rejects_failed_receipt_outcome(tmp_path: Path) -> None:
    _write(tmp_path, "receipt-1.yaml", f"gate_id: {GATE}\nstatus: failed\n")

    assert not public_gate_receipt_value_present(
        "public-gate:receipt-1.yaml",
        expected_gate=GATE,
        roots=(tmp_path,),
    )


def test_rejects_false_passed_marker(tmp_path: Path) -> None:
    _write(tmp_path, "receipt-1.yaml", f"gate_id: {GATE}\npassed: false\n")

    assert not public_gate_receipt_value_present(
        "public-gate:receipt-1.yaml",
        expected_gate=GATE,
        roots=(tmp_path,),
    )


def test_rejects_gate_only_receipt_without_positive_outcome(tmp_path: Path) -> None:
    _write(tmp_path, "receipt-1.yaml", f"gate_id: {GATE}\n")

    assert not public_gate_receipt_value_present(
        "public-gate:receipt-1.yaml",
        expected_gate=GATE,
        roots=(tmp_path,),
    )


def test_rejects_positive_outcome_not_bound_to_gate_object(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "receipt-1.yaml",
        f"gate_id: {GATE}\nmetadata:\n  status: passed\n",
    )

    assert not public_gate_receipt_value_present(
        "public-gate:receipt-1.yaml",
        expected_gate=GATE,
        roots=(tmp_path,),
    )


def test_accepts_iterable_ref_and_markdown_frontmatter(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "receipt-1.md",
        f"---\nrequired_gates:\n  - {GATE}\nverdict: accepted\n---\n\nBody\n",
    )

    assert public_gate_receipt_value_present(
        ["placeholder", "public-gate:receipt-1.md"],
        expected_gate=GATE,
        roots=(tmp_path,),
    )


def test_accepts_direct_gate_mapping_with_positive_status(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "nested.yaml",
        f"gates:\n  {GATE}: passed\noutcome: approved\n",
    )

    assert public_gate_receipt_value_present(
        "public-gate:nested.yaml",
        expected_gate=GATE,
        roots=(tmp_path,),
    )


def test_rejects_direct_gate_key_with_failed_value(tmp_path: Path) -> None:
    _write(tmp_path, "receipt-1.yaml", f"{GATE}: failed\nstatus: passed\n")

    assert not public_gate_receipt_value_present(
        "public-gate:receipt-1.yaml",
        expected_gate=GATE,
        roots=(tmp_path,),
    )


def test_rejects_direct_gate_key_contradiction_with_matching_gate_id(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "receipt-1.yaml",
        f"gate_id: {GATE}\n{GATE}: failed\nstatus: passed\n",
    )

    assert not public_gate_receipt_value_present(
        "public-gate:receipt-1.yaml",
        expected_gate=GATE,
        roots=(tmp_path,),
    )


def test_rejects_nested_gate_key_with_failed_value(tmp_path: Path) -> None:
    _write(tmp_path, "receipt-1.yaml", f"gates:\n  {GATE}: failed\nstatus: passed\n")

    assert not public_gate_receipt_value_present(
        "public-gate:receipt-1.yaml",
        expected_gate=GATE,
        roots=(tmp_path,),
    )


def test_rejects_mapping_and_bytes_values(tmp_path: Path) -> None:
    _write(tmp_path, "receipt-1.yaml", f"gate_id: {GATE}\nstatus: passed\n")

    assert not public_gate_receipt_value_present(
        {"ref": "public-gate:receipt-1.yaml"},
        expected_gate=GATE,
        roots=(tmp_path,),
    )
    assert not public_gate_receipt_value_present(
        b"public-gate:receipt-1.yaml",
        expected_gate=GATE,
        roots=(tmp_path,),
    )


def test_rejects_unsupported_receipt_extension(tmp_path: Path) -> None:
    _write(tmp_path, "receipt-1.txt", f"gate_id: {GATE}\nstatus: passed\n")
    _write(tmp_path, "receipt-1.txt.yaml", f"gate_id: {GATE}\nstatus: passed\n")

    assert not public_gate_receipt_value_present(
        "public-gate:receipt-1.txt",
        expected_gate=GATE,
        roots=(tmp_path,),
    )


def test_rejects_root_escape_and_malformed_yaml(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-public-gate.yaml"
    outside.write_text(f"gate_id: {GATE}\nstatus: passed\n", encoding="utf-8")
    _write(tmp_path, "bad.yaml", f"gate_id: {GATE}\nstatus: [\n")

    assert not public_gate_receipt_value_present(
        "public-gate:../outside-public-gate.yaml",
        expected_gate=GATE,
        roots=(tmp_path,),
    )
    assert not public_gate_receipt_value_present(
        "public-gate:bad.yaml",
        expected_gate=GATE,
        roots=(tmp_path,),
    )
