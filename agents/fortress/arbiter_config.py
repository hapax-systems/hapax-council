"""Fortress resource arbitration — priority configuration.

Configures ResourceArbiter for shared fortress resources (dwarf labor, materials).
Reuses ResourceArbiter/ResourceClaim from agents.hapax_daimonion.arbiter.
"""

from __future__ import annotations

from agents.hapax_daimonion.arbiter import ResourceArbiter


def create_fortress_arbiter() -> ResourceArbiter:
    """Create arbiter with fortress priority configuration."""
    priorities = {
        ("dwarf_labor", "crisis_responder"): 100,
        ("dwarf_labor", "military_commander"): 80,
        ("dwarf_labor", "fortress_planner"): 60,
        ("dwarf_labor", "resource_manager"): 40,
        ("materials", "crisis_responder"): 100,
        ("materials", "fortress_planner"): 60,
        ("materials", "resource_manager"): 40,
    }
    return ResourceArbiter(priorities=priorities)
