"""Tests for PipelineGovernor axiom compliance veto (H1).

Proves that runtime compliance rules match workspace_context from the
slow-tick LLM analysis, causing the governor to pause when the operator's
workspace suggests management-sensitive context.
"""

from __future__ import annotations

import time

from agents.hapax_voice.governor import _RUNTIME_COMPLIANCE_RULES, PipelineGovernor
from agents.hapax_voice.perception import EnvironmentState
from shared.axiom_enforcement import check_fast


def _make_state(**overrides) -> EnvironmentState:
    defaults = dict(
        timestamp=time.monotonic(),
        speech_detected=False,
        vad_confidence=0.0,
        face_count=1,
        guest_count=0,
        operator_present=True,
        activity_mode="idle",
    )
    defaults.update(overrides)
    return EnvironmentState(**defaults)


class TestRuntimeRulesContent:
    """The runtime rules match real management-sensitive workspace descriptions."""

    def test_rules_exist(self):
        assert len(_RUNTIME_COMPLIANCE_RULES) >= 2

    def test_feedback_keyword_matches(self):
        result = check_fast(
            "operator reviewing quarterly feedback document in Obsidian",
            rules=_RUNTIME_COMPLIANCE_RULES,
        )
        assert not result.compliant
        assert "management_governance" in result.axiom_ids

    def test_coaching_keyword_matches(self):
        result = check_fast(
            "editing coaching notes for direct report",
            rules=_RUNTIME_COMPLIANCE_RULES,
        )
        assert not result.compliant

    def test_one_on_one_matches(self):
        result = check_fast(
            "preparing 1-on-1 agenda in Google Docs",
            rules=_RUNTIME_COMPLIANCE_RULES,
        )
        assert not result.compliant

    def test_performance_review_matches(self):
        result = check_fast(
            "writing performance review in Lattice",
            rules=_RUNTIME_COMPLIANCE_RULES,
        )
        assert not result.compliant

    def test_draft_conversation_matches(self):
        result = check_fast(
            "draft difficult conversation script for underperformer",
            rules=_RUNTIME_COMPLIANCE_RULES,
        )
        assert not result.compliant

    def test_coding_context_passes(self):
        result = check_fast(
            "editing Python module in VS Code, running pytest",
            rules=_RUNTIME_COMPLIANCE_RULES,
        )
        assert result.compliant

    def test_browser_context_passes(self):
        result = check_fast(
            "reading documentation in Firefox, 3 tabs open",
            rules=_RUNTIME_COMPLIANCE_RULES,
        )
        assert result.compliant

    def test_empty_context_passes(self):
        result = check_fast("", rules=_RUNTIME_COMPLIANCE_RULES)
        assert result.compliant


