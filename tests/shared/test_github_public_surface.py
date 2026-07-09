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
        registry_license_by_repo={},
        root_file_sha256={},
        notice_links=(),
        notice_missing_links=(),
        package_surfaces=(),
    )


def _reins_live_state(*, license_spdx: str | None, license_file_exists: bool) -> RepoLiveState:
    return RepoLiveState(
        repo_id="hapax-systems/reins",
        owner="hapax-systems",
        name="reins",
        exists=True,
        private=False,
        visibility="public",
        license_spdx=license_spdx,
        files={
            "LICENSE": RepoFilePresence(path="LICENSE", exists=license_file_exists),
        },
    )


def _reins_license_findings(
    *, license_spdx: str | None, license_file_exists: bool, expected_detection: str | None
) -> list:
    local = LocalPublicSurfaceEvidence(
        registry_license_by_repo={"reins": "BUSL-1.1"},
        registry_expected_detection_by_repo=(
            {"reins": expected_detection} if expected_detection else {}
        ),
        root_file_sha256={},
        notice_links=(),
        notice_missing_links=(),
        package_surfaces=(),
    )
    findings = build_drift_findings(
        repos={
            "hapax-systems/reins": _reins_live_state(
                license_spdx=license_spdx, license_file_exists=license_file_exists
            )
        },
        local=local,
    )
    return [f for f in findings if f.category == "license_detection" and "reins" in f.finding_id]


def test_expected_detection_pin_with_authority_file_is_ok_witness() -> None:
    findings = _reins_license_findings(
        license_spdx="NOASSERTION", license_file_exists=True, expected_detection="NOASSERTION"
    )
    assert [f.finding_id for f in findings] == ["github.license.reins.authority-file-present"]
    assert findings[0].status == "ok"
    assert findings[0].severity == "info"
    # Presence-level witness only — the wording must not overclaim proof.
    assert "presence-level" in findings[0].summary
    assert "proved" not in findings[0].summary


def test_expected_detection_pin_without_authority_file_blocks() -> None:
    findings = _reins_license_findings(
        license_spdx="NOASSERTION", license_file_exists=False, expected_detection="NOASSERTION"
    )
    assert [f.finding_id for f in findings] == ["github.license.reins.authority-file-missing"]
    assert findings[0].status == "blocked"


def test_detection_diverging_from_pin_is_drift() -> None:
    findings = _reins_license_findings(
        license_spdx="Apache-2.0", license_file_exists=True, expected_detection="NOASSERTION"
    )
    assert [f.finding_id for f in findings] == ["github.license.reins.registry-mismatch"]
    assert findings[0].status == "unreconciled"


def test_missing_pin_falls_back_to_policy_comparison() -> None:
    # Backward compatibility: no pin means detection must equal the policy
    # license, which for BUSL repos reproduces the historical mismatch drift.
    findings = _reins_license_findings(
        license_spdx="NOASSERTION", license_file_exists=True, expected_detection=None
    )
    assert [f.finding_id for f in findings] == ["github.license.reins.registry-mismatch"]


def test_pin_equal_to_policy_with_matching_detection_yields_no_findings() -> None:
    # MIT-class repos: the pin equals the policy license and licensee detects
    # it, so the early return emits nothing (no witness needed — detection
    # itself is the proof).
    local = LocalPublicSurfaceEvidence(
        registry_license_by_repo={"agentgov": "MIT"},
        registry_expected_detection_by_repo={"agentgov": "MIT"},
        root_file_sha256={},
        notice_links=(),
        notice_missing_links=(),
        package_surfaces=(),
    )
    findings = build_drift_findings(
        repos={
            "hapax-systems/agentgov": RepoLiveState(
                repo_id="hapax-systems/agentgov",
                owner="hapax-systems",
                name="agentgov",
                exists=True,
                private=False,
                visibility="public",
                license_spdx="MIT",
                files={"LICENSE": RepoFilePresence(path="LICENSE", exists=True)},
            )
        },
        local=local,
    )
    assert [
        f.finding_id
        for f in findings
        if f.category == "license_detection" and "agentgov" in f.finding_id
    ] == []


