"""Refusal Brief footer auto-injector for publication-bus deposit descriptions.

Per V5 weave drop 2 §4 anti-spam guardrail #5 + cc-task
``pub-bus-refusal-footer-injector``. Every deposit description from
the publication-bus carries a Refusal Brief footer auto-appended;
the footer cross-links to ``docs/refusal-briefs/`` index and the
constitutional refusal stance.

Constitutional fit:
- Refusal-as-data — every deposit footer points to refusal-briefs
  registry; refusals are co-equal with the published work
- Full-automation-or-nothing — footer generation is daemon-side; the
  operator never edits the footer text
- Anti-anthropomorphization — footer is structured (links +
  classification badges), not narrative voice
- Co-publishing + auto-only + unsettled-contribution — footer encodes
  the operator's unsettled-contribution stance per
  ``feedback_co_publishing_auto_only_unsettled_contribution``

This module is the pure-function builder. The hook into
``deposit_builder.build_description()`` ships with Phase 2 of
``pub-bus-zenodo-related-identifier-graph`` (when the deposit_builder
itself ships).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from shared.attribution_block import NON_ENGAGEMENT_CLAUSE_LONG

REFUSAL_BRIEFS_INDEX_DEFAULT: Path = Path("docs/refusal-briefs/index.json")
"""Default path to the refusal-briefs index file. Operator + Hapax
curated; pure-function consumers can pass an alternate path."""

MAX_ACTIVE_REFUSALS_IN_FOOTER: int = 10
"""Limit on the number of active refusals enumerated in any single
footer. The full index is reachable via the index link; the in-footer
list is a recency cue, not the canonical record."""


@dataclass(frozen=True)
class RefusalEntry:
    """One entry from the refusal-briefs index.

    ``slug`` is the URL-safe identifier (``bandcamp-no-upload-api``);
    ``title`` is the human-readable summary
    (``Bandcamp upload — refused (no API)``); ``doi`` is the optional
    Zenodo-minted DOI when the refusal has been deposited as its own
    artifact (per ``xprom-refusal-as-related-identifier``); ``date``
    is the refusal-event ISO-8601 date.
    """

    slug: str
    title: str
    date: str
    doi: str | None = None


def load_refusals(
    index_path: Path | None = None,
) -> list[RefusalEntry]:
    """Load the refusal-briefs index from disk; gracefully empty when missing.

    The index file's expected shape is a JSON array of objects with
    ``slug`` / ``title`` / ``date`` / optional ``doi`` keys::

        [
          {"slug": "bandcamp-no-upload-api", "title": "...", "date": "2026-04-25"},
          {"slug": "discogs-tos-forbids", "title": "...", "date": "2026-04-25", "doi": "10.5281/..."}
        ]

    When the file is absent (e.g., pre-bootstrap; the operator hasn't
    yet authored the index), returns an empty list. The footer still
    renders — without an enumerated refusal list, the link to the
    index suffices.
    """
    path = index_path or REFUSAL_BRIEFS_INDEX_DEFAULT
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    entries: list[RefusalEntry] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        slug = raw.get("slug")
        title = raw.get("title")
        date = raw.get("date")
        if not all(isinstance(v, str) for v in (slug, title, date)):
            continue
        doi = raw.get("doi") if isinstance(raw.get("doi"), str) else None
        entries.append(RefusalEntry(slug=slug, title=title, date=date, doi=doi))
    return entries


def render_footer(
    refusals: list[RefusalEntry] | None = None,
    *,
    today: datetime | None = None,
) -> str:
    """Render the Refusal Brief footer Markdown for a deposit description.

    Pure function. Consumes a list of :class:`RefusalEntry` (loaded
    via :func:`load_refusals`); returns the Markdown footer string.

    The footer carries:

    - Section heading (``## Constitutional disclosure``)
    - Reference to the full-automation-or-no-engagement directive
    - Reference to the unsettled-contribution co-publishing stance
    - The LONG non-engagement clause from
      :data:`shared.attribution_block.NON_ENGAGEMENT_CLAUSE_LONG`
    - Active refusals subsection enumerating up to
      :data:`MAX_ACTIVE_REFUSALS_IN_FOOTER` entries
    - Link to the full refusal-briefs index

    ``today`` defaults to ``datetime.now(timezone.utc)``; tests may
    pass a fixed value for deterministic snapshots.
    """
    today_dt = today or datetime.now(UTC)
    iso_date = today_dt.date().isoformat()

    entries = refusals or []
    # Newest first for the in-footer list (operator + Hapax may
    # commit the index in any order; we sort here for deterministic
    # output).
    entries_sorted = sorted(entries, key=lambda e: e.date, reverse=True)
    capped = entries_sorted[:MAX_ACTIVE_REFUSALS_IN_FOOTER]

    parts: list[str] = []
    parts.append("---")
    parts.append("")
    parts.append("## Constitutional disclosure")
    parts.append("")
    parts.append(
        "This artefact is published under Hapax's full-automation-or-no-engagement "
        "constitutional stance "
        "(`docs/feedback/full-automation-or-no-engagement.md`)."
    )
    parts.append("")
    parts.append(
        "Authorship is co-published between Hapax (Claude-based agent) and the "
        "operator. Authorship indeterminacy is constitutive per "
        "`docs/feedback/co-publishing-auto-only-unsettled-contribution.md`."
    )
    parts.append("")
    parts.append(NON_ENGAGEMENT_CLAUSE_LONG)
    parts.append("")
    parts.append(f"### Active refusals as of {iso_date}")
    parts.append("")

    if capped:
        for entry in capped:
            doi_suffix = f" ({entry.doi})" if entry.doi else ""
            parts.append(f"- {entry.title}{doi_suffix}")
    else:
        parts.append("- (no active refusals registered yet; see index link below)")

    parts.append("")
    parts.append(
        "Full refusal index: "
        "[docs/refusal-briefs/](https://github.com/ryanklee/hapax-council/tree/main/docs/refusal-briefs/)"
    )
    parts.append("")
    return "\n".join(parts)


def inject_footer(
    description: str,
    *,
    refusals_path: Path | None = None,
    today: datetime | None = None,
) -> str:
    """Append the Refusal Brief footer to ``description``.

    Idempotent in the structural sense: the footer is always
    appended; if the description already carries a footer (e.g., on
    re-deposit), the second copy is also appended. Callers are
    responsible for not re-injecting on already-injected text. The
    pure-function shape favors composability over hidden state.

    ``description`` is the deposit's body Markdown (without footer);
    the return value is ``description`` + ``"\\n"`` + the rendered
    footer. A trailing newline is included so the boundary is visible
    in `diff` output.
    """
    refusals = load_refusals(refusals_path)
    footer = render_footer(refusals, today=today)
    if not description.endswith("\n"):
        description = description + "\n"
    return description + "\n" + footer


__all__ = [
    "MAX_ACTIVE_REFUSALS_IN_FOOTER",
    "REFUSAL_BRIEFS_INDEX_DEFAULT",
    "RefusalEntry",
    "inject_footer",
    "load_refusals",
    "render_footer",
]
