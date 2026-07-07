"""Tests for durable public-gate receipt validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from shared import public_gate_receipts
from shared.public_gate_receipts import public_gate_receipt_value_present

GATE = "rights_privacy_redaction_pass"
TASK_ID = "cc-task-public-gate-test"
AUTHORITY_BLOCK = (
    "authority_case: CASE-PUBLIC-EGRESS-TEST\n"
    "acceptor: claim-verification-council\n"
    "review_profile: claim_verification_council_public_egress\n"
    f"evidence_ref: review-dossier:{TASK_ID}\n"
)


@pytest.fixture(autouse=True)
def trusted_authority_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    authority_root = tmp_path.parent / f"{tmp_path.name}-authority"
    authority_root.mkdir()
    monkeypatch.setattr(public_gate_receipts, "PUBLIC_GATE_AUTHORITY_ROOTS", (authority_root,))


def _write(root: Path, name: str, text: str) -> None:
    if f"evidence_ref: review-dossier:{TASK_ID}" in text:
        _write_review_evidence(root, receipt_name=name)
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _write_review_evidence(
    root: Path,
    *,
    receipt_name: str,
    gate: str = GATE,
    artifact_fingerprint: str = "abc123",
) -> None:
    del root
    public_gate_receipts.PUBLIC_GATE_AUTHORITY_ROOTS[0].mkdir(parents=True, exist_ok=True)
    (
        public_gate_receipts.PUBLIC_GATE_AUTHORITY_ROOTS[0] / f"{TASK_ID}.review-dossier.yaml"
    ).write_text(
        "dossier_schema: 1\n"
        f"task_id: {TASK_ID}\n"
        "head_sha: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        "review_team_verdict: quorum-accept\n"
        "quorum_required: 1\n"
        "accept_count: 1\n"
        f"gate_id: {gate}\n"
        "authorized_public_gate_receipts:\n"
        f"  - public-gate:{receipt_name}\n"
        "artifact_slug: demo\n"
        f"artifact_fingerprint: {artifact_fingerprint}\n"
        "target_surfaces:\n"
        "  - fake\n"
        "reviewers:\n"
        "  - id: cvc-1\n"
        "    family: cvc\n"
        "    verdict: accept\n",
        encoding="utf-8",
    )


def _receipt_text(*, gate: str = GATE, status: str = "passed", extra: str = "") -> str:
    return f"gate_id: {gate}\nstatus: {status}\n{AUTHORITY_BLOCK}{extra}"


def test_accepts_passed_yaml_receipt_with_extension_inferred(tmp_path: Path) -> None:
    _write(tmp_path, "receipt-1.yaml", _receipt_text())

    assert public_gate_receipt_value_present(
        "public-gate:receipt-1",
        expected_gate=GATE,
        roots=(tmp_path,),
    )


def test_rejects_self_minted_receipt_without_delegated_authority(tmp_path: Path) -> None:
    _write(tmp_path, "receipt-1.yaml", f"gate_id: {GATE}\nstatus: passed\n")

    assert not public_gate_receipt_value_present(
        "public-gate:receipt-1",
        expected_gate=GATE,
        roots=(tmp_path,),
    )


def test_rejects_unresolved_authority_evidence_ref(tmp_path: Path) -> None:
    (tmp_path / "receipt-1.yaml").write_text(_receipt_text(), encoding="utf-8")

    assert not public_gate_receipt_value_present(
        "public-gate:receipt-1",
        expected_gate=GATE,
        roots=(tmp_path,),
    )


def test_rejects_operator_accepted_receipt_without_independent_acceptor(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "receipt-1.yaml",
        _receipt_text().replace(
            "acceptor: claim-verification-council",
            "acceptor: operator",
        ),
    )

    assert not public_gate_receipt_value_present(
        "public-gate:receipt-1",
        expected_gate=GATE,
        roots=(tmp_path,),
    )


def test_rejects_circular_public_gate_evidence_ref(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "receipt-1.yaml",
        _receipt_text().replace(
            f"evidence_ref: review-dossier:{TASK_ID}",
            "evidence_ref: public-gate:self",
        ),
    )

    assert not public_gate_receipt_value_present(
        "public-gate:receipt-1",
        expected_gate=GATE,
        roots=(tmp_path,),
    )


def test_rejects_forged_review_dossier_in_receipt_root(tmp_path: Path) -> None:
    _write(tmp_path, "receipt-1.yaml", _receipt_text())
    (tmp_path / f"{TASK_ID}.review-dossier.yaml").write_text(
        "dossier_schema: 1\n"
        f"task_id: {TASK_ID}\n"
        "head_sha: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        "review_team_verdict: quorum-accept\n"
        "quorum_required: 1\n"
        "accept_count: 1\n"
        f"gate_id: {GATE}\n"
        "authorized_public_gate_receipts:\n"
        "  - public-gate:receipt-1.yaml\n"
        "reviewers:\n"
        "  - id: cvc-1\n"
        "    family: cvc\n"
        "    verdict: accept\n",
        encoding="utf-8",
    )
    (
        public_gate_receipts.PUBLIC_GATE_AUTHORITY_ROOTS[0] / f"{TASK_ID}.review-dossier.yaml"
    ).unlink()

    assert not public_gate_receipt_value_present(
        "public-gate:receipt-1.yaml",
        expected_gate=GATE,
        roots=(tmp_path,),
    )


def test_rejects_authority_evidence_for_different_gate(tmp_path: Path) -> None:
    _write(tmp_path, "receipt-1.yaml", _receipt_text())
    _write_review_evidence(
        tmp_path,
        receipt_name="receipt-1.yaml",
        gate="claim_review_current",
    )

    assert not public_gate_receipt_value_present(
        "public-gate:receipt-1.yaml",
        expected_gate=GATE,
        roots=(tmp_path,),
    )


def test_rejects_authority_evidence_for_different_receipt(tmp_path: Path) -> None:
    _write(tmp_path, "receipt-1.yaml", _receipt_text())
    _write_review_evidence(tmp_path, receipt_name="receipt-2.yaml")

    assert not public_gate_receipt_value_present(
        "public-gate:receipt-1.yaml",
        expected_gate=GATE,
        roots=(tmp_path,),
    )


def test_rejects_authority_evidence_for_different_artifact_binding(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "receipt-1.yaml",
        _receipt_text(
            extra=(
                "artifact_slug: demo\nartifact_fingerprint: abc123\ntarget_surfaces:\n  - fake\n"
            )
        ),
    )
    _write_review_evidence(
        tmp_path,
        receipt_name="receipt-1.yaml",
        artifact_fingerprint="stale-fingerprint",
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


def test_rejects_review_dossier_without_current_head_binding(tmp_path: Path) -> None:
    _write(tmp_path, "receipt-1.yaml", _receipt_text())
    (
        public_gate_receipts.PUBLIC_GATE_AUTHORITY_ROOTS[0] / f"{TASK_ID}.review-dossier.yaml"
    ).write_text(
        "dossier_schema: 1\n"
        f"task_id: {TASK_ID}\n"
        "review_team_verdict: quorum-accept\n"
        "quorum_required: 1\n"
        "accept_count: 1\n"
        f"gate_id: {GATE}\n"
        "authorized_public_gate_receipts:\n"
        "  - public-gate:receipt-1.yaml\n"
        "reviewers:\n"
        "  - id: cvc-1\n"
        "    family: cvc\n"
        "    verdict: accept\n",
        encoding="utf-8",
    )

    assert not public_gate_receipt_value_present(
        "public-gate:receipt-1.yaml",
        expected_gate=GATE,
        roots=(tmp_path,),
    )


def test_accepts_receipt_with_matching_artifact_binding(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "receipt-1.yaml",
        _receipt_text(
            extra=(
                "artifact_slug: demo\nartifact_fingerprint: abc123\ntarget_surfaces:\n  - fake\n"
            )
        ),
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
        _receipt_text(
            extra=(
                "artifact_slug: demo\n"
                "artifact_fingerprint: old-fingerprint\n"
                "target_surfaces:\n"
                "  - fake\n"
            )
        ),
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
        _receipt_text(
            extra=(
                "current_binding_record:\n"
                "  artifact_slug: demo\n"
                "  artifact_fingerprint: abc123\n"
                "  target_surfaces:\n"
                "    - fake\n"
            )
        ),
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
        f"gate_id: {GATE}\n{AUTHORITY_BLOCK}metadata:\n  status: passed\n",
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
        f"---\nrequired_gates:\n  - {GATE}\nverdict: accepted\n{AUTHORITY_BLOCK}---\n\nBody\n",
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
        f"gates:\n  {GATE}: passed\noutcome: approved\n{AUTHORITY_BLOCK}",
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
    _write(tmp_path, "receipt-1.yaml", _receipt_text())

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
    _write(tmp_path, "receipt-1.txt", _receipt_text())
    _write(tmp_path, "receipt-1.txt.yaml", _receipt_text())

    assert not public_gate_receipt_value_present(
        "public-gate:receipt-1.txt",
        expected_gate=GATE,
        roots=(tmp_path,),
    )


def test_rejects_root_escape_and_malformed_yaml(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-public-gate.yaml"
    outside.write_text(_receipt_text(), encoding="utf-8")
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
