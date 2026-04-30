"""Typed contract for GitHub public-surface live-state reconciliation.

The report is an evidence envelope, not a public-claim grant. It records what
GitHub and the repository files currently say so downstream renderers can fail
closed when README/profile/package copy would outrun live state.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

REPORT_SCHEMA_VERSION: int = 1
CLAIM_CEILING: str = "public_archive"

INTENDED_PUBLIC_REPOS: tuple[str, ...] = (
    "ryanklee/hapax-council",
    "ryanklee/hapax-constitution",
    "ryanklee/hapax-officium",
    "ryanklee/hapax-watch",
    "ryanklee/hapax-phone",
    "ryanklee/hapax-mcp",
    "ryanklee/hapax-assets",
)

PROFILE_REPO_CANDIDATES: tuple[str, ...] = (
    "ryanklee/ryanklee",
    "ryanklee/.github",
)

REQUIRED_FILE_PATHS: tuple[str, ...] = (
    "README.md",
    "LICENSE",
    "NOTICE.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "GOVERNANCE.md",
    "CITATION.cff",
    "codemeta.json",
    ".zenodo.json",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".github/FUNDING.yml",
)

REQUIRED_DRIFT_CATEGORIES: tuple[str, ...] = (
    "readme_currentness",
    "license_detection",
    "citation_codemeta_zenodo",
    "contributing_governance",
    "settings_truth",
    "profile_repo_state",
    "pages_cdn_state",
    "package_public_surfaces",
    "notice_links",
    "closed_repo_pres_claims",
)

FindingSeverity = Literal["blocking", "high", "medium", "low", "info"]
FindingStatus = Literal["drift", "blocked", "unreconciled", "observed", "ok"]


class StrictModel(BaseModel):
    """Base model that keeps report fields stable for renderer consumers."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class RepoFilePresence(StrictModel):
    path: str
    exists: bool
    sha: str | None = None
    size: int | None = None
    html_url: str | None = None
    evidence: str = "github_contents_api"


class PagesState(StrictModel):
    exists: bool
    status: str | None = None
    html_url: str | None = None
    cname: str | None = None
    source_branch: str | None = None
    source_path: str | None = None
    error: str | None = None


class ReleaseTagState(StrictModel):
    count: int
    latest_name: str | None = None
    latest_tag_name: str | None = None
    latest_published_at: str | None = None
    error: str | None = None


class CommunityProfileState(StrictModel):
    health_percentage: int | None = None
    description: str | None = None
    files: dict[str, bool] = Field(default_factory=dict)
    error: str | None = None


class RepoLiveState(StrictModel):
    repo_id: str
    owner: str
    name: str
    expected_public: bool = True
    exists: bool
    private: bool | None = None
    visibility: str | None = None
    archived: bool | None = None
    default_branch: str | None = None
    default_branch_sha: str | None = None
    description: str | None = None
    homepage: str | None = None
    topics: tuple[str, ...] = ()
    license_spdx: str | None = None
    license_name: str | None = None
    has_issues: bool | None = None
    has_discussions: bool | None = None
    has_wiki: bool | None = None
    has_projects: bool | None = None
    pushed_at: str | None = None
    html_url: str | None = None
    files: dict[str, RepoFilePresence] = Field(default_factory=dict)
    pages: PagesState = Field(default_factory=lambda: PagesState(exists=False))
    releases: ReleaseTagState = Field(default_factory=lambda: ReleaseTagState(count=0))
    tags: ReleaseTagState = Field(default_factory=lambda: ReleaseTagState(count=0))
    community: CommunityProfileState = Field(default_factory=CommunityProfileState)
    api_error: str | None = None


class PackageSurface(StrictModel):
    path: str
    package_name: str
    has_readme: bool
    has_citation: bool
    has_pyproject: bool
    readme_mentions_issues: bool
    readme_mentions_support: bool
    claim_status: Literal["needs_claim_discipline", "evidence_only", "not_public_package"]
    evidence_refs: tuple[str, ...]


