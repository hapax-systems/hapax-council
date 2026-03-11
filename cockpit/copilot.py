"""copilot — context-aware cognitive partner engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from cockpit.voice import operator_name


@dataclass
class CopilotContext:
    """Snapshot of everything the copilot can see."""

    # System state
    health_status: str = ""  # "healthy"|"degraded"|"failed"
    health_changed: bool = False  # True if status changed this refresh cycle
    healthy_count: int = 0
    total_checks: int = 0
    failed_checks: list[str] = field(default_factory=list)
    vram_pct: float = 0.0
    loaded_model: str = ""
    briefing_age_h: float | None = None
    action_item_count: int = 0
    drift_count: int | None = None

    # Readiness state
    readiness_level: str = ""  # "bootstrapping"|"developing"|"operational"
    readiness_top_gap: str = ""
    readiness_gaps: list[str] = field(default_factory=list)
    interview_conducted: bool = True  # default True to avoid false alerts before data loads

    # Session state
    last_agent_run: str = ""  # label
    last_agent_exit: int | None = None
    last_agent_duration: float = 0.0
    last_agent_elapsed: float = 999.0  # seconds since last run completed
    agents_run_count: int = 0
    just_returned_from: str | None = None  # screen name or None
    idle_seconds: float = 0.0
    session_age_s: float = 0.0

    # Micro-probe
    current_probe: object | None = None  # MicroProbe when available

    # Accommodations
    accommodations: object | None = None  # AccommodationSet when loaded

    # Data freshness (seconds since last refresh, -1 = not tracked)
    fast_cache_age_s: int = -1
    slow_cache_age_s: int = -1

    # Time
    hour: int = field(default_factory=lambda: datetime.now().hour)


# ── Readiness observation pools ─────────────────────────────────────────────

_BOOTSTRAPPING_OBSERVATIONS = [
    "I know your stack, but I don't really know you yet.",
    "I've been watching how you work, but we've never actually talked about it.",
    "I don't know your priorities — only what I've inferred from configs and logs.",
    "there's a whole neurocognitive dimension I know nothing about — how you focus, what blocks you.",
    "your goals exist on paper, but I've never asked if they're actually what matters to you.",
    "I can tell you the stack is healthy, but I can't tell you if it's serving your actual priorities.",
    "I'm working from observation, not conversation. that's a gap I'd like to close.",
    "a 15-minute interview would teach me more about your priorities than another week of watching logs.",
]

_DEVELOPING_OBSERVATIONS = [
    "still some profile gaps — {gap} is thin.",
    "we've talked, but there are dimensions I haven't explored yet.",
    "the neurocognitive picture is still incomplete — that affects how I frame suggestions.",
    "some of your goals haven't been discussed in detail yet.",
]

# Cooldown: readiness messages fire at most every 5 evaluations (~2.5 min at 30s).
_READINESS_COOLDOWN = 5


class CopilotEngine:
    """Priority-ordered rule engine. First matching rule wins."""

    def __init__(self) -> None:
        self._eval_count: int = 0
        self._last_readiness_eval: int = -_READINESS_COOLDOWN
        self._readiness_msg_index: int = 0

    def evaluate(self, ctx: CopilotContext) -> str:
        self._eval_count += 1
        msg = self._evaluate_rules(ctx)
        return self._apply_accommodations(msg, ctx)

    def _evaluate_rules(self, ctx: CopilotContext) -> str:
        name = operator_name()

        # P1: Immediate transitions
        if ctx.health_changed and ctx.health_status != "healthy":
            check = ctx.failed_checks[0] if ctx.failed_checks else "something"
            return (
                f"heads up — health just dropped to {ctx.health_status}. "
                f"{check} needs attention."
            )

        if ctx.last_agent_elapsed < 10:
            if ctx.last_agent_exit == 0:
                return f"nice, {ctx.last_agent_run} done in {ctx.last_agent_duration:.1f}s."
            else:
                return f"{ctx.last_agent_run} failed — check the output."

        if ctx.just_returned_from == "chat":
            if ctx.action_item_count > 0:
                return f"back from chat. {ctx.action_item_count} items still open."
            return "back from chat. nothing pressing."

        # P2: Ongoing concerns
        if (
            ctx.briefing_age_h is not None
            and ctx.briefing_age_h > 26
            and ctx.action_item_count > 0
        ):
            return (
                f"briefing is {ctx.briefing_age_h:.0f}h old with "
                f"{ctx.action_item_count} items still open."
            )

        if ctx.health_status == "degraded":
            check = ctx.failed_checks[0] if ctx.failed_checks else "check"
            return (
                f"{ctx.healthy_count}/{ctx.total_checks} checks passing — "
                f"{check} still down."
            )

        if ctx.health_status == "failed":
            return f"health is failed — {len(ctx.failed_checks)} checks need attention."

        if ctx.vram_pct > 85 and ctx.loaded_model:
            return f"{ctx.vram_pct:.0f}% VRAM with {ctx.loaded_model}. runs might queue."

        if ctx.drift_count is not None and ctx.drift_count > 5:
            return f"{ctx.drift_count} drift items — docs and reality diverging."

        # P2-F: Data freshness — stale collectors
        if ctx.fast_cache_age_s > 90:  # 3x fast cadence (30s)
            return f"health data is {ctx.fast_cache_age_s}s stale — fast refresh may be stuck."
        if ctx.slow_cache_age_s > 900:  # 3x slow cadence (5min)
            return f"dashboard data is {ctx.slow_cache_age_s // 60}m stale — slow refresh may be stuck."

        # P2-R: Bootstrapping readiness alert (with cooldown, not during greeting)
        if (
            ctx.readiness_level == "bootstrapping"
            and ctx.session_age_s >= 60
            and self._readiness_cooldown_expired()
        ):
            return self._next_readiness_message(ctx)

        # P3: Idle nudges (items are visible on dashboard — copilot stays observational)
        if ctx.idle_seconds > 300:
            # Every 3rd idle eval with readiness gaps: rotate readiness observation
            if (
                ctx.readiness_level
                and ctx.readiness_level != "operational"
                and self._eval_count % 3 == 0
            ):
                return self._next_readiness_message(ctx)
            # Micro-probe: surface a discovery question during idle
            if ctx.current_probe is not None and self._eval_count % 4 == 0:
                probe = ctx.current_probe
                return f"I've been wondering — {probe.rationale}. {probe.question}"
            return "quiet session. everything's running smooth."

        # P4: Ambient
        if ctx.session_age_s < 60:
            return _session_greeting(ctx, name)

        return _ambient_status(ctx)

    def _readiness_cooldown_expired(self) -> bool:
        return (self._eval_count - self._last_readiness_eval) >= _READINESS_COOLDOWN

    def _next_readiness_message(self, ctx: CopilotContext) -> str:
        """Pick the next readiness observation from the appropriate pool."""
        self._last_readiness_eval = self._eval_count

        if ctx.readiness_level == "bootstrapping":
            pool = _BOOTSTRAPPING_OBSERVATIONS
        else:
            pool = _DEVELOPING_OBSERVATIONS

        idx = self._readiness_msg_index % len(pool)
        self._readiness_msg_index += 1

        msg = pool[idx]
        # Developing pool uses {gap} placeholder
        if "{gap}" in msg:
            if ctx.readiness_gaps:
                # Pick a gap that isn't about interview (already done in developing)
                non_interview_gaps = [
                    g for g in ctx.readiness_gaps if "interview" not in g
                ]
                gap = non_interview_gaps[0] if non_interview_gaps else ctx.readiness_gaps[0]
            else:
                gap = "some dimensions"
            msg = msg.format(gap=gap)

        return msg

    def _apply_accommodations(self, msg: str, ctx: CopilotContext) -> str:
        """Post-process message with confirmed accommodations."""
        acc = ctx.accommodations
        if acc is None:
            return msg

        # Time anchor: append session duration to ambient/idle messages
        if acc.time_anchor_enabled and ctx.session_age_s >= 60:
            mins = int(ctx.session_age_s / 60)
            msg = f"{msg} ({mins}m in)"

        return msg


def _session_greeting(ctx: CopilotContext, name: str) -> str:
    """First-minute greeting with status summary."""
    parts: list[str] = []
    if ctx.action_item_count > 0:
        parts.append(f"{ctx.action_item_count} items pending")
    if ctx.health_status and ctx.health_status != "healthy":
        parts.append(f"health {ctx.health_status}")
    elif ctx.health_status:
        parts.append("stack's healthy")

    period = (
        "morning"
        if 4 <= ctx.hour < 12
        else "afternoon"
        if ctx.hour < 17
        else "evening"
        if ctx.hour < 21
        else "late one"
    )
    summary = ", ".join(parts) if parts else "all clear"
    greeting = f"{period}, {name} — {summary}."

    # Append top gap for bootstrapping
    if ctx.readiness_level == "bootstrapping" and ctx.readiness_top_gap:
        greeting += f" {ctx.readiness_top_gap}."

    return greeting


def _ambient_status(ctx: CopilotContext) -> str:
    """Default status when nothing specific is happening."""
    parts: list[str] = []
    if ctx.health_status:
        parts.append(f"stack {ctx.health_status}")
    if ctx.briefing_age_h is not None:
        parts.append(f"briefing {ctx.briefing_age_h:.0f}h old")

    if parts:
        return ". ".join(parts) + "."

    # No operational info — surface readiness awareness instead of "all clear"
    if ctx.readiness_level and ctx.readiness_level != "operational":
        return f"nothing operational to report. {ctx.readiness_top_gap}." if ctx.readiness_top_gap else "all clear. nothing pressing."

    return "all clear. nothing pressing."
