"""Aggregate publication hardening gate for publication-bus artifacts."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.governance.omg_referent import ENV_OPERATOR_LEGAL_NAME
from shared.operator_referent import REFERENTS
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

    name: Literal["lint", "known_entities", "legal_name", "codebase", "review"]
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
        legal_name_child = self._legal_name_child(_artifact_legal_name_surface(artifact))
        codebase_child = self._codebase_child(text, context)

        if legal_name_child.decision == PublicationGateDecision.REJECT:
            # corporate_boundary egress: a detected legal name must NOT leave the
            # trust boundary. Withhold the draft from the external review LLM — the
            # only egressing child — rather than send a leaked draft out to be
            # rejected. lint / known_entities / codebase are local and still run.
            review_child = PublicationGateChildResult(
                name="review",
                decision=PublicationGateDecision.REJECT,
                findings=(
                    "review skipped: legal-name REJECT withheld the draft from "
                    "external review (corporate_boundary egress guard)",
                ),
            )
            review_report_fm: dict[str, object] | None = None
        else:
            review_child, review_report = self._review_child(text, artifact, lint_child)
            review_report_fm = review_report.to_frontmatter()

        child_results = (
            lint_child,
            entity_child,
            legal_name_child,
            codebase_child,
            review_child,
        )
        decision = _aggregate_decision(child_results)
        flagged = _flagged_issues(child_results)
        override, override_error = _publication_gate_override(artifact)

        if override_error:
            flagged = (*flagged, override_error)

        if decision == PublicationGateDecision.HOLD and override is not None:
            decision = PublicationGateDecision.OPERATOR_OVERRIDDEN_HOLD
        elif decision == PublicationGateDecision.REJECT and override is not None:
            flagged = (*flagged, "operator_override_ignored_for_reject")

        result = PublicationGateResult(
            decision=decision,
            generated_at=datetime.now(UTC).isoformat(),
            child_results=child_results,
            flagged_issues=flagged,
            override=override
            if decision == PublicationGateDecision.OPERATOR_OVERRIDDEN_HOLD
            else None,
            review_report=review_report_fm,
        )
        return _redacted_receipt(result)

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

    def _legal_name_child(self, text: str) -> PublicationGateChildResult:
        """REJECT when the operator's personal legal name appears in the text.

        Anchors ``corporate_boundary`` (the operator's personal legal name must
        never reach a public surface) at the one path every artifact traverses
        before fan-out. REJECT is non-overridable: a legal-name leak cannot be
        released by a ``by_referent`` operator override.

        Scans the artifact's full public identity surface — the authored
        publication text PLUS the co-author and other authored public fields
        enumerated in :func:`_artifact_legal_name_surface` (co-author identity,
        slug, embed URL, source path, approval referent) — matched by
        :func:`_legal_name_pattern`, whose flexible separator class catches the
        name across slug/URL separators, wrapped whitespace, or adjacent fields.
        The scan reads the surface unchanged: it does NOT use
        ``omg_referent.safe_render`` (which renders the
        ``{operator}`` template token stochastically, with ``segment_id=None``,
        mutating the scanned text and making the decision non-deterministic — a
        scanner must read what the author wrote). The operator's legal name is
        injected only at the per-surface *formal* render, downstream of this gate;
        it must never appear in the authored artifact.

        When the pattern source ``HAPAX_OPERATOR_NAME`` is unconfigured the scan
        cannot run; the child PASSES but records a ``legal_name_guard_unconfigured``
        finding in the gate receipt's ``child_results`` so a disabled guard is
        visible (advisory, not a decision-affecting flagged issue) rather than
        silently no-opping.
        """
        pattern = os.environ.get(ENV_OPERATOR_LEGAL_NAME, "").strip()
        if not pattern:
            return PublicationGateChildResult(
                name="legal_name",
                decision=PublicationGateDecision.PASS,
                findings=(
                    "legal_name_guard_unconfigured: HAPAX_OPERATOR_NAME unset — "
                    "provision it (e.g. via `pass`) to arm the corporate_boundary guard",
                ),
            )
        if _legal_name_pattern(pattern).search(text):
            # Omit the matched substring: the receipt must never re-emit the leak.
            return PublicationGateChildResult(
                name="legal_name",
                decision=PublicationGateDecision.REJECT,
                findings=(
                    "operator legal name detected in publication surface — replace "
                    "it with a canonical referent (The Operator / Oudepode / OTO), "
                    "or restrict formal legal-name use to the per-surface formal "
                    "render rather than the authored artifact",
                ),
            )
        return PublicationGateChildResult(
            name="legal_name",
            decision=PublicationGateDecision.PASS,
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


_AUTHORIZED_OVERRIDE_REFERENTS: frozenset[str] = frozenset(
    referent.casefold() for referent in REFERENTS
)
"""Case-folded referents permitted to author a HOLD override. Sourced from the
canonical non-formal referent set (``shared.operator_referent.REFERENTS``);
personal legal names are excluded by construction — an override is a public
audit record and must not embed the operator's legal identity."""


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
    if by_referent.casefold() not in _AUTHORIZED_OVERRIDE_REFERENTS:
        return None, (
            "operator_override_invalid: unauthorized_referent — author the override "
            "with a canonical referent (The Operator / Oudepode / OTO)"
        )
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


