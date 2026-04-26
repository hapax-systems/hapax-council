"""DataCite Commons GraphQL citation-graph snapshot — Phase 1.

Per cc-task ``leverage-attrib-datacite-graphql-snapshot``. Periodic
GraphQL snapshot of the citation network around Hapax's DOI / SWHID /
ORCID nodes. DataCite indexes Zenodo + arXiv + Crossref + SWH cross-
citations; the GraphQL surface lets the daemon pull a structured
neighbourhood per node.

Distinct from :mod:`agents.publication_bus.datacite_mirror` which
mirrors the operator's authored works (ORCID-scoped). This module
queries the citation graph AROUND specific DOI/SWHID nodes and
persists per-node snapshots for downstream graph analysis.

Phase 1 ships:

  - GraphQL POST against the public DataCite endpoint
  - Snapshot persistence at
    ``~/hapax-state/attribution/datacite-snapshot-{iso-date}.json``
  - Citation-count extraction helper

Phase 2 will wire downstream consumers (awareness ``attribution``
block, ``xprom-`` deposit graph cross-link).
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

DEFAULT_SNAPSHOT_DIR: Path = Path.home() / "hapax-state" / "attribution"
"""Per-spec: snapshots persist alongside swhids.yaml + bibtex.bib in
the attribution state directory."""

DOI_CITATION_QUERY: str = """\
query doiCitationGraph($doi: ID!) {
  doi(id: $doi) {
    id
    doi
    citationCount
    relatedIdentifiers { relatedIdentifier relationType }
    citations(first: 100) {
      totalCount
      nodes { id doi }
    }
  }
}
"""
"""GraphQL query for the citation neighbourhood around one DOI.

Pulls the citationCount, all relatedIdentifiers (the deposit's outgoing
graph edges), and the first 100 citing-DOIs (the deposit's incoming
graph edges). 100 is well above expected per-deposit citation counts
for current Hapax artefacts; pagination is a Phase 2 concern."""


datacite_citations_total = Counter(
    "hapax_leverage_datacite_citations_total",
    "DataCite GraphQL citation-graph snapshot outcomes per node + result.",
    ["node_type", "outcome"],
)


def query_doi_citation_graph(
    doi: str,
    *,
    endpoint: str = DATACITE_GRAPHQL_ENDPOINT,
    timeout_s: float = DATACITE_REQUEST_TIMEOUT_S,
) -> dict[str, Any] | None:
    """POST the doiCitationGraph query for ``doi``; return parsed body or None.

    Network and 4xx/5xx failures return None for retry on the next
    snapshot tick. The caller aggregates per-DOI results into a
    daily snapshot file.
    """
    if requests is None:
        log.warning("requests library not available; skipping datacite query")
        return None
    payload = {"query": DOI_CITATION_QUERY, "variables": {"doi": doi}}
    try:
        response = requests.post(endpoint, json=payload, timeout=timeout_s)
    except requests.RequestException as exc:
        log.warning("datacite GraphQL fetch raised: %s", exc)
        datacite_citations_total.labels(node_type="doi", outcome="transport-error").inc()
        return None
    if response.status_code != 200:
        datacite_citations_total.labels(
            node_type="doi", outcome=f"http-{response.status_code}"
        ).inc()
        return None
    try:
        body = response.json()
    except ValueError:
        datacite_citations_total.labels(node_type="doi", outcome="non-json").inc()
        return None
    datacite_citations_total.labels(node_type="doi", outcome="ok").inc()
    return body


def extract_citation_count(payload: dict[str, Any]) -> int:
    """Pull ``citationCount`` out of a DataCite DOI response.

    Returns 0 on missing/malformed payload. Constitutional
    boundary-permissiveness: the snapshot must remain operational
    when DataCite returns partial data (e.g., during reindexing).
    """
    if not isinstance(payload, dict):
        return 0
    data = payload.get("data")
    if not isinstance(data, dict):
        return 0
    doi_node = data.get("doi")
    if not isinstance(doi_node, dict):
        return 0
    count = doi_node.get("citationCount")
    return int(count) if isinstance(count, int) else 0


def snapshot_attribution_graph(
    *,
    dois: list[str],
    swhids: list[str],
    orcids: list[str],
    snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR,
    now: datetime | None = None,
) -> Path:
    """Query each input node and persist a per-day citation snapshot.

    The snapshot file shape is:

        {
          "snapshot_at": "2026-04-26T05:30:00+00:00",
          "dois": {"10.5281/zenodo.111": {<graphql response>}},
          "swhids": {<swhid>: <response>},  # Phase 2
          "orcids": {<orcid>: <response>}   # Phase 2
        }

    Phase 1 only queries the DOI tier; SWHID and ORCID query shapes
    differ enough that they ship in Phase 2 alongside the awareness
    consumer wiring.

    Failed queries are silently omitted from the snapshot (they're
    counter-recorded as ``transport-error`` / ``http-N`` so observability
    surfaces the gap).
    """
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    when = now or datetime.now(UTC)
    target = snapshot_dir / f"datacite-snapshot-{when.date().isoformat()}.json"

    doi_results: dict[str, Any] = {}
    for doi in dois:
        result = query_doi_citation_graph(doi)
        if result is not None:
            doi_results[doi] = result

    payload: dict[str, Any] = {
        "snapshot_at": when.isoformat(),
        "dois": doi_results,
        "swhids": {},
        "orcids": {},
    }
    target.write_text(json.dumps(payload, indent=2, default=str))
    return target


def main() -> int:
    """Daemon-friendly entry for ``python -m agents.attribution.datacite_graphql_snapshot``.

    Phase 1 reads no input list; Phase 2 will source DOI/SWHID/ORCID
    sets from ``hapax-state/publications/recent-concept-dois.txt`` +
    ``hapax-state/attribution/swhids.yaml`` + ``HAPAX_OPERATOR_ORCID``.
    For now the daemon entry no-ops cleanly so the systemd unit can
    be installed in advance of Phase 2.
    """
    logging.basicConfig(level=logging.INFO)
    log.info("datacite snapshot Phase 1 entry: source-list wiring deferred to Phase 2")
    return 0


__all__ = [
    "DATACITE_GRAPHQL_ENDPOINT",
    "DEFAULT_SNAPSHOT_DIR",
    "DOI_CITATION_QUERY",
    "datacite_citations_total",
    "extract_citation_count",
    "main",
    "query_doi_citation_graph",
    "snapshot_attribution_graph",
]


if __name__ == "__main__":
    raise SystemExit(main())
