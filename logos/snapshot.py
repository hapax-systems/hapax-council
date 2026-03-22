"""CLI one-shot mode: collect all data, print formatted snapshot, exit."""

from __future__ import annotations

import asyncio

from logos.data.agents import get_agent_registry
from logos.data.briefing import collect_briefing
from logos.data.cost import CostSnapshot, collect_cost
from logos.data.goals import GoalSnapshot, collect_goals
from logos.data.gpu import VramSnapshot, collect_vram
from logos.data.health import (
    HealthHistory,
    HealthSnapshot,
    collect_health_history,
    collect_live_health,
)
from logos.data.infrastructure import (
    ContainerStatus,
    TimerStatus,
    collect_docker,
    collect_timers,
)
from logos.data.readiness import ReadinessSnapshot, collect_readiness
from logos.data.scout import collect_scout


def _format_health(health: HealthSnapshot, history: HealthHistory) -> str:
    lines = [f"HEALTH: {health.overall_status.upper()}"]
    lines.append(
        f"  {health.healthy}/{health.total_checks} healthy"
        f"  {health.degraded} degraded  {health.failed} failed"
        f"  ({health.duration_ms}ms)"
    )
    if health.failed_checks:
        for name in health.failed_checks[:5]:
            lines.append(f"  ! {name}")
    if history.total_runs > 0:
        lines.append(f"  Uptime: {history.uptime_pct}% ({history.total_runs} runs)")
    return "\n".join(lines)


def _format_vram(vram: VramSnapshot | None) -> str:
    if vram is None:
        return "VRAM: unavailable"
    bar_width = 20
    filled = int(vram.usage_pct / 100 * bar_width)
    bar = "=" * filled + "." * (bar_width - filled)
    lines = [f"VRAM: {vram.name}  {vram.temperature_c}C"]
    lines.append(
        f"  [{bar}] {vram.used_mb / 1024:.1f}/{vram.total_mb / 1024:.0f} GB"
        f"  ({vram.free_mb / 1024:.1f} GB free)"
    )
    if vram.loaded_models:
        lines.append(f"  Loaded: {', '.join(vram.loaded_models)}")
    else:
        lines.append("  No models loaded")
    return "\n".join(lines)


def _format_timers(timers: list[TimerStatus]) -> str:
    if not timers:
        return "TIMERS: none found"
    lines = ["TIMERS:"]
    for t in timers:
        lines.append(f"  {t.unit:<24s} {t.next_fire:>10s}  (last: {t.last_fired})")
    return "\n".join(lines)


def _format_containers(containers: list[ContainerStatus]) -> str:
    if not containers:
        return "INFRASTRUCTURE: no containers"
    healthy = sum(1 for c in containers if c.health == "healthy")
    lines = [f"INFRASTRUCTURE: {len(containers)} containers, {healthy} healthy"]
    for c in containers:
        health_str = c.health if c.health else "-"
        lines.append(f"  {c.name:<20s} {c.state:<10s} {health_str}")
    return "\n".join(lines)


def _format_actions(briefing) -> str:
    if briefing is None:
        return "ACTIONS: no briefing available\n  Run: uv run python -m agents.briefing --save"
    lines = [f"ACTIONS: {briefing.headline}"]
    if briefing.action_items:
        icon_map = {"high": "!!", "medium": "! ", "low": ".."}
        for item in sorted(
            briefing.action_items,
            key=lambda a: (
                ["high", "medium", "low"].index(a.priority)
                if a.priority in ["high", "medium", "low"]
                else 99
            ),
        ):
            icon = icon_map.get(item.priority, "??")
            lines.append(f"  [{icon}] {item.action}")
            if item.command:
                lines.append(f"       $ {item.command}")
    else:
        lines.append("  No action items")
    return "\n".join(lines)


def _format_scout(scout) -> str:
    if scout is None:
        return "SCOUT: no report available\n  Run: uv run python -m agents.scout --save"
    lines = [f"SCOUT: {scout.components_scanned} components scanned ({scout.generated_at})"]
    actionable = [r for r in scout.recommendations if r.tier in ("adopt", "evaluate")]
    if actionable:
        for r in actionable:
            lines.append(f"  [{r.tier[0].upper()}] {r.component}: {r.summary}")
    current_best = sum(1 for r in scout.recommendations if r.tier == "current-best")
    if current_best:
        lines.append(f"  {current_best} components current-best (no action)")
    return "\n".join(lines)


def _format_agents() -> str:
    agents = get_agent_registry()
    lines = ["AGENTS:"]
    for a in agents:
        llm_tag = "LLM" if a.uses_llm else " - "
        flag_strs = [f.flag for f in a.flags[:3]]
        lines.append(f"  {a.name:<20s} {llm_tag}  {' '.join(flag_strs)}")
    return "\n".join(lines)


