"""DataCite mirror snapshot reader for the /deposits page.

The DataCite mirror daemon (``agents/publication_bus/datacite_mirror.py``)
writes one JSON snapshot per day to
``~/hapax-state/datacite-mirror/<iso-date>.json`` containing the
operator's authored works as resolved via the public DataCite
GraphQL API. This module reads the freshest snapshot and exposes
the works list to the renderer's ``/deposits`` page.

Schema (per a real snapshot at 2026-05-01.json):

  {
    "data": {
      "person": {
        "id": "https://orcid.org/<id>",
        "works": {
          "totalCount": <N>,
          "nodes": [
            {
              "id": "https://doi.org/<doi>",
              "doi": "<doi>",
              "relatedIdentifiers": [
                {"relatedIdentifier": "<url>", "relationType": "<type>"}
              ],
              "citations": {"totalCount": <M>}
            }
          ]
        }
      }
    }
  }

Safe-fallback: when the snapshot dir is missing / empty / unreadable,
``read_latest_snapshot()`` returns an empty :class:`DataCiteSnapshot`
so the renderer emits a Phase-1c placeholder rather than failing the
build. Operator-overridable via ``HAPAX_DATACITE_MIRROR_DIR``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SNAPSHOT_DIR = Path.home() / "hapax-state" / "datacite-mirror"
"""Default snapshot dir written by hapax-datacite-mirror.timer."""

SNAPSHOT_DIR_ENV = "HAPAX_DATACITE_MIRROR_DIR"
"""Env var that overrides the snapshot dir at build time."""


@dataclass(frozen=True)
class RelatedIdentifier:
    """One ``relatedIdentifiers`` entry on a work."""

    related_identifier: str
    relation_type: str


@dataclass(frozen=True)
class Work:
    """One DataCite-tracked work (Zenodo deposit, OSF preprint, etc.)."""

    doi: str
    """Bare DOI, e.g. ``10.17605/osf.io/5c2kr``."""
    landing_page_url: str
    """``https://doi.org/<doi>`` resolution URL."""
    citation_count: int
    """Number of inbound citations DataCite knows about."""
    related_identifiers: list[RelatedIdentifier] = field(default_factory=list)


@dataclass(frozen=True)
class DataCiteSnapshot:
    """The freshest DataCite snapshot resolved at renderer build time."""

    snapshot_date: str | None
    """ISO date of the source file (e.g. ``2026-05-01``); ``None``
    when no snapshot was found."""
    orcid_url: str | None
    """Operator's ORCID iD URL; ``None`` when no snapshot."""
    works: list[Work] = field(default_factory=list)
    """Works in the snapshot. Empty when no snapshot was found."""

    @property
    def available(self) -> bool:
        """True when a snapshot was successfully read."""
        return self.snapshot_date is not None


def _snapshot_dir() -> Path:
    """Resolve the active snapshot dir from env or default."""
    env = os.environ.get(SNAPSHOT_DIR_ENV, "").strip()
    return Path(env) if env else DEFAULT_SNAPSHOT_DIR


def _latest_snapshot_path(snapshot_dir: Path) -> Path | None:
    """Pick the freshest ``YYYY-MM-DD.json`` file by sorted filename.

    ISO-date filenames sort lexicographically the same as
    chronologically, so a plain ``sorted()`` reverse pick gives
    today's snapshot. Returns ``None`` when the dir is missing or
    contains no matching files.
    """
    if not snapshot_dir.is_dir():
        return None
    candidates = sorted(snapshot_dir.glob("*.json"))
    return candidates[-1] if candidates else None


def read_latest_snapshot() -> DataCiteSnapshot:
    """Read the freshest DataCite snapshot from the snapshot dir.

    Safe-fallback: returns an empty :class:`DataCiteSnapshot` when
    the dir is missing / empty / contains malformed JSON. Logs are
    silent (callers degrade gracefully via ``snapshot.available``).
    """
    snapshot_dir = _snapshot_dir()
    path = _latest_snapshot_path(snapshot_dir)
    if path is None:
        return DataCiteSnapshot(snapshot_date=None, orcid_url=None)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DataCiteSnapshot(snapshot_date=None, orcid_url=None)

    person = (raw.get("data") or {}).get("person") or {}
    works_block = person.get("works") or {}
    nodes = works_block.get("nodes") or []

    works: list[Work] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        doi = (node.get("doi") or "").strip()
        if not doi:
            continue
        landing = node.get("id") or f"https://doi.org/{doi}"
        citations_block = node.get("citations") or {}
        citation_count = int(citations_block.get("totalCount") or 0)
        related = [
            RelatedIdentifier(
                related_identifier=str(r.get("relatedIdentifier") or ""),
                relation_type=str(r.get("relationType") or ""),
            )
            for r in (node.get("relatedIdentifiers") or [])
            if isinstance(r, dict)
        ]
        works.append(
            Work(
                doi=doi,
                landing_page_url=str(landing),
                citation_count=citation_count,
                related_identifiers=related,
            )
        )

    return DataCiteSnapshot(
        snapshot_date=path.stem,  # "YYYY-MM-DD"
        orcid_url=person.get("id"),
        works=works,
    )


__all__ = [
    "DEFAULT_SNAPSHOT_DIR",
    "DataCiteSnapshot",
    "RelatedIdentifier",
    "SNAPSHOT_DIR_ENV",
    "Work",
    "read_latest_snapshot",
]
