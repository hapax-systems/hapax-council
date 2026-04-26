"""Graph touch policy — Phase 1.

Per cc-task ``cold-contact-zenodo-iscitedby-touch``. The graph touch
policy decides which candidates from
:mod:`agents.cold_contact.candidate_registry` to cite per Zenodo
deposit, subject to:

  - audience-vector overlap (must be > 0)
  - cadence rule (≤ ``DEFAULT_MAX_TOUCHES_PER_YEAR`` per candidate
    in the trailing 365 days; chronicle-tracked via JSONL log)
  - suppression-list precedence (set of ORCIDs to skip)

Phase 1 ships the pure-function policy + the cadence-tracking JSONL
log + RelatedIdentifier construction. Phase 2 will integrate with
the Zenodo deposit_builder once it ships.

Constitutional fit:

- **Cadence cap** keeps citation density low — touch is *evidence
  of relevance*, not *spamming*. 3/year/candidate is the operator-
  decreed ceiling per drop 2.
- **Suppression precedence** lets the operator fully retract a
  candidate at any point; suppression is first-class data alongside
  the registry itself.
- **No-direct-outreach:** this module produces only DataCite
  RelatedIdentifier graph edges; the citation graph IS the entire
  contact surface. Drop 2's family-wide refusal stance retained.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from prometheus_client import Counter

from agents.cold_contact.candidate_registry import CandidateEntry
from agents.publication_bus.related_identifier import (
    IdentifierType,
    RelatedIdentifier,
    RelationType,
)

log = logging.getLogger(__name__)

DEFAULT_TOUCHES_LOG_PATH: Final[Path] = (
    Path.home() / "hapax-state" / "cold-contact" / "touches.jsonl"
)
"""Append-only JSONL log of every Zenodo touch. Cadence enforcement
reads this log to count per-candidate trailing-365d touches."""

DEFAULT_MAX_CANDIDATES_PER_DEPOSIT: Final[int] = 5
"""Per cc-task spec: ≤5 candidates cited per deposit. Caps citation
density so each touch retains evidential weight."""

DEFAULT_MAX_TOUCHES_PER_YEAR: Final[int] = 3
"""Per drop 2 spec: ≤3 candidate touches/year/target. Enforced by
:func:`apply_cadence_rule`."""

TOPIC_RELEVANCE_BONUS: Final[float] = 0.5
"""Score bonus per topic-relevance term that intersects the deposit's
topic tags. Smaller than the audience-vector overlap weight (1.0) so
audience-vector primacy is preserved."""


zenodo_touches_total = Counter(
    "hapax_cold_contact_zenodo_touches_total",
    "Zenodo IsCitedBy touch outcomes per candidate audience-vector + result.",
    ["candidate_audience_vector", "result"],
)


def score_candidate_for_deposit(
    candidate: CandidateEntry,
    *,
    deposit_topics: list[str],
    deposit_audience_vectors: list[str],
) -> float:
    """Score a candidate's relevance to the deposit.

    Score formula (Phase 1, intentionally simple):

        score = |candidate.audience_vectors ∩ deposit_audience_vectors|
              + TOPIC_RELEVANCE_BONUS *
                |candidate.topic_relevance ∩ deposit_topics|

    Audience-vector overlap is the primary signal (1.0 per match);
    topic-relevance overlap is a smaller multiplier so vector mismatch
    can't be papered over by topic-only overlap. Phase 2 may shift
    to TF-IDF / embedding similarity if heuristic precision is
    insufficient.
    """
    vector_overlap = set(candidate.audience_vectors) & set(deposit_audience_vectors)
    topic_overlap = set(candidate.topic_relevance) & set(deposit_topics)
    return float(len(vector_overlap)) + TOPIC_RELEVANCE_BONUS * float(len(topic_overlap))


def select_candidates_for_deposit(
    *,
    deposit_topics: list[str],
    deposit_audience_vectors: list[str],
    registry: list[CandidateEntry],
    suppressions: set[str],
    max_candidates: int = DEFAULT_MAX_CANDIDATES_PER_DEPOSIT,
) -> list[CandidateEntry]:
    """Return the top-N most-relevant non-suppressed candidates.

    Filters: zero-score candidates excluded; suppressed ORCIDs
    excluded. Sort: descending score, ties broken by name (stable).
    """
    eligible: list[tuple[float, CandidateEntry]] = []
    for candidate in registry:
        if candidate.orcid in suppressions:
            continue
        score = score_candidate_for_deposit(
            candidate,
            deposit_topics=deposit_topics,
            deposit_audience_vectors=deposit_audience_vectors,
        )
        if score <= 0:
            continue
        eligible.append((score, candidate))

    eligible.sort(key=lambda pair: (-pair[0], pair[1].name))
    return [candidate for _, candidate in eligible[:max_candidates]]


def apply_cadence_rule(
    candidates: list[CandidateEntry],
    *,
    log_path: Path = DEFAULT_TOUCHES_LOG_PATH,
    max_touches_per_year: int = DEFAULT_MAX_TOUCHES_PER_YEAR,
) -> list[CandidateEntry]:
    """Filter candidates whose trailing-365d touch count is at the cap.

    Reads :data:`DEFAULT_TOUCHES_LOG_PATH` (or override). Each line is
    a JSON record with ``orcid`` and ``timestamp``. Counts touches in
    the last 365 days; candidates at or above ``max_touches_per_year``
    are filtered out.

    Missing or malformed log lines are ignored — the daemon must remain
    operational under partial-state conditions.
    """
    counts = _count_touches_last_365d(log_path)
    return [c for c in candidates if counts.get(c.orcid, 0) < max_touches_per_year]


def log_touch(
    *,
    orcid: str,
    deposit_doi: str,
    log_path: Path = DEFAULT_TOUCHES_LOG_PATH,
    now: datetime | None = None,
) -> None:
    """Append one touch event to the JSONL log.

    Called immediately after a Zenodo deposit is minted with the
    candidate cited. Idempotent at the deposit-DOI granularity is
    NOT enforced here — re-deposits create new touch events
    (cadence rule still applies).
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    when = now or datetime.now(UTC)
    entry = {
        "orcid": orcid,
        "deposit_doi": deposit_doi,
        "timestamp": when.isoformat(),
    }
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def build_touch_related_identifiers(
    candidates: list[CandidateEntry],
) -> list[RelatedIdentifier]:
    """Build IsCitedBy RelatedIdentifier edges for each candidate.

    Returns one :class:`RelatedIdentifier` per candidate, with
    ``identifier_type=ORCID`` and ``relation_type=IsCitedBy``. The
    identifier is the full ORCID URL form (``https://orcid.org/...``)
    per DataCite convention.

    Consumed by the Zenodo deposit_builder to inject the candidates
    into the deposit's ``related_identifiers`` array.
    """
    return [
        RelatedIdentifier(
            identifier=f"https://orcid.org/{candidate.orcid}",
            identifier_type=IdentifierType.ORCID,
            relation_type=RelationType.IS_CITED_BY,
        )
        for candidate in candidates
    ]


def _count_touches_last_365d(log_path: Path) -> dict[str, int]:
    if not log_path.exists():
        return {}
    cutoff = datetime.now(UTC) - timedelta(days=365)
    counts: dict[str, int] = {}
    for line in log_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            ts = datetime.fromisoformat(record["timestamp"])
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
        if ts < cutoff:
            continue
        orcid = record.get("orcid")
        if isinstance(orcid, str):
            counts[orcid] = counts.get(orcid, 0) + 1
    return counts


__all__ = [
    "DEFAULT_MAX_CANDIDATES_PER_DEPOSIT",
    "DEFAULT_MAX_TOUCHES_PER_YEAR",
    "DEFAULT_TOUCHES_LOG_PATH",
    "TOPIC_RELEVANCE_BONUS",
    "apply_cadence_rule",
    "build_touch_related_identifiers",
    "log_touch",
    "score_candidate_for_deposit",
    "select_candidates_for_deposit",
    "zenodo_touches_total",
]
