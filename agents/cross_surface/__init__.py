"""Cross-surface federation (ytb-010).

Phase 1: Discord webhook poster (PR #1319).
Phase 2: Bluesky client (atproto, PR #1320).
Phase 3 (this module): Mastodon client (Mastodon.py).

All three surfaces consume `broadcast_rotated` events from
``/dev/shm/hapax-broadcast/events.jsonl`` and use
``agents.metadata_composer.composer.compose_metadata(scope="cross_surface")``
to draft the post text. Per-surface allowlist contracts at
``axioms/contracts/publication/{discord-webhook,bluesky-post,mastodon-post}.yaml``
gate the write.
"""
