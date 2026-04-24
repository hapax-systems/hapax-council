"""YouTube broadcast boundary orchestrator.

Rotates the operator's 24/7 livestream broadcast resource on a ~11h
cadence so YouTube doesn't drop the VOD past the 12h archive cap.
RTMP ingest is unchanged across rotations; only the broadcast resource
cycles. See ``docs/superpowers/specs/2026-04-23-vod-boundary-orchestrator-spec.md``
or the ytb-007 cc-task for full design.
"""
