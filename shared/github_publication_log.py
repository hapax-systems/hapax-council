"""GitHub public-material publication witness rows.

The live-state reconciler records what GitHub currently exposes. This module
projects that evidence into append-only ``publication.github.*`` rows so the
value-braid snapshot can distinguish witnessed publication state from planned
or assumed public presence.

These rows are evidence of public-surface existence or absence only. They do
not grant truth, rights, privacy, egress, support, monetization, or research
validity authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.github_public_surface import (
    GitHubPublicSurfaceReport,
    PackageSurface,
    RepoFilePresence,
    RepoLiveState,
)

DEFAULT_PUBLICATION_LOG = Path.home() / "hapax-state/publication/publication-log.jsonl"
PRODUCER = "shared.github_publication_log"
TASK_ANCHOR = "github-publication-log-value-braid-adapter"
CLAIM_CEILING = "publication_witness_rows"
ANTI_OVERCLAIM_REASON = (
    "publication_row_does_not_grant_truth_rights_privacy_egress_support_"
    "monetization_or_research_validity"
)

type GitHubPublicationEventType = Literal[
    "publication.github.metadata",
    "publication.github.readme",
    "publication.github.profile",
    "publication.github.release",
    "publication.github.package",
    "publication.github.pages",
    "publication.github.citation",
    "publication.github.governance",
]

type GitHubPublicationSurface = Literal[
    "repo_metadata",
    "readme",
    "profile",
    "release",
    "package",
    "pages",
    "citation_metadata",
    "security_governance",
]

type GitHubPublicationMode = Literal["private", "dry_run", "public_archive"]
type GitHubPublicationState = Literal[
    "public",
    "dry_run",
    "missing_or_private",
    "withdrawn",
    "correction",
    "refusal",
]


class GitHubPublicationLogModel(BaseModel):
    """Strict immutable base for GitHub publication-log records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class GitHubPublicationLogEvent(GitHubPublicationLogModel):
    """One witnessed GitHub public-material publication row."""

    schema_version: Literal[1] = 1
    event_id: str = Field(pattern=r"^ghpub:[a-z0-9_.:-]+$")
    event_type: GitHubPublicationEventType
    generated_at: str
    occurred_at: str
    producer: Literal["shared.github_publication_log"] = PRODUCER
    task_anchor: Literal["github-publication-log-value-braid-adapter"] = TASK_ANCHOR
    repo: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    surface: GitHubPublicationSurface
    surface_id: str = Field(min_length=1)
    ref: str | None = None
    commit_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    content_sha: str | None = Field(default=None, min_length=7)
    source_refs: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    claim_ceiling: Literal["publication_witness_rows"] = CLAIM_CEILING
    publication_mode: GitHubPublicationMode
    publication_state: GitHubPublicationState
    live_url: str | None = None
    notes: tuple[str, ...] = Field(default_factory=tuple)
    truth_authority: Literal[False] = False
    rights_authority: Literal[False] = False
    privacy_authority: Literal[False] = False
    egress_authority: Literal[False] = False
    support_authority: Literal[False] = False
    monetization_authority: Literal[False] = False
    research_validity_authority: Literal[False] = False
    value_braid_authority: Literal["witness_only"] = "witness_only"

    @model_validator(mode="after")
    def _publication_state_matches_evidence(self) -> Self:
        if not self.event_type.startswith("publication.github."):
            raise ValueError("GitHub publication events must use publication.github.* type")
        if self.publication_state == "public":
            if self.publication_mode != "public_archive":
                raise ValueError("public GitHub rows must use public_archive mode")
            if not self.live_url:
                raise ValueError("public GitHub rows need a live_url")
            if not self.commit_sha:
                raise ValueError("public GitHub rows need a commit_sha")
            if not self.content_sha:
                raise ValueError("public GitHub rows need a content_sha")
        if self.publication_state == "missing_or_private":
            if self.publication_mode != "private":
                raise ValueError("missing/private GitHub rows must stay private")
            if self.live_url is not None:
                raise ValueError("missing/private GitHub rows cannot carry live_url")
        return self

    def to_json_line(self) -> str:
        """Serialize as a deterministic JSONL line."""

        return json.dumps(self.model_dump(mode="json"), sort_keys=True) + "\n"


