"""Discourse sensing producer, slice 1.

A read-only sensor: it polls public sources (Bluesky AppView author feeds,
RSS feeds, Hacker News search) on a per-source cadence and records each new
item once to the desk's scan intake. It performs no outward act of any kind:
it never posts, replies, follows, likes or mentions.
"""

from agents.discourse_sensing.run import run_once

__all__ = ["run_once"]
