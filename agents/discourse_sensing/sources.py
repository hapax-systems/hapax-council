"""Source list loading and request URL construction for the discourse sensor.

The source list is vault-side (this repository is public) and read from a
configurable path; every entry carries a terms note and the date it was
checked at source.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import yaml

BLUESKY_APPVIEW = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"
HN_SEARCH_BY_DATE = "https://hn.algolia.com/api/v1/search_by_date"

VALID_KINDS = frozenset({"bluesky_author_feed", "rss_feed", "hn_algolia_query"})

_REQUIRED_FIELDS = (
    "id",
    "venue",
    "kind",
    "cadence_minutes",
    "checked_at_source",
    "terms_note",
)
_ADDRESS_FIELDS = {
    "bluesky_author_feed": "actor",
    "rss_feed": "url",
    "hn_algolia_query": "query",
}


@dataclass(frozen=True)
class SourceSpec:
    """One declared public source, as carried in the vault-side SOURCES.yaml."""

    id: str
    venue: str
    kind: str
    cadence_minutes: int
    checked_at_source: str
    terms_note: str
    actor: str | None = None
    url: str | None = None
    query: str | None = None

    def address(self) -> str:
        """The public address that identifies this source in intake records."""
        if self.kind == "bluesky_author_feed":
            return self.actor or ""
        if self.kind == "rss_feed":
            return self.url or ""
        return self.query or ""

    def request_url(self, since_epoch: int, limit: int) -> str:
        """The read-only GET URL for one poll of this source."""
        if self.kind == "bluesky_author_feed":
            capped = min(limit, 100)
            return f"{BLUESKY_APPVIEW}?actor={self.actor}&filter=posts_no_reply&limit={capped}"
        if self.kind == "rss_feed":
            return self.url or ""
        capped = min(limit, 50)
        return (
            f"{HN_SEARCH_BY_DATE}?query={quote(self.query or '')}"
            f"&tags=story&hitsPerPage={capped}"
            f"&numericFilters=created_at_i>{int(since_epoch)}"
        )


def load_sources(path: str | Path) -> list[SourceSpec]:
    """Load and validate the declared source list, with repair guidance."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(
            f"source list not found at {path}; pass --sources or set "
            "DISCOURSE_SENSING_SOURCES to the vault-side SOURCES.yaml"
        ) from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"{path}: invalid YAML ({exc}); repair the source list") from exc
    entries = raw.get("sources") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        raise ValueError(f"{path}: expected a top-level 'sources' list; repair the source list")
    specs: list[SourceSpec] = []
    seen_ids: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: source #{index} is not a mapping; repair the source list")
        missing = [field for field in _REQUIRED_FIELDS if not entry.get(field)]
        if missing:
            raise ValueError(
                f"{path}: source #{index} ({entry.get('id', '?')}) lacks {missing}; add the "
                "missing fields to the vault-side source list — every source needs a terms "
                "note and a checked-at-source date"
            )
        kind = entry["kind"]
        if kind not in VALID_KINDS:
            raise ValueError(
                f"{path}: source {entry['id']} has kind {kind!r}; expected one of "
                f"{sorted(VALID_KINDS)}; correct the kind or move the source to a later slice"
            )
        address_field = _ADDRESS_FIELDS[kind]
        if not entry.get(address_field):
            raise ValueError(
                f"{path}: source {entry['id']} needs a non-empty {address_field} for kind "
                f"{kind}; repair the source list"
            )
        if entry["id"] in seen_ids:
            raise ValueError(f"{path}: duplicate source id {entry['id']!r}; repair the source list")
        seen_ids.add(entry["id"])
        cadence = entry["cadence_minutes"]
        if not isinstance(cadence, int) or isinstance(cadence, bool) or cadence <= 0:
            raise ValueError(
                f"{path}: source {entry['id']} needs a positive integer cadence_minutes; set "
                "it to the poll interval in minutes in the vault-side source list"
            )
        specs.append(
            SourceSpec(
                id=str(entry["id"]),
                venue=str(entry["venue"]),
                kind=kind,
                cadence_minutes=cadence,
                checked_at_source=str(entry["checked_at_source"]),
                terms_note=str(entry["terms_note"]),
                actor=str(entry["actor"]) if entry.get("actor") else None,
                url=str(entry["url"]) if entry.get("url") else None,
                query=str(entry["query"]) if entry.get("query") else None,
            )
        )
    return specs
