"""Polysemic-audit CI gate scaffold (V5 weave wk1 d2-d4 — epsilon).

Pins the contract for ``agents.authoring.polysemic_audit``: every
artifact passes through this gate before entering the approval queue.
The audit scans for unintended cross-domain readings — especially
where a term has divergent established meanings in legal /
governance / AI-safety registers.

Per V5 weave § 12 invariant 5: "Polysemic audit — every artifact
passes ``agents/authoring/polysemic_audit.py`` CI gate before
approval-queue entry. Audit checks for unintended cross-domain
readings (esp. legal/governance/AI-safety polysemy)."

Wk1 d2 (this scaffold): API contract + minimal seed registry + tests.
Wk1 d4 (PUB-CITATION-A): registry expansion + CI integration.

This is a SCAFFOLD: false-negative bias is intentional. Better to
miss a borderline polysemy than to spam the approval queue with
flagged-for-review noise on legitimate prose. Wk1 d4's expansion
adds curated terms after operator review.
"""

from __future__ import annotations

import pytest

from agents.authoring.polysemic_audit import (
    PolysemicAuditResult,
    PolysemicConcern,
    audit_artifact,
)

# ── Empty / minimal artifact ─────────────────────────────────────────


class TestEmptyArtifact:
    def test_empty_string_passes(self) -> None:
        result = audit_artifact("")
        assert result.passed is True
        assert result.concerns == ()

    def test_whitespace_only_passes(self) -> None:
        result = audit_artifact("   \n\n  \t")
        assert result.passed is True


# ── Result model ─────────────────────────────────────────────────────


class TestResultShape:
    def test_passed_when_no_concerns(self) -> None:
        result = audit_artifact("This is a benign paragraph about cats.")
        assert isinstance(result, PolysemicAuditResult)
        assert result.passed is True
        assert isinstance(result.concerns, tuple)

    def test_concerns_is_tuple_of_PolysemicConcern(self) -> None:
        # An artifact mixing legal and AI-safety meanings of "compliance"
        # within close proximity should flag at least one concern.
        text = (
            "Our compliance gate enforces the constitutional axioms; "
            "this is GDPR compliance for the artifact's persistence."
        )
        result = audit_artifact(text)
        for concern in result.concerns:
            assert isinstance(concern, PolysemicConcern)


# ── Cross-domain ambiguity detection (seed) ──────────────────────────


class TestCrossDomainPolysemy:
    """Seed registry should flag at least the obvious cross-domain
    cases. The full registry expands at wk1 d4 PUB-CITATION-A."""

    def test_flags_compliance_in_legal_and_ai_proximity(self) -> None:
        """``compliance`` reads as GDPR/HIPAA in legal register and as
        rule-following in AI-safety register. Same paragraph mixing both
        is a polysemy hazard for academic readers."""
        text = (
            "GDPR compliance and HIPAA compliance govern our data flows. "
            "The model's compliance with operator directives is gate-enforced."
        )
        result = audit_artifact(text)
        assert any("compliance" in c.term.lower() for c in result.concerns), (
            f"Expected 'compliance' polysemy concern; got concerns={result.concerns}"
        )

    def test_flags_governance_polysemy(self) -> None:
        """``governance`` has a corporate/board meaning AND an
        AI-governance meaning. Mixing both registers without explicit
        framing is the polysemy hazard."""
        text = (
            "Corporate governance principles inform the board's decisions. "
            "Model governance ensures axiom-bound behavior."
        )
        result = audit_artifact(text)
        assert any("governance" in c.term.lower() for c in result.concerns)

    def test_flags_safety_polysemy(self) -> None:
        """``safety`` reads as workplace/product safety in legal-OSHA
        register and as alignment-safety in AI register."""
        text = (
            "Product safety regulations cover the device's operational scope. "
            "AI safety research focuses on alignment guarantees."
        )
        result = audit_artifact(text)
        assert any("safety" in c.term.lower() for c in result.concerns)


# ── Single-register text — clean ─────────────────────────────────────


class TestSingleRegisterClean:
    """Text staying within one register should NOT flag — even if it
    uses polysemic terms — because the single-register usage is
    unambiguous."""

    def test_legal_only_compliance_passes(self) -> None:
        """All-legal context for 'compliance' is unambiguous —
        no AI-register collision."""
        text = (
            "GDPR compliance and HIPAA compliance are the two regulatory "
            "frameworks our data-processing must satisfy."
        )
        result = audit_artifact(text)
        # Single-register usage shouldn't flag the term.
        compliance_concerns = [c for c in result.concerns if "compliance" in c.term.lower()]
        assert compliance_concerns == [], (
            f"Single-register usage should not flag; got {compliance_concerns}"
        )

    def test_ai_only_governance_passes(self) -> None:
        text = (
            "Model governance and prompt governance are the two layers "
            "our orchestrator relies on for axiom-bound behavior."
        )
        result = audit_artifact(text)
        governance_concerns = [c for c in result.concerns if "governance" in c.term.lower()]
        assert governance_concerns == []


# ── Concern shape ────────────────────────────────────────────────────


class TestPolysemicConcernShape:
    def test_concern_has_term_and_excerpt(self) -> None:
        text = "GDPR compliance concerns. AI compliance behavior is axiom-bound."
        result = audit_artifact(text)
        for concern in result.concerns:
            assert concern.term
            assert concern.excerpt
            assert isinstance(concern.term, str)
            assert isinstance(concern.excerpt, str)


# ── PolysemicConcern dataclass ───────────────────────────────────────


class TestPolysemicConcernDataclass:
    def test_concern_is_constructable(self) -> None:
        concern = PolysemicConcern(
            term="compliance",
            excerpt="GDPR compliance ... model's compliance with directives",
            registers=("legal", "ai_safety"),
        )
        assert concern.term == "compliance"
        assert concern.registers == ("legal", "ai_safety")


@pytest.mark.parametrize(
    "term",
    ["compliance", "governance", "safety"],
)
class TestSeedRegistryCoverage:
    """Seed registry covers the V5-spec'd "legal/governance/AI-safety
    polysemy" core. Wk1 d4 expansion adds more terms after operator
    review."""

    def test_term_in_seed_registry(self, term: str) -> None:
        from agents.authoring.polysemic_audit import SEED_POLYSEMIC_TERMS

        assert term in SEED_POLYSEMIC_TERMS
