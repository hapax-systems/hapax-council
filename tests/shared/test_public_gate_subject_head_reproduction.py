"""Round-one witness: a reviewed PR subject and an executing release differ.

All review inputs, keys, artifacts, and receipts are synthetic. Only producer
helpers and consumer checks run; no dispatcher, publisher, or daemon is started.
"""

from __future__ import annotations

import hashlib
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
    monkeypatch.setattr(orchestrator, "_current_repo_head_sha", lambda: SUBJECT_HEAD)
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


@pytest.fixture
def transfer_seat(accepted_dossier, monkeypatch):
    """Synthetic authenticated API and immutable objects; every unexpected action fails."""
    accepted = accepted_dossier
    dispatch = sys.modules["cc_pr_review_dispatch_subject_head_reproduction"]
    dossier = yaml.safe_load(accepted.dossier_path.read_text())
    dossier.update(repository="synthetic/repository", artifact_git_path="drafts/synthetic.md")
    dispatch._sign_public_gate_authority_evidence(dossier)
    accepted.dossier_path.write_text(yaml.safe_dump(dossier))
    markdown = "---\n" + yaml.safe_dump(accepted.frontmatter) + "---\n" + accepted.artifact.body_md
    state = {
        "head": EXECUTING_HEAD,
        "dirty": "",
        "repo": "synthetic/repository",
        "method": "merge",
        "a_text": markdown,
        "b_text": markdown,
        "record": {
            "number": 1,
            "merged": True,
            "merged_at": "2026-09-05T01:00:00Z",
            "head": {"sha": SUBJECT_HEAD},
            "merge_commit_sha": EXECUTING_HEAD,
            "base": {"repo": {"full_name": "synthetic/repository"}},
        },
    }

    def runner(cmd, **kwargs):
        if cmd[:3] == ["git", "--no-optional-locks", "--no-replace-objects"]:
            cmd = ["git", *cmd[3:]]
        if cmd[:3] == ["gh", "pr", "view"]:
            output = json.dumps({"number": 1, "headRefOid": SUBJECT_HEAD})
        elif cmd[0] == "gh" and "repos/synthetic/repository/pulls/1" in cmd:
            output = json.dumps(state["record"])
        elif cmd == ["git", "remote", "get-url", "origin"]:
            output = "https://github.com/" + state["repo"] + ".git"
        elif cmd == ["git", "status", "--porcelain", "--untracked-files=all"]:
            output = state["dirty"]
        elif cmd == ["git", "rev-parse", "--verify", "HEAD"]:
            output = state["head"] or ""
        elif cmd[:3] == ["git", "cat-file", "blob"]:
            assert cmd[3] == "d" * 40
            if state.get("missing_blob"):
                return subprocess.CompletedProcess(
                    cmd, 1, stdout="", stderr="synthetic missing blob"
                )
            output = state["a_text"]
        elif cmd[:3] == ["git", "cat-file", "commit"]:
            if cmd[3] in state.get("extra_commits", {}):
                return subprocess.CompletedProcess(
                    cmd, 0, stdout=state["extra_commits"][cmd[3]], stderr=""
                )
            assert cmd[3] == EXECUTING_HEAD
            parents = ["c" * 40, SUBJECT_HEAD] if state["method"] == "merge" else ["c" * 40]
            output = (
                "tree "
                + "d" * 40
                + "\n"
                + "".join("parent " + p + "\n" for p in state.get("parents", parents))
                + "\nSynthetic commit"
            )
        elif cmd[:2] == ["git", "show"]:
            assert cmd[2] in (
                SUBJECT_HEAD + ":drafts/synthetic.md",
                EXECUTING_HEAD + ":drafts/synthetic.md",
            )
            output = state["a_text"] if cmd[2].startswith(SUBJECT_HEAD) else state["b_text"]
        else:
            pytest.fail(f"unexpected external action: {cmd}")
        return subprocess.CompletedProcess(cmd, 0, stdout=output, stderr="")

    monkeypatch.setattr(subprocess, "run", runner)
    state["runner"] = runner
    state["dispatch"] = dispatch
    state["accepted"] = accepted
    return state


def _issue_transfer(seat, *, apply=True):
    return seat["dispatch"].transfer_acceptance(
        1,
        repo="synthetic/repository",
        repo_root=publisher.REPO_ROOT,
        dossier_name=seat["accepted"].dossier_path.name,
        apply=apply,
        runner=seat["runner"],
        receipt_roots=(seat["accepted"].receipt_root,),
    )


