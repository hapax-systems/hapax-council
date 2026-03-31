"""Tests for Traum responsive grounding act directives."""

from __future__ import annotations

import unittest

from agents.hapax_daimonion.grounding_ledger import GroundingLedger


class TestResponsiveDirectives(unittest.TestCase):
    def test_pending_produces_request_acknowledge(self):
        """PENDING state (turn 2+) should produce check-understanding directive."""
        ledger = GroundingLedger()
        ledger.add_du(turn=1, summary="initial point")
        ledger.add_du(turn=2, summary="second point")
        directive = ledger.grounding_directive()
        assert "confirm" in directive.lower() or "check" in directive.lower()

    def test_repair_1_produces_acknowledge_plus_repair(self):
        """REPAIR-1 should acknowledge then rephrase."""
        ledger = GroundingLedger()
        ledger.add_du(turn=1, summary="test point")
        ledger.update_from_acceptance("CLARIFY")
        directive = ledger.grounding_directive()
        assert "acknowledge" in directive.lower()
        assert "rephrase" in directive.lower()

    def test_repair_2_produces_request_repair(self):
        """REPAIR-2 should ask what isn't clear."""
        ledger = GroundingLedger()
        ledger.add_du(turn=1, summary="test point")
        ledger.update_from_acceptance("CLARIFY")
        ledger.update_from_acceptance("CLARIFY")
        directive = ledger.grounding_directive()
        assert "what" in directive.lower() and "clear" in directive.lower()

    def test_contested_produces_acknowledge(self):
        """CONTESTED should acknowledge disagreement."""
        ledger = GroundingLedger()
        ledger.add_du(turn=1, summary="test point")
        ledger.update_from_acceptance("REJECT")
        directive = ledger.grounding_directive()
        assert "acknowledge" in directive.lower()

    def test_grounded_consecutive_does_not_revisit(self):
        """Consecutive GROUNDED DUs should not revisit grounded content."""
        ledger = GroundingLedger()
        ledger.add_du(turn=1, summary="point A")
        ledger.update_from_acceptance("ACCEPT")
        ledger.add_du(turn=2, summary="point B")
        ledger.update_from_acceptance("ACCEPT")
        directive = ledger.grounding_directive()
        assert "revisit" in directive.lower() or "new" in directive.lower()

    def test_abandoned_produces_move_on(self):
        """ABANDONED should move on."""
        ledger = GroundingLedger()
        ledger.add_du(turn=1, summary="test point")
        ledger.update_from_acceptance("CLARIFY")
        ledger.update_from_acceptance("CLARIFY")
        ledger.update_from_acceptance("CLARIFY")
        directive = ledger.grounding_directive()
        assert "move on" in directive.lower() or "abandon" in directive.lower()


if __name__ == "__main__":
    unittest.main()
