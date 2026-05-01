"""YouTube channel-level metadata autonomy (ytb-011).

Phase 1 (this module): trailer rotator. Subscribes to
``broadcast_rotated`` events on
``/dev/shm/hapax-broadcast/events.jsonl`` and updates the channel's
``unsubscribedTrailer`` to the new live broadcast video so non-
subscribers visiting the channel home see the currently-live stream.
Phase 1 is itself NOT-LIVE (credential_blocked) — see
``docs/governance/channel-trailer-status.md``.

Phase 2 (DEFERRED — see ``docs/governance/channel-sections-status.md``):
sections manager that maintains 3 channel sections (Currently live /
Recent research segments / Playlists by topic). The original 10-min
timer cadence is rejected by the quota math (3 × 144 × 150 = 21,600
units/day vs 10,000-unit daily quota); the implementing PR must
default to a content-change gate above the API with a ≥ 1h fallback
heartbeat.

Four concrete blockers gate Phase 2:
  1. No ``channel_section.candidate`` event producer exists yet
     (canonical event type is defined; nothing emits one).
  2. Phase 1 trailer rotator must be live first (Phase 2 must not
     stack onto an unverified Phase 1).
  3. OAuth ``youtube.force-ssl`` scope + ``YOUTUBE_CHANNEL_ID`` —
     same physical credential gate as Phase 1.
  4. Quota math: 10-min cadence is unbookable; redesign to
     content-change gate + ≥ 1h heartbeat.

When all four resolve, the follow-up PR ships
``agents/channel_metadata/sections_manager.py`` mirroring the
trailer-rotator shape but consuming ``channel_section.candidate``
events from the canonical public-event bus
(``/dev/shm/hapax-public-events/events.jsonl``).
"""
