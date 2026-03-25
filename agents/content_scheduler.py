"""Content scheduler — weighted softmax sampler for ambient content decisions.

Pure-logic module: no I/O, no threading, no network. Receives context and
content pools, returns decisions about what to show when. Replaces random
heuristics (_rotate_ambient_text, _maybe_inject_camera) with intelligent
selection based on activity, flow, biometrics, and time.

Architecture:
  Aggregator.compute_and_write() calls ContentScheduler.tick() each cycle.
  Scheduler scores all content sources, applies softmax temperature selection,
  and returns a SchedulerDecision (or None if no injection this tick).

Design: ADHD/autism operator — display is functional stochastic resonance.
Emptiness is hostile. Stimulation through variation, not distraction.
"""

from __future__ import annotations

import math
import random
import time
from enum import StrEnum

from pydantic import BaseModel, Field

# ── Content Sources ─────────────────────────────────────────────────────────


class ContentSource(StrEnum):
    """Injectable content types the scheduler can select."""

    PROFILE_FACT = "profile_fact"
    CAMERA_FEED = "camera_feed"
    SHADER_VARIATION = "shader_variation"
    STUDIO_MOMENT = "studio_moment"
    SIGNAL_CARD = "signal_card"
    VOICE_STATE = "voice_state"
    ACTIVITY_LABEL = "activity_label"
    BIOMETRIC_MOD = "biometric_mod"
    TIME_OF_DAY = "time_of_day"
    SUPPLEMENTARY_CARD = "supplementary_card"


# ── Display Density ─────────────────────────────────────────────────────────


class DisplayDensity(StrEnum):
    """Content density mode — controls injection rate and temperature."""

    AMBIENT = "ambient"  # Normal: 2-4 elements, balanced
    FOCUSED = "focused"  # Deep work: minimal, low temperature
    RECEPTIVE = "receptive"  # Idle/browsing: rich, high temperature
    PRESENTING = "presenting"  # Meeting/presenting: near-silent


class DensityParams(BaseModel, frozen=True):
    """Per-density tuning parameters."""

    min_elements: int
    max_elements: int
    temperature: float
    inject_probability: float
    tick_interval_s: float


DENSITY_PARAMS: dict[DisplayDensity, DensityParams] = {
    DisplayDensity.AMBIENT: DensityParams(
        min_elements=2,
        max_elements=4,
        temperature=1.0,
        inject_probability=0.6,
        tick_interval_s=15.0,
    ),
    DisplayDensity.FOCUSED: DensityParams(
        min_elements=0,
        max_elements=2,
        temperature=0.5,
        inject_probability=0.3,
        tick_interval_s=30.0,
    ),
    DisplayDensity.RECEPTIVE: DensityParams(
        min_elements=3,
        max_elements=6,
        temperature=2.0,
        inject_probability=0.8,
        tick_interval_s=10.0,
    ),
    DisplayDensity.PRESENTING: DensityParams(
        min_elements=0,
        max_elements=1,
        temperature=0.3,
        inject_probability=0.1,
        tick_interval_s=60.0,
    ),
}


# ── Source Configuration ────────────────────────────────────────────────────


class SourceConfig(BaseModel, frozen=True):
    """Per-source tuning knobs."""

    source: ContentSource
    base_weight: float = 1.0
    half_life_s: float = 120.0  # freshness decay
    min_dwell_s: float = 20.0
    max_dwell_s: float = 60.0
    notification_level: str = "change_blind"  # ignore | change_blind | make_aware | interrupt


