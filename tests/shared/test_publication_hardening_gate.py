"""Tests for the aggregate publication hardening gate."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from shared.co_author_model import OUDEPODE
from shared.preprint_artifact import PreprintArtifact
from shared.publication_hardening.codebase import (
    CodebaseDecision,
    CodebaseVerificationReport,
)
from shared.publication_hardening.gate import (
    PublicationGateContext,
    PublicationGateDecision,
    PublicationHardeningGate,
    publication_gate_fingerprint,
)
from shared.publication_hardening.lint import LintFinding
from shared.publication_hardening.review import ReviewReport


class _ReviewPass:
    threshold = 0.7

    def __init__(self, confidence: float = 0.99, flagged: tuple[str, ...] = ()) -> None:
        self.confidence = confidence
        self.flagged = flagged

    def review_text(self, text: str, **kwargs) -> ReviewReport:  # type: ignore[no-untyped-def]
        del text
        return ReviewReport(
            reviewer_model="test-reviewer",
            author_model=kwargs.get("author_model"),
            overall_confidence=self.confidence,
            flagged_issues=self.flagged,
        )


def _artifact(**overrides) -> PreprintArtifact:
    defaults = {
        "slug": "gate-test",
        "title": "Gate Test",
        "body_md": "Body.",
        "surfaces_targeted": ["omg-weblog"],
    }
    defaults.update(overrides)
    return PreprintArtifact(**defaults)


def _gate(
    *,
    lint_findings: tuple[LintFinding, ...] = (),
    codebase_decision: CodebaseDecision = CodebaseDecision.PASS,
    review_confidence: float = 0.99,
) -> PublicationHardeningGate:
    return PublicationHardeningGate(
        repo_root=Path.cwd(),
        review_pass=_ReviewPass(confidence=review_confidence),
        lint_runner=lambda _text, _source_path: lint_findings,
        entity_checker=lambda _text: (),
        codebase_verifier=lambda _text, _context: CodebaseVerificationReport(
            decision=codebase_decision
        ),
    )


def test_gate_passes_when_all_child_reports_pass() -> None:
    result = _gate().evaluate(_artifact())

    assert result.decision == PublicationGateDecision.PASS
    assert result.passes()
    assert {child.name for child in result.child_results} == {
        "lint",
        "known_entities",
        "legal_name",
        "codebase",
        "review",
    }


def test_review_low_confidence_holds() -> None:
    result = _gate(review_confidence=0.2).evaluate(_artifact())

    assert result.decision == PublicationGateDecision.HOLD
    assert not result.passes()


def test_deterministic_reject_dominates_review_pass() -> None:
    lint_error = LintFinding(
        file="artifact:gate-test",
        line=1,
        level="error",
        rule="Hapax.PublicClaimOverreach",
        message="hard failure",
    )

    result = _gate(lint_findings=(lint_error,), review_confidence=0.99).evaluate(_artifact())

    assert result.decision == PublicationGateDecision.REJECT
    assert not result.passes()


def test_codebase_hold_can_be_operator_overridden() -> None:
    artifact = _artifact(
        publication_gate_override={
            "by_referent": "Oudepode",
            "reason": "Receipts checked manually",
        }
    )
    result = _gate(codebase_decision=CodebaseDecision.HOLD).evaluate(artifact)

    assert result.decision == PublicationGateDecision.OPERATOR_OVERRIDDEN_HOLD
    assert result.passes()
    assert result.override is not None
    assert result.override.by_referent == "Oudepode"


def test_reject_cannot_be_operator_overridden() -> None:
    artifact = _artifact(
        publication_gate_override={
            "by_referent": "Oudepode",
            "reason": "Receipts checked manually",
        }
    )
    result = _gate(codebase_decision=CodebaseDecision.REJECT).evaluate(artifact)

    assert result.decision == PublicationGateDecision.REJECT
    assert not result.passes()
    assert result.override is None
    assert "operator_override_ignored_for_reject" in result.flagged_issues


def test_gate_rejects_operator_legal_name_in_attribution(monkeypatch) -> None:
    """corporate_boundary: a personal legal name in the artifact text is a
    non-overridable REJECT at the aggregate gate, independent of publisher."""
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Real Person")
    result = _gate().evaluate(
        _artifact(attribution_block="Real Person (distributor) · Hapax (performer)")
    )

    assert result.decision == PublicationGateDecision.REJECT
    assert not result.passes()
    assert any(child.name == "legal_name" for child in result.child_results)


def test_gate_legal_name_guard_warns_when_unconfigured(monkeypatch) -> None:
    """Unset HAPAX_OPERATOR_NAME = the guard is a no-op; the gate must surface
    this as an explicit finding, never silently disable the guard."""
    monkeypatch.delenv("HAPAX_OPERATOR_NAME", raising=False)
    result = _gate().evaluate(_artifact(attribution_block="Real Person, Hapax"))

    legal = next(c for c in result.child_results if c.name == "legal_name")
    assert any("unconfigured" in finding for finding in legal.findings)
    # advisory, not a decision-affecting flagged issue
    assert not any("unconfigured" in issue for issue in result.flagged_issues)
    assert result.decision == PublicationGateDecision.PASS


def test_gate_rejects_operator_legal_name_in_co_authors(monkeypatch) -> None:
    """corporate_boundary: a legal name in a co-author's identity fields — which
    publishers render into public metadata (Zenodo creators, CFF authors) — is a
    REJECT, even when it never appears in the authored body or byline. This is the
    co_authors coverage gap (gate scanned only _artifact_publication_text)."""
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Jane Doe")
    artifact = _artifact(
        attribution_block="Oudepode (distributor) · Hapax (performer)",
        co_authors=[replace(OUDEPODE, given_names="Jane", family_names="Doe")],
    )
    result = _gate().evaluate(artifact)

    assert result.decision == PublicationGateDecision.REJECT
    assert not result.passes()
    legal = next(c for c in result.child_results if c.name == "legal_name")
    assert legal.decision == PublicationGateDecision.REJECT


def test_gate_legal_name_configured_but_clean_passes(monkeypatch) -> None:
    """The live-guard happy path (most common production state once provisioned):
    HAPAX_OPERATOR_NAME is set and the artifact is clean. The guard ran (no
    'unconfigured' finding) and PASSED — distinct from the unset-env no-op."""
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Jane Doe")
    result = _gate().evaluate(_artifact(attribution_block="Oudepode · Hapax"))

    legal = next(c for c in result.child_results if c.name == "legal_name")
    assert legal.decision == PublicationGateDecision.PASS
    assert not any("unconfigured" in finding for finding in legal.findings)
    assert result.decision == PublicationGateDecision.PASS


def test_gate_reject_receipt_omits_leaked_name(monkeypatch) -> None:
    """Non-re-emission invariant: a rejected receipt must never echo the matched
    legal name — not in any child finding, not in the serialized frontmatter.
    A privacy guard that leaks the name into its own audit record is self-defeating."""
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Jane Doe")
    result = _gate().evaluate(
        _artifact(attribution_block="Jane Doe (distributor) · Hapax (performer)")
    )

    assert result.decision == PublicationGateDecision.REJECT
    assert all("Jane Doe" not in finding for c in result.child_results for finding in c.findings)
    assert "Jane Doe" not in str(result.to_frontmatter())


def test_gate_override_rejects_unauthorized_referent() -> None:
    """A HOLD override authored by a non-ratified referent is invalid: the
    HOLD stands and the receipt flags the unauthorized referent."""
    artifact = _artifact(
        publication_gate_override={"by_referent": "Real Person", "reason": "ship it"},
    )
    result = _gate(review_confidence=0.2).evaluate(artifact)

    assert result.decision == PublicationGateDecision.HOLD
    assert result.override is None
    assert any("unauthorized_referent" in issue for issue in result.flagged_issues)


def test_gate_override_accepts_case_insensitive_referent() -> None:
    """A valid non-formal referent in any casing authors a HOLD override."""
    artifact = _artifact(
        publication_gate_override={"by_referent": "oudepode", "reason": "receipts checked"},
    )
    result = _gate(codebase_decision=CodebaseDecision.HOLD).evaluate(artifact)

    assert result.decision == PublicationGateDecision.OPERATOR_OVERRIDDEN_HOLD
    assert result.passes()
    assert result.override is not None


def test_gate_context_is_passed_to_codebase_verifier() -> None:
    seen: list[PublicationGateContext] = []

    def verifier(_text: str, context: PublicationGateContext) -> CodebaseVerificationReport:
        seen.append(context)
        return CodebaseVerificationReport(decision=CodebaseDecision.PASS)

    gate = PublicationHardeningGate(
        repo_root=Path.cwd(),
        review_pass=_ReviewPass(),
        lint_runner=lambda _text, _source_path: (),
        entity_checker=lambda _text: (),
        codebase_verifier=verifier,
    )
    artifact = _artifact(
        publication_gate_context={
            "numeric_expectations": {"42 hooks": 42},
            "currentness_evidence_refs": ["receipt:hn-readiness"],
        }
    )

    result = gate.evaluate(artifact)

    assert result.decision == PublicationGateDecision.PASS
    assert seen[0].numeric_expectations == {"42 hooks": 42}
    assert seen[0].currentness_evidence_refs == ("receipt:hn-readiness",)


def test_gate_fingerprint_is_stable() -> None:
    result = _gate().evaluate(_artifact())

    assert publication_gate_fingerprint(result) == publication_gate_fingerprint(
        result.to_frontmatter()
    )