def github_publication_log_event_json_schema() -> dict[str, Any]:
    """Return the JSON schema for ``publication.github.*`` rows."""

    return GitHubPublicationLogEvent.model_json_schema()


def build_github_publication_event(
    *,
    repo: str,
    surface: GitHubPublicationSurface,
    generated_at: str,
    occurred_at: str,
    source_refs: tuple[str, ...],
    evidence_refs: tuple[str, ...],
    publication_state: GitHubPublicationState,
    publication_mode: GitHubPublicationMode,
    live_url: str | None,
    commit_sha: str | None,
    content_sha: str | None,
    ref: str | None = None,
    surface_id: str | None = None,
    event_type: GitHubPublicationEventType | None = None,
    notes: tuple[str, ...] = (),
) -> GitHubPublicationLogEvent:
    """Build one stable GitHub publication witness row."""

    selected_event_type = event_type or event_type_for_surface(surface)
    selected_surface_id = surface_id or f"github.{surface}.{repo}"
    event_id = github_publication_event_id(
        repo=repo,
        surface=surface,
        content_sha=content_sha,
        publication_state=publication_state,
        ref=ref,
    )
    return GitHubPublicationLogEvent(
        event_id=event_id,
        event_type=selected_event_type,
        generated_at=generated_at,
        occurred_at=occurred_at,
        repo=repo,
        surface=surface,
        surface_id=selected_surface_id,
        ref=ref,
        commit_sha=commit_sha,
        content_sha=content_sha,
        source_refs=dedupe(source_refs),
        evidence_refs=dedupe(evidence_refs),
        publication_mode=publication_mode,
        publication_state=publication_state,
        live_url=live_url,
        notes=dedupe((*notes, ANTI_OVERCLAIM_REASON)),
    )


def event_type_for_surface(surface: GitHubPublicationSurface) -> GitHubPublicationEventType:
    """Map a public-material surface to a publication event type."""

    return {
        "repo_metadata": "publication.github.metadata",
        "readme": "publication.github.readme",
        "profile": "publication.github.profile",
        "release": "publication.github.release",
        "package": "publication.github.package",
        "pages": "publication.github.pages",
        "citation_metadata": "publication.github.citation",
        "security_governance": "publication.github.governance",
    }[surface]


def github_publication_event_id(
    *,
    repo: str,
    surface: GitHubPublicationSurface,
    content_sha: str | None,
    publication_state: GitHubPublicationState,
    ref: str | None = None,
) -> str:
    """Return a stable schema-safe event id."""

    repo_slug = slug(repo.replace("/", "_"))
    ref_slug = slug(ref or "default")
    content = slug((content_sha or "no-content")[:16])
    return f"ghpub:{repo_slug}:{surface}:{ref_slug}:{content}:{publication_state}"


def events_from_github_public_surface_report(
    report: GitHubPublicSurfaceReport,
    *,
    generated_at: str | None = None,
) -> tuple[GitHubPublicationLogEvent, ...]:
    """Project a GitHub live-state report into publication witness rows."""

    generated = generated_at or isoformat_z(datetime.now(tz=UTC))
    source_refs = (
        "docs/repo-pres/github-public-surface-live-state-reconcile.json",
        *report.source_refs,
    )
    events: list[GitHubPublicationLogEvent] = []
    for repo in (*report.live_repos, *report.profile_repo_candidates):
        events.append(_repo_metadata_event(repo, generated_at=generated, source_refs=source_refs))
        if not _repo_is_public(repo):
            continue
        for path, file_info in sorted(repo.files.items()):
            surface = file_surface(repo, path)
            if surface is None or not file_info.exists:
                continue
            events.append(
                _file_event(
                    repo,
                    file_info,
                    surface=surface,
                    generated_at=generated,
                    source_refs=source_refs,
                )
            )
        if repo.releases.count and repo.releases.latest_tag_name:
            events.append(_release_event(repo, generated_at=generated, source_refs=source_refs))
        if repo.pages.exists and repo.pages.html_url:
            events.append(_pages_event(repo, generated_at=generated, source_refs=source_refs))

    for package_surface in report.local_evidence.package_surfaces:
        if (
            package_surface.has_readme
            or package_surface.has_citation
            or package_surface.has_pyproject
        ):
            events.append(
                _package_event(
                    package_surface,
                    repo_head=report.local_evidence.repo_head,
                    generated_at=generated,
                    source_refs=source_refs,
                )
            )
    return tuple(events)


