"""Tests for MC desk_allows_throw veto driven by desk_activity.

Validates that the desk_allows_throw veto in build_mc_veto_chain blocks
throws during scratching/typing, allows during drumming/tapping/idle,
and degrades gracefully when desk_activity is missing from samples.

Self-contained, unittest.mock only, asyncio_mode="auto".
"""

from __future__ import annotations

import unittest

from agents.hapax_daimonion.governance import FusedContext
from agents.hapax_daimonion.mc_governance import build_mc_veto_chain
from agents.hapax_daimonion.primitives import Stamped


def _make_ctx(desk_activity: str | None = None) -> FusedContext:
    """Build a minimal FusedContext for testing the desk_allows_throw veto."""
    samples: dict[str, Stamped] = {}
    if desk_activity is not None:
        samples["desk_activity"] = Stamped(desk_activity, 1.0)
    return FusedContext(
        trigger_time=1.0,
        trigger_value=None,
        samples=samples,
        min_watermark=1.0,
    )


class TestDeskAllowsThrowVeto(unittest.TestCase):
    """desk_allows_throw veto predicate tests."""

    def setUp(self) -> None:
        self.chain = build_mc_veto_chain()
        self.veto = next(v for v in self.chain._vetoes if v.name == "desk_allows_throw")

    def test_scratching_blocks(self) -> None:
        ctx = _make_ctx("scratching")
        self.assertFalse(self.veto.predicate(ctx))

    def test_typing_blocks(self) -> None:
        ctx = _make_ctx("typing")
        self.assertFalse(self.veto.predicate(ctx))

    def test_drumming_allows(self) -> None:
        ctx = _make_ctx("drumming")
        self.assertTrue(self.veto.predicate(ctx))

    def test_tapping_allows(self) -> None:
        ctx = _make_ctx("tapping")
        self.assertTrue(self.veto.predicate(ctx))

    def test_idle_allows(self) -> None:
        ctx = _make_ctx("idle")
        self.assertTrue(self.veto.predicate(ctx))

    def test_missing_desk_activity_allows(self) -> None:
        ctx = _make_ctx()  # no desk_activity in samples
        self.assertTrue(self.veto.predicate(ctx))


if __name__ == "__main__":
    unittest.main()