class LocalPublicSurfaceEvidence(StrictModel):
    repo_head: str
    registry_license_by_repo: dict[str, str]
    registry_assets_policy: str | None = None
    root_file_sha256: dict[str, str]
    notice_links: tuple[str, ...]
    notice_missing_links: tuple[str, ...]
    package_surfaces: tuple[PackageSurface, ...]


class GitHubDocsEvidence(StrictModel):
    user_profile_readme_url: str
    organization_profile_readme_url: str
    user_profile_requirement: str
    organization_profile_requirement: str
    profile_readme_decision: Literal["user_repo_named_ryanklee_required"]


class DriftFinding(StrictModel):
    finding_id: str
    severity: FindingSeverity
    category: str
    surface: str
    status: FindingStatus
    summary: str
    expected: str
    observed: str
    evidence_refs: tuple[str, ...]
    blocks: tuple[str, ...] = ()


class ClosedRepoPresClaim(StrictModel):
    task_id: str
    task_path: str
    claimed_status: str
    live_status: Literal["true", "false", "unreconciled", "not_applicable"]
    summary: str
    evidence_refs: tuple[str, ...]


class GitHubPublicSurfaceReport(StrictModel):
    schema_version: Literal[1]
    generated_at: str
    generated_by: str
    claim_ceiling: Literal["public_archive"]
    source_refs: tuple[str, ...]
    live_repos: tuple[RepoLiveState, ...]
    profile_repo_candidates: tuple[RepoLiveState, ...]
    local_evidence: LocalPublicSurfaceEvidence
    docs_evidence: GitHubDocsEvidence
    drift_findings: tuple[DriftFinding, ...]
    closed_repo_pres_claims: tuple[ClosedRepoPresClaim, ...]
    required_drift_categories: tuple[str, ...] = REQUIRED_DRIFT_CATEGORIES
    anti_overclaim: tuple[str, ...] = (
        "live GitHub coherence does not prove research validity",
        "live GitHub coherence does not prove livestream health",
        "live GitHub coherence does not prove support readiness",
        "live GitHub coherence does not prove artifact rights",
        "live GitHub coherence does not prove monetization readiness",
    )

    def repos_by_id(self) -> dict[str, RepoLiveState]:
        return {repo.repo_id: repo for repo in self.live_repos + self.profile_repo_candidates}

    def findings_by_category(self) -> dict[str, tuple[DriftFinding, ...]]:
        grouped: dict[str, list[DriftFinding]] = {}
        for finding in self.drift_findings:
            grouped.setdefault(finding.category, []).append(finding)
        return {category: tuple(findings) for category, findings in grouped.items()}


def missing_required_categories(report: GitHubPublicSurfaceReport) -> tuple[str, ...]:
    """Return required drift categories absent from a report."""

    present = set(report.findings_by_category())
    return tuple(category for category in REQUIRED_DRIFT_CATEGORIES if category not in present)


