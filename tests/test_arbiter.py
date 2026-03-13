"""Tests for ResourceClaim and ResourceArbiter."""

from __future__ import annotations

import unittest

from agents.hapax_voice.arbiter import ResourceArbiter, ResourceClaim


def _priorities() -> dict[tuple[str, str], int]:
    return {
        ("audio_output", "mc"): 50,
        ("audio_output", "conversation"): 100,
        ("audio_output", "tts"): 30,
        ("obs_scene", "obs"): 70,
        ("obs_scene", "mc"): 40,
    }


def _claim(
    resource: str = "audio_output",
    chain: str = "mc",
    priority: int = 50,
    command: str = "vocal_throw",
    hold_until: float = 0.0,
    max_hold_s: float = 30.0,
    created_at: float = 1.0,
) -> ResourceClaim:
    return ResourceClaim(
        resource=resource,
        chain=chain,
        priority=priority,
        command=command,
        hold_until=hold_until,
        max_hold_s=max_hold_s,
        created_at=created_at,
    )


class TestResourceClaim(unittest.TestCase):
    def test_frozen(self):
        rc = _claim()
        with self.assertRaises(AttributeError):
            rc.resource = "other"  # type: ignore[misc]

    def test_fields(self):
        rc = _claim(resource="audio_output", chain="mc", priority=50)
        self.assertEqual(rc.resource, "audio_output")
        self.assertEqual(rc.chain, "mc")
        self.assertEqual(rc.priority, 50)


class TestResourceArbiterClaim(unittest.TestCase):
    def test_valid_claim(self):
        arb = ResourceArbiter(_priorities())
        arb.claim(_claim(resource="audio_output", chain="mc", priority=50))
        self.assertIsNotNone(arb.resolve("audio_output"))

    def test_unconfigured_pair_raises(self):
        arb = ResourceArbiter(_priorities())
        with self.assertRaises(ValueError):
            arb.claim(_claim(resource="audio_output", chain="unknown", priority=50))

    def test_wrong_priority_raises(self):
        arb = ResourceArbiter(_priorities())
        with self.assertRaises(ValueError):
            arb.claim(_claim(resource="audio_output", chain="mc", priority=999))

    def test_replaces_existing_same_chain(self):
        arb = ResourceArbiter(_priorities())
        arb.claim(_claim(resource="audio_output", chain="mc", priority=50, command="ad_lib"))
        arb.claim(_claim(resource="audio_output", chain="mc", priority=50, command="vocal_throw"))
        winner = arb.resolve("audio_output")
        self.assertEqual(winner.command, "vocal_throw")


class TestResourceArbiterResolve(unittest.TestCase):
    def test_highest_priority_wins(self):
        arb = ResourceArbiter(_priorities())
        arb.claim(_claim(resource="audio_output", chain="mc", priority=50, created_at=1.0))
        arb.claim(
            _claim(
                resource="audio_output", chain="conversation", priority=100, created_at=2.0
            )
        )
        winner = arb.resolve("audio_output")
        self.assertEqual(winner.chain, "conversation")

    def test_fifo_on_equal_priority(self):
        # Need two chains with same priority for this test
        priorities = {("audio_output", "a"): 50, ("audio_output", "b"): 50}
        arb = ResourceArbiter(priorities)
        arb.claim(_claim(resource="audio_output", chain="a", priority=50, created_at=1.0))
        arb.claim(_claim(resource="audio_output", chain="b", priority=50, created_at=2.0))
        winner = arb.resolve("audio_output")
        self.assertEqual(winner.chain, "a")  # earlier created_at

    def test_empty_resource_returns_none(self):
        arb = ResourceArbiter(_priorities())
        self.assertIsNone(arb.resolve("audio_output"))

    def test_unknown_resource_returns_none(self):
        arb = ResourceArbiter(_priorities())
        self.assertIsNone(arb.resolve("nonexistent"))


class TestResourceArbiterRelease(unittest.TestCase):
    def test_release_removes_claim(self):
        arb = ResourceArbiter(_priorities())
        arb.claim(_claim(resource="audio_output", chain="mc", priority=50))
        arb.release("audio_output", "mc")
        self.assertIsNone(arb.resolve("audio_output"))

    def test_release_unblocks_lower_priority(self):
        arb = ResourceArbiter(_priorities())
        arb.claim(_claim(resource="audio_output", chain="tts", priority=30, created_at=1.0))
        arb.claim(
            _claim(
                resource="audio_output", chain="conversation", priority=100, created_at=2.0
            )
        )
        self.assertEqual(arb.resolve("audio_output").chain, "conversation")
        arb.release("audio_output", "conversation")
        self.assertEqual(arb.resolve("audio_output").chain, "tts")

    def test_release_nonexistent_no_error(self):
        arb = ResourceArbiter(_priorities())
        arb.release("audio_output", "mc")  # should not raise


