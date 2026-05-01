"""Refusal annex series renderer.

Per cc-task ``leverage-mktg-refusal-annex-series``. Each refusal is
its own publishable micro-artifact: citable, referenceable,
constitutive of the academic-spectacle strategy. Module ships the
pure-function renderer + log-grouping discovery + per-annex/index
markdown writes + the orchestrator-side fanout helper
:func:`publish_all_annexes`.

Cross-surface fanout (was previously called "Phase 2"):

- ``zenodo-refusal-deposit`` — V5 RefusalBriefPublisher (#1676 wired);
  mints refusal-deposit DOIs.
- ``omg-weblog`` — operator-owned hapax.weblog.lol (legacy adapter,
  WIRED).
- Bridgy fan-out — BLOCKED on the source-URL witness path (see
  :data:`BRIDGY_FANOUT_BLOCKER` and the module-level discussion at the
  ``Bridgy fanout source-URL witness path`` section). The
  ``refusal_annex_bridgy_daemon`` is a dry-run inventory daemon, not a
  publisher; ``--commit`` fails closed with the witness-path blocker
  rather than POSTing webmentions.

Render pipeline:

  refusal_brief log JSONL → group by surface → annex entries → render markdown

Slug taxonomy (8 seed annexes from the cc-task):

  - declined-alphaxiv               (alphaxiv platform)
  - declined-bandcamp               (Bandcamp music)
  - declined-stripe-kyc             (Stripe Connect)
  - declined-arxiv-shortcut         (arXiv institutional-email shortcut)
  - declined-twitter-linkedin-substack
  - declined-discord-community
  - declined-tutorial-videos
  - declined-patreon

Surface → slug heuristic: surface label contains a fragment of the
slug (case-insensitive substring) — matches existing surface naming
conventions in :mod:`agents.publication_bus.surface_registry`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from prometheus_client import Counter

log = logging.getLogger(__name__)

DEFAULT_ANNEX_OUTPUT_DIR: Path = Path.home() / "hapax-state" / "publications"
"""Per-annex markdown files land here as ``refusal-annex-{slug}.md``;
the index lives at ``refusal-annex-series.md`` in the same dir."""

DEFAULT_LOG_PATH: Path = Path("/dev/shm/hapax-refusals/log.jsonl")
"""Canonical refusal-brief log path; mirrors :data:`agents.refusal_brief.writer.DEFAULT_LOG_PATH`."""

REFUSAL_ANNEX_SLUGS: Final[tuple[str, ...]] = (
    "declined-alphaxiv",
    "declined-bandcamp",
    "declined-stripe-kyc",
    "declined-arxiv-shortcut",
    "declined-twitter-linkedin-substack",
    "declined-discord-community",
    "declined-tutorial-videos",
    "declined-patreon",
)
"""Seed annex slugs from cc-task ``leverage-mktg-refusal-annex-series``.
Each annex aggregates refusal-brief log entries whose ``surface`` matches
the slug fragment (case-insensitive)."""

INDEX_FILENAME: Final[str] = "refusal-annex-series.md"
PER_ANNEX_FILENAME_PREFIX: Final[str] = "refusal-annex-"

NON_ENGAGEMENT_CLAUSE: Final[str] = (
    "Hapax operates as infrastructure-as-argument: no operator outreach, "
    "no community-management, no surfaces requiring continuous engagement. "
    "Refusals are first-class data; this annex is one such datum."
)
"""Short non-engagement clause for annex bodies. Long-form clause lives
in :data:`shared.attribution_block.NON_ENGAGEMENT_CLAUSE_LONG`; we use
the short form here so each annex stays compact."""


refusal_annexes_published_total = Counter(
    "hapax_leverage_refusal_annexes_published_total",
    "Number of refusal annexes rendered to disk per slug + outcome.",
    ["slug", "outcome"],
)


@dataclass(frozen=True)
class RefusalAnnexEntry:
    """One refusal-brief log row, normalised for annex rendering."""

    timestamp: datetime
    axiom: str
    surface: str
    reason: str


def render_annex(
    *,
    slug: str,
    title: str,
    events: list[RefusalAnnexEntry],
) -> str:
    """Render a single refusal annex as markdown.

    Pure function; output is deterministic given fixed inputs. Format:

      # {title}

      _slug: {slug}_

      {non-engagement clause}

      ## Log

      - {timestamp ISO} — _{surface}_ — {reason}
      - ...
    """
    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"_slug: {slug}_")
    lines.append("")
    lines.append(NON_ENGAGEMENT_CLAUSE)
    if events:
        lines.append("")
        lines.append("## Log")
        lines.append("")
        for entry in events:
            ts = entry.timestamp.isoformat()
            lines.append(f"- {ts} — _{entry.surface}_ — {entry.reason}")
    lines.append("")
    return "\n".join(lines)


def render_index(slugs: list[str]) -> str:
    """Render the index page listing every annex in the series."""
    lines: list[str] = []
    lines.append("# Refusal Annex Series")
    lines.append("")
    lines.append(NON_ENGAGEMENT_CLAUSE)
    lines.append("")
    if slugs:
        lines.append("## Annexes")
        lines.append("")
        for slug in slugs:
            filename = f"{PER_ANNEX_FILENAME_PREFIX}{slug}.md"
            lines.append(f"- [{slug}]({filename})")
    lines.append("")
    return "\n".join(lines)


def discover_annex_entries(*, log_path: Path = DEFAULT_LOG_PATH) -> list[dict]:
    """Read the refusal-brief log and group entries into annex buckets.

    Returns a list of ``{"slug": ..., "title": ..., "events": [...]}``
    dicts (one per matched seed slug). Surfaces that don't match any
    seed slug are skipped — Phase 2 may add a "miscellaneous" bucket
    if observed gaps justify it.
    """
    if not log_path.exists():
        return []

    raw_events: list[RefusalAnnexEntry] = []
    for line in log_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            log.debug("skipped malformed refusal-log line")
            continue
        try:
            raw_events.append(
                RefusalAnnexEntry(
                    timestamp=datetime.fromisoformat(data["timestamp"]),
                    axiom=data.get("axiom", ""),
                    surface=data.get("surface", ""),
                    reason=data.get("reason", ""),
                )
            )
        except (KeyError, ValueError):
            log.debug("skipped malformed refusal-log row")
            continue

    grouped: dict[str, list[RefusalAnnexEntry]] = {}
    for entry in raw_events:
        slug = _slug_for_surface(entry.surface)
        if slug is None:
            continue
        grouped.setdefault(slug, []).append(entry)

    return [
        {
            "slug": slug,
            "title": _title_for_slug(slug),
            "events": grouped[slug],
        }
        for slug in grouped
    ]


def _slug_for_surface(surface: str) -> str | None:
    """Map a refusal-log surface label to one of the seed annex slugs.

    Matches case-insensitive substring of the surface against a slug
    fragment. ``publication-bus:bandcamp-upload`` → ``declined-bandcamp``;
    ``leverage:discord-community`` → ``declined-discord-community``.
    Returns ``None`` when no match — the entry is dropped from the
    annex series (it lives in the underlying log either way).
    """
    surface_lower = surface.lower()
    for slug in REFUSAL_ANNEX_SLUGS:
        # Strip the "declined-" prefix and use the remainder as match key
        key = slug.removeprefix("declined-")
        if key in surface_lower:
            return slug
    return None


def _title_for_slug(slug: str) -> str:
    """Human-readable annex title from slug.

    ``declined-bandcamp`` → ``Refusal Annex: Bandcamp``.
    """
    raw = slug.removeprefix("declined-")
    pretty = raw.replace("-", " ").title()
    return f"Refusal Annex: {pretty}"


DEFAULT_PUBLISH_STATE_ROOT: Path = Path.home() / "hapax-state" / "publish"
"""Where ``shared.preprint_artifact.PreprintArtifact`` lives.

