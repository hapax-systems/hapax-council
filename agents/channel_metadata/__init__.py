"""YouTube channel-level metadata autonomy (ytb-011).

Phase 1 (this module): trailer rotator. Subscribes to
``broadcast_rotated`` events on
``/dev/shm/hapax-broadcast/events.jsonl`` and updates the channel's
``unsubscribedTrailer`` to the new live broadcast video so non-
subscribers visiting the channel home see the currently-live stream.

Phase 2 (deferred): sections manager — 10-min timer with digest-diff
that maintains 3 channel sections (Currently live / Recent research
segments / Playlists by topic).
"""
