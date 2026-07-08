"""Tests for the RDLC/SDLC experimental disposition adapter."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.preprint_artifact import ApprovalState, PreprintArtifact
from shared.rdlc_experimental_disposition import (
    RdlcDispositionError,
    RdlcDispositionKind,
    RdlcDispositionReceipt,
    RdlcExperimentalObservation,
    RdlcTaskConversion,
    build_disposition_receipt,
    build_preprint_draft_from_disposition,
)


def _observation(**overrides) -> RdlcExperimentalObservation:
    defaults = {
        "observation_id": "obs-trainyard-4459-head",
        "source_refs": ("github:hapax-systems/hapax-council#4459",),
        "authority_case": "CASE-RDLC-SDLC-EXPERIMENTAL-CONTEXT-20260704",
        "parent_spec": (
            "/home/hapax/Documents/Personal/30-areas/hapax/"
            "rdlc-sdlc-experimental-loop-publication-program-2026-07-04.md"
        ),
        "observation_kind": "pr_admission",
        "intervention": "stale rebuild drop-in cleanup",
        "outcome": "checks green except release-governance blocker",
        "claim_ceiling": "support_non_authoritative internal research context",
        "evidence_refs": ("review-dossier:trainyard-gap1:a35262fe",),
    }
    defaults.update(overrides)
    return RdlcExperimentalObservation(**defaults)


def test_observation_is_immutable() -> None:
    observation = _observation()

    with pytest.raises(ValidationError):
        observation.outcome = "rewritten"  # type: ignore[misc]


def test_missing_custody_blocks_non_blocked_disposition() -> None:
    observation = _observation(
        source_refs=("",),
        authority_case=None,
        parent_spec=" ",
        evidence_refs=("  ",),
    )

    receipt = build_disposition_receipt(
        observation,
        disposition=RdlcDispositionKind.SUPPORT_NON_AUTHORITATIVE,
        rationale="useful but missing custody",
    )

    assert receipt.disposition == RdlcDispositionKind.BLOCKED
    assert "missing_custody:source_refs" in receipt.blocked_reasons
    assert "missing_custody:authority_case" in receipt.blocked_reasons
    assert "missing_custody:parent_spec" in receipt.blocked_reasons
    assert "missing_custody:evidence_refs" in receipt.blocked_reasons
    with pytest.raises(RdlcDispositionError):
        build_preprint_draft_from_disposition(receipt, slug="x", title="X")


def test_direct_non_blocked_receipt_rejects_missing_custody() -> None:
    observation = _observation(evidence_refs=())

    with pytest.raises(RdlcDispositionError, match="non-blocked disposition requires custody"):
        RdlcDispositionReceipt(
            receipt_id="manual",
            observation=observation,
            disposition=RdlcDispositionKind.SUPPORT_NON_AUTHORITATIVE,
            rationale="manual bypass attempt",
        )


def test_publish_candidate_missing_freeze_inputs_blocks() -> None:
    receipt = build_disposition_receipt(
        _observation(),
        disposition=RdlcDispositionKind.PUBLISH_CANDIDATE,
        rationale="candidate, but not frozen",
        claim_text="The SDLC event supports a recurring RDLC observation pattern.",
    )

    assert receipt.disposition == RdlcDispositionKind.BLOCKED
    assert "missing_publish:frozen_ruler_ref" in receipt.blocked_reasons
    assert "missing_publish:public_safe_evidence_refs" in receipt.blocked_reasons
    assert "missing_publish:freshness_ref" in receipt.blocked_reasons
    with pytest.raises(RdlcDispositionError):
        build_preprint_draft_from_disposition(receipt, slug="x", title="X")


def test_publish_candidate_blank_evidence_refs_block() -> None:
    receipt = build_disposition_receipt(
        _observation(),
        disposition=RdlcDispositionKind.PUBLISH_CANDIDATE,
        rationale="candidate with blank public evidence",
        claim_text="The SDLC event supports a recurring RDLC observation pattern.",
        frozen_ruler_ref="sha256:rdlc-ruler",
        frozen_ruler_version="2026-07-08T02:40:00Z",
        public_safe_evidence_refs=(" ",),
        freshness_ref="gh:pr-4459:a35262fe",
        currentness_ref="gh:checks:2026-07-08T02:24Z",
    )

    assert receipt.disposition == RdlcDispositionKind.BLOCKED
    assert "missing_publish:public_safe_evidence_refs" in receipt.blocked_reasons


def test_publish_candidate_missing_claim_text_blocks() -> None:
    receipt = build_disposition_receipt(
        _observation(),
        disposition=RdlcDispositionKind.PUBLISH_CANDIDATE,
        rationale="candidate with missing claim text",
        frozen_ruler_ref="sha256:rdlc-ruler",
        frozen_ruler_version="2026-07-08T02:40:00Z",
        public_safe_evidence_refs=("public:pr-4459-check-summary",),
        freshness_ref="gh:pr-4459:a35262fe",
        currentness_ref="gh:checks:2026-07-08T02:24Z",
    )

    assert receipt.disposition == RdlcDispositionKind.BLOCKED
    assert "missing_publish:claim_text" in receipt.blocked_reasons


def test_direct_publish_candidate_rejects_missing_freeze_inputs() -> None:
    with pytest.raises(
        RdlcDispositionError,
        match="publish_candidate requires assay/freeze inputs",
    ):
        RdlcDispositionReceipt(
            receipt_id="manual-publish",
            observation=_observation(),
            disposition=RdlcDispositionKind.PUBLISH_CANDIDATE,
            rationale="manual bypass attempt",
            claim_text="The SDLC event supports a recurring RDLC observation pattern.",
            claim_ceiling="case-study candidate",
        )


def test_support_non_authoritative_preserves_context_without_artifact() -> None:
    receipt = build_disposition_receipt(
        _observation(),
        disposition="support_non_authoritative",
        rationale="keep as internal support, not a public claim",
    )

    assert receipt.disposition == RdlcDispositionKind.SUPPORT_NON_AUTHORITATIVE
    with pytest.raises(RdlcDispositionError, match="next action: provide a publish_candidate"):
        build_preprint_draft_from_disposition(receipt, slug="support", title="Support")


def test_convert_to_task_requires_structured_task_detail() -> None:
    observation = _observation(outcome="NDCVB supplied-direction path lacks held-out split")

    blocked = build_disposition_receipt(
        observation,
        disposition=RdlcDispositionKind.CONVERT_TO_TASK,
        rationale="needs governed NDCVB source work",
    )
    assert blocked.disposition == RdlcDispositionKind.BLOCKED
    assert "missing_task_conversion" in blocked.blocked_reasons

    receipt = build_disposition_receipt(
        observation,
        disposition=RdlcDispositionKind.CONVERT_TO_TASK,
        rationale="mint a source task for the retrofit",
        task_conversion=RdlcTaskConversion(
            title="NDCVB supplied-direction held-out split",
            mutation_scope_refs=(
                "non-deception-benchmark/ndcvb/whitebox/measure.py",
                "non-deception-benchmark/tests/test_whitebox.py",
            ),
            acceptance_refs=("noise direction scores near chance on held-out split",),
            rationale="prevents in-sample J-lens/DiffMean scoring",
        ),
    )

    assert receipt.disposition == RdlcDispositionKind.CONVERT_TO_TASK
    assert receipt.task_conversion is not None
    assert "measure.py" in receipt.task_conversion.mutation_scope_refs[0]


def test_convert_to_task_rejects_incomplete_task_minting_detail() -> None:
    incomplete = RdlcTaskConversion(
        title="NDCVB supplied-direction held-out split",
        rationale="prevents in-sample J-lens/DiffMean scoring",
    )

    blocked = build_disposition_receipt(
        _observation(outcome="NDCVB supplied-direction path lacks held-out split"),
        disposition=RdlcDispositionKind.CONVERT_TO_TASK,
        rationale="needs governed NDCVB source work",
        task_conversion=incomplete,
    )
    assert blocked.disposition == RdlcDispositionKind.BLOCKED
    assert "missing_task_conversion:mutation_scope_refs" in blocked.blocked_reasons
    assert "missing_task_conversion:acceptance_refs" in blocked.blocked_reasons

    with pytest.raises(
        RdlcDispositionError,
        match="convert_to_task requires task_conversion detail: mutation_scope_refs, "
        "acceptance_refs",
    ):
        RdlcDispositionReceipt(
            receipt_id="manual-convert",
            observation=_observation(),
            disposition=RdlcDispositionKind.CONVERT_TO_TASK,
            rationale="manual bypass attempt",
            task_conversion=incomplete,
        )


def test_publish_candidate_creates_draft_only_preprint_artifact(monkeypatch) -> None:
    write_attempts: list[tuple[str, str]] = []
    original_open = Path.open

    def fail_on_write(path: Path, mode: str = "r", *args, **kwargs):  # type: ignore[no-untyped-def]
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            write_attempts.append((str(path), mode))
            raise AssertionError(f"unexpected artifact write to {path} with mode {mode}")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_on_write)
    receipt = build_disposition_receipt(
        _observation(),
        disposition=RdlcDispositionKind.PUBLISH_CANDIDATE,
        rationale="all custody, assay, and freeze inputs are present",
        claim_text="This SDLC event is a publishable case study candidate under RDLC.",
        claim_ceiling="case-study candidate, not generalized causal proof",
        frozen_ruler_ref="sha256:rdlc-ruler",
        frozen_ruler_version="2026-07-08T02:40:00Z",
        public_safe_evidence_refs=("public:pr-4459-check-summary",),
        freshness_ref="gh:pr-4459:a35262fe",
        currentness_ref="gh:checks:2026-07-08T02:24Z",
    )

    artifact = build_preprint_draft_from_disposition(
        receipt,
        slug="rdlc-sdlc-case-study-candidate",
        title="RDLC SDLC Case Study Candidate",
        abstract="Draft only; publication bus egress remains separately gated.",
        surfaces_targeted=("osf-preprint",),
    )

    assert isinstance(artifact, PreprintArtifact)
    assert artifact.approval == ApprovalState.DRAFT
    assert artifact.surfaces_targeted == ["osf-preprint"]
    assert artifact.publication_gate_context is not None
    assert artifact.publication_gate_context["egress_state"] == "draft_only_no_inbox_write"
    assert artifact.publication_gate_context["currentness_evidence_refs"] == [
        "gh:checks:2026-07-08T02:24Z",
        "gh:pr-4459:a35262fe",
    ]
    assert artifact.publication_gate_context["currentness_ref"] == "gh:checks:2026-07-08T02:24Z"
    assert artifact.publication_gate_context["freshness_ref"] == "gh:pr-4459:a35262fe"
    assert "case-study candidate" in artifact.body_md
    assert "AuthorityCase: CASE-RDLC-SDLC-EXPERIMENTAL-CONTEXT-20260704" in artifact.body_md
    assert "Frozen ruler: sha256:rdlc-ruler@2026-07-08T02:40:00Z" in artifact.body_md
    assert "- public:pr-4459-check-summary" in artifact.body_md
    assert write_attempts == []
