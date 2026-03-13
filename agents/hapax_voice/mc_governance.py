"""MC-specific governance constraints for the Backup MC use case.

Composes VetoChain, FallbackChain, and FreshnessGuard from the general-purpose
governance primitives into a domain-specific pipeline:
  trigger Event → with_latest_from → FreshnessGuard → VetoChain → FallbackChain → Schedule
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

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
)
from agents.hapax_voice.primitives import Behavior, Event
from agents.hapax_voice.timeline import TimelineMapping, TransportState


class MCAction(Enum):
    """Possible MC interjection types, ordered by intensity."""

    VOCAL_THROW = "vocal_throw"
    AD_LIB = "ad_lib"
    SILENCE = "silence"


@dataclass(frozen=True)
class MCConfig:
    """Tunable thresholds for MC governance constraints."""

    # VetoChain thresholds
    speech_vad_threshold: float = 0.5
    energy_min_threshold: float = 0.3
    spacing_cooldown_s: float = 4.0

    # FallbackChain thresholds
    vocal_throw_energy_min: float = 0.7
    vocal_throw_arousal_min: float = 0.6
    ad_lib_energy_min: float = 0.3
    ad_lib_arousal_min: float = 0.3

    # FreshnessGuard limits
    energy_max_staleness_s: float = 0.2
    emotion_max_staleness_s: float = 3.0
    timeline_max_staleness_s: float = 0.5


# ---------------------------------------------------------------------------
# Veto predicates — module-level functions for testability
# ---------------------------------------------------------------------------


def speech_clear(ctx: FusedContext, threshold: float = 0.5) -> bool:
    """Allow when no speech detected (VAD below threshold). Block during speech."""
    return ctx.get_sample("vad_confidence").value < threshold


def energy_sufficient(ctx: FusedContext, threshold: float = 0.3) -> bool:
    """Allow when audio energy RMS is at or above threshold."""
    return ctx.get_sample("audio_energy_rms").value >= threshold


def spacing_respected(
    ctx: FusedContext, cooldown_s: float = 4.0, last_throw_time: list[float] | None = None
) -> bool:
    """Allow when enough time has elapsed since the last throw.

    last_throw_time is a single-element mutable list holding the timestamp of the
    most recent throw. If None or empty, the first throw is always permitted.
    """
    if last_throw_time is None or len(last_throw_time) == 0:
        return True
    return (ctx.trigger_time - last_throw_time[0]) >= cooldown_s


def transport_active(ctx: FusedContext) -> bool:
    """Allow when timeline transport is PLAYING. Block when STOPPED."""
    mapping: TimelineMapping = ctx.get_sample("timeline_mapping").value
    return mapping.transport is TransportState.PLAYING


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def build_mc_veto_chain(
    cfg: MCConfig | None = None,
    last_throw_time: list[float] | None = None,
) -> VetoChain[FusedContext]:
    """Construct the MC-specific VetoChain.

    Four vetoes, all evaluated (order-independent, deny-wins):
      - speech_clear: block throws during detected speech
      - energy_sufficient: block when audio energy too low
      - spacing_respected: minimum cooldown between throws
      - transport_active: block when transport stopped
    """
    c = cfg or MCConfig()
    return VetoChain(
        [
            Veto(
                name="speech_clear",
                predicate=lambda ctx, t=c.speech_vad_threshold: speech_clear(ctx, t),
            ),
            Veto(
                name="energy_sufficient",
                predicate=lambda ctx, t=c.energy_min_threshold: energy_sufficient(ctx, t),
            ),
            Veto(
                name="spacing_respected",
                predicate=lambda ctx, cd=c.spacing_cooldown_s, lt=last_throw_time: (
                    spacing_respected(ctx, cd, lt)
                ),
            ),
            Veto(
                name="transport_active",
                predicate=transport_active,
            ),
        ]
    )


def build_mc_fallback_chain(cfg: MCConfig | None = None) -> FallbackChain[FusedContext, MCAction]:
    """Construct the MC-specific FallbackChain.

    Priority order (first eligible wins):
      1. vocal_throw: energy >= 0.7 AND arousal >= 0.6
      2. ad_lib: energy >= 0.3 AND arousal >= 0.3
      3. silence (default)
    """
    c = cfg or MCConfig()
    return FallbackChain(
        candidates=[
            Candidate(
                name="vocal_throw",
                predicate=lambda ctx, e=c.vocal_throw_energy_min, a=c.vocal_throw_arousal_min: (
                    ctx.get_sample("audio_energy_rms").value >= e
                    and ctx.get_sample("emotion_arousal").value >= a
                ),
                action=MCAction.VOCAL_THROW,
            ),
            Candidate(
                name="ad_lib",
                predicate=lambda ctx, e=c.ad_lib_energy_min, a=c.ad_lib_arousal_min: (
                    ctx.get_sample("audio_energy_rms").value >= e
                    and ctx.get_sample("emotion_arousal").value >= a
                ),
                action=MCAction.AD_LIB,
            ),
        ],
        default=MCAction.SILENCE,
    )


def build_mc_freshness_guard(cfg: MCConfig | None = None) -> FreshnessGuard:
    """Construct the MC-specific FreshnessGuard.

    Requirements:
      - audio_energy_rms: max 200ms stale
      - emotion_arousal: max 3s stale
      - timeline_mapping: max 500ms stale
    """
    c = cfg or MCConfig()
    return FreshnessGuard(
        [
            FreshnessRequirement("audio_energy_rms", c.energy_max_staleness_s),
            FreshnessRequirement("emotion_arousal", c.emotion_max_staleness_s),
            FreshnessRequirement("timeline_mapping", c.timeline_max_staleness_s),
        ]
    )


# ---------------------------------------------------------------------------
# Compose — full MC governance pipeline
# ---------------------------------------------------------------------------


def compose_mc_governance(
    trigger: Event,
    behaviors: dict[str, Behavior],
    cfg: MCConfig | None = None,
) -> Event[Schedule | None]:
    """Wire the full MC governance pipeline.

    trigger Event
      → with_latest_from(behaviors)
      → FreshnessGuard check
      → VetoChain evaluate
      → FallbackChain select
      → Schedule (or None if vetoed/stale)

    Returns an Event that emits Schedule on allowed actions, None on denial.
    """
    c = cfg or MCConfig()
    last_throw_time: list[float] = []

    freshness = build_mc_freshness_guard(c)
    veto_chain = build_mc_veto_chain(c, last_throw_time)
    fallback = build_mc_fallback_chain(c)

    fused: Event[FusedContext] = with_latest_from(trigger, behaviors)
    output: Event[Schedule | None] = Event()

    def _on_fused(timestamp: float, ctx: FusedContext) -> None:
        # 1. Freshness gate — reject stale signals before reading values
        freshness_result = freshness.check(ctx, now=timestamp)
        if not freshness_result.fresh_enough:
            output.emit(timestamp, None)
            return

        # 2. VetoChain — deny-wins safety constraints
        veto_result = veto_chain.evaluate(ctx)
        if not veto_result.allowed:
            output.emit(timestamp, None)
            return

        # 3. FallbackChain — select action
        selected = fallback.select(ctx)

        # 4. Build Schedule with full provenance
        mapping: TimelineMapping = ctx.get_sample("timeline_mapping").value
        current_beat = mapping.beat_at_time(timestamp)
        target_beat = current_beat + 4.0  # schedule 4 beats ahead
        wall_time = mapping.time_at_beat(target_beat)

        cmd = Command(
            action=selected.action.value,
            trigger_time=timestamp,
            trigger_source="mc_governance",
            min_watermark=ctx.min_watermark,
            governance_result=veto_result,
            selected_by=selected.selected_by,
        )
        schedule = Schedule(
            command=cmd,
            domain="beat",
            target_time=target_beat,
            wall_time=wall_time,
        )

        # Record throw time for spacing cooldown
        if selected.action is not MCAction.SILENCE:
            if last_throw_time:
                last_throw_time[0] = timestamp
            else:
                last_throw_time.append(timestamp)

        output.emit(timestamp, schedule)

    fused.subscribe(_on_fused)
    return output
