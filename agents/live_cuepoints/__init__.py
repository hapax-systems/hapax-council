"""Live cuepoint chapter marker daemon (ytb-004).

Tails ``/dev/shm/hapax-broadcast/events.jsonl`` (written by the
broadcast orchestrator, ytb-007) and emits ``liveBroadcasts.cuepoint``
calls on chapter-worthy events — primarily ``broadcast_rotated`` at
~11h segment boundaries. Zero-duration cuepoints render scrub-bar
markers on the live DVR and the eventual VOD without triggering an ad
break.

Default DISABLED via ``HAPAX_LIVE_CUEPOINTS_ENABLED`` until operator
runs the one-shot empirical verification per beta's R3 spec.
"""
