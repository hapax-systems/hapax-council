"""Tests for the GitHub public material claim gate."""

from __future__ import annotations

from agents.metadata_composer.public_claim_gate import Decision
from shared.github_public_claim_gate import (
    GitHubClaimClass,
    GitHubMaterialEvidenceEnvelope,
    GitHubPublicSurface,
    ResearchStatus,
    evaluate_github_public_claims,
    github_material_envelope_from_mapping,
)


def _envelope(**overrides: object) -> GitHubMaterialEvidenceEnvelope:
    base = {
        "surface": GitHubPublicSurface.README,
        "repo": "ryanklee/hapax-council",
        "source_commit": "abc123",
        "current_source_commit": "abc123",
        "current_source_refs": ("CLAUDE.md", "docs/repo-pres/repo-registry.yaml"),
        "live_state_report_ref": "docs/repo-pres/github-public-surface-live-state-reconcile.json",
        "profile_repo_present": True,
        "license_present": True,
        "notice_present": True,
        "citation_present": True,
        "codemeta_present": True,
        "zenodo_present": True,
        "declared_license": "PolyForm-Strict-1.0.0",
        "github_detected_license": "PolyForm-Strict-1.0.0",
        "contributing_present": True,
        "governance_present": True,
        "has_issues": False,
        "has_discussions": False,
        "has_wiki": False,
        "sponsor_surface_active": False,
        "settings_witness_refs": ("gh:repos/ryanklee/hapax-council",),
        "issue_template_present": True,
        "research_status": ResearchStatus.SPEC_READY,
    }
    base.update(overrides)
    return GitHubMaterialEvidenceEnvelope(**base)


def _blocked_classes(text: str, envelope: GitHubMaterialEvidenceEnvelope) -> set[str]:
    verdict = evaluate_github_public_claims(text, envelope)
    return {finding.claim_class.value for finding in verdict.blocked_findings}


def test_research_status_taxonomy_distinguishes_required_statuses() -> None:
    assert {status.value for status in ResearchStatus} == {
        "implemented",
        "pilot",
        "spec_ready",
        "dry_run",
        "public_archive",
        "empirically_validated",
    }


def test_missing_material_envelope_refuses_public_copy() -> None:
    verdict = evaluate_github_public_claims("Hapax is a single-operator system.", None)

    assert verdict.allows_emission is False
    assert verdict.blocked_findings[0].claim_class is GitHubClaimClass.MATERIAL_CURRENTNESS
    assert "missing GitHub material evidence envelope" in verdict.blocked_findings[0].reason


def test_stale_readme_claim_requires_current_source_refs() -> None:
    envelope = _envelope(source_commit="old-sha", current_source_commit="new-sha")

    classes = _blocked_classes("Hapax is a single-operator operating environment.", envelope)

    assert GitHubClaimClass.MATERIAL_CURRENTNESS.value in classes


def test_missing_profile_repo_blocks_profile_claims() -> None:
    envelope = _envelope(
        surface=GitHubPublicSurface.PROFILE,
        profile_repo_present=False,
    )

    verdict = evaluate_github_public_claims("Profile README for Hapax.", envelope)

    assert GitHubClaimClass.MATERIAL_CURRENTNESS.value in _blocked_classes(
        "Profile README for Hapax.", envelope
    )
    assert "organization profile README repo" in verdict.blocked_findings[0].reason


def test_missing_contributing_blocks_contribution_claims() -> None:
    envelope = _envelope(
        contributing_present=False,
        has_issues=True,
    )

    classes = _blocked_classes("Open an issue or contribute a pull request.", envelope)

    assert GitHubClaimClass.CONTRIBUTION_REFUSAL.value in classes


def test_contribution_claim_requires_live_settings_witnesses() -> None:
    envelope = _envelope(settings_witness_refs=(), contributing_present=True)

    verdict = evaluate_github_public_claims("Contributors can participate here.", envelope)

    assert verdict.allows_emission is False
    assert any("settings witnesses" in finding.reason for finding in verdict.blocked_findings)


def test_license_mismatch_blocks_license_claim() -> None:
    envelope = _envelope(github_detected_license="Apache-2.0")

    verdict = evaluate_github_public_claims(
        "Licensed under PolyForm Strict 1.0.0 with DOI-ready citation metadata.",
        envelope,
    )

    license_findings = [
        finding
        for finding in verdict.blocked_findings
        if finding.claim_class is GitHubClaimClass.LICENSE
    ]
    assert license_findings
    assert license_findings[0].decision is Decision.CORRECT
    assert "Apache-2.0" in license_findings[0].reason


def test_issues_enabled_blocks_disabled_issue_claim() -> None:
    envelope = _envelope(has_issues=True)

    verdict = evaluate_github_public_claims("Issues are disabled for this repository.", envelope)

    assert GitHubClaimClass.CONTRIBUTION_REFUSAL.value in {
        finding.claim_class.value for finding in verdict.blocked_findings
    }
    assert any("issues_disabled=False" in finding.reason for finding in verdict.blocked_findings)


def test_package_readme_issue_invitation_requires_live_issue_surface() -> None:
    envelope = _envelope(
        surface=GitHubPublicSurface.PACKAGE_README,
        has_issues=False,
    )

    verdict = evaluate_github_public_claims("Open an issue for package support.", envelope)

    assert verdict.allows_emission is False
    assert any(
        finding.claim_class is GitHubClaimClass.CONTRIBUTION_REFUSAL
        for finding in verdict.blocked_findings
    )


def test_live_current_claim_requires_fresh_wcs_or_publication_event_refs() -> None:
    stale = _envelope()
    fresh = _envelope(wcs_refs=("wcs:runtime-health",), current_ref_age_s=2.0)

    stale_verdict = evaluate_github_public_claims("The current system is live now.", stale)
    fresh_verdict = evaluate_github_public_claims("The current system is live now.", fresh)

    assert GitHubClaimClass.LIVE_CURRENT_SYSTEM.value in {
        finding.claim_class.value for finding in stale_verdict.blocked_findings
    }
    assert fresh_verdict.allows_emission is True


def test_release_note_overclaim_blocks_research_artifact_support_and_monetization() -> None:
    envelope = _envelope(surface=GitHubPublicSurface.RELEASE_NOTES)

    classes = _blocked_classes(
        (
            "This release is an empirically validated public artifact ready for "
            "support and monetization."
        ),
        envelope,
    )

    assert classes >= {
        GitHubClaimClass.RESEARCH_STATUS.value,
        GitHubClaimClass.SUPPORT.value,
        GitHubClaimClass.ARTIFACT.value,
        GitHubClaimClass.MONETIZATION.value,
    }


def test_complete_envelope_allows_bounded_spec_ready_license_copy() -> None:
    envelope = _envelope()

    verdict = evaluate_github_public_claims(
        "This spec-ready material is licensed as PolyForm Strict 1.0.0.",
        envelope,
    )

    assert verdict.allows_emission is True
    assert {finding.decision for finding in verdict.findings} == {Decision.ALLOW}


def test_mapping_parser_accepts_json_like_fixture() -> None:
    envelope = github_material_envelope_from_mapping(
        {
            "surface": "release_notes",
            "repo": "ryanklee/hapax-council",
            "source_commit": "abc123",
            "current_source_commit": "abc123",
            "current_source_refs": ["CLAUDE.md"],
            "research_status": "dry_run",
        }
    )

    assert envelope.surface is GitHubPublicSurface.RELEASE_NOTES
    assert envelope.research_status is ResearchStatus.DRY_RUN
