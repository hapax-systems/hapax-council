"""Tests for ``agents.operator_awareness.public_filter``."""

from __future__ import annotations

from datetime import UTC, datetime

from agents.operator_awareness.public_filter import public_filter
from agents.operator_awareness.state import (
    AwarenessState,
    HealthBlock,
    MarketingOutreachBlock,
    RefusalEvent,
    StreamBlock,
)


def _now() -> datetime:
    return datetime.now(UTC)


class TestPublicFilter:
    def test_redacts_non_public_block(self):
        state = AwarenessState(
            timestamp=_now(),
            health_system=HealthBlock(
                public=False,
                overall_status="critical",
                failed_units=3,
            ),
        )
        out = public_filter(state)
        assert out.health_system.overall_status == "unknown"
        assert out.health_system.failed_units == 0

    def test_passes_public_block_through(self):
        state = AwarenessState(
            timestamp=_now(),
            stream=StreamBlock(public=True, live=True, chronicle_events_5min=42),
        )
        out = public_filter(state)
        assert out.stream.live is True
        assert out.stream.chronicle_events_5min == 42

    def test_refusals_always_pass_through(self):
        """Refusals are public-by-design — never redacted."""
        ev = RefusalEvent(timestamp=_now(), surface="x", reason="y")
        state = AwarenessState(timestamp=_now(), refusals_recent=[ev])
        out = public_filter(state)
        assert len(out.refusals_recent) == 1
        assert out.refusals_recent[0].surface == "x"

    def test_mixed_public_state(self):
        state = AwarenessState(
            timestamp=_now(),
            stream=StreamBlock(public=True, live=True),
            health_system=HealthBlock(public=False, overall_status="critical"),
            marketing_outreach=MarketingOutreachBlock(public=False, pending_count=5),
        )
        out = public_filter(state)
        assert out.stream.live is True  # public passes
        assert out.health_system.overall_status == "unknown"  # private redacted
        assert out.marketing_outreach.pending_count == 0  # private redacted

    def test_returns_new_instance(self):
        state = AwarenessState(
            timestamp=_now(),
            health_system=HealthBlock(public=False, failed_units=3),
        )
        out = public_filter(state)
        # Original unchanged (frozen=True anyway).
        assert state.health_system.failed_units == 3
        assert out is not state

    def test_default_blocks_redacted(self):
        """All 12 default sub-blocks default public=False → all redacted."""
        state = AwarenessState(timestamp=_now())
        out = public_filter(state)
        # Every block is the type's default — redacted to itself effectively.
        # Just confirm the filter ran without crashing on default state.
        assert out.health_system.overall_status == "unknown"
        assert out.timestamp == state.timestamp
