"""WeblogPublisher — operator-reviewed draft to omg.lol."""

from __future__ import annotations

import argparse
import logging
import re
import sys
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Any

import yaml

from shared.governance.omg_referent import OperatorNameLeak, safe_render
from shared.governance.publication_allowlist import check as allowlist_check

log = logging.getLogger(__name__)

SURFACE = "omg-lol-weblog"
DEFAULT_ADDRESS = "hapax"

try:
    from prometheus_client import Counter

    _PUBLISH_TOTAL = Counter(
        "hapax_broadcast_omg_weblog_publishes_total",
        "omg.lol weblog publishes by outcome.",
        ["result"],
    )

    def _record(outcome: str) -> None:
        _PUBLISH_TOTAL.labels(result=outcome).inc()
except ImportError:

    def _record(outcome: str) -> None:
        log.debug("prometheus_client unavailable; metric dropped")


_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[-_]?(.*))?$")
_SLUG_CLEAN_RE = re.compile(r"[^a-z0-9-]+")


@dataclass(frozen=True)
class WeblogDraft:
    """Parsed draft — slug + content + approval state.

    ``approved`` defaults to ``False`` for drafts from
    ``agents.omg_weblog_composer`` (Phase A). Operator flips the
    frontmatter ``approved: true`` after review; publish gate enforces
    this in :meth:`WeblogPublisher.publish` (returns
    ``"not-approved"`` when False).
    """

    slug: str
    content: str
    title: str
    approved: bool = False
    grounding_gate_result: dict[str, Any] | None = None


