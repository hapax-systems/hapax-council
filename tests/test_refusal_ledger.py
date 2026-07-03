"""Unit tests for the dispatch refusal ledger.

M4 2e (re-arm prevention): ``invalidate_by_reason_predicate`` wipes only the
class of refusals whose external cause has cleared (e.g. stale route-policy
receipts), so a fresh receipt re-attempts immediately instead of waiting out the
up-to-1h backoff.
"""

from __future__ import annotations

import unittest

from agents.coordinator.refusal_ledger import DispatchRefusalLedger


def _is_freshness(reason: str) -> bool:
    """Mirror of agents.coordinator.core._is_freshness_hold_reason for ledger tests."""
    markers = ("stale_or_unknown", "account_live_quota_receipt_absent", "cli_missing_or_unusable")
    lowered = (reason or "").lower()
    return any(m in lowered for m in markers)


class InvalidateByReasonPredicateTest(unittest.TestCase):
    """A cleared external condition wipes only its own class of refusals."""

    def test_removes_only_predicate_matching_cooled_pairs(self) -> None:
        ledger = DispatchRefusalLedger()
        now = 1000.0
        # A freshness-cooled pair (stale receipts) + an unrelated validation block.
        for _ in range(ledger.k):
            ledger.record_refusal(
                "t-fresh", "alpha", "route policy hold: stale_or_unknown", now=now
            )
            now += 1
        for _ in range(ledger.k):
            ledger.record_refusal("t-valid", "beta", "validation: schema mismatch", now=now)
            now += 1
        self.assertTrue(ledger.is_cooled_down("t-fresh", "alpha", now=now))
        self.assertTrue(ledger.is_cooled_down("t-valid", "beta", now=now))

        wiped = ledger.invalidate_by_reason_predicate(_is_freshness, now=now)

        self.assertEqual(wiped, 1)
        # The freshness pair is gone (re-dispatchable); the validation pair stays cooled.
        self.assertFalse(ledger.is_cooled_down("t-fresh", "alpha", now=now))
        self.assertTrue(ledger.is_cooled_down("t-valid", "beta", now=now))

    def test_no_match_returns_zero_and_leaves_ledger_untouched(self) -> None:
        ledger = DispatchRefusalLedger()
        now = 1000.0
        for _ in range(ledger.k):
            ledger.record_refusal("t", "alpha", "validation: x", now=now)
        wiped = ledger.invalidate_by_reason_predicate(_is_freshness, now=now)
        self.assertEqual(wiped, 0)
        self.assertTrue(ledger.is_cooled_down("t", "alpha", now=now))

    def test_removes_non_cooled_matching_entries_too(self) -> None:
        """A predicate match means the reason is stale regardless of cooldown state."""
        ledger = DispatchRefusalLedger()
        # One freshness refusal — below K, not yet cooled.
        ledger.record_refusal("t", "alpha", "route policy hold: stale_or_unknown", now=1000.0)
        self.assertFalse(ledger.is_cooled_down("t", "alpha", now=1001.0))
        wiped = ledger.invalidate_by_reason_predicate(_is_freshness, now=1001.0)
        self.assertEqual(wiped, 1)
        self.assertFalse(ledger.is_cooled_down("t", "alpha", now=1001.0))


class FreshnessPredicateWiringTest(unittest.TestCase):
    """The coordinator's freshness-reason predicate mirrors dispatcher_policy holds."""

    def test_is_freshness_hold_reason_classifies_route_policy_holds(self) -> None:
        from agents.coordinator.core import _is_freshness_hold_reason

        for reason in (
            "BLOCKED: route policy hold: resource_telemetry_stale_or_unknown; "
            "quota_telemetry_stale_or_unknown",
            "route policy hold: account_live_quota_receipt_absent",
            "capability blocked: cli_missing_or_unusable",
        ):
            self.assertTrue(_is_freshness_hold_reason(reason), reason)
        # Non-freshness refusals must not match.
        for reason in (
            "validation: schema mismatch",
            "not authorized",
            "route policy refuse: timeout",
        ):
            self.assertFalse(_is_freshness_hold_reason(reason), reason)


if __name__ == "__main__":
    unittest.main()
