"""Observation tools — constrained fortress state queries returning NL patches."""

from __future__ import annotations

from agents.fortress.attention import AttentionBudget, AttentionTier
from agents.fortress.patches import describe_patch, extract_patches
from agents.fortress.schema import FullFortressState
from agents.fortress.spatial_memory import EntityMobility, SpatialMemoryStore


def observe_region(
    state: FullFortressState,
    memory: SpatialMemoryStore,
    budget: AttentionBudget,
    center_x: int,
    center_y: int,
    z: int,
    radius: int = 5,
) -> str:
    """Observe patches within radius of center point. Costs 1 Tier 2 budget."""
    if not budget.spend(AttentionTier.ROUTINE):
        return "Observation budget exhausted for routine tier."

    patches = extract_patches(state)
    nearby = [
        p
        for p in patches
        if p.z_level == z
        and abs((p.x1 + p.x2) // 2 - center_x) <= radius
        and abs((p.y1 + p.y2) // 2 - center_y) <= radius
    ]

    if not nearby:
        return f"No notable features within {radius} tiles of ({center_x}, {center_y}, z={z})."

    descriptions = []
    for patch in nearby:
        desc = describe_patch(patch, state)
        memory.observe(patch.patch_id, desc, state.game_tick, EntityMobility.STATIC)
        descriptions.append(desc)

    return " ".join(descriptions)


def describe_patch_tool(
    state: FullFortressState,
    memory: SpatialMemoryStore,
    budget: AttentionBudget,
    patch_id: str,
) -> str:
    """Detailed description of a specific patch. Costs 1 Tier 2 budget."""
    if not budget.spend(AttentionTier.ROUTINE):
        return "Observation budget exhausted for routine tier."

    patches = extract_patches(state)
    for patch in patches:
        if patch.patch_id == patch_id:
            desc = describe_patch(patch, state)
            memory.observe(patch_id, desc, state.game_tick)
            return desc

    return f"Patch '{patch_id}' not found."


def check_stockpile(
    state: FullFortressState,
    memory: SpatialMemoryStore,
    budget: AttentionBudget,
    category: str,
) -> str:
    """Quick stockpile level check. Costs 1 Tier 2 budget."""
    if not budget.spend(AttentionTier.ROUTINE):
        return "Observation budget exhausted for routine tier."

    stockpiles = state.stockpiles
    value = getattr(stockpiles, category, None)
    if value is None:
        return f"Unknown stockpile category: {category}"

    per_capita = value / max(1, state.population)
    adequacy = "adequate" if per_capita >= 5 else "low" if per_capita >= 2 else "critical"
    desc = f"{category.title()}: {value} items ({adequacy} for {state.population} dwarves)"

    memory.observe(f"stockpile-{category}", desc, state.game_tick, EntityMobility.SLOW)
    return desc


def scan_threats(
    state: FullFortressState,
    memory: SpatialMemoryStore,
    budget: AttentionBudget,
) -> str:
    """Scan for active threats. FREE — does not consume budget."""
    if state.active_threats == 0:
        return "No active threats detected."

    desc = f"ALERT: {state.active_threats} hostile units detected!"
    for event in state.pending_events:
        if hasattr(event, "attacker_civ"):
            desc += f" Siege by {event.attacker_civ}, force size {event.force_size}."
        elif hasattr(event, "creature_type"):
            desc += f" {event.creature_type} spotted!"

    memory.observe("threats", desc, state.game_tick, EntityMobility.FAST)
    return desc


def examine_dwarf(
    state: FullFortressState,
    memory: SpatialMemoryStore,
    budget: AttentionBudget,
    unit_id: int,
) -> str:
    """Examine a specific dwarf. Costs 1 Tier 2 budget."""
    if not budget.spend(AttentionTier.ROUTINE):
        return "Observation budget exhausted for routine tier."

    for unit in state.units:
        if unit.id == unit_id:
            skills_str = ", ".join(f"{s.name} ({s.level})" for s in unit.skills[:3])
            mood_str = f", mood: {unit.mood}" if unit.mood != "normal" else ""
            desc = (
                f"{unit.name}, {unit.profession}. "
                f"Skills: {skills_str or 'none'}. "
                f"Job: {unit.current_job}. Stress: {unit.stress}{mood_str}."
            )
            memory.observe(f"dwarf-{unit_id}", desc, state.game_tick, EntityMobility.FAST)
            return desc

    return f"Dwarf {unit_id} not found."


def survey_floor(
    state: FullFortressState,
    memory: SpatialMemoryStore,
    budget: AttentionBudget,
    z_level: int,
) -> str:
    """High-level survey of a z-level. Costs 1 Tier 3 budget."""
    if not budget.spend(AttentionTier.STRATEGIC):
        return "Observation budget exhausted for strategic tier."

    patches = extract_patches(state)
    floor_patches = [p for p in patches if p.z_level == z_level]

    if not floor_patches:
        return f"Z-level {z_level}: No developed features."

    rooms = [p for p in floor_patches if p.patch_type.value == "room"]
    workshops = [p for p in floor_patches if p.patch_type.value == "workshop"]
    zones = [p for p in floor_patches if p.patch_type.value == "zone"]

    parts = [f"Z-level {z_level}:"]
    if rooms:
        parts.append(f"{len(rooms)} room(s) ({', '.join(r.name for r in rooms[:5])})")
    if workshops:
        parts.append(f"{len(workshops)} workshop(s) ({', '.join(w.name for w in workshops[:5])})")
    if zones:
        parts.append(f"{len(zones)} zone(s)")

    desc = ". ".join(parts) + "."
    memory.observe(f"floor-{z_level}", desc, state.game_tick, EntityMobility.STATIC)
    return desc


def check_announcements(
    state: FullFortressState,
    memory: SpatialMemoryStore,
    budget: AttentionBudget,
    since_tick: int = 0,
) -> str:
    """Recent game announcements. FREE — does not consume budget."""
    events = list(state.pending_events)
    if not events:
        return "No recent announcements."

    parts = []
    for event in events:
        parts.append(f"[{event.type}] {event.model_dump_json()}")

    return " | ".join(parts)
