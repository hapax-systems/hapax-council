"""Tests for D-17 final piece — quiet_frame subscriber to gate decisions.

Verifies the listener API + cooldown + env-var gating without requiring
a real ProgrammePlanStore. ``activate_quiet_frame`` is mocked so tests
don't touch ~/hapax-state.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest  # noqa: TC002 — runtime import for fixtures + decorators

import shared.governance.monetization_safety as safety_mod
import shared.governance.quiet_frame_subscriber as sub_mod
from shared.governance.monetization_safety import RiskAssessment


@pytest.fixture(autouse=True)
def reset_subscriber_state(monkeypatch: pytest.MonkeyPatch):
    """Each test starts with a clean cooldown + listener registry."""
    sub_mod.reset_for_tests()
    # Snapshot listeners so tests don't pollute each other's globals.
    original = list(safety_mod._assess_listeners)
    safety_mod._assess_listeners.clear()
    yield
    safety_mod._assess_listeners.clear()
    safety_mod._assess_listeners.extend(original)
    sub_mod.reset_for_tests()


class TestEnvGating:
    def test_install_no_op_without_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HAPAX_QUIET_FRAME_AUTO", raising=False)
        sub_mod.install()
        assert sub_mod._on_assess not in safety_mod._assess_listeners

    def test_install_registers_when_env_var_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HAPAX_QUIET_FRAME_AUTO", "1")
        sub_mod.install()
        assert sub_mod._on_assess in safety_mod._assess_listeners

    def test_install_idempotent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HAPAX_QUIET_FRAME_AUTO", "1")
        sub_mod.install()
        sub_mod.install()
        sub_mod.install()
        assert safety_mod._assess_listeners.count(sub_mod._on_assess) == 1


class TestSubscriberBehavior:
    def test_allowed_assessment_does_not_activate(self) -> None:
        assessment = RiskAssessment(allowed=True, risk="low", reason="ok")
        with patch("shared.governance.quiet_frame.activate_quiet_frame") as mock_act:
            sub_mod._on_assess(assessment, "knowledge.web_search", None)
        mock_act.assert_not_called()

    def test_blocked_assessment_activates_quiet_frame(self) -> None:
        assessment = RiskAssessment(allowed=False, risk="high", reason="dangerous")
        with patch("shared.governance.quiet_frame.activate_quiet_frame") as mock_act:
            sub_mod._on_assess(assessment, "mouth.broadcast", "test-prog-001")
        mock_act.assert_called_once()
        # Reason includes capability + risk + gate reason for forensics.
        call_kwargs = mock_act.call_args.kwargs
        assert "mouth.broadcast" in call_kwargs["reason"]
        assert "high" in call_kwargs["reason"]
        assert "dangerous" in call_kwargs["reason"]

    def test_cooldown_prevents_repeated_activation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assessment = RiskAssessment(allowed=False, risk="medium", reason="needs opt-in")
        # Cooldown well below test-runtime so we KNOW the second call is
        # within window without timing flakiness.
        monkeypatch.setattr(sub_mod, "COOLDOWN_S", 60.0)
        with patch("shared.governance.quiet_frame.activate_quiet_frame") as mock_act:
            sub_mod._on_assess(assessment, "cap.a", None)
            sub_mod._on_assess(assessment, "cap.b", None)
            sub_mod._on_assess(assessment, "cap.c", None)
        # 10 blocks in rapid succession → 1 activation.
        assert mock_act.call_count == 1

    def test_cooldown_expires_allows_reactivation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assessment = RiskAssessment(allowed=False, risk="medium", reason="needs opt-in")
        # Cooldown=0 → every call activates.
        monkeypatch.setattr(sub_mod, "COOLDOWN_S", 0.0)
        with patch("shared.governance.quiet_frame.activate_quiet_frame") as mock_act:
            sub_mod._on_assess(assessment, "cap.a", None)
            sub_mod._on_assess(assessment, "cap.b", None)
        assert mock_act.call_count == 2

    def test_activation_failure_does_not_propagate(self) -> None:
        """Listener faults must NOT break the gate — verified at the
        subscriber boundary as well as the gate's listener wrapper."""
        assessment = RiskAssessment(allowed=False, risk="high", reason="x")
        with patch(
            "shared.governance.quiet_frame.activate_quiet_frame",
            side_effect=RuntimeError("disk full"),
        ):
            # Must not raise.
            sub_mod._on_assess(assessment, "cap.a", None)


class TestEndToEndThroughGate:
    def test_block_through_gate_triggers_subscriber(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify the listener is actually invoked by the gate's
        _record_and_return wrapper — not just callable in isolation."""
        # Disable audit writes so this doesn't touch ~/hapax-state.
        monkeypatch.setenv("HAPAX_DEMONET_AUDIT", "0")
        # Force the listener's "yes activate" path with cooldown=0 so the
        # call lands deterministically.
        monkeypatch.setattr(sub_mod, "COOLDOWN_S", 0.0)

        # Minimal manual install (bypassing env var so the test is self-
        # contained).
        safety_mod.register_assess_listener(sub_mod._on_assess)

        from dataclasses import dataclass, field
        from typing import Any

        @dataclass
        class _Cand:
            capability_name: str
            payload: dict[str, Any] = field(default_factory=dict)

        with patch("shared.governance.quiet_frame.activate_quiet_frame") as mock_act:
            cand = _Cand("mouth.broadcast", {"monetization_risk": "high"})
            r = safety_mod.GATE.assess(cand, programme=None)
        assert r.allowed is False
        mock_act.assert_called_once()

    def test_listener_failure_does_not_break_gate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Even if the subscriber crashes, the gate returns its assessment."""
        monkeypatch.setenv("HAPAX_DEMONET_AUDIT", "0")

        def _broken_listener(*args, **kwargs):
            raise RuntimeError("bad listener")

        safety_mod.register_assess_listener(_broken_listener)

        from dataclasses import dataclass, field
        from typing import Any

        @dataclass
        class _Cand:
            capability_name: str
            payload: dict[str, Any] = field(default_factory=dict)

        cand = _Cand("mouth.broadcast", {"monetization_risk": "high"})
        # Must not raise.
        r = safety_mod.GATE.assess(cand, programme=None)
        assert r.allowed is False
