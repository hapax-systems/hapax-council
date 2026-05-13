"""Aggregate publication hardening gate for publication-bus artifacts."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.preprint_artifact import PreprintArtifact
from shared.publication_hardening.codebase import (
    CodebaseDecision,
    CodebaseVerificationReport,
    verify_publication_codebase,
)
from shared.publication_hardening.entity_checker import AttributionFinding, check_attributions
from shared.publication_hardening.lint import LintFinding, lint_file, lint_text
from shared.publication_hardening.review import (
    DEFAULT_REVIEW_THRESHOLD,
    ReviewPass,
    ReviewReport,
)


class PublicationGateDecision(StrEnum):
    """Terminal aggregate decisions for the pre-fanout hardening gate."""

    PASS = "pass"
    HOLD = "hold"
    REJECT = "reject"
    OPERATOR_OVERRIDDEN_HOLD = "operator_overridden_hold"


class PublicationGateModel(BaseModel):
    """Strict immutable base for publication gate models."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class PublicationGateOverride(PublicationGateModel):
    """Operator-provided hold override."""

    by_referent: str
    reason: str


class PublicationGateContext(PublicationGateModel):
    """Optional verifier context supplied by artifact frontmatter."""

    numeric_expectations: dict[str, object] = Field(default_factory=dict)
    currentness_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)


class PublicationGateChildResult(PublicationGateModel):
    """One child predicate result included in the gate receipt."""

    name: Literal["lint", "known_entities", "codebase", "review"]
    decision: PublicationGateDecision
    findings: tuple[str, ...] = Field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    report: dict[str, object] | None = None


class PublicationGateResult(PublicationGateModel):
    """Auditable aggregate decision for a publication artifact."""

    schema_version: Literal[1] = 1
    decision: PublicationGateDecision
    generated_at: str
    child_results: tuple[PublicationGateChildResult, ...]
    flagged_issues: tuple[str, ...] = Field(default_factory=tuple)
    override: PublicationGateOverride | None = None
    review_report: dict[str, object] | None = None

    def passes(self) -> bool:
        return self.decision in {
            PublicationGateDecision.PASS,
            PublicationGateDecision.OPERATOR_OVERRIDDEN_HOLD,
        }

    def to_frontmatter(self) -> dict[str, object]:
        return self.model_dump(mode="json")


LintRunner = Callable[[str, Path | None], Sequence[LintFinding]]
EntityChecker = Callable[[str], Sequence[AttributionFinding]]
CodebaseVerifier = Callable[[str, PublicationGateContext], CodebaseVerificationReport]


class PublicationHardeningGate:
    """Run all pre-fanout publication hardening checks."""

    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        review_pass: ReviewPass | None = None,
        lint_runner: LintRunner | None = None,
        entity_checker: EntityChecker | None = None,
        codebase_verifier: CodebaseVerifier | None = None,
    ) -> None:
        self.repo_root = repo_root or Path(__file__).resolve().parents[2]
        self.review_pass = review_pass or ReviewPass()
        self.lint_runner = lint_runner
        self.entity_checker = entity_checker or check_attributions
        self.codebase_verifier = codebase_verifier

    def evaluate(self, artifact: PreprintArtifact) -> PublicationGateResult:
        text = _artifact_publication_text(artifact)
        context = _publication_gate_context(artifact)
        lint_child = self._lint_child(text, artifact)
        entity_child = self._entity_child(text)
        codebase_child = self._codebase_child(text, context)
        review_child, review_report = self._review_child(text, artifact, lint_child)

        child_results = (lint_child, entity_child, codebase_child, review_child)
        decision = _aggregate_decision(child_results)
        flagged = _flagged_issues(child_results)
        override, override_error = _publication_gate_override(artifact)

        if override_error:
            flagged = (*flagged, override_error)

        if decision == PublicationGateDecision.HOLD and override is not None:
            decision = PublicationGateDecision.OPERATOR_OVERRIDDEN_HOLD
        elif decision == PublicationGateDecision.REJECT and override is not None:
            flagged = (*flagged, "operator_override_ignored_for_reject")

        return PublicationGateResult(
            decision=decision,
            generated_at=datetime.now(UTC).isoformat(),
            child_results=child_results,
            flagged_issues=flagged,
            override=override
            if decision == PublicationGateDecision.OPERATOR_OVERRIDDEN_HOLD
            else None,
            review_report=review_report.to_frontmatter(),
        )

    def _lint_child(
        self,
        text: str,
        artifact: PreprintArtifact,
    ) -> PublicationGateChildResult:
        source_path = Path(artifact.source_path).expanduser() if artifact.source_path else None
        if self.lint_runner is not None:
            findings = tuple(self.lint_runner(text, source_path))
        elif source_path is not None and source_path.exists():
            findings = tuple(lint_file(source_path))
        else:
            findings = tuple(lint_text(text, file_label=f"artifact:{artifact.slug}"))

        errors = tuple(finding for finding in findings if finding.level == "error")
        warnings = tuple(finding for finding in findings if finding.level != "error")
        if errors:
            decision = PublicationGateDecision.REJECT
        elif warnings:
            decision = PublicationGateDecision.HOLD
        else:
            decision = PublicationGateDecision.PASS

        return PublicationGateChildResult(
            name="lint",
            decision=decision,
            findings=tuple(_lint_finding_text(finding) for finding in findings),
        )

    def _entity_child(self, text: str) -> PublicationGateChildResult:
        findings = tuple(self.entity_checker(text))
        return PublicationGateChildResult(
            name="known_entities",
            decision=PublicationGateDecision.REJECT if findings else PublicationGateDecision.PASS,
            findings=tuple(str(finding) for finding in findings),
        )

    def _codebase_child(
        self,
        text: str,
        context: PublicationGateContext,
    ) -> PublicationGateChildResult:
        report = (
            self.codebase_verifier(text, context)
            if self.codebase_verifier is not None
            else verify_publication_codebase(
                text,
                repo_root=self.repo_root,
                numeric_expectations=context.numeric_expectations,
                currentness_evidence_refs=context.currentness_evidence_refs,
            )
        )
        decision = {
            CodebaseDecision.PASS: PublicationGateDecision.PASS,
            CodebaseDecision.HOLD: PublicationGateDecision.HOLD,
            CodebaseDecision.REJECT: PublicationGateDecision.REJECT,
        }[report.decision]
        return PublicationGateChildResult(
            name="codebase",
            decision=decision,
            findings=tuple(finding.message for finding in report.findings),
            evidence_refs=tuple(
                ref for finding in report.findings for ref in finding.evidence_refs
            ),
            report=report.model_dump(mode="json"),
        )

    def _review_child(
        self,
        text: str,
        artifact: PreprintArtifact,
        lint_child: PublicationGateChildResult,
    ) -> tuple[PublicationGateChildResult, ReviewReport]:
        report = self.review_pass.review_text(
            text,
            author_model=_artifact_author_model(artifact),
            lint_report="\n".join(lint_child.findings) or None,
            metadata={
                "slug": artifact.slug,
                "title": artifact.title,
                "source_path": artifact.source_path,
                "surfaces_targeted": artifact.surfaces_targeted,
            },
        )
        threshold = getattr(self.review_pass, "threshold", DEFAULT_REVIEW_THRESHOLD)
        decision = (
            PublicationGateDecision.PASS
            if report.passes(threshold=threshold)
            else PublicationGateDecision.HOLD
        )
        child = PublicationGateChildResult(
            name="review",
            decision=decision,
            findings=tuple(report.flagged_issues),
            report=report.to_frontmatter(),
        )
        return child, report


