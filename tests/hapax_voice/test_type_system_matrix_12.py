"""Cross-cutting integration tests for the perception type system (matrix 12).

Multi-path coherence (Q2): composes forward pipeline flow (T1), convergent
pipelines (T3), and provenance tracing (T5). Each test exercises parallel
forward paths that converge at a decision point, with provenance traceable
through both contributing chains.
"""

from __future__ import annotations

import time
from types import MappingProxyType
from unittest.mock import MagicMock

from agents.hapax_voice.combinator import with_latest_from
from agents.hapax_voice.commands import Command, Schedule
from agents.hapax_voice.governance import (
    Candidate,
    FallbackChain,
    FreshnessGuard,
    FreshnessRequirement,
    FusedContext,
    Veto,
    VetoChain,
    VetoResult,
)
from agents.hapax_voice.governor import PipelineGovernor
from agents.hapax_voice.perception import EnvironmentState, PerceptionEngine
from agents.hapax_voice.primitives import Behavior, Event, Stamped

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


# ── Q2: Multi-Path Coherence ─────────────────────────────────────────────────


class TestDualPathForwardConvergence:
    """Two forward pipelines converge — outputs must be coherent."""

    def test_two_perception_paths_converge_at_governor(self):
        """T1+T3+T5: Engine provides state + combinator provides FusedContext,
        both feed governance that must agree on same environment."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        # Path A: direct EnvironmentState → Governor
        gov_a = PipelineGovernor()
        directive_a = gov_a.evaluate(engine.latest)

        # Path B: Behaviors → combinator → FusedContext → VetoChain
        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))
        trigger.emit(time.monotonic(), "tick")
        ctx = received[0]

        chain: VetoChain[FusedContext] = VetoChain([
            Veto(
                name="activity_mode",
                predicate=lambda c: c.samples["activity_mode"].value
                not in ("production", "meeting"),
            ),
        ])
        veto_b = chain.evaluate(ctx)

        # Convergence: both paths agree
        assert directive_a == "process"
        assert veto_b.allowed
        # Provenance: combinator path has operator_present from same tick
        assert ctx.samples["operator_present"].value == engine.latest.operator_present

    def test_freshness_and_veto_dual_path_convergence(self):
        """T1+T3+T5: FreshnessGuard path + VetoChain path evaluate same FusedContext."""
        now = time.monotonic()
        ctx = FusedContext(
            trigger_time=now,
            trigger_value="eval",
            samples={
                "activity_mode": Stamped(value="idle", watermark=now),
                "sensor": Stamped(value="ok", watermark=now),
            },
            min_watermark=now,
        )

        # Path A: freshness
        guard = FreshnessGuard([
            FreshnessRequirement(behavior_name="sensor", max_staleness_s=5.0),
        ])
        freshness = guard.check(ctx, now)

        # Path B: veto chain
        chain: VetoChain[FusedContext] = VetoChain([
            Veto(
                name="activity_check",
                predicate=lambda c: c.samples["activity_mode"].value != "meeting",
            ),
        ])
        veto = chain.evaluate(ctx)

        # Convergence: both paths allow
        assert freshness.fresh_enough
        assert veto.allowed

        # Merge into Command with provenance from both paths
        cmd = Command(
            action="process",
            params={"fresh": freshness.fresh_enough, "veto_allowed": veto.allowed},
            governance_result=veto,
            min_watermark=ctx.min_watermark,
        )
        assert cmd.params["fresh"] is True
        assert cmd.params["veto_allowed"] is True
        assert isinstance(cmd.params, MappingProxyType)

    def test_combinator_dual_trigger_convergence_with_provenance(self):
        """T1+T3+T5: Two events trigger same behaviors → two FusedContexts converge."""
        b_mode = Behavior("idle", watermark=time.monotonic())
        b_face = Behavior(True, watermark=time.monotonic())
        behaviors = {"activity_mode": b_mode, "operator_present": b_face}

        trigger_a: Event[str] = Event()
        trigger_b: Event[str] = Event()
        fused_a = with_latest_from(trigger_a, behaviors)
        fused_b = with_latest_from(trigger_b, behaviors)

        ctx_a: list[FusedContext] = []
        ctx_b: list[FusedContext] = []
        fused_a.subscribe(lambda ts, ctx: ctx_a.append(ctx))
        fused_b.subscribe(lambda ts, ctx: ctx_b.append(ctx))

        now = time.monotonic()
        trigger_a.emit(now, "path_a")
        trigger_b.emit(now, "path_b")

        # Convergence: same behavior snapshots, different trigger values
        assert ctx_a[0].samples["activity_mode"].value == ctx_b[0].samples["activity_mode"].value
        assert ctx_a[0].trigger_value == "path_a"
        assert ctx_b[0].trigger_value == "path_b"
        # Provenance: both have same watermarks (same underlying behaviors)
        assert ctx_a[0].min_watermark == ctx_b[0].min_watermark

    def test_fast_slow_behavior_convergence_in_fused_context(self):
        """T1+T3+T5: Fast and slow behaviors converge, provenance shows different ages."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.update_slow_fields(activity_mode="coding")
        slow_wm = engine.behaviors["activity_mode"].watermark

        engine.tick()
        fast_wm = engine.behaviors["operator_present"].watermark
        assert fast_wm > slow_wm

        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))
        trigger.emit(time.monotonic(), "snap")

        ctx = received[0]
        # Convergence: fast and slow paths visible in same FusedContext
        slow_sample = ctx.samples["activity_mode"]
        fast_sample = ctx.samples["operator_present"]
        assert fast_sample.watermark > slow_sample.watermark
        # Provenance: min_watermark is from slow path
        assert ctx.min_watermark <= slow_wm


