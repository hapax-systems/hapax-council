"""Tests for the aggregate publication hardening gate."""

from __future__ import annotations

from pathlib import Path

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
