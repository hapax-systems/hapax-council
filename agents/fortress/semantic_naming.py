"""Semantic naming engine — maps Hapax concepts to DF dwarf identities."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class DwarfProfile:
    nickname: str
    facets: dict[str, int] = field(default_factory=dict)
    beliefs: dict[str, int] = field(default_factory=dict)
    goals: tuple[str, ...] = ()


# Map Hapax profile dimensions to DF personality facets
DIMENSION_TO_FACET: dict[str, dict[str, int]] = {
    "energy_and_attention": {"ACTIVITY_LEVEL": 2, "FOCUS": 2},
    "work_patterns": {"PERSEVERANCE": 2, "ORDERLINESS": 1},
    "information_seeking": {"INTELLECTUAL_CURIOSITY": 3, "ABSTRACT_INCLINED": 2},
    "creative_process": {"IMAGINATION": 3, "CREATIVITY": 2},
    "tool_usage": {"CRAFTSMANSHIP": 2, "SKILL_FOCUS": 1},
    "communication_patterns": {"GREGARIOUSNESS": 1, "ASSERTIVENESS": 1},
    "identity": {"PRIDE": 1, "SELF_CONSCIOUSNESS": -1},
    "neurocognitive": {"STRESS_VULNERABILITY": -1, "ANXIETY_PROPENSITY": -1},
    "values": {"HARMONY": 2, "TRUTH": 2},
    "communication_style": {"ELOQUENCE": 2, "PATIENCE": 1},
    "relationships": {"FRIENDLINESS": 2, "TRUST": 1},
}

# Hapax system concepts for naming
HAPAX_CONCEPT_NAMES: tuple[str, ...] = (
    "Stimmung",
    "Protention",
    "Retention",
    "Impression",
    "Salience",
    "Archivist",
    "Sentinel",
    "Compositor",
    "Nexus",
    "Cortex",
    "Drift",
    "Cadence",
    "Resonance",
    "Epoch",
    "Seam",
    "Meridian",
    "Axiom",
    "Canon",
    "Locus",
    "Praxis",
)


def generate_profiles(
    concept_names: tuple[str, ...] | None = None,
    dimension_facets: dict[str, dict[str, int]] | None = None,
) -> list[DwarfProfile]:
    """Generate dwarf profiles from Hapax concepts."""
    names = concept_names or HAPAX_CONCEPT_NAMES
    facet_map = dimension_facets or DIMENSION_TO_FACET

    profiles = []
    dims = list(facet_map.keys())
    for i, name in enumerate(names):
        # Rotate through dimensions to vary profiles
        dim = dims[i % len(dims)]
        facets = dict(facet_map[dim])

        # Derive beliefs from dimension
        beliefs: dict[str, int] = {"KNOWLEDGE": 2, "CRAFTSMANSHIP": 1}
        if "creative" in dim:
            beliefs["ART"] = 3
        if "information" in dim:
            beliefs["TRUTH"] = 3

        # Derive goals
        goals: list[str] = []
        if "creative" in dim:
            goals.append("CREATE_A_GREAT_WORK_OF_ART")
        elif "information" in dim:
            goals.append("MAKE_A_GREAT_DISCOVERY")
        elif "work" in dim:
            goals.append("MASTER_A_SKILL")
        else:
            goals.append("CRAFT_A_MASTERWORK")

        profiles.append(
            DwarfProfile(
                nickname=name,
                facets=facets,
                beliefs=beliefs,
                goals=tuple(goals),
            )
        )

    return profiles


def assign_profile(profiles: list[DwarfProfile], unit_id: int) -> DwarfProfile:
    """Deterministic profile assignment based on unit ID."""
    idx = unit_id % len(profiles) if profiles else 0
    return profiles[idx] if profiles else DwarfProfile(nickname="Unnamed")


def write_profiles(profiles: list[DwarfProfile], output_path: Path) -> None:
    """Write profiles to JSON for Lua consumption."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = [
        {
            "nickname": p.nickname,
            "facets": p.facets,
            "beliefs": p.beliefs,
            "goals": list(p.goals),
        }
        for p in profiles
    ]
    output_path.write_text(json.dumps(data, indent=2))
