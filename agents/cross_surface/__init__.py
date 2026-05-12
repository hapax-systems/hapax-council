"""Cross-surface federation (ytb-010).

Five publishing adapters live in this package:

- :mod:`agents.cross_surface.discord_webhook` — Discord webhook poster (PR #1319).
- :mod:`agents.cross_surface.bluesky_post` — bus-backed Bluesky public-event poster.
- :mod:`agents.cross_surface.mastodon_post` — bus-backed Mastodon public-event poster.
- :mod:`agents.cross_surface.arena_post` — Are.na PAT/channels client (PR #1953).
- :mod:`agents.cross_surface.alphaxiv_post` — alphaXiv comments adapter.

Bluesky / Mastodon / Arena consume canonical ``ResearchVehiclePublicEvent``
records from ``/dev/shm/hapax-public-events/events.jsonl``. Discord remains
a bounded legacy ``broadcast_rotated`` consumer until its public-event
adapter task lands. alphaXiv is a comment-side surface (not a livestream
fanout target) and runs against arXiv-deposited artefact threads. All
cross-surface adapters use
``agents.metadata_composer.composer.compose_metadata(scope="cross_surface")``
to draft the post text. Per-surface allowlist contracts at
``axioms/contracts/publication/{discord-webhook,bluesky-post,mastodon-post,arena-post,alphaxiv-comments}.yaml``
gate the write.
"""
