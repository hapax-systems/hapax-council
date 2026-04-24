"""omg.lol pastebin artifact publisher — ytb-OMG6 Phase A.

Publishes curated Hapax-internal artifacts as discoverable pastes at
``hapax.omg.lol/pastebin/<slug>``. Phase A ships the chronicle category
(week-aggregated high-salience event summary); other categories
(programme plans, axiom precedents, research corpus) are follow-ups
that reuse the same publisher machinery.

Each paste walks the publication allowlist for
``surface=omg-lol-pastebin`` + state-kind-specific redactions before
the API call. Slugs are deterministic so re-publishing the same digest
is idempotent (omg.lol `set_paste` overwrites on slug collision).
"""

from agents.omg_pastebin_publisher.publisher import (
    PastebinArtifactPublisher,
    build_chronicle_digest,
    build_chronicle_slug,
)

__all__ = [
    "PastebinArtifactPublisher",
    "build_chronicle_digest",
    "build_chronicle_slug",
]