def _council_license_findings(*, license_spdx: str | None) -> list:
    local = LocalPublicSurfaceEvidence(
        registry_license_by_repo={"hapax-council": "PolyForm-Strict-1.0.0"},
        registry_expected_detection_by_repo={"hapax-council": "NOASSERTION"},
        root_file_sha256={},
        notice_links=(),
        notice_missing_links=(),
        package_surfaces=(),
    )
    council = RepoLiveState(
        repo_id="hapax-systems/hapax-council",
        owner="hapax-systems",
        name="hapax-council",
        exists=True,
        private=False,
        visibility="public",
        license_spdx=license_spdx,
        files={"LICENSE": RepoFilePresence(path="LICENSE", exists=True)},
    )
    findings = build_drift_findings(repos={"hapax-systems/hapax-council": council}, local=local)
    return [
        f for f in findings if f.category == "license_detection" and "hapax-council" in f.finding_id
    ]


def test_council_call_site_pins_detection_and_keeps_blocking_mismatch_id() -> None:
    # Divergence on the council-specific call site keeps the historical
    # blocking finding id and severity, plus the extra metadata evidence refs.
    diverged = _council_license_findings(license_spdx="Apache-2.0")
    assert [f.finding_id for f in diverged] == ["github.license.hapax-council.apache-vs-polyform"]
    assert diverged[0].severity == "blocking"
    assert diverged[0].status == "blocked"
    assert "CITATION.cff" in diverged[0].evidence_refs
    assert "codemeta.json" in diverged[0].evidence_refs

    # Pinned NOASSERTION detection with the authority file present yields the
    # presence-level witness through the same call site.
    pinned = _council_license_findings(license_spdx="NOASSERTION")
    assert [f.finding_id for f in pinned] == ["github.license.hapax-council.authority-file-present"]
    assert pinned[0].status == "ok"


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

    # Council's NOASSERTION detection is pinned as expected; the committed
    # report carries the presence-level authority-file witness instead of the
    # historical apache-vs-polyform blocker.
    council_license = findings["github.license.hapax-council.authority-file-present"]
    assert council_license.severity == "info"
    assert council_license.status == "ok"
    assert council_license.category == "license_detection"

    # The remaining license hard-blocker is the constitution split-license
    # divergence (live Apache-2.0 vs pinned NOASSERTION).
    constitution_license = findings["github.license.hapax-constitution.registry-mismatch"]
    assert constitution_license.severity == "high"
    assert constitution_license.status == "unreconciled"
    assert "github-public-claim-evidence-gate" in constitution_license.blocks

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


def test_closed_repo_pres_claims_are_compared_without_deleting_records() -> None:
    report = _report()
    claims = {claim.task_id: claim for claim in report.closed_repo_pres_claims}

    assert claims["repo-pres-license-policy"].live_status == "true"
    assert claims["repo-pres-notice-md-all-repos"].live_status == "true"
    assert claims["repo-pres-issues-redirect-walls"].live_status == "true"
    assert claims["repo-pres-org-level-github"].live_status == "true"
    assert "github_license_spdx=NOASSERTION" in claims["repo-pres-license-policy"].live_status_basis
    assert (
        "issue_template_config=True" in claims["repo-pres-issues-redirect-walls"].live_status_basis
    )
    profile_claim = claims["repo-pres-org-level-github"]
    assert "profile_readme=True" in profile_claim.live_status_basis
    assert any(
        ref.startswith("live-report:repo:hapax-systems/.github:file:profile/README.md:sha=")
        for ref in profile_claim.live_witness_refs
    )
    assert all(claim.live_status_basis for claim in claims.values())
    assert all(claim.live_witness_refs for claim in claims.values())
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
    assert package_findings[0].status == "observed"
    assert {surface.claim_status for surface in report.local_evidence.package_surfaces} == {
        "evidence_only"
    }


def test_every_required_category_has_positive_witness_when_clean() -> None:
    """A healthier estate must not invalidate the report.

    Categories whose checks find no drift must still appear via an
    ok-status witness, or missing_required_categories fails on
    absent-because-clean (regression: contributing_governance vanished
    once GOVERNANCE.md landed on the live default branch).
    """
    findings = build_drift_findings(repos={}, local=_minimal_local_evidence())
    present = {finding.category for finding in findings}
    assert set(REQUIRED_DRIFT_CATEGORIES) <= present

    witnesses = [
        finding for finding in findings if finding.finding_id.endswith(".no-drift-observed")
    ]
    for finding in witnesses:
        assert finding.status == "ok"
        assert finding.severity == "info"