class TestComplianceVetoInChain:
    """Axiom compliance veto participates in governor evaluation."""

    def test_compliance_veto_present_in_chain(self):
        gov = PipelineGovernor()
        names = [v.name for v in gov.veto_chain.vetoes]
        assert "axiom_compliance" in names

    def test_compliance_veto_is_last(self):
        gov = PipelineGovernor()
        names = [v.name for v in gov.veto_chain.vetoes]
        assert names[-1] == "axiom_compliance"

    def test_compliance_veto_has_axiom_tag(self):
        gov = PipelineGovernor()
        compliance = [v for v in gov.veto_chain.vetoes if v.name == "axiom_compliance"][0]
        assert compliance.axiom == "constitutional"

    def test_idle_workspace_processes(self):
        gov = PipelineGovernor()
        state = _make_state(workspace_context="editing Python in VS Code")
        assert gov.evaluate(state) == "process"

    def test_empty_workspace_processes(self):
        """No workspace_context yet (slow-tick hasn't run) → fail-open."""
        gov = PipelineGovernor()
        state = _make_state(workspace_context="")
        assert gov.evaluate(state) == "process"

    def test_management_workspace_pauses(self):
        """Workspace with feedback content triggers compliance veto → pause."""
        gov = PipelineGovernor()
        state = _make_state(
            workspace_context="reviewing quarterly feedback document for direct report"
        )
        assert gov.evaluate(state) == "pause"

    def test_coaching_workspace_pauses(self):
        gov = PipelineGovernor()
        state = _make_state(workspace_context="editing coaching notes in Obsidian")
        assert gov.evaluate(state) == "pause"

    def test_one_on_one_workspace_pauses(self):
        gov = PipelineGovernor()
        state = _make_state(workspace_context="preparing 1-on-1 agenda for Thursday")
        assert gov.evaluate(state) == "pause"

    def test_violation_recorded_in_veto_result(self):
        gov = PipelineGovernor()
        state = _make_state(workspace_context="editing performance review notes")
        gov.evaluate(state)
        assert gov.last_veto_result is not None
        assert not gov.last_veto_result.allowed
        assert "axiom_compliance" in gov.last_veto_result.denied_by
        assert "constitutional" in gov.last_veto_result.axiom_ids

    def test_wake_word_overrides_compliance(self):
        """Wake word supremacy bypasses compliance veto."""
        gov = PipelineGovernor()
        gov.wake_word_active = True
        state = _make_state(workspace_context="reviewing feedback for team member")
        assert gov.evaluate(state) == "process"

    def test_no_rules_passes(self):
        """With no compiled rules, compliance veto always allows."""
        gov = PipelineGovernor()
        gov._compliance_rules = []
        state = _make_state(workspace_context="reviewing feedback doc")
        assert gov.evaluate(state) == "process"


class TestComplianceWindowTitle:
    """Window title is a fast signal for compliance (updated every focus change)."""

    def test_title_with_feedback_pauses(self):
        from shared.hyprland import WindowInfo

        win = WindowInfo(
            address="0x1",
            app_class="firefox",
            title="Q1 Performance Review - Google Docs",
            workspace_id=1,
            pid=1,
            x=0,
            y=0,
            width=1920,
            height=1080,
            floating=False,
            fullscreen=False,
        )
        gov = PipelineGovernor()
        state = _make_state(active_window=win)
        assert gov.evaluate(state) == "pause"

    def test_title_with_one_on_one_pauses(self):
        from shared.hyprland import WindowInfo

        win = WindowInfo(
            address="0x1",
            app_class="obsidian",
            title="1-on-1 Agenda - Operator",
            workspace_id=1,
            pid=1,
            x=0,
            y=0,
            width=1920,
            height=1080,
            floating=False,
            fullscreen=False,
        )
        gov = PipelineGovernor()
        state = _make_state(active_window=win)
        assert gov.evaluate(state) == "pause"

    def test_title_without_management_processes(self):
        from shared.hyprland import WindowInfo

        win = WindowInfo(
            address="0x1",
            app_class="kitty",
            title="nvim - perception.py",
            workspace_id=1,
            pid=1,
            x=0,
            y=0,
            width=1920,
            height=1080,
            floating=False,
            fullscreen=False,
        )
        gov = PipelineGovernor()
        state = _make_state(active_window=win)
        assert gov.evaluate(state) == "process"

    def test_title_fires_without_workspace_context(self):
        """Window title catches management context before slow-tick runs."""
        from shared.hyprland import WindowInfo

        win = WindowInfo(
            address="0x1",
            app_class="firefox",
            title="Coaching Notes - Team",
            workspace_id=1,
            pid=1,
            x=0,
            y=0,
            width=1920,
            height=1080,
            floating=False,
            fullscreen=False,
        )
        gov = PipelineGovernor()
        state = _make_state(active_window=win, workspace_context="")
        assert gov.evaluate(state) == "pause"

    def test_no_active_window_failopen(self):
        gov = PipelineGovernor()
        state = _make_state(active_window=None, workspace_context="")
        assert gov.evaluate(state) == "process"


class TestWorkspaceContextComplianceVeto:
    """workspace_context containing management-sensitive content triggers veto."""

    def test_one_on_one_feedback_in_workspace_context_pauses(self):
        gov = PipelineGovernor()
        state = _make_state(workspace_context="1-on-1 feedback session with direct report")
        assert gov.evaluate(state) == "pause"
