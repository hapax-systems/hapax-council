"""Typed publication artifact for the auto-publish bus.

Phase 0 prerequisite (PUB-P0-A) per the v5 workstream realignment. The
``PreprintArtifact`` model is the canonical payload that the
``agents/publish_orchestrator`` watches for in the approval-gated
inbox; each ``surfaces_targeted`` surface is dispatched to its
corresponding publisher in parallel.

## Inbox layout

``~/hapax-state/publish/draft/{slug}.json``    — awaiting approval
``~/hapax-state/publish/inbox/{slug}.json``    — approved, dispatchable
``~/hapax-state/publish/published/{slug}.json`` — every targeted surface returned ``ok``
``~/hapax-state/publish/failed/{slug}.json`` — at least one targeted surface failed/refused
``~/hapax-state/publish/log/{slug}.{surface}.json`` — per-surface outcome

The orchestrator only globs ``inbox/`` so unapproved drafts can sit in
``draft/`` indefinitely without firing.

## Co-author cluster

Every artifact carries a ``co_authors: list[CoAuthor]`` matching the
canonical registry in ``shared/co_author_model.py``. The default is
``ALL_CO_AUTHORS`` (Hapax + Claude Code + Oudepode); per-artifact
overrides handle venue-specific deviations (PsyArXiv compliant byline,
Bandcamp PROTO-precedent performer-only, etc.) — those overrides are
the responsibility of ``shared/attribution_block.py`` (PUB-CITATION-A,
parallel-shippable).

## Constitutional alignment

Per the 2026-04-25 directive (auto-publish BY HAPAX or NOT AT ALL),
every dispatch from this artifact is non-interactive — the operator
moves a draft to ``inbox/`` once, and Hapax handles all surface
dispatch. The ``approved_by_referent`` field captures which
operator-referent (per ``shared/operator_referent.OperatorReferentPicker``)
moved the draft, for auditability.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from shared.co_author_model import ALL_CO_AUTHORS, CoAuthor

DEFAULT_OMG_WEBLOG_SURFACES: tuple[str, ...] = ("omg-weblog",)
OMG_WEBLOG_DIRECT_FANOUT_OPT_IN_SURFACES: tuple[str, ...] = (
    "bluesky-post",
    "mastodon-post",
    "arena-post",
    "bridgy-webmention-publish",
)
OMG_WEBLOG_DIRECT_FANOUT_SURFACES: tuple[str, ...] = (
    *DEFAULT_OMG_WEBLOG_SURFACES,
    *OMG_WEBLOG_DIRECT_FANOUT_OPT_IN_SURFACES,
)

# Inbox layout — relative to ``$HAPAX_STATE`` (default ``~/hapax-state``)
DRAFT_DIR_NAME = "publish/draft"
INBOX_DIR_NAME = "publish/inbox"
PUBLISHED_DIR_NAME = "publish/published"
FAILED_DIR_NAME = "publish/failed"
LOG_DIR_NAME = "publish/log"


class ApprovalState(StrEnum):
    """Lifecycle stages a ``PreprintArtifact`` walks through."""

    DRAFT = "draft"
    AWAITING = "awaiting"
    APPROVED = "approved"
    WITHHELD = "withheld"
    PUBLISHED = "published"
    FAILED = "failed"


class PreprintArtifact(BaseModel):
    """One publishable artifact destined for ≥1 outbound surfaces.

    The ``PreprintArtifact`` is venue-neutral; per-surface composition
    happens at dispatch time via each publisher's ``compose()`` (the
    ``BasePublisher`` ABC pattern, PUB-P0-B). The artifact itself
    carries the canonical content + attribution + target list; the
    publisher renders for the specific surface.
    """

    schema_version: str = "1"
    """Round-trip schema version. Bump when fields are added that older
    consumers cannot ignore (Pydantic v2 ignores unknown fields by
    default, so additive changes don't bump this)."""

    slug: str = Field(min_length=1, max_length=120)
    """URL-safe identifier; used as filename in inbox layout."""

    title: str = Field(min_length=1, max_length=240)
    abstract: str = Field(default="", max_length=4096)
    body_md: str = ""
    body_html: str = ""

    doi: str | None = None
    """Filled in post-publish if any surface mints a DOI (OSF, Zenodo,
    arXiv). Used by downstream artifacts that cite this one."""

    co_authors: list[CoAuthor] = Field(default_factory=lambda: list(ALL_CO_AUTHORS))
    """Default to the canonical Hapax + Claude Code + Oudepode cluster.
    Per-artifact override only when a venue requires deviation (e.g.,
    PsyArXiv strict-AI-content rule = operator-as-primary)."""

    surfaces_targeted: list[str] = Field(default_factory=list)
    """List of allowlist-surface slugs (e.g. ``"bluesky-post"``,
    ``"arena-post"``, ``"osf-preprint"``). Each must have a registered
    publisher in ``agents/publish_orchestrator``'s surface registry;
    unknown surfaces are skipped with a ``surface_unwired`` log entry."""

    approval: ApprovalState = ApprovalState.DRAFT
    approved_at: datetime | None = None
    approved_by_referent: str | None = None
    """Which referent (per OperatorReferentPicker) moved this draft to
    inbox. Logged for auditability; not consumed at dispatch time."""

    attribution_block: str = ""
    """Pre-rendered V1-V5 attribution sentence (per attribution-policy
    flesher §11). Defaults to V5 minimal one-liner when empty; the
    orchestrator can re-render per-surface via
    ``shared/attribution_block.render_attribution()``."""

    embed_image_url: str | None = None
    """Optional hero image / OG card. Most surfaces (Bluesky, Mastodon,
    Are.na, omg.lol) consume; PDF surfaces (OSF, arXiv) ignore."""

    source_path: str | None = None
    """Optional source Markdown path for vault-originated drafts.

    When present, publication hardening can write review metadata back
    into the draft frontmatter before fan-out.
    """

    author_model: str | None = None
    """Optional frontmatter-provided model identifier for cross-provider review."""

    publication_review: dict[str, object] | None = None
    """Latest cross-provider publication review report attached before fan-out."""

    publication_gate_context: dict[str, object] | None = None
    """Optional operator-supplied verifier context for the publication hardening gate."""

    publication_gate_override: dict[str, object] | None = None
    """Optional operator-supplied hold override; rejects remain non-overridable."""

    publication_gate_result: dict[str, object] | None = None
    """Latest aggregate publication-hardening gate receipt attached before fan-out."""

    grounding_gate_result: dict[str, object] | None = None

    # ── Inbox helpers ──────────────────────────────────────────────

    def inbox_path(self, *, state_root: Path) -> Path:
        """Where this artifact lives when ``approval == APPROVED``."""
        return state_root / INBOX_DIR_NAME / f"{self.slug}.json"

    def draft_path(self, *, state_root: Path) -> Path:
        """Where this artifact lives when ``approval`` is in
        ``{DRAFT, AWAITING, WITHHELD}``."""
        return state_root / DRAFT_DIR_NAME / f"{self.slug}.json"

    def published_path(self, *, state_root: Path) -> Path:
        """Where this artifact moves once every targeted surface returns ``ok``."""
        return state_root / PUBLISHED_DIR_NAME / f"{self.slug}.json"

    def failed_path(self, *, state_root: Path) -> Path:
        """Where this artifact moves when any surface reaches a failed terminal state."""
        return state_root / FAILED_DIR_NAME / f"{self.slug}.json"

    def log_path(self, surface: str, *, state_root: Path) -> Path:
        """Per-surface outcome log path."""
        return state_root / LOG_DIR_NAME / f"{self.slug}.{surface}.json"

    def is_approved(self) -> bool:
        return self.approval == ApprovalState.APPROVED

    def mark_approved(self, *, by_referent: str) -> None:
        """Move artifact to APPROVED with audit trail."""
        self.approval = ApprovalState.APPROVED
        self.approved_at = datetime.now(UTC)
        self.approved_by_referent = by_referent

    def mark_published(self) -> None:
        """Move artifact to PUBLISHED after every targeted surface returns ``ok``.

        ``approved_at`` and ``approved_by_referent`` are preserved for the audit trail.
        """
        self.approval = ApprovalState.PUBLISHED

    def mark_failed(self) -> None:
        """Move artifact to FAILED after one or more non-retryable surface failures."""
        self.approval = ApprovalState.FAILED


# ── Construction helpers ────────────────────────────────────────────


def from_omg_weblog_draft(
    *,
    slug: str,
    title: str,
    abstract: str,
    body_md: str,
    surfaces_targeted: list[str] | None = None,
    co_authors: list[CoAuthor] | None = None,
) -> PreprintArtifact:
    """Construct a ``PreprintArtifact`` from omg.lol weblog-draft fields.

    Mirrors ``agents/omg_weblog_publisher/publisher.py::parse_draft``
    field shape so omg.lol drafts upgrade cleanly to multi-surface
    artifacts. Does NOT consume ``WeblogDraft`` directly (would create
    a circular import); callers extract fields and pass them in.

    Default ``surfaces_targeted`` is the canonical omg.lol weblog only.
    Direct Bluesky, Mastodon, Are.na, and Bridgy dispatch remain opt-in
    because the weblog public-event producer already fans out published
    weblog entries after the source URL exists.
    """
    return PreprintArtifact(
        slug=slug,
        title=title,
        abstract=abstract,
        body_md=body_md,
        surfaces_targeted=list(surfaces_targeted or DEFAULT_OMG_WEBLOG_SURFACES),
        co_authors=co_authors or list(ALL_CO_AUTHORS),
    )


__all__ = [
    "ApprovalState",
    "DRAFT_DIR_NAME",
    "DEFAULT_OMG_WEBLOG_SURFACES",
    "FAILED_DIR_NAME",
    "INBOX_DIR_NAME",
    "LOG_DIR_NAME",
    "OMG_WEBLOG_DIRECT_FANOUT_OPT_IN_SURFACES",
    "OMG_WEBLOG_DIRECT_FANOUT_SURFACES",
    "PUBLISHED_DIR_NAME",
    "PreprintArtifact",
    "from_omg_weblog_draft",
]