def build_drift_findings(
    *,
    repos: Mapping[str, RepoLiveState],
    local: LocalPublicSurfaceEvidence,
) -> tuple[DriftFinding, ...]:
    """Build deterministic drift findings from live state and repo evidence."""

    findings: list[DriftFinding] = []
    council = repos.get("ryanklee/hapax-council")
    constitution = repos.get("ryanklee/hapax-constitution")
    assets = repos.get("ryanklee/hapax-assets")
    user_profile = repos.get("ryanklee/ryanklee")
    org_profile = repos.get("ryanklee/.github")

    for repo_id in INTENDED_PUBLIC_REPOS:
        repo = repos.get(repo_id)
        if repo is None:
            continue
        if repo_id != "ryanklee/hapax-assets" and (
            not repo.exists or repo.private or repo.visibility != "public"
        ):
            findings.append(
                DriftFinding(
                    finding_id=f"github.visibility.{repo.name}.not-public",
                    severity="high",
                    category="settings_truth",
                    surface=repo_id,
                    status="blocked",
                    summary="An intended public first-party repo is not publicly visible.",
                    expected="Live GitHub visibility is public before public material names the repo.",
                    observed=_repo_visibility_observed(repo),
                    evidence_refs=(f"gh:repos/{repo_id}",),
                    blocks=("github-public-claim-evidence-gate",),
                )
            )

        expected_license = local.registry_license_by_repo.get(repo.name)
        if (
            repo_id != "ryanklee/hapax-council"
            and expected_license
            and repo.exists
            and repo.visibility == "public"
        ):
            if repo.license_spdx != expected_license:
                findings.append(
                    DriftFinding(
                        finding_id=f"github.license.{repo.name}.registry-mismatch",
                        severity="high",
                        category="license_detection",
                        surface=repo_id,
                        status="unreconciled",
                        summary="GitHub detected license does not match the repo registry policy.",
                        expected=f"GitHub public license surfaces align to {expected_license}.",
                        observed=f"GitHub detects {repo.license_spdx or 'no license'}.",
                        evidence_refs=("docs/repo-pres/repo-registry.yaml", f"gh:repos/{repo_id}"),
                        blocks=("github-public-claim-evidence-gate",),
                    )
                )

    if council is not None:
        expected_license = local.registry_license_by_repo.get("hapax-council")
        if expected_license and council.license_spdx != expected_license:
            findings.append(
                DriftFinding(
                    finding_id="github.license.hapax-council.apache-vs-polyform",
                    severity="blocking",
                    category="license_detection",
                    surface="ryanklee/hapax-council",
                    status="blocked",
                    summary="GitHub/root license detection contradicts the repo registry policy.",
                    expected=f"GitHub public license surfaces align to {expected_license}.",
                    observed=f"GitHub detects {council.license_spdx or 'no license'}.",
                    evidence_refs=(
                        "docs/repo-pres/repo-registry.yaml",
                        "LICENSE",
                        "CITATION.cff",
                        "codemeta.json",
                        "gh:repos/ryanklee/hapax-council",
                    ),
                    blocks=("github-readme-profile-current-project-refresh",),
                )
            )

        if "CONTRIBUTING.md" in local.notice_missing_links:
            findings.append(
                DriftFinding(
                    finding_id="github.notice.contributing-link-missing",
                    severity="blocking",
                    category="notice_links",
                    surface="NOTICE.md",
                    status="blocked",
                    summary="NOTICE links to CONTRIBUTING.md, but the linked file is absent.",
                    expected="Every public NOTICE link resolves to an existing public path.",
                    observed="CONTRIBUTING.md is referenced but missing on the default branch.",
                    evidence_refs=("NOTICE.md", "gh:contents/CONTRIBUTING.md"),
                    blocks=("github-public-claim-evidence-gate",),
                )
            )

        if not council.files.get(
            "GOVERNANCE.md", RepoFilePresence(path="GOVERNANCE.md", exists=False)
        ).exists:
            findings.append(
                DriftFinding(
                    finding_id="github.governance.root-file-missing",
                    severity="high",
                    category="contributing_governance",
                    surface="ryanklee/hapax-council",
                    status="drift",
                    summary="GOVERNANCE.md is missing from the public repo root.",
                    expected="Governance/refusal posture is surfaced by a live public file.",
                    observed="GOVERNANCE.md is not present on the default branch.",
                    evidence_refs=(
                        "gh:contents/GOVERNANCE.md",
                        "docs/repo-pres/repo-registry.yaml",
                    ),
                    blocks=("cross-surface-public-legibility-pack",),
                )
            )

        has_issue_template = council.community.files.get("issue_template") is True
        if council.has_issues is True and not has_issue_template:
            findings.append(
                DriftFinding(
                    finding_id="github.settings.issues-enabled-without-template",
                    severity="high",
                    category="settings_truth",
                    surface="ryanklee/hapax-council",
                    status="unreconciled",
                    summary="Issues are enabled while GitHub does not report an issue template.",
                    expected="Issue/refusal posture either matches has_issues or is marked unreconciled.",
                    observed="has_issues=true and community profile issue_template=false.",
                    evidence_refs=(
                        "gh:repos/ryanklee/hapax-council",
                        "gh:repos/ryanklee/hapax-council/community/profile",
                        ".github/ISSUE_TEMPLATE/config.yml",
                    ),
                    blocks=("github-public-claim-evidence-gate",),
                )
            )

        findings.append(
            DriftFinding(
                finding_id="github.readme.current-project-spine-stale",
                severity="high",
                category="readme_currentness",
                surface="README.md",
                status="drift",
                summary="README currentness must be regenerated after live-state reconciliation.",
                expected="README/profile copy cites current project-spine evidence and report head.",
                observed="README predates this live-state report and cannot claim reconciled state.",
                evidence_refs=("README.md", "CLAUDE.md", "gh:repos/ryanklee/hapax-council"),
                blocks=("github-readme-profile-current-project-refresh",),
            )
        )

        findings.append(
            DriftFinding(
                finding_id="github.metadata.citation-codemeta-zenodo-coherence",
                severity="high",
                category="citation_codemeta_zenodo",
                surface="CITATION.cff/codemeta.json/.zenodo.json",
                status="unreconciled",
                summary="Citation/CodeMeta/Zenodo metadata must be reconciled after license drift.",
                expected="Metadata license, preferred citation, and DOI posture agree with live surfaces.",
                observed="Metadata cannot be treated as coherent while GitHub detects a contradictory license.",
                evidence_refs=("CITATION.cff", "codemeta.json", ".zenodo.json", "LICENSE"),
                blocks=("github-public-claim-evidence-gate",),
            )
        )

    if user_profile is not None and not _repo_has_root_readme(user_profile):
        findings.append(
            DriftFinding(
                finding_id="github.profile.user-profile-readme-missing",
                severity="blocking",
                category="profile_repo_state",
                surface="ryanklee/ryanklee",
                status="blocked",
                summary="User profile README repo is missing, private, or lacks root README.md.",
                expected="GitHub user profile README lives in public ryanklee/ryanklee with root README.md.",
                observed=_profile_observed(user_profile),
                evidence_refs=(
                    "gh:repos/ryanklee/ryanklee",
                    "https://docs.github.com/en/account-and-profile/how-tos/profile-customization/managing-your-profile-readme",
                ),
                blocks=("github-readme-profile-current-project-refresh",),
            )
        )

    if org_profile is not None and org_profile.exists:
        findings.append(
            DriftFinding(
                finding_id="github.profile.org-profile-candidate-not-user-surface",
                severity="medium",
                category="profile_repo_state",
                surface="ryanklee/.github",
                status="observed",
                summary="The .github/profile path is an organization-profile pattern, not the user-profile README path.",
                expected="Use ryanklee/ryanklee for the operator user profile unless ryanklee is an organization.",
                observed="ryanklee/.github is visible but is not the selected user-profile target.",
                evidence_refs=(
                    "gh:repos/ryanklee/.github",
                    "https://docs.github.com/en/organizations/collaborating-with-groups-in-organizations/customizing-your-organizations-profile",
                ),
            )
        )

    if assets is not None and (
        not assets.exists or assets.private or assets.visibility != "public"
    ):
        findings.append(
            DriftFinding(
                finding_id="github.pages.hapax-assets-not-public-cdn",
                severity="blocking",
                category="pages_cdn_state",
                surface="ryanklee/hapax-assets",
                status="blocked",
                summary="hapax-assets is not a verified public Pages/CDN surface.",
                expected="hapax-assets is visible and Pages state is explicit before public CDN claims.",
                observed=_repo_visibility_observed(assets),
                evidence_refs=(
                    "gh:repos/ryanklee/hapax-assets",
                    "gh:repos/ryanklee/hapax-assets/pages",
                ),
                blocks=("github-public-claim-evidence-gate",),
            )
        )
    elif assets is not None and not assets.pages.exists:
        findings.append(
            DriftFinding(
                finding_id="github.pages.hapax-assets-pages-missing",
                severity="high",
                category="pages_cdn_state",
                surface="ryanklee/hapax-assets",
                status="unreconciled",
                summary="hapax-assets is visible but GitHub Pages is not enabled or not readable.",
                expected="Public CDN claims cite a live Pages state.",
                observed=assets.pages.error or "Pages API returned no site.",
                evidence_refs=("gh:repos/ryanklee/hapax-assets/pages",),
                blocks=("github-public-claim-evidence-gate",),
            )
        )

    if constitution is not None and constitution.has_wiki is not True:
        findings.append(
            DriftFinding(
                finding_id="github.settings.constitution-wiki-disabled",
                severity="medium",
                category="settings_truth",
                surface="ryanklee/hapax-constitution",
                status="drift",
                summary="hapax-constitution wiki is expected as the axiom-registry exception.",
                expected="has_wiki=true for the constitution repo only.",
                observed=f"has_wiki={constitution.has_wiki}",
                evidence_refs=("docs/repo-pres/wiki-axiom-registry/architecture.md",),
            )
        )

    findings.extend(_package_surface_findings(local.package_surfaces))
    findings.extend(_closed_repo_pres_findings(local, council, user_profile, assets))
    return tuple(findings)


