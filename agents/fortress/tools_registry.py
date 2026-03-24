"""Tool definitions for LLM tool-use in the deliberation loop.

Defines the 12 observation tools in Claude tool-use format.
"""

from __future__ import annotations

FORTRESS_TOOLS: list[dict] = [
    {
        "name": "observe_region",
        "description": (
            "Observe a region of the fortress map around a center point. "
            "Returns natural language description of buildings, units, and terrain in the area."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "center_x": {"type": "integer", "description": "X coordinate center"},
                "center_y": {"type": "integer", "description": "Y coordinate center"},
                "z": {"type": "integer", "description": "Z-level"},
                "radius": {
                    "type": "integer",
                    "description": "Observation radius in tiles",
                    "default": 5,
                },
            },
            "required": ["center_x", "center_y", "z"],
        },
    },
    {
        "name": "describe_patch",
        "description": (
            "Get detailed description of a specific named patch (room, workshop, zone)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patch_id": {"type": "string", "description": "Patch identifier"},
            },
            "required": ["patch_id"],
        },
    },
    {
        "name": "check_stockpile",
        "description": (
            "Check inventory levels for a category. Categories: food, drink, wood, "
            "stone, metal_bars, weapons, armor, cloth, seeds."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Stock category to check"},
            },
            "required": ["category"],
        },
    },
    {
        "name": "scan_threats",
        "description": (
            "Scan for active threats (hostile creatures, invaders). Free — no budget cost."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "examine_dwarf",
        "description": (
            "Examine a specific dwarf by unit ID. Shows skills, mood, current job, stress level."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "unit_id": {"type": "integer", "description": "Dwarf unit ID"},
            },
            "required": ["unit_id"],
        },
    },
    {
        "name": "survey_floor",
        "description": "Survey an entire z-level for an overview of what's built there.",
        "input_schema": {
            "type": "object",
            "properties": {
                "z_level": {"type": "integer", "description": "Z-level to survey"},
            },
            "required": ["z_level"],
        },
    },
    {
        "name": "check_announcements",
        "description": ("Check recent game announcements and events. Free — no budget cost."),
        "input_schema": {
            "type": "object",
            "properties": {
                "since_tick": {
                    "type": "integer",
                    "description": "Only show events after this tick",
                    "default": 0,
                },
            },
        },
    },
    {
        "name": "check_military",
        "description": (
            "Check military readiness: squads, equipment quality, training level, alert status."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "check_nobles",
        "description": "Check noble appointments, mandates, and demands.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "check_work_orders",
        "description": "Check active work orders and production queue.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "recall_memory",
        "description": (
            "Recall what you remember about a location or patch without re-observing. "
            "Free — returns cached memory with confidence level."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patch_id": {
                    "type": "string",
                    "description": "Patch identifier to recall",
                },
            },
            "required": ["patch_id"],
        },
    },
    {
        "name": "get_situation",
        "description": (
            "Get the 4 compressed situation chunks (food, population, industry, safety). Free."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]
