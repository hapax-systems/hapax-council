"""WeblogPublisher — operator-reviewed draft to omg.lol."""

from __future__ import annotations

import argparse
import logging
import re
import sys
from dataclasses import dataclass
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

    return WeblogDraft(slug=slug, content=body.lstrip("\n"), title=title, approved=approved)


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

        allow = allowlist_check(
            SURFACE,
            "weblog.entry",
            {"title": draft.title, "slug": draft.slug, "content": draft.content},
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

        # AUDIT-05: scan operator-edited weblog content for legal-name
        # leak before publishing. Operator drafts may contain inadvertent
        # name mentions; this is the last guard before omg.lol egress.
        try:
            content = safe_render(draft.content, segment_id=draft.slug)
        except OperatorNameLeak:
            log.warning("omg-weblog: legal-name leak detected — DROPPING publish")
            _record("legal-name-leak")
            return "legal-name-leak"

        resp = self.client.set_entry(self.address, draft.slug, content=content)
        if resp is None:
            log.warning("omg-weblog: set_entry returned None")
            _record("failed")
            return "failed"

        log.info("omg-weblog: published %s", draft.slug)
        _record("published")
        return "published"


# ── Orchestrator entry-point (PUB-P2-C foundation) ───────────────────


def publish_artifact(artifact) -> str:  # type: ignore[no-untyped-def]
    """Dispatch a ``PreprintArtifact`` to the operator's omg.lol weblog.

    Static entry-point consumed by ``agents/publish_orchestrator``'s
    surface registry. Returns one of: ``ok | denied | auth_error |
    error | no_credentials | legal_name_leak``. Never raises.

    Per the 2026-04-25 4-cluster automation-tractability audit, omg.lol
    weblog is operator-owned and FULL_AUTO eligible. The Refusal Brief's
    Locus 2 (the standalone web essay) lives at hapax.omg.lol/refusal,
    so this entry-point is the unblocking work for that publish.

    Composition: the artifact's ``slug`` becomes the omg.lol entry slug,
    ``title`` renders as a markdown ``# H1`` at the top, ``attribution_block``
    + ``abstract`` + ``body_md`` follow. ``safe_render`` passes the
    composed content through the legal-name-leak guard.

    Bypasses the WeblogDraft approval-gate because orchestrator-dispatched
    artifacts have already passed the inbox approval gate (DRAFT →
    APPROVED via ``mark_approved``).
    """
    from shared.omg_lol_client import OmgLolClient

    client = OmgLolClient()
    if not client.enabled:
        log.info("omg-weblog: API key unavailable; deferring artifact %s", artifact.slug)
        _record("no_credentials")
        return "no_credentials"

    content = _compose_artifact_content(artifact)
    if not content:
        log.error("omg-weblog: empty content for artifact %s", artifact.slug)
        _record("error")
        return "error"

    verdict = allowlist_check(
        SURFACE,
        "weblog.entry",
        {"title": artifact.title, "slug": artifact.slug, "content": content},
    )
    if verdict.decision == "deny":
        log.warning("omg-weblog: allowlist denied artifact %s (%s)", artifact.slug, verdict.reason)
        _record("denied")
        return "denied"

    try:
        guarded = safe_render(content, segment_id=artifact.slug)
    except OperatorNameLeak:
        log.warning("omg-weblog: legal-name leak in artifact %s — DROPPING", artifact.slug)
        _record("legal_name_leak")
        return "error"

    try:
        resp = client.set_entry(DEFAULT_ADDRESS, artifact.slug, content=guarded)
    except Exception:  # noqa: BLE001
        log.exception("omg-weblog: set_entry raised for artifact %s", artifact.slug)
        _record("error")
        return "error"

    if resp is None:
        log.warning("omg-weblog: set_entry returned None for artifact %s", artifact.slug)
        _record("error")
        return "error"

    log.info("omg-weblog: published artifact %s", artifact.slug)
    _record("ok")
    return "ok"


def _compose_artifact_content(artifact) -> str:  # type: ignore[no-untyped-def]
    """Render a ``PreprintArtifact`` to omg.lol weblog markdown content.

    Preferred order: ``# {title}`` → ``attribution_block`` →
    ``abstract`` → ``body_md``. Each section separated by a blank line.
    Skips empty sections; never produces leading/trailing whitespace.
    """
    title = (getattr(artifact, "title", "") or "").strip()
    attribution = (getattr(artifact, "attribution_block", "") or "").strip()
    abstract = (getattr(artifact, "abstract", "") or "").strip()
    body_md = (getattr(artifact, "body_md", "") or "").strip()

    parts: list[str] = []
    if title:
        parts.append(f"# {title}")
    if attribution:
        parts.append(attribution)
    if abstract:
        parts.append(abstract)
    if body_md:
        parts.append(body_md)

    return "\n\n".join(parts)


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
