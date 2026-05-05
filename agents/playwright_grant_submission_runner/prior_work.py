"""Auto-generate the prior-work section from the DataCite mirror snapshot.

Closes the cc-task ``immediate-q2-2026-grant-submission-batch``
acceptance item: *Each submission minted as Zenodo concept-DOI ...
prior-work section auto-generated from agents/publication_bus/datacite_mirror.py
snapshot.*

The DataCite mirror daemon writes one snapshot per day to
``~/hapax-state/datacite-mirror/{iso-date}.json``. This module reads
the latest snapshot and renders a markdown prior-work list — DOI +
title + publication year — that recipes interpolate into the grant
application's prior-work section.

If no snapshot exists yet (the mirror daemon hasn't run or
``HAPAX_OPERATOR_ORCID`` isn't configured), the renderer returns an
operator-actionable placeholder rather than an empty string. Grant
reviewers will see *"Prior work — none registered in DataCite yet"*
and the operator can swap in a manually-curated list.

Pure — no network. The mirror daemon owns the GraphQL fetch; this
module only reads the persisted JSON.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from agents.publication_bus.datacite_mirror import DEFAULT_MIRROR_DIR

log = logging.getLogger(__name__)

__all__ = [
    "PRIOR_WORK_PLACEHOLDER",
    "PriorWorkEntry",
    "extract_prior_work_entries",
    "load_latest_snapshot",
    "render_prior_work_section",
]

PRIOR_WORK_PLACEHOLDER: str = (
    "_Prior work — none registered in DataCite yet. The operator's "
    "publication-bus daemons mint Zenodo concept-DOIs that propagate "
    "to DataCite via the Auto-Update path; the prior-work section "
    "will populate automatically once the first deposit lands._"
)
"""Operator-actionable placeholder when no snapshot exists or when
the snapshot is empty. Grant reviewers see a coherent statement
rather than an empty section."""


@dataclass(frozen=True)
class PriorWorkEntry:
    """One DataCite-registered work attributed to the operator's ORCID.

    Fields mirror the DataCite GraphQL ``Work`` node subset that
    grant applications surface. Citation counts are included so the
    rendered list can be sorted citation-first when the operator
    wants to lead with most-cited.
    """

    doi: str
    title: str
    publication_year: int | None = None
    citation_count: int = 0
    publisher: str = ""

    def render_line(self) -> str:
        """Render one bullet for the prior-work markdown list."""

        year = f" ({self.publication_year})" if self.publication_year else ""
        cite_suffix = f" — cited {self.citation_count}×" if self.citation_count > 0 else ""
        publisher = f" — {self.publisher}" if self.publisher else ""
        return f"- **{self.title}**{year}. DOI: `{self.doi}`{publisher}{cite_suffix}"


def load_latest_snapshot(mirror_dir: Path = DEFAULT_MIRROR_DIR) -> dict | None:
    """Load the most recent ``{iso-date}.json`` snapshot, or None.

    Returns ``None`` when the mirror dir is missing, empty, or
    contains no parseable snapshot. The renderer maps None to the
    placeholder so a missing snapshot does not crash the runner.
    """

    if not mirror_dir.is_dir():
        log.debug("datacite mirror dir %s missing; no prior work", mirror_dir)
        return None
    snapshots = sorted(mirror_dir.glob("*.json"))
    if not snapshots:
        return None
    latest = snapshots[-1]
    try:
        return json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("datacite mirror snapshot %s unreadable", latest, exc_info=True)
        return None


def extract_prior_work_entries(snapshot: dict) -> list[PriorWorkEntry]:
    """Project a DataCite mirror snapshot into PriorWorkEntry list.

    Pure projection over the GraphQL response shape — same nodes
    accessor :func:`agents.publication_bus.datacite_mirror._extract_nodes`
    uses internally. Skips work nodes without a DOI (DataCite
    sometimes returns placeholder records without identifiers).
    """

    person = (snapshot or {}).get("data", {}).get("person")
    if not isinstance(person, dict):
        return []
    works = person.get("works")
    if not isinstance(works, dict):
        return []
    nodes = works.get("nodes")
    if not isinstance(nodes, list):
        return []

    out: list[PriorWorkEntry] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        doi = node.get("doi")
        if not doi:
            continue
        out.append(
            PriorWorkEntry(
                doi=str(doi),
                title=str(_extract_title(node)),
                publication_year=_extract_year(node),
                citation_count=_extract_citation_count(node),
                publisher=str(node.get("publisher") or ""),
            )
        )
    return out


def render_prior_work_section(
    *,
    mirror_dir: Path = DEFAULT_MIRROR_DIR,
    max_entries: int = 25,
    sort_by_citations: bool = True,
) -> str:
    """Render the markdown prior-work section ready for grant interpolation.

    Args:
        mirror_dir: Override the snapshot directory (default:
            ``~/hapax-state/datacite-mirror/``).
        max_entries: Cap the rendered list. Grants rarely tolerate
            more than 20-30 prior-work entries; default 25 leaves
            buffer for the most-impactful ones.
        sort_by_citations: When True, sort citation-count DESC;
            ties broken by publication-year DESC. When False, preserve
            the snapshot's native order (DataCite's default is
            chronological).
    """

    snapshot = load_latest_snapshot(mirror_dir)
    if snapshot is None:
        return PRIOR_WORK_PLACEHOLDER
    entries = extract_prior_work_entries(snapshot)
    if not entries:
        return PRIOR_WORK_PLACEHOLDER

    if sort_by_citations:
        entries.sort(
            key=lambda e: (e.citation_count, e.publication_year or 0),
            reverse=True,
        )
    capped = entries[:max_entries]
    return "\n".join(e.render_line() for e in capped)


# ── Internals ─────────────────────────────────────────────────────────


def _extract_title(node: dict) -> str:
    titles = node.get("titles")
    if isinstance(titles, list) and titles:
        first = titles[0]
        if isinstance(first, dict):
            return str(first.get("title") or "")
    raw_title = node.get("title")
    return str(raw_title) if raw_title else ""


def _extract_year(node: dict) -> int | None:
    raw = node.get("publicationYear")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return None


def _extract_citation_count(node: dict) -> int:
    citations = node.get("citations")
    if not isinstance(citations, dict):
        return 0
    total = citations.get("totalCount")
    return int(total) if isinstance(total, int) else 0
