"""Candidate registry — Phase 1.

Per cc-task ``cold-contact-candidate-registry``. The registry declares
the named targets eligible for citation-graph touches. Each entry
carries an ORCID iD (validated by :mod:`agents.cold_contact.orcid_validator`),
audience-vector tags (drawn from a fixed 14+-vector controlled
vocabulary per drop 2), and topic-relevance markers.

The registry is operator+Hapax curated; the YAML schema is the
authoritative form. Phase 1 ships the loader + Pydantic model + the
controlled-vocabulary constant. Phase 2 will populate the YAML with
the 37 candidates from drop 2 (after operator review pass).

Constitutional fit:

- **Single-operator:** the registry is operator-curated; not a
  multi-tenant directory.
- **Refusal-as-data:** entries can be moved to the suppression list
  (``hapax-state/contact-suppression-list.yaml``) at any point;
  suppression takes precedence over registry membership.
- **Anti-anthropomorphization:** entries are tagged scientifically
  (audience-vector + topic-relevance), not with personality /
  interaction-style labels.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Final

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

from shared.contact_suppression import load as load_suppression_list

log = logging.getLogger(__name__)

ORCID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")

DEFAULT_REGISTRY_PATH: Final[Path] = (
    Path(__file__).resolve().parents[2] / "config" / "cold-contact-candidates.yaml"
)
"""Repository-relative path: ``<repo>/config/cold-contact-candidates.yaml``."""

AUDIENCE_VECTORS: Final[frozenset[str]] = frozenset(
    {
        "4e-cognition",
        "active-inference",
        "ai-consciousness",
        "ai-personhood-law",
        "crit-code-studies",
        "critical-ai",
        "demoscene",
        "infrastructure-studies",
        "listservs",
        "permacomputing",
        "philosophy-of-tech",
        "posthumanism",
        "practice-as-research",
        "sound-art",
    }
)
"""Controlled vocabulary of audience vectors per drop 2 §3. Expansion
beyond this set requires constitutional discussion (per cc-task
``out of scope`` clause)."""


class CandidateEntry(BaseModel):
    """One named target eligible for citation-graph touch.

    Constitutional fit: this is a tagged research-relevance record,
    not a contact-database row. There is no email field, no telephone,
    no address — direct outreach is REFUSED per the family-wide refusal
    stance. The ORCID iD is the only identifier that participates in
    the citation graph.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    orcid: str
    audience_vectors: list[str]
    topic_relevance: list[str]

    @field_validator("orcid", mode="before")
    @classmethod
    def _normalize_and_validate_orcid(cls, value: str) -> str:
        """Normalise and validate ORCID iD to the bare 16-character form.

        Operator may write either ``0000-0001-2345-6789`` or the full
        ``https://orcid.org/0000-0001-2345-6789`` URL. Both normalise
        to the bare form so downstream consumers (DataCite GraphQL,
        Zenodo RelatedIdentifier graph) can treat them uniformly.
        """
        if not isinstance(value, str):
            raise ValueError("ORCID iD must be a string")
        normalized = value.strip()
        if normalized.startswith("https://orcid.org/"):
            normalized = normalized.removeprefix("https://orcid.org/")
        normalized = normalized.upper()
        if not ORCID_PATTERN.fullmatch(normalized):
            raise ValueError("ORCID iD must match 0000-0000-0000-0000 with optional X check digit")
        if not _orcid_checksum_valid(normalized):
            raise ValueError("ORCID iD checksum is invalid")
        return normalized

    @field_validator("audience_vectors")
    @classmethod
    def _check_audience_vectors_in_vocabulary(cls, value: list[str]) -> list[str]:
        for vector in value:
            if vector not in AUDIENCE_VECTORS:
                raise ValueError(
                    f"audience vector {vector!r} not in controlled vocabulary; "
                    f"expansion requires constitutional discussion"
                )
        return value


def _orcid_checksum_valid(orcid: str) -> bool:
    """Return whether ``orcid`` satisfies ISO 7064 MOD 11-2."""
    compact = orcid.replace("-", "")
    total = 0
    for char in compact[:-1]:
        total = (total + int(char)) * 2
    result = (12 - (total % 11)) % 11
    expected = "X" if result == 10 else str(result)
    return compact[-1] == expected


def load_candidate_registry(*, path: Path = DEFAULT_REGISTRY_PATH) -> list[CandidateEntry]:
    """Load the candidate registry from YAML.

    Returns an empty list when the file is missing, empty, or lacks
    the ``candidates`` key — the loader is permissive at the structural
    boundary so partially-bootstrapped configs don't break the daemon.
    Per-entry validation errors propagate (so malformed entries fail
    loud at registry-load time).
    """
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text()) or {}
    if not isinstance(raw, dict):
        return []
    candidates_raw = raw.get("candidates", [])
    if not isinstance(candidates_raw, list):
        return []
    return [CandidateEntry.model_validate(entry) for entry in candidates_raw]


def filter_suppressed_candidates(
    candidates: list[CandidateEntry],
    *,
    suppression_path: Path | None = None,
) -> list[CandidateEntry]:
    """Remove candidates whose ORCID appears in the suppression list.

    The raw registry loader preserves on-disk facts. Runtime callers
    should use this helper, or :func:`load_eligible_candidate_registry`,
    so the contact suppression primitive stays ahead of every
    graph-touch decision.
    """
    suppressions = load_suppression_list(path=suppression_path)
    suppressed_orcids = {entry.orcid for entry in suppressions.entries if entry.orcid}
    if not suppressed_orcids:
        return list(candidates)
    return [candidate for candidate in candidates if candidate.orcid not in suppressed_orcids]


def load_eligible_candidate_registry(
    *,
    path: Path = DEFAULT_REGISTRY_PATH,
    suppression_path: Path | None = None,
) -> list[CandidateEntry]:
    """Load candidates eligible for runtime graph-touch consideration."""
    return filter_suppressed_candidates(
        load_candidate_registry(path=path),
        suppression_path=suppression_path,
    )


__all__ = [
    "AUDIENCE_VECTORS",
    "DEFAULT_REGISTRY_PATH",
    "CandidateEntry",
    "filter_suppressed_candidates",
    "load_candidate_registry",
    "load_eligible_candidate_registry",
]
