"""Publisher kit for V5 publication-bus (one-shot publish-on-demand).

Per V5 weave §2.1 PUB-P0-B keystone. Three load-bearing invariants
every v5 publisher enforces, all baked into the superclass
``publish()`` method:

1. **Allowlist gate** — surface targets must be explicitly registered
2. **Legal-name-leak guard** — operator-referent picker enforced on
   every emitted text payload; legal name only in formal-required
   fields (subclass declares via ``requires_legal_name``)
3. **Counter** — Prometheus emit per send (success/error/refused),
   per-surface labels

Subclass shape (~80 LOC):

    class ZenodoPublisher(Publisher):
        surface_name = "zenodo-deposit"
        allowlist = ALLOWLIST_ZENODO
        requires_legal_name = True  # creators array uses formal name

        def _emit(self, payload):
            return self.zenodo_client.deposit(payload)

The v4 daemon-tail ``BasePublisher`` at
``shared/governance/publisher_kit.py`` continues to serve cross-
surface JSONL-event publishers; this v5 kit is for one-shot
publish-on-demand.
"""

from __future__ import annotations

from agents.publication_bus.publisher_kit.allowlist import (
    AllowlistGate,
    AllowlistViolation,
)
from agents.publication_bus.publisher_kit.base import (
    Publisher,
    PublisherPayload,
    PublisherResult,
)
from agents.publication_bus.publisher_kit.legal_name_guard import (
    LegalNameLeak,
    assert_no_leak,
)
from agents.publication_bus.publisher_kit.refused import (
    REFUSED_PUBLISHER_CLASSES,
    AlphaXivCommentsRefusedPublisher,
    BandcampRefusedPublisher,
    CrossrefEventDataRefusedPublisher,
    DiscogsRefusedPublisher,
    DiscordWebhookRefusedPublisher,
    GitHubDiscussionsRefusedPublisher,
    LinkedInRefusedPublisher,
    RedditRefusedPublisher,
    RefusedPublisher,
    RymRefusedPublisher,
    SubstackRefusedPublisher,
    TwitterRefusedPublisher,
    WikipediaAutoEditRefusedPublisher,
    WiseDirectDebitRefusedPublisher,
)

__all__ = [
    "AllowlistGate",
    "AllowlistViolation",
    "AlphaXivCommentsRefusedPublisher",
    "BandcampRefusedPublisher",
    "CrossrefEventDataRefusedPublisher",
    "DiscogsRefusedPublisher",
    "DiscordWebhookRefusedPublisher",
    "GitHubDiscussionsRefusedPublisher",
    "LinkedInRefusedPublisher",
    "LegalNameLeak",
    "Publisher",
    "PublisherPayload",
    "PublisherResult",
    "REFUSED_PUBLISHER_CLASSES",
    "RedditRefusedPublisher",
    "RefusedPublisher",
    "RymRefusedPublisher",
    "SubstackRefusedPublisher",
    "TwitterRefusedPublisher",
    "WikipediaAutoEditRefusedPublisher",
    "WiseDirectDebitRefusedPublisher",
    "assert_no_leak",
]
