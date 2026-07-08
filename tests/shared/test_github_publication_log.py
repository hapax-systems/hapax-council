from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from shared.github_public_surface import GitHubPublicSurfaceReport, RepoFilePresence, RepoLiveState
from shared.github_publication_log import (
    ANTI_OVERCLAIM_REASON,
    GitHubPublicationLogEvent,
    build_github_publication_event,
    classify_publication_log_payload,
    events_from_github_public_surface_report,
    github_publication_log_event_json_schema,
    write_publication_log_events,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = REPO_ROOT / "docs/repo-pres/github-public-surface-live-state-reconcile.json"
GENERATED_AT = "2026-05-01T00:50:00Z"


def _report() -> GitHubPublicSurfaceReport:
    return GitHubPublicSurfaceReport.model_validate(
        json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    )


def _events() -> tuple[GitHubPublicationLogEvent, ...]:
    return events_from_github_public_surface_report(_report(), generated_at=GENERATED_AT)


def test_github_public_surface_report_projects_schema_valid_publication_rows() -> None:
    events = _events()
    schema = github_publication_log_event_json_schema()

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(events[0].model_dump(mode="json"))

    assert events
    assert all(event.event_type.startswith("publication.github.") for event in events)
    assert {event.surface for event in events} >= {"repo_metadata", "readme", "profile", "package"}
    assert all(event.claim_ceiling == "publication_witness_rows" for event in events)


def test_github_publication_rows_are_witness_only_and_anti_overclaim() -> None:
    public_event = next(event for event in _events() if event.publication_state == "public")

    assert public_event.value_braid_authority == "witness_only"
    assert public_event.truth_authority is False
    assert public_event.rights_authority is False
    assert public_event.privacy_authority is False
    assert public_event.egress_authority is False
    assert public_event.support_authority is False
    assert public_event.monetization_authority is False
    assert public_event.research_validity_authority is False
    assert ANTI_OVERCLAIM_REASON in public_event.notes


def test_missing_or_private_rows_do_not_carry_live_urls_or_public_mode() -> None:
    private_event = build_github_publication_event(
        repo="hapax-systems/private-example",
        surface="repo_metadata",
        generated_at=GENERATED_AT,
        occurred_at=GENERATED_AT,
        source_refs=("fixture-report",),
        evidence_refs=("gh:repos/hapax-systems/private-example",),
        publication_state="missing_or_private",
        publication_mode="private",
        live_url=None,
        commit_sha=None,
        content_sha=None,
        ref="main",
    )

    assert private_event.publication_mode == "private"
    assert private_event.live_url is None
    assert private_event.commit_sha is None
    assert private_event.content_sha is None
    assert classify_publication_log_payload(private_event.model_dump(mode="json")) == (
        "degraded",
        ("github_publication_missing_or_private", ANTI_OVERCLAIM_REASON),
    )


def test_missing_public_required_file_projects_degraded_publication_row() -> None:
    report = _report()
    repo = RepoLiveState(
        repo_id="hapax-systems/missing-readme",
        owner="hapax-systems",
        name="missing-readme",
        exists=True,
        private=False,
        visibility="public",
        default_branch="main",
        default_branch_sha="a" * 40,
        html_url="https://github.com/hapax-systems/missing-readme",
        files={"README.md": RepoFilePresence(path="README.md", exists=False)},
    )
    fixture = report.model_copy(
        update={
            "live_repos": (repo,),
            "profile_repo_candidates": (),
            "local_evidence": report.local_evidence.model_copy(update={"package_surfaces": ()}),
        }
    )

    events = events_from_github_public_surface_report(fixture, generated_at=GENERATED_AT)
    missing = next(event for event in events if event.surface == "readme")
    missing_governance = next(event for event in events if event.ref == "main:GOVERNANCE.md")

    assert missing.publication_state == "missing_or_private"
    assert missing.publication_mode == "private"
    assert missing.live_url is None
    assert missing.commit_sha is None
    assert missing.content_sha is None
    assert missing.surface_id.endswith("README.md")
    assert classify_publication_log_payload(missing.model_dump(mode="json")) == (
        "degraded",
        ("github_publication_missing_or_private", ANTI_OVERCLAIM_REASON),
    )
    assert missing_governance.publication_state == "missing_or_private"
    assert missing_governance.evidence_refs == (
        "gh:contents/hapax-systems/missing-readme/GOVERNANCE.md",
    )


def test_org_profile_repo_only_projects_profile_readme_file_surface() -> None:
    report = _report()
    org_profile = RepoLiveState(
        repo_id="hapax-systems/.github",
        owner="hapax-systems",
        name=".github",
        exists=True,
        private=False,
        visibility="public",
        default_branch="main",
        default_branch_sha="a" * 40,
        html_url="https://github.com/hapax-systems/.github",
        files={
            "README.md": RepoFilePresence(path="README.md", exists=False),
            "profile/README.md": RepoFilePresence(
                path="profile/README.md",
                exists=True,
                sha="b" * 40,
                html_url="https://github.com/hapax-systems/.github/blob/main/profile/README.md",
            ),
        },
    )
    fixture = report.model_copy(
        update={
            "live_repos": (),
            "profile_repo_candidates": (org_profile,),
            "local_evidence": report.local_evidence.model_copy(update={"package_surfaces": ()}),
        }
    )

    events = events_from_github_public_surface_report(fixture, generated_at=GENERATED_AT)

    assert any(event.surface == "profile" for event in events)
    assert not any(event.surface == "readme" for event in events)
    assert not any(event.publication_state == "missing_or_private" for event in events)


def test_public_rows_require_direct_public_evidence() -> None:
    with pytest.raises(ValidationError, match="public GitHub rows need a commit_sha"):
        build_github_publication_event(
            repo="hapax-systems/hapax-council",
            surface="readme",
            generated_at=GENERATED_AT,
            occurred_at=GENERATED_AT,
            source_refs=("fixture-report",),
            evidence_refs=("gh:contents/hapax-systems/hapax-council/README.md",),
            publication_state="public",
            publication_mode="public_archive",
            live_url="https://github.com/hapax-systems/hapax-council/blob/main/README.md",
            commit_sha=None,
            content_sha="d19edcddf92f59b91119f689da208056b5cd330f",
            ref="main",
        )


def test_publication_log_writer_supports_dry_run_and_append(tmp_path: Path) -> None:
    events = _events()[:2]
    log_path = tmp_path / "publication-log.jsonl"

    dry_lines = write_publication_log_events(events, log_path=log_path, dry_run=True)
    assert len(dry_lines) == 2
    assert not log_path.exists()

    written_lines = write_publication_log_events(events, log_path=log_path)
    assert written_lines == dry_lines
    assert len(log_path.read_text(encoding="utf-8").splitlines()) == 2
    assert json.loads(written_lines[0])["event_type"].startswith("publication.github.")