def _install_transfer(seat):
    issued = _issue_transfer(seat)
    assert issued["status"] == "transferred", issued
    context = {"acceptance_transfer": issued["transfer"], "publication_pr": 1}
    accepted = seat["accepted"]
    accepted.frontmatter["publication_gate_context"] = context
    accepted.artifact.publication_gate_context.update(context)
    return context


def _both_transfer_consumers(seat):
    accepted = seat["accepted"]
    try:
        built = publisher._build_artifact(
            body_md=accepted.artifact.body_md,
            frontmatter=accepted.frontmatter,
            surfaces=accepted.artifact.surfaces_targeted,
            approver="Oudepode",
        )
        publisher_result = built
    except publisher.PublicationGateError as exc:
        publisher_result = str(exc)
    result = _consumer(accepted, SUBJECT_HEAD)._public_gate_receipts_gate_result(accepted.artifact)
    return publisher_result, result


@pytest.mark.parametrize("method", ["merge", "squash"])
def test_signed_transfer_positive_control_both_real_consumers(transfer_seat, method):
    seat = transfer_seat
    seat["method"] = method
    context = _install_transfer(seat)
    built, result = _both_transfer_consumers(seat)
    assert isinstance(built, PreprintArtifact), built
    assert result.passes(), result
    report = result.child_results[0].report
    assert report["reviewed_subject"]["head_sha"] == SUBJECT_HEAD
    assert report["executing_release"]["head_sha"] == EXECUTING_HEAD
    assert report["transfer_evidence"]["provenance"]["merge_method"] == method
    assert json.loads(
        json.dumps(built.publication_gate_context["acceptance_transfer_result"])
    ) == json.loads(json.dumps(report))
    assert report["transfer_evidence"] == context["acceptance_transfer"]
    assert SUBJECT_HEAD not in " ".join(result.child_results[0].evidence_refs)
    assert EXECUTING_HEAD not in " ".join(result.child_results[0].evidence_refs)
    assert built.approval == ApprovalState.APPROVED