def _format_cost(cost: CostSnapshot) -> str:
    if not cost.available:
        return "COST: unavailable"
    lines = [f"COST: ${cost.today_cost:.2f} today, ${cost.daily_average:.2f}/day avg"]
    if cost.top_models:
        lines.append("  By model:")
        for m in cost.top_models:
            lines.append(f"    {m.model:<24s} ${m.cost:.2f}")
    return "\n".join(lines)


def _format_readiness(readiness: ReadinessSnapshot) -> str:
    lines = [f"READINESS: {readiness.level.upper()}"]
    interview = "yes" if readiness.interview_conducted else "no"
    lines.append(
        f"  {readiness.populated_dimensions}/{readiness.total_dimensions} dims"
        f"  Interview: {interview}"
    )
    if readiness.top_gap:
        lines.append(f"  Gap: {readiness.top_gap}")
    return "\n".join(lines)


def _format_goals(goals: GoalSnapshot) -> str:
    if not goals.goals:
        return "GOALS: none defined"
    lines = [f"GOALS: {goals.active_count} active, {goals.stale_count} stale"]
    for g in goals.goals:
        stale_marker = " [STALE]" if g.stale else ""
        cat = g.category[0].upper()  # P or S
        lines.append(f"  [{cat}] {g.name} ({g.status}){stale_marker}")
    return "\n".join(lines)


async def generate_snapshot() -> str:
    """Collect all logos data and format as plain text."""
    health, containers, vram, timers = await asyncio.gather(
        collect_live_health(),
        collect_docker(),
        collect_vram(),
        collect_timers(),
    )
    history = collect_health_history()
    briefing = collect_briefing()
    scout = collect_scout()
    cost = collect_cost()
    readiness = collect_readiness()
    goals = collect_goals()

    sections = [
        _format_health(health, history),
        _format_vram(vram),
        _format_readiness(readiness),
        _format_goals(goals),
        _format_cost(cost),
        _format_timers(timers),
        _format_actions(briefing),
        _format_containers(containers),
        _format_scout(scout),
        _format_agents(),
    ]

    return "\n\n".join(sections)


