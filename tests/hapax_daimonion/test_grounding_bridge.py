"""Tests for CPAL grounding bridge."""

from unittest.mock import MagicMock

from agents.hapax_daimonion.cpal.grounding_bridge import GroundingBridge, GroundingState


class TestGroundingStateDefaults:
    def test_no_ledger_returns_healthy_defaults(self):
        bridge = GroundingBridge(ledger=None)
        state = bridge.snapshot()
        assert state.gqi == 0.8
        assert state.ungrounded_du_count == 0
        assert state.repair_rate == 0.0
        assert state.total_dus == 0

    def test_state_is_frozen(self):
        state = GroundingState(
            gqi=0.5, ungrounded_du_count=1, repair_rate=0.1, total_dus=3, grounded_count=2
        )
        try:
            state.gqi = 0.9
            raise AssertionError("Should be frozen")
        except (AttributeError, TypeError):
            pass


class TestGroundingBridgeWithLedger:
    def _make_du(self, state_value: str, repair_count: int = 0):
        du = MagicMock()
        du.state.value = state_value
        du.repair_count = repair_count
        return du

    def test_reads_gqi_from_ledger(self):
        ledger = MagicMock()
        ledger.compute_gqi.return_value = 0.65
        ledger._units = []

        bridge = GroundingBridge(ledger=ledger)
        state = bridge.snapshot()
        assert state.gqi == 0.65

    def test_counts_ungrounded_dus(self):
        ledger = MagicMock()
        ledger.compute_gqi.return_value = 0.5
        ledger._units = [
            self._make_du("PENDING"),
            self._make_du("GROUNDED"),
            self._make_du("UNGROUNDED"),
            self._make_du("REPAIR-1"),
            self._make_du("GROUNDED"),
        ]

        bridge = GroundingBridge(ledger=ledger)
        state = bridge.snapshot()
        assert state.ungrounded_du_count == 3  # PENDING + UNGROUNDED + REPAIR-1
        assert state.grounded_count == 2
        assert state.total_dus == 5

    def test_computes_repair_rate(self):
        ledger = MagicMock()
        ledger.compute_gqi.return_value = 0.4
        ledger._units = [
            self._make_du("GROUNDED", repair_count=1),  # was repaired
            self._make_du("GROUNDED", repair_count=0),  # clean
            self._make_du("REPAIR-1", repair_count=1),  # in repair
            self._make_du("GROUNDED", repair_count=0),  # clean
        ]

        bridge = GroundingBridge(ledger=ledger)
        state = bridge.snapshot()
        assert state.repair_rate == 0.5  # 2 out of 4 had repairs

    def test_empty_ledger(self):
        ledger = MagicMock()
        ledger.compute_gqi.return_value = 0.8
        ledger._units = []

        bridge = GroundingBridge(ledger=ledger)
        state = bridge.snapshot()
        assert state.total_dus == 0
        assert state.repair_rate == 0.0
        assert state.ungrounded_du_count == 0

    def test_record_outcome_is_noop(self):
        bridge = GroundingBridge(ledger=None)
        bridge.record_outcome(success=True)  # should not raise
        bridge.record_outcome(success=False)
