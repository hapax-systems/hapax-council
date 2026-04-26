"""ORCID auto-update verifier — Phase 1.

Per cc-task ``pub-bus-orcid-auto-update``. ORCID's DataCite
auto-update only operates at concept-DOI granularity; the daemon
verifies that minted concept-DOIs flow through to the operator's
ORCID record without intervening per-version PUTs (anti-pattern
per drop 5).

Phase 1 ships the verifier function trio:

  - :func:`fetch_orcid_works` — GET against the ORCID public API
    (``https://pub.orcid.org/v3.0/{orcid}/works``); no auth required
  - :func:`extract_dois` — pull DOI ``external-id`` values out of the
    works response
  - :func:`verify_dois_present` — set diff returning DOIs expected
    but not present in ORCID

Phase 2 wires these into a 24h timer that reads recent concept-DOIs
from local state, verifies they appear, and emits ntfy if any are
missing past 72h (likely indicates auto-update toggle was disabled
on the ORCID side).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from prometheus_client import Counter

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

ORCID_PUBLIC_API_BASE: str = "https://pub.orcid.org/v3.0"
"""Public ORCID API endpoint root. No auth required for read."""

ORCID_REQUEST_TIMEOUT_S: float = 30.0


orcid_works_total = Counter(
    "hapax_publication_bus_orcid_works_total",
    "ORCID works fetch outcomes per ORCID + result.",
    ["orcid", "outcome"],
)


def fetch_orcid_works(
    orcid_id: str,
    *,
    api_base: str = ORCID_PUBLIC_API_BASE,
    timeout_s: float = ORCID_REQUEST_TIMEOUT_S,
) -> dict[str, Any] | None:
    """GET the ``/works`` summary for ``orcid_id``; return parsed body or None.

    The endpoint returns a list of grouped works; each group bundles
    multiple `external-id` records (DOI, URI, etc.) for the same
    underlying work. Network and 4xx/5xx failures return None for
    retry on the next verification tick.
    """
    if requests is None:
        log.warning("requests library not available; skipping orcid works fetch")
        return None
    url = f"{api_base}/{orcid_id}/works"
    try:
        response = requests.get(
            url,
            headers={"Accept": "application/json"},
            timeout=timeout_s,
        )
    except requests.RequestException as exc:
        log.warning("orcid works fetch raised: %s", exc)
        orcid_works_total.labels(orcid=orcid_id, outcome="transport-error").inc()
        return None

    if response.status_code != 200:
        orcid_works_total.labels(orcid=orcid_id, outcome=f"http-{response.status_code}").inc()
        return None
    try:
        body = response.json()
    except ValueError:
        orcid_works_total.labels(orcid=orcid_id, outcome="non-json").inc()
        return None
    orcid_works_total.labels(orcid=orcid_id, outcome="ok").inc()
    return body


def extract_dois(works_response: dict[str, Any]) -> set[str]:
    """Pull all DOI ``external-id-value`` strings out of an ORCID works response.

    The response shape is ``{"group": [{"external-ids": {"external-id":
    [{"external-id-type": "doi", "external-id-value": "..."}]}}]}``;
    this helper normalises that nested structure into a flat set of
    DOIs. Malformed nodes are silently skipped — the verifier must
    remain operational under partial-data conditions.
    """
    dois: set[str] = set()
    if not isinstance(works_response, dict):
        return dois
    groups = works_response.get("group")
    if not isinstance(groups, list):
        return dois
    for group in groups:
        ext_ids = group.get("external-ids") if isinstance(group, dict) else None
        if not isinstance(ext_ids, dict):
            continue
        ext_id_list = ext_ids.get("external-id")
        if not isinstance(ext_id_list, list):
            continue
        for ext_id in ext_id_list:
            if not isinstance(ext_id, dict):
                continue
            if ext_id.get("external-id-type") != "doi":
                continue
            value = ext_id.get("external-id-value")
            if isinstance(value, str):
                dois.add(value)
    return dois


def verify_dois_present(
    *,
    expected_dois: set[str],
    fetched_dois: set[str],
) -> set[str]:
    """Return the set of expected DOIs not present in ``fetched_dois``.

    Comparison is case-insensitive — DOIs are case-insensitive per
    DataCite spec, but ORCID may return mixed case. Extra DOIs in
    ``fetched_dois`` are ignored (the verifier doesn't gate on
    completeness, only on absence of expected entries).
    """
    fetched_lower = {doi.lower() for doi in fetched_dois}
    return {doi for doi in expected_dois if doi.lower() not in fetched_lower}


DEFAULT_RECENT_CONCEPT_DOIS_PATH = (
    Path.home() / "hapax-state" / "publications" / "recent-concept-dois.txt"
)
"""Local newline-delimited list of concept-DOIs recently minted by
the publication bus. The Phase 2 daemon reads this file as the
"expected DOIs" set; the Zenodo deposit_builder writes to it on each
successful mint (Phase 2 of pub-bus-zenodo-related-identifier-graph)."""


def load_recent_concept_dois(*, path: Path = DEFAULT_RECENT_CONCEPT_DOIS_PATH) -> set[str]:
    """Read the newline-delimited concept-DOI list; return empty set if absent."""
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text().splitlines() if line.strip()}


def main() -> int:
    """Single-pass verification entry for systemd timer.

    Reads ``HAPAX_OPERATOR_ORCID`` env var; fetches the operator's
    ORCID works; loads expected concept-DOIs from
    ``~/hapax-state/publications/recent-concept-dois.txt``; logs any
    missing DOIs (ntfy escalation on >72h-old gaps belongs in Phase 3
    once the recent-DOIs file carries timestamps).
    """
    import os

    logging.basicConfig(level=logging.INFO)
    orcid = os.environ.get("HAPAX_OPERATOR_ORCID")
    if not orcid:
        log.info("HAPAX_OPERATOR_ORCID not set; orcid verifier skipping this tick")
        orcid_works_total.labels(orcid="unset", outcome="no-orcid-configured").inc()
        return 0

    works = fetch_orcid_works(orcid)
    if works is None:
        log.info("orcid works fetch failed; will retry next tick")
        return 0

    fetched = extract_dois(works)
    expected = load_recent_concept_dois()
    missing = verify_dois_present(expected_dois=expected, fetched_dois=fetched)

    if missing:
        log.info(
            "orcid auto-update verification: %d DOIs minted but not yet visible in ORCID: %s",
            len(missing),
            sorted(missing),
        )
    else:
        log.info(
            "orcid auto-update verification ok: %d DOIs all visible in ORCID",
            len(expected),
        )
    return 0


__all__ = [
    "DEFAULT_RECENT_CONCEPT_DOIS_PATH",
    "ORCID_PUBLIC_API_BASE",
    "ORCID_REQUEST_TIMEOUT_S",
    "extract_dois",
    "fetch_orcid_works",
    "load_recent_concept_dois",
    "main",
    "orcid_works_total",
    "verify_dois_present",
]


if __name__ == "__main__":
    raise SystemExit(main())