class TestResourceArbiterDrainWinners(unittest.TestCase):
    def test_one_winner_per_resource(self):
        arb = ResourceArbiter(_priorities())
        arb.claim(_claim(resource="audio_output", chain="mc", priority=50, created_at=1.0))
        arb.claim(
            _claim(
                resource="audio_output", chain="conversation", priority=100, created_at=2.0
            )
        )
        arb.claim(_claim(resource="obs_scene", chain="obs", priority=70, created_at=1.0))
        winners = arb.drain_winners(now=5.0)
        resources = {w.resource for w in winners}
        self.assertEqual(resources, {"audio_output", "obs_scene"})

    def test_one_shot_claims_removed_after_drain(self):
        arb = ResourceArbiter(_priorities())
        arb.claim(
            _claim(
                resource="audio_output", chain="mc", priority=50, hold_until=0.0, created_at=1.0
            )
        )
        winners = arb.drain_winners(now=2.0)
        self.assertEqual(len(winners), 1)
        # After drain, one-shot should be gone
        self.assertIsNone(arb.resolve("audio_output"))

    def test_held_claims_survive_drain(self):
        arb = ResourceArbiter(_priorities())
        arb.claim(
            _claim(
                resource="audio_output",
                chain="mc",
                priority=50,
                hold_until=10.0,
                created_at=1.0,
            )
        )
        arb.drain_winners(now=2.0)
        self.assertIsNotNone(arb.resolve("audio_output"))

    def test_gc_expired_holds(self):
        arb = ResourceArbiter(_priorities())
        arb.claim(
            _claim(
                resource="audio_output",
                chain="mc",
                priority=50,
                hold_until=5.0,
                max_hold_s=2.0,
                created_at=1.0,
            )
        )
        # At now=4.0, age is 3.0 > max_hold_s=2.0 → GC'd
        winners = arb.drain_winners(now=4.0)
        self.assertEqual(len(winners), 0)
        self.assertIsNone(arb.resolve("audio_output"))

    def test_held_claim_blocks_lower_priority(self):
        arb = ResourceArbiter(_priorities())
        arb.claim(
            _claim(
                resource="audio_output",
                chain="conversation",
                priority=100,
                hold_until=10.0,
                created_at=1.0,
            )
        )
        arb.claim(
            _claim(
                resource="audio_output", chain="mc", priority=50, hold_until=0.0, created_at=2.0
            )
        )
        winners = arb.drain_winners(now=3.0)
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0].chain, "conversation")

    def test_multi_resource_independence(self):
        arb = ResourceArbiter(_priorities())
        arb.claim(_claim(resource="audio_output", chain="mc", priority=50, created_at=1.0))
        arb.claim(_claim(resource="obs_scene", chain="obs", priority=70, created_at=1.0))
        winners = arb.drain_winners(now=2.0)
        resource_chains = {w.resource: w.chain for w in winners}
        self.assertEqual(resource_chains["audio_output"], "mc")
        self.assertEqual(resource_chains["obs_scene"], "obs")

    def test_empty_arbiter_drains_empty(self):
        arb = ResourceArbiter(_priorities())
        winners = arb.drain_winners(now=1.0)
        self.assertEqual(winners, [])

    def test_release_then_lower_priority_dispatches(self):
        arb = ResourceArbiter(_priorities())
        arb.claim(
            _claim(
                resource="audio_output",
                chain="conversation",
                priority=100,
                hold_until=5.0,
                created_at=1.0,
            )
        )
        arb.claim(
            _claim(
                resource="audio_output", chain="mc", priority=50, hold_until=5.0, created_at=2.0
            )
        )
        # Conversation holds
        winners = arb.drain_winners(now=3.0)
        self.assertEqual(winners[0].chain, "conversation")
        # Release conversation
        arb.release("audio_output", "conversation")
        winners = arb.drain_winners(now=4.0)
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0].chain, "mc")


class TestResourceArbiterActiveClaims(unittest.TestCase):
    def test_active_claims_snapshot(self):
        arb = ResourceArbiter(_priorities())
        arb.claim(_claim(resource="audio_output", chain="mc", priority=50))
        snapshot = arb.active_claims
        self.assertIn("audio_output", snapshot)
        self.assertEqual(len(snapshot["audio_output"]), 1)

    def test_snapshot_is_copy(self):
        arb = ResourceArbiter(_priorities())
        arb.claim(_claim(resource="audio_output", chain="mc", priority=50))
        snapshot = arb.active_claims
        snapshot["audio_output"].clear()
        # Original should be unaffected
        self.assertIsNotNone(arb.resolve("audio_output"))


if __name__ == "__main__":
    unittest.main()