DEFAULT_SOURCE_CONFIGS: list[SourceConfig] = [
    SourceConfig(
        source=ContentSource.PROFILE_FACT,
        base_weight=1.5,
        half_life_s=180.0,
        min_dwell_s=25.0,
        max_dwell_s=60.0,
    ),
    SourceConfig(
        source=ContentSource.CAMERA_FEED,
        base_weight=0.8,
        half_life_s=90.0,
        min_dwell_s=30.0,
        max_dwell_s=60.0,
    ),
    SourceConfig(
        source=ContentSource.SHADER_VARIATION,
        base_weight=0.6,
        half_life_s=300.0,
        min_dwell_s=30.0,
        max_dwell_s=120.0,
    ),
    SourceConfig(
        source=ContentSource.STUDIO_MOMENT,
        base_weight=1.0,
        half_life_s=120.0,
        min_dwell_s=20.0,
        max_dwell_s=45.0,
    ),
    SourceConfig(
        source=ContentSource.SIGNAL_CARD,
        base_weight=0.7,
        half_life_s=60.0,
        min_dwell_s=15.0,
        max_dwell_s=30.0,
    ),
    SourceConfig(
        source=ContentSource.VOICE_STATE,
        base_weight=0.3,
        half_life_s=30.0,
        min_dwell_s=10.0,
        max_dwell_s=20.0,
    ),
    SourceConfig(
        source=ContentSource.ACTIVITY_LABEL,
        base_weight=0.4,
        half_life_s=60.0,
        min_dwell_s=15.0,
        max_dwell_s=30.0,
    ),
    SourceConfig(
        source=ContentSource.BIOMETRIC_MOD,
        base_weight=0.5,
        half_life_s=120.0,
        min_dwell_s=20.0,
        max_dwell_s=60.0,
    ),
    SourceConfig(
        source=ContentSource.TIME_OF_DAY,
        base_weight=0.3,
        half_life_s=600.0,
        min_dwell_s=60.0,
        max_dwell_s=180.0,
    ),
    SourceConfig(
        source=ContentSource.SUPPLEMENTARY_CARD,
        base_weight=1.2,
        half_life_s=90.0,
        min_dwell_s=20.0,
        max_dwell_s=45.0,
    ),
]


# ── Relevance Matrix ───────────────────────────────────────────────────────
# Maps (source, activity) → relevance multiplier. Missing = 1.0.

RELEVANCE_MATRIX: dict[ContentSource, dict[str, float]] = {
    ContentSource.PROFILE_FACT: {
        "present": 1.5,
        "browsing": 1.3,
        "coding": 0.8,
        "making music": 0.6,
        "in a meeting": 0.3,
        "talking to hapax": 0.5,
        "deep work": 0.7,
    },
    ContentSource.CAMERA_FEED: {
        "coding": 0.1,
        "deep work": 0.2,
        "present": 1.2,
        "browsing": 0.8,
        "making music": 1.0,
        "in a meeting": 0.0,
        "talking to hapax": 0.3,
    },
    ContentSource.SHADER_VARIATION: {
        "making music": 1.3,
        "coding": 0.8,
        "present": 1.0,
        "deep work": 0.6,
        "in a meeting": 0.3,
    },
    ContentSource.STUDIO_MOMENT: {
        "making music": 1.5,
        "present": 1.0,
        "coding": 0.5,
        "in a meeting": 0.2,
    },
    ContentSource.SIGNAL_CARD: {
        "present": 1.2,
        "browsing": 1.0,
        "coding": 0.6,
        "deep work": 0.4,
        "in a meeting": 0.2,
    },
    ContentSource.VOICE_STATE: {
        "talking to hapax": 2.0,
    },
    ContentSource.SUPPLEMENTARY_CARD: {
        "talking to hapax": 1.5,
        "present": 1.0,
        "browsing": 0.8,
        "coding": 0.5,
    },
}


# ── Context & Decision Models ──────────────────────────────────────────────


class SchedulerContext(BaseModel):
    """All inputs the scheduler needs — passed in, no I/O."""

    activity: str = "present"
    flow_score: float = 0.0
    audio_energy: float = 0.0
    stress_elevated: bool = False
    heart_rate: int = 0
    sleep_quality: float = 1.0
    voice_active: bool = False
    display_state: str = "ambient"
    hour: int = 12
    signal_count: int = 0
    # Phase 6: temporal context from perception ring
    trend_flow: float = 0.0  # flow_score trend (slope/s)
    trend_audio: float = 0.0  # audio_energy trend (slope/s)
    perception_age_s: float = 0.0  # staleness of perception data
    # WS2: system self-state
    stimmung_stance: str = "nominal"
    # Classification consumption: enriched perception signals
    gaze_direction: str = "unknown"  # screen | away | down | unknown
    emotion: str = "neutral"  # happy | sad | angry | fear | neutral | ...
    posture: str = "unknown"  # upright | slouching | leaning | unknown
    recent_transition: bool = False  # BOCPD detected activity change in last 30s


