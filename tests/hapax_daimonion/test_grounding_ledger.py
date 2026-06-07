"""Tests for GroundingLedger: DU state machine, concern-aware thresholds, GQI, effort."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.research


class TestDUStateTransitions:
    def _make_ledger(self):
        from agents.hapax_daimonion.grounding_ledger import GroundingLedger

        ledger = GroundingLedger()
        ledger.add_du(1, "initial statement")
        return ledger

    def test_accept_grounds(self):
        ledger = self._make_ledger()
        strategy = ledger.update_from_acceptance("ACCEPT")
        assert strategy == "advance"
        assert ledger.last_du_state == "GROUNDED"

    def test_clarify_triggers_repair_1(self):
        ledger = self._make_ledger()
        strategy = ledger.update_from_acceptance("CLARIFY")
        assert strategy == "rephrase"
        assert ledger.last_du_state == "REPAIR-1"

    def test_double_clarify_triggers_repair_2(self):
        ledger = self._make_ledger()
        ledger.update_from_acceptance("CLARIFY")  # du1 → REPAIR-1
        # Second CLARIFY on same DU (operator still confused after rephrase)
        strategy = ledger.update_from_acceptance("CLARIFY")
        assert strategy == "elaborate"
        assert ledger.last_du_state == "REPAIR-2"

    def test_triple_clarify_abandons(self):
        ledger = self._make_ledger()
        ledger.update_from_acceptance("CLARIFY")  # → REPAIR-1
        ledger.update_from_acceptance("CLARIFY")  # → REPAIR-2
        strategy = ledger.update_from_acceptance("CLARIFY")  # → ABANDONED
        assert strategy == "move_on"
        assert ledger.last_du_state == "ABANDONED"

    def test_reject_contests(self):
        ledger = self._make_ledger()
        strategy = ledger.update_from_acceptance("REJECT")
        assert strategy == "present_reasoning"
        assert ledger.last_du_state == "CONTESTED"

    def test_double_reject_abandons(self):
        ledger = self._make_ledger()
        ledger.update_from_acceptance("REJECT")  # → CONTESTED
        # Second reject on same DU (operator still disagrees after reasoning)
        strategy = ledger.update_from_acceptance("REJECT")
        assert strategy == "move_on"
        assert ledger.last_du_state == "ABANDONED"

    def test_ignore_low_concern_grounds(self):
        ledger = self._make_ledger()
        strategy = ledger.update_from_acceptance("IGNORE", concern_overlap=0.1)
        assert strategy == "advance"
        assert ledger.last_du_state == "GROUNDED"

    def test_ignore_high_concern_ungrounds(self):
        ledger = self._make_ledger()
        strategy = ledger.update_from_acceptance("IGNORE", concern_overlap=0.8)
        assert strategy == "ungrounded_caution"
        assert ledger.last_du_state == "UNGROUNDED"

    def test_no_du_returns_neutral(self):
        from agents.hapax_daimonion.grounding_ledger import GroundingLedger

        ledger = GroundingLedger()
        strategy = ledger.update_from_acceptance("ACCEPT")
        assert strategy == "neutral"


class TestConcernAwareThresholds:
    def _make_ledger_with_history(self, accepts=5, rejects=0):
        from agents.hapax_daimonion.grounding_ledger import GroundingLedger

        ledger = GroundingLedger()
        for i in range(accepts):
            ledger.add_du(i, f"statement {i}")
            ledger.update_from_acceptance("ACCEPT")
        for i in range(rejects):
            ledger.add_du(accepts + i, f"statement {accepts + i}")
            ledger.update_from_acceptance("REJECT")
        ledger.add_du(accepts + rejects, "test statement")
        return ledger

    def test_high_concern_low_gqi_tight_threshold(self):
        from agents.hapax_daimonion.grounding_ledger import GroundingLedger

        ledger = GroundingLedger()
        # Simulate low GQI by feeding rejects
        for i in range(5):
            ledger.add_du(i, f"s{i}")
            ledger.update_from_acceptance("REJECT")
        ledger.add_du(5, "high concern test")
        # CLARIFY (0.7) should NOT meet threshold (0.9) for high concern + low GQI
        strategy = ledger.update_from_acceptance("CLARIFY", concern_overlap=0.8)
        assert strategy == "rephrase"  # still triggers repair, not grounded

    def test_low_concern_high_gqi_loose_threshold(self):
        ledger = self._make_ledger_with_history(accepts=5)
        # IGNORE (0.3) should meet threshold (0.3) for low concern + high GQI
        strategy = ledger.update_from_acceptance("IGNORE", concern_overlap=0.1)
        assert strategy == "advance"


class TestGQI:
    def test_cold_start_neutral(self):
        from agents.hapax_daimonion.grounding_ledger import GroundingLedger

        ledger = GroundingLedger()
        gqi = ledger.compute_gqi()
        assert 0.4 <= gqi <= 0.6  # neutral cold start

    def test_all_accepts_high_gqi(self):
        from agents.hapax_daimonion.grounding_ledger import GroundingLedger

        ledger = GroundingLedger()
        for i in range(10):
            ledger.add_du(i, f"s{i}")
            ledger.update_from_acceptance("ACCEPT")
        gqi = ledger.compute_gqi()
        assert gqi > 0.7

    def test_all_rejects_low_gqi(self):
        from agents.hapax_daimonion.grounding_ledger import GroundingLedger

        ledger = GroundingLedger()
        for i in range(10):
            ledger.add_du(i, f"s{i}")
            ledger.update_from_acceptance("REJECT")
        gqi = ledger.compute_gqi()
        assert gqi < 0.3

    def test_gqi_bounded(self):
        from agents.hapax_daimonion.grounding_ledger import GroundingLedger

        ledger = GroundingLedger()
        for i in range(20):
            ledger.add_du(i, f"s{i}")
            ledger.update_from_acceptance("ACCEPT")
        assert 0.0 <= ledger.compute_gqi() <= 1.0


class TestEffortCalibration:
    # No-presets: word_limit is a continuum (no 23/33/45 buckets) and the GQI
    # discount is ledger-fit (no fixed 0.6). These tests assert qualitative
    # monotonicity, not bucket equality.

    def test_high_activation_low_gqi_yields_more_words_than_low_activation_high_gqi(self):
        from agents.hapax_daimonion.grounding_ledger import GroundingLedger

        poorly_grounded = GroundingLedger()
        for i in range(5):
            poorly_grounded.add_du(i, f"s{i}")
            poorly_grounded.update_from_acceptance("REJECT")
        hi = poorly_grounded.effort_calibration(activation=0.9)

        well_grounded = GroundingLedger()
        for i in range(5):
            well_grounded.add_du(i, f"s{i}")
            well_grounded.update_from_acceptance("ACCEPT")
        well_grounded.effort_calibration(activation=0.2)  # allow the slew to settle
        lo = well_grounded.effort_calibration(activation=0.2)

        # complex + poorly grounded ⇒ strictly more effort/words than simple + well grounded
        assert hi.word_limit > lo.word_limit
        assert hi.effort_score > lo.effort_score

    def test_word_limit_is_continuum_within_envelope(self):
        from agents.hapax_daimonion.grounding_ledger import WORD_MAX, WORD_MIN, GroundingLedger

        limits = set()
        for activation in (0.0, 0.25, 0.5, 0.75, 1.0):
            e = GroundingLedger().effort_calibration(activation=activation)
            assert WORD_MIN <= e.word_limit <= WORD_MAX
            limits.add(e.word_limit)
        # a continuum produces more than the 3 legacy bucket values
        assert len(limits) > 3

    def test_word_limit_monotonic_in_activation(self):
        from agents.hapax_daimonion.grounding_ledger import GroundingLedger

        low = GroundingLedger().effort_calibration(activation=0.1).word_limit
        high = GroundingLedger().effort_calibration(activation=0.9).word_limit
        assert high > low

    def test_deescalation_is_gradual_not_immediate(self):
        from agents.hapax_daimonion.grounding_ledger import GroundingLedger

        ledger = GroundingLedger()
        for i in range(5):
            ledger.add_du(i, f"s{i}")
            ledger.update_from_acceptance("REJECT")
        e1 = ledger.effort_calibration(activation=0.9)  # escalated

        # conditions improve; de-escalation is damped (asymmetric slew), so the
        # word limit decreases GRADUALLY over turns rather than snapping down.
        for i in range(5):
            ledger.add_du(10 + i, f"s{10 + i}")
            ledger.update_from_acceptance("ACCEPT")
        e2 = ledger.effort_calibration(activation=0.2)
        e3 = ledger.effort_calibration(activation=0.2)
        assert e1.word_limit >= e2.word_limit > e3.word_limit

    def test_escalation_is_immediate(self):
        from agents.hapax_daimonion.grounding_ledger import GroundingLedger

        ledger = GroundingLedger()
        ledger.effort_calibration(activation=0.1)  # settle low
        for i in range(5):
            ledger.add_du(i, f"s{i}")
            ledger.update_from_acceptance("REJECT")
        e = ledger.effort_calibration(activation=0.95)  # high effort
        # escalation jumps in one step (not damped)
        assert e.effort_score > 0.6

    def test_gqi_discount_is_ledger_fit_not_fixed(self):
        from agents.hapax_daimonion.grounding_ledger import GroundingLedger

        accepting = GroundingLedger()
        rejecting = GroundingLedger()
        for i in range(5):
            accepting.add_du(i, f"a{i}")
            accepting.update_from_acceptance("ACCEPT")
            rejecting.add_du(i, f"r{i}")
            rejecting.update_from_acceptance("REJECT")
        # the discount adapts to the ledger — it is not a constant 0.6
        assert accepting._gqi_discount() != rejecting._gqi_discount()

    def test_effort_score_bounded(self):
        from agents.hapax_daimonion.grounding_ledger import GroundingLedger

        ledger = GroundingLedger()
        e = ledger.effort_calibration(activation=1.0)
        assert 0.0 <= e.effort_score <= 1.0
        e = ledger.effort_calibration(activation=0.0)
        assert 0.0 <= e.effort_score <= 1.0


class TestGroundingDirective:
    def test_empty_when_no_dus(self):
        from agents.hapax_daimonion.grounding_ledger import GroundingLedger

        ledger = GroundingLedger()
        assert ledger.grounding_directive() == ""

    def test_advance_after_accept(self):
        from agents.hapax_daimonion.grounding_ledger import GroundingLedger

        ledger = GroundingLedger()
        ledger.add_du(1, "statement")
        ledger.update_from_acceptance("ACCEPT")
        directive = ledger.grounding_directive()
        assert "Grounding Directive" in directive
        assert "Advance" in directive or "advance" in directive.lower()

    def test_rephrase_after_clarify(self):
        from agents.hapax_daimonion.grounding_ledger import GroundingLedger

        ledger = GroundingLedger()
        ledger.add_du(1, "statement")
        ledger.update_from_acceptance("CLARIFY")
        directive = ledger.grounding_directive()
        assert "Rephrase" in directive or "rephrase" in directive.lower()

    def test_reasoning_after_reject(self):
        from agents.hapax_daimonion.grounding_ledger import GroundingLedger

        ledger = GroundingLedger()
        ledger.add_du(1, "statement")
        ledger.update_from_acceptance("REJECT")
        directive = ledger.grounding_directive()
        assert "reasoning" in directive.lower()

    def test_ungrounded_caution_after_high_concern_ignore(self):
        from agents.hapax_daimonion.grounding_ledger import GroundingLedger

        ledger = GroundingLedger()
        ledger.add_du(1, "important statement")
        ledger.update_from_acceptance("IGNORE", concern_overlap=0.8)
        directive = ledger.grounding_directive()
        assert "Do not build on it" in directive or "ungrounded" in directive.lower()


class TestIgnoreBranch:
    def test_low_concern_ignore_grounds(self):
        from agents.hapax_daimonion.grounding_ledger import GroundingLedger

        ledger = GroundingLedger()
        ledger.add_du(1, "test statement", concern_overlap=0.1)
        result = ledger.update_from_acceptance("IGNORE", concern_overlap=0.1)
        assert result == "advance"

    def test_high_concern_ignore_ungrounds(self):
        from agents.hapax_daimonion.grounding_ledger import GroundingLedger

        ledger = GroundingLedger()
        ledger.add_du(1, "test statement", concern_overlap=0.8)
        result = ledger.update_from_acceptance("IGNORE", concern_overlap=0.8)
        assert result == "ungrounded_caution"

    def test_medium_concern_ignore_ungrounds(self):
        from agents.hapax_daimonion.grounding_ledger import GroundingLedger

        ledger = GroundingLedger()
        ledger.add_du(1, "test statement", concern_overlap=0.5)
        result = ledger.update_from_acceptance("IGNORE", concern_overlap=0.5)
        assert result == "ungrounded_caution"


# TestEffortHoldCounter removed: the discrete-level hold-counter hysteresis it
# pinned was replaced by the asymmetric EWMA slew (no-presets continuum). The
# escalation-immediate / de-escalation-gradual behavior is now covered by
# TestEffortCalibration.test_escalation_is_immediate and
# .test_deescalation_is_gradual_not_immediate.


class TestUngroundedCount:
    def test_counts_ungrounded_and_abandoned(self):
        from agents.hapax_daimonion.grounding_ledger import GroundingLedger

        ledger = GroundingLedger()
        ledger.add_du(1, "s1")
        ledger.update_from_acceptance("ACCEPT")  # grounded
        ledger.add_du(2, "s2")
        ledger.update_from_acceptance("IGNORE", concern_overlap=0.8)  # ungrounded
        ledger.add_du(3, "s3")
        ledger.update_from_acceptance("CLARIFY")
        ledger.add_du(4, "s4")
        ledger.update_from_acceptance("CLARIFY")
        ledger.add_du(5, "s5")
        ledger.update_from_acceptance("CLARIFY")  # abandoned
        assert ledger.ungrounded_count >= 1
