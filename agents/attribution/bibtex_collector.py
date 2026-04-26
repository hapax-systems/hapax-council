"""BibTeX collector — pulls Citation Feature entries for resolved SWHIDs.

Per cc-task ``leverage-attrib-swh-swhid-bibtex`` Phase 2b. Reads the
canonical ``swhids.yaml``, calls SWH's Citation Feature for each record
with a resolved SWHID, concatenates the BibTeX entries to a single
``bibtex.bib`` file, and (optionally) injects each repo's SWHID into
its CITATION.cff sidecar.

Designed to be run after :mod:`agents.attribution.swh_archive_daemon`
populates ``swhids.yaml``. Idempotent: re-running overwrites
``bibtex.bib`` and updates each ``CITATION.cff`` in place.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from prometheus_client import Counter

from agents.attribution.citation_cff_updater import update_citation_cff
from agents.attribution.citation_feature import fetch_bibtex
from agents.attribution.swhids_yaml import (
    DEFAULT_SWHIDS_PATH,
    load_swhids,
)

log = logging.getLogger(__name__)

DEFAULT_BIBTEX_PATH: Path = Path.home() / "hapax-state" / "attribution" / "bibtex.bib"
"""Canonical path for the concatenated BibTeX file. Downstream consumers
(the website-side citation surface, README badges) read this single
file rather than re-fetching from SWH per render."""


bibtex_entries_total = Counter(
    "hapax_leverage_bibtex_entries_total",
    "Number of BibTeX entries fetched per repo + outcome.",
    ["repo", "outcome"],
)


def collect_all_bibtex(
    *,
    swhids_path: Path = DEFAULT_SWHIDS_PATH,
    bibtex_path: Path = DEFAULT_BIBTEX_PATH,
    citation_cff_root: Path | None = None,
) -> None:
    """Pull BibTeX for every resolved SWHID and persist results.

    ``citation_cff_root`` is optional; when provided, each repo's
    ``CITATION.cff`` at ``<root>/<slug>/CITATION.cff`` receives a
    SWH identifier entry. Production callers leave this ``None`` for
    daemon mode (CITATION.cff updates happen at deploy time, not
    crawl time).
    """
    records = load_swhids(path=swhids_path)
    entries: list[str] = []
    for slug, record in records.items():
        if record.swhid is None:
            bibtex_entries_total.labels(repo=slug, outcome="skip-no-swhid").inc()
            continue
        bibtex = fetch_bibtex(record.swhid)
        if bibtex is None:
            bibtex_entries_total.labels(repo=slug, outcome="fetch-failed").inc()
            continue
        entries.append(bibtex)
        bibtex_entries_total.labels(repo=slug, outcome="ok").inc()

        if citation_cff_root is not None:
            cff_path = citation_cff_root / slug / "CITATION.cff"
            if cff_path.exists():
                try:
                    update_citation_cff(cff_path, record.swhid)
                except Exception as exc:  # pragma: no cover — defensive
                    log.warning("CITATION.cff update raised for %s: %s", slug, exc)

    _atomic_write_text(bibtex_path, "\n\n".join(entries) + "\n" if entries else "")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".bibtex-", suffix=".bib", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def main() -> int:
    """Entry for ``python -m agents.attribution.bibtex_collector``."""
    logging.basicConfig(level=logging.INFO)
    collect_all_bibtex()
    return 0


__all__ = [
    "DEFAULT_BIBTEX_PATH",
    "bibtex_entries_total",
    "collect_all_bibtex",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