def publication_gate_fingerprint(result: PublicationGateResult | Mapping[str, object]) -> str:
    payload = result.to_frontmatter() if isinstance(result, PublicationGateResult) else dict(result)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return sha256(encoded).hexdigest()


def _aggregate_decision(
    child_results: Sequence[PublicationGateChildResult],
) -> PublicationGateDecision:
    if any(child.decision == PublicationGateDecision.REJECT for child in child_results):
        return PublicationGateDecision.REJECT
    if any(child.decision == PublicationGateDecision.HOLD for child in child_results):
        return PublicationGateDecision.HOLD
    return PublicationGateDecision.PASS


def _flagged_issues(child_results: Sequence[PublicationGateChildResult]) -> tuple[str, ...]:
    issues: list[str] = []
    for child in child_results:
        if child.decision == PublicationGateDecision.PASS:
            continue
        issues.extend(f"{child.name}: {finding}" for finding in child.findings)
    return tuple(issues)


def _publication_gate_context(artifact: PreprintArtifact) -> PublicationGateContext:
    raw = artifact.publication_gate_context or {}
    if not isinstance(raw, Mapping):
        return PublicationGateContext()
    numeric_expectations = raw.get("numeric_expectations")
    currentness_evidence_refs = raw.get("currentness_evidence_refs")
    refs: tuple[str, ...]
    if currentness_evidence_refs is None:
        refs = ()
    elif isinstance(currentness_evidence_refs, str):
        refs = (currentness_evidence_refs,)
    elif isinstance(currentness_evidence_refs, Sequence):
        refs = tuple(str(item) for item in currentness_evidence_refs if item is not None)
    else:
        refs = (str(currentness_evidence_refs),)
    return PublicationGateContext(
        numeric_expectations=dict(numeric_expectations)
        if isinstance(numeric_expectations, Mapping)
        else {},
        currentness_evidence_refs=refs,
    )


def _publication_gate_override(
    artifact: PreprintArtifact,
) -> tuple[PublicationGateOverride | None, str | None]:
    raw = artifact.publication_gate_override
    if raw is None:
        return None, None
    if not isinstance(raw, Mapping):
        return None, "operator_override_invalid: expected mapping"
    by_referent = str(raw.get("by_referent") or raw.get("referent") or raw.get("by") or "").strip()
    reason = str(raw.get("reason") or "").strip()
    if not by_referent or not reason:
        return None, "operator_override_invalid: referent_and_reason_required"
    normalized = {
        "by_referent": by_referent,
        "reason": reason,
    }
    try:
        return PublicationGateOverride.model_validate(normalized), None
    except Exception as exc:  # noqa: BLE001
        return None, f"operator_override_invalid: {type(exc).__name__}"


def _artifact_publication_text(artifact: PreprintArtifact) -> str:
    return "\n\n".join(
        part
        for part in (
            f"# {artifact.title}",
            artifact.abstract,
            artifact.attribution_block,
            artifact.body_md,
            artifact.body_html,
        )
        if part
    )


def _artifact_author_model(artifact: PreprintArtifact) -> str | None:
    if artifact.author_model:
        return artifact.author_model
    names = {author.name.lower() for author in artifact.co_authors}
    aliases = {author.alias.lower() for author in artifact.co_authors if author.alias}
    if "claude code" in names or "claude-code" in aliases:
        return "claude-code"
    return None


def _lint_finding_text(finding: LintFinding) -> str:
    return f"{finding.file}:{finding.line}:{finding.rule}:{finding.level}:{finding.message}"


__all__ = [
    "PublicationGateChildResult",
    "PublicationGateContext",
    "PublicationGateDecision",
    "PublicationGateOverride",
    "PublicationGateResult",
    "PublicationHardeningGate",
    "publication_gate_fingerprint",
]