def _package_surface_findings(
    package_surfaces: Sequence[PackageSurface],
) -> tuple[DriftFinding, ...]:
    needs = [
        surface for surface in package_surfaces if surface.claim_status == "needs_claim_discipline"
    ]
    if not needs:
        return (
            DriftFinding(
                finding_id="github.packages.public-surfaces-inventory",
                severity="info",
                category="package_public_surfaces",
                surface="packages/",
                status="observed",
                summary="Package public surfaces were inventoried and did not trigger issue/support drift.",
                expected="Package README/CITATION/PyPI surfaces are explicitly inventoried.",
                observed="No issue/support language detected by the current scanner.",
                evidence_refs=("packages/",),
            ),
        )
    return (
        DriftFinding(
            finding_id="github.packages.issue-support-language-present",
            severity="medium",
            category="package_public_surfaces",
            surface="packages/",
            status="unreconciled",
            summary="Some package README/PyPI surfaces contain issue/support language needing claim discipline.",
            expected="Package-public surfaces inherit the repo refusal/claim ceiling before refresh.",
            observed=", ".join(surface.path for surface in needs),
            evidence_refs=tuple(ref for surface in needs for ref in surface.evidence_refs),
            blocks=("github-public-claim-evidence-gate",),
        ),
    )


def _closed_repo_pres_findings(
    local: LocalPublicSurfaceEvidence,
    council: RepoLiveState | None,
    user_profile: RepoLiveState | None,
    assets: RepoLiveState | None,
) -> tuple[DriftFinding, ...]:
    false_tasks = [
        task.task_id
        for task in build_closed_repo_pres_claims(
            local=local,
            council=council,
            user_profile=user_profile,
            assets=assets,
        )
        if task.live_status in {"false", "unreconciled"}
    ]
    return (
        DriftFinding(
            finding_id="github.closed-repo-pres.claim-drift",
            severity="high" if false_tasks else "info",
            category="closed_repo_pres_claims",
            surface="cc-task closed/repo-pres-*",
            status="unreconciled" if false_tasks else "ok",
            summary="Closed repo-pres task claims were compared to live state.",
            expected="Closed task records remain immutable, but false live claims feed drift.",
            observed=", ".join(false_tasks)
            if false_tasks
            else "No false closed-task claims detected.",
            evidence_refs=("vault:hapax-cc-tasks/closed",),
            blocks=("github-readme-profile-current-project-refresh",) if false_tasks else (),
        ),
    )


