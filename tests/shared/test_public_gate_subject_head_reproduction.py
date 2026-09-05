"""Round-one witness: a reviewed PR subject and an executing release differ.

All review inputs, keys, artifacts, and receipts are synthetic. Only producer
helpers and consumer checks run; no dispatcher, publisher, or daemon is started.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock, call

import pytest
import yaml
from prometheus_client import CollectorRegistry

from agents.publish_orchestrator import orchestrator
from scripts import publish_vault_artifact as publisher
from shared import public_gate_receipts
from shared.preprint_artifact import ApprovalState, PreprintArtifact
from shared.publication_hardening.gate import PublicationGateDecision

SUBJECT_HEAD = "a" * 40
EXECUTING_HEAD = "b" * 40
TASK_ID = "synthetic-public-gate-subject-head"
AUTHORITY_KEY = "synthetic-subject-head-hmac-key"  # pragma: allowlist secret
GATES = (
    "source_artifact_public_safe",
    "source_refs_present",
    "rights_privacy_redaction_pass",
    "target_surface_allowlist_pass",
    "claim_review_current",
    "no_direct_public_egress",
)
PUBLISHER_REASON = (
    "publication_gate_receipts missing, invalid, or not bound to "
    "artifact_slug, artifact_fingerprint, and target_surfaces for required receipt refs: "
    "claim_review_current, no_direct_public_egress, rights_privacy_redaction_pass, "
    "source_artifact_public_safe, source_refs_present, target_surface_allowlist_pass; "
    "next action: hold the draft until durable public-gate receipt refs are recorded"
)
ORCHESTRATOR_REASON = (
    "publication_gate_receipts missing or invalid required receipt refs: "
    "source_artifact_public_safe, source_refs_present, rights_privacy_redaction_pass, "
    "target_surface_allowlist_pass, claim_review_current, no_direct_public_egress; "
    "next action: hold the artifact until durable public-gate receipt refs "
    "bound to artifact_slug, artifact_fingerprint, and target_surfaces are recorded"
)


@dataclass(frozen=True)
class AcceptedDossier:
    artifact: PreprintArtifact
    frontmatter: dict
    receipt_root: Path
    dossier_path: Path


@pytest.fixture
def accepted_dossier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AcceptedDossier:
    receipt_root = tmp_path / "receipts"
    authority_root = tmp_path / "authority"
    receipt_root.mkdir()
    authority_root.mkdir()
    monkeypatch.setenv(public_gate_receipts.PUBLIC_GATE_AUTHORITY_SECRET_ENV, AUTHORITY_KEY)
    monkeypatch.setenv(public_gate_receipts.PUBLIC_GATE_AUTHORITY_ROOTS_ENV, str(authority_root))
    monkeypatch.setattr(publisher, "PUBLIC_GATE_RECEIPT_ROOTS", (receipt_root,))

    # Import the real dispatcher without invoking its CLI or review runners.
    module_name = "cc_pr_review_dispatch_subject_head_reproduction"
    spec = importlib.util.spec_from_file_location(
        module_name, publisher.REPO_ROOT / "scripts/cc-pr-review-dispatch.py"
    )
    assert spec is not None and spec.loader is not None
    dispatch = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, dispatch)
    spec.loader.exec_module(dispatch)

    artifact = PreprintArtifact(
        slug="synthetic-subject-head",
        title="Synthetic subject head",
        abstract="Synthetic accepted artifact.",
        body_md="Synthetic body.",
        attribution_block="Synthetic attribution.",
        surfaces_targeted=["omg-weblog"],
    )
    bindings = publisher._publication_gate_receipt_bindings(artifact)
    assert bindings == orchestrator._publication_gate_receipt_bindings(artifact)
    receipts = {gate: f"public-gate:{gate}.yaml" for gate in GATES}
    frontmatter = {
        "Publication-Allowed": True,
        "slug": artifact.slug,
        "title": artifact.title,
        "abstract": artifact.abstract,
        "attribution_block": artifact.attribution_block,
        "publication_gate_receipts": receipts,
    }
    artifact.publication_gate_context = {"publication_gate_receipts": receipts}
    api_runner = Mock(
        return_value=subprocess.CompletedProcess(
            [], 0, stdout=json.dumps({"number": 1, "headRefOid": SUBJECT_HEAD}), stderr=""
        )
    )
    pr = dispatch._fetch_pr_via_view(
        1, repo="synthetic/repository", repo_root=tmp_path, runner=api_runner
    )
    assert pr.head_sha == SUBJECT_HEAD
    dossier = dispatch.review_team.synthesize_dossier(
        task_id=TASK_ID,
        pr_number=pr.number,
        head_sha=pr.head_sha,
        team_class="synthetic",
        registry={
            "families": [{"family": family} for family in ("claude", "codex")],
            "sizing": {"synthetic": {"quorum_accept": 2, "min_families": 2}},
        },
        reviews=[
            {"id": family, "family": family, "verdict": "accept", "checklist": {}}
            for family in ("claude", "codex")
        ],
        lenses=(),
        constituted_at="2026-09-05T00:00:00Z",
    )
    dispatch._apply_public_gate_authority_context(
        dossier,
        {"public_gate_authority": {"publication_gate_receipts": receipts, **bindings}},
    )
    dispatch._sign_public_gate_authority_evidence(dossier)
    assert dossier["review_team_verdict"] == "quorum-accept"
    assert dossier["accept_count"] == dossier["quorum_required"] == 2
    assert dossier["authority_issuer"] == "review-team:claude,codex"
    assert dossier["authority_signature"] == public_gate_receipts.public_gate_authority_signature(
        dossier, AUTHORITY_KEY
    )
    dossier_path = authority_root / f"{TASK_ID}.review-dossier.yaml"
    dossier_path.write_text(yaml.safe_dump(dossier), encoding="utf-8")
    for gate in GATES:
        receipt = {
            "gate_id": gate,
            "status": "passed",
            "authority_case": "CASE-SYNTHETIC-SUBJECT-HEAD",
            "acceptor": dossier["authority_issuer"],
            "review_profile": "claim_verification_council_public_egress",
            "evidence_ref": f"review-dossier:{TASK_ID}",
            **bindings,
        }
        (receipt_root / f"{gate}.yaml").write_text(yaml.safe_dump(receipt), encoding="utf-8")
    return AcceptedDossier(artifact, frontmatter, receipt_root, dossier_path)


def _consumer(accepted: AcceptedDossier, head: str | None = None) -> orchestrator.Orchestrator:
    return orchestrator.Orchestrator(
        state_root=accepted.receipt_root.parent / "state",
        surface_registry={},
        public_event_path=None,
        public_gate_receipt_roots=(accepted.receipt_root,),
        public_gate_expected_head_sha=head,
        registry=CollectorRegistry(),
    )


def test_accepted_pr_head_dossier_is_refused_at_a_different_executing_head(
    accepted_dossier: AcceptedDossier,
) -> None:
    """Reproduction: accepted PR head A fails both real consumers executing at B."""
    accepted = accepted_dossier
    assert SUBJECT_HEAD != EXECUTING_HEAD
    original = accepted.dossier_path.read_bytes()
    bindings = publisher._publication_gate_receipt_bindings(accepted.artifact)
    # Hold every receipt and binding constant; only the caller's head changes.
    for gate, receipt in accepted.frontmatter["publication_gate_receipts"].items():
        for head, expected in ((SUBJECT_HEAD, True), (EXECUTING_HEAD, False)):
            assert (
                public_gate_receipts.public_gate_receipt_value_present(
                    receipt,
                    expected_gate=gate,
                    roots=(accepted.receipt_root,),
                    bindings=bindings,
                    expected_head_sha=head,
                )
                is expected
            )
    with pytest.raises(publisher.PublicationGateError) as refused:
        publisher._assert_publication_gate_receipts(
            accepted.frontmatter,
            accepted.artifact.surfaces_targeted,
            bindings=bindings,
            expected_head_sha=EXECUTING_HEAD,
        )
    assert str(refused.value) == PUBLISHER_REASON
    result = _consumer(accepted, EXECUTING_HEAD)._public_gate_receipts_gate_result(
        accepted.artifact
    )
    assert result.decision == PublicationGateDecision.HOLD
    assert not result.passes()
    assert result.child_results[0].findings == (ORCHESTRATOR_REASON,)
    assert result.flagged_issues == (f"public_gate_receipts: {ORCHESTRATOR_REASON}",)
    assert accepted.dossier_path.read_bytes() == original
    print("shared: six identical bound receipts validate at A=True, B=False")
    print(f"publisher PublicationGateError: {refused.value}")
    print(f"orchestrator hold: {result.child_results[0].findings[0]}")
    print(f"orchestrator flagged issue: {result.flagged_issues[0]}")


def test_accepted_pr_head_dossier_positive_control_records_no_reviewed_subject(
    accepted_dossier: AcceptedDossier, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same signed dossier passes at A; acceptance outputs carry no subject identity."""
    accepted = accepted_dossier
    monkeypatch.setattr(publisher, "_current_repo_head_sha", lambda: SUBJECT_HEAD)
    assert (
        publisher._assert_publication_gate_receipts(
            accepted.frontmatter,
            accepted.artifact.surfaces_targeted,
            bindings=publisher._publication_gate_receipt_bindings(accepted.artifact),
            expected_head_sha=SUBJECT_HEAD,
        )
        is None
    )
    artifact = publisher._build_artifact(
        body_md=accepted.artifact.body_md,
        frontmatter=accepted.frontmatter,
        surfaces=accepted.artifact.surfaces_targeted,
        approver="Oudepode",
    )
    assert artifact.approval == ApprovalState.APPROVED
    result = _consumer(accepted, SUBJECT_HEAD)._public_gate_receipts_gate_result(artifact)
    assert result.decision == PublicationGateDecision.PASS
    assert result.passes()
    assert result.child_results[0].findings == ()
    assert result.child_results[0].evidence_refs == tuple(
        accepted.frontmatter["publication_gate_receipts"].values()
    )
    assert artifact.publication_gate_result is None
    for payload in (artifact.model_dump_json(), result.model_dump_json()):
        assert SUBJECT_HEAD not in payload
        assert EXECUTING_HEAD not in payload
        assert "head_sha" not in payload
    print("positive control: publisher=None; built artifact=approved; orchestrator=pass")
    print("acceptance results: receipt refs retained; reviewed A and executing B absent")


