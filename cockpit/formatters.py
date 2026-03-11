"""Rich text formatters for cockpit data — used by CLI snapshot and tests."""
from __future__ import annotations

from rich.text import Text

from cockpit.data.infrastructure import ContainerStatus
from cockpit.data.scout import ScoutData


def render_infra_detail(containers: list[ContainerStatus]) -> Text:
    """Render container details as rich Text — usable standalone for drill-down."""
    if not containers:
        t = Text()
        t.append("  No containers found", style="dim")
        return t

    t = Text()

    for c in containers:
        if c.state == "running" and c.health == "healthy":
            indicator = "●"
            style = "green"
        elif c.state == "running":
            indicator = "●"
            style = "yellow"
        else:
            indicator = "○"
            style = "red"

        t.append(f"  {indicator} ", style=style)
        t.append(f"{c.name:<20s}", style=style if style != "green" else "")
        t.append(f"{c.state:<10s}", style="dim")

        health_str = c.health if c.health else "-"
        t.append(f"{health_str}", style="dim")
        t.append("\n")

    healthy = sum(1 for c in containers if c.health == "healthy")
    t.append(f"\n  {len(containers)} containers, {healthy} healthy", style="dim")

    return t


def render_scout_detail(scout: ScoutData | None) -> Text:
    """Render scout recommendations as rich Text — usable standalone for drill-down."""
    if scout is None:
        t = Text()
        t.append("  No scout report\n", style="dim")
        t.append("  Run: ", style="dim")
        t.append("uv run python -m agents.scout --save", style="bold dim")
        return t

    t = Text()
    t.append(f"  {scout.components_scanned} components", style="dim")
    t.append(f"  {scout.generated_at}\n\n", style="dim")

    tier_style = {
        "adopt": "red bold",
        "evaluate": "yellow",
        "monitor": "dim",
    }
    tier_icon = {
        "adopt": "▲",
        "evaluate": "?",
        "monitor": "○",
    }

    actionable = [r for r in scout.recommendations if r.tier != "current-best"]
    if actionable:
        for r in actionable:
            icon = tier_icon.get(r.tier, "?")
            style = tier_style.get(r.tier, "")
            t.append(f"  {icon} ", style=style)
            t.append(f"{r.component}: ", style=style)
            t.append(f"{r.tier}", style=style)
            t.append(f" ({r.confidence})\n", style="dim")
            t.append(f"    {r.summary}\n", style="dim")

    current_best = sum(1 for r in scout.recommendations if r.tier == "current-best")
    if current_best:
        t.append(f"\n  {current_best} current-best", style="dim")

    return t