@pytest.mark.parametrize(
    ("boundary", "reason"),
    [
        ("mismatched_b", "transfer_authorizes_exact_commit_only:" + EXECUTING_HEAD),
        ("descendant", "transfer_authorizes_exact_commit_only:" + EXECUTING_HEAD),
        ("unobserved", "transfer_execution_identity_unobserved"),
        ("wrong_key", "transfer_signature_or_domain_invalid"),
        ("wrong_domain", "transfer_signature_or_domain_invalid"),
        ("digest", "transfer_dossier_digest_mismatch"),
        ("missing_digest", "transfer_dossier_digest_missing_or_malformed"),
        ("wrong_repo", "transfer_repository_mismatch"),
        ("wrong_pr", "transfer_pr_mismatch"),
        ("dirty", "transfer_dirty_checkout"),
        ("kind", "transfer_kind_or_schema_invalid"),
        ("malformed", "transfer_missing_or_malformed"),
        ("ambiguous", "transfer_ambiguous"),
        ("artifact", "transfer_artifact_binding_mismatch"),
        ("targets", "transfer_artifact_binding_mismatch"),
        ("substitution", "transfer_dossier_digest_mismatch"),
        ("missing_dossier", "transfer_dossier_missing_or_ambiguous"),
        ("stale_result", "transfer_stale_result_identity"),
        ("immutable_b", "transfer_execution_artifact_mismatch"),
        ("receipts", "transfer_receipts_mismatch"),
        ("provenance", "transfer_provenance_invalid"),
        ("dossier_signature", "transfer_dossier_signature_invalid"),
        ("dossier_head", "transfer_dossier_acceptance_invalid:"),
        ("dossier_quorum", "transfer_dossier_acceptance_invalid:"),
        ("bound_receipt", "transfer_bound_receipt_invalid:"),
        ("artifact_source", "transfer_artifact_source_mismatch"),
        ("result_without_transfer", "transfer_missing_or_malformed"),
    ],
)
def test_transfer_consumer_trust_boundary(transfer_seat, boundary, reason):
    seat = transfer_seat
    context = _install_transfer(seat)
    accepted = seat["accepted"]
    transfer = context["acceptance_transfer"]
    if boundary in {"mismatched_b", "descendant"}:
        seat["head"] = "e" * 40
        if boundary == "descendant":
            seat["extra_commits"] = {
                seat["head"]: "tree "
                + "d" * 40
                + "\nparent "
                + EXECUTING_HEAD
                + "\n\nSynthetic descendant"
            }
            commit = public_gate_receipts.transfer_git_data(
                publisher.REPO_ROOT, "cat-file", "commit", seat["head"]
            )
            assert "parent " + EXECUTING_HEAD in commit.split("\n\n", 1)[0]
    elif boundary == "unobserved":
        seat["head"] = None
    elif boundary == "wrong_key":
        key = "synthetic-forged-transfer-key"  # pragma: allowlist secret
        transfer["transfer_signature"] = public_gate_receipts.acceptance_transfer_signature(
            transfer, key
        )
    elif boundary == "wrong_domain":
        transfer["transfer_signature"] = public_gate_receipts.public_gate_authority_signature(
            {key: value for key, value in transfer.items() if key != "transfer_signature"},
            AUTHORITY_KEY,
        )
    elif boundary == "digest":
        transfer["dossier_digest"] = "sha256:" + "0" * 64
    elif boundary == "missing_digest":
        transfer.pop("dossier_digest")
    elif boundary == "wrong_repo":
        transfer["repository"] = "synthetic/elsewhere"
    elif boundary == "wrong_pr":
        transfer["pr"] = 2
    elif boundary == "dirty":
        seat["dirty"] = " M drafts/synthetic.md"
    elif boundary == "kind":
        transfer["kind"] = "review-dossier"
    elif boundary == "malformed":
        context["acceptance_transfer"] = None
    elif boundary == "ambiguous":
        context["acceptance_transfer"] = [transfer, transfer]
    elif boundary == "artifact":
        accepted.artifact.body_md += " Tampered."
    elif boundary == "targets":
        accepted.artifact.surfaces_targeted.append("mastodon-post")
    elif boundary == "substitution":
        accepted.dossier_path.write_text(
            accepted.dossier_path.read_text() + "\n# substituted bytes\n"
        )
    elif boundary == "missing_dossier":
        accepted.dossier_path.unlink()
    elif boundary == "stale_result":
        context["acceptance_transfer_result"] = {"executing_release": {"head_sha": SUBJECT_HEAD}}
    elif boundary == "immutable_b":
        seat["b_text"] += " Tampered."
    elif boundary == "receipts":
        transfer["receipts"] = {}
    elif boundary == "provenance":
        transfer["provenance"]["merged"] = False
    elif boundary in {"dossier_signature", "dossier_quorum"}:
        dossier = yaml.safe_load(accepted.dossier_path.read_text())
        if boundary == "dossier_signature":
            dossier["authority_signature"] = "hmac-sha256:" + "0" * 64
        else:
            dossier["review_team_verdict"] = "no-quorum"
            seat["dispatch"]._sign_public_gate_authority_evidence(dossier)
        accepted.dossier_path.write_text(yaml.safe_dump(dossier))
        transfer["dossier_digest"] = (
            "sha256:" + hashlib.sha256(accepted.dossier_path.read_bytes()).hexdigest()
        )
    elif boundary == "dossier_head":
        transfer["subject_head_sha"] = "f" * 40
    elif boundary == "bound_receipt":
        path = accepted.receipt_root / (GATES[0] + ".yaml")
        receipt = yaml.safe_load(path.read_text())
        receipt["status"] = "failed"
        path.write_text(yaml.safe_dump(receipt))
    elif boundary == "artifact_source":
        transfer["artifact_source"]["git_path"] = "another.md"
    elif boundary == "result_without_transfer":
        context.pop("acceptance_transfer")
        accepted.artifact.publication_gate_context.pop("acceptance_transfer")
        context["acceptance_transfer_result"] = {}
    if boundary not in {"wrong_key", "wrong_domain"}:
        transfer["transfer_signature"] = public_gate_receipts.acceptance_transfer_signature(
            transfer, AUTHORITY_KEY
        )
    accepted.artifact.publication_gate_context.update(context)
    built, result = _both_transfer_consumers(seat)
    assert isinstance(built, str), boundary
    assert reason in built
    assert not result.passes(), boundary
    assert reason in result.child_results[0].findings[0]
    assert "next action:" in built
    assert "next action:" in result.child_results[0].findings[0]
    # Exercise the real dispatch boundary, including its retry entry point.
    consumer = _consumer(accepted, SUBJECT_HEAD)
    consumer._withhold_for_gate = Mock()
    consumer._hardening_gate = Mock()
    pool = Mock()
    consumer._dispatch(accepted.artifact, pool=pool)
    consumer._withhold_for_gate.assert_called_once()
    consumer._hardening_gate.evaluate.assert_not_called()
    pool.submit.assert_not_called()