class TestProvenanceAcrossConvergentPaths:
    """Provenance remains traceable through convergent path merges."""

    def test_denied_by_from_dual_veto_chains_with_traceable_provenance(self):
        """T1+T3+T5: Two VetoChains evaluate, denials trace back to both."""
        ctx = FusedContext(
            trigger_time=time.monotonic(),
            trigger_value="x",
            samples={
                "activity_mode": Stamped(value="meeting", watermark=time.monotonic()),
                "sensor": Stamped(value="bad", watermark=time.monotonic() - 100.0),
            },
            min_watermark=time.monotonic() - 100.0,
        )

        # Path A: activity veto
        chain_a: VetoChain[FusedContext] = VetoChain([
            Veto(
                name="activity",
                predicate=lambda c: c.samples["activity_mode"].value != "meeting",
            ),
        ])
        veto_a = chain_a.evaluate(ctx)

        # Path B: freshness veto
        guard = FreshnessGuard([
            FreshnessRequirement(behavior_name="sensor", max_staleness_s=5.0),
        ])
        chain_b: VetoChain[FusedContext] = VetoChain([
            Veto(name="freshness", predicate=lambda c: guard.check(c, time.monotonic()).fresh_enough),
        ])
        veto_b = chain_b.evaluate(ctx)

        # Convergence: merge denials into Command
        all_denials = veto_a.denied_by + veto_b.denied_by
        cmd = Command(
            action="pause",
            params={"denials": list(all_denials)},
            governance_result=VetoResult(allowed=False, denied_by=tuple(all_denials)),
        )
        assert "activity" in cmd.governance_result.denied_by
        assert "freshness" in cmd.governance_result.denied_by
        assert len(cmd.governance_result.denied_by) == 2

    def test_watermark_provenance_through_convergent_combinator_paths(self):
        """T1+T3+T5: Two combinators, different behavior sets, min_watermarks differ."""
        now = time.monotonic()
        b_fast = Behavior("fast", watermark=now)
        b_slow = Behavior("slow", watermark=now - 50.0)

        trigger: Event[str] = Event()
        fused_fast = with_latest_from(trigger, {"sig": b_fast})
        fused_slow = with_latest_from(trigger, {"sig": b_slow})

        ctx_fast: list[FusedContext] = []
        ctx_slow: list[FusedContext] = []
        fused_fast.subscribe(lambda ts, ctx: ctx_fast.append(ctx))
        fused_slow.subscribe(lambda ts, ctx: ctx_slow.append(ctx))

        trigger.emit(now, "tick")

        # Provenance: different min_watermarks from different source ages
        assert ctx_fast[0].min_watermark == now
        assert ctx_slow[0].min_watermark == now - 50.0
        assert ctx_fast[0].min_watermark > ctx_slow[0].min_watermark

    def test_governance_result_provenance_from_merged_chains(self):
        """T1+T3+T5: VetoChain + FallbackChain merge into Command with full provenance."""
        state = _make_state(activity_mode="idle")

        # Path A: VetoChain
        chain: VetoChain[EnvironmentState] = VetoChain([
            Veto(
                name="mode_check",
                predicate=lambda s: s.activity_mode not in ("production", "meeting"),
            ),
        ])
        veto = chain.evaluate(state)

        # Path B: FallbackChain
        fallback: FallbackChain[EnvironmentState, str] = FallbackChain(
            candidates=[
                Candidate(name="special", predicate=lambda s: s.face_count > 5, action="alert"),
            ],
            default="process",
        )
        selected = fallback.select(state)

        # Convergence: merge provenance into Command
        cmd = Command(
            action=selected.action,
            params={"veto_allowed": veto.allowed},
            governance_result=veto,
            selected_by=selected.selected_by,
        )
        assert cmd.action == "process"
        assert cmd.governance_result.allowed is True
        assert cmd.selected_by == "default"
        assert isinstance(cmd.params, MappingProxyType)

    def test_trigger_source_provenance_through_dual_events(self):
        """T1+T3+T5: Two events with different sources, provenance in Commands."""
        b = Behavior("val", watermark=time.monotonic())

        ev_audio: Event[str] = Event()
        ev_visual: Event[str] = Event()
        fused_audio = with_latest_from(ev_audio, {"sig": b})
        fused_visual = with_latest_from(ev_visual, {"sig": b})

        ctx_audio: list[FusedContext] = []
        ctx_visual: list[FusedContext] = []
        fused_audio.subscribe(lambda ts, ctx: ctx_audio.append(ctx))
        fused_visual.subscribe(lambda ts, ctx: ctx_visual.append(ctx))

        now = time.monotonic()
        ev_audio.emit(now, "speech_onset")
        ev_visual.emit(now, "face_appear")

        cmd_audio = Command(
            action="process",
            trigger_source="audio",
            trigger_time=ctx_audio[0].trigger_time,
        )
        cmd_visual = Command(
            action="process",
            trigger_source="visual",
            trigger_time=ctx_visual[0].trigger_time,
        )

        # Provenance: different trigger sources, same trigger time
        assert cmd_audio.trigger_source == "audio"
        assert cmd_visual.trigger_source == "visual"
        assert cmd_audio.trigger_time == cmd_visual.trigger_time
        assert ctx_audio[0].trigger_value == "speech_onset"
        assert ctx_visual[0].trigger_value == "face_appear"


