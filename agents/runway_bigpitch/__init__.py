"""Runway Big Pitch contest orchestration agent.

Reads a prompt brief, calls Gen-3 (gen3a_turbo by default), polls
until terminal, downloads the resulting video. Submission is via
social-media hashtag (#RunwayBigPitchContest) — handled by
publication_bus surfaces in a follow-up phase.
"""
