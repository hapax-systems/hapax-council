"""Evidence gate for GitHub public-material claims.

This is the GitHub-surface consumer for the reusable metadata public-claim gate
shipped by ``agents.metadata_composer.public_claim_gate``. It validates README,
profile, repo-description, package README, and release-note copy against a
material envelope instead of letting public prose promote stale or missing
evidence into claims.
"""

from __future__ import annotations

import enum
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from agents.metadata_composer.public_claim_gate import (
    ClaimEvidence,
    ClaimKind,
    Decision,
    PublicClaimGateDecision,
    evaluate_public_claim,
)


class GitHubPublicSurface(enum.StrEnum):
    """GitHub public-material surfaces covered by this gate."""

    README = "readme"
    PROFILE = "profile"
    REPO_DESCRIPTION = "repo_description"
    PACKAGE_README = "package_readme"
    RELEASE_NOTES = "release_notes"


class ResearchStatus(enum.StrEnum):
    """Research-status terms public material must not conflate."""

    IMPLEMENTED = "implemented"
    PILOT = "pilot"
    SPEC_READY = "spec_ready"
    DRY_RUN = "dry_run"
    PUBLIC_ARCHIVE = "public_archive"
    EMPIRICALLY_VALIDATED = "empirically_validated"


class GitHubClaimClass(enum.StrEnum):
    """Claim classes pinned by ``github-public-claim-evidence-gate``."""

    MATERIAL_CURRENTNESS = "material_currentness"
    LICENSE = "license"
    CONTRIBUTION_REFUSAL = "contribution_refusal"
    LIVE_CURRENT_SYSTEM = "live_current_system"
    RESEARCH_STATUS = "research_status"
    SUPPORT = "support"
    ARTIFACT = "artifact"
    MONETIZATION = "monetization"


@dataclass(frozen=True)
class GitHubMaterialEvidenceEnvelope:
    """Machine-readable evidence envelope for one GitHub public material."""

    surface: GitHubPublicSurface
    repo: str
    source_commit: str = ""
    current_source_commit: str = ""
    current_source_refs: tuple[str, ...] = ()
    generated_at: str = ""
    live_state_report_ref: str = ""
    live_state_report_generated_at: str = ""
    profile_repo_present: bool | None = None
    license_present: bool = False
    notice_present: bool = False
    citation_present: bool = False
    codemeta_present: bool = False
    zenodo_present: bool = False
    declared_license: str = ""
    github_detected_license: str = ""
    license_exception_disclosed: bool = False
    contributing_present: bool = False
    governance_present: bool = False
    has_issues: bool | None = None
    has_discussions: bool | None = None
    has_wiki: bool | None = None
    sponsor_surface_active: bool | None = None
    settings_witness_refs: tuple[str, ...] = ()
    issue_template_present: bool | None = None
    wcs_refs: tuple[str, ...] = ()
    publication_event_refs: tuple[str, ...] = ()
    current_ref_age_s: float | None = None
    max_current_ref_age_s: float = 86_400.0
    public_event_refs: tuple[str, ...] = ()
    research_status: ResearchStatus = ResearchStatus.SPEC_READY
    research_evidence_refs: tuple[str, ...] = ()
    support_conversion_ready: bool = False
    artifact_conversion_ready: bool = False
    monetization_conversion_ready: bool = False
    artifact_rights_refs: tuple[str, ...] = ()

    @property
    def material_current(self) -> bool:
        """Whether the material cites current source refs for this repo."""

        return bool(
            self.source_commit
            and self.current_source_refs
            and (not self.current_source_commit or self.current_source_commit == self.source_commit)
        )

    @property
    def license_evidence_complete(self) -> bool:
        """Whether license-claim witnesses satisfy the GitHub material spec."""

        files_present = all(
            (
                self.license_present,
                self.notice_present,
                self.citation_present,
                self.codemeta_present,
                self.zenodo_present,
            )
        )
        license_agrees = (
            bool(self.declared_license)
            and bool(self.github_detected_license)
            and self.github_detected_license == self.declared_license
        )
        return files_present and (license_agrees or self.license_exception_disclosed)

    @property
    def settings_witness_complete(self) -> bool:
        """Whether GitHub issue/discussion/wiki/sponsor settings are witnessed."""

        return bool(self.settings_witness_refs) and all(
            setting is not None
            for setting in (
                self.has_issues,
                self.has_discussions,
                self.has_wiki,
                self.sponsor_surface_active,
            )
        )

    @property
    def has_fresh_current_refs(self) -> bool:
        """Whether live/current claims have fresh WCS or publication evidence."""

        has_refs = bool(self.wcs_refs or self.publication_event_refs)
        fresh = (
            self.current_ref_age_s is not None
            and self.current_ref_age_s <= self.max_current_ref_age_s
        )
        return has_refs and fresh

    @property
    def has_public_event_refs(self) -> bool:
        """Whether conversion/artifact claims cite a public event row."""

        return bool(self.public_event_refs or self.publication_event_refs)


