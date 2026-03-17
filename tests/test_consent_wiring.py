"""Tests for consent e2e wiring: governor veto + visual signals.

Verifies the wife-walks-in scenario produces correct governor directives
and visual layer signals at each consent phase transition.
"""

from __future__ import annotations

import time

from agents.hapax_voice.governor import PipelineGovernor
from agents.hapax_voice.perception import EnvironmentState
from agents.visual_layer_state import SEVERITY_CRITICAL, SEVERITY_HIGH, SEVERITY_LOW


def _state(**overrides) -> EnvironmentState:
    defaults = {"timestamp": time.monotonic(), "operator_present": True}
    defaults.update(overrides)
    return EnvironmentState(**defaults)


class TestGovernorConsentVeto:
    """Governor pauses pipeline during consent_pending and consent_refused."""

    def test_no_guest_allows_process(self):
        gov = PipelineGovernor()
        result = gov.evaluate(_state(consent_phase="no_guest"))
        assert result == "process"

    def test_guest_detected_allows_process(self):
        """guest_detected is debounce phase — pipeline still runs."""
        gov = PipelineGovernor()
        result = gov.evaluate(_state(consent_phase="guest_detected"))
        assert result == "process"

    def test_consent_pending_pauses(self):
        """consent_pending → pipeline must pause (data curtailed)."""
        gov = PipelineGovernor()
        result = gov.evaluate(_state(consent_phase="consent_pending"))
        assert result == "pause"
        assert gov.last_veto_result is not None
        assert not gov.last_veto_result.allowed
        assert "consent_pending" in str(gov.last_veto_result)

    def test_consent_refused_pauses(self):
        """consent_refused → pipeline stays paused."""
        gov = PipelineGovernor()
        result = gov.evaluate(_state(consent_phase="consent_refused"))
        assert result == "pause"

    def test_consent_granted_allows_process(self):
        """consent_granted → pipeline resumes."""
        gov = PipelineGovernor()
        result = gov.evaluate(_state(consent_phase="consent_granted"))
        assert result == "process"

    def test_wake_word_overrides_consent_pending(self):
        """Wake word supremacy override — even during consent_pending.

        This is correct: the operator explicitly triggered voice. The consent
        veto only blocks autonomous pipeline processing, not operator-initiated
        interaction.
        """
        gov = PipelineGovernor()
        gov.wake_word_active = True
        result = gov.evaluate(_state(consent_phase="consent_pending"))
        assert result == "process"

    def test_scenario_wife_walks_in(self):
        """Full state transition sequence."""
        gov = PipelineGovernor()

        # 1. Alone → process
        assert gov.evaluate(_state(consent_phase="no_guest")) == "process"

        # 2. Wife detected → still process (debounce)
        assert gov.evaluate(_state(consent_phase="guest_detected", face_count=2)) == "process"

        # 3. Consent pending → pause
        assert gov.evaluate(_state(consent_phase="consent_pending", face_count=2)) == "pause"

        # 4. Consent granted → process
        assert gov.evaluate(_state(consent_phase="consent_granted", face_count=2)) == "process"

        # 5. Wife leaves → back to no_guest → process
        assert gov.evaluate(_state(consent_phase="no_guest", face_count=1)) == "process"

    def test_scenario_consent_refused_then_leaves(self):
        """Refused consent → pause until guest leaves."""
        gov = PipelineGovernor()

        # Consent refused → pause
        assert gov.evaluate(_state(consent_phase="consent_refused", face_count=2)) == "pause"

        # Guest leaves → no_guest → process
        assert gov.evaluate(_state(consent_phase="no_guest", face_count=1)) == "process"


class TestVisualConsentSignals:
    """Visual layer produces correct signals per consent phase."""

    def test_guest_detected_low_severity(self):
        from agents.visual_layer_aggregator import map_perception

        data = {"consent_phase": "guest_detected", "flow_score": 0.5}
        signals, _, _, _ = map_perception(data)
        consent_signals = [s for s in signals if s.source_id == "consent-phase"]
        assert len(consent_signals) == 1
        assert consent_signals[0].severity == SEVERITY_LOW
        assert "identifying" in consent_signals[0].title.lower()

    def test_consent_pending_high_severity(self):
        from agents.visual_layer_aggregator import map_perception

        data = {"consent_phase": "consent_pending", "flow_score": 0.5}
        signals, _, _, _ = map_perception(data)
        consent_signals = [s for s in signals if s.source_id == "consent-phase"]
        assert len(consent_signals) == 1
        assert consent_signals[0].severity == SEVERITY_HIGH
        assert "curtailed" in consent_signals[0].title.lower()

    def test_consent_refused_critical_severity(self):
        from agents.visual_layer_aggregator import map_perception

        data = {"consent_phase": "consent_refused", "flow_score": 0.5}
        signals, _, _, _ = map_perception(data)
        consent_signals = [s for s in signals if s.source_id == "consent-phase"]
        assert len(consent_signals) == 1
        assert consent_signals[0].severity == SEVERITY_CRITICAL
        assert "purged" in consent_signals[0].title.lower()

    def test_consent_granted_low_severity(self):
        from agents.visual_layer_aggregator import map_perception

        data = {"consent_phase": "consent_granted", "flow_score": 0.5}
        signals, _, _, _ = map_perception(data)
        consent_signals = [s for s in signals if s.source_id == "consent-phase"]
        assert len(consent_signals) == 1
        assert consent_signals[0].severity == SEVERITY_LOW
        assert "consented" in consent_signals[0].title.lower()

    def test_no_guest_no_signal(self):
        from agents.visual_layer_aggregator import map_perception

        data = {"consent_phase": "no_guest", "flow_score": 0.5}
        signals, _, _, _ = map_perception(data)
        consent_signals = [s for s in signals if s.source_id == "consent-phase"]
        assert len(consent_signals) == 0