class TestCoherentSystemOutput:
    """System produces coherent, consistent outputs across convergent paths."""

    def test_dual_pipeline_produces_consistent_directives(self):
        """T1+T3+T5: Same state through two governors → same directive."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.update_slow_fields(activity_mode="meeting")
        engine.tick()

        gov_a = PipelineGovernor()
        gov_b = PipelineGovernor()

        directive_a = gov_a.evaluate(engine.latest)
        directive_b = gov_b.evaluate(engine.latest)

        # Coherence: same input → same output
        assert directive_a == directive_b == "pause"
        assert gov_a.last_veto_result.denied_by == gov_b.last_veto_result.denied_by

    def test_convergent_freshness_coherence(self):
        """T1+T3+T5: Two FusedContexts, FreshnessGuard consistent about staleness."""
        now = time.monotonic()
        ctx_fresh = FusedContext(
            trigger_time=now,
            trigger_value="a",
            samples={"sensor": Stamped(value=1.0, watermark=now)},
            min_watermark=now,
        )
        ctx_stale = FusedContext(
            trigger_time=now,
            trigger_value="b",
            samples={"sensor": Stamped(value=1.0, watermark=now - 100.0)},
            min_watermark=now - 100.0,
        )

        guard = FreshnessGuard([
            FreshnessRequirement(behavior_name="sensor", max_staleness_s=5.0),
        ])

        # Same guard, two contexts → coherent about which is stale
        fresh_result = guard.check(ctx_fresh, now)
        stale_result = guard.check(ctx_stale, now)

        assert fresh_result.fresh_enough is True
        assert stale_result.fresh_enough is False
        assert len(stale_result.violations) == 1

        # Convergence into commands with traceable freshness
        cmd_fresh = Command(action="process", params={"fresh": True})
        cmd_stale = Command(action="pause", params={"fresh": False})
        assert cmd_fresh.action != cmd_stale.action

    def test_provenance_coherence_across_schedule_wrapping(self):
        """T1+T3+T5: Commands from convergent paths → Schedules preserve provenance."""
        now = time.monotonic()
        veto_a = VetoResult(allowed=True)
        veto_b = VetoResult(allowed=False, denied_by=("staleness",))

        cmd_a = Command(
            action="process",
            trigger_source="audio",
            trigger_time=now,
            governance_result=veto_a,
            selected_by="default",
        )
        cmd_b = Command(
            action="pause",
            trigger_source="visual",
            trigger_time=now,
            governance_result=veto_b,
            selected_by="freshness_veto",
        )

        sched_a = Schedule(command=cmd_a, domain="wall", target_time=now)
        sched_b = Schedule(command=cmd_b, domain="wall", target_time=now)

        # Provenance preserved through Schedule wrapping
        assert sched_a.command.trigger_source == "audio"
        assert sched_b.command.trigger_source == "visual"
        assert sched_a.command.governance_result.allowed is True
        assert sched_b.command.governance_result.allowed is False
        assert "staleness" in sched_b.command.governance_result.denied_by

    def test_full_coherence_engine_to_dual_governance_to_schedule(self):
        """T1+T3+T5: End-to-end dual governance → convergent Schedules."""
        engine = _make_engine(face_detected=True, face_count=1)
        engine.tick()

        # Path A: Governor (direct state)
        gov = PipelineGovernor()
        directive = gov.evaluate(engine.latest)

        # Path B: Combinator → FreshnessGuard → VetoChain
        trigger: Event[str] = Event()
        fused = with_latest_from(trigger, engine.behaviors)
        received: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))
        trigger.emit(time.monotonic(), "tick")
        ctx = received[0]

        guard = FreshnessGuard([
            FreshnessRequirement(behavior_name="operator_present", max_staleness_s=30.0),
        ])
        freshness = guard.check(ctx, time.monotonic())

        # Both paths → Commands → Schedules
        cmd_a = Command(
            action=directive,
            trigger_source="governor",
            min_watermark=engine.min_watermark,
            governance_result=gov.last_veto_result,
            selected_by=gov.last_selected.selected_by,
        )
        cmd_b = Command(
            action="process" if freshness.fresh_enough else "pause",
            trigger_source="combinator",
            min_watermark=ctx.min_watermark,
            params={"fresh": freshness.fresh_enough},
        )

        sched_a = Schedule(command=cmd_a)
        sched_b = Schedule(command=cmd_b)

        # Coherence: both paths agree
        assert sched_a.command.action == sched_b.command.action == "process"
        # Provenance: different sources, both traceable
        assert sched_a.command.trigger_source == "governor"
        assert sched_b.command.trigger_source == "combinator"
        assert sched_a.command.min_watermark > 0
        assert sched_b.command.min_watermark > 0
        assert isinstance(sched_b.command.params, MappingProxyType)
