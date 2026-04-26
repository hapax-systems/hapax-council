"""Zenodo community submitter — Phase 1.

Per cc-task ``xprom-zenodo-community-policy`` and drop-5 anti-pattern
§7. Zenodo communities have a manual-acceptance gate by default; this
module honors that gate (does NOT auto-accept) but auto-submits
relevant deposits to relevant communities so that, when a community
owner accepts, the citation graph extends.

If a community owner declines or never reviews, the deposit still
exists at its own DOI — submission is best-effort, never load-bearing.

Phase 1 ships:
  - :data:`HAPAX_COMMUNITY_SLUGS` — operator-curated community slugs
  - :data:`DEFAULT_COMMUNITY_TAXONOMY` — topic → community mapping
  - :func:`match_communities_for_deposit` — topic-to-community resolver
  - :class:`SubmissionOutcome` — typed outcome shape
  - :class:`ZenodoCommunitySubmitter` — submit-only client

Phase 2 will wire the daemon path that pulls each new deposit from
the publish-orchestrator queue, computes topic intersection, and
dispatches submissions per matched community.

Constitutional posture:
- ``feedback_full_automation_or_no_engagement``: submission is
  daemon-side, never operator-mediated
- Drop-5 anti-pattern §7: NEVER auto-accept; manual gate is honored
- Refusal-as-data on missing creds (Zenodo PAT bootstrap is one-time)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

from prometheus_client import Counter

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

ZENODO_API_BASE: Final[str] = "https://zenodo.org/api"
"""Zenodo REST API root."""

ZENODO_COMMUNITY_SUBMIT_PATH_TEMPLATE: Final[str] = "/deposit/depositions/{deposit_id}"
"""Per Zenodo REST API: community submission is a metadata.communities
field update on the deposit. The PUT updates the deposit's
``metadata.communities`` array; Zenodo internally enqueues the
community-side review request when the deposit is published.

We do NOT call ``/community/{slug}/curate/accept`` — that's the
auto-accept anti-pattern drop-5 §7 forbids."""

ZENODO_REQUEST_TIMEOUT_S: Final[float] = 60.0
"""Zenodo PUT timeout. 60s is generous; metadata updates are small."""

HAPAX_COMMUNITY_SLUGS: Final[frozenset[str]] = frozenset(
    {
        "single-operator-systems",
        "philosophy-of-computation",
        "refusal-shaped-infrastructure",
        "anti-anthropomorphization",
        "infrastructure-as-argument",
    }
)
"""Operator-curated Zenodo community slugs that match Hapax research
themes. Each slug must exist on Zenodo; if the community doesn't yet
exist, this list is the operator's TODO for community-creation
bootstrap."""

DEFAULT_COMMUNITY_TAXONOMY: Final[dict[str, frozenset[str]]] = {
    "single-operator": frozenset({"single-operator-systems"}),
    "axioms": frozenset({"philosophy-of-computation", "single-operator-systems"}),
    "refusal-as-data": frozenset({"refusal-shaped-infrastructure", "philosophy-of-computation"}),
    "philosophy-of-computation": frozenset({"philosophy-of-computation"}),
    "philosophy-of-tech": frozenset({"philosophy-of-computation"}),
    "anti-anthropomorphization": frozenset({"anti-anthropomorphization"}),
    "infrastructure-as-argument": frozenset({"infrastructure-as-argument"}),
}
"""Topic → community mapping. Per drop-5 §7, deposit-topic strings
arrive from the publish-orchestrator's classification step; this
table maps them to community slugs for the submission decision.