def test_executing_release_head_is_observed_separately_from_reviewed_subject(
    accepted_dossier: AcceptedDossier, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both default consumers observe checkout B via git; the signed subject remains A."""
    accepted = accepted_dossier
    git_run = Mock(
        return_value=subprocess.CompletedProcess([], 0, stdout=f"{EXECUTING_HEAD}\n", stderr="")
    )
    monkeypatch.setattr(subprocess, "run", git_run)
    assert publisher._current_repo_head_sha() == EXECUTING_HEAD
    assert orchestrator._current_repo_head_sha() == EXECUTING_HEAD
    assert git_run.call_args_list == [
        call(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=module.REPO_ROOT,
            capture_output=True,
            check=False,
            text=True,
        )
        for module in (publisher, orchestrator)
    ]
    consumer = _consumer(accepted)
    assert consumer._public_gate_expected_head_sha == EXECUTING_HEAD
    result = consumer._public_gate_receipts_gate_result(accepted.artifact)
    assert result.decision == PublicationGateDecision.HOLD
    assert result.child_results[0].findings == (ORCHESTRATOR_REASON,)
    with pytest.raises(publisher.PublicationGateError) as refused:
        publisher._build_artifact(
            body_md=accepted.artifact.body_md,
            frontmatter=accepted.frontmatter,
            surfaces=accepted.artifact.surfaces_targeted,
            approver="Oudepode",
        )
    assert str(refused.value) == PUBLISHER_REASON
    assert yaml.safe_load(accepted.dossier_path.read_text())["head_sha"] == SUBJECT_HEAD
    assert SUBJECT_HEAD not in result.model_dump_json()
    assert EXECUTING_HEAD not in result.model_dump_json()
    print("checkout observation: both git rev-parse --verify HEAD helpers return B")
    print("default consumers: publisher refuses; orchestrator expected=B, decision=hold")
    print("signed subject remains A; no subject or executing SHA in gate result")
