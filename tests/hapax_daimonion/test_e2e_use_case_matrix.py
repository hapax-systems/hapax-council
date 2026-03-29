"""End-to-end use case matrix: real use cases through primitive surfaces.

Each test exercises a realistic daemon scenario using real type system
primitives (no mocks on governance/perception types). Asserts at both
ends: use-case outcome AND primitive property.

Primitive surfaces exercised: Behavior, Event, Stamped, FusedContext,
VetoChain, FallbackChain, FreshnessGuard, Command, Schedule,
PipelineGovernor, FrameGate, ContextGate.
"""

from __future__ import annotations

import time
from types import MappingProxyType
from unittest.mock import MagicMock

from agents.hapax_daimonion.combinator import with_latest_from
from agents.hapax_daimonion.commands import Command, Schedule
from agents.hapax_daimonion.context_gate import ContextGate
from agents.hapax_daimonion.frame_gate import FrameGate
from agents.hapax_daimonion.governance import (
    FreshnessGuard,
    FreshnessRequirement,
    FusedContext,
    Veto,
    VetoChain,
)
from agents.hapax_daimonion.governor import PipelineGovernor
from agents.hapax_daimonion.perception import EnvironmentState, PerceptionEngine
from agents.hapax_daimonion.primitives import Event, Stamped
from agents.hapax_daimonion.session import SessionManager

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_state(**overrides) -> EnvironmentState:
    defaults = dict(
        timestamp=time.monotonic(),
        speech_detected=False,
        vad_confidence=0.0,
        face_count=1,
        guest_count=0,
        operator_present=True,
        activity_mode="idle",
        workspace_context="",
        active_window=None,
        window_count=0,
        active_workspace_id=0,
    )
    defaults.update(overrides)
    return EnvironmentState(**defaults)


def _make_engine(face_detected: bool = False, face_count: int = 0, vad: float = 0.0):
    presence = MagicMock()
    presence.latest_vad_confidence = vad
    presence.face_detected = face_detected
    presence.face_count = face_count
    presence.guest_count = max(0, face_count - 1)
    presence.operator_visible = face_detected
    return PerceptionEngine(presence, MagicMock())


def _make_context_gate(session: SessionManager, activity_mode: str = "idle") -> ContextGate:
    """ContextGate with behaviors set to allow (no subprocess calls)."""
    import time as _time

    from agents.hapax_daimonion.primitives import Behavior

    gate = ContextGate(session=session, ambient_classification=False)
    gate.set_activity_mode(activity_mode)
    now = _time.monotonic()
    gate.set_behaviors(
        {
            "sink_volume": Behavior(0.3, watermark=now),
            "midi_active": Behavior(False, watermark=now),
        }
    )
    return gate


# ── Wake Word Use Cases ──────────────────────────────────────────────────────