Multi-community matches are common (e.g., ``axioms`` deposits
typically fit both ``philosophy-of-computation`` and
``single-operator-systems``)."""


submissions_total = Counter(
    "hapax_publication_bus_community_submissions_total",
    "Per-community Zenodo submission outcomes",
    ["community", "result"],
)


@dataclass(frozen=True)
class SubmissionOutcome:
    """One community submission's outcome.

    ``ok=True`` for 2xx response; ``ok=False`` for transport / 4xx /
    5xx / missing-creds. ``detail`` carries a short human-readable
    string for observability.
    """

    deposit_id: str
    community: str
    ok: bool
    detail: str


def match_communities_for_deposit(
    deposit_topics: list[str] | tuple[str, ...],
    taxonomy: dict[str, frozenset[str]] | dict[str, list[str]] | None = None,
) -> list[str]:
    """Return the deduplicated list of community slugs matching the
    deposit's topics.

    ``taxonomy`` defaults to :data:`DEFAULT_COMMUNITY_TAXONOMY`. The
    return list preserves insertion order (first-topic-first) and is
    deduplicated; multiple topics mapping to the same community
    contribute one entry.

    Returns ``[]`` when no topic intersects the taxonomy. Per
    drop-5 §7 anti-pattern: a deposit with no community match is
    NOT a refusal — it just means none of the operator-curated
    communities are a fit. The deposit still mints its DOI and
    surfaces in DataCite Commons via the GraphQL mirror.
    """
    if taxonomy is None:
        taxonomy = DEFAULT_COMMUNITY_TAXONOMY  # type: ignore[assignment]

    seen: set[str] = set()
    ordered: list[str] = []
    for topic in deposit_topics:
        candidates = taxonomy.get(topic, [])
        for community in candidates:
            if community not in seen:
                seen.add(community)
                ordered.append(community)
    return ordered


class ZenodoCommunitySubmitter:
    """Submit deposits to Zenodo communities (no auto-accept).

    One instance per Zenodo PAT. ``submit_to_community(deposit_id,
    community)`` PUTs an updated ``metadata.communities`` array on the
    deposit, which enqueues Zenodo's community-side review.

    Refusal-as-data on missing token. Per drop-5 §7, the auto-accept
    side of the curation API is NEVER called.
    """

    def __init__(self, *, zenodo_token: str) -> None:
        self.zenodo_token = zenodo_token

    def submit_to_community(
        self,
        *,
        deposit_id: str,
        community: str,
    ) -> SubmissionOutcome:
        """Submit one deposit to one community.

        Returns :class:`SubmissionOutcome`; never raises. The submitter
        does not track submission cadence — the daemon caller is
        responsible for not double-submitting.
        """
        if not self.zenodo_token:
            submissions_total.labels(community=community, result="refused").inc()
            return SubmissionOutcome(
                deposit_id=deposit_id,
                community=community,
                ok=False,
                detail=(
                    "missing Zenodo credentials "
                    "(operator-action queue: configure Zenodo PAT in pass)"
                ),
            )
        if requests is None:
            return SubmissionOutcome(
                deposit_id=deposit_id,
                community=community,
                ok=False,
                detail="requests library not available",
            )

        url = ZENODO_API_BASE + ZENODO_COMMUNITY_SUBMIT_PATH_TEMPLATE.format(deposit_id=deposit_id)
        headers = {
            "Authorization": f"Bearer {self.zenodo_token}",
            "Content-Type": "application/json",
        }
        body = {
            "metadata": {
                "communities": [{"identifier": community}],
            },
        }
        try:
            response = requests.post(
                url,
                json=body,
                headers=headers,
                timeout=ZENODO_REQUEST_TIMEOUT_S,
            )
        except requests.RequestException as exc:
            log.warning("Zenodo community submission raised: %s", exc)
            submissions_total.labels(community=community, result="error").inc()
            return SubmissionOutcome(
                deposit_id=deposit_id,
                community=community,
                ok=False,
                detail=f"transport failure: {exc}",
            )

        status = response.status_code
        if 200 <= status < 300:
            submissions_total.labels(community=community, result="ok").inc()
            return SubmissionOutcome(
                deposit_id=deposit_id,
                community=community,
                ok=True,
                detail=f"submitted (HTTP {status})",
            )
        submissions_total.labels(community=community, result="error").inc()
        return SubmissionOutcome(
            deposit_id=deposit_id,
            community=community,
            ok=False,
            detail=f"Zenodo HTTP {status}: {response.text[:160]}",
        )


__all__ = [
    "DEFAULT_COMMUNITY_TAXONOMY",
    "HAPAX_COMMUNITY_SLUGS",
    "SubmissionOutcome",
    "ZENODO_API_BASE",
    "ZENODO_COMMUNITY_SUBMIT_PATH_TEMPLATE",
    "ZENODO_REQUEST_TIMEOUT_S",
    "ZenodoCommunitySubmitter",
    "match_communities_for_deposit",
    "submissions_total",
]