@dataclass(frozen=True)
class GitHubPublicClaimFinding:
    """One claim-gate decision for a detected GitHub public claim."""

    claim_class: GitHubClaimClass
    decision: Decision
    surface: GitHubPublicSurface
    reason: str
    claim_text: str
    correction: str = ""
    evidence_refs: tuple[str, ...] = ()

    @property
    def allows_emission(self) -> bool:
        """``True`` when the original public copy may be emitted."""

        return self.decision is Decision.ALLOW


@dataclass(frozen=True)
class GitHubPublicClaimGateVerdict:
    """Gate verdict for one GitHub public material."""

    surface: GitHubPublicSurface
    findings: tuple[GitHubPublicClaimFinding, ...]

    @property
    def allows_emission(self) -> bool:
        """``True`` iff every detected claim is supported."""

        return all(finding.allows_emission for finding in self.findings)

    @property
    def blocked_findings(self) -> tuple[GitHubPublicClaimFinding, ...]:
        """Findings that require dropping or correcting the original copy."""

        return tuple(finding for finding in self.findings if not finding.allows_emission)


_LICENSE_RE = re.compile(
    r"\b(?:license|licensed|apache|polyform|osi[-\s]?approved|open[-\s]?source|doi|"
    r"citation|citable)\b",
    re.IGNORECASE,
)
_ISSUE_DISABLED_RE = re.compile(
    r"\b(?:issues?|discussions?|wiki)\s+(?:are\s+)?(?:disabled|closed|refused|off)\b|"
    r"\b(?:no|without)\s+(?:issues?|discussions?|wiki)\b",
    re.IGNORECASE,
)
_ISSUE_INVITE_RE = re.compile(
    r"\b(?:open|file|raise|submit)\s+(?:an?\s+)?issues?\b|"
    r"\bissue\s+(?:tracker|queue|discussion|negotiation)\b",
    re.IGNORECASE,
)
_CONTRIBUTING_RE = re.compile(
    r"\b(?:contribut(?:e|ion|or|ors|ing)|pull\s+requests?|community|collaborat(?:e|ion))\b",
    re.IGNORECASE,
)
_SETTINGS_RE = re.compile(r"\b(?:discussions?|wiki|sponsors?)\b", re.IGNORECASE)
_LIVE_CURRENT_RE = re.compile(
    r"\b(?:live|live[-\s]?now|currently|current\s+system|running\s+now|"
    r"system\s+health|fresh\s+runtime|active\s+runtime)\b",
    re.IGNORECASE,
)
_SUPPORT_RE = re.compile(
    r"\b(?:support|sponsor|donate|funding|patreon|buy\s+me\s+a\s+coffee)\b",
    re.IGNORECASE,
)
_MONETIZATION_RE = re.compile(
    r"\b(?:monetiz(?:e|ed|ation)|paid|revenue|purchase|commercially\s+available)\b",
    re.IGNORECASE,
)
_ARTIFACT_RE = re.compile(
    r"\b(?:public\s+artifact|artifact\s+(?:ready|release|sale)|released\s+artifact|"
    r"release[-\s]?ready|downloadable\s+artifact|published\s+artifact)\b",
    re.IGNORECASE,
)
_RESEARCH_STATUS_PATTERNS: tuple[tuple[ResearchStatus, re.Pattern[str]], ...] = (
    (
        ResearchStatus.EMPIRICALLY_VALIDATED,
        re.compile(r"\b(?:empirically\s+validated|validated\s+empirically|proven)\b", re.I),
    ),
    (ResearchStatus.PUBLIC_ARCHIVE, re.compile(r"\bpublic[-\s]+archive\b", re.I)),
    (ResearchStatus.SPEC_READY, re.compile(r"\bspec[-\s]+ready\b", re.I)),
    (ResearchStatus.DRY_RUN, re.compile(r"\bdry[-\s]+run\b", re.I)),
    (ResearchStatus.PILOT, re.compile(r"\bpilot\b", re.I)),
    (ResearchStatus.IMPLEMENTED, re.compile(r"\bimplemented\b", re.I)),
)