async def generate_snapshot_rich():
    """Collect all logos data and return a Rich renderable (colored)."""
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    health, containers, vram, timers = await asyncio.gather(
        collect_live_health(),
        collect_docker(),
        collect_vram(),
        collect_timers(),
    )
    history = collect_health_history()
    briefing = collect_briefing()
    scout = collect_scout()
    cost = collect_cost()
    readiness = collect_readiness()
    goals_snap = collect_goals()

    table = Table.grid(padding=(0, 2))
    table.add_column(width=36)
    table.add_column()

    # --- Sidebar column ---
    sidebar_parts = []

    # Health
    status_color = {"healthy": "green", "degraded": "yellow", "failed": "red"}.get(
        health.overall_status, "white"
    )
    ht = Text()
    ht.append(f"{health.overall_status.upper()}", style=f"bold {status_color}")
    ht.append(f"  {health.healthy}/{health.total_checks}\n")
    if health.failed_checks:
        for name in health.failed_checks[:3]:
            ht.append(f"! {name}\n", style="red")
    if history.total_runs > 0:
        ht.append(f"{history.uptime_pct}% uptime ({history.total_runs} runs)", style="dim")
    sidebar_parts.append(Panel(ht, title="health", border_style="blue"))

    # Timers
    tt = Text()
    for t in timers:
        tt.append(f"{t.unit:<22s} {t.next_fire:>8s}\n")
    sidebar_parts.append(Panel(tt or Text("No timers"), title="timers", border_style="blue"))

    # VRAM
    vt = Text()
    if vram:
        temp_color = (
            "green" if vram.temperature_c < 60 else "yellow" if vram.temperature_c < 80 else "red"
        )
        vt.append(f"{vram.name.replace('NVIDIA GeForce ', '')}  ")
        vt.append(f"{vram.temperature_c}\u00b0C\n", style=temp_color)
        bar_w = 20
        filled = int(vram.usage_pct / 100 * bar_w)
        vt.append("[")
        vt.append("=" * filled, style="green" if vram.usage_pct < 50 else "yellow")
        vt.append("." * (bar_w - filled), style="dim")
        vt.append(f"] {vram.used_mb / 1024:.1f}/{vram.total_mb / 1024:.0f} GB\n")
        if vram.loaded_models:
            vt.append(", ".join(vram.loaded_models), style="bold")
        else:
            vt.append("idle", style="dim")
    else:
        vt.append("No GPU detected", style="dim")
    sidebar_parts.append(Panel(vt, title="vram", border_style="blue"))

    # Cost
    ct = Text()
    if cost.available:
        ct.append(f"${cost.today_cost:.2f}", style="bold")
        ct.append(" today  ")
        ct.append(f"${cost.daily_average:.2f}/d\n", style="dim")
        for m in cost.top_models:
            ct.append(f"{m.model:<20s} ${m.cost:.2f}\n", style="dim")
    else:
        ct.append("unavailable", style="dim")
    sidebar_parts.append(Panel(ct, title="cost", border_style="blue"))

    # Readiness
    rt = Text()
    level_color = "green" if readiness.level == "operational" else "yellow"
    level_icon = "●" if readiness.level == "operational" else "◐"
    rt.append(f"{level_icon} ", style=level_color)
    rt.append(f"{readiness.level.upper()}", style=f"bold {level_color}")
    rt.append(f"  {readiness.populated_dimensions}/{readiness.total_dimensions}\n")
    interview = "yes" if readiness.interview_conducted else "no"
    rt.append(f"Interview: {interview}\n", style="dim")
    if readiness.top_gap:
        rt.append(f"Gap: {readiness.top_gap}", style="dim")
    sidebar_parts.append(Panel(rt, title="readiness", border_style="blue"))

    # Goals
    gt = Text()
    if goals_snap.goals:
        gt.append(f"{goals_snap.active_count} active", style="dim")
        if goals_snap.stale_count > 0:
            gt.append(f"  {goals_snap.stale_count} stale", style="yellow")
        gt.append("\n")
        for g in goals_snap.goals:
            cat = "P" if g.category == "primary" else "S"
            style = "yellow" if g.stale else "dim"
            gt.append(f"[{cat}] {g.name} ({g.status})\n", style=style)
    else:
        gt.append("No goals defined", style="dim")
    sidebar_parts.append(Panel(gt, title="goals", border_style="blue"))

    from rich.console import Group

    sidebar = Group(*sidebar_parts)

    # --- Main column ---
    main_parts = []

    # Actions
    at = Text()
    if briefing:
        if briefing.headline:
            at.append(f"{briefing.headline}\n\n", style="bold")
        if briefing.action_items:
            icon_map = {"high": "!!", "medium": "! ", "low": ".."}
            color_map = {"high": "red bold", "medium": "yellow", "low": "dim"}
            for item in sorted(
                briefing.action_items,
                key=lambda a: (
                    ["high", "medium", "low"].index(a.priority)
                    if a.priority in ["high", "medium", "low"]
                    else 99
                ),
            ):
                at.append(
                    f"[{icon_map.get(item.priority, '??')}] ",
                    style=color_map.get(item.priority, ""),
                )
                at.append(f"{item.action}\n")
        if briefing.generated_at:
            at.append(f"\n{briefing.generated_at}", style="dim")
    else:
        at.append("No briefing available", style="dim")
    main_parts.append(Panel(at, title="actions", border_style="blue"))

    # Infrastructure
    it = Text()
    for c in containers:
        if c.state == "running" and c.health == "healthy":
            it.append("\u25cf ", style="green")
        elif c.state == "running":
            it.append("\u25cf ", style="yellow")
        else:
            it.append("\u25cb ", style="red")
        health_str = c.health if c.health else "-"
        it.append(f"{c.name} {health_str}\n")
    healthy = sum(1 for c in containers if c.health == "healthy")
    it.append(f"\n{len(containers)} containers, {healthy} healthy", style="dim")
    main_parts.append(Panel(it, title="infrastructure", border_style="blue"))

    # Scout
    st = Text()
    if scout:
        st.append(f"{scout.components_scanned} components  {scout.generated_at}\n\n", style="dim")
        actionable = [r for r in scout.recommendations if r.tier != "current-best"]
        for r in actionable:
            st.append(f"[{r.tier[0].upper()}] {r.component}: {r.summary}\n")
        current_best = sum(1 for r in scout.recommendations if r.tier == "current-best")
        if current_best:
            st.append(f"\n{current_best} current-best", style="dim")
    else:
        st.append("No scout report", style="dim")
    main_parts.append(Panel(st, title="scout", border_style="blue"))

    # Agents
    agt = Text()
    for a in get_agent_registry():
        llm_tag = "LLM" if a.uses_llm else " \u2013 "
        agt.append(f"{a.name:<22s}", style="bold" if a.uses_llm else "")
        agt.append(f"{llm_tag}  ", style="dim")
        flag_strs = [f.flag for f in a.flags[:3]]
        agt.append(f"{' '.join(flag_strs)}\n", style="dim")
    main_parts.append(Panel(agt, title="agents", border_style="blue"))

    main = Group(*main_parts)

    table.add_row(sidebar, main)
    return Panel(table, title="[bold]System Logos[/bold]", border_style="blue")