def _artifact_legal_name_surface(artifact: PreprintArtifact) -> str:
    """Every authored field a publisher can render the operator's identity into.

    Superset of ``_artifact_publication_text``: adds each co-author's identity
    fields (``name`` / ``given_names`` / ``family_names`` / ``alias``) and the
    other authored fields that reach a public surface — ``slug`` (public URLs /
    filenames / event-ids), ``embed_image_url``, ``source_path``, and
    ``approved_by_referent``. Publishers render co-authors into public metadata
    (Zenodo ``creators``, OSF, CFF ``authors``) even when ``attribution_block`` is
    empty, so a legal name there leaks just like a byline. Fields are newline-joined
    and matched by :func:`_legal_name_pattern`, whose flexible separator class
    catches the name however it is rendered: split across separators (``jane-doe``),
    whitespace (a wrapped ``Jane\\nDoe``), or two adjacent fields. The default
    co-authors carry the referent (``Oudepode`` / ``The Operator`` / ``OTO``),
    never a legal name; the legal name is injected only at the per-surface formal
    render, downstream of this gate.
    """
    parts: list[str] = [_artifact_publication_text(artifact)]
    for author in artifact.co_authors:
        parts.extend(
            field
            for field in (author.name, author.given_names, author.family_names, author.alias)
            if field
        )
    parts.extend(
        field
        for field in (
            artifact.slug,
            artifact.embed_image_url,
            artifact.source_path,
            artifact.approved_by_referent,
        )
        if field
    )
    return "\n".join(part for part in parts if part)


def _legal_name_pattern(name: str) -> re.Pattern[str]:
    """Case-insensitive regex matching the legal name with a flexible separator
    class between tokens, so detection and redaction both catch the name however a
    publisher renders it: ``Jane Doe`` (byline), ``jane-doe`` / ``jane_doe`` (slug /
    URL), ``Jane  Doe`` or a line-wrapped ``Jane\\nDoe`` (prose), or a name split
    across two adjacent fields. Symmetry is the point — the SAME pattern gates the
    REJECT and scrubs the receipt, so a detected leak can never survive unredacted.
    """
    tokens = [re.escape(token) for token in name.split()]
    body = r"[-_/.\s]+".join(tokens) if tokens else re.escape(name)
    return re.compile(body, re.IGNORECASE)


_LEGAL_NAME_REDACTION = "[redacted: operator legal name]"


def _redact_legal_name(value: object, regex: re.Pattern[str]) -> object:
    """Recursively replace the configured legal name with a redaction token in
    every string of a JSON-serializable receipt structure, using the SAME
    flexible-separator pattern as detection so a detected ``jane-doe`` slug is
    scrubbed too (not just the literal ``Jane Doe``).

    Mapping keys (field names) are left intact; only values are scrubbed.
    """
    if isinstance(value, str):
        return regex.sub(_LEGAL_NAME_REDACTION, value)
    if isinstance(value, Mapping):
        return {key: _redact_legal_name(item, regex) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_legal_name(item, regex) for item in value]
    return value


def _redacted_receipt(result: PublicationGateResult) -> PublicationGateResult:
    """Final chokepoint: scrub the configured operator legal name from every string
    in the serialized receipt before it is returned.

    The legal-name child omits the match from its OWN finding, but the same name can
    still reach the receipt through an operator override ``reason`` or a
    reviewer-echoed ``review_report`` (the production ``ReviewPass`` returns claim
    text). Redacting the serialized form closes the re-emission CLASS for every
    field at once — including fields added later — rather than each instance.
    """
    pattern = os.environ.get(ENV_OPERATOR_LEGAL_NAME, "").strip()
    if not pattern:
        return result
    scrubbed = _redact_legal_name(result.model_dump(mode="json"), _legal_name_pattern(pattern))
    return PublicationGateResult.model_validate(scrubbed)


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