def test_caller_supplied_subject_without_transfer_stays_refused(transfer_seat):
    seat = transfer_seat
    accepted = seat["accepted"]
    accepted.frontmatter["release_head_sha"] = SUBJECT_HEAD
    built, result = _both_transfer_consumers(seat)
    assert isinstance(built, str)
    assert not result.passes()
    with pytest.raises(publisher.PublicationGateError):
        publisher._assert_publication_gate_receipts(
            accepted.frontmatter,
            accepted.artifact.surfaces_targeted,
            bindings=publisher._publication_gate_receipt_bindings(accepted.artifact),
            expected_head_sha=SUBJECT_HEAD,
        )


@pytest.mark.parametrize(
    ("boundary", "reason"),
    [
        ("record_head", "transfer_merge_record_head_mismatch"),
        ("record_repo", "transfer_merge_record_repository_or_pr_mismatch"),
        ("record_pr", "transfer_merge_record_repository_or_pr_mismatch"),
        ("not_merged", "transfer_pr_not_merged"),
        ("parents", "transfer_merge_parent_relation_invalid"),
        ("signature", "transfer_dossier_signature_invalid"),
        ("artifact_b", "transfer_artifact_fingerprint_mismatch:" + EXECUTING_HEAD),
        ("mutable_vault", "missing_immutable_artifact_object:"),
        ("dossier_repo", "transfer_dossier_repository_mismatch"),
        ("dossier_pr", "transfer_dossier_pr_mismatch"),
        ("quorum", "transfer_bound_receipt_invalid:"),
        ("receipt", "transfer_bound_receipt_invalid:"),
        ("transfer_of_transfer", "transfer_subject_must_be_dossier"),
    ],
)
def test_transfer_issuer_provenance_boundary(transfer_seat, boundary, reason):
    seat = transfer_seat
    accepted = seat["accepted"]
    dossier = yaml.safe_load(accepted.dossier_path.read_text())
    if boundary == "record_head":
        seat["record"]["head"]["sha"] = "e" * 40
    elif boundary == "record_repo":
        seat["record"]["base"]["repo"]["full_name"] = "synthetic/elsewhere"
    elif boundary == "record_pr":
        seat["record"]["number"] = 2
    elif boundary == "not_merged":
        seat["record"]["merged"] = False
    elif boundary == "parents":
        seat["parents"] = ["c" * 40, "d" * 40]
    elif boundary == "signature":
        dossier["authority_signature"] = "hmac-sha256:" + "0" * 64
    elif boundary == "artifact_b":
        seat["b_text"] += " Tampered."
    elif boundary == "mutable_vault":
        dossier.pop("artifact_git_path")
        dossier["source_path"] = "vault/synthetic-mutable-note.md"
    elif boundary == "dossier_repo":
        dossier["repository"] = "synthetic/elsewhere"
    elif boundary == "dossier_pr":
        dossier["pr"] = 2
    elif boundary == "quorum":
        dossier["review_team_verdict"] = "no-quorum"
    elif boundary == "receipt":
        receipt = accepted.receipt_root / (GATES[0] + ".yaml")
        data = yaml.safe_load(receipt.read_text())
        data["status"] = "failed"
        receipt.write_text(yaml.safe_dump(data))
    elif boundary == "transfer_of_transfer":
        dossier.update(kind=public_gate_receipts.PUBLIC_GATE_TRANSFER_KIND, transfer_schema=1)
    if boundary != "signature":
        seat["dispatch"]._sign_public_gate_authority_evidence(dossier)
    accepted.dossier_path.write_text(yaml.safe_dump(dossier))
    result = _issue_transfer(seat)
    assert result["status"] == "refused", result
    assert reason in result["reason"]
    assert "next action:" in result["reason"]