def write_publication_log_events(
    events: tuple[GitHubPublicationLogEvent, ...],
    *,
    log_path: Path = DEFAULT_PUBLICATION_LOG,
    dry_run: bool = False,
) -> tuple[str, ...]:
    """Serialize events and optionally append them to the publication log."""

    lines = tuple(event.to_json_line() for event in events)
    if dry_run:
        return lines
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.writelines(lines)
    return lines


def classify_publication_log_payload(payload: Any) -> tuple[str, tuple[str, ...]]:
    """Classify the last publication-log payload for the snapshot runner."""

    if not payload:
        return "missing", ("empty_publication_log",)
    if not isinstance(payload, dict):
        return "malformed", ("publication_log_payload_not_mapping",)
    event_type = str(payload.get("event_type") or "")
    if not event_type.startswith("publication.github."):
        return "ok", ("publication_witness_present",)
    try:
        event = GitHubPublicationLogEvent.model_validate(payload)
    except ValueError as exc:
        return "malformed", (f"github_publication_event_invalid:{exc.__class__.__name__}",)
    if event.publication_state == "missing_or_private":
        return "degraded", ("github_publication_missing_or_private", ANTI_OVERCLAIM_REASON)
    return "ok", ("github_publication_witness", ANTI_OVERCLAIM_REASON)


def file_surface(repo: RepoLiveState, path: str) -> GitHubPublicationSurface | None:
    """Return the publication surface represented by a GitHub file path."""

    if path == "README.md":
        return "profile" if repo.repo_id == "ryanklee/ryanklee" else "readme"
    if path in {"CITATION.cff", "codemeta.json", ".zenodo.json"}:
        return "citation_metadata"
    if path in {"NOTICE.md", "SECURITY.md", "CONTRIBUTING.md", "GOVERNANCE.md"}:
        return "security_governance"
    return None


def _repo_metadata_event(
    repo: RepoLiveState,
    *,
    generated_at: str,
    source_refs: tuple[str, ...],
) -> GitHubPublicationLogEvent:
    is_public = _repo_is_public(repo)
    state: GitHubPublicationState = "public" if is_public else "missing_or_private"
    mode: GitHubPublicationMode = "public_archive" if is_public else "private"
    content_sha = digest_json(
        {
            "repo_id": repo.repo_id,
            "visibility": repo.visibility,
            "description": repo.description,
            "topics": repo.topics,
            "default_branch_sha": repo.default_branch_sha,
            "license_spdx": repo.license_spdx,
            "has_issues": repo.has_issues,
            "has_discussions": repo.has_discussions,
            "has_wiki": repo.has_wiki,
            "has_projects": repo.has_projects,
        }
    )
    return build_github_publication_event(
        repo=repo.repo_id,
        surface="repo_metadata",
        generated_at=generated_at,
        occurred_at=repo.pushed_at or generated_at,
        commit_sha=repo.default_branch_sha if is_public else None,
        content_sha=content_sha if is_public else None,
        source_refs=source_refs,
        evidence_refs=(f"gh:repos/{repo.repo_id}",),
        publication_state=state,
        publication_mode=mode,
        live_url=repo.html_url if is_public else None,
        ref=repo.default_branch,
        notes=("repo_metadata_witness",),
    )


