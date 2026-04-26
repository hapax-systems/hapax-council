"""SWH Citation Feature — fetch BibTeX entries for resolved SWHIDs.

Per cc-task ``leverage-attrib-swh-swhid-bibtex`` Phase 2b. Once a repo
has a SWHID (via :func:`agents.attribution.swh_register.resolve_swhid`),
we fetch a citation-ready BibTeX entry from SWH's Citation Feature.

Endpoint: ``GET /api/1/raw-intrinsic-metadata/citation/swhid/?citation_format=bibtex&target_swhid=<SWHID>``

SWH derives the BibTeX entry from intrinsic metadata in the repo
(``codemeta.json`` and/or ``CITATION.cff``). The entry type
(``@software``, ``@softwareversion``) is auto-selected from the
SWHID prefix.

Like :mod:`agents.attribution.swh_register`, this is unauthenticated.
"""

from __future__ import annotations

import logging

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

SWH_CITATION_ENDPOINT: str = (
    "https://archive.softwareheritage.org/api/1/raw-intrinsic-metadata/citation/swhid/"
)
"""Citation Feature endpoint. Returns a BibTeX entry as text/plain when
``citation_format=bibtex`` is set."""

CITATION_REQUEST_TIMEOUT_S: float = 30.0


def fetch_bibtex(
    swhid: str,
    *,
    endpoint: str = SWH_CITATION_ENDPOINT,
    timeout_s: float = CITATION_REQUEST_TIMEOUT_S,
) -> str | None:
    """Fetch a BibTeX entry for ``swhid``; return ``None`` on any failure.

    SWH returns 404 when the SWHID has no resolved snapshot or the
    repo lacks intrinsic metadata; transient 5xx and network errors
    return ``None`` so callers retry on next pass without losing
    state. The caller persists successful entries to ``bibtex.bib``.
    """
    if requests is None:
        log.warning("requests library not available; skipping bibtex fetch")
        return None

    params = {"citation_format": "bibtex", "target_swhid": swhid}
    try:
        response = requests.get(endpoint, params=params, timeout=timeout_s)
    except requests.RequestException as exc:
        log.warning("swh citation fetch raised: %s", exc)
        return None

    if response.status_code == 200:
        return response.text
    log.info("swh citation fetch HTTP %d for %s", response.status_code, swhid)
    return None


__all__ = [
    "CITATION_REQUEST_TIMEOUT_S",
    "SWH_CITATION_ENDPOINT",
    "fetch_bibtex",
]