def derive_entry_slug(filename: str) -> str:
    """Derive a URL-safe slug from a draft filename.

    Accepts ``2026-04-24-something.md`` or ``arbitrary-title.md`` and
    returns a lowercase kebab-cased slug. Strips extension and any
    lead-in period. A pure ISO-date name (``2026-04-24.md``) returns
    the ISO date itself.
    """
    stem = Path(filename).stem
    # Date prefix: keep the date portion; if there's a tail use both.
    m = _DATE_PREFIX_RE.match(stem)
    if m:
        date, tail = m.group(1), (m.group(2) or "").strip("-_ ")
        base = f"{date}-{tail}" if tail else date
    else:
        base = stem
    # Kebab-case: lowercase + collapse non-alphanumerics to hyphen.
    slug = _SLUG_CLEAN_RE.sub("-", base.lower()).strip("-")
    return slug or "untitled"


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (frontmatter_dict, body_text). Empty dict if no frontmatter.

    Frontmatter is stripped from the body so it never reaches the
    omg.lol weblog payload.
    """
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    try:
        frontmatter = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return {}, text
    body = text[end + len("\n---\n") :]
    return (frontmatter if isinstance(frontmatter, dict) else {}), body


def parse_draft(path: Path) -> WeblogDraft:
    """Read a draft file and return slug + content + title + approval flag.

    Reads YAML frontmatter (if present), strips it from the published
    body, and lifts the ``approved`` flag onto the returned draft.
    Title extraction: frontmatter ``title`` if present; else first ``# ``
    heading; else filename-derived slug.
    """
    raw = path.read_text(encoding="utf-8")
    slug = derive_entry_slug(path.name)
    frontmatter, body = _split_frontmatter(raw)

    title = frontmatter.get("title", "") or slug
    if isinstance(title, str):
        title = title.strip() or slug

    if not frontmatter.get("title"):
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                title = stripped.lstrip("# ").strip() or slug
                break

    approved = bool(frontmatter.get("approved", False))
    raw_grounding_gate = frontmatter.get("grounding_gate_result")
    grounding_gate_result = raw_grounding_gate if isinstance(raw_grounding_gate, dict) else None

    return WeblogDraft(
        slug=slug,
        content=body.lstrip("\n"),
        title=title,
        approved=approved,
        grounding_gate_result=grounding_gate_result,
    )


class WeblogPublisher:
    """Publish an operator-reviewed weblog draft.

    Parameters:
        client:    :class:`OmgLolClient` (may be disabled)
        address:   omg.lol address
    """

    def __init__(self, *, client: Any, address: str = DEFAULT_ADDRESS) -> None:
        self.client = client
        self.address = address

    def publish(self, draft: WeblogDraft, *, dry_run: bool = False) -> str:
        """Publish the draft. Returns one of:
        ``"published"`` | ``"dry-run"`` | ``"client-disabled"`` |
        ``"allowlist-denied"`` | ``"not-approved"`` | ``"failed"``.

        Approval gate: drafts with ``approved=False`` short-circuit at
        the start. The Phase A composer (``agents/omg_weblog_composer``)
        emits ``approved: false`` by default; operator flips the
        frontmatter flag to ``true`` after review.
        """
        if not draft.approved:
            log.info("omg-weblog: draft %s not approved; skipping publish", draft.slug)
            _record("not-approved")
            return "not-approved"

        # AUDIT-05: scan operator-edited weblog content before publication
        # policy so legal-name leak refusals do not get masked by later
        # allowlist holds.
        try:
            content = safe_render(draft.content, segment_id=draft.slug)
        except OperatorNameLeak:
            log.warning("omg-weblog: legal-name leak detected — DROPPING publish")
            _record("legal-name-leak")
            return "legal-name-leak"

        allow = allowlist_check(
            SURFACE,
            "weblog.entry",
            {
                "title": draft.title,
                "slug": draft.slug,
                "content": content,
                "grounding_gate_result": draft.grounding_gate_result,
            },
        )
        if allow.decision == "deny":
            log.warning("omg-weblog: allowlist denied (%s)", allow.reason)
            _record("allowlist-denied")
            return "allowlist-denied"

        if dry_run:
            log.info("omg-weblog: dry-run — slug=%s, %d chars", draft.slug, len(draft.content))
            _record("dry-run")
            return "dry-run"

        if not getattr(self.client, "enabled", False):
            log.warning("omg-weblog: client disabled — skipping publish")
            _record("client-disabled")
            return "client-disabled"

        result = _publish_weblog_entry_through_bus(
            client=self.client,
            address=self.address,
            slug=draft.slug,
            content=content,
        )
        if result.refused:
            log.warning(
                "omg-weblog: publication bus refused draft %s: %s", draft.slug, result.detail
            )
            _record("allowlist-denied")
            return "allowlist-denied"
        if result.error:
            log.warning(
                "omg-weblog: publication bus failed draft %s: %s", draft.slug, result.detail
            )
            _record("failed")
            return "failed"

        log.info("omg-weblog: published %s", draft.slug)
        _record("published")
        return "published"


# ── Orchestrator entry-point (PUB-P2-C foundation) ───────────────────


def publish_artifact(  # type: ignore[no-untyped-def]
    artifact,
    *,
    address: str = DEFAULT_ADDRESS,
    pass_key: str = "omg-lol/api-key",
) -> str:
    """Dispatch a ``PreprintArtifact`` to an omg.lol weblog account.

    Static entry-point consumed by ``agents/publish_orchestrator``'s
    surface registry. Returns one of: ``ok | denied | auth_error |
    error | no_credentials | legal_name_leak``. Never raises.

    Per the 2026-04-25 4-cluster automation-tractability audit, omg.lol
    weblog is operator-owned and FULL_AUTO eligible. The Refusal Brief's
    Locus 2 (the standalone web essay) lives at hapax.omg.lol/refusal,
    so this entry-point is the unblocking work for that publish.

    The ``address`` + ``pass_key`` kwargs select which omg.lol account
    receives the artifact; the orchestrator binds them through sibling
    surface entries (``omg-weblog`` for hapax, ``oudepode-omg-weblog``
    for oudepode). Operator-side cross-account routing is metadata on
    the artifact itself — the publisher does not infer.

    Composition: the artifact's ``slug`` becomes the omg.lol entry slug,
    ``title`` renders as a markdown ``# H1`` at the top, ``attribution_block``
    + ``abstract`` + ``body_md`` follow. ``safe_render`` passes the
    composed content through the legal-name-leak guard.

    Bypasses the WeblogDraft approval-gate because orchestrator-dispatched
    artifacts have already passed the inbox approval gate (DRAFT →
    APPROVED via ``mark_approved``).
    """
    from shared.omg_lol_client import OmgLolClient

    client = OmgLolClient(address=address, pass_key=pass_key)
    if not client.enabled:
        log.info(
            "omg-weblog[%s]: API key unavailable; deferring artifact %s",
            address,
            artifact.slug,
        )
        _record("no_credentials")
        return "no_credentials"

    content = _compose_artifact_content(artifact)
    if not content:
        log.error("omg-weblog: empty content for artifact %s", artifact.slug)
        _record("error")
        return "error"

    try:
        guarded = safe_render(content, segment_id=artifact.slug)
    except OperatorNameLeak:
        log.warning("omg-weblog: legal-name leak in artifact %s — DROPPING", artifact.slug)
        _record("legal_name_leak")
        return "error"

    verdict = allowlist_check(
        SURFACE,
        "weblog.entry",
        {
            "title": artifact.title,
            "slug": artifact.slug,
            "content": guarded,
            "grounding_gate_result": getattr(artifact, "grounding_gate_result", None),
        },
    )
    if verdict.decision == "deny":
        log.warning("omg-weblog: allowlist denied artifact %s (%s)", artifact.slug, verdict.reason)
        _record("denied")
        return "denied"

    result = _publish_weblog_entry_through_bus(
        client=client,
        address=address,
        slug=artifact.slug,
        content=guarded,
    )
    if result.refused:
        log.warning(
            "omg-weblog[%s]: publication bus refused artifact %s: %s",
            address,
            artifact.slug,
            result.detail,
        )
        _record("denied")
        return "denied"
    if result.error:
        log.warning(
            "omg-weblog[%s]: publication bus failed artifact %s: %s",
            address,
            artifact.slug,
            result.detail,
        )
        _record("error")
        return "error"

    log.info("omg-weblog[%s]: published artifact %s", address, artifact.slug)
    _record("ok")
    return "ok"


def publish_artifact_oudepode(artifact) -> str:  # type: ignore[no-untyped-def]
    """Dispatch a ``PreprintArtifact`` to the oudepode omg.lol weblog account.

    Sibling entry-point for the operator's second omg.lol identity. The
    hapax account carries the system-side surface (Manifesto, Refusal
    Brief, governance disclosures); the oudepode account carries the
    music-side surface (cohort disclosures, release-window companion
    notes, future Insights-API attestations). Cross-linking happens at
    artifact authorship time, not at publish time — this function is
    just the credential + address selector.
    """
    return publish_artifact(
        artifact,
        address="oudepode",
        pass_key="omg-lol/oudepode-api-key",
    )


def _compose_artifact_content(artifact) -> str:  # type: ignore[no-untyped-def]
    """Render a ``PreprintArtifact`` to omg.lol weblog entry format.

    omg.lol weblog entries are markdown with YAML frontmatter; the
    ``Date:`` field is required (omg.lol parses the title from the
    first ``# H1`` heading and auto-derives the slug from the title).
    Without the frontmatter block the entry stores blank title + body,
    so this function ALWAYS prepends a minimal frontmatter even if
    the artifact carries no body.

    Body section order: ``# {title}`` → ``attribution_block`` →
    ``abstract`` → ``body_md``. Each section separated by a blank line.
    If ``body_md`` already contains a leading ``# H1`` matching the
    artifact's title, the duplicate H1 is suppressed (avoids the omg.lol
    parser seeing two title candidates).
    """
    from datetime import datetime  # noqa: I001 — local for testability

    title = (getattr(artifact, "title", "") or "").strip()
    attribution = (getattr(artifact, "attribution_block", "") or "").strip()
    abstract = (getattr(artifact, "abstract", "") or "").strip()
    body_md = (getattr(artifact, "body_md", "") or "").strip()

    # omg.lol parses the FIRST # H1 as the title and derives the URL
    # slug from it. The H1 must be the first content after the Date
    # line — anything before it (e.g., a freestanding attribution
    # paragraph) gets parsed as the title and the actual H1 becomes
    # body.
    #
    # If body_md already leads with the artifact title as ``# {title}``,
    # split it off so the H1 lands first; attribution + abstract follow
    # the H1, then the rest of body_md (with leading H1 removed) closes
    # out. This way the layout is always: Date → H1 → byline →
    # abstract → body, regardless of whether body_md carries its own H1.
    body_after_title = body_md
    leading_title: str | None = None
    if title:
        h1_marker = f"# {title}"
        if body_md.startswith(h1_marker):
            leading_title = h1_marker
            body_after_title = body_md[len(h1_marker) :].lstrip("\n")
        else:
            leading_title = h1_marker

    parts: list[str] = []

    # Inject Open Graph Metadata
    og_tags = [
        '<meta property="og:type" content="article" />',
    ]
    if title:
        # Simple escape for quotes in meta content
        escaped_title = title.replace('"', "&quot;")
        og_tags.append(f'<meta property="og:title" content="{escaped_title}" />')
    if abstract:
        escaped_abstract = abstract.replace('"', "&quot;")
        og_tags.append(f'<meta property="og:description" content="{escaped_abstract}" />')
    if getattr(artifact, "slug", ""):
        og_tags.append(
            f'<meta property="og:url" content="https://hapax.weblog.lol/{artifact.slug}" />'
        )

    parts.append("\n".join(og_tags))

    if leading_title:
        parts.append(leading_title)

    content_parts: list[str] = []
    if attribution:
        content_parts.append(attribution)
    if abstract and not _abstract_duplicates_body(abstract, body_after_title):
        content_parts.append(abstract)
    if body_after_title:
        content_parts.append(body_after_title)

    body_inner = "\n\n".join(content_parts)

    # Per the 2026-04-25 full-automation directive, append the Refusal
    # Brief LONG clause unless the artifact IS the Refusal Brief or
    # already cites it. omg.lol weblog has no enforced ceiling so the
    # LONG form always fits.
    slug = (getattr(artifact, "slug", "") or "").strip()
    if slug != "refusal-brief" and "refusal" not in body_inner.lower():
        from shared.attribution_block import NON_ENGAGEMENT_CLAUSE_LONG

        if body_inner:
            body_inner = f"{body_inner}\n\n{NON_ENGAGEMENT_CLAUSE_LONG}"
        else:
            body_inner = NON_ENGAGEMENT_CLAUSE_LONG

    if not body_inner and not leading_title:
        return ""

    # Build IndieWeb markup
    indieweb_blocks = []
    indieweb_blocks.append('<div class="h-entry">')
    indieweb_blocks.append(
        '<a class="p-author h-card" href="https://hapax.omg.lol" style="display:none">hapax</a>'
    )

    surfaces = getattr(artifact, "surfaces_targeted", []) or []
    if "bluesky-atproto-multi-identity" in surfaces:
        indieweb_blocks.append(
            '<a class="u-syndication" href="https://bsky.app/profile/oudepode.bsky.social" style="display:none">Bluesky</a>'
        )
    if "mastodon-rest-publisher" in surfaces:
        indieweb_blocks.append(
            '<a class="u-syndication" href="https://mastodon.social/@oudepode" style="display:none">Mastodon</a>'
        )
    if "github-readme-profile-current-project-refresh" in surfaces:
        indieweb_blocks.append(
            '<a class="u-syndication" href="https://github.com/hapax-systems" style="display:none">GitHub</a>'
        )

    indieweb_blocks.append('<div class="e-content">')
    indieweb_blocks.append(body_inner)
    indieweb_blocks.append("</div>")
    indieweb_blocks.append("</div>")

    parts.append("\n\n".join(indieweb_blocks))
    body = "\n\n".join(parts)

    # omg.lol weblog entry format: a single ``Date:`` line followed by
    # a blank line, then the markdown body. NOT YAML frontmatter (no
    # triple-dash delimiters). Spec example from api.omg.lol:
    # "Date: 2022-12-11 5:46 PM EDT\n\n# Test post\n\nThis is a test."
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M %Z")
    return f"Date: {timestamp}\n\n{body}"


def _abstract_duplicates_body(abstract: str, body_md: str) -> bool:
    """Return true when an abstract is only the leading body paragraph.

    ``scripts/publish_vault_artifact.py`` derives a default abstract from
    the first non-heading paragraph. Long-form weblog entries already carry
    that paragraph in the body, so rendering the abstract before the body
    produces a duplicated lead and can truncate mid-sentence.
    """

    needle = _normalize_for_duplicate_check(abstract)
    if not needle:
        return False

    haystack = _normalize_for_duplicate_check(body_md)
    if haystack.startswith(needle):
        return True

    for para in body_md.split("\n\n"):
        stripped = para.strip()
        if not stripped or stripped.startswith("#"):
            continue
        normalized = _normalize_for_duplicate_check(stripped)
        if normalized.startswith(needle) or needle.startswith(normalized):
            return True
    return False


def _normalize_for_duplicate_check(text: str) -> str:
    return " ".join(text.split()).strip()


def _publish_weblog_entry_through_bus(
    *,
    client: Any,
    address: str,
    slug: str,
    content: str,
):
    from agents.publication_bus.omg_weblog_publisher import OmgLolWeblogPublisher
    from agents.publication_bus.publisher_kit import PublisherPayload
    from agents.publication_bus.publisher_kit.allowlist import load_allowlist

    OmgLolWeblogPublisher.allowlist = load_allowlist(
        OmgLolWeblogPublisher.surface_name,
        [slug],
    )
    publisher = OmgLolWeblogPublisher(client=client, address=address)
    return publisher.publish(PublisherPayload(target=slug, text=content))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("draft_path", type=Path, help="path to the approved draft markdown")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--address", default=DEFAULT_ADDRESS)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    if not args.draft_path.is_file():
        log.error("draft not found: %s", args.draft_path)
        return 2
    draft = parse_draft(args.draft_path)

    from shared.omg_lol_client import OmgLolClient

    publisher = WeblogPublisher(client=OmgLolClient(address=args.address), address=args.address)
    outcome = publisher.publish(draft, dry_run=args.dry_run)
    print(outcome)
    return 0 if outcome in ("published", "dry-run") else 1


if __name__ == "__main__":
    sys.exit(main())
