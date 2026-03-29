"""OBS livestream direction governance — the second actuation domain.

Composes VetoChain, FallbackChain, and FreshnessGuard from the general-purpose
governance primitives into a livestream-specific pipeline:
  tick Event → with_latest_from → FreshnessGuard → VetoChain → FallbackChain → Command

Architectural validation: this module uses the same primitives as mc_governance.py
with different predicates and thresholds. No new infrastructure was required.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from agents.hapax_daimonion.combinator import with_latest_from
from agents.hapax_daimonion.commands import Command
from agents.hapax_daimonion.governance import (
    Candidate,
    FallbackChain,
    FreshnessGuard,
    FreshnessRequirement,
    FusedContext,
    Veto,
    VetoChain,
)
from agents.hapax_daimonion.primitives import Behavior, Event
from agents.hapax_daimonion.timeline import TimelineMapping, TransportState


class OBSScene(Enum):
    """Available camera scenes, ordered from calmest to most intense."""

    WIDE_AMBIENT = "wide_ambient"
    GEAR_CLOSEUP = "gear_closeup"
    FACE_CAM = "face_cam"
    RAPID_CUT = "rapid_cut"
    HOLD = "hold"  # no scene change


class OBSTransition(Enum):
    """Transition styles between scenes."""

    CUT = "cut"
    DISSOLVE = "dissolve"
    FADE = "fade"


@dataclass(frozen=True)
class OBSConfig:
    """Tunable thresholds for OBS governance constraints."""

    # VetoChain thresholds
    dwell_min_s: float = 5.0  # minimum time on a scene (~2 bars at 96 BPM)
    stream_health_min_bitrate_kbps: float = 2000.0
    encoding_lag_max_ms: float = 100.0
    dropped_frames_max_pct: float = 5.0

    # FallbackChain thresholds
    rapid_cut_energy_min: float = 0.8
    rapid_cut_arousal_min: float = 0.7
    face_cam_energy_min: float = 0.5
    face_cam_arousal_min: float = 0.5
    gear_closeup_energy_min: float = 0.2

    # Transition thresholds
    hard_cut_energy_min: float = 0.6  # above → cut, below → dissolve/fade

    # FreshnessGuard limits
    energy_max_staleness_s: float = 3.0  # perception cadence, not beat precision
    emotion_max_staleness_s: float = 5.0
    stream_health_max_staleness_s: float = 10.0


# ---------------------------------------------------------------------------
# Veto predicates — module-level functions for testability
# ---------------------------------------------------------------------------


def dwell_time_respected(
    ctx: FusedContext, min_dwell_s: float = 5.0, last_switch_time: list[float] | None = None
) -> bool:
    """Allow when enough time has elapsed since the last scene switch.

    Same pattern as MC spacing_respected — governance constraint on temporal spacing.
    """
    if last_switch_time is None or len(last_switch_time) == 0:
        return True
    return (ctx.trigger_time - last_switch_time[0]) >= min_dwell_s


def stream_health_sufficient(ctx: FusedContext, min_bitrate_kbps: float = 2000.0) -> bool:
    """Allow when stream bitrate is at or above minimum threshold."""
    return ctx.get_sample("stream_bitrate").value >= min_bitrate_kbps


def encoding_capacity_available(ctx: FusedContext, max_lag_ms: float = 100.0) -> bool:
    """Allow when encoding lag is within acceptable bounds."""
    return ctx.get_sample("stream_encoding_lag").value <= max_lag_ms


def transport_active(ctx: FusedContext) -> bool:
    """Allow when timeline transport is PLAYING. Block when STOPPED."""
    mapping: TimelineMapping = ctx.get_sample("timeline_mapping").value
    return mapping.transport is TransportState.PLAYING


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def build_obs_veto_chain(
    cfg: OBSConfig | None = None,
    last_switch_time: list[float] | None = None,
) -> VetoChain[FusedContext]:
    """Construct the OBS-specific VetoChain.

    Four vetoes, all evaluated (order-independent, deny-wins):
      - dwell_time_respected: minimum time on a scene before switching
      - stream_health_sufficient: block complex transitions when bitrate drops
      - encoding_capacity_available: block when encoder is overloaded
      - transport_active: block when transport stopped
    """
    c = cfg or OBSConfig()
    return VetoChain(
        [
            Veto(
                name="dwell_time_respected",
                predicate=lambda ctx, d=c.dwell_min_s, lt=last_switch_time: dwell_time_respected(
                    ctx, d, lt
                ),
            ),
            Veto(
                name="stream_health_sufficient",
                predicate=lambda ctx, b=c.stream_health_min_bitrate_kbps: stream_health_sufficient(
                    ctx, b
                ),
            ),
            Veto(
                name="encoding_capacity_available",
                predicate=lambda ctx, l=c.encoding_lag_max_ms: encoding_capacity_available(ctx, l),
            ),
            Veto(
                name="transport_active",
                predicate=transport_active,
            ),
        ]
    )


def build_obs_fallback_chain(cfg: OBSConfig | None = None) -> FallbackChain[FusedContext, OBSScene]:
    """Construct the OBS-specific FallbackChain.

    Priority order (first eligible wins):
      1. rapid_cut: energy >= 0.8 AND arousal >= 0.7 (peak energy moments)
      2. face_cam: energy >= 0.5 AND arousal >= 0.5 (engaged performance)
      3. instrument_focus: desk_activity in (scratching, drumming, tapping)
      4. gear_closeup: energy >= 0.2 (active but calm — building/sustain)
      5. wide_ambient (default — silence/low energy)
    """
    c = cfg or OBSConfig()
    return FallbackChain(
        candidates=[
            Candidate(
                name="rapid_cut",
                predicate=lambda ctx, e=c.rapid_cut_energy_min, a=c.rapid_cut_arousal_min: (
                    ctx.get_sample("audio_energy_rms").value >= e
                    and ctx.get_sample("emotion_arousal").value >= a
                ),
                action=OBSScene.RAPID_CUT,
            ),
            Candidate(
                name="face_cam_mc_bias",
                predicate=lambda ctx, e=c.face_cam_energy_min: (
                    _mc_fired_recently(ctx) and ctx.get_sample("audio_energy_rms").value >= e
                ),
                action=OBSScene.FACE_CAM,
            ),
            Candidate(
                name="face_cam",
                predicate=lambda ctx, e=c.face_cam_energy_min, a=c.face_cam_arousal_min: (
                    ctx.get_sample("audio_energy_rms").value >= e
                    and ctx.get_sample("emotion_arousal").value >= a
                ),
                action=OBSScene.FACE_CAM,
            ),
            Candidate(
                name="instrument_focus",
                predicate=lambda ctx: (
                    ctx.get_sample("desk_activity").value in ("scratching", "drumming", "tapping")
                    if "desk_activity" in ctx.samples
                    else False
                ),
                action=OBSScene.GEAR_CLOSEUP,
            ),
            Candidate(
                name="gear_closeup",
                predicate=lambda ctx, e=c.gear_closeup_energy_min: (
                    ctx.get_sample("audio_energy_rms").value >= e
                ),
                action=OBSScene.GEAR_CLOSEUP,
            ),
        ],
        default=OBSScene.WIDE_AMBIENT,
    )


def build_obs_freshness_guard(cfg: OBSConfig | None = None) -> FreshnessGuard:
    """Construct the OBS-specific FreshnessGuard.

    Requirements:
      - audio_energy_rms: max 3s stale (perception cadence, not beat)
      - emotion_arousal: max 5s stale (visual slower than audio)
      - stream_bitrate: max 10s stale (stream stats don't change fast)
    """
    c = cfg or OBSConfig()
    return FreshnessGuard(
        [
            FreshnessRequirement("audio_energy_rms", c.energy_max_staleness_s),
            FreshnessRequirement("emotion_arousal", c.emotion_max_staleness_s),
            FreshnessRequirement("stream_bitrate", c.stream_health_max_staleness_s),
        ]
    )


def _mc_fired_recently(ctx: FusedContext, window_s: float = 2.0) -> bool:
    """Check if MC fired within the given window. Used for feedback-driven bias."""
    try:
        last_mc_fire = ctx.get_sample("last_mc_fire").value
    except KeyError:
        return False
    return (ctx.trigger_time - last_mc_fire) <= window_s and last_mc_fire > 0


def select_transition(ctx: FusedContext, cfg: OBSConfig | None = None) -> OBSTransition:
    """Select transition style based on current energy level.

    High energy → hard cut (immediate, energetic)
    Low energy → dissolve or fade (smooth, calm)
    """
    c = cfg or OBSConfig()
    energy = ctx.get_sample("audio_energy_rms").value
    if energy >= c.hard_cut_energy_min:
        return OBSTransition.CUT
    return OBSTransition.DISSOLVE


# ---------------------------------------------------------------------------
# Compose — full OBS governance pipeline
# ---------------------------------------------------------------------------


def compose_obs_governance(
    trigger: Event,
    behaviors: dict[str, Behavior],
    cfg: OBSConfig | None = None,
) -> Event[Command | None]:
    """Wire the full OBS governance pipeline.

    tick Event
      → with_latest_from(behaviors)
      → FreshnessGuard check
      → VetoChain evaluate
      → FallbackChain select
      → Command (or None if vetoed/stale)

    Unlike MC governance which produces Schedules (beat-aligned future actions),
    OBS governance produces Commands (immediate actuation at perception cadence).

    Raises ValueError if required behaviors are missing from the dict (D6.3).
    """
    c = cfg or OBSConfig()
    last_switch_time: list[float] = []

    freshness = build_obs_freshness_guard(c)
    veto_chain = build_obs_veto_chain(c, last_switch_time)
    fallback = build_obs_fallback_chain(c)

    # D6.3: validate behavior keys at composition time, not at first tick
    required = {r.behavior_name for r in freshness._requirements}
    required |= {"audio_energy_rms", "emotion_arousal", "timeline_mapping"}
    missing = required - frozenset(behaviors)
    if missing:
        raise ValueError(f"OBS governance missing required behaviors: {missing}")

    fused: Event[FusedContext] = with_latest_from(trigger, behaviors)
    output: Event[Command | None] = Event()

    def _on_fused(timestamp: float, ctx: FusedContext) -> None:
        # 1. Freshness gate
        freshness_result = freshness.check(ctx, now=timestamp)
        if not freshness_result.fresh_enough:
            output.emit(timestamp, None)
            return

        # 2. VetoChain — deny-wins safety constraints
        veto_result = veto_chain.evaluate(ctx)
        if not veto_result.allowed:
            output.emit(timestamp, None)
            return

        # 3. FallbackChain — select scene
        selected = fallback.select(ctx)

        # 4. Select transition style
        transition = select_transition(ctx, c)

        # 5. Build Command with full provenance
        cmd = Command(
            action=selected.action.value,
            params={"transition": transition.value},
            trigger_time=timestamp,
            trigger_source="obs_governance",
            min_watermark=ctx.min_watermark,
            governance_result=veto_result,
            selected_by=selected.selected_by,
            consent_label=ctx.consent_label,
        )

        # Record switch time for dwell cooldown
        if selected.action is not OBSScene.HOLD:
            if last_switch_time:
                last_switch_time[0] = timestamp
            else:
                last_switch_time.append(timestamp)

        output.emit(timestamp, cmd)

    fused.subscribe(_on_fused)
    return output
