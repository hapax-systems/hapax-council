"""Self-federating subscription surface.

Per cc-task ``cold-contact-activitypub-rss-self-federate``. The
surface inverts the cold-contact model: rather than Hapax pushing
notifications to named candidates, the discovery surface is open
(omg.lol weblog RSS feed) and consumers self-subscribe. Hapax's role
is to keep the feed valid, discoverable, and properly cross-linked
to the Zenodo concept-DOI graph.

Phase 1: RSS validity + DOI cross-link verification (this module).
Phase 2: Bridgy Fed activation for ActivityPub bridging (deferred
until operator decision per cc-task design).
"""
