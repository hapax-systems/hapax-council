"""Integration tests: Backup MC composition — multi-cadence perception to schedule.

Proves the full wiring: clock Event → with_latest_from(energy, emotion, timeline)
→ VetoChain → Schedule, using only the general-purpose primitives.
"""

from __future__ import annotations

import time

from agents.hapax_voice.combinator import with_latest_from
from agents.hapax_voice.commands import Command, Schedule
from agents.hapax_voice.governance import (
    FreshnessGuard,
    FreshnessRequirement,
    FusedContext,
    Veto,
    VetoChain,
)
from agents.hapax_voice.primitives import Behavior, Event
from agents.hapax_voice.timeline import TimelineMapping, TransportState


def _make_behaviors(
    *,
    energy_rms: float = 0.7,
    emotion_valence: float = 0.5,
    tempo: float = 120.0,
    transport: TransportState = TransportState.PLAYING,
    ref_time: float = 1000.0,
    watermark: float | None = None,
) -> dict[str, Behavior]:
    """Create a set of behaviors for the backup MC use case."""
    wm = watermark if watermark is not None else time.monotonic()
    mapping = TimelineMapping(
        reference_time=ref_time,
        reference_beat=0.0,
        tempo=tempo,
        transport=transport,
    )
    return {
        "audio_energy_rms": Behavior(energy_rms, watermark=wm),
        "emotion_valence": Behavior(emotion_valence, watermark=wm),
        "timeline_mapping": Behavior(mapping, watermark=wm),
    }


def _build_veto_chain() -> VetoChain[FusedContext]:
    """Veto chain: energy must exceed threshold."""
    return VetoChain([
        Veto(
            name="energy_threshold",
            predicate=lambda ctx: ctx.samples["audio_energy_rms"].value >= 0.3,
            description="Block when energy is too low for MC interjection",
        ),
    ])


class TestBackupMCComposition:
    def test_midi_clock_to_schedule(self):
        """Clock Event → with_latest_from → VetoChain → Schedule with correct wall_time."""
        clock_event: Event[float] = Event()
        behaviors = _make_behaviors(ref_time=1000.0, tempo=120.0)
        fused_event = with_latest_from(clock_event, behaviors)

        veto_chain = _build_veto_chain()
        schedules: list[Schedule] = []

        def _on_fused(ts: float, ctx: FusedContext) -> None:
            result = veto_chain.evaluate(ctx)
            if not result.allowed:
                return
            mapping: TimelineMapping = ctx.samples["timeline_mapping"].value
            target_beat = mapping.beat_at_time(ts) + 4.0  # schedule 4 beats ahead
            wall_time = mapping.time_at_beat(target_beat)
            cmd = Command(
                action="mc_interjection",
                trigger_time=ts,
                trigger_source="midi_clock",
                governance_result=result,
            )
            schedules.append(Schedule(
                command=cmd,
                domain="beat",
                target_time=target_beat,
                wall_time=wall_time,
            ))

        fused_event.subscribe(_on_fused)

        # Simulate a clock tick at t=1001.0 (1s in, beat 2.0 at 120 BPM)
        clock_event.emit(1001.0, 1001.0)

        assert len(schedules) == 1
        s = schedules[0]
        assert s.command.action == "mc_interjection"
        assert s.domain == "beat"
        # At t=1001, beat=2.0; target=6.0; wall_time = 1000 + 6*(60/120) = 1003.0
        assert s.target_time == 6.0
        assert abs(s.wall_time - 1003.0) < 1e-6

    def test_energy_below_threshold_vetoed(self):
        """Low energy → VetoChain denies, no schedule produced."""
        clock_event: Event[float] = Event()
        behaviors = _make_behaviors(energy_rms=0.1)  # below 0.3 threshold
        fused_event = with_latest_from(clock_event, behaviors)

        veto_chain = _build_veto_chain()
        schedules: list[Schedule] = []

        def _on_fused(ts: float, ctx: FusedContext) -> None:
            result = veto_chain.evaluate(ctx)
            if not result.allowed:
                return
            schedules.append(Schedule(
                command=Command(action="mc_interjection", trigger_time=ts),
                domain="beat",
            ))

        fused_event.subscribe(_on_fused)
        clock_event.emit(1001.0, 1001.0)

        assert len(schedules) == 0

    def test_transport_stopped_no_schedule(self):
        """STOPPED timeline → beat frozen → schedule not produced (same beat every time)."""
        clock_event: Event[float] = Event()
        behaviors = _make_behaviors(transport=TransportState.STOPPED)
        fused_event = with_latest_from(clock_event, behaviors)

        beats_seen: list[float] = []

        def _on_fused(ts: float, ctx: FusedContext) -> None:
            mapping: TimelineMapping = ctx.samples["timeline_mapping"].value
            beats_seen.append(mapping.beat_at_time(ts))

        fused_event.subscribe(_on_fused)

        # Multiple ticks at different wall times — beat is always frozen
        clock_event.emit(1001.0, 1001.0)
        clock_event.emit(1005.0, 1005.0)
        clock_event.emit(1010.0, 1010.0)

        assert all(b == 0.0 for b in beats_seen)

    def test_freshness_guard_rejects_stale_energy(self):
        """Stale energy watermark → FreshnessGuard rejects."""
        now = time.monotonic()
        stale_wm = now - 10.0  # 10 seconds stale

        clock_event: Event[float] = Event()
        behaviors = _make_behaviors(watermark=stale_wm)
        fused_event = with_latest_from(clock_event, behaviors)

        guard = FreshnessGuard([
            FreshnessRequirement(behavior_name="audio_energy_rms", max_staleness_s=5.0),
        ])

        results: list[bool] = []

        def _on_fused(ts: float, ctx: FusedContext) -> None:
            freshness = guard.check(ctx, now=ts)
            results.append(freshness.fresh_enough)

        fused_event.subscribe(_on_fused)
        clock_event.emit(now, now)

        assert len(results) == 1
        assert results[0] is False