class ContentPools(BaseModel):
    """Available content the scheduler can draw from."""

    facts: list[str] = Field(default_factory=list)
    moments: list[str] = Field(default_factory=list)
    nudge_titles: list[str] = Field(default_factory=list)
    camera_roles: list[str] = Field(default_factory=list)
    camera_filters: list[str] = Field(default_factory=list)
    pool_age_s: float = 0.0  # seconds since pools were last refreshed


MAX_POOL_AGE_S = 120.0  # refuse content from pools older than 2 minutes


class ShaderNudge(BaseModel):
    """Subtle shader parameter adjustments from the scheduler."""

    speed_mult: float = 1.0
    turbulence_mult: float = 1.0
    warmth_offset: float = 0.0
    brightness_offset: float = 0.0


class SchedulerDecision(BaseModel):
    """What the scheduler decided to inject this tick."""

    source: ContentSource
    content: str = ""  # the actual text/role/label to display
    dwell_s: float = 30.0
    notification_level: str = "change_blind"
    # Camera-specific fields
    camera_role: str = ""
    camera_filter: str = ""
    camera_x: float = 0.6
    camera_y: float = 0.3
    camera_w: float = 0.35
    camera_h: float = 0.35
    camera_opacity: float = 0.5
    # Shader nudge (always present, neutral by default)
    shader_nudge: ShaderNudge = Field(default_factory=ShaderNudge)


# ── Content Scheduler ──────────────────────────────────────────────────────