def github_material_envelope_from_mapping(
    payload: Mapping[str, Any],
) -> GitHubMaterialEvidenceEnvelope:
    """Parse a JSON-like envelope mapping into the gate dataclass."""

    return GitHubMaterialEvidenceEnvelope(
        surface=GitHubPublicSurface(str(payload.get("surface", GitHubPublicSurface.README))),
        repo=str(payload.get("repo", "")),
        source_commit=str(payload.get("source_commit", "")),
        current_source_commit=str(payload.get("current_source_commit", "")),
        current_source_refs=_tuple_of_str(payload.get("current_source_refs", ())),
        generated_at=str(payload.get("generated_at", "")),
        live_state_report_ref=str(payload.get("live_state_report_ref", "")),
        live_state_report_generated_at=str(payload.get("live_state_report_generated_at", "")),
        profile_repo_present=_optional_bool(payload.get("profile_repo_present")),
        license_present=bool(payload.get("license_present", False)),
        notice_present=bool(payload.get("notice_present", False)),
        citation_present=bool(payload.get("citation_present", False)),
        codemeta_present=bool(payload.get("codemeta_present", False)),
        zenodo_present=bool(payload.get("zenodo_present", False)),
        declared_license=str(payload.get("declared_license", "")),
        github_detected_license=str(payload.get("github_detected_license", "")),
        license_exception_disclosed=bool(payload.get("license_exception_disclosed", False)),
        contributing_present=bool(payload.get("contributing_present", False)),
        governance_present=bool(payload.get("governance_present", False)),
        has_issues=_optional_bool(payload.get("has_issues")),
        has_discussions=_optional_bool(payload.get("has_discussions")),
        has_wiki=_optional_bool(payload.get("has_wiki")),
        sponsor_surface_active=_optional_bool(payload.get("sponsor_surface_active")),
        settings_witness_refs=_tuple_of_str(payload.get("settings_witness_refs", ())),
        issue_template_present=_optional_bool(payload.get("issue_template_present")),
        wcs_refs=_tuple_of_str(payload.get("wcs_refs", ())),
        publication_event_refs=_tuple_of_str(payload.get("publication_event_refs", ())),
        current_ref_age_s=_optional_float(payload.get("current_ref_age_s")),
        max_current_ref_age_s=float(payload.get("max_current_ref_age_s", 86_400.0)),
        public_event_refs=_tuple_of_str(payload.get("public_event_refs", ())),
        research_status=ResearchStatus(
            str(payload.get("research_status", ResearchStatus.SPEC_READY))
        ),
        research_evidence_refs=_tuple_of_str(payload.get("research_evidence_refs", ())),
        support_conversion_ready=bool(payload.get("support_conversion_ready", False)),
        artifact_conversion_ready=bool(payload.get("artifact_conversion_ready", False)),
        monetization_conversion_ready=bool(payload.get("monetization_conversion_ready", False)),
        artifact_rights_refs=_tuple_of_str(payload.get("artifact_rights_refs", ())),
    )