def build_closed_repo_pres_claims(
    *,
    local: LocalPublicSurfaceEvidence,
    council: RepoLiveState | None,
    user_profile: RepoLiveState | None,
    assets: RepoLiveState | None,
) -> tuple[ClosedRepoPresClaim, ...]:
    """Summarize closed repo-pres claims that are true/false in live state."""

    closed_root = "vault:hapax-cc-tasks/closed"
    expected_license = local.registry_license_by_repo.get("hapax-council")
    license_live = (
        "true"
        if council is not None
        and expected_license is not None
        and council.license_spdx == expected_license
        else "false"
    )
    contributing_live = "false" if "CONTRIBUTING.md" in local.notice_missing_links else "true"
    profile_live = (
        "true" if user_profile is not None and _repo_has_root_readme(user_profile) else "false"
    )
    assets_live = (
        "true"
        if assets is not None
        and assets.exists
        and not assets.private
        and assets.visibility == "public"
        else "false"
    )
    issue_live = "true"
    if (
        council is not None
        and council.has_issues is True
        and not council.community.files.get("issue_template", False)
    ):
        issue_live = "unreconciled"

    return (
        ClosedRepoPresClaim(
            task_id="repo-pres-license-policy",
            task_path=f"{closed_root}/repo-pres-license-policy.md",
            claimed_status="done",
            live_status=license_live,
            summary="License policy closed state compared to GitHub detected license.",
            evidence_refs=("docs/repo-pres/repo-registry.yaml", "gh:repos/ryanklee/hapax-council"),
        ),
        ClosedRepoPresClaim(
            task_id="repo-pres-notice-md-all-repos",
            task_path=f"{closed_root}/repo-pres-notice-md-all-repos.md",
            claimed_status="done",
            live_status=contributing_live,
            summary="NOTICE link closure compared to live CONTRIBUTING.md presence.",
            evidence_refs=("NOTICE.md", "gh:contents/CONTRIBUTING.md"),
        ),
        ClosedRepoPresClaim(
            task_id="repo-pres-issues-redirect-walls",
            task_path=f"{closed_root}/repo-pres-issues-redirect-walls.md",
            claimed_status="done",
            live_status=issue_live,
            summary="Issue redirect-wall closure compared to has_issues and community profile state.",
            evidence_refs=("scripts/repo-presentation-enforce.sh", "gh:community/profile"),
        ),
        ClosedRepoPresClaim(
            task_id="repo-pres-org-level-github",
            task_path=f"{closed_root}/repo-pres-org-level-github.md",
            claimed_status="done",
            live_status=profile_live,
            summary="Profile README closure compared to current user-profile README docs and repo state.",
            evidence_refs=("gh:repos/ryanklee/ryanklee", "GitHub profile README docs"),
        ),
        ClosedRepoPresClaim(
            task_id="repo-pres-hapax-assets-public-cdn",
            task_path=f"{closed_root}/repo-pres-hapax-assets-public-cdn.md",
            claimed_status="implicit-or-docs",
            live_status=assets_live,
            summary="hapax-assets CDN/public visibility claim compared to live repo and Pages state.",
            evidence_refs=("CLAUDE.md", "gh:repos/ryanklee/hapax-assets"),
        ),
    )