def _file_event(
    repo: RepoLiveState,
    file_info: RepoFilePresence,
    *,
    surface: GitHubPublicationSurface,
    generated_at: str,
    source_refs: tuple[str, ...],
) -> GitHubPublicationLogEvent:
    return build_github_publication_event(
        repo=repo.repo_id,
        surface=surface,
        generated_at=generated_at,
        occurred_at=repo.pushed_at or generated_at,
        commit_sha=repo.default_branch_sha,
        content_sha=file_info.sha,
        source_refs=source_refs,
        evidence_refs=(f"gh:contents/{repo.repo_id}/{file_info.path}",),
        publication_state="public",
        publication_mode="public_archive",
        live_url=file_info.html_url or repo.html_url,
        ref=repo.default_branch,
        surface_id=f"github.{surface}.{repo.repo_id}.{file_info.path}",
        notes=(f"file:{file_info.path}",),
    )


def _release_event(
    repo: RepoLiveState,
    *,
    generated_at: str,
    source_refs: tuple[str, ...],
) -> GitHubPublicationLogEvent:
    payload = repo.releases.model_dump(mode="json")
    tag = repo.releases.latest_tag_name or "release"
    return build_github_publication_event(
        repo=repo.repo_id,
        surface="release",
        generated_at=generated_at,
        occurred_at=repo.releases.latest_published_at or generated_at,
        commit_sha=repo.default_branch_sha,
        content_sha=digest_json(payload),
        source_refs=source_refs,
        evidence_refs=(f"gh:repos/{repo.repo_id}/releases",),
        publication_state="public",
        publication_mode="public_archive",
        live_url=f"{repo.html_url}/releases/tag/{tag}" if repo.html_url else None,
        ref=tag,
        notes=("release_or_tag_witness_only",),
    )


def _pages_event(
    repo: RepoLiveState,
    *,
    generated_at: str,
    source_refs: tuple[str, ...],
) -> GitHubPublicationLogEvent:
    payload = repo.pages.model_dump(mode="json")
    return build_github_publication_event(
        repo=repo.repo_id,
        surface="pages",
        generated_at=generated_at,
        occurred_at=repo.pushed_at or generated_at,
        commit_sha=repo.default_branch_sha,
        content_sha=digest_json(payload),
        source_refs=source_refs,
        evidence_refs=(f"gh:repos/{repo.repo_id}/pages",),
        publication_state="public",
        publication_mode="public_archive",
        live_url=repo.pages.html_url,
        ref=repo.pages.source_branch or repo.default_branch,
        notes=("pages_publication_witness_only",),
    )


def _package_event(
    package_surface: PackageSurface,
    *,
    repo_head: str,
    generated_at: str,
    source_refs: tuple[str, ...],
) -> GitHubPublicationLogEvent:
    payload = package_surface.model_dump(mode="json")
    path = package_surface.path
    return build_github_publication_event(
        repo="ryanklee/hapax-council",
        surface="package",
        generated_at=generated_at,
        occurred_at=generated_at,
        commit_sha=repo_head if re.fullmatch(r"[0-9a-f]{40}", repo_head) else None,
        content_sha=digest_json(payload),
        source_refs=source_refs,
        evidence_refs=tuple(package_surface.evidence_refs),
        publication_state="public",
        publication_mode="public_archive",
        live_url=f"https://github.com/ryanklee/hapax-council/tree/{repo_head}/{path}",
        ref=repo_head,
        surface_id=f"github.package.ryanklee/hapax-council.{path}",
        notes=(f"package_claim_status:{package_surface.claim_status}",),
    )


def _repo_is_public(repo: RepoLiveState) -> bool:
    return repo.exists and repo.private is False and repo.visibility == "public"


def digest_json(payload: Any) -> str:
    """Return a stable sha256 digest for report-derived material."""

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def slug(value: str) -> str:
    """Normalize an event-id component."""

    text = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", value.strip().lower())
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "unknown"


def dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    """Deduplicate strings while preserving order."""

    return tuple(dict.fromkeys(value for value in values if value))


def isoformat_z(value: datetime) -> str:
    """Return a UTC RFC3339 timestamp with ``Z`` suffix."""

    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "ANTI_OVERCLAIM_REASON",
    "CLAIM_CEILING",
    "DEFAULT_PUBLICATION_LOG",
    "GitHubPublicationLogEvent",
    "build_github_publication_event",
    "classify_publication_log_payload",
    "events_from_github_public_surface_report",
    "github_publication_event_id",
    "github_publication_log_event_json_schema",
    "write_publication_log_events",
]