class TestWakeWordUseCases:
    """Wake word scenarios exercising governor override + Command + FrameGate."""

    def test_wake_word_idle_opens_session_with_immutable_command(self):
        """UC1: Wake word while idle → process, Command immutable, FrameGate receives."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor()
        gate = FrameGate()
        session = SessionManager(silence_timeout_s=30)

        # Simulate daemon _on_wake_word
        gov.wake_word_active = True
        gate.set_directive("process")
        session.open(trigger="wake_word")

        # Perception tick evaluates governor
        engine.tick()
        action = gov.evaluate(engine.latest)

        cmd = Command(
            action=action,
            params={"trigger": "wake_word", "op_present": engine.latest.operator_present},
            trigger_source="wake_word",
            governance_result=gov.last_veto_result,
            selected_by=gov.last_selected.selected_by,
        )
        gate.apply_command(cmd)

        # Use-case: session active, gate processing
        assert session.is_active
        assert session.trigger == "wake_word"
        assert gate.directive == "process"

        # Primitive: Command immutable, provenance correct
        assert isinstance(cmd.params, MappingProxyType)
        assert cmd.selected_by == "wake_word_override"
        assert cmd.governance_result.allowed is True
        assert gate.last_command is cmd

    def test_wake_word_overrides_meeting_with_traceable_provenance(self):
        """UC2: Wake word during meeting → override, provenance traces both paths."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.update_slow_fields(activity_mode="meeting")
        gov = PipelineGovernor()
        gate = FrameGate()

        # First tick: meeting mode → pause
        engine.tick()
        r1 = gov.evaluate(engine.latest)
        cmd1 = Command(action=r1, governance_result=gov.last_veto_result)
        gate.apply_command(cmd1)

        assert gate.directive == "pause"
        assert not cmd1.governance_result.allowed
        assert "activity_mode" in cmd1.governance_result.denied_by

        # Wake word fires
        gov.wake_word_active = True
        engine.tick()
        r2 = gov.evaluate(engine.latest)
        cmd2 = Command(
            action=r2,
            trigger_source="wake_word",
            governance_result=gov.last_veto_result,
            selected_by=gov.last_selected.selected_by,
        )
        gate.apply_command(cmd2)

        # Use-case: gate now processing
        assert gate.directive == "process"

        # Primitive: override provenance, veto result shows allowed
        assert cmd2.governance_result.allowed is True
        assert cmd2.selected_by == "wake_word_override"
        assert gate.last_command is cmd2

    def test_wake_word_consumed_production_resumes_pause(self):
        """UC3: Wake word → process → next tick production re-pauses."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.update_slow_fields(activity_mode="production")
        gov = PipelineGovernor()
        gate = FrameGate()

        # Tick 1: production → pause
        engine.tick()
        r1 = gov.evaluate(engine.latest)
        gate.apply_command(Command(action=r1))
        assert gate.directive == "pause"

        # Wake word
        gov.wake_word_active = True
        engine.tick()
        r2 = gov.evaluate(engine.latest)
        gate.apply_command(Command(action=r2, selected_by=gov.last_selected.selected_by))
        assert gate.directive == "process"
        assert gov.wake_word_active is False  # consumed

        # Exhaust 8-tick grace period
        for _ in range(8):
            engine.tick()
            gov.evaluate(engine.latest)

        # Tick 8: grace exhausted, production still active → pause again
        engine.tick()
        r3 = gov.evaluate(engine.latest)
        cmd3 = Command(action=r3, governance_result=gov.last_veto_result)
        gate.apply_command(cmd3)

        # Use-case: back to pause
        assert gate.directive == "pause"

        # Primitive: veto re-engaged, single-use consumption verified
        assert not cmd3.governance_result.allowed
        assert "activity_mode" in cmd3.governance_result.denied_by

    def test_wake_word_overrides_conversation_debounce(self):
        """UC4: Conversation debounce active → wake word → process via override."""
        gov = PipelineGovernor(conversation_debounce_s=0.0)

        # Drive into conversation pause
        s1 = _make_state(face_count=2, guest_count=1, speech_detected=True)
        gov.evaluate(s1)
        assert gov._paused_by_conversation is True

        # Wake word — overrides all vetoes
        gov.wake_word_active = True
        s2 = _make_state(face_count=2, guest_count=1, speech_detected=True)
        r2 = gov.evaluate(s2)

        # Use-case: processing despite conversation
        assert r2 == "process"

        # Primitive: override is active, conversation state persists but overridden
        assert gov.last_selected.selected_by == "wake_word_override"


# ── Governance Use Cases ─────────────────────────────────────────────────────


class TestGovernanceUseCases:
    """Governor-driven scenarios exercising VetoChain + FallbackChain + FrameGate."""

    def test_meeting_detected_frame_gate_drops_with_provenance(self):
        """UC5: Meeting mode → FrameGate pauses, last_command carries denial provenance."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.update_slow_fields(activity_mode="meeting")
        gov = PipelineGovernor()
        gate = FrameGate()

        engine.tick()
        action = gov.evaluate(engine.latest)
        cmd = Command(
            action=action,
            params={"mode": engine.latest.activity_mode},
            governance_result=gov.last_veto_result,
            min_watermark=engine.min_watermark,
        )
        gate.apply_command(cmd)

        # Use-case: gate dropping audio
        assert gate.directive == "pause"

        # Primitive: VetoResult denial traceable, Command immutable
        assert not gate.last_command.governance_result.allowed
        assert "activity_mode" in gate.last_command.governance_result.denied_by
        assert isinstance(gate.last_command.params, MappingProxyType)
        assert gate.last_command.min_watermark > 0

    def test_operator_absence_withdraw_with_fallback_provenance(self):
        """UC6: Operator absent → withdraw → operator returns → process."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor(operator_absent_withdraw_s=5.0)
        gate = FrameGate()

        # Present → process
        engine.tick()
        r1 = gov.evaluate(engine.latest)
        gate.apply_command(Command(action=r1))
        assert gate.directive == "process"

        # Absent beyond threshold → withdraw
        engine._presence.face_detected = False
        engine._presence.face_count = 0
        gov._last_operator_seen = time.monotonic() - 10.0
        engine.tick()
        r2 = gov.evaluate(engine.latest)
        cmd2 = Command(
            action=r2,
            governance_result=gov.last_veto_result,
            selected_by=gov.last_selected.selected_by,
        )

        # Use-case: withdraw
        assert r2 == "withdraw"

        # Primitive: FallbackChain selected "operator_absent"
        assert cmd2.selected_by == "operator_absent"
        assert cmd2.governance_result.allowed  # veto passed, fallback selected withdraw

        # Operator returns
        engine._presence.face_detected = True
        engine._presence.face_count = 1
        engine.tick()
        r3 = gov.evaluate(engine.latest)
        gate.apply_command(Command(action=r3))
        assert gate.directive == "process"

    def test_conversation_debounce_lifecycle(self):
        """UC7: No conversation → detected → debounce → pause → clear → resume."""
        gov = PipelineGovernor(conversation_debounce_s=0.0, environment_clear_resume_s=0.0)
        gate = FrameGate()

        # No conversation → process
        s1 = _make_state(face_count=1, speech_detected=False)
        r1 = gov.evaluate(s1)
        gate.apply_command(Command(action=r1, governance_result=gov.last_veto_result))
        assert gate.directive == "process"

        # Conversation detected → pause (debounce_s=0)
        s2 = _make_state(face_count=2, guest_count=1, speech_detected=True)
        r2 = gov.evaluate(s2)
        cmd2 = Command(action=r2, governance_result=gov.last_veto_result)
        gate.apply_command(cmd2)
        assert gate.directive == "pause"
        assert "conversation_debounce" in cmd2.governance_result.denied_by

        # Conversation clears → resume (clear_resume_s=0)
        s3 = _make_state(face_count=1, speech_detected=False)
        r3 = gov.evaluate(s3)
        gate.apply_command(Command(action=r3))
        assert gate.directive == "process"

    def test_context_gate_blocks_during_production_mode(self):
        """UC8: ContextGate denies interrupt during production mode."""
        session = SessionManager(silence_timeout_s=30)
        gate = _make_context_gate(session, activity_mode="production")

        result = gate.check()

        # Use-case: not eligible
        assert result.eligible is False
        assert "production" in result.reason.lower()

        # Primitive: ContextGate uses VetoChain internally — verify deny-wins
        gate2 = _make_context_gate(session, activity_mode="idle")
        result2 = gate2.check()
        assert result2.eligible is True


# ── Full Pipeline Use Cases ──────────────────────────────────────────────────


class TestFullPipelineUseCases:
    """End-to-end pipeline scenarios: perception → governance → command → actuator."""

    def test_context_gate_eligible_for_proactive_delivery(self):
        """UC9: All checks pass → ContextGate eligible, VetoChain all-allow."""
        session = SessionManager(silence_timeout_s=30)
        gate = _make_context_gate(session, activity_mode="idle")

        result = gate.check()

        assert result.eligible is True
        assert result.reason == ""

        # Exercise primitive: ContextGate's internal VetoChain evaluated all predicates
        # Verify the chain structure
        assert len(gate._veto_chain.vetoes) >= 4  # session, activity, volume, studio

    def test_perception_to_combinator_to_freshness_to_command(self):
        """UC10: Full primitive chain in use-case context: engine → combinator → guard → cmd."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))
        trigger.emit(time.monotonic(), "tick")

        ctx = received[0]
        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="operator_present", max_staleness_s=30.0),
            ]
        )
        freshness = guard.check(ctx, time.monotonic())

        cmd = Command(
            action="process" if freshness.fresh_enough else "pause",
            params={"op_val": ctx.samples["operator_present"].value},
            min_watermark=ctx.min_watermark,
        )

        # Use-case: fresh data → process
        assert cmd.action == "process"

        # Primitive: watermarks flow, samples immutable, params immutable
        assert ctx.min_watermark > 0
        assert isinstance(ctx.samples, MappingProxyType)
        assert isinstance(cmd.params, MappingProxyType)
        assert cmd.params["op_val"] is True
        assert freshness.fresh_enough
        assert len(freshness.violations) == 0

    def test_stale_behavior_freshness_denies_with_violations(self):
        """UC11: Stale/missing behavior → FreshnessGuard denies, violations traceable."""
        now = time.monotonic()
        ctx = FusedContext(
            trigger_time=now,
            trigger_value="tick",
            samples={
                "operator_present": Stamped(value=True, watermark=now - 100.0),
            },
            min_watermark=now - 100.0,
        )

        guard = FreshnessGuard(
            [
                FreshnessRequirement(behavior_name="operator_present", max_staleness_s=5.0),
                FreshnessRequirement(behavior_name="gaze_confidence", max_staleness_s=5.0),
            ]
        )
        freshness = guard.check(ctx, now)

        # Wrap as veto chain predicate (real use-case pattern)
        chain: VetoChain[FusedContext] = VetoChain(
            [
                Veto(name="freshness", predicate=lambda c: guard.check(c, now).fresh_enough),
            ]
        )
        veto = chain.evaluate(ctx)

        cmd = Command(
            action="pause",
            params={"violations": list(freshness.violations)},
            governance_result=veto,
        )

        # Use-case: stale data → pause
        assert cmd.action == "pause"

        # Primitive: 2 violations (stale + missing), VetoChain denies, immutable
        assert not freshness.fresh_enough
        assert len(freshness.violations) == 2
        assert any("stale" in v for v in freshness.violations)
        assert any("not present" in v for v in freshness.violations)
        assert not veto.allowed
        assert "freshness" in veto.denied_by
        assert isinstance(cmd.params, MappingProxyType)

    def test_full_daemon_tick_perception_to_governor_to_command_to_gate(self):
        """UC12: End-to-end daemon tick — every field traceable from sensor to actuator."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor()
        gate = FrameGate()

        # Simulate one daemon tick
        state = engine.tick()
        action = gov.evaluate(state)

        # Build Command with full provenance (as daemon does)
        cmd = Command(
            action=action,
            params={
                "op_present": state.operator_present,
                "face_count": state.face_count,
                "mode": state.activity_mode,
            },
            trigger_time=state.timestamp,
            trigger_source="perception_tick",
            min_watermark=engine.min_watermark,
            governance_result=gov.last_veto_result,
            selected_by=gov.last_selected.selected_by,
        )
        gate.apply_command(cmd)

        # Schedule for future phase
        sched = Schedule(command=cmd, target_time=state.timestamp)

        # Use-case: idle + present → process, gate processing
        assert gate.directive == "process"

        # Primitive: full provenance chain traceable
        assert gate.last_command is cmd
        assert gate.last_command.trigger_source == "perception_tick"
        assert gate.last_command.trigger_time == state.timestamp
        assert gate.last_command.min_watermark > 0
        assert gate.last_command.governance_result.allowed is True
        assert gate.last_command.selected_by == "default"
        assert gate.last_command.params["op_present"] is True
        assert isinstance(gate.last_command.params, MappingProxyType)

        # Schedule preserves everything
        assert sched.command.action == "process"
        assert sched.command.governance_result is cmd.governance_result
        assert sched.target_time == state.timestamp

        # Behaviors accessible and consistent with state
        assert engine.behaviors["operator_present"].value == state.operator_present
        assert engine.behaviors["face_count"].value == state.face_count
