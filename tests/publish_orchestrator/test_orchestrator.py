"""Tests for ``agents.publish_orchestrator.orchestrator.Orchestrator``."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from unittest import mock

import pytest
import yaml
from prometheus_client import CollectorRegistry

from agents.publish_orchestrator import orchestrator as orchestrator_module
from agents.publish_orchestrator.orchestrator import (
    FANOUT_SURFACE_IDS,
    PUBLICATION_BASELINE_REQUIRED_GATES,
    PUBLICATION_FANOUT_REQUIRED_GATES,
    Orchestrator,
    _artifact_fingerprint,
)
from shared import public_gate_receipts
from shared.preprint_artifact import PreprintArtifact
from shared.publication_hardening.gate import (
    PublicationGateChildResult,
    PublicationGateDecision,
    PublicationGateResult,
)
from shared.publication_hardening.review import ReviewReport

TASK_ID = "cc-task-public-gate-test"
AUTHORITY_SECRET = "test-public-gate-authority-secret"
PUBLIC_GATE_AUTHORITY_BLOCK = (
    "authority_case: CASE-PUBLIC-EGRESS-TEST\n"
    "acceptor: claim-verification-council\n"
    "review_profile: claim_verification_council_public_egress\n"
    f"evidence_ref: review-dossier:{TASK_ID}\n"
)


@pytest.fixture(autouse=True)
def stable_public_gate_head(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator_module, "_current_repo_head_sha", lambda: "a" * 40)


def _drop_artifact(
    state_root: Path,
    *,
    slug: str,
    surfaces: list[str],
    body_md: str = "Body.",
    source_path: Path | None = None,
    author_model: str | None = None,
    include_gate_receipts: bool = True,
) -> Path:
    """Write an approved PreprintArtifact JSON to inbox/."""
    artifact = PreprintArtifact(
        slug=slug,
        title=f"Test artifact {slug}",
        abstract="Brief.",
        body_md=body_md,
        surfaces_targeted=surfaces,
        source_path=str(source_path) if source_path is not None else None,
        author_model=author_model,
    )
    artifact.mark_approved(by_referent="Oudepode")
    if include_gate_receipts:
        artifact.publication_gate_context = {
            "publication_gate_receipts": _write_public_gate_receipts(state_root, artifact)
        }
    inbox_path = artifact.inbox_path(state_root=state_root)
    inbox_path.parent.mkdir(parents=True, exist_ok=True)
    inbox_path.write_text(artifact.model_dump_json(indent=2))
    return inbox_path


def _write_public_gate_receipts(
    state_root: Path,
    artifact: PreprintArtifact,
) -> dict[str, str]:
    surfaces = artifact.surfaces_targeted
    gates = (
        PUBLICATION_FANOUT_REQUIRED_GATES
        if set(surfaces).intersection(FANOUT_SURFACE_IDS)
        else PUBLICATION_BASELINE_REQUIRED_GATES
    )
    receipt_root = state_root / "public-gate-receipts"
    authority_root = state_root / "public-gate-authority"
    receipt_root.mkdir(parents=True, exist_ok=True)
    authority_root.mkdir(parents=True, exist_ok=True)
    public_gate_receipts.PUBLIC_GATE_AUTHORITY_ROOTS = (authority_root,)
    os.environ[public_gate_receipts.PUBLIC_GATE_AUTHORITY_SECRET_ENV] = AUTHORITY_SECRET
    surfaces_yaml = "\n".join(f"  - {surface}" for surface in sorted(surfaces))
    for gate in gates:
        (receipt_root / f"{gate}.yaml").write_text(
            f"gate_id: {gate}\n"
            "status: passed\n"
            f"{PUBLIC_GATE_AUTHORITY_BLOCK}"
            f"artifact_slug: {artifact.slug}\n"
            f"artifact_fingerprint: {_artifact_fingerprint(artifact)}\n"
            "target_surfaces:\n"
            f"{surfaces_yaml}\n",
            encoding="utf-8",
        )
    _write_public_gate_review_evidence(
        receipt_root,
        gates=tuple(gates),
        receipt_refs=tuple(f"public-gate:{gate}.yaml" for gate in gates),
        artifact_slug=artifact.slug,
        artifact_fingerprint=_artifact_fingerprint(artifact),
        target_surfaces=tuple(sorted(surfaces)),
    )
    return {gate: f"public-gate:{gate}.yaml" for gate in gates}


def _write_public_gate_review_evidence(
    receipt_root: Path,
    *,
    gates: tuple[str, ...],
    receipt_refs: tuple[str, ...],
    artifact_slug: str,
    artifact_fingerprint: str,
    target_surfaces: tuple[str, ...],
) -> None:
    del receipt_root
    gate_yaml = "\n".join(f"  - {gate}" for gate in gates)
    receipt_yaml = "\n".join(f"  - {receipt_ref}" for receipt_ref in receipt_refs)
    surface_yaml = "\n".join(f"  - {surface}" for surface in target_surfaces)
    payload = yaml.safe_load(
        "dossier_schema: 1\n"
        f"task_id: {TASK_ID}\n"
        "head_sha: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        "review_team_verdict: quorum-accept\n"
        "quorum_required: 1\n"
        "accept_count: 1\n"
        "required_gates:\n"
        f"{gate_yaml}\n"
        "authorized_public_gate_receipts:\n"
        f"{receipt_yaml}\n"
        f"artifact_slug: {artifact_slug}\n"
        f"artifact_fingerprint: {artifact_fingerprint}\n"
        "target_surfaces:\n"
        f"{surface_yaml}\n"
        "authority_issuer: claim-verification-council\n"
        "reviewers:\n"
        "  - id: cvc-1\n"
        "    family: cvc\n"
        "    verdict: accept\n"
    )
    payload["authority_signature"] = public_gate_receipts.public_gate_authority_signature(
        payload,
        AUTHORITY_SECRET,
    )
    (
        public_gate_receipts.PUBLIC_GATE_AUTHORITY_ROOTS[0] / f"{TASK_ID}.review-dossier.yaml"
    ).write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )


def _write_publication_policy(
    state_root: Path,
    *,
    target_surfaces: tuple[str, ...],
    required_gates: tuple[str, ...],
    status: str = "guarded_public_channel",
    publication_allowed_without_bus: bool = False,
    direct_public_egress_allowed: bool = False,
    review_required: str = "Claim Verification Council",
    claim_ceiling: str = "source refs, rights, privacy, redaction, and target surfaces",
) -> Path:
    path = state_root / "publication-policy.yaml"
    target_lines = "\n".join(f"    - {surface}" for surface in target_surfaces)
    gate_lines = "\n".join(f"    - {gate}" for gate in required_gates)
    path.write_text(
        "publication_frontmatter_policy:\n"
        f"  status: {status}\n"
        f"  publication_allowed_without_bus: {str(publication_allowed_without_bus).lower()}\n"
        f"  direct_public_egress_allowed: {str(direct_public_egress_allowed).lower()}\n"
        f"  review_required: {review_required}\n"
        "  target_surfaces:\n"
        f"{target_lines}\n"
        "  required_gates:\n"
        f"{gate_lines}\n"
        f"  claim_ceiling: {claim_ceiling}\n",
        encoding="utf-8",
    )
    return path


class _ApprovingReviewPass:
    def review_text(
        self,
        text: str,
        *,
        author_model: str | None = None,
        lint_report: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> ReviewReport:
        del text, lint_report, metadata
        return ReviewReport(
            reviewer_model="test-reviewer",
            author_model=author_model,
            overall_confidence=0.99,
        )


class _CountingReviewPass(_ApprovingReviewPass):
    def __init__(self) -> None:
        self.calls = 0

    def review_text(
        self,
        text: str,
        *,
        author_model: str | None = None,
        lint_report: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> ReviewReport:
        self.calls += 1
        return super().review_text(
            text,
            author_model=author_model,
            lint_report=lint_report,
            metadata=metadata,
        )


class _HoldingReviewPass:
    def review_text(
        self,
        text: str,
        *,
        author_model: str | None = None,
        lint_report: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> ReviewReport:
        del text, lint_report, metadata
        return ReviewReport(
            reviewer_model="test-reviewer",
            author_model=author_model,
            overall_confidence=0.2,
            flagged_issues=("tone too promotional",),
        )


class _StaticGate:
    def __init__(self, decision: PublicationGateDecision) -> None:
        self.decision = decision

    def evaluate(self, _artifact: PreprintArtifact) -> PublicationGateResult:
        return PublicationGateResult(
            decision=self.decision,
            generated_at="2026-05-13T00:00:00+00:00",
            child_results=(
                PublicationGateChildResult(
                    name="codebase",
                    decision=PublicationGateDecision.HOLD
                    if self.decision == PublicationGateDecision.OPERATOR_OVERRIDDEN_HOLD
                    else self.decision,
                    findings=("static gate",),
                ),
            ),
            flagged_issues=("static gate",)
            if self.decision in {PublicationGateDecision.HOLD, PublicationGateDecision.REJECT}
            else (),
            override={"by_referent": "Oudepode", "reason": "test"}
            if self.decision == PublicationGateDecision.OPERATOR_OVERRIDDEN_HOLD
            else None,
            review_report={
                "schema_version": 1,
                "reviewer_model": "test-reviewer",
                "overall_confidence": 0.99,
                "flagged_issues": [],
            },
        )


def _make_orchestrator(
    state_root: Path,
    *,
    surface_registry: dict[str, str],
    publication_allowed_surfaces: set[str] | None = None,
) -> Orchestrator:
    return Orchestrator(
        state_root=state_root,
        surface_registry=surface_registry,
        publication_allowed_surfaces=publication_allowed_surfaces
        if publication_allowed_surfaces is not None
        else set(surface_registry),
        public_event_path=state_root / "public-events.jsonl",
        review_pass=_ApprovingReviewPass(),
        registry=CollectorRegistry(),
    )


# ── Empty inbox ─────────────────────────────────────────────────────


class TestEmptyInbox:
    def test_missing_inbox_dir(self, tmp_path):
        orch = _make_orchestrator(tmp_path, surface_registry={})
        assert orch.run_once() == 0

    def test_empty_inbox(self, tmp_path):
        (tmp_path / "publish/inbox").mkdir(parents=True)
        orch = _make_orchestrator(tmp_path, surface_registry={})
        assert orch.run_once() == 0


# ── Single artifact, single surface ─────────────────────────────────


class TestSingleSurface:
    def test_unwired_surface(self, tmp_path):
        _drop_artifact(tmp_path, slug="x", surfaces=["unknown-surface"])
        orch = _make_orchestrator(
            tmp_path,
            surface_registry={},
            publication_allowed_surfaces={"unknown-surface"},
        )
        orch.run_once()

        log_path = tmp_path / "publish/log/x.unknown-surface.json"
        assert log_path.exists()
        record = json.loads(log_path.read_text())
        assert record["result"] == "surface_unwired"
        assert not (tmp_path / "publish/published/x.json").exists()
        assert (tmp_path / "publish/failed/x.json").exists()

    def test_ok_dispatch(self, tmp_path, monkeypatch):
        # Create a fake module with a publish_artifact entry-point
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        _drop_artifact(tmp_path, slug="x", surfaces=["fake"])
        orch = _make_orchestrator(
            tmp_path, surface_registry={"fake": "fake_publisher:publish_artifact"}
        )
        orch.run_once()

        # Result logged
        log_path = tmp_path / "publish/log/x.fake.json"
        assert log_path.exists()
        assert json.loads(log_path.read_text())["result"] == "ok"

        # Artifact moved to published/
        assert not (tmp_path / "publish/inbox/x.json").exists()
        assert (tmp_path / "publish/published/x.json").exists()

        events = [
            json.loads(line) for line in (tmp_path / "public-events.jsonl").read_text().splitlines()
        ]
        assert [event["event_type"] for event in events] == [
            "publication.artifact",
            "publication.artifact",
            "publication.artifact",
        ]
        assert {event["source"]["substrate_id"] for event in events} == {"publication_artifact"}
        surface_event = next(event for event in events if event["event_id"].endswith(":fake:ok"))
        assert surface_event["surface_policy"]["dry_run_reason"] == ("surface_policy_denied:fake")
        assert "Body." not in json.dumps(surface_event)

    def test_cross_provider_review_hold_suppresses_surface_dispatch(self, tmp_path, monkeypatch):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        source = tmp_path / "draft.md"
        source.write_text("---\ntitle: Held\n---\n\nBody\n", encoding="utf-8")
        _drop_artifact(
            tmp_path,
            slug="held-for-review",
            surfaces=["fake"],
            source_path=source,
            author_model="codex",
        )
        orch = Orchestrator(
            state_root=tmp_path,
            surface_registry={"fake": "fake_publisher:publish_artifact"},
            publication_allowed_surfaces={"fake"},
            public_event_path=tmp_path / "public-events.jsonl",
            review_pass=_HoldingReviewPass(),
            registry=CollectorRegistry(),
        )

        assert orch.run_once() == 1
        fake_module.publish_artifact.assert_not_called()

        assert not (tmp_path / "publish/inbox/held-for-review.json").exists()
        assert not (tmp_path / "publish/published/held-for-review.json").exists()
        assert not (tmp_path / "publish/failed/held-for-review.json").exists()

        draft = json.loads((tmp_path / "publish/draft/held-for-review.json").read_text())
        assert draft["approval"] == "withheld"
        assert draft["publication_review"]["overall_confidence"] == 0.2
        assert draft["publication_review"]["author_model"] == "codex"
        assert draft["publication_gate_result"]["decision"] == "hold"

        frontmatter = source.read_text(encoding="utf-8").split("---", 2)[1]
        assert "publication_review:" in frontmatter
        assert "publication_gate_result:" in frontmatter
        assert "overall_confidence: 0.2" in frontmatter

        review_log = json.loads(
            (tmp_path / "publish/log/held-for-review.publication-hardening-gate.json").read_text()
        )
        assert review_log["result"] == "operator_hold"
        assert review_log["publication_gate_decision"] == "hold"
        assert review_log["flagged_issues"] == ["review: tone too promotional"]

    def test_publication_gate_reject_suppresses_surface_dispatch(self, tmp_path, monkeypatch):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        _drop_artifact(tmp_path, slug="rejected-by-gate", surfaces=["fake"])
        orch = Orchestrator(
            state_root=tmp_path,
            surface_registry={"fake": "fake_publisher:publish_artifact"},
            publication_allowed_surfaces={"fake"},
            public_event_path=tmp_path / "public-events.jsonl",
            hardening_gate=_StaticGate(PublicationGateDecision.REJECT),
            registry=CollectorRegistry(),
        )

        assert orch.run_once() == 1
        fake_module.publish_artifact.assert_not_called()

        assert not (tmp_path / "publish/inbox/rejected-by-gate.json").exists()
        assert (tmp_path / "publish/failed/rejected-by-gate.json").exists()
        gate_log = json.loads(
            (tmp_path / "publish/log/rejected-by-gate.publication-hardening-gate.json").read_text()
        )
        assert gate_log["result"] == "rejected"
        assert gate_log["publication_gate_decision"] == "reject"

    def test_unsafe_inbox_slug_quarantines_without_path_escape(self, tmp_path, monkeypatch):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        artifact = PreprintArtifact(
            slug="../escape",
            title="Unsafe slug",
            abstract="Brief.",
            body_md="Body.",
            surfaces_targeted=["fake"],
        )
        artifact.mark_approved(by_referent="Oudepode")
        inbox_path = tmp_path / "publish" / "inbox" / "unsafe.json"
        inbox_path.parent.mkdir(parents=True, exist_ok=True)
        inbox_path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        review_pass = _CountingReviewPass()
        orch = Orchestrator(
            state_root=tmp_path,
            surface_registry={"fake": "fake_publisher:publish_artifact"},
            publication_allowed_surfaces={"fake"},
            public_event_path=tmp_path / "public-events.jsonl",
            review_pass=review_pass,
            registry=CollectorRegistry(),
        )

        assert orch.run_once() == 1
        assert review_pass.calls == 0
        fake_module.publish_artifact.assert_not_called()
        assert not inbox_path.exists()
        assert not (tmp_path / "publish" / "escape.json").exists()
        assert not (tmp_path.parent / "escape.json").exists()
        failed = list((tmp_path / "publish" / "failed").glob("invalid-artifact-*.json"))
        assert len(failed) == 1
        payload = json.loads(failed[0].read_text())
        assert payload["approval"] == "failed"
        assert payload["publication_gate_result"]["decision"] == "reject"
        child = payload["publication_gate_result"]["child_results"][0]
        assert child["name"] == "artifact_envelope"
        assert any("slug" in finding for finding in child["findings"])

    def test_unsafe_source_path_quarantines_before_frontmatter_write(self, tmp_path, monkeypatch):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        source = tmp_path.parent / "outside-publication-source.md"
        source.write_text("---\ntitle: Outside\n---\n\nBody\n", encoding="utf-8")
        _drop_artifact(tmp_path, slug="unsafe-source", surfaces=["fake"], source_path=source)
        review_pass = _CountingReviewPass()
        orch = Orchestrator(
            state_root=tmp_path,
            surface_registry={"fake": "fake_publisher:publish_artifact"},
            publication_allowed_surfaces={"fake"},
            public_event_path=tmp_path / "public-events.jsonl",
            review_pass=review_pass,
            registry=CollectorRegistry(),
        )

        assert orch.run_once() == 1
        assert review_pass.calls == 0
        fake_module.publish_artifact.assert_not_called()
        assert source.read_text(encoding="utf-8") == "---\ntitle: Outside\n---\n\nBody\n"
        assert not (tmp_path / "publish" / "inbox" / "unsafe-source.json").exists()
        assert not (tmp_path / "publish" / "draft" / "unsafe-source.json").exists()
        failed = list((tmp_path / "publish" / "failed").glob("invalid-artifact-*.json"))
        assert len(failed) == 1
        payload = json.loads(failed[0].read_text())
        child = payload["publication_gate_result"]["child_results"][0]
        assert child["name"] == "artifact_envelope"
        assert any("source_path" in finding for finding in child["findings"])

    def test_direct_inbox_surface_outside_allowlist_quarantines(self, tmp_path, monkeypatch):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        _drop_artifact(tmp_path, slug="outside-allowlist", surfaces=["fake"])
        orch = Orchestrator(
            state_root=tmp_path,
            surface_registry={"fake": "fake_publisher:publish_artifact"},
            publication_allowed_surfaces={"allowed-surface"},
            public_event_path=tmp_path / "public-events.jsonl",
            review_pass=_CountingReviewPass(),
            registry=CollectorRegistry(),
        )

        assert orch.run_once() == 1
        fake_module.publish_artifact.assert_not_called()
        assert not (tmp_path / "publish" / "inbox" / "outside-allowlist.json").exists()
        failed = list((tmp_path / "publish" / "failed").glob("invalid-artifact-*.json"))
        assert len(failed) == 1
        payload = json.loads(failed[0].read_text())
        child = payload["publication_gate_result"]["child_results"][0]
        assert child["name"] == "artifact_envelope"
        assert any(
            "outside configured publication allowlist" in finding for finding in child["findings"]
        )

    def test_direct_inbox_draft_approval_quarantines_before_dispatch(self, tmp_path, monkeypatch):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        artifact = PreprintArtifact(
            slug="draft-inbox",
            title="Draft Inbox",
            abstract="Brief.",
            body_md="Body.",
            surfaces_targeted=["fake"],
        )
        artifact.publication_gate_context = {
            "publication_gate_receipts": _write_public_gate_receipts(tmp_path, artifact)
        }
        inbox_path = tmp_path / "publish" / "inbox" / "draft-inbox.json"
        inbox_path.parent.mkdir(parents=True, exist_ok=True)
        inbox_path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        review_pass = _CountingReviewPass()
        orch = Orchestrator(
            state_root=tmp_path,
            surface_registry={"fake": "fake_publisher:publish_artifact"},
            publication_allowed_surfaces={"fake"},
            public_event_path=tmp_path / "public-events.jsonl",
            review_pass=review_pass,
            registry=CollectorRegistry(),
        )

        assert orch.run_once() == 1
        assert review_pass.calls == 0
        fake_module.publish_artifact.assert_not_called()
        assert not inbox_path.exists()
        failed = list((tmp_path / "publish" / "failed").glob("invalid-artifact-*.json"))
        assert len(failed) == 1
        payload = json.loads(failed[0].read_text())
        child = payload["publication_gate_result"]["child_results"][0]
        assert child["name"] == "artifact_envelope"
        assert any("approval must be approved" in finding for finding in child["findings"])

    def test_malformed_source_path_quarantines_before_resolution_error(self, tmp_path, monkeypatch):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        artifact = PreprintArtifact(
            slug="malformed-source",
            title="Malformed Source",
            abstract="Brief.",
            body_md="Body.",
            surfaces_targeted=["fake"],
            source_path="\0",
        )
        artifact.mark_approved(by_referent="Oudepode")
        inbox_path = tmp_path / "publish" / "inbox" / "malformed-source.json"
        inbox_path.parent.mkdir(parents=True, exist_ok=True)
        inbox_path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        review_pass = _CountingReviewPass()
        orch = Orchestrator(
            state_root=tmp_path,
            surface_registry={"fake": "fake_publisher:publish_artifact"},
            publication_allowed_surfaces={"fake"},
            public_event_path=tmp_path / "public-events.jsonl",
            review_pass=review_pass,
            registry=CollectorRegistry(),
        )

        assert orch.run_once() == 1
        assert review_pass.calls == 0
        fake_module.publish_artifact.assert_not_called()
        assert not inbox_path.exists()
        failed = list((tmp_path / "publish" / "failed").glob("invalid-artifact-*.json"))
        assert len(failed) == 1
        payload = json.loads(failed[0].read_text())
        child = payload["publication_gate_result"]["child_results"][0]
        assert child["name"] == "artifact_envelope"
        assert any("source_path" in finding for finding in child["findings"])

    def test_duplicate_surfaces_quarantine_before_dispatch(self, tmp_path, monkeypatch):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        _drop_artifact(tmp_path, slug="duplicate-surface", surfaces=["fake", "fake"])
        review_pass = _CountingReviewPass()
        orch = Orchestrator(
            state_root=tmp_path,
            surface_registry={"fake": "fake_publisher:publish_artifact"},
            publication_allowed_surfaces={"fake"},
            public_event_path=tmp_path / "public-events.jsonl",
            review_pass=review_pass,
            registry=CollectorRegistry(),
        )

        assert orch.run_once() == 1
        assert review_pass.calls == 0
        fake_module.publish_artifact.assert_not_called()
        assert not (tmp_path / "publish" / "inbox" / "duplicate-surface.json").exists()
        failed = list((tmp_path / "publish" / "failed").glob("invalid-artifact-*.json"))
        assert len(failed) == 1
        payload = json.loads(failed[0].read_text())
        child = payload["publication_gate_result"]["child_results"][0]
        assert child["name"] == "artifact_envelope"
        assert any("duplicate surface ids: fake" in finding for finding in child["findings"])

    def test_dispatch_boundary_dedupes_duplicate_surfaces(self, tmp_path, monkeypatch):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        artifact = PreprintArtifact(
            slug="direct-duplicate-surface",
            title="Direct Duplicate Surface",
            abstract="Brief.",
            body_md="Body.",
            surfaces_targeted=["fake", "fake"],
        )
        artifact.mark_approved(by_referent="Oudepode")
        receipt_artifact = artifact.model_copy(update={"surfaces_targeted": ["fake"]})
        artifact.publication_gate_context = {
            "publication_gate_receipts": _write_public_gate_receipts(tmp_path, receipt_artifact)
        }
        orch = _make_orchestrator(
            tmp_path,
            surface_registry={"fake": "fake_publisher:publish_artifact"},
        )

        with orchestrator_module.ThreadPoolExecutor(max_workers=2) as pool:
            orch._dispatch(artifact, pool=pool)

        assert fake_module.publish_artifact.call_count == 1
        log_path = tmp_path / "publish" / "log" / "direct-duplicate-surface.fake.json"
        assert json.loads(log_path.read_text())["result"] == "ok"
        published = json.loads(
            (tmp_path / "publish" / "published" / "direct-duplicate-surface.json").read_text()
        )
        assert published["surfaces_targeted"] == ["fake"]

    def test_malformed_inbox_json_quarantines_and_continues(self, tmp_path, monkeypatch):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        bad_path = tmp_path / "publish" / "inbox" / "bad.json"
        bad_path.parent.mkdir(parents=True, exist_ok=True)
        bad_path.write_text("{not-json", encoding="utf-8")
        _drop_artifact(tmp_path, slug="valid-after-bad", surfaces=["fake"])
        orch = _make_orchestrator(
            tmp_path,
            surface_registry={"fake": "fake_publisher:publish_artifact"},
        )

        assert orch.run_once() == 2
        assert not bad_path.exists()
        failed = list((tmp_path / "publish" / "failed").glob("invalid-artifact-*.json"))
        assert len(failed) == 1
        payload = json.loads(failed[0].read_text())
        assert payload["approval"] == "failed"
        assert payload["quarantine_reason"] == "invalid_inbox_artifact"
        assert (tmp_path / "publish" / "published" / "valid-after-bad.json").exists()

    def test_inbox_load_oserror_quarantines_before_public_egress(self, tmp_path, monkeypatch):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        inbox_path = _drop_artifact(tmp_path, slug="retry-after-read-error", surfaces=["fake"])
        orch = _make_orchestrator(
            tmp_path,
            surface_registry={"fake": "fake_publisher:publish_artifact"},
        )

        with mock.patch.object(orch, "_load_artifact", side_effect=OSError("temporary I/O")):
            assert orch.run_once() == 1

        assert not inbox_path.exists()
        failed = list((tmp_path / "publish" / "failed").glob("invalid-artifact-*.json"))
        assert len(failed) == 1
        payload = json.loads(failed[0].read_text())
        assert payload["quarantine_reason"] == "unreadable_inbox_artifact"
        assert payload["suspected_code_path_error"] is False
        fake_module.publish_artifact.assert_not_called()

    def test_unexpected_inbox_load_error_quarantines_poison_pill(self, tmp_path, monkeypatch):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        inbox_path = _drop_artifact(tmp_path, slug="poison-pill", surfaces=["fake"])
        orch = _make_orchestrator(
            tmp_path,
            surface_registry={"fake": "fake_publisher:publish_artifact"},
        )

        with mock.patch.object(orch, "_load_artifact", side_effect=RuntimeError("boom")):
            assert orch.run_once() == 1

        assert not inbox_path.exists()
        failed = list((tmp_path / "publish" / "failed").glob("invalid-artifact-*.json"))
        assert len(failed) == 1
        payload = json.loads(failed[0].read_text())
        assert payload["quarantine_reason"] == "unexpected_inbox_artifact_load_exception"
        assert payload["suspected_code_path_error"] is True
        child = payload["publication_gate_result"]["child_results"][0]
        assert child["name"] == "artifact_envelope"
        assert any("suspected code-path error" in finding for finding in child["findings"])
        assert any("next action" in finding for finding in child["findings"])
        fake_module.publish_artifact.assert_not_called()

    def test_missing_public_gate_receipts_hold_before_surface_dispatch(
        self,
        tmp_path,
        monkeypatch,
    ):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        _drop_artifact(
            tmp_path,
            slug="missing-public-receipts",
            surfaces=["fake"],
            include_gate_receipts=False,
        )
        review_pass = _CountingReviewPass()
        orch = Orchestrator(
            state_root=tmp_path,
            surface_registry={"fake": "fake_publisher:publish_artifact"},
            publication_allowed_surfaces={"fake"},
            public_event_path=tmp_path / "public-events.jsonl",
            review_pass=review_pass,
            registry=CollectorRegistry(),
        )

        assert orch.run_once() == 1
        assert review_pass.calls == 0
        fake_module.publish_artifact.assert_not_called()

        assert not (tmp_path / "publish/inbox/missing-public-receipts.json").exists()
        assert not (tmp_path / "publish/published/missing-public-receipts.json").exists()
        assert not (tmp_path / "publish/failed/missing-public-receipts.json").exists()

        draft = json.loads((tmp_path / "publish/draft/missing-public-receipts.json").read_text())
        assert draft["approval"] == "withheld"
        assert draft["publication_gate_result"]["decision"] == "hold"
        receipt_child = next(
            child
            for child in draft["publication_gate_result"]["child_results"]
            if child["name"] == "public_gate_receipts"
        )
        assert receipt_child["decision"] == "hold"

        gate_log = json.loads(
            (
                tmp_path / "publish/log/missing-public-receipts.publication-hardening-gate.json"
            ).read_text()
        )
        assert gate_log["result"] == "operator_hold"
        assert gate_log["publication_gate_decision"] == "hold"
        assert any("public_gate_receipts:" in issue for issue in gate_log["flagged_issues"])

    def test_configured_public_gate_receipts_hold_before_surface_dispatch(
        self,
        tmp_path,
        monkeypatch,
    ):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)
        policy_path = _write_publication_policy(
            tmp_path,
            target_surfaces=("fake",),
            required_gates=(
                *PUBLICATION_BASELINE_REQUIRED_GATES,
                "operator_extra_gate",
            ),
        )
        monkeypatch.setattr(
            orchestrator_module,
            "PUBLICATION_POLICY_PATHS",
            (policy_path,),
        )

        _drop_artifact(tmp_path, slug="missing-configured-gate", surfaces=["fake"])
        review_pass = _CountingReviewPass()
        orch = Orchestrator(
            state_root=tmp_path,
            surface_registry={"fake": "fake_publisher:publish_artifact"},
            public_event_path=tmp_path / "public-events.jsonl",
            review_pass=review_pass,
            registry=CollectorRegistry(),
        )

        assert orch.run_once() == 1
        assert review_pass.calls == 0
        fake_module.publish_artifact.assert_not_called()
        assert not (tmp_path / "publish/inbox/missing-configured-gate.json").exists()
        assert not (tmp_path / "publish/published/missing-configured-gate.json").exists()

        draft = json.loads((tmp_path / "publish/draft/missing-configured-gate.json").read_text())
        receipt_child = next(
            child
            for child in draft["publication_gate_result"]["child_results"]
            if child["name"] == "public_gate_receipts"
        )
        assert receipt_child["decision"] == "hold"
        assert any("operator_extra_gate" in finding for finding in receipt_child["findings"])

        gate_log = json.loads(
            (
                tmp_path / "publish/log/missing-configured-gate.publication-hardening-gate.json"
            ).read_text()
        )
        assert gate_log["result"] == "operator_hold"
        assert any("operator_extra_gate" in issue for issue in gate_log["flagged_issues"])

    def test_replayed_public_gate_receipt_holds_before_surface_dispatch(
        self,
        tmp_path,
        monkeypatch,
    ):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        _drop_artifact(tmp_path, slug="replayed-public-receipt", surfaces=["fake"])
        receipt = tmp_path / "public-gate-receipts" / "rights_privacy_redaction_pass.yaml"
        receipt.write_text(
            "gate_id: rights_privacy_redaction_pass\n"
            "status: passed\n"
            f"{PUBLIC_GATE_AUTHORITY_BLOCK}"
            "artifact_slug: replayed-public-receipt\n"
            "artifact_fingerprint: stale-fingerprint\n"
            "target_surfaces:\n"
            "  - fake\n",
            encoding="utf-8",
        )
        review_pass = _CountingReviewPass()
        orch = Orchestrator(
            state_root=tmp_path,
            surface_registry={"fake": "fake_publisher:publish_artifact"},
            publication_allowed_surfaces={"fake"},
            public_event_path=tmp_path / "public-events.jsonl",
            review_pass=review_pass,
            registry=CollectorRegistry(),
        )

        assert orch.run_once() == 1
        assert review_pass.calls == 0
        fake_module.publish_artifact.assert_not_called()
        gate_log = json.loads(
            (
                tmp_path / "publish/log/replayed-public-receipt.publication-hardening-gate.json"
            ).read_text()
        )
        assert gate_log["result"] == "operator_hold"
        assert gate_log["publication_gate_decision"] == "hold"
        assert any("rights_privacy_redaction_pass" in issue for issue in gate_log["flagged_issues"])

    def test_public_gate_receipts_for_unexpected_head_hold_before_surface_dispatch(
        self,
        tmp_path,
        monkeypatch,
    ):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)
        artifact = PreprintArtifact(
            slug="stale-head-public-receipt",
            title="Stale Head Public Receipt",
            abstract="Brief.",
            body_md="Body.",
            surfaces_targeted=["fake"],
        )
        artifact.mark_approved(by_referent="Oudepode")
        artifact.publication_gate_context = {
            "publication_gate_receipts": _write_public_gate_receipts(tmp_path, artifact),
        }
        inbox_path = artifact.inbox_path(state_root=tmp_path)
        inbox_path.parent.mkdir(parents=True, exist_ok=True)
        inbox_path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")

        review_pass = _CountingReviewPass()
        orch = Orchestrator(
            state_root=tmp_path,
            surface_registry={"fake": "fake_publisher:publish_artifact"},
            publication_allowed_surfaces={"fake"},
            public_event_path=tmp_path / "public-events.jsonl",
            review_pass=review_pass,
            public_gate_expected_head_sha="b" * 40,
            registry=CollectorRegistry(),
        )

        assert orch.run_once() == 1
        assert review_pass.calls == 0
        fake_module.publish_artifact.assert_not_called()
        gate_log = json.loads(
            (
                tmp_path / "publish/log/stale-head-public-receipt.publication-hardening-gate.json"
            ).read_text()
        )
        assert gate_log["result"] == "operator_hold"
        assert gate_log["publication_gate_decision"] == "hold"
        assert any("claim_review_current" in issue for issue in gate_log["flagged_issues"])

    def test_malformed_fanout_policy_status_holds_before_surface_dispatch(
        self,
        tmp_path,
        monkeypatch,
    ):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)
        policy_path = _write_publication_policy(
            tmp_path,
            target_surfaces=("omg-lol-weblog-bearer-fanout",),
            required_gates=PUBLICATION_FANOUT_REQUIRED_GATES,
            status="guarded_public_channel",
        )
        monkeypatch.setattr(
            orchestrator_module,
            "PUBLICATION_POLICY_PATHS",
            (policy_path,),
        )

        _drop_artifact(
            tmp_path,
            slug="bad-fanout-policy-status",
            surfaces=["omg-lol-weblog-bearer-fanout"],
        )
        review_pass = _CountingReviewPass()
        orch = Orchestrator(
            state_root=tmp_path,
            surface_registry={"omg-lol-weblog-bearer-fanout": "fake_publisher:publish_artifact"},
            public_event_path=tmp_path / "public-events.jsonl",
            review_pass=review_pass,
            registry=CollectorRegistry(),
        )

        assert orch.run_once() == 1
        assert review_pass.calls == 0
        fake_module.publish_artifact.assert_not_called()
        gate_log = json.loads(
            (
                tmp_path / "publish/log/bad-fanout-policy-status.publication-hardening-gate.json"
            ).read_text()
        )
        assert gate_log["result"] == "operator_hold"
        assert any("guarded_public_fanout" in issue for issue in gate_log["flagged_issues"])

    def test_malformed_non_fanout_policy_status_holds_before_surface_dispatch(
        self,
        tmp_path,
        monkeypatch,
    ):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)
        policy_path = _write_publication_policy(
            tmp_path,
            target_surfaces=("fake",),
            required_gates=PUBLICATION_BASELINE_REQUIRED_GATES,
            status="guarded_public_surface",
        )
        monkeypatch.setattr(
            orchestrator_module,
            "PUBLICATION_POLICY_PATHS",
            (policy_path,),
        )

        _drop_artifact(tmp_path, slug="bad-channel-policy-status", surfaces=["fake"])
        review_pass = _CountingReviewPass()
        orch = Orchestrator(
            state_root=tmp_path,
            surface_registry={"fake": "fake_publisher:publish_artifact"},
            public_event_path=tmp_path / "public-events.jsonl",
            review_pass=review_pass,
            registry=CollectorRegistry(),
        )

        assert orch.run_once() == 1
        assert review_pass.calls == 0
        fake_module.publish_artifact.assert_not_called()
        gate_log = json.loads(
            (
                tmp_path / "publish/log/bad-channel-policy-status.publication-hardening-gate.json"
            ).read_text()
        )
        assert gate_log["result"] == "operator_hold"
        assert any("guarded_public_channel" in issue for issue in gate_log["flagged_issues"])

    def test_publication_policy_boundary_fields_hold_before_surface_dispatch(
        self,
        tmp_path,
        monkeypatch,
    ):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)
        policy_path = _write_publication_policy(
            tmp_path,
            target_surfaces=("fake",),
            required_gates=PUBLICATION_BASELINE_REQUIRED_GATES,
            publication_allowed_without_bus=True,
        )
        monkeypatch.setattr(
            orchestrator_module,
            "PUBLICATION_POLICY_PATHS",
            (policy_path,),
        )

        _drop_artifact(tmp_path, slug="bad-policy-boundary", surfaces=["fake"])
        review_pass = _CountingReviewPass()
        orch = Orchestrator(
            state_root=tmp_path,
            surface_registry={"fake": "fake_publisher:publish_artifact"},
            public_event_path=tmp_path / "public-events.jsonl",
            review_pass=review_pass,
            registry=CollectorRegistry(),
        )

        assert orch.run_once() == 1
        assert review_pass.calls == 0
        fake_module.publish_artifact.assert_not_called()
        gate_log = json.loads(
            (
                tmp_path / "publish/log/bad-policy-boundary.publication-hardening-gate.json"
            ).read_text()
        )
        assert gate_log["result"] == "operator_hold"
        assert any(
            "publication_allowed_without_bus must be false" in issue
            for issue in gate_log["flagged_issues"]
        )

    def test_publication_gate_override_dispatches_with_surface_receipt(self, tmp_path, monkeypatch):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        _drop_artifact(tmp_path, slug="override-by-gate", surfaces=["fake"])
        orch = Orchestrator(
            state_root=tmp_path,
            surface_registry={"fake": "fake_publisher:publish_artifact"},
            publication_allowed_surfaces={"fake"},
            public_event_path=tmp_path / "public-events.jsonl",
            hardening_gate=_StaticGate(PublicationGateDecision.OPERATOR_OVERRIDDEN_HOLD),
            registry=CollectorRegistry(),
        )

        assert orch.run_once() == 1
        fake_module.publish_artifact.assert_called_once()

        surface_log = json.loads((tmp_path / "publish/log/override-by-gate.fake.json").read_text())
        assert surface_log["result"] == "ok"
        assert surface_log["publication_gate_decision"] == "operator_overridden_hold"
        assert surface_log["publication_gate_fingerprint"]

    def test_dispatch_reuses_public_gate_receipt_child(self, tmp_path, monkeypatch):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        _drop_artifact(tmp_path, slug="reuse-receipt-child", surfaces=["fake"])
        orch = _make_orchestrator(
            tmp_path,
            surface_registry={"fake": "fake_publisher:publish_artifact"},
        )
        original = orch._public_gate_receipts_child
        calls = 0

        def count_public_gate_receipts_child(artifact: PreprintArtifact):
            nonlocal calls
            calls += 1
            return original(artifact)

        monkeypatch.setattr(
            orch,
            "_public_gate_receipts_child",
            count_public_gate_receipts_child,
        )

        assert orch.run_once() == 1
        assert calls == 1
        fake_module.publish_artifact.assert_called_once()

    def test_publication_gate_override_cannot_bypass_missing_public_receipts(
        self,
        tmp_path,
        monkeypatch,
    ):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        _drop_artifact(
            tmp_path,
            slug="override-missing-public-receipts",
            surfaces=["fake"],
            include_gate_receipts=False,
        )
        orch = Orchestrator(
            state_root=tmp_path,
            surface_registry={"fake": "fake_publisher:publish_artifact"},
            publication_allowed_surfaces={"fake"},
            public_event_path=tmp_path / "public-events.jsonl",
            hardening_gate=_StaticGate(PublicationGateDecision.OPERATOR_OVERRIDDEN_HOLD),
            registry=CollectorRegistry(),
        )

        assert orch.run_once() == 1
        fake_module.publish_artifact.assert_not_called()

        gate_log = json.loads(
            (
                tmp_path
                / "publish/log/override-missing-public-receipts.publication-hardening-gate.json"
            ).read_text()
        )
        assert gate_log["result"] == "operator_hold"
        assert gate_log["publication_gate_decision"] == "hold"
        assert any(child["name"] == "public_gate_receipts" for child in gate_log["child_results"])
        assert (tmp_path / "publish/draft/override-missing-public-receipts.json").exists()

    def test_surface_override_still_validates_publication_policy_shape(
        self,
        tmp_path,
        monkeypatch,
    ):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)
        policy_path = tmp_path / "publication-policy.yaml"
        policy_path.write_text("publication_frontmatter_policy: [not-a-policy]\n", encoding="utf-8")
        monkeypatch.setattr(
            orchestrator_module,
            "PUBLICATION_POLICY_PATHS",
            (policy_path,),
        )

        _drop_artifact(tmp_path, slug="override-bad-policy", surfaces=["fake"])
        review_pass = _CountingReviewPass()
        orch = Orchestrator(
            state_root=tmp_path,
            surface_registry={"fake": "fake_publisher:publish_artifact"},
            publication_allowed_surfaces={"fake"},
            public_event_path=tmp_path / "public-events.jsonl",
            review_pass=review_pass,
            registry=CollectorRegistry(),
        )

        assert orch.run_once() == 1
        assert review_pass.calls == 0
        fake_module.publish_artifact.assert_not_called()
        gate_log = json.loads(
            (
                tmp_path / "publish/log/override-bad-policy.publication-hardening-gate.json"
            ).read_text()
        )
        assert gate_log["result"] == "operator_hold"
        assert any(
            "publication_frontmatter_policy" in issue for issue in gate_log["flagged_issues"]
        )

    def test_surface_override_still_validates_policy_required_gates(
        self,
        tmp_path,
        monkeypatch,
    ):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)
        policy_path = _write_publication_policy(
            tmp_path,
            target_surfaces=("fake",),
            required_gates=("source_artifact_public_safe",),
        )
        monkeypatch.setattr(
            orchestrator_module,
            "PUBLICATION_POLICY_PATHS",
            (policy_path,),
        )

        _drop_artifact(tmp_path, slug="override-incomplete-policy", surfaces=["fake"])
        review_pass = _CountingReviewPass()
        orch = Orchestrator(
            state_root=tmp_path,
            surface_registry={"fake": "fake_publisher:publish_artifact"},
            publication_allowed_surfaces={"fake"},
            public_event_path=tmp_path / "public-events.jsonl",
            review_pass=review_pass,
            registry=CollectorRegistry(),
        )

        assert orch.run_once() == 1
        assert review_pass.calls == 0
        fake_module.publish_artifact.assert_not_called()
        gate_log = json.loads(
            (
                tmp_path / "publish/log/override-incomplete-policy.publication-hardening-gate.json"
            ).read_text()
        )
        assert gate_log["result"] == "operator_hold"
        assert any("missing baseline gate ids" in issue for issue in gate_log["flagged_issues"])

    def test_publisher_raises_logs_error(self, tmp_path, monkeypatch):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(side_effect=RuntimeError("send failure"))
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        _drop_artifact(tmp_path, slug="y", surfaces=["fake"])
        orch = _make_orchestrator(
            tmp_path, surface_registry={"fake": "fake_publisher:publish_artifact"}
        )
        orch.run_once()

        log_path = tmp_path / "publish/log/y.fake.json"
        assert json.loads(log_path.read_text())["result"] == "error"
        assert not (tmp_path / "publish/published/y.json").exists()
        assert (tmp_path / "publish/failed/y.json").exists()

    def test_no_credentials_moves_to_failed_not_published(self, tmp_path, monkeypatch):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="no_credentials")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        _drop_artifact(tmp_path, slug="creds", surfaces=["fake"])
        orch = _make_orchestrator(
            tmp_path, surface_registry={"fake": "fake_publisher:publish_artifact"}
        )
        orch.run_once()

        assert json.loads((tmp_path / "publish/log/creds.fake.json").read_text())["result"] == (
            "no_credentials"
        )
        assert not (tmp_path / "publish/published/creds.json").exists()
        assert not (tmp_path / "publish/inbox/creds.json").exists()
        assert (tmp_path / "publish/failed/creds.json").exists()

    def test_deferred_re_runs(self, tmp_path, monkeypatch):
        fake_module = mock.Mock()
        # First call returns deferred; second call returns ok
        fake_module.publish_artifact = mock.Mock(side_effect=["deferred", "ok"])
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        _drop_artifact(tmp_path, slug="z", surfaces=["fake"])
        orch = _make_orchestrator(
            tmp_path, surface_registry={"fake": "fake_publisher:publish_artifact"}
        )

        # Tick 1: deferred — artifact stays in inbox
        orch.run_once()
        assert (tmp_path / "publish/inbox/z.json").exists()
        assert not (tmp_path / "publish/published/z.json").exists()

        # Tick 2: ok — artifact moves to published
        orch.run_once()
        assert not (tmp_path / "publish/inbox/z.json").exists()
        assert (tmp_path / "publish/published/z.json").exists()

        events = [
            json.loads(line) for line in (tmp_path / "public-events.jsonl").read_text().splitlines()
        ]
        event_ids = [event["event_id"] for event in events]
        assert any(event_id.endswith(":fake:deferred") for event_id in event_ids)
        assert any(event_id.endswith(":fake:ok") for event_id in event_ids)
        assert len(event_ids) == len(set(event_ids))

    def test_corrupt_prior_surface_log_warns_before_redispatch(
        self,
        tmp_path,
        monkeypatch,
        caplog,
    ):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        _drop_artifact(tmp_path, slug="corrupt-log", surfaces=["fake"])
        log_path = tmp_path / "publish/log/corrupt-log.fake.json"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("{not-json", encoding="utf-8")
        orch = _make_orchestrator(
            tmp_path,
            surface_registry={"fake": "fake_publisher:publish_artifact"},
        )

        with caplog.at_level("WARNING", logger=orchestrator_module.__name__):
            assert orch.run_once() == 1

        fake_module.publish_artifact.assert_called_once()
        assert "publication prior surface log unreadable" in caplog.text
        assert "next action: inspect or remove the corrupt surface log" in caplog.text
        assert str(log_path) in caplog.text

    def test_changed_artifact_republishes_same_slug(self, tmp_path, monkeypatch):
        fake_module = mock.Mock()
        fake_module.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_publisher", fake_module)

        orch = _make_orchestrator(
            tmp_path, surface_registry={"fake": "fake_publisher:publish_artifact"}
        )

        _drop_artifact(tmp_path, slug="repeat", surfaces=["fake"], body_md="first")
        orch.run_once()
        first_log = json.loads((tmp_path / "publish/log/repeat.fake.json").read_text())

        _drop_artifact(tmp_path, slug="repeat", surfaces=["fake"], body_md="second")
        orch.run_once()
        second_log = json.loads((tmp_path / "publish/log/repeat.fake.json").read_text())
        published = json.loads((tmp_path / "publish/published/repeat.json").read_text())

        assert fake_module.publish_artifact.call_count == 2
        assert first_log["artifact_fingerprint"] != second_log["artifact_fingerprint"]
        assert published["body_md"] == "second"


# ── Multi-surface fan-out ───────────────────────────────────────────


class TestMultiSurface:
    def test_all_surfaces_terminal_publishes(self, tmp_path, monkeypatch):
        bsky = mock.Mock()
        bsky.publish_artifact = mock.Mock(return_value="ok")
        masto = mock.Mock()
        masto.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_bsky", bsky)
        monkeypatch.setitem(__import__("sys").modules, "fake_masto", masto)

        _drop_artifact(tmp_path, slug="multi", surfaces=["bsky", "masto"])
        orch = _make_orchestrator(
            tmp_path,
            surface_registry={
                "bsky": "fake_bsky:publish_artifact",
                "masto": "fake_masto:publish_artifact",
            },
        )
        orch.run_once()

        assert (tmp_path / "publish/published/multi.json").exists()
        assert json.loads((tmp_path / "publish/log/multi.bsky.json").read_text())["result"] == "ok"
        assert json.loads((tmp_path / "publish/log/multi.masto.json").read_text())["result"] == "ok"

    def test_one_deferred_holds_artifact(self, tmp_path, monkeypatch):
        bsky = mock.Mock()
        bsky.publish_artifact = mock.Mock(return_value="ok")
        masto = mock.Mock()
        masto.publish_artifact = mock.Mock(return_value="deferred")
        monkeypatch.setitem(__import__("sys").modules, "fake_bsky", bsky)
        monkeypatch.setitem(__import__("sys").modules, "fake_masto", masto)

        _drop_artifact(tmp_path, slug="held", surfaces=["bsky", "masto"])
        orch = _make_orchestrator(
            tmp_path,
            surface_registry={
                "bsky": "fake_bsky:publish_artifact",
                "masto": "fake_masto:publish_artifact",
            },
        )
        orch.run_once()

        # bsky is terminal, masto is deferred — artifact stays in inbox
        assert (tmp_path / "publish/inbox/held.json").exists()
        assert not (tmp_path / "publish/published/held.json").exists()
        assert not (tmp_path / "publish/failed/held.json").exists()

    def test_partial_success_moves_to_failed_not_published(self, tmp_path, monkeypatch):
        bsky = mock.Mock()
        bsky.publish_artifact = mock.Mock(return_value="ok")
        masto = mock.Mock()
        masto.publish_artifact = mock.Mock(return_value="auth_error")
        monkeypatch.setitem(__import__("sys").modules, "fake_bsky", bsky)
        monkeypatch.setitem(__import__("sys").modules, "fake_masto", masto)

        _drop_artifact(tmp_path, slug="partial", surfaces=["bsky", "masto"])
        orch = _make_orchestrator(
            tmp_path,
            surface_registry={
                "bsky": "fake_bsky:publish_artifact",
                "masto": "fake_masto:publish_artifact",
            },
        )
        orch.run_once()

        assert json.loads((tmp_path / "publish/log/partial.bsky.json").read_text())["result"] == (
            "ok"
        )
        assert (
            json.loads((tmp_path / "publish/log/partial.masto.json").read_text())["result"]
            == "auth_error"
        )
        assert not (tmp_path / "publish/published/partial.json").exists()
        assert (tmp_path / "publish/failed/partial.json").exists()


# ── Counter labels ──────────────────────────────────────────────────


class TestCounter:
    def test_counter_labels_per_surface(self, tmp_path, monkeypatch):
        fake = mock.Mock()
        fake.publish_artifact = mock.Mock(return_value="ok")
        monkeypatch.setitem(__import__("sys").modules, "fake_pub", fake)

        _drop_artifact(tmp_path, slug="count", surfaces=["fake"])
        orch = _make_orchestrator(tmp_path, surface_registry={"fake": "fake_pub:publish_artifact"})
        orch.run_once()

        sample = orch.dispatches_total.labels(surface="fake", result="ok")._value.get()
        assert sample == 1.0

    def test_counter_unwired_surface(self, tmp_path):
        _drop_artifact(tmp_path, slug="u", surfaces=["nope"])
        orch = _make_orchestrator(
            tmp_path,
            surface_registry={},
            publication_allowed_surfaces={"nope"},
        )
        orch.run_once()

        sample = orch.dispatches_total.labels(surface="nope", result="surface_unwired")._value.get()
        assert sample == 1.0


# ── SURFACE_REGISTRY entries (regression pin) ───────────────────────


class TestSurfaceRegistry:
    """Pin module-level SURFACE_REGISTRY wiring per ticket.

    Each entry must point at a real ``module:attr`` path. We pin the
    string here rather than importing so a renamed symbol fails the
    test loudly. Live import-resolution is exercised by
    ``Orchestrator._import_publisher`` indirectly across the rest of
    the suite.
    """

    def test_omg_weblog_direct_fanout_surfaces_are_runtime_wired_and_resolve(self):
        import importlib

        from agents.publication_bus.surface_registry import dispatch_registry
        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY
        from shared.preprint_artifact import OMG_WEBLOG_DIRECT_FANOUT_SURFACES

        canonical_dispatch = dispatch_registry()
        for surface in OMG_WEBLOG_DIRECT_FANOUT_SURFACES:
            assert surface in SURFACE_REGISTRY
            assert SURFACE_REGISTRY[surface] == canonical_dispatch[surface]
            module_path, attr = SURFACE_REGISTRY[surface].split(":")
            module = importlib.import_module(module_path)
            assert callable(getattr(module, attr))

    def test_bluesky_post_wired(self):
        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        assert "bluesky-post" in SURFACE_REGISTRY
        assert SURFACE_REGISTRY["bluesky-post"] == (
            "agents.cross_surface.bluesky_post:publish_artifact"
        )

    def test_mastodon_post_wired(self):
        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        assert "mastodon-post" in SURFACE_REGISTRY
        assert SURFACE_REGISTRY["mastodon-post"] == (
            "agents.cross_surface.mastodon_post:publish_artifact"
        )

    def test_bluesky_entry_resolves(self):
        """Importing the registered entry-point must not raise."""
        import importlib

        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        module_path, attr = SURFACE_REGISTRY["bluesky-post"].split(":")
        mod = importlib.import_module(module_path)
        fn = getattr(mod, attr)
        assert callable(fn)

    def test_mastodon_entry_resolves(self):
        import importlib

        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        module_path, attr = SURFACE_REGISTRY["mastodon-post"].split(":")
        mod = importlib.import_module(module_path)
        fn = getattr(mod, attr)
        assert callable(fn)

    def test_arena_post_wired(self):
        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        assert "arena-post" in SURFACE_REGISTRY
        assert SURFACE_REGISTRY["arena-post"] == (
            "agents.cross_surface.arena_post:publish_artifact"
        )

    def test_arena_entry_resolves(self):
        import importlib

        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        module_path, attr = SURFACE_REGISTRY["arena-post"].split(":")
        mod = importlib.import_module(module_path)
        fn = getattr(mod, attr)
        assert callable(fn)

    def test_discord_webhook_refused_not_in_dispatch(self):
        """discord-webhook was retired 2026-05-01 per cc-task
        ``discord-public-event-activation-or-retire``. Constitutional refusal
        per ``leverage-REFUSED-discord-community`` (single-operator axiom +
        full-automation envelope). The surface still exists in the canonical
        registry as REFUSED tier so refusal_brief / dashboard can enumerate it,
        but the runtime dispatch registry (FULL_AUTO + CONDITIONAL_ENGAGE only)
        must not include it.
        """
        from agents.publication_bus.surface_registry import (
            SURFACE_REGISTRY as CANONICAL,
        )
        from agents.publication_bus.surface_registry import (
            AutomationStatus,
        )
        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        assert CANONICAL["discord-webhook"].automation_status == AutomationStatus.REFUSED, (
            "discord-webhook must be REFUSED tier in canonical surface_registry"
        )
        assert "discord-webhook" not in SURFACE_REGISTRY, (
            "discord-webhook must not appear in the orchestrator dispatch "
            "registry (REFUSED surfaces are quarantined from runtime fanout)"
        )

    def test_zenodo_doi_wired(self):
        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        assert "zenodo-doi" in SURFACE_REGISTRY
        assert SURFACE_REGISTRY["zenodo-doi"] == ("agents.zenodo_publisher:publish_artifact")

    def test_zenodo_entry_resolves(self):
        import importlib

        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        module_path, attr = SURFACE_REGISTRY["zenodo-doi"].split(":")
        mod = importlib.import_module(module_path)
        fn = getattr(mod, attr)
        assert callable(fn)

    def test_omg_weblog_wired(self):
        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        assert "omg-weblog" in SURFACE_REGISTRY
        assert SURFACE_REGISTRY["omg-weblog"] == ("agents.omg_weblog_publisher:publish_artifact")

    def test_omg_weblog_entry_resolves(self):
        import importlib

        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        module_path, attr = SURFACE_REGISTRY["omg-weblog"].split(":")
        mod = importlib.import_module(module_path)
        fn = getattr(mod, attr)
        assert callable(fn)

    def test_alphaxiv_comments_not_runtime_wired(self):
        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        assert "alphaxiv-comments" not in SURFACE_REGISTRY
