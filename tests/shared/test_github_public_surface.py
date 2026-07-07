"""Contract tests for GitHub public-surface live-state reconciliation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import jsonschema

from shared.github_public_surface import (
    CLAIM_CEILING,
    INTENDED_PUBLIC_REPOS,
    ORG_PROFILE_README_PATH,
    ORG_PROFILE_REPO_ID,
    PROFILE_REPO_CANDIDATES,
    REQUIRED_DRIFT_CATEGORIES,
    GitHubPublicSurfaceReport,
    LocalPublicSurfaceEvidence,
    RepoFilePresence,
    RepoLiveState,
    build_drift_findings,
    missing_required_categories,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT = REPO_ROOT / "docs/repo-pres/github-public-surface-live-state-reconcile.json"
SCHEMA = REPO_ROOT / "schemas/github-public-surface-live-state-report.schema.json"


def _payload() -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(REPORT.read_text(encoding="utf-8")))


def _report() -> GitHubPublicSurfaceReport:
    return GitHubPublicSurfaceReport.model_validate(_payload())


def _minimal_local_evidence() -> LocalPublicSurfaceEvidence:
    return LocalPublicSurfaceEvidence(
        repo_head="test-head",
        registry_license_by_repo={},
        root_file_sha256={},
        notice_links=(),
        notice_missing_links=(),
        package_surfaces=(),
    )


def test_report_schema_validates_committed_live_state_report() -> None:
    schema = cast("dict[str, Any]", json.loads(SCHEMA.read_text(encoding="utf-8")))
    payload = _payload()

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(payload)
    assert payload["schema_version"] == 1
    assert payload["claim_ceiling"] == CLAIM_CEILING


def test_live_snapshot_covers_required_repos_and_profile_candidates() -> None:
    report = _report()
    repos = report.repos_by_id()

    assert set(INTENDED_PUBLIC_REPOS).issubset(repos)
    assert set(PROFILE_REPO_CANDIDATES).issubset(repos)
    for repo_id in INTENDED_PUBLIC_REPOS:
        repo = repos[repo_id]
        assert repo.repo_id == repo_id
        assert repo.visibility is not None
        if repo.exists and repo.visibility == "public":
            assert repo.default_branch
            assert repo.html_url
        if repo.exists and repo.visibility != "public":
            assert repo.api_error == "repo is not public; authenticated-only details redacted"
            assert repo.default_branch_sha is None


def test_drift_report_covers_all_acceptance_categories() -> None:
    report = _report()

    assert report.required_drift_categories == REQUIRED_DRIFT_CATEGORIES
    assert missing_required_categories(report) == ()
    assert all(finding.evidence_refs for finding in report.drift_findings)
    assert all(finding.expected for finding in report.drift_findings)
    assert all(finding.observed for finding in report.drift_findings)


def test_hard_blockers_are_explicit_and_feed_downstream_tasks() -> None:
    report = _report()
    findings = {finding.finding_id: finding for finding in report.drift_findings}

    license_finding = findings["github.license.hapax-council.apache-vs-polyform"]
    assert license_finding.severity == "blocking"
    assert license_finding.category == "license_detection"
    assert "github-readme-profile-current-project-refresh" in license_finding.blocks

    assert findings["github.notice.links-resolve"].status == "ok"
    assert findings["github.profile.org-profile-readme-present"].severity == "info"
    assert findings["github.profile.org-profile-readme-present"].status == "ok"
    assert "github.profile.user-profile-readme-missing" not in findings
    assert "github.profile.org-profile-candidate-not-user-surface" not in findings
    assert findings["github.pages.hapax-assets-pages-present"].status == "ok"


def test_profile_readme_decision_uses_org_dot_github_profile_pattern() -> None:
    report = _report()

    assert report.docs_evidence.profile_readme_decision == "org_repo_named_dot_github_required"
    assert "hapax-systems/.github" in report.repos_by_id()
    org_profile = report.repos_by_id()["hapax-systems/.github"]
    assert org_profile.exists is True
    assert org_profile.files["profile/README.md"].exists is True
    assert report.docs_evidence.user_profile_readme_url.startswith("https://docs.github.com/")
    assert report.docs_evidence.organization_profile_readme_url.startswith(
        "https://docs.github.com/"
    )


def test_closed_repo_pres_false_claims_are_reported_without_deleting_records() -> None:
    report = _report()
    claims = {claim.task_id: claim for claim in report.closed_repo_pres_claims}

    assert claims["repo-pres-license-policy"].live_status == "false"
    assert claims["repo-pres-notice-md-all-repos"].live_status == "true"
    assert claims["repo-pres-issues-redirect-walls"].live_status == "unreconciled"
    assert claims["repo-pres-org-level-github"].live_status == "true"
    assert all(claim.task_path.startswith("vault:hapax-cc-tasks/") for claim in claims.values())


def test_org_profile_not_collected_blocks_profile_state() -> None:
    findings = {
        finding.finding_id: finding
        for finding in build_drift_findings(repos={}, local=_minimal_local_evidence())
    }

    finding = findings["github.profile.org-profile-readme-not-collected"]
    assert finding.severity == "blocking"
    assert finding.surface == ORG_PROFILE_REPO_ID
    assert "github-readme-profile-current-project-refresh" in finding.blocks


def test_org_profile_without_profile_readme_blocks_profile_state() -> None:
    repo = RepoLiveState(
        repo_id=ORG_PROFILE_REPO_ID,
        owner="hapax-systems",
        name=".github",
        exists=True,
        private=False,
        visibility="public",
        files={
            ORG_PROFILE_README_PATH: RepoFilePresence(
                path=ORG_PROFILE_README_PATH,
                exists=False,
            )
        },
    )
    findings = {
        finding.finding_id: finding
        for finding in build_drift_findings(
            repos={ORG_PROFILE_REPO_ID: repo},
            local=_minimal_local_evidence(),
        )
    }

    finding = findings["github.profile.org-profile-readme-missing"]
    assert finding.severity == "blocking"
    assert finding.observed == "visibility=public, private=False, profile_readme=False"
    assert "github-readme-profile-current-project-refresh" in finding.blocks


def test_public_claim_ceiling_and_package_surface_inventory_are_fail_closed() -> None:
    report = _report()
    package_findings = [
        finding
        for finding in report.drift_findings
        if finding.category == "package_public_surfaces"
    ]

    assert report.claim_ceiling == "public_archive"
    assert package_findings
    assert "monetization readiness" in " ".join(report.anti_overclaim)
    assert any(
        surface.claim_status == "needs_claim_discipline"
        for surface in report.local_evidence.package_surfaces
    )
