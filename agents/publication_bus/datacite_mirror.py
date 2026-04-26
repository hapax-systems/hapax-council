"""DataCite Commons GraphQL mirror — Phase 1 of pub-bus-datacite-mirror.

Per cc-task ``pub-bus-datacite-graphql-mirror``. Daily-mirror the
DataCite Commons GraphQL view of works attributed to the operator's
ORCID iD into local state. Phase 1 ships:

  - GraphQL POST against ``https://api.datacite.org/graphql``
  - Snapshot persistence at ``~/hapax-state/datacite-mirror/{iso-date}.json``
  - Snapshot-to-snapshot diff (added DOIs, removed DOIs, citation deltas)
  - Prometheus counter on per-snapshot outcome

Phase 2 (operator-credential-gated) wires :mod:`agents.zenodo_publisher`
to mint a version-DOI under the "Hapax Citation Graph" concept-DOI when
the diff is non-empty.

The DataCite GraphQL endpoint is **public, unauthenticated**. The
operator's ORCID iD parameterises the query but no API key is needed
to consume the endpoint. This makes the daemon shippable today; the
operator-action queue item is the ORCID iD configuration only.

Reference: https://api.datacite.org/graphql/playground
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prometheus_client import Counter

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

DATACITE_GRAPHQL_ENDPOINT: str = "https://api.datacite.org/graphql"
"""Public DataCite Commons GraphQL endpoint. No authentication
required for read queries."""

DATACITE_REQUEST_TIMEOUT_S: float = 30.0

DEFAULT_MIRROR_DIR: Path = Path.home() / "hapax-state" / "datacite-mirror"
"""Per-spec: snapshots persist alongside other publication-bus state."""

ORCID_WORKS_QUERY: str = """\
query orcidWorks($orcid: ID!) {
  person(id: $orcid) {
    id
    works(first: 1000) {
      totalCount
      nodes {
        id
        doi
        relatedIdentifiers { relatedIdentifier relationType }
        citations { totalCount }
      }
    }
  }
}
"""
"""GraphQL query for the operator's authored works.

Mirrors the cc-task spec; ``$orcid`` is bound at request-time."""


datacite_mirror_works_total = Counter(
    "hapax_publication_bus_datacite_mirror_works_total",
    "DataCite GraphQL mirror snapshot outcomes per ORCID + result.",
    ["orcid", "outcome"],
)


def fetch_orcid_works(
    orcid_id: str,
    *,
    endpoint: str = DATACITE_GRAPHQL_ENDPOINT,
    timeout_s: float = DATACITE_REQUEST_TIMEOUT_S,
) -> dict[str, Any] | None:
    """POST the orcidWorks query for ``orcid_id``; return parsed body or None.

    The ORCID iD is the bare 16-digit form (e.g. ``0000-0001-2345-6789``);
    the query accepts a full ID URL too, but we keep the param shape
    aligned with what ``shared/orcid.py`` returns. Network and 5xx
    failures return None for retry on the next daily tick.
    """
    if requests is None:
        log.warning("requests library not available; skipping datacite fetch")
        return None
    payload = {
        "query": ORCID_WORKS_QUERY,
        "variables": {"orcid": f"https://orcid.org/{orcid_id}"},
    }
    try:
        response = requests.post(endpoint, json=payload, timeout=timeout_s)
    except requests.RequestException as exc:
        log.warning("datacite GraphQL fetch raised: %s", exc)
        return None

    if response.status_code != 200:
        log.info("datacite GraphQL HTTP %d", response.status_code)
        return None
    try:
        return response.json()
    except ValueError:
        log.warning("datacite GraphQL returned non-JSON body")
        return None


def mirror_works(
    *,
    orcid_id: str,
    mirror_dir: Path = DEFAULT_MIRROR_DIR,
    now: datetime | None = None,
) -> Path | None:
    """Fetch + persist one snapshot; return path written, or None on fetch failure.

    Each tick writes ``{mirror_dir}/{iso-date}.json``. Re-running on
    the same calendar day overwrites the existing snapshot (cadence
    is daily; multiple-runs-per-day are not the design target).
    """
    response = fetch_orcid_works(orcid_id)
    if response is None:
        datacite_mirror_works_total.labels(orcid=orcid_id, outcome="fetch-failed").inc()
        return None

    mirror_dir.mkdir(parents=True, exist_ok=True)
    when = now or datetime.now(UTC)
    target = mirror_dir / f"{when.date().isoformat()}.json"
    target.write_text(json.dumps(response, indent=2))
    datacite_mirror_works_total.labels(orcid=orcid_id, outcome="ok").inc()
    return target


def compute_diff(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    """Compute set diff + citation deltas between two snapshots.

    Returns ``{
        "added_dois": set[str],
        "removed_dois": set[str],
        "citation_count_delta": dict[str, int],
    }``. Missing or malformed payloads degrade to empty diffs (the
    daemon's downstream graph_publisher handles empty-diff as no-op).
    """
    prev_works = _extract_nodes(previous)
    curr_works = _extract_nodes(current)
    prev_dois = {w["doi"] for w in prev_works if w.get("doi")}
    curr_dois = {w["doi"] for w in curr_works if w.get("doi")}

    citation_delta: dict[str, int] = {}
    prev_cite = {w["doi"]: _citation_count(w) for w in prev_works if w.get("doi")}
    curr_cite = {w["doi"]: _citation_count(w) for w in curr_works if w.get("doi")}
    for doi in prev_dois & curr_dois:
        delta = curr_cite.get(doi, 0) - prev_cite.get(doi, 0)
        if delta != 0:
            citation_delta[doi] = delta

    return {
        "added_dois": curr_dois - prev_dois,
        "removed_dois": prev_dois - curr_dois,
        "citation_count_delta": citation_delta,
    }


def _extract_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    person = (payload or {}).get("data", {}).get("person")
    if not isinstance(person, dict):
        return []
    works = person.get("works")
    if not isinstance(works, dict):
        return []
    nodes = works.get("nodes")
    return list(nodes) if isinstance(nodes, list) else []


def _citation_count(work: dict[str, Any]) -> int:
    citations = work.get("citations")
    if not isinstance(citations, dict):
        return 0
    total = citations.get("totalCount")
    return int(total) if isinstance(total, int) else 0


def main() -> int:
    """Entry for ``python -m agents.publication_bus.datacite_mirror``.

    Reads the operator's ORCID iD from the ``HAPAX_OPERATOR_ORCID`` env
    var; emits a refusal-brief event if not configured (operator-action
    queue still pending) and exits 0 (daemon-friendly no-op).
    """
    import os

    logging.basicConfig(level=logging.INFO)
    orcid = os.environ.get("HAPAX_OPERATOR_ORCID")
    if not orcid:
        log.info("HAPAX_OPERATOR_ORCID not set; datacite mirror skipping this tick")
        datacite_mirror_works_total.labels(orcid="unset", outcome="no-orcid-configured").inc()
        return 0
    path = mirror_works(orcid_id=orcid)
    if path is None:
        log.info("datacite mirror snapshot fetch failed; will retry next tick")
        return 0
    log.info("datacite mirror snapshot persisted: %s", path)
    return 0


__all__ = [
    "DATACITE_GRAPHQL_ENDPOINT",
    "DEFAULT_MIRROR_DIR",
    "ORCID_WORKS_QUERY",
    "compute_diff",
    "datacite_mirror_works_total",
    "fetch_orcid_works",
    "main",
    "mirror_works",
]


if __name__ == "__main__":
    raise SystemExit(main())