The ``publish_orchestrator`` (legacy + V5 wired) globs ``inbox/`` for
approved artefacts, dispatches each via ``SURFACE_REGISTRY``, and moves
to ``published/`` when every targeted surface reaches a terminal state.
"""

BRIDGY_FANOUT_SURFACE: Final[str] = "bridgy-webmention-publish"
"""Generic Bridgy webmention surface slug.

This is intentionally not part of the refusal-annex default fanout set:
the publish orchestrator dispatches targeted surfaces in parallel, while
refusal-annex Bridgy fanout needs a previously published omg.lol weblog
source URL witness before POSTing to Bridgy.
"""

BRIDGY_FANOUT_BLOCKER: Final[str] = (
    "refusal-annex Bridgy fanout is blocked until the committed path can "
    "prove the omg-weblog source URL exists before issuing the webmention POST"
)

DEFAULT_FANOUT_SURFACES: tuple[str, ...] = (
    "zenodo-refusal-deposit",
    "omg-weblog",
)
"""Where each refusal annex fans out via the orchestrator.

- ``zenodo-refusal-deposit`` — V5 RefusalBriefPublisher (#1676 wired); mints DOI
- ``omg-weblog`` — operator-owned hapax.weblog.lol (legacy adapter, WIRED)

The generic ``bridgy-webmention-publish`` surface remains wired for normal
weblog artifacts, but refusal-annex artifacts do not target it by default
until source-URL sequencing is committed.
"""

DORMANT_FANOUT_SURFACES: tuple[str, ...] = (BRIDGY_FANOUT_SURFACE,)
"""Refusal-annex surfaces that are inventoried but deliberately not live."""


def enqueue_annex_for_fanout(
    *,
    slug: str,
    title: str,
    body: str,
    surfaces: list[str] | None = None,
    state_root: Path = DEFAULT_PUBLISH_STATE_ROOT,
) -> Path:
    """Persist a ``PreprintArtifact`` for orchestrator dispatch.

    The renderer-side already wrote the canonical ``.md`` artefact to
    ``~/hapax-state/publications/`` via the V5 RefusalAnnexPublisher.
    This function drops the orchestrator-side companion: an approved
    PreprintArtifact JSON in ``~/hapax-state/publish/inbox/`` whose
    ``surfaces_targeted`` instructs the orchestrator to fan out to the
    committed refusal-annex surfaces. Bridgy POSSE is excluded until a
    source-URL witness/sequencing path is committed.

    Returns the inbox path for caller observability.
    """
    from shared.preprint_artifact import PreprintArtifact

    requested_surfaces = _validate_committed_fanout_surfaces(
        list(surfaces or DEFAULT_FANOUT_SURFACES)
    )
    artefact_slug = f"refusal-annex-{slug}"
    artefact = PreprintArtifact(
        slug=artefact_slug,
        title=title,
        abstract=body[:4096],
        body_md=body,
        surfaces_targeted=requested_surfaces,
    )
    artefact.mark_approved(by_referent="Oudepode")
    inbox_path = artefact.inbox_path(state_root=state_root)
    inbox_path.parent.mkdir(parents=True, exist_ok=True)
    inbox_path.write_text(artefact.model_dump_json(), encoding="utf-8")
    return inbox_path


def publish_all_annexes(
    *,
    log_path: Path = DEFAULT_LOG_PATH,
    output_dir: Path = DEFAULT_ANNEX_OUTPUT_DIR,
    enqueue_for_fanout: bool = False,
    fanout_state_root: Path | None = None,
    fanout_surfaces: list[str] | None = None,
) -> dict[str, Path]:
    """Render every annex with at least one log entry + the series index.

    Phase 2b dispatches each annex through
    :class:`agents.marketing.refusal_annex_publisher.RefusalAnnexPublisher`
    so the V5 publication-bus invariants (allowlist gate, legal-name-leak
    guard, canonical Counter) apply to every write. The legacy
    ``hapax_leverage_refusal_annexes_published_total`` counter
    continues to record per-slug outcomes for backward compatibility.

    Phase 3 (``enqueue_for_fanout=True``): per published annex, drop a
    ``PreprintArtifact`` in the orchestrator inbox so each annex fans out
    to the committed Zenodo + omg.lol weblog surfaces without operator
    action. Bridgy remains a documented dry-run/dormant path until its
    source-URL witness is committed.

    Returns ``{slug: output_path}`` for the per-annex files. The index
    file is always written (even when empty) so downstream tooling
    can rely on its existence.
    """
    # Lazy import to avoid a hard import-cycle: the publisher module
    # imports renderer constants (REFUSAL_ANNEX_SLUGS,
    # PER_ANNEX_FILENAME_PREFIX, DEFAULT_ANNEX_OUTPUT_DIR) at module load.
    from agents.marketing.refusal_annex_publisher import RefusalAnnexPublisher
    from agents.publication_bus.publisher_kit import PublisherPayload

    output_dir.mkdir(parents=True, exist_ok=True)
    annexes = discover_annex_entries(log_path=log_path)
    publisher = RefusalAnnexPublisher(output_dir=output_dir)
    written: dict[str, Path] = {}

    for annex in annexes:
        slug = annex["slug"]
        body = render_annex(slug=slug, title=annex["title"], events=annex["events"])
        result = publisher.publish(PublisherPayload(target=slug, text=body))
        if result.ok:
            refusal_annexes_published_total.labels(slug=slug, outcome="ok").inc()
            written[slug] = output_dir / f"{PER_ANNEX_FILENAME_PREFIX}{slug}.md"
            if enqueue_for_fanout:
                try:
                    enqueue_annex_for_fanout(
                        slug=slug,
                        title=annex["title"],
                        body=body,
                        surfaces=fanout_surfaces,
                        state_root=fanout_state_root or DEFAULT_PUBLISH_STATE_ROOT,
                    )
                    refusal_annexes_published_total.labels(
                        slug=slug, outcome="enqueued-fanout"
                    ).inc()
                except Exception:
                    log.warning("annex fanout-enqueue failed for %s", slug, exc_info=True)
                    refusal_annexes_published_total.labels(
                        slug=slug, outcome="fanout-enqueue-failed"
                    ).inc()
        elif result.refused:
            refusal_annexes_published_total.labels(slug=slug, outcome="refused").inc()
            log.info("annex publish refused for %s: %s", slug, result.detail)
        else:
            refusal_annexes_published_total.labels(slug=slug, outcome="write-failed").inc()
            log.warning("annex publish errored for %s: %s", slug, result.detail)

    index_path = output_dir / INDEX_FILENAME
    index_path.write_text(render_index([annex["slug"] for annex in annexes]))

    return written


def main() -> int:
    """Entry for ``python -m agents.marketing.refusal_annex_renderer``."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-fanout",
        action="store_true",
        help="Render local files only; skip enqueuing for orchestrator dispatch",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    written = publish_all_annexes(enqueue_for_fanout=not args.no_fanout)
    log.info("rendered %d refusal annexes", len(written))
    return 0


def _validate_committed_fanout_surfaces(surfaces: list[str]) -> list[str]:
    """Reject refusal-annex targets that are inventoried but not live."""
    dormant = sorted(set(surfaces).intersection(DORMANT_FANOUT_SURFACES))
    if dormant:
        raise ValueError(f"{BRIDGY_FANOUT_BLOCKER}: {', '.join(dormant)}")
    return surfaces


__all__ = [
    "BRIDGY_FANOUT_BLOCKER",
    "BRIDGY_FANOUT_SURFACE",
    "DEFAULT_ANNEX_OUTPUT_DIR",
    "DEFAULT_FANOUT_SURFACES",
    "DEFAULT_LOG_PATH",
    "DEFAULT_PUBLISH_STATE_ROOT",
    "DORMANT_FANOUT_SURFACES",
    "INDEX_FILENAME",
    "NON_ENGAGEMENT_CLAUSE",
    "PER_ANNEX_FILENAME_PREFIX",
    "REFUSAL_ANNEX_SLUGS",
    "RefusalAnnexEntry",
    "discover_annex_entries",
    "enqueue_annex_for_fanout",
    "main",
    "publish_all_annexes",
    "refusal_annexes_published_total",
    "render_annex",
    "render_index",
    "_validate_committed_fanout_surfaces",
]


if __name__ == "__main__":
    raise SystemExit(main())
