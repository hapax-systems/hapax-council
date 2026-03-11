"""shared/dimensions.py — Profile dimension registry.

Single source of truth for all profile dimensions. Replaces the
hardcoded PROFILE_DIMENSIONS list in agents/profiler.py.

Each dimension defines its kind (trait vs behavioral), consumers
(what agents act on it), producers (what writes to it), and whether
the interview system can target it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class DimensionDef:
    """Definition of a profile dimension."""

    name: str
    kind: Literal["trait", "behavioral"]
    description: str
    consumers: tuple[str, ...]
    primary_sources: tuple[str, ...]
    interview_eligible: bool = True


# ── Dimension Registry ────────────────────────────────────────────────────────

DIMENSIONS: tuple[DimensionDef, ...] = (
    # ── Trait dimensions (stable, interview-sourced) ──────────────────────
    DimensionDef(
        name="identity",
        kind="trait",
        description="Who the operator is — roles, background, stated skills, affiliations",
        consumers=("system_prompt", "profiler_digest"),
        primary_sources=("interview", "config", "profiler"),
    ),
    DimensionDef(
        name="neurocognitive",
        kind="trait",
        description="Stable cognitive traits — demand sensitivity, sensory preferences, cognitive style",
        consumers=("system_prompt", "nudge_framing", "notification_timing"),
        primary_sources=("interview", "micro_probes"),
    ),
    DimensionDef(
        name="values",
        kind="trait",
        description="Principles, aesthetic sensibility, decision heuristics, philosophy",
        consumers=("demo_content", "scout_framing"),
        primary_sources=("interview", "profiler"),
    ),
    DimensionDef(
        name="communication_style",
        kind="trait",
        description="How the operator prefers to receive and give information",
        consumers=("agent_output_formatting", "briefing_structure", "notification_verbosity"),
        primary_sources=("interview", "profiler"),
    ),
    DimensionDef(
        name="relationships",
        kind="trait",
        description="People context, relational history, meeting cadence expectations",
        consumers=("calendar_context",),
        primary_sources=("interview", "vault_contacts", "gcalendar_sync"),
    ),
    # ── Behavioral dimensions (dynamic, observation-sourced) ──────────────
    DimensionDef(
        name="work_patterns",
        kind="behavioral",
        description="Time allocation, task switching, project engagement, focus sessions",
        consumers=("briefing", "nudges", "workspace_vision"),
        primary_sources=("gcalendar_sync", "screen_context", "claude_code_sync", "git"),
    ),
    DimensionDef(
        name="energy_and_attention",
        kind="behavioral",
        description="Focus duration, presence patterns, circadian rhythm, productive windows",
        consumers=("nudge_timing", "interview_gating", "notification_priority", "briefing"),
        primary_sources=("workspace_vision", "audio_processor", "gcalendar_sync"),
    ),
    DimensionDef(
        name="information_seeking",
        kind="behavioral",
        description="Research patterns, content consumption, learning interests, browsing depth",
        consumers=("scout_topics", "digest_selection", "profiler_sources"),
        primary_sources=("chrome_sync", "youtube_sync", "obsidian_sync", "gdrive_sync"),
    ),
    DimensionDef(
        name="creative_process",
        kind="behavioral",
        description="Production sessions, creative flow triggers, aesthetic development",
        consumers=("demo_content", "briefing", "studio"),
        primary_sources=("audio_processor", "screen_context", "interview"),
    ),
    DimensionDef(
        name="tool_usage",
        kind="behavioral",
        description="Tool preferences, adoption patterns, workflow toolchain, dev environment",
        consumers=("context_tools", "profiler_targeting"),
        primary_sources=("chrome_sync", "claude_code_sync", "shell_history", "git"),
    ),
    DimensionDef(
        name="communication_patterns",
        kind="behavioral",
        description="Response cadence, meeting density, collaboration frequency",
        consumers=("nudges", "briefing"),
        primary_sources=("gmail_sync", "gcalendar_sync", "audio_processor"),
        interview_eligible=False,
    ),
)

# ── Index for fast lookup ─────────────────────────────────────────────────────

_BY_NAME: dict[str, DimensionDef] = {d.name: d for d in DIMENSIONS}


# ── Public API ────────────────────────────────────────────────────────────────


def get_dimension(name: str) -> DimensionDef | None:
    """Look up a dimension by name. Returns None if not found."""
    return _BY_NAME.get(name)


def get_dimension_names() -> list[str]:
    """Return all dimension names as a list. Backward-compatible with PROFILE_DIMENSIONS."""
    return [d.name for d in DIMENSIONS]


def get_dimensions_by_kind(kind: Literal["trait", "behavioral"]) -> list[DimensionDef]:
    """Return dimensions filtered by kind."""
    return [d for d in DIMENSIONS if d.kind == kind]


def validate_behavioral_write(dimension: str, source: str) -> None:
    """Assert that a source is writing to a valid behavioral dimension.

    Raises ValueError if the dimension doesn't exist or is a trait dimension.
    Used by sync agent tests to catch misrouted facts.
    """
    dim_def = _BY_NAME.get(dimension)
    if dim_def is None:
        raise ValueError(f"{source} writing to unknown dimension: {dimension}")
    if dim_def.kind != "behavioral":
        raise ValueError(f"{source} writing to trait dimension: {dimension}")