def evaluate_github_public_claims(
    text: str,
    envelope: GitHubMaterialEvidenceEnvelope | None,
    *,
    surface: GitHubPublicSurface | None = None,
) -> GitHubPublicClaimGateVerdict:
    """Evaluate GitHub public copy against a material evidence envelope."""

    selected_surface = surface or (envelope.surface if envelope else GitHubPublicSurface.README)
    if not text.strip():
        return GitHubPublicClaimGateVerdict(surface=selected_surface, findings=())

    if envelope is None:
        return GitHubPublicClaimGateVerdict(
            surface=selected_surface,
            findings=(
                GitHubPublicClaimFinding(
                    claim_class=GitHubClaimClass.MATERIAL_CURRENTNESS,
                    decision=Decision.REFUSE,
                    surface=selected_surface,
                    reason="missing GitHub material evidence envelope",
                    claim_text=_snippet(text),
                    correction="render as private draft or attach a current material envelope",
                ),
            ),
        )

    findings: list[GitHubPublicClaimFinding] = []
    if not envelope.material_current:
        findings.append(
            GitHubPublicClaimFinding(
                claim_class=GitHubClaimClass.MATERIAL_CURRENTNESS,
                decision=Decision.REFUSE,
                surface=envelope.surface,
                reason="material lacks current source refs or source_commit is stale",
                claim_text=_snippet(text),
                correction="regenerate from current source refs before publishing",
                evidence_refs=envelope.current_source_refs,
            )
        )

    if (
        envelope.surface is GitHubPublicSurface.PROFILE
        and envelope.profile_repo_present is not True
    ):
        findings.append(
            GitHubPublicClaimFinding(
                claim_class=GitHubClaimClass.MATERIAL_CURRENTNESS,
                decision=Decision.REFUSE,
                surface=envelope.surface,
                reason="profile README repo is missing/private or lacks root README.md",
                claim_text=_snippet(text),
                correction="publish only after the user profile repo is present and public",
                evidence_refs=envelope.current_source_refs,
            )
        )

    if _LICENSE_RE.search(text):
        findings.append(_license_finding(text, envelope))

    findings.extend(_contribution_findings(text, envelope))

    if _LIVE_CURRENT_RE.search(text):
        findings.append(_live_current_finding(text, envelope))

    findings.extend(_research_status_findings(text, envelope))

    if _SUPPORT_RE.search(text):
        findings.append(_support_finding(text, envelope))

    if _ARTIFACT_RE.search(text):
        findings.append(_artifact_finding(text, envelope))

    if _MONETIZATION_RE.search(text):
        findings.append(_monetization_finding(text, envelope))

    return GitHubPublicClaimGateVerdict(surface=envelope.surface, findings=tuple(findings))


def _license_finding(
    text: str, envelope: GitHubMaterialEvidenceEnvelope
) -> GitHubPublicClaimFinding:
    decision = evaluate_public_claim(
        ClaimKind.LICENSE_CLASS,
        ClaimEvidence(
            declared_license=envelope.declared_license,
            license_consistent=envelope.license_evidence_complete,
        ),
    )
    if decision.decision is Decision.ALLOW:
        return _finding_from_metadata(
            GitHubClaimClass.LICENSE,
            text,
            envelope,
            decision,
            evidence_refs=_license_refs(envelope),
        )
    missing = _missing_license_witnesses(envelope)
    reason = decision.reason
    if missing:
        reason = f"{reason}; missing witnesses: {', '.join(missing)}"
    elif (
        envelope.declared_license
        and envelope.github_detected_license
        and envelope.declared_license != envelope.github_detected_license
    ):
        reason = (
            f"{reason}; GitHub detects {envelope.github_detected_license!r} while "
            f"the envelope declares {envelope.declared_license!r}"
        )
    return GitHubPublicClaimFinding(
        claim_class=GitHubClaimClass.LICENSE,
        decision=decision.decision,
        surface=envelope.surface,
        reason=reason,
        claim_text=_snippet(text),
        correction=decision.correction or "state license posture as unreconciled",
        evidence_refs=_license_refs(envelope),
    )


