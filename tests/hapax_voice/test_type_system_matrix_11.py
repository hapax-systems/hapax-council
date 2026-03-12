"""Cross-cutting integration tests for the perception type system (matrix 11).

Lifecycle simulation (Q1): composes forward pipeline flow (T1), perturbation
cascades (T2), and feedback/re-entry (T6). Each test exercises a full daemon
lifecycle where inputs change dynamically and state feeds back across cycles.
System-level property: the daemon produces correct directives across a
multi-cycle lifecycle with mid-flight perturbations.
"""

from __future__ import annotations

import time
from types import MappingProxyType
from unittest.mock import MagicMock

from agents.hapax_voice.combinator import with_latest_from
from agents.hapax_voice.commands import Command, Schedule
from agents.hapax_voice.governance import (
    FreshnessGuard,
    FreshnessRequirement,
    FusedContext,
    Veto,
    VetoChain,
)
from agents.hapax_voice.governor import PipelineGovernor
from agents.hapax_voice.perception import EnvironmentState, PerceptionEngine
from agents.hapax_voice.primitives import Behavior, Event

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_state(**overrides) -> EnvironmentState:
    defaults = dict(
        timestamp=time.monotonic(),
        speech_detected=False,
        speech_volume_db=-40.0,
        ambient_class="quiet",
        vad_confidence=0.0,
        face_count=1,
        operator_present=True,
        gaze_at_camera=False,
        activity_mode="idle",
        workspace_context="",
        ambient_detailed="",
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
    return PerceptionEngine(presence, MagicMock())


# ── Q1: Lifecycle Simulation ─────────────────────────────────────────────────


class TestIdleToActiveLifecycle:
    """System transitions from idle to active via perturbation, with feedback."""

    def test_idle_start_perturbation_to_active_feedback_loop(self):
        """T1+T2+T6: Idle engine → face appears → governor processes → next cycle stable."""
        engine = _make_engine()
        gov = PipelineGovernor()

        # Cycle 1: no face → process (idle is allowed by veto chain)
        engine.tick()
        r1 = gov.evaluate(engine.latest)
        cmd1 = Command(action=r1, params={"cycle": 1})

        # Perturbation: face appears
        engine._presence.face_detected = True
        engine._presence.face_count = 1

        # Cycle 2: face present → process (still allowed)
        engine.tick()
        r2 = gov.evaluate(engine.latest)
        cmd2 = Command(action=r2, params={"cycle": 2})

        # Cycle 3: feedback — state carries forward, still processing
        engine.tick()
        r3 = gov.evaluate(engine.latest)
        cmd3 = Command(action=r3, params={"cycle": 3})

        assert cmd1.action == "process"
        assert cmd2.action == "process"
        assert cmd3.action == "process"
        assert engine.latest.operator_present is True
        assert isinstance(cmd3.params, MappingProxyType)

    def test_meeting_mode_perturbation_pauses_active_pipeline(self):
        """T1+T2+T6: Active pipeline → meeting mode perturbation → pause persists."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor()

        # Cycle 1: idle mode → process
        engine.tick()
        r1 = gov.evaluate(engine.latest)
        assert r1 == "process"

        # Perturbation: meeting mode
        engine.update_slow_fields(activity_mode="meeting")

        # Cycle 2: meeting → pause
        engine.tick()
        r2 = gov.evaluate(engine.latest)
        assert r2 == "pause"
        assert not gov.last_veto_result.allowed
        assert "activity_mode" in gov.last_veto_result.denied_by

        # Cycle 3: feedback — meeting persists → still paused
        engine.tick()
        r3 = gov.evaluate(engine.latest)
        assert r3 == "pause"

        # Perturbation: meeting ends
        engine.update_slow_fields(activity_mode="idle")
        engine.tick()
        r4 = gov.evaluate(engine.latest)
        assert r4 == "process"

    def test_wake_word_overrides_perturbation_in_lifecycle(self):
        """T1+T2+T6: Meeting-paused → wake word fires → overrides → next cycle clear."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor()

        # Cycle 1: meeting mode → pause
        engine.update_slow_fields(activity_mode="meeting")
        engine.tick()
        r1 = gov.evaluate(engine.latest)
        assert r1 == "pause"

        # Perturbation: wake word
        gov.wake_word_active = True

        # Cycle 2: wake word overrides → process
        engine.tick()
        r2 = gov.evaluate(engine.latest)
        assert r2 == "process"
        assert gov.last_selected.selected_by == "wake_word_override"
        assert gov.wake_word_active is False  # consumed

        # Grace period: 3 ticks protected by wake_word_grace
        for _ in range(3):
            engine.tick()
            rg = gov.evaluate(engine.latest)
            assert rg == "process"
            assert gov.last_selected.selected_by == "wake_word_grace"

        # Cycle 3: grace exhausted, meeting still active → pause again
        engine.tick()
        r3 = gov.evaluate(engine.latest)
        assert r3 == "pause"

    def test_absence_lifecycle_with_delayed_perturbation(self):
        """T1+T2+T6: Present → absent → grace period → withdraw → re-appear → process."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor(operator_absent_withdraw_s=5.0)

        # Cycle 1: present → process
        engine.tick()
        r1 = gov.evaluate(engine.latest)
        assert r1 == "process"

        # Perturbation: operator leaves
        engine._presence.face_detected = False
        engine._presence.face_count = 0

        # Cycle 2: just left, within grace → process
        engine.tick()
        r2 = gov.evaluate(engine.latest)
        assert r2 == "process"

        # Cycle 3: force past threshold → withdraw
        gov._last_operator_seen = time.monotonic() - 10.0
        engine.tick()
        r3 = gov.evaluate(engine.latest)
        assert r3 == "withdraw"

        # Perturbation: operator returns
        engine._presence.face_detected = True
        engine._presence.face_count = 1

        # Cycle 4: feedback — presence resets tracking → process
        engine.tick()
        r4 = gov.evaluate(engine.latest)
        assert r4 == "process"


class TestConversationDebounceLifecycle:
    """Multi-cycle conversation debounce as stateful lifecycle."""

    def test_conversation_onset_through_debounce_to_pause(self):
        """T1+T2+T6: No conversation → detected → debounce accumulates → pause."""
        gov = PipelineGovernor(conversation_debounce_s=0.0)

        # Cycle 1: no conversation → process
        s1 = _make_state(face_count=1, speech_detected=False)
        r1 = gov.evaluate(s1)
        assert r1 == "process"

        # Perturbation: conversation starts (face_count > 1 AND speech)
        s2 = _make_state(face_count=2, speech_detected=True)
        r2 = gov.evaluate(s2)
        # debounce_s=0 → pauses immediately
        assert r2 == "pause"

        # Feedback: conversation continues → still paused
        s3 = _make_state(face_count=2, speech_detected=True)
        r3 = gov.evaluate(s3)
        assert r3 == "pause"

    def test_conversation_clears_through_environment_resume(self):
        """T1+T2+T6: Paused by conversation → clears → timer accumulates → resume."""
        gov = PipelineGovernor(conversation_debounce_s=0.0, environment_clear_resume_s=0.0)

        # Drive into conversation pause
        s1 = _make_state(face_count=2, speech_detected=True)
        gov.evaluate(s1)
        s2 = _make_state(face_count=2, speech_detected=True)
        gov.evaluate(s2)
        assert gov._paused_by_conversation is True

        # Perturbation: conversation stops
        s3 = _make_state(face_count=1, speech_detected=False)
        r3 = gov.evaluate(s3)
        # environment_clear_resume_s=0 → clears immediately
        assert r3 == "process"

    def test_conversation_interrupted_by_wake_word_in_lifecycle(self):
        """T1+T2+T6: Conversation accumulating → wake word → clears debounce state."""
        gov = PipelineGovernor(conversation_debounce_s=0.0)

        # Conversation starts and pauses
        s1 = _make_state(face_count=2, speech_detected=True)
        gov.evaluate(s1)
        assert gov._paused_by_conversation is True

        # Perturbation: wake word
        gov.wake_word_active = True
        s2 = _make_state(face_count=2, speech_detected=True)
        r2 = gov.evaluate(s2)
        assert r2 == "process"
        assert gov._paused_by_conversation is False
        assert gov._conversation_first_seen is None

        # Grace period: 3 ticks protected by wake_word_grace
        for _ in range(3):
            s_grace = _make_state(face_count=2, speech_detected=True)
            rg = gov.evaluate(s_grace)
            assert rg == "process"
            assert gov.last_selected.selected_by == "wake_word_grace"

        # Feedback: grace exhausted, conversation still happening → re-debounces
        s3 = _make_state(face_count=2, speech_detected=True)
        r3 = gov.evaluate(s3)
        # Will start accumulating again, debounce_s=0 so immediate
        assert r3 == "pause"

    def test_rapid_perturbation_oscillation_across_cycles(self):
        """T1+T2+T6: Conversation flickers on/off rapidly → debounce resets each time."""
        gov = PipelineGovernor(conversation_debounce_s=5.0)

        results = []
        for i in range(6):
            # Alternate: conversation on odd cycles, off even
            has_conv = i % 2 == 1
            s = _make_state(
                face_count=2 if has_conv else 1,
                speech_detected=has_conv,
            )
            results.append(gov.evaluate(s))

        # debounce_s=5 and conversation keeps resetting → never pauses
        assert all(r == "process" for r in results)


class TestFullDaemonLifecycle:
    """End-to-end daemon lifecycle scenarios."""

    def test_five_cycle_daemon_idle_meeting_wake_absent_return(self):
        """T1+T2+T6: 5-cycle scenario exercising all governor paths."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor(operator_absent_withdraw_s=5.0)
        directives = []

        # Cycle 1: idle → process
        engine.tick()
        directives.append(gov.evaluate(engine.latest))

        # Cycle 2: perturbation → meeting → pause
        engine.update_slow_fields(activity_mode="meeting")
        engine.tick()
        directives.append(gov.evaluate(engine.latest))

        # Cycle 3: perturbation → wake word → process (overrides meeting)
        gov.wake_word_active = True
        engine.tick()
        directives.append(gov.evaluate(engine.latest))

        # Exhaust 3-tick grace period
        for _ in range(3):
            engine.tick()
            gov.evaluate(engine.latest)

        # Cycle 4: grace exhausted, meeting still active, operator leaves, force past threshold
        engine._presence.face_detected = False
        engine._presence.face_count = 0
        engine.tick()
        directives.append(gov.evaluate(engine.latest))
        # meeting mode veto fires first → pause (not withdraw, veto takes precedence)

        # Cycle 5: meeting ends, but operator still absent
        engine.update_slow_fields(activity_mode="idle")
        gov._last_operator_seen = time.monotonic() - 10.0
        engine.tick()
        directives.append(gov.evaluate(engine.latest))

        assert directives == ["process", "pause", "process", "pause", "withdraw"]

    def test_perception_engine_feeds_governor_feeds_command_across_cycles(self):
        """T1+T2+T6: Engine → governor → Command pipeline, 3 cycles with perturbations."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor()
        commands: list[Command] = []

        for cycle in range(3):
            if cycle == 1:
                engine.update_slow_fields(activity_mode="production")
            elif cycle == 2:
                engine.update_slow_fields(activity_mode="idle")

            engine.tick()
            action = gov.evaluate(engine.latest)
            cmd = Command(
                action=action,
                params={"cycle": cycle, "op": engine.latest.operator_present},
            )
            commands.append(cmd)

        assert commands[0].action == "process"
        assert commands[1].action == "pause"
        assert commands[2].action == "process"
        for cmd in commands:
            assert isinstance(cmd.params, MappingProxyType)

    def test_combinator_lifecycle_with_stale_perturbation(self):
        """T1+T2+T6: Combinator across cycles, behavior goes stale, freshness vetoes."""
        b_sensor = Behavior("ok", watermark=time.monotonic())
        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, {"sensor": b_sensor})
        guard = FreshnessGuard([
            FreshnessRequirement(behavior_name="sensor", max_staleness_s=5.0),
        ])
        chain: VetoChain[FusedContext] = VetoChain([
            Veto(name="freshness", predicate=lambda c: guard.check(c, time.monotonic()).fresh_enough),
        ])

        contexts: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: contexts.append(ctx))

        # Cycle 1: fresh → allowed
        trigger.emit(time.monotonic(), "c1")
        veto1 = chain.evaluate(contexts[0])
        assert veto1.allowed

        # Perturbation: sensor goes stale (don't update behavior)
        # Force staleness by using an old watermark
        b_stale = Behavior("old", watermark=time.monotonic() - 100.0)
        fused2 = with_latest_from(trigger, {"sensor": b_stale})
        contexts2: list[FusedContext] = []
        fused2.subscribe(lambda ts, ctx: contexts2.append(ctx))

        # Cycle 2: stale → denied
        trigger.emit(time.monotonic(), "c2")
        veto2 = chain.evaluate(contexts2[0])
        assert not veto2.allowed
        assert "freshness" in veto2.denied_by

        # Cycle 3: fresh again (update behavior)
        b_fresh = Behavior("new", watermark=time.monotonic())
        fused3 = with_latest_from(trigger, {"sensor": b_fresh})
        contexts3: list[FusedContext] = []
        fused3.subscribe(lambda ts, ctx: contexts3.append(ctx))
        trigger.emit(time.monotonic(), "c3")
        veto3 = chain.evaluate(contexts3[0])
        assert veto3.allowed

    def test_schedule_sequence_lifecycle_with_perturbation(self):
        """T1+T2+T6: Full pipeline to Schedule, perturbation changes action mid-sequence."""
        engine = _make_engine(face_detected=True, face_count=1)
        gov = PipelineGovernor()
        schedules: list[Schedule] = []

        for cycle in range(3):
            if cycle == 1:
                engine.update_slow_fields(activity_mode="meeting")
            elif cycle == 2:
                gov.wake_word_active = True

            engine.tick()
            action = gov.evaluate(engine.latest)
            cmd = Command(
                action=action,
                params={"cycle": cycle},
                trigger_time=engine.latest.timestamp,
                min_watermark=engine.min_watermark,
            )
            sched = Schedule(command=cmd, target_time=engine.latest.timestamp)
            schedules.append(sched)

        assert schedules[0].command.action == "process"
        assert schedules[1].command.action == "pause"
        assert schedules[2].command.action == "process"
        # Provenance: each schedule carries engine watermark
        for sched in schedules:
            assert sched.command.min_watermark > 0
            assert isinstance(sched.command.params, MappingProxyType)
