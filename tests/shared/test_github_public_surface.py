"""Contract tests for GitHub public-surface live-state reconciliation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import jsonschema

from shared.github_public_surface import (
    CLAIM_CEILING,
    INTENDED_PUBLIC_REPOS,
    PROFILE_REPO_CANDIDATES,
    REQUIRED_DRIFT_CATEGORIES,
    GitHubPublicSurfaceReport,
    missing_required_categories,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT = REPO_ROOT / "docs/repo-pres/github-public-surface-live-state-reconcile.json"
SCHEMA = REPO_ROOT / "schemas/github-public-surface-live-state-report.schema.json"


def _payload() -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(REPORT.read_text(encoding="utf-8")))


def _report() -> GitHubPublicSurfaceReport:
    return GitHubPublicSurfaceReport.model_validate(_payload())


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

    assert findings["github.notice.contributing-link-missing"].severity == "blocking"
    assert findings["github.profile.user-profile-readme-missing"].severity == "blocking"
    assert findings["github.pages.hapax-assets-not-public-cdn"].severity == "blocking"


def test_profile_readme_decision_uses_user_repo_not_org_profile_pattern() -> None:
    report = _report()

    assert report.docs_evidence.profile_readme_decision == "user_repo_named_ryanklee_required"
    assert "ryanklee/ryanklee" in report.repos_by_id()
    assert report.repos_by_id()["ryanklee/ryanklee"].exists is False
    assert report.docs_evidence.user_profile_readme_url.startswith("https://docs.github.com/")
    assert report.docs_evidence.organization_profile_readme_url.startswith(
        "https://docs.github.com/"
    )


def test_closed_repo_pres_false_claims_are_reported_without_deleting_records() -> None:
    report = _report()
    claims = {claim.task_id: claim for claim in report.closed_repo_pres_claims}

    assert claims["repo-pres-license-policy"].live_status == "false"
    assert claims["repo-pres-notice-md-all-repos"].live_status == "false"
    assert claims["repo-pres-issues-redirect-walls"].live_status == "unreconciled"
    assert claims["repo-pres-org-level-github"].live_status == "false"
    assert all(claim.task_path.startswith("vault:hapax-cc-tasks/") for claim in claims.values())


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
