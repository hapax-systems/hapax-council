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
from pathlib import Path
from typing import Final

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

log = logging.getLogger(__name__)

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
    def _strip_orcid_url_prefix(cls, value: str) -> str:
        """Normalise ORCID iD to the bare 16-digit form.

        Operator may write either ``0000-0001-2345-6789`` or the full
        ``https://orcid.org/0000-0001-2345-6789`` URL. Both normalise
        to the bare form so downstream consumers (DataCite GraphQL,
        Zenodo RelatedIdentifier graph) can treat them uniformly.
        """
        if isinstance(value, str) and value.startswith("https://orcid.org/"):
            return value.removeprefix("https://orcid.org/")
        return value

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


__all__ = [
    "AUDIENCE_VECTORS",
    "DEFAULT_REGISTRY_PATH",
    "CandidateEntry",
    "load_candidate_registry",
]
