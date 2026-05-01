"""Cross-surface federation (ytb-010).

Phase 1: Discord webhook poster (PR #1319).
Phase 2: Bluesky client (atproto, PR #1320).
Phase 3: Mastodon client (Mastodon.py).

Bluesky and Mastodon consume canonical ``ResearchVehiclePublicEvent`` records
from ``/dev/shm/hapax-public-events/events.jsonl``. Discord remains a bounded
legacy ``broadcast_rotated`` consumer until its public-event adapter task lands.
All cross-surface adapters use
``agents.metadata_composer.composer.compose_metadata(scope="cross_surface")``
to draft the post text. Per-surface allowlist contracts at
``axioms/contracts/publication/{discord-webhook,bluesky-post,mastodon-post}.yaml``
gate the write.
"""