class ContentScheduler:
    """Weighted softmax sampler for ambient content selection.

    Pure logic — no I/O. Gets context and content pools via tick(),
    returns a decision or None. Microsecond budget per tick.
    """

    def __init__(self, configs: list[SourceConfig] | None = None) -> None:
        self._configs = {c.source: c for c in (configs or DEFAULT_SOURCE_CONFIGS)}
        self._last_selected: dict[ContentSource, float | None] = {}
        self._selection_counts: dict[ContentSource, int] = {s: 0 for s in ContentSource}
        self._last_tick: float = 0.0
        self._fact_history: list[str] = []  # avoid recent repetition
        self._rng = random.Random()

    def tick(
        self,
        context: SchedulerContext,
        content_pools: ContentPools,
        now: float | None = None,
    ) -> SchedulerDecision | None:
        """Run one scheduling cycle. Returns a decision or None."""
        if now is None:
            now = time.monotonic()

        density = self._compute_density(context)
        params = DENSITY_PARAMS[density]

        # Respect tick interval
        if now - self._last_tick < params.tick_interval_s:
            return None
        self._last_tick = now

        # Probabilistic gate
        if self._rng.random() > params.inject_probability:
            return None

        # Filter to sources that have content available
        available = self._available_sources(context, content_pools)
        if not available:
            return None

        # Score and select
        scores = {s: self._score_source(s, context, now) for s in available}
        selected = self._softmax_sample(scores, params.temperature)
        if selected is None:
            return None

        # Build decision
        config = self._configs.get(selected, SourceConfig(source=selected))
        decision = self._build_decision(selected, config, context, content_pools, now)

        # Record
        self._last_selected[selected] = now
        self._selection_counts[selected] = self._selection_counts.get(selected, 0) + 1

        return decision

    def _compute_density(self, ctx: SchedulerContext) -> DisplayDensity:
        """Derive display density from context + temporal trends + stimmung."""
        if ctx.activity in ("in a meeting", "presenting"):
            return DisplayDensity.PRESENTING
        # Voice conversation active → minimal ambient injection
        if ctx.voice_active:
            return DisplayDensity.PRESENTING
        # WS2: stressed system → quiet down
        if ctx.stimmung_stance in ("degraded", "critical"):
            return DisplayDensity.PRESENTING
        if ctx.flow_score >= 0.6 or ctx.activity in ("coding", "deep work"):
            return DisplayDensity.FOCUSED
        # Phase 6: rising flow → preemptive FOCUSED shift
        if ctx.trend_flow > 0.01 and ctx.flow_score > 0.3:
            return DisplayDensity.FOCUSED
        # Phase 6: falling flow → RECEPTIVE (operator disengaging)
        if ctx.trend_flow < -0.02 and ctx.flow_score < 0.4:
            return DisplayDensity.RECEPTIVE
        if ctx.activity in ("present", "browsing", "listening") or ctx.flow_score < 0.2:
            return DisplayDensity.RECEPTIVE
        return DisplayDensity.AMBIENT

    def _available_sources(self, ctx: SchedulerContext, pools: ContentPools) -> list[ContentSource]:
        """Filter to sources that actually have content to show.

        Applies absolute staleness veto: pool-backed sources are rejected
        when pool_age_s exceeds MAX_POOL_AGE_S (2 minutes).
        """
        available: list[ContentSource] = []

        # Absolute staleness veto for pool-backed content
        pool_fresh = pools.pool_age_s <= MAX_POOL_AGE_S

        if pools.facts and pool_fresh:
            available.append(ContentSource.PROFILE_FACT)
        if pools.camera_roles and pool_fresh:
            available.append(ContentSource.CAMERA_FEED)
        if pools.moments and pool_fresh:
            available.append(ContentSource.STUDIO_MOMENT)
        if pools.nudge_titles and pool_fresh:
            available.append(ContentSource.SIGNAL_CARD)
        if ctx.voice_active:
            available.append(ContentSource.VOICE_STATE)

        # Non-pool sources are always conceptually available (computed per-tick)
        available.append(ContentSource.SHADER_VARIATION)
        available.append(ContentSource.TIME_OF_DAY)
        available.append(ContentSource.ACTIVITY_LABEL)
        available.append(ContentSource.BIOMETRIC_MOD)
        if pools.nudge_titles and pool_fresh:
            available.append(ContentSource.SUPPLEMENTARY_CARD)

        # Filter out meeting-blocked sources
        if ctx.activity in ("in a meeting", "presenting"):
            available = [s for s in available if s != ContentSource.CAMERA_FEED]

        return available

    def _score_source(self, source: ContentSource, ctx: SchedulerContext, now: float) -> float:
        """Score a source: base × relevance × freshness × urgency × novelty."""
        config = self._configs.get(source, SourceConfig(source=source))

        # Base weight
        score = config.base_weight

        # Relevance: activity-based multiplier
        relevance_map = RELEVANCE_MATRIX.get(source, {})
        relevance = relevance_map.get(ctx.activity, 1.0)
        score *= relevance

        # Freshness: exponential decay since last shown
        last = self._last_selected.get(source)
        elapsed = now - last if last is not None else config.half_life_s * 2
        freshness = 1.0 - math.exp(-0.693 * elapsed / config.half_life_s)
        score *= freshness

        # Urgency: stress/poor-sleep boosts calming sources
        if ctx.stress_elevated and source in (
            ContentSource.SHADER_VARIATION,
            ContentSource.TIME_OF_DAY,
        ):
            score *= 1.5
        if ctx.sleep_quality < 0.6 and source == ContentSource.SHADER_VARIATION:
            score *= 1.3

        # Novelty: penalize over-selected sources
        count = self._selection_counts.get(source, 0)
        total = max(1, sum(self._selection_counts.values()))
        expected_share = 1.0 / len(ContentSource)
        actual_share = count / total
        if actual_share > expected_share * 2:
            score *= 0.5

        # WS2: cautious+ stance → boost calming sources
        if ctx.stimmung_stance in ("cautious", "degraded", "critical") and source in (
            ContentSource.SHADER_VARIATION,
            ContentSource.TIME_OF_DAY,
        ):
            score *= 1.4

        # Classification consumption: gaze/emotion/posture modulation
        if ctx.gaze_direction == "screen" and source == ContentSource.CAMERA_FEED:
            # Already looking at screen — suppress camera feed injection
            score *= 0.1
        if (
            ctx.emotion in ("angry", "sad", "fear", "disgust")
            and source == ContentSource.PROFILE_FACT
        ):
            # Negative emotion — suppress jovial content
            score *= 0.3
        if ctx.posture == "slouching" and source == ContentSource.STUDIO_MOMENT:
            # Low energy posture — boost break/stretch content
            score *= 1.5

        # BOCPD: recent activity transition → suppress content switches
        if ctx.recent_transition:
            score *= 0.4  # don't interrupt flow entry/exit

        # Phase 6: stale perception → reduced scheduling confidence
        if ctx.perception_age_s > 10.0:
            stale_penalty = max(0.3, 1.0 - ctx.perception_age_s / 60.0)
            score *= stale_penalty

        return max(score, 0.001)  # floor to avoid zero

    def _softmax_sample(
        self, scores: dict[ContentSource, float], temperature: float
    ) -> ContentSource | None:
        """Sample one source using softmax with temperature."""
        if not scores:
            return None

        sources = list(scores.keys())
        raw = [scores[s] for s in sources]

        # Temperature-scaled softmax
        max_score = max(raw)
        exps = [math.exp((v - max_score) / max(temperature, 0.01)) for v in raw]
        total = sum(exps)
        if total == 0:
            return self._rng.choice(sources)

        probs = [e / total for e in exps]
        r = self._rng.random()
        cumulative = 0.0
        for source, p in zip(sources, probs, strict=True):
            cumulative += p
            if r <= cumulative:
                return source
        return sources[-1]

    def _build_decision(
        self,
        source: ContentSource,
        config: SourceConfig,
        ctx: SchedulerContext,
        pools: ContentPools,
        now: float,
    ) -> SchedulerDecision:
        """Build a concrete decision for the selected source."""
        dwell = self._rng.uniform(config.min_dwell_s, config.max_dwell_s)
        shader_nudge = self._compute_shader_nudge(source, ctx)

        if source == ContentSource.PROFILE_FACT:
            content = self._pick_fact(pools.facts)
            return SchedulerDecision(
                source=source,
                content=content,
                dwell_s=dwell,
                notification_level=config.notification_level,
                shader_nudge=shader_nudge,
            )

        if source == ContentSource.CAMERA_FEED:
            role = self._rng.choice(pools.camera_roles)
            css_filter = self._rng.choice(pools.camera_filters) if pools.camera_filters else ""
            x = self._rng.uniform(0.5, 0.7)
            y = self._rng.uniform(0.15, 0.55)
            return SchedulerDecision(
                source=source,
                content=role,
                dwell_s=dwell,
                notification_level=config.notification_level,
                camera_role=role,
                camera_filter=css_filter,
                camera_x=x,
                camera_y=y,
                camera_w=self._rng.uniform(0.25, 0.4),
                camera_h=self._rng.uniform(0.25, 0.4),
                camera_opacity=self._rng.uniform(0.3, 0.6),
                shader_nudge=shader_nudge,
            )

        if source == ContentSource.STUDIO_MOMENT:
            content = self._rng.choice(pools.moments) if pools.moments else ""
            return SchedulerDecision(
                source=source,
                content=content,
                dwell_s=dwell,
                notification_level=config.notification_level,
                shader_nudge=shader_nudge,
            )

        if source == ContentSource.SIGNAL_CARD:
            content = self._rng.choice(pools.nudge_titles) if pools.nudge_titles else ""
            return SchedulerDecision(
                source=source,
                content=content,
                dwell_s=dwell,
                notification_level="make_aware",
                shader_nudge=shader_nudge,
            )

        if source == ContentSource.SHADER_VARIATION:
            return SchedulerDecision(
                source=source,
                content="shader_nudge",
                dwell_s=dwell,
                notification_level="ignore",
                shader_nudge=shader_nudge,
            )

        if source == ContentSource.TIME_OF_DAY:
            content = self._rng.choice(self._circadian_phrases(ctx.hour))
            return SchedulerDecision(
                source=source,
                content=content,
                dwell_s=dwell,
                notification_level="change_blind",
                shader_nudge=shader_nudge,
            )

        if source == ContentSource.ACTIVITY_LABEL:
            content = self._activity_phrase(ctx.activity, ctx.flow_score)
            return SchedulerDecision(
                source=source,
                content=content,
                dwell_s=dwell,
                notification_level="change_blind",
                shader_nudge=shader_nudge,
            )

        if source == ContentSource.BIOMETRIC_MOD:
            content = self._biometric_phrase(ctx.heart_rate, ctx.sleep_quality, ctx.stress_elevated)
            return SchedulerDecision(
                source=source,
                content=content,
                dwell_s=dwell,
                notification_level="change_blind",
                shader_nudge=shader_nudge,
            )

        if source == ContentSource.SUPPLEMENTARY_CARD:
            title = self._rng.choice(pools.nudge_titles) if pools.nudge_titles else ""
            content = f"open loop: {title}" if title else ""
            return SchedulerDecision(
                source=source,
                content=content,
                dwell_s=dwell,
                notification_level="change_blind",
                shader_nudge=shader_nudge,
            )

        # Default: source name as content
        return SchedulerDecision(
            source=source,
            content=source.value,
            dwell_s=dwell,
            notification_level=config.notification_level,
            shader_nudge=shader_nudge,
        )

    def _pick_fact(self, facts: list[str]) -> str:
        """Pick a fact, avoiding recent repetition."""
        available = [f for f in facts if f not in self._fact_history[-20:]]
        if not available:
            available = facts
            self._fact_history.clear()
        if not available:
            return ""
        choice = self._rng.choice(available)
        self._fact_history.append(choice)
        return choice

    def _circadian_phrases(self, hour: int) -> list[str]:
        """Atmospheric time-of-day phrases."""
        if hour < 6:
            return ["the quiet hours", "deep night", "before dawn"]
        if hour < 9:
            return ["morning threshold", "day emerging", "first light"]
        if hour < 12:
            return ["morning arc", "rising energy", "mid-morning"]
        if hour < 14:
            return ["midday plateau", "solar peak", "noon passage"]
        if hour < 17:
            return ["afternoon drift", "post-meridian", "waning daylight"]
        if hour < 20:
            return ["evening approach", "golden hour", "day receding"]
        if hour < 22:
            return ["evening settling", "dusk threshold", "dimming"]
        return ["late hours", "winding down", "approaching quiet"]

    def _activity_phrase(self, activity: str, flow_score: float) -> str:
        """Surface activity as atmospheric text."""
        if flow_score > 0.6:
            return f"{activity} · flow"
        if flow_score > 0.3:
            return f"{activity} · engaged"
        return activity

    def _biometric_phrase(self, heart_rate: int, sleep_quality: float, stress: bool) -> str:
        """Surface biometric state as atmospheric text."""
        parts: list[str] = []
        if heart_rate > 0:
            if heart_rate > 100:
                parts.append(f"hr {heart_rate} elevated")
            elif heart_rate < 60:
                parts.append(f"hr {heart_rate} resting")
            else:
                parts.append(f"hr {heart_rate}")
        if 0 < sleep_quality < 0.6:
            parts.append(f"sleep {int(sleep_quality * 100)}%")
        if stress:
            parts.append("stress detected")
        return " · ".join(parts) if parts else "steady state"

    def _compute_shader_nudge(self, source: ContentSource, ctx: SchedulerContext) -> ShaderNudge:
        """Compute shader parameter adjustments based on source + context.

        Batch 5: activity-based mood, audio-reactive speed, content-synchronized
        shifts, circadian alignment.
        """
        speed_mult = 1.0
        turbulence_mult = 1.0
        warmth_offset = 0.0
        brightness_offset = 0.0

        # Activity-based shader mood
        if ctx.activity in ("coding", "deep work", "writing"):
            speed_mult *= 0.7  # cooler, slower
            warmth_offset -= 0.1
        elif ctx.activity in ("making music",):
            speed_mult *= 1.3  # warmer, faster
            turbulence_mult *= 1.2
            warmth_offset += 0.1
        elif ctx.activity in ("browsing", "present"):
            speed_mult *= 1.1  # slightly livelier

        # Audio-reactive turbulence
        if ctx.audio_energy > 0.1:
            turbulence_mult *= 1.0 + ctx.audio_energy * 0.5

        # Content-synchronized shifts
        if source == ContentSource.CAMERA_FEED:
            brightness_offset += 0.03  # slightly brighter when camera shows
        elif source == ContentSource.PROFILE_FACT:
            brightness_offset -= 0.02  # slightly darker bg for text readability

        # Circadian energy curve (subtle)
        if ctx.hour < 6 or ctx.hour >= 22:
            speed_mult *= 0.6
            warmth_offset += 0.15
        elif 9 <= ctx.hour <= 11:
            speed_mult *= 1.1  # morning energy peak
        elif 14 <= ctx.hour <= 15:
            speed_mult *= 0.85  # post-lunch dip

        return ShaderNudge(
            speed_mult=round(speed_mult, 3),
            turbulence_mult=round(turbulence_mult, 3),
            warmth_offset=round(warmth_offset, 3),
            brightness_offset=round(brightness_offset, 3),
        )