def _contribution_findings(
    text: str, envelope: GitHubMaterialEvidenceEnvelope
) -> tuple[GitHubPublicClaimFinding, ...]:
    findings: list[GitHubPublicClaimFinding] = []
    if _ISSUE_DISABLED_RE.search(text):
        decision = evaluate_public_claim(
            ClaimKind.DISABLED_ISSUES,
            ClaimEvidence(issues_disabled=envelope.has_issues is False),
        )
        if not envelope.settings_witness_complete and decision.decision is Decision.ALLOW:
            decision = PublicClaimGateDecision(
                decision=Decision.REFUSE,
                kind=ClaimKind.DISABLED_ISSUES,
                reason="issue/discussion/wiki/sponsor settings witness is incomplete",
                correction="state issue/refusal posture as unreconciled",
            )
        findings.append(
            _finding_from_metadata(
                GitHubClaimClass.CONTRIBUTION_REFUSAL,
                text,
                envelope,
                decision,
                evidence_refs=envelope.settings_witness_refs,
            )
        )

    if _ISSUE_INVITE_RE.search(text):
        if envelope.has_issues is True and envelope.contributing_present:
            decision = Decision.ALLOW
            reason = "issues are enabled and CONTRIBUTING.md is present"
            correction = ""
        elif envelope.has_issues is not True:
            decision = Decision.REFUSE
            reason = "issue invitation without live has_issues=true witness"
            correction = "replace issue invitation with the governed receive-only/refusal path"
        else:
            decision = Decision.REFUSE
            reason = "issue invitation without CONTRIBUTING.md"
            correction = "publish CONTRIBUTING.md before inviting issues"
        if not envelope.settings_witness_complete and decision is Decision.ALLOW:
            decision = Decision.REFUSE
            reason = "issue invitation without complete live settings witnesses"
            correction = "mark issue posture unreconciled"
        findings.append(
            GitHubPublicClaimFinding(
                claim_class=GitHubClaimClass.CONTRIBUTION_REFUSAL,
                decision=decision,
                surface=envelope.surface,
                reason=reason,
                claim_text=_snippet(text),
                correction=correction,
                evidence_refs=envelope.settings_witness_refs,
            )
        )

    if _CONTRIBUTING_RE.search(text):
        if not envelope.contributing_present:
            findings.append(
                GitHubPublicClaimFinding(
                    claim_class=GitHubClaimClass.CONTRIBUTION_REFUSAL,
                    decision=Decision.REFUSE,
                    surface=envelope.surface,
                    reason="contribution/community claim without CONTRIBUTING.md",
                    claim_text=_snippet(text),
                    correction="render contribution language as refusal or add CONTRIBUTING.md",
                    evidence_refs=envelope.settings_witness_refs,
                )
            )
        if not envelope.settings_witness_complete:
            findings.append(
                GitHubPublicClaimFinding(
                    claim_class=GitHubClaimClass.CONTRIBUTION_REFUSAL,
                    decision=Decision.REFUSE,
                    surface=envelope.surface,
                    reason="contribution/community claim lacks live settings witnesses",
                    claim_text=_snippet(text),
                    correction="attach issue/discussion/wiki/sponsor witnesses before publishing",
                    evidence_refs=envelope.settings_witness_refs,
                )
            )

    if _SETTINGS_RE.search(text) and not envelope.settings_witness_complete:
        findings.append(
            GitHubPublicClaimFinding(
                claim_class=GitHubClaimClass.CONTRIBUTION_REFUSAL,
                decision=Decision.REFUSE,
                surface=envelope.surface,
                reason="GitHub settings claim lacks issue/discussion/wiki/sponsor witnesses",
                claim_text=_snippet(text),
                correction="state settings as unreconciled until live GitHub API witnesses exist",
                evidence_refs=envelope.settings_witness_refs,
            )
        )

    return tuple(findings)