def build_report(
    *,
    generated_at: str,
    generated_by: str,
    source_refs: Sequence[str],
    live_repos: Sequence[RepoLiveState],
    profile_repo_candidates: Sequence[RepoLiveState],
    local_evidence: LocalPublicSurfaceEvidence,
    docs_evidence: GitHubDocsEvidence,
) -> GitHubPublicSurfaceReport:
    repos = {repo.repo_id: repo for repo in tuple(live_repos) + tuple(profile_repo_candidates)}
    findings = build_drift_findings(repos=repos, local=local_evidence)
    claims = build_closed_repo_pres_claims(
        local=local_evidence,
        council=repos.get("ryanklee/hapax-council"),
        user_profile=repos.get("ryanklee/ryanklee"),
        assets=repos.get("ryanklee/hapax-assets"),
    )
    return GitHubPublicSurfaceReport(
        schema_version=1,
        generated_at=generated_at,
        generated_by=generated_by,
        claim_ceiling="public_archive",
        source_refs=tuple(source_refs),
        live_repos=tuple(live_repos),
        profile_repo_candidates=tuple(profile_repo_candidates),
        local_evidence=local_evidence,
        docs_evidence=docs_evidence,
        drift_findings=findings,
        closed_repo_pres_claims=claims,
    )


def report_to_markdown(report: GitHubPublicSurfaceReport) -> str:
    """Render a concise operator-facing companion to the JSON report."""

    lines = [
        "---",
        "title: GitHub public surface live state reconcile",
        f"date: {report.generated_at[:10]}",
        "status: evidence-produced",
        "source: github-public-surface-live-state-reconcile",
        "---",
        "",
        "# GitHub Public Surface Live State Reconcile",
        "",
        f"- Generated: `{report.generated_at}`",
        f"- Claim ceiling: `{report.claim_ceiling}`",
        f"- Blocking findings: `{_count_severity(report, 'blocking')}`",
        f"- Report schema: `schema_version={report.schema_version}`",
        "",
        "## Live Repos",
        "",
        "| Repo | Visibility | Default SHA | License | Issues | Discussions | Wiki | Pages |",
        "|---|---:|---|---|---:|---:|---:|---:|",
    ]
    for repo in report.live_repos:
        lines.append(
            "| "
            + " | ".join(
                (
                    repo.repo_id,
                    repo.visibility or ("missing" if not repo.exists else "unknown"),
                    (repo.default_branch_sha or "")[:12],
                    repo.license_spdx or "",
                    _bool_cell(repo.has_issues),
                    _bool_cell(repo.has_discussions),
                    _bool_cell(repo.has_wiki),
                    _bool_cell(repo.pages.exists),
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Drift Findings",
            "",
            "| Severity | Category | Surface | Summary |",
            "|---|---|---|---|",
        ]
    )
    for finding in report.drift_findings:
        lines.append(
            f"| {finding.severity} | {finding.category} | {finding.surface} | {finding.summary} |"
        )
    lines.extend(
        [
            "",
            "## Profile README Decision",
            "",
            "Current GitHub docs require a public user repo named `ryanklee` with a root "
            "`README.md` for a user profile README. The `.github/profile/README.md` "
            "pattern is for organization profiles, so it is evidence only for this "
            "operator-account surface.",
            "",
            "## Anti-Overclaim",
            "",
        ]
    )
    repos = report.repos_by_id()
    user_profile = repos.get("ryanklee/ryanklee")
    lines.append(
        "Observed user-profile candidate: "
        f"`{_profile_observed(user_profile) if user_profile is not None else 'not collected'}`."
    )
    lines.append("")
    for item in report.anti_overclaim:
        lines.append(f"- {item}.")
    lines.append("")
    return "\n".join(lines)


def _repo_has_root_readme(repo: RepoLiveState) -> bool:
    return (
        repo.exists
        and repo.visibility == "public"
        and repo.files.get("README.md", RepoFilePresence(path="README.md", exists=False)).exists
    )


def _profile_observed(repo: RepoLiveState) -> str:
    if not repo.exists:
        return repo.api_error or "repo not found"
    readme = repo.files.get("README.md")
    return (
        f"visibility={repo.visibility}, private={repo.private}, "
        f"root_readme={readme.exists if readme else False}"
    )


def _repo_visibility_observed(repo: RepoLiveState) -> str:
    if not repo.exists:
        return repo.api_error or "repo missing/private"
    return f"visibility={repo.visibility}, private={repo.private}, pages={repo.pages.exists}"


def _count_severity(report: GitHubPublicSurfaceReport, severity: FindingSeverity) -> int:
    return sum(1 for finding in report.drift_findings if finding.severity == severity)


def _bool_cell(value: bool | None) -> str:
    if value is None:
        return ""
    return "true" if value else "false"


def report_json_schema() -> dict[str, Any]:
    """Return the JSON Schema for committed report validation."""

    return GitHubPublicSurfaceReport.model_json_schema()