def test_transfer_presented_as_acceptance_is_refused(transfer_seat):
    seat = transfer_seat
    context = _install_transfer(seat)
    dossier = yaml.safe_load(seat["accepted"].dossier_path.read_text())
    # Even a dual-shaped record signed in the old domain cannot be an acceptance.
    dossier.update(kind=context["acceptance_transfer"]["kind"], transfer_schema=1)
    seat["dispatch"]._sign_public_gate_authority_evidence(dossier)
    seat["accepted"].dossier_path.write_text(yaml.safe_dump(dossier))
    seat["accepted"].frontmatter.pop("publication_gate_context")
    seat["accepted"].artifact.publication_gate_context.pop("acceptance_transfer")
    seat["head"] = SUBJECT_HEAD
    built, result = _both_transfer_consumers(seat)
    assert isinstance(built, str)
    assert not result.passes()


def test_transfer_issuer_plan_has_no_authority(transfer_seat):
    result = _issue_transfer(transfer_seat, apply=False)
    assert result["status"] == "plan"
    assert "transfer_signature" not in result["transfer"]


@pytest.mark.parametrize("gate", GATES)
def test_transfer_requires_each_of_six_bound_receipts(transfer_seat, gate):
    seat = transfer_seat
    _install_transfer(seat)
    path = seat["accepted"].receipt_root / (gate + ".yaml")
    receipt = yaml.safe_load(path.read_text())
    receipt["artifact_fingerprint"] = "altered"
    path.write_text(yaml.safe_dump(receipt))
    built, result = _both_transfer_consumers(seat)
    assert isinstance(built, str)
    assert "transfer_bound_receipt_invalid:" + gate in built
    assert not result.passes()
    assert "transfer_bound_receipt_invalid:" + gate in result.child_results[0].findings[0]


def test_transfer_cannot_skip_additional_surface_policy_gate(transfer_seat, monkeypatch):
    seat = transfer_seat
    _install_transfer(seat)
    required = (*GATES, "fanout_loop_prevention_present")
    monkeypatch.setattr(publisher, "_required_publication_gate_receipts", lambda surfaces: required)
    monkeypatch.setattr(
        orchestrator.Orchestrator,
        "_required_publication_gate_receipts",
        lambda self, surfaces: (required, None),
    )
    built, result = _both_transfer_consumers(seat)
    assert isinstance(built, str)
    assert "transfer_policy_gates_not_covered" in built
    assert not result.passes()
    assert "transfer_policy_gates_not_covered" in result.child_results[0].findings[0]


def test_vault_transfer_uses_immutable_blob_only(transfer_seat):
    seat = transfer_seat
    accepted = seat["accepted"]
    dossier = yaml.safe_load(accepted.dossier_path.read_text())
    dossier.pop("artifact_git_path")
    dossier["artifact_blob_oid"] = "d" * 40
    dossier["source_path"] = "vault/synthetic-mutable-note.md"
    seat["dispatch"]._sign_public_gate_authority_evidence(dossier)
    accepted.dossier_path.write_text(yaml.safe_dump(dossier))
    _install_transfer(seat)
    built, result = _both_transfer_consumers(seat)
    assert isinstance(built, PreprintArtifact), built
    assert result.passes()
    seat["missing_blob"] = True
    refused = _issue_transfer(seat)
    assert refused["status"] == "refused"
    assert "transfer_git_object_unavailable:" + "d" * 40 in refused["reason"]


def test_transfer_result_does_not_rewrite_accepted_source(transfer_seat, tmp_path):
    seat = transfer_seat
    _install_transfer(seat)
    built, result = _both_transfer_consumers(seat)
    assert isinstance(built, PreprintArtifact)
    source = tmp_path / "synthetic-source.md"
    original = seat["a_text"]
    source.write_text(original)
    built.source_path = str(source)
    built.publication_gate_result = result.to_frontmatter()
    _consumer(seat["accepted"])._attach_gate_frontmatter(built)
    assert source.read_text() == original


def test_transfer_issuer_malformed_api_record_is_named_refusal(transfer_seat):
    seat = transfer_seat
    seat["record"]["base"] = None
    result = _issue_transfer(seat)
    assert result["status"] == "refused"
    assert "transfer_evidence_unobservable_or_malformed" in result["reason"]
    assert "next action:" in result["reason"]


def test_immutable_parser_error_does_not_serialize_source_content():
    marker = "synthetic-private-source-marker"
    with pytest.raises(publisher.PublicationFrontmatterError) as exc:
        publisher._parse_publication_markdown("---\nbroken: [\n---\n" + marker)
    assert "immutable artifact text" in str(exc.value)
    assert marker not in str(exc.value)