def _live_current_finding(
    text: str, envelope: GitHubMaterialEvidenceEnvelope
) -> GitHubPublicClaimFinding:
    if envelope.has_fresh_current_refs:
        decision = PublicClaimGateDecision(
            decision=Decision.ALLOW,
            kind=ClaimKind.PUBLICATION_STATE,
            reason="fresh WCS/publication-event refs support live/current claim",
        )
    else:
        decision = PublicClaimGateDecision(
            decision=Decision.REFUSE,
            kind=ClaimKind.PUBLICATION_STATE,
            reason="live/current claim lacks fresh WCS or publication-event refs",
            correction="render as historical implementation-scope copy",
        )
    return _finding_from_metadata(
        GitHubClaimClass.LIVE_CURRENT_SYSTEM,
        text,
        envelope,
        decision,
        evidence_refs=(*envelope.wcs_refs, *envelope.publication_event_refs),
    )


def _research_status_findings(
    text: str, envelope: GitHubMaterialEvidenceEnvelope
) -> tuple[GitHubPublicClaimFinding, ...]:
    findings: list[GitHubPublicClaimFinding] = []
    for claimed_status, pattern in _RESEARCH_STATUS_PATTERNS:
        if not pattern.search(text):
            continue
        if claimed_status == envelope.research_status and (
            claimed_status is not ResearchStatus.EMPIRICALLY_VALIDATED
            or envelope.research_evidence_refs
        ):
            decision = Decision.ALLOW
            reason = f"research status is {claimed_status.value}"
            correction = ""
        elif claimed_status is ResearchStatus.EMPIRICALLY_VALIDATED:
            decision = Decision.REFUSE
            reason = (
                "empirical-validation claim requires research_status=empirically_validated "
                "and evidence refs"
            )
            correction = f"state research status as {envelope.research_status.value}"
        else:
            decision = Decision.REFUSE
            reason = (
                f"research-status claim {claimed_status.value!r} exceeds "
                f"envelope status {envelope.research_status.value!r}"
            )
            correction = f"state research status as {envelope.research_status.value}"
        findings.append(
            GitHubPublicClaimFinding(
                claim_class=GitHubClaimClass.RESEARCH_STATUS,
                decision=decision,
                surface=envelope.surface,
                reason=reason,
                claim_text=_snippet(text),
                correction=correction,
                evidence_refs=envelope.research_evidence_refs,
            )
        )
    return tuple(findings)


def _support_finding(
    text: str, envelope: GitHubMaterialEvidenceEnvelope
) -> GitHubPublicClaimFinding:
    decision = evaluate_public_claim(
        ClaimKind.SUPPORT,
        ClaimEvidence(
            support_surface_active=(
                envelope.support_conversion_ready and envelope.has_public_event_refs
            )
        ),
    )
    return _finding_from_metadata(
        GitHubClaimClass.SUPPORT,
        text,
        envelope,
        decision,
        evidence_refs=(*envelope.public_event_refs, *envelope.publication_event_refs),
    )


