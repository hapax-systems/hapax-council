"""Update CITATION.cff sidecars with SWH identifier.

Per cc-task ``leverage-attrib-swh-swhid-bibtex`` Phase 2b. CITATION.cff
files in each repo declare bibliographic metadata in YAML; the spec
(cff-version 1.2.0) supports an ``identifiers`` field for persistent
external IDs (DOI, SWH, etc.). After a SWHID resolves, we add or
update its entry so downstream citation tools (Zenodo, Crossref,
Semantic Scholar) discover the SWH archival anchor.

The updater is idempotent: re-running with the same SWHID is a no-op;
re-running with a new SWHID replaces the prior ``type: swh`` entry
(repos publish from a moving HEAD, so SWHIDs evolve).

Atomic write via ``shared.threshold_tuner``-style tempfile + os.replace.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

SWH_IDENTIFIER_DESCRIPTION: str = "Software Heritage persistent identifier (snapshot)"
"""Description string attached to the SWH identifier entry. Surfaces
in CITATION.cff readers (Zenodo, Crossref) as the ID's human-readable
context."""


def update_citation_cff(cff_path: Path, swhid: str) -> None:
    """Add or update the SWH identifier in ``cff_path``.

    If the file lacks an ``identifiers`` block, one is created. If
    a ``type: swh`` entry already exists, its value is replaced (so
    subsequent SWHID rotations as the repo evolves write through
    cleanly). Other identifier types (e.g. ``doi``) are preserved.

    Atomic write semantics: failure mid-rewrite leaves the original
    file intact.
    """
    raw = yaml.safe_load(cff_path.read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"CITATION.cff at {cff_path} is not a YAML mapping")

    identifiers = raw.get("identifiers", [])
    if not isinstance(identifiers, list):
        identifiers = []

    # Filter out any pre-existing swh entry so the replacement is unique.
    identifiers = [i for i in identifiers if not _is_swh_entry(i)]
    identifiers.append(
        {
            "type": "swh",
            "value": swhid,
            "description": SWH_IDENTIFIER_DESCRIPTION,
        }
    )
    raw["identifiers"] = identifiers

    _atomic_write_yaml(cff_path, raw)


def _is_swh_entry(entry: Any) -> bool:
    return isinstance(entry, dict) and entry.get("type") == "swh"


def _atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".cff-", suffix=".yaml", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, sort_keys=False, default_flow_style=False)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


__all__ = [
    "SWH_IDENTIFIER_DESCRIPTION",
    "update_citation_cff",
]