def _artifact_finding(
    text: str, envelope: GitHubMaterialEvidenceEnvelope
) -> GitHubPublicClaimFinding:
    has_artifact_evidence = (
        envelope.artifact_conversion_ready
        and envelope.has_public_event_refs
        and bool(envelope.artifact_rights_refs)
    )
    decision = evaluate_public_claim(
        ClaimKind.PUBLICATION_STATE,
        ClaimEvidence(
            publication_state="released" if has_artifact_evidence else "",
            publication_evidence_url=(
                envelope.public_event_refs[0]
                if envelope.public_event_refs
                else (envelope.publication_event_refs[0] if envelope.publication_event_refs else "")
            ),
        ),
    )
    if not has_artifact_evidence and decision.decision is Decision.REFUSE:
        return GitHubPublicClaimFinding(
            claim_class=GitHubClaimClass.ARTIFACT,
            decision=Decision.REFUSE,
            surface=envelope.surface,
            reason="artifact/release claim lacks conversion readiness, public-event, or rights refs",
            claim_text=_snippet(text),
            correction="render artifact state as planned or unreconciled",
            evidence_refs=(
                *envelope.public_event_refs,
                *envelope.publication_event_refs,
                *envelope.artifact_rights_refs,
            ),
        )
    return _finding_from_metadata(
        GitHubClaimClass.ARTIFACT,
        text,
        envelope,
        decision,
        evidence_refs=(
            *envelope.public_event_refs,
            *envelope.publication_event_refs,
            *envelope.artifact_rights_refs,
        ),
    )


def _monetization_finding(
    text: str, envelope: GitHubMaterialEvidenceEnvelope
) -> GitHubPublicClaimFinding:
    decision = evaluate_public_claim(
        ClaimKind.MONETIZATION,
        ClaimEvidence(
            monetization_active=(
                envelope.monetization_conversion_ready and envelope.has_public_event_refs
            )
        ),
    )
    return _finding_from_metadata(
        GitHubClaimClass.MONETIZATION,
        text,
        envelope,
        decision,
        evidence_refs=(*envelope.public_event_refs, *envelope.publication_event_refs),
    )


def _finding_from_metadata(
    claim_class: GitHubClaimClass,
    text: str,
    envelope: GitHubMaterialEvidenceEnvelope,
    decision: PublicClaimGateDecision,
    *,
    evidence_refs: tuple[str, ...],
) -> GitHubPublicClaimFinding:
    return GitHubPublicClaimFinding(
        claim_class=claim_class,
        decision=decision.decision,
        surface=envelope.surface,
        reason=decision.reason,
        claim_text=_snippet(text),
        correction=decision.correction,
        evidence_refs=evidence_refs,
    )


def _license_refs(envelope: GitHubMaterialEvidenceEnvelope) -> tuple[str, ...]:
    refs = ["gh:repos/license"]
    if envelope.license_present:
        refs.append("LICENSE")
    if envelope.notice_present:
        refs.append("NOTICE.md")
    if envelope.citation_present:
        refs.append("CITATION.cff")
    if envelope.codemeta_present:
        refs.append("codemeta.json")
    if envelope.zenodo_present:
        refs.append(".zenodo.json")
    return tuple(refs)


def _missing_license_witnesses(envelope: GitHubMaterialEvidenceEnvelope) -> tuple[str, ...]:
    missing: list[str] = []
    for label, present in (
        ("LICENSE", envelope.license_present),
        ("NOTICE.md", envelope.notice_present),
        ("CITATION.cff", envelope.citation_present),
        ("codemeta.json", envelope.codemeta_present),
        (".zenodo.json", envelope.zenodo_present),
    ):
        if not present:
            missing.append(label)
    if not envelope.declared_license:
        missing.append("declared_license")
    if not envelope.github_detected_license:
        missing.append("github_detected_license")
    return tuple(missing)


def _tuple_of_str(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value if str(item))
    return (str(value),)


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _snippet(text: str) -> str:
    normalized = " ".join(text.split())
    return normalized[:180]


__all__ = [
    "GitHubClaimClass",
    "GitHubMaterialEvidenceEnvelope",
    "GitHubPublicClaimFinding",
    "GitHubPublicClaimGateVerdict",
    "GitHubPublicSurface",
    "ResearchStatus",
    "evaluate_github_public_claims",
    "github_material_envelope_from_mapping",
]
