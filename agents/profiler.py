"""profiler.py — User profile extraction agent.

Builds a structured profile by mining local data sources (config files,
Claude Code transcripts, shell history, git repos) and optionally ingesting
external platform exports (Claude.ai, Gemini).

Usage:
    uv run python -m agents.profiler                    # Full extraction
    uv run python -m agents.profiler --source config    # Config files only
    uv run python -m agents.profiler --generate-prompts # Output extraction prompts
    uv run python -m agents.profiler --ingest data.json # Import external data
    uv run python -m agents.profiler --show             # Display current profile
    uv run python -m agents.profiler --full             # Force complete re-extraction
    uv run python -m agents.profiler --auto             # Unattended: detect changes, update if needed
    uv run python -m agents.profiler --curate           # Run quality curation on existing profile
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from shared.config import get_model

# Import Langfuse OTel config (side-effect: configures exporter)
try:
    from shared import langfuse_config  # noqa: F401
except ImportError:
    pass  # Langfuse optional

from opentelemetry import trace

_tracer = trace.get_tracer(__name__)

from agents.profiler_sources import (
    BRIDGED_SOURCE_TYPES,
    SourceChunk,
    detect_changed_sources,
    discover_sources,
    get_source_mtimes,
    list_source_ids,
    read_all_sources,
    save_state,
)

log = logging.getLogger("profiler")


# ── Schemas ──────────────────────────────────────────────────────────────────

from shared.dimensions import DIMENSIONS as _DIMENSIONS
from shared.dimensions import get_dimension_names

PROFILE_DIMENSIONS = get_dimension_names()

_DIM_DESCRIPTIONS = "\n".join(f"- {d.name} ({d.kind}): {d.description}" for d in _DIMENSIONS)

# Sources representing operator intent (explicit statements).
# These take precedence over observation sources during merge.
AUTHORITY_SOURCES = frozenset({"interview", "config", "memory", "operator"})


class ProfileFact(BaseModel):
    """A single extracted fact about the user."""

    dimension: str = Field(description="Profile dimension: " + ", ".join(PROFILE_DIMENSIONS))
    key: str = Field(description="Snake_case identifier for this fact")
    value: str = Field(description="The factual information")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence 0.0-1.0")
    source: str = Field(description='Source identifier, e.g. "config:~/.claude/CLAUDE.md"')
    evidence: str = Field(description="Supporting quote or paraphrase from source")


class ChunkExtraction(BaseModel):
    """Structured output from the extraction agent."""

    facts: list[ProfileFact] = Field(default_factory=list)


class ProfileDimension(BaseModel):
    """A group of facts under one dimension with a narrative summary."""

    name: str
    summary: str = ""
    facts: list[ProfileFact] = Field(default_factory=list)


class UserProfile(BaseModel):
    """The complete user profile."""

    name: str = ""
    email: str | None = None
    summary: str = ""
    dimensions: list[ProfileDimension] = Field(default_factory=list)
    sources_processed: list[str] = Field(default_factory=list)
    version: int = 1
    updated_at: str = ""


class SynthesisOutput(BaseModel):
    """Structured output from the synthesis agent."""

    name: str = Field(description="User's name")
    email: str | None = Field(default=None, description="User's email if found")
    summary: str = Field(description="2-3 sentence profile summary")
    dimension_summaries: dict[str, str] = Field(
        description="Dimension name → narrative summary paragraph"
    )


# ── Agents ───────────────────────────────────────────────────────────────────

extraction_agent = Agent(
    get_model("balanced"),
    output_type=ChunkExtraction,
    system_prompt=(
        "You are a profile extraction agent. Given a text chunk from a data source, "
        "extract factual information about the user into structured ProfileFact objects.\n\n"
        "Dimensions to extract into:\n" + _DIM_DESCRIPTIONS + "\n\n"
        "Guidelines:\n"
        "- Extract concrete, specific facts — not vague observations\n"
        "- Set confidence based on how explicit the evidence is (0.9+ for stated preferences, "
        "0.5-0.7 for inferred patterns, below 0.5 for weak signals)\n"
        "- Use snake_case keys that are descriptive (e.g., 'preferred_python_tool', 'daw_philosophy')\n"
        "- Include the supporting quote/paraphrase as evidence\n"
        "- Skip tool output, system messages, and boilerplate — focus on user preferences, "
        "skills, decisions, and patterns\n"
        "- If the chunk has no extractable user profile information, return an empty facts list"
    ),
)

synthesis_agent = Agent(
    get_model("balanced"),
    output_type=SynthesisOutput,
    system_prompt=(
        "You are a profile synthesis agent. Given a collection of extracted facts about a user, "
        "produce a coherent narrative profile.\n\n"
        "For the summary: Write 2-3 sentences capturing who this person is — their role, "
        "primary domain, and defining characteristics.\n\n"
        "For dimension summaries: Write a concise paragraph for each dimension that has facts. "
        "Synthesize the facts into a narrative — don't just list them. Highlight patterns, "
        "preferences, and connections between facts.\n\n"
        "If you can identify the user's name and email from the facts, include them."
    ),
)

# Register axiom compliance tools on agents that make architectural decisions
from shared.axiom_tools import get_axiom_tools

for _tool_fn in get_axiom_tools():
    extraction_agent.tool(_tool_fn)
    synthesis_agent.tool(_tool_fn)


class OperatorUpdate(BaseModel):
    """Structured output for operator manifest dynamic updates."""

    goal_updates: dict[str, str] = Field(
        description="Goal ID → updated progress string for each goal that has changed"
    )
    new_patterns: list[str] = Field(
        default_factory=list,
        description="New behavioral patterns observed that aren't in the current manifest",
    )
    summary: str = Field(
        description="Updated 1-2 sentence operator summary if facts warrant a change, else empty string"
    )
    neurocognitive_updates: dict[str, list[str]] = Field(
        default_factory=dict,
        description=(
            "Category → list of neurocognitive findings to add. Categories should be "
            "descriptive snake_case (e.g., 'task_initiation', 'energy_cycles'). "
            "Only include well-evidenced, specific patterns — not one-off observations."
        ),
    )


operator_agent = Agent(
    get_model("balanced"),
    output_type=OperatorUpdate,
    system_prompt=(
        "You are an operator manifest updater. Given the current operator manifest and "
        "new profile facts, determine what dynamic sections need updating.\n\n"
        "You update ONLY:\n"
        "1. Goal progress — if new facts show progress on existing goals (new agents built, "
        "services deployed, capabilities added), update the progress string.\n"
        "2. New patterns — if the facts reveal behavioral patterns not captured in the current "
        "manifest, add them. Be selective — only add clearly established patterns, not one-off behaviors.\n"
        "3. Summary — only update if there's a material change to who the operator is. Usually empty.\n"
        "4. Neurocognitive profile — if facts in the neurocognitive_profile dimension reveal "
        "cognitive patterns (task initiation, energy cycles, focus, time perception, motivation, "
        "decision-making, sensory environment, demand sensitivity), organize them into "
        "category → findings lists. Frame findings as system design inputs, not clinical "
        "observations. Only include well-evidenced patterns.\n\n"
        "You must NOT modify constraints, agent_context_map, or use_cases — those are structural.\n"
        "Return empty/unchanged fields if nothing needs updating."
    ),
)


# ── Curation schemas & agent ─────────────────────────────────────────────────


class CurationOp(BaseModel):
    """A single curation operation on profile facts."""

    action: Literal["merge", "delete", "update", "flag"] = Field(
        description="merge: combine redundant facts; delete: remove stale/irrelevant; "
        "update: fix key/value/confidence; flag: mark contradiction for human review"
    )
    keys: list[str] = Field(description="Fact key(s) affected by this operation")
    reason: str = Field(description="Why this operation is needed")
    new_key: str | None = Field(default=None, description="For merge/update: the resulting key")
    new_value: str | None = Field(default=None, description="For merge/update: the resulting value")
    new_confidence: float | None = Field(
        default=None, ge=0.0, le=1.0, description="For merge/update: the resulting confidence"
    )
    gap_type: str | None = Field(
        default=None,
        description="For flag action: executive_function (knows but struggles to initiate/sustain), "
        "knowledge (genuinely doesn't know), context_dependent (both valid in different contexts), "
        "or preference_shift (stated preference outdated, behavior reflects change)",
    )


class DimensionCuration(BaseModel):
    """Curation results for a single profile dimension."""

    dimension: str
    operations: list[CurationOp] = Field(default_factory=list)
    health_score: float = Field(
        ge=0.0, le=1.0, description="0.0 = needs major cleanup, 1.0 = pristine"
    )


curator_agent = Agent(
    get_model("balanced"),
    output_type=DimensionCuration,
    system_prompt=(
        "You are a profile quality curator. Given a set of facts for one dimension of a "
        "user profile, assess their quality and return curation operations.\n\n"
        "Your job is to maintain a clean, operationally useful profile. Every fact should "
        "serve at least one purpose: informing agent constraints, matching behavioral patterns, "
        "tracking goals, or providing context for a specific agent.\n\n"
        "Operations:\n"
        "- **merge**: Two or more facts say the same thing differently. Combine into one with "
        "the best key name, most complete value, and highest justified confidence. List ALL "
        "keys being merged in the 'keys' field.\n"
        "- **delete**: Fact is stale (superseded by newer info), trivially obvious, too vague "
        "to be actionable, or irrelevant to configuring agent behavior. Set 'keys' to the "
        "single key being deleted.\n"
        "- **update**: Fact's key needs normalization (inconsistent naming), value needs "
        "correction, or confidence is miscalibrated. Set 'keys' to the key being updated.\n"
        "- **flag**: Two facts represent an intention-practice gap. Set 'keys' to both facts. "
        "You MUST classify the gap by setting gap_type to one of:\n"
        "  - 'executive_function': operator knows and wants to do X but struggles to initiate or "
        "sustain it. This is the MOST VALUABLE signal — it means the system should reduce friction "
        "for this action, not that the operator is wrong.\n"
        "  - 'knowledge': genuinely doesn't know something.\n"
        "  - 'context_dependent': both values are valid in different contexts.\n"
        "  - 'preference_shift': stated preference is outdated, behavior reflects a genuine change.\n"
        "Include in 'reason' what the gap suggests.\n\n"
        "Guidelines:\n"
        "- Be aggressive about merging redundancy. 'preferred_python_tool: uv' and "
        "'python_package_manager: uv' are the same fact.\n"
        "- Delete facts that are one-off observations rather than stable patterns.\n"
        "- Delete facts that duplicate information already captured in constraints or config.\n"
        "- Normalize keys to consistent snake_case conventions within the dimension.\n"
        "- Contradictions between authority sources (interview, config) and observation sources "
        "(langfuse, shell, git) are intention-practice gaps, not errors. Flag them.\n"
        "- Executive function gaps are the most common type — the operator often knows what to do "
        "but the system doesn't make it easy enough to start. Classify these accurately.\n"
        "- health_score: 1.0 if no operations needed, lower based on severity and count.\n"
        "- If the dimension is clean, return an empty operations list with health_score near 1.0."
    ),
)


# ── Fact merging ─────────────────────────────────────────────────────────────


def _source_prefix(source: str) -> str:
    """Extract the source type prefix (e.g., 'interview' from 'interview:2024-...')."""
    return source.split("/")[0].split(":")[0]


def merge_facts(existing: list[ProfileFact], new: list[ProfileFact]) -> list[ProfileFact]:
    """Merge new facts into existing with authority-aware precedence.

    When a new fact conflicts with an existing fact on the same (dimension, key):
    - Authority source (interview/config/memory/operator) always wins over observation
    - Observation source never overrides an authority source
    - Same source type: higher confidence wins
    """
    fact_map: dict[tuple[str, str], ProfileFact] = {}

    for fact in existing:
        key = (fact.dimension, fact.key)
        fact_map[key] = fact

    for fact in new:
        key = (fact.dimension, fact.key)
        if key not in fact_map:
            fact_map[key] = fact
            continue

        existing_fact = fact_map[key]
        new_is_authority = _source_prefix(fact.source) in AUTHORITY_SOURCES
        existing_is_authority = _source_prefix(existing_fact.source) in AUTHORITY_SOURCES

        if new_is_authority and not existing_is_authority:
            # Authority always overrides observation
            fact_map[key] = fact
        elif existing_is_authority and not new_is_authority:
            # Don't override intent with behavior
            pass
        elif fact.confidence > existing_fact.confidence:
            # Same source type: higher confidence wins
            fact_map[key] = fact

    return list(fact_map.values())


def group_facts_by_dimension(facts: list[ProfileFact]) -> dict[str, list[ProfileFact]]:
    """Group facts by their dimension."""
    groups: dict[str, list[ProfileFact]] = {}
    for fact in facts:
        groups.setdefault(fact.dimension, []).append(fact)
    return groups


# ── Pipeline ─────────────────────────────────────────────────────────────────

from shared.config import PROFILES_DIR

DEFAULT_EXTRACTION_CONCURRENCY = 8

# Early-stop: stop processing a source type when the last N chunks
# produce fewer than THRESHOLD new unique (dimension, key) pairs.
EARLY_STOP_WINDOW = 20
EARLY_STOP_THRESHOLD = 1


async def extract_from_chunks(
    chunks: list[SourceChunk],
    *,
    concurrency: int = DEFAULT_EXTRACTION_CONCURRENCY,
    existing_fact_keys: set[tuple[str, str]] | None = None,
) -> list[ProfileFact]:
    """Run the extraction agent on each chunk with bounded concurrency.

    Args:
        chunks: Text chunks to extract facts from.
        concurrency: Max parallel LLM calls.
        existing_fact_keys: Known (dimension, key) pairs for early-stop detection.
    """
    all_facts: list[ProfileFact] = []
    total = len(chunks)
    completed = 0
    lock = asyncio.Lock()
    sem = asyncio.Semaphore(concurrency)

    # Early-stop tracking: per source_type
    seen_keys: set[tuple[str, str]] = set(existing_fact_keys or ())
    # Per source_type: list of bools — did chunk N produce new keys?
    source_type_new_counts: dict[str, list[int]] = {}
    stopped_types: set[str] = set()

    async def _extract_one(chunk: SourceChunk) -> list[ProfileFact]:
        nonlocal completed

        # Check early-stop before acquiring semaphore
        if chunk.source_type in stopped_types:
            return []

        async with sem:
            # Re-check after acquiring (may have been stopped while waiting)
            if chunk.source_type in stopped_types:
                return []

            prompt = (
                f"Source: {chunk.source_id} (type: {chunk.source_type})\n\n"
                f"--- TEXT ---\n{chunk.text}\n--- END ---"
            )
            try:
                result = await extraction_agent.run(prompt)
                facts = result.output.facts or []
                for fact in facts:
                    fact.source = chunk.source_id
            except Exception as e:
                print(f"    → ERROR [{chunk.source_id}]: {e}", file=sys.stderr, flush=True)
                facts = []

            # Update progress and early-stop tracking
            async with lock:
                completed += 1
                new_key_count = 0
                for fact in facts:
                    fkey = (fact.dimension, fact.key)
                    if fkey not in seen_keys:
                        seen_keys.add(fkey)
                        new_key_count += 1

                st = chunk.source_type
                source_type_new_counts.setdefault(st, []).append(new_key_count)

                # Check early-stop condition
                window = source_type_new_counts[st]
                if len(window) >= EARLY_STOP_WINDOW:
                    recent = window[-EARLY_STOP_WINDOW:]
                    if sum(recent) < EARLY_STOP_THRESHOLD:
                        stopped_types.add(st)
                        print(
                            f"  Early-stop: {st} — last {EARLY_STOP_WINDOW} "
                            f"chunks produced {sum(recent)} new keys",
                            flush=True,
                        )

                if facts:
                    print(
                        f"  [{completed}/{total}] {chunk.source_id} → "
                        f"{len(facts)} facts ({new_key_count} new keys)",
                        flush=True,
                    )
                else:
                    print(f"  [{completed}/{total}] {chunk.source_id} → no facts", flush=True)

            return facts

    # Launch all tasks with bounded concurrency
    tasks = [asyncio.create_task(_extract_one(chunk)) for chunk in chunks]
    results = await asyncio.gather(*tasks)

    for facts in results:
        all_facts.extend(facts)

    if stopped_types:
        print(f"  Early-stopped source types: {', '.join(sorted(stopped_types))}", flush=True)

    return all_facts


async def synthesize_profile(facts: list[ProfileFact]) -> SynthesisOutput:
    """Run the synthesis agent on all collected facts."""
    grouped = group_facts_by_dimension(facts)

    # Build a text representation of all facts for the synthesis agent
    parts: list[str] = []
    for dim, dim_facts in sorted(grouped.items()):
        parts.append(f"## {dim}")
        for f in dim_facts:
            parts.append(
                f"- **{f.key}**: {f.value} (confidence: {f.confidence}, source: {f.source})"
            )
        parts.append("")

    facts_text = "\n".join(parts)
    prompt = (
        f"Synthesize the following extracted facts into a coherent user profile:\n\n{facts_text}"
    )

    result = await synthesis_agent.run(prompt)
    return result.output


def build_profile(
    facts: list[ProfileFact],
    synthesis: SynthesisOutput,
    sources_processed: list[str],
    existing_profile: UserProfile | None = None,
) -> UserProfile:
    """Assemble the final UserProfile from facts and synthesis output."""
    grouped = group_facts_by_dimension(facts)

    dimensions: list[ProfileDimension] = []
    for dim_name in PROFILE_DIMENSIONS:
        dim_facts = grouped.get(dim_name, [])
        summary = synthesis.dimension_summaries.get(dim_name, "")
        if dim_facts or summary:
            dimensions.append(
                ProfileDimension(
                    name=dim_name,
                    summary=summary,
                    facts=dim_facts,
                )
            )

    # Include any extra dimensions not in the default list
    for dim_name in sorted(grouped.keys()):
        if dim_name not in PROFILE_DIMENSIONS:
            dimensions.append(
                ProfileDimension(
                    name=dim_name,
                    summary=synthesis.dimension_summaries.get(dim_name, ""),
                    facts=grouped[dim_name],
                )
            )

    version = (existing_profile.version + 1) if existing_profile else 1

    return UserProfile(
        name=synthesis.name,
        email=synthesis.email,
        summary=synthesis.summary,
        dimensions=dimensions,
        sources_processed=sources_processed,
        version=version,
        updated_at=datetime.now(UTC).isoformat(),
    )


# ── I/O ──────────────────────────────────────────────────────────────────────


def load_existing_profile() -> UserProfile | None:
    """Load existing profile from disk if it exists."""
    path = PROFILES_DIR / "operator-profile.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return UserProfile.model_validate(data)
    except json.JSONDecodeError as e:
        log.warning("Profile %s is corrupt (invalid JSON): %s", path, e)
        return None
    except Exception as e:
        log.warning("Failed to load profile %s: %s", path, e)
        return None


def save_profile(profile: UserProfile) -> None:
    """Save profile to JSON and Markdown."""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)

    # JSON
    json_path = PROFILES_DIR / "operator-profile.json"
    json_path.write_text(profile.model_dump_json(indent=2))
    print(f"Saved: {json_path}")

    # Markdown
    md_path = PROFILES_DIR / "operator-profile.md"
    md_path.write_text(_profile_to_markdown(profile))
    print(f"Saved: {md_path}")


def _profile_to_markdown(profile: UserProfile) -> str:
    """Render a UserProfile as readable Markdown."""
    lines: list[str] = [
        f"# User Profile: {profile.name or 'Unknown'}",
        "",
        f"*Version {profile.version} — {profile.updated_at}*",
        "",
    ]

    if profile.email:
        lines.append(f"**Email:** {profile.email}")
        lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(profile.summary or "*No summary generated yet.*")
    lines.append("")

    for dim in profile.dimensions:
        lines.append(f"## {dim.name.replace('_', ' ').title()}")
        lines.append("")
        if dim.summary:
            lines.append(dim.summary)
            lines.append("")
        if dim.facts:
            lines.append("| Key | Value | Confidence | Source |")
            lines.append("|-----|-------|-----------|--------|")
            for f in sorted(dim.facts, key=lambda x: -x.confidence):
                lines.append(f"| {f.key} | {f.value} | {f.confidence:.1f} | {f.source} |")
            lines.append("")

    # Data gaps
    covered = {d.name for d in profile.dimensions}
    missing = [d for d in PROFILE_DIMENSIONS if d not in covered]
    if missing:
        lines.append("## Data Gaps")
        lines.append("")
        lines.append("The following dimensions have no data yet:")
        lines.append("")
        for m in missing:
            lines.append(f"- {m.replace('_', ' ').title()}")
        lines.append("")

    # Sources
    lines.append("## Sources Processed")
    lines.append("")
    for s in profile.sources_processed:
        lines.append(f"- {s}")
    lines.append("")

    return "\n".join(lines)


# ── Interview integration ────────────────────────────────────────────────────


def flush_interview_facts(
    facts: list,
    insights: list,
    source: str = "interview:cockpit",
) -> str:
    """Merge interview-sourced facts into the profile pipeline.

    Converts RecordedFact objects from the interview system into ProfileFact
    objects and merges them with the existing profile. Does NOT run LLM
    synthesis — just merges facts and saves.

    Args:
        facts: list of RecordedFact (from cockpit.interview).
        insights: list of RecordedInsight (from cockpit.interview).
        source: Source tag for provenance tracking.

    Returns:
        Summary of what was updated.
    """
    if not facts and not insights:
        return "No facts or insights to flush."

    source_tag = source
    now_iso = datetime.now(UTC).isoformat()

    # Convert RecordedFact → ProfileFact
    new_profile_facts: list[ProfileFact] = []
    for rf in facts:
        new_profile_facts.append(
            ProfileFact(
                dimension=rf.dimension,
                key=rf.key,
                value=rf.value,
                confidence=rf.confidence,
                source=source_tag,
                evidence=rf.evidence,
            )
        )

    # Convert insights to facts in the relevant dimension
    insight_dimension_map = {
        "workflow_gap": "work_patterns",
        "goal_refinement": "values",
        "practice_critique": "work_patterns",
        "aspiration": "values",
        "contradiction": "values",
        "neurocognitive_pattern": "neurocognitive",
    }
    for _i, ins in enumerate(insights):
        dim = insight_dimension_map.get(ins.category, "philosophy")
        # Use index + truncated description hash for unique keys across flushes
        desc_hash = hex(hash(ins.description) & 0xFFFF)[2:]
        new_profile_facts.append(
            ProfileFact(
                dimension=dim,
                key=f"insight_{ins.category}_{desc_hash}",
                value=f"{ins.description}. Recommendation: {ins.recommendation}"
                if ins.recommendation
                else ins.description,
                confidence=0.85,
                source=source_tag,
                evidence=f"Interview insight ({ins.category})",
            )
        )

    # Load existing profile and merge
    existing = load_existing_profile()
    if existing:
        existing_facts = [f for dim in existing.dimensions for f in dim.facts]
        merged = merge_facts(existing_facts, new_profile_facts)
    else:
        merged = new_profile_facts

    # Rebuild dimensions (without re-synthesizing — preserve existing summaries)
    grouped = group_facts_by_dimension(merged)
    existing_summaries: dict[str, str] = {}
    if existing:
        existing_summaries = {d.name: d.summary for d in existing.dimensions}

    dimensions: list[ProfileDimension] = []
    for dim_name in PROFILE_DIMENSIONS:
        dim_facts = grouped.get(dim_name, [])
        if dim_facts:
            dimensions.append(
                ProfileDimension(
                    name=dim_name,
                    summary=existing_summaries.get(dim_name, ""),
                    facts=dim_facts,
                )
            )

    # Include extra dimensions
    for dim_name in sorted(grouped.keys()):
        if dim_name not in PROFILE_DIMENSIONS:
            dimensions.append(
                ProfileDimension(
                    name=dim_name,
                    summary=existing_summaries.get(dim_name, ""),
                    facts=grouped[dim_name],
                )
            )

    version = (existing.version + 1) if existing else 1
    updated_profile = UserProfile(
        name=existing.name if existing else "",
        email=existing.email if existing else None,
        summary=existing.summary if existing else "",
        dimensions=dimensions,
        sources_processed=(existing.sources_processed if existing else []) + [source_tag],
        version=version,
        updated_at=now_iso,
    )

    save_profile(updated_profile)

    new_fact_count = len([f for f in facts])
    insight_count = len(insights)
    return (
        f"Flushed {new_fact_count} facts and {insight_count} insights to profile "
        f"(v{version}, {len(merged)} total facts).\n"
        f"Run `profiler --auto` to update dimension summaries."
    )


# ── Operator corrections ──────────────────────────────────────────────────────


def apply_corrections(corrections: list[dict]) -> str:
    """Apply operator corrections to the profile.

    Each correction dict has:
        dimension: str
        key: str
        value: str | None  (None = delete the fact)

    Corrections use source "operator:correction" with confidence 1.0 — the
    highest possible authority.

    Returns summary of changes.
    """
    existing = load_existing_profile()
    if not existing:
        return "No profile found. Run extraction first."

    existing_facts = [f for dim in existing.dimensions for f in dim.facts]
    now_iso = datetime.now(UTC).isoformat()
    applied = 0
    deleted = 0

    for corr in corrections:
        dim = corr.get("dimension", "")
        key = corr.get("key", "")
        value = corr.get("value")

        if value is None:
            # Delete: remove matching facts
            before = len(existing_facts)
            existing_facts = [
                f for f in existing_facts if not (f.dimension == dim and f.key == key)
            ]
            if len(existing_facts) < before:
                deleted += 1
        else:
            # Correct: add/override with max authority
            correction_fact = ProfileFact(
                dimension=dim,
                key=key,
                value=value,
                confidence=1.0,
                source="operator:correction",
                evidence=f"Operator correction at {now_iso}",
            )
            existing_facts = merge_facts(existing_facts, [correction_fact])
            applied += 1

    # Rebuild dimensions
    grouped = group_facts_by_dimension(existing_facts)
    existing_summaries = {d.name: d.summary for d in existing.dimensions}

    dimensions: list[ProfileDimension] = []
    for dim_name in PROFILE_DIMENSIONS:
        dim_facts = grouped.get(dim_name, [])
        if dim_facts:
            dimensions.append(
                ProfileDimension(
                    name=dim_name,
                    summary=existing_summaries.get(dim_name, ""),
                    facts=dim_facts,
                )
            )
    for dim_name in sorted(grouped.keys()):
        if dim_name not in PROFILE_DIMENSIONS:
            dimensions.append(
                ProfileDimension(
                    name=dim_name,
                    summary=existing_summaries.get(dim_name, ""),
                    facts=grouped[dim_name],
                )
            )

    updated_profile = UserProfile(
        name=existing.name,
        email=existing.email,
        summary=existing.summary,
        dimensions=dimensions,
        sources_processed=existing.sources_processed,
        version=existing.version + 1,
        updated_at=now_iso,
    )
    save_profile(updated_profile)

    parts = []
    if applied:
        parts.append(f"{applied} corrected")
    if deleted:
        parts.append(f"{deleted} deleted")
    total = sum(len(d.facts) for d in dimensions)
    return f"Applied corrections ({', '.join(parts)}). Profile v{updated_profile.version}, {total} total facts."


# ── Ingest ───────────────────────────────────────────────────────────────────


def load_structured_facts() -> list[ProfileFact]:
    """Load pre-computed structured facts from profiler bridges.

    These are deterministic facts extracted from structured data
    (Chrome history, search queries, Proton Mail, etc.) without LLM.
    Produced by shared.takeout.profiler_bridge.generate_facts().
    """
    facts: list[ProfileFact] = []

    for facts_file in [
        PROFILES_DIR / "takeout-structured-facts.json",
        PROFILES_DIR / "proton-structured-facts.json",
        PROFILES_DIR / "management-structured-facts.json",
    ]:
        if not facts_file.exists():
            continue
        try:
            data = json.loads(facts_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to load structured facts from %s: %s", facts_file.name, e)
            continue
        if not isinstance(data, list):
            continue
        for item in data:
            try:
                facts.append(ProfileFact.model_validate(item))
            except Exception:
                pass

    return facts


async def ingest_file(path: Path) -> list[ProfileFact]:
    """Ingest an external platform export file.

    Handles two formats:
    1. JSON matching ProfileFact schema (list of fact objects)
    2. Freeform text (run through extraction agent)
    """
    text = path.read_text(encoding="utf-8", errors="replace")

    # Try structured JSON first
    try:
        data = json.loads(text)
        if isinstance(data, list):
            facts: list[ProfileFact] = []
            for item in data:
                try:
                    facts.append(ProfileFact.model_validate(item))
                except Exception:
                    pass  # Skip malformed entries
            if facts:
                print(f"Ingested {len(facts)} structured facts from {path.name}")
                return facts
    except json.JSONDecodeError:
        pass

    # Freeform text fallback: chunk and extract
    print(f"Running extraction on freeform text from {path.name}...")
    from agents.profiler_sources import _chunk_text

    chunks = _chunk_text(text, f"ingest:{path.name}", "ingest")
    return await extract_from_chunks(chunks)


# ── Extraction prompts ───────────────────────────────────────────────────────


def generate_extraction_prompts() -> str:
    """Generate prompts for external platform data extraction."""
    schema_example = json.dumps(
        [
            {
                "dimension": "technical_skills",
                "key": "preferred_language",
                "value": "Python with type hints",
                "confidence": 0.9,
                "source": "platform-history",
                "evidence": "Consistently requests Python solutions with full type annotations",
            },
            {
                "dimension": "communication_style",
                "key": "brevity_preference",
                "value": "Prefers concise, precise responses over verbose explanations",
                "confidence": 0.85,
                "source": "platform-history",
                "evidence": "Frequently asks to shorten responses or get to the point",
            },
        ],
        indent=2,
    )

    dimensions_list = "\n".join(f"- **{d.name}** ({d.kind}): {d.description}" for d in _DIMENSIONS)

    base_instructions = f"""Analyze our complete conversation history and extract a structured profile of me as a user. Return a JSON array of fact objects.

Each fact should follow this schema:
```json
{schema_example}
```

Dimensions to cover:
{dimensions_list}

Guidelines:
- Extract concrete, specific facts — not vague observations
- Set confidence based on how explicit the evidence is (0.9+ for stated preferences, 0.5-0.7 for inferred patterns)
- Use snake_case keys that are descriptive
- Include supporting evidence (direct quotes or paraphrases)
- Cover ALL dimensions where you have data
- Return ONLY the JSON array, no other text"""

    claude_prompt = f"""# Profile Extraction — Claude.ai History

{base_instructions}

**Platform-specific focus for Claude.ai:**
- Communication style: How do I frame technical requests? What level of detail do I expect?
- Problem-solving approach: Do I prefer iterative exploration or direct solutions?
- Decision rationale: In long working sessions, how do I make choices between approaches?
- Technical depth: What assumptions do I make about my own knowledge level?
- Feedback patterns: How do I respond to suggestions — what do I accept, push back on, or refine?

Set the "source" field to "claude-ai-history" for all facts."""

    gemini_prompt = f"""# Profile Extraction — Gemini History

{base_instructions}

**Platform-specific focus for Gemini:**
- Research patterns: What topics do I research deeply vs. ask quick questions about?
- Information usage: How do I apply information after receiving it?
- Knowledge domains: What subjects come up repeatedly?
- Learning style: Do I prefer explanations, examples, references, or a mix?
- Follow-up patterns: Do I iterate on topics or move between subjects?

Set the "source" field to "gemini-history" for all facts."""

    return f"""# External Platform Extraction Prompts

Paste each prompt into the respective platform to extract profile data from your
conversation history. Save the JSON output and ingest it:

```bash
uv run python -m agents.profiler --ingest claude-export.json
uv run python -m agents.profiler --ingest gemini-export.json
```

---

## Claude.ai

```
{claude_prompt}
```

---

## Gemini

```
{gemini_prompt}
```
"""


# ── Profile digest generation ─────────────────────────────────────────────────


async def generate_digest(profile: UserProfile) -> dict:
    """Generate a pre-computed profile digest with per-dimension summaries.

    One LLM call per dimension using the fast model. Samples top facts by
    confidence per dimension for summarization. Returns the digest dict
    and saves it to profiles/operator-digest.json.
    """
    from shared.config import get_model as _get_model

    grouped = group_facts_by_dimension([f for dim in profile.dimensions for f in dim.facts])

    dimensions: dict[str, dict] = {}
    for dim_name in PROFILE_DIMENSIONS:
        facts = grouped.get(dim_name, [])
        count = len(facts)
        if count == 0:
            dimensions[dim_name] = {
                "summary": "No data collected yet.",
                "fact_count": 0,
                "avg_confidence": 0.0,
            }
            continue

        avg_conf = sum(f.confidence for f in facts) / count
        # Sample top 20 facts by confidence for summarization
        top_facts = sorted(facts, key=lambda f: -f.confidence)[:20]
        fact_lines = [f"- {f.key}: {f.value} (conf: {f.confidence})" for f in top_facts]

        try:
            summary_agent = Agent(
                _get_model("fast"),
                system_prompt=(
                    "Summarize these operator profile facts into a concise narrative paragraph "
                    "(200-400 tokens). Focus on key patterns and preferences. "
                    "Write in third person about the operator."
                ),
            )
            result = await summary_agent.run(
                f"Dimension: {dim_name}\n"
                f"Facts ({count} total, showing top {len(top_facts)}):\n" + "\n".join(fact_lines)
            )
            summary = result.output
        except Exception as e:
            log.warning("Failed to summarize dimension %s: %s", dim_name, e)
            summary = f"{count} facts collected, avg confidence {avg_conf:.2f}."

        dimensions[dim_name] = {
            "summary": summary,
            "fact_count": count,
            "avg_confidence": round(avg_conf, 2),
        }

    total_facts = sum(d["fact_count"] for d in dimensions.values())

    digest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "profile_version": profile.version,
        "total_facts": total_facts,
        "overall_summary": profile.summary or "",
        "dimensions": dimensions,
    }

    # Save to disk
    digest_path = PROFILES_DIR / "operator-digest.json"
    digest_path.write_text(json.dumps(digest, indent=2))
    log.info("Saved profile digest: %s (%d facts)", digest_path, total_facts)

    return digest


# ── Operator manifest regeneration ────────────────────────────────────────────


async def regenerate_operator(profile: UserProfile) -> None:
    """Update dynamic sections of operator.json from current profile.

    Preserves hand-curated structural sections (constraints, agent_context_map,
    use_cases). Updates goal progress, patterns, and summary via LLM.
    """
    operator_path = PROFILES_DIR / "operator.json"
    if not operator_path.exists():
        log.info("No operator.json found — skipping regeneration")
        return

    try:
        operator_data = json.loads(operator_path.read_text())
    except json.JSONDecodeError as e:
        # F-1.3: Recover from corrupt operator.json
        backup_path = operator_path.with_suffix(".json.bak")
        if backup_path.exists():
            log.warning("operator.json is corrupt (%s), recovering from backup", e)
            try:
                operator_data = json.loads(backup_path.read_text())
            except json.JSONDecodeError:
                log.error("Both operator.json and backup are corrupt — skipping regeneration")
                return
        else:
            log.error("operator.json is corrupt and no backup exists — skipping regeneration")
            return

    # Build a compact fact summary for the LLM
    grouped = group_facts_by_dimension([f for dim in profile.dimensions for f in dim.facts])
    recent_facts: list[str] = []
    for dim_name, facts in sorted(grouped.items()):
        for f in sorted(facts, key=lambda x: -x.confidence)[:10]:
            recent_facts.append(f"[{dim_name}] {f.key}: {f.value}")

    current_goals = json.dumps(operator_data.get("goals", {}), indent=2)
    current_patterns = json.dumps(operator_data.get("patterns", {}), indent=2)
    current_neurocognitive = json.dumps(operator_data.get("neurocognitive", {}), indent=2)

    prompt = (
        f"Current operator manifest goals:\n{current_goals}\n\n"
        f"Current operator manifest patterns:\n{current_patterns}\n\n"
        f"Current neurocognitive profile:\n{current_neurocognitive}\n\n"
        f"Profile facts (top per dimension, {len(recent_facts)} total):\n" + "\n".join(recent_facts)
    )

    try:
        result = await operator_agent.run(prompt)
        update = result.output
    except Exception as e:
        log.error(f"Operator update failed: {e}")
        return

    changed = False

    # Apply goal progress updates
    if update.goal_updates:
        now_iso = datetime.now(UTC).isoformat()[:19] + "Z"
        for goal_list_key in ("primary", "secondary"):
            goals = operator_data.get("goals", {}).get(goal_list_key, [])
            for goal in goals:
                if goal["id"] in update.goal_updates:
                    goal["progress"] = update.goal_updates[goal["id"]]
                    goal["last_activity_at"] = now_iso
                    changed = True

    # Append new patterns
    if update.new_patterns:
        for pattern in update.new_patterns:
            # Add to workflow patterns by default
            operator_data.setdefault("patterns", {}).setdefault("workflow", [])
            if pattern not in operator_data["patterns"]["workflow"]:
                operator_data["patterns"]["workflow"].append(pattern)
                changed = True

    # Apply neurocognitive updates
    if update.neurocognitive_updates:
        existing_neuro = operator_data.setdefault("neurocognitive", {})
        for category, findings in update.neurocognitive_updates.items():
            existing_list = existing_neuro.setdefault(category, [])
            for finding in findings:
                if finding not in existing_list:
                    existing_list.append(finding)
                    changed = True

    # Update summary if provided
    if update.summary:
        operator_data["operator"]["context"] = update.summary
        changed = True

    if changed:
        # F-1.1: Validate, backup, and atomic write
        new_content = json.dumps(operator_data, indent=2)
        if len(new_content) < 100:
            log.error(
                "Operator update produced suspiciously small output (%d bytes) — aborting write",
                len(new_content),
            )
            return

        # Backup existing before overwrite
        if operator_path.exists():
            backup_path = operator_path.with_suffix(".json.bak")
            import shutil

            shutil.copy2(operator_path, backup_path)

        # Atomic write via temp file
        import tempfile

        tmp_fd, tmp_path = tempfile.mkstemp(dir=operator_path.parent, suffix=".json")
        try:
            with open(tmp_fd, "w", encoding="utf-8") as f:
                f.write(new_content)
            Path(tmp_path).replace(operator_path)
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise

        log.info("Updated operator.json dynamic sections")

        # Regenerate operator.md from the updated JSON
        _regenerate_operator_md(operator_data)
    else:
        log.info("No operator manifest changes needed")


def _regenerate_operator_md(operator_data: dict) -> None:
    """Regenerate operator.md from operator.json data."""
    op = operator_data.get("operator", {})
    constraints = operator_data.get("constraints", {})
    patterns = operator_data.get("patterns", {})
    goals = operator_data.get("goals", {})
    use_cases = operator_data.get("use_cases", [])

    lines: list[str] = [
        f"# Operator Profile: {op.get('name', 'Unknown')}",
        "",
        op.get("context", ""),
        "",
        "## Constraints",
        "",
        "These are hard rules. Agents must never violate them.",
        "",
    ]

    for cat, rules in constraints.items():
        lines.append(f"### {cat.replace('_', ' ').title()}")
        for rule in rules:
            lines.append(f"- {rule}")
        lines.append("")

    lines.append("## Patterns")
    lines.append("")
    lines.append("How the operator works. Agents should anticipate and match these.")
    lines.append("")

    for cat, items in patterns.items():
        lines.append(f"### {cat.replace('_', ' ').title()}")
        for item in items:
            lines.append(f"- {item}")
        lines.append("")

    neurocognitive = operator_data.get("neurocognitive", {})
    if neurocognitive:
        lines.append("## Neurocognitive Profile")
        lines.append("")
        lines.append("Discovered cognitive patterns — agents should accommodate these.")
        lines.append("")
        for cat, findings in neurocognitive.items():
            lines.append(f"### {cat.replace('_', ' ').title()}")
            for finding in findings:
                lines.append(f"- {finding}")
            lines.append("")

    lines.append("## Active Goals")
    lines.append("")
    for label, goal_list in goals.items():
        lines.append(f"### {label.title()}")
        for i, goal in enumerate(goal_list, 1):
            progress = goal.get("progress", "")
            desc = goal.get("description", "")
            lines.append(f"{i}. **{goal.get('name', '')}** — {desc}")
            if progress:
                lines.append(f"   *{progress}*")
        lines.append("")

    lines.append("## Use Cases")
    lines.append("")
    for uc in use_cases:
        lines.append(f"### {uc.get('name', '')}")
        lines.append(uc.get("description", ""))
        lines.append("")

    md_path = PROFILES_DIR / "operator.md"
    md_path.write_text("\n".join(lines))
    log.info("Regenerated operator.md")


# ── Profile curation ─────────────────────────────────────────────────────────


def apply_curation(
    facts: list[ProfileFact],
    curation: DimensionCuration,
) -> tuple[list[ProfileFact], list[CurationOp]]:
    """Apply curation operations to a list of facts for one dimension.

    Returns (curated_facts, flagged_ops) — flagged ops need human review.
    """
    fact_map = {f.key: f for f in facts}
    flagged: list[CurationOp] = []

    for op in curation.operations:
        if op.action == "delete":
            for key in op.keys:
                fact_map.pop(key, None)

        elif op.action == "merge":
            # Remove all source keys, insert merged fact
            source_facts = [fact_map.pop(k) for k in op.keys if k in fact_map]
            if source_facts and op.new_key and op.new_value is not None:
                # Use highest confidence from sources, or the explicit override
                best_confidence = op.new_confidence or max(f.confidence for f in source_facts)
                # Combine sources
                all_sources = ", ".join(sorted({f.source for f in source_facts}))
                fact_map[op.new_key] = ProfileFact(
                    dimension=curation.dimension,
                    key=op.new_key,
                    value=op.new_value,
                    confidence=best_confidence,
                    source=all_sources,
                    evidence=f"Merged from: {', '.join(op.keys)}. {op.reason}",
                )

        elif op.action == "update":
            for key in op.keys:
                if key not in fact_map:
                    continue
                fact = fact_map[key]
                # If key is being renamed, remove old and insert new
                target_key = op.new_key or key
                if target_key != key:
                    fact_map.pop(key)
                fact_map[target_key] = ProfileFact(
                    dimension=curation.dimension,
                    key=target_key,
                    value=op.new_value or fact.value,
                    confidence=op.new_confidence
                    if op.new_confidence is not None
                    else fact.confidence,
                    source=fact.source,
                    evidence=fact.evidence,
                )

        elif op.action == "flag":
            flagged.append(op)

    return list(fact_map.values()), flagged


async def curate_profile(profile: UserProfile) -> tuple[UserProfile, list[CurationOp]]:
    """Run the curator agent on each dimension of the profile.

    Returns (curated_profile, all_flagged_ops).
    """
    # Load operator manifest for fitness context
    operator_path = PROFILES_DIR / "operator.json"
    fitness_context = ""
    if operator_path.exists():
        op_data = json.loads(operator_path.read_text())
        agent_names = list(op_data.get("agent_context_map", {}).keys())
        constraint_cats = list(op_data.get("constraints", {}).keys())
        fitness_context = (
            f"\n\nFitness context — facts should serve these agents: {', '.join(agent_names)}. "
            f"Constraint categories: {', '.join(constraint_cats)}. "
            "Facts that don't inform any agent's behavior or any constraint are candidates for deletion."
        )

    all_flagged: list[CurationOp] = []
    curated_dimensions: list[ProfileDimension] = []
    total_ops = 0

    for dim in profile.dimensions:
        if not dim.facts:
            curated_dimensions.append(dim)
            continue

        # Build fact listing for the curator
        fact_lines = []
        for f in dim.facts:
            fact_lines.append(
                f"- **{f.key}**: {f.value} (confidence={f.confidence:.2f}, source={f.source})"
            )

        prompt = (
            f"Dimension: {dim.name}\n"
            f"Fact count: {len(dim.facts)}\n\n" + "\n".join(fact_lines) + fitness_context
        )

        print(f"  Curating {dim.name} ({len(dim.facts)} facts)...", flush=True)
        try:
            result = await curator_agent.run(prompt)
            curation = result.output

            curated_facts, flagged = apply_curation(dim.facts, curation)
            all_flagged.extend(flagged)
            total_ops += len(curation.operations)

            op_summary = []
            for action in ("merge", "delete", "update", "flag"):
                count = sum(1 for o in curation.operations if o.action == action)
                if count:
                    op_summary.append(f"{count} {action}")

            if op_summary:
                print(
                    f"    → {', '.join(op_summary)} | health: {curation.health_score:.2f}",
                    flush=True,
                )
            else:
                print(f"    → clean | health: {curation.health_score:.2f}", flush=True)

            curated_dimensions.append(
                ProfileDimension(
                    name=dim.name,
                    summary=dim.summary,
                    facts=curated_facts,
                )
            )

        except Exception as e:
            log.error(f"Curation failed for {dim.name}: {e}")
            curated_dimensions.append(dim)  # Keep uncurated on failure

    before_count = sum(len(d.facts) for d in profile.dimensions)
    after_count = sum(len(d.facts) for d in curated_dimensions)

    curated_profile = profile.model_copy(
        update={
            "dimensions": curated_dimensions,
            "version": profile.version + 1,
            "updated_at": datetime.now(UTC).isoformat(),
        }
    )

    print(f"\nCuration complete: {total_ops} operations applied")
    print(f"  Facts: {before_count} → {after_count} ({before_count - after_count} removed/merged)")
    if all_flagged:
        print(f"  Flagged for review: {len(all_flagged)}")

    return curated_profile, all_flagged


async def run_curate() -> None:
    """Run curation on existing profile."""
    profile = load_existing_profile()
    if not profile:
        print("No profile found. Run extraction first.")
        return

    fact_count = sum(len(d.facts) for d in profile.dimensions)
    print(
        f"Curating profile v{profile.version} ({fact_count} facts, "
        f"{len(profile.dimensions)} dimensions)...\n"
    )

    curated, flagged = await curate_profile(profile)
    save_profile(curated)

    # Re-synthesize after curation since facts changed
    all_facts = [f for dim in curated.dimensions for f in dim.facts]
    print("\nRe-synthesizing after curation...")
    synthesis = await synthesize_profile(all_facts)

    # Update summaries
    final_dims = []
    for dim in curated.dimensions:
        new_summary = synthesis.dimension_summaries.get(dim.name, dim.summary)
        final_dims.append(ProfileDimension(name=dim.name, summary=new_summary, facts=dim.facts))

    final = curated.model_copy(
        update={
            "summary": synthesis.summary,
            "dimensions": final_dims,
        }
    )
    save_profile(final)

    # Append flagged items to the markdown
    if flagged:
        md_path = PROFILES_DIR / "operator-profile.md"
        flag_lines = ["\n## Flagged for Review\n"]
        for op in flagged:
            prefix = f"[{op.gap_type}] " if op.gap_type else ""
            flag_lines.append(f"- {prefix}**{', '.join(op.keys)}**: {op.reason}")
        with open(md_path, "a") as f:
            f.write("\n".join(flag_lines) + "\n")
        print(f"\nFlagged items appended to {md_path}")


# ── CLI ──────────────────────────────────────────────────────────────────────


async def run_extraction(
    source_filter: str | None = None,
    force_full: bool = False,
) -> None:
    """Main extraction pipeline."""
    with _tracer.start_as_current_span(
        "profiler.extract",
        attributes={"agent.name": "profiler", "agent.repo": "hapax-council"},
    ):
        return await _run_extraction_impl(source_filter, force_full)


async def _run_extraction_impl(
    source_filter: str | None = None,
    force_full: bool = False,
) -> None:
    """Implementation of run_extraction, wrapped by OTel span."""
    existing = load_existing_profile()

    # Determine which sources to skip
    skip_ids: set[str] = set()
    if existing and not force_full:
        skip_ids = set(existing.sources_processed)

    # Exclude bridged source types unless explicitly requested via --source
    exclude_types: set[str] | None = None
    if source_filter is None or source_filter not in BRIDGED_SOURCE_TYPES:
        exclude_types = BRIDGED_SOURCE_TYPES

    # Discover and read sources
    sources = discover_sources()
    all_source_ids = list_source_ids(sources)
    print(f"Discovered {len(all_source_ids)} sources")

    chunks = read_all_sources(
        sources,
        source_filter=source_filter,
        skip_source_ids=skip_ids,
        exclude_source_types=exclude_types,
    )
    if not chunks:
        print("No new sources to process.")
        if existing:
            print(
                f"Current profile: v{existing.version} with {sum(len(d.facts) for d in existing.dimensions)} facts"
            )
        return

    print(f"Processing {len(chunks)} chunks...")
    print()

    # Collect existing fact keys for early-stop detection
    existing_facts: list[ProfileFact] = []
    if existing and not force_full:
        for dim in existing.dimensions:
            existing_facts.extend(dim.facts)
    existing_keys = {(f.dimension, f.key) for f in existing_facts}

    # Extract facts from chunks
    new_facts = await extract_from_chunks(chunks, existing_fact_keys=existing_keys)
    print(f"\nExtracted {len(new_facts)} total facts")

    # Load pre-computed structured facts (deterministic, zero LLM cost)
    structured_facts = load_structured_facts()
    if structured_facts:
        print(f"Loaded {len(structured_facts)} structured facts from bridges")
        new_facts.extend(structured_facts)

    all_facts = merge_facts(existing_facts, new_facts)
    print(
        f"Merged to {len(all_facts)} facts ({len(existing_facts)} existing + {len(new_facts)} new)"
    )

    # Synthesize
    print("\nSynthesizing profile...")
    synthesis = await synthesize_profile(all_facts)

    # Track processed sources
    new_source_ids = {c.source_id for c in chunks}
    all_processed = sorted(set(existing.sources_processed if existing else []) | new_source_ids)

    # Build and save
    profile = build_profile(all_facts, synthesis, all_processed, existing)
    save_profile(profile)
    print(f"\nProfile v{profile.version}: {profile.name or 'Unknown'}")
    print(f"  {len(all_facts)} facts across {len(profile.dimensions)} dimensions")

    # Persist state for change detection and update operator manifest
    mtimes = get_source_mtimes(sources)
    save_state(mtimes, all_processed)
    await regenerate_operator(profile)


async def run_ingest(file_path: str) -> None:
    """Ingest external platform export."""
    path = Path(file_path)
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    existing = load_existing_profile()
    existing_facts: list[ProfileFact] = []
    if existing:
        for dim in existing.dimensions:
            existing_facts.extend(dim.facts)

    new_facts = await ingest_file(path)
    if not new_facts:
        print("No facts extracted from file")
        return

    all_facts = merge_facts(existing_facts, new_facts)

    print(f"\nSynthesizing with {len(all_facts)} total facts...")
    synthesis = await synthesize_profile(all_facts)

    source_id = f"ingest:{path.name}"
    all_processed = sorted(set(existing.sources_processed if existing else []) | {source_id})

    profile = build_profile(all_facts, synthesis, all_processed, existing)
    save_profile(profile)
    print(f"Profile updated to v{profile.version} with {len(all_facts)} facts")

    # Update operator manifest after ingest
    await regenerate_operator(profile)


def run_show() -> None:
    """Display current profile."""
    profile = load_existing_profile()
    if not profile:
        print("No profile found. Run extraction first:")
        print("  uv run python -m agents.profiler")
        return

    md_path = PROFILES_DIR / "operator-profile.md"
    if md_path.exists():
        print(md_path.read_text())
    else:
        print(_profile_to_markdown(profile))


def run_generate_prompts() -> None:
    """Generate and save extraction prompts for external platforms."""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    prompts = generate_extraction_prompts()
    out_path = PROFILES_DIR / "extraction-prompts.md"
    out_path.write_text(prompts)
    print(f"Saved: {out_path}")
    print(prompts)


async def run_digest() -> None:
    """Generate profile digest only."""
    profile = load_existing_profile()
    if not profile:
        print("No profile found. Run extraction first.")
        return
    digest = await generate_digest(profile)
    print(
        f"Generated digest: {digest['total_facts']} facts across {len(digest['dimensions'])} dimensions"
    )
    print(f"Saved to: {PROFILES_DIR / 'operator-digest.json'}")


async def run_index_profile() -> None:
    """Index profile facts into Qdrant profile-facts collection."""
    from shared.profile_store import ProfileStore

    profile = load_existing_profile()
    if not profile:
        print("No profile found. Run extraction first.")
        return
    store = ProfileStore()
    store.ensure_collection()
    count = store.index_profile(profile)
    print(f"Indexed {count} profile facts into Qdrant profile-facts collection")


async def run_auto() -> None:
    """Unattended auto-update: detect changes, extract if needed, update operator.

    Designed for systemd timer / cron invocation. Exits quickly (no LLM calls)
    when nothing has changed. Logs to stderr for journal compatibility.
    """
    from shared.log_setup import configure_logging

    configure_logging(agent="profiler")

    # Pre-flight: abort early if critical services are unreachable
    try:
        from agents.health_monitor import quick_check

        ok, results = await quick_check(["litellm", "qdrant"])
        if not ok:
            failed = [r for r in results if r.status.value != "healthy"]
            for r in failed:
                log.error("Pre-flight failed: %s — %s", r.name, r.message)
            log.error("Aborting: required services unreachable")
            return
    except ImportError:
        pass  # health_monitor not available — skip pre-flight

    sources = discover_sources()
    changed, new = detect_changed_sources(sources)

    if not changed and not new:
        log.info("No source changes detected — nothing to do")
        return

    log.info(
        "Changes detected: %d modified, %d new sources",
        len(changed),
        len(new),
    )
    for sid in sorted(changed):
        log.info("  modified: %s", sid)
    for sid in sorted(new):
        log.info("  new: %s", sid)

    # Read only changed/new sources, excluding bridged types from LLM extraction
    skip_ids = set(list_source_ids(sources)) - changed - new
    chunks = read_all_sources(
        sources,
        skip_source_ids=skip_ids,
        exclude_source_types=BRIDGED_SOURCE_TYPES,
    )

    # Load pre-computed structured facts (deterministic, zero LLM cost)
    # Must happen regardless of whether text chunks exist — bridge sources
    # are excluded from LLM extraction but their facts still need merging.
    structured_facts = load_structured_facts()
    if structured_facts:
        log.info("Loaded %d structured facts from bridges", len(structured_facts))

    if not chunks and not structured_facts:
        log.info("Changed sources produced no readable chunks and no structured facts")
        mtimes = get_source_mtimes(sources)
        save_state(mtimes, list_source_ids(sources))
        return

    # Load existing profile and collect fact keys for early-stop
    existing = load_existing_profile()
    existing_facts: list[ProfileFact] = []
    if existing:
        for dim in existing.dimensions:
            existing_facts.extend(dim.facts)
    existing_keys = {(f.dimension, f.key) for f in existing_facts}

    # Extract from text chunks (LLM-based, concurrent with early-stop)
    new_facts: list[ProfileFact] = []
    if chunks:
        log.info("Processing %d chunks from changed sources", len(chunks))
        new_facts = await extract_from_chunks(chunks, existing_fact_keys=existing_keys)
        log.info("Extracted %d facts from text sources", len(new_facts))

    if structured_facts:
        new_facts.extend(structured_facts)

    all_facts = merge_facts(existing_facts, new_facts)
    log.info(
        "Merged to %d facts (%d existing + %d new)",
        len(all_facts),
        len(existing_facts),
        len(new_facts),
    )

    # Synthesize
    synthesis = await synthesize_profile(all_facts)

    # Track sources
    new_source_ids = {c.source_id for c in chunks}
    all_processed = sorted(set(existing.sources_processed if existing else []) | new_source_ids)

    # Build, save, persist state
    profile = build_profile(all_facts, synthesis, all_processed, existing)
    save_profile(profile)
    log.info(
        "Profile v%d: %d facts across %d dimensions",
        profile.version,
        len(all_facts),
        len(profile.dimensions),
    )

    # Curate after extraction
    log.info("Running post-extraction curation")
    curated, flagged = await curate_profile(profile)
    save_profile(curated)

    # Re-synthesize after curation
    curated_facts = [f for dim in curated.dimensions for f in dim.facts]
    synthesis = await synthesize_profile(curated_facts)
    final_dims = []
    for dim in curated.dimensions:
        new_summary = synthesis.dimension_summaries.get(dim.name, dim.summary)
        final_dims.append(ProfileDimension(name=dim.name, summary=new_summary, facts=dim.facts))
    final = curated.model_copy(update={"summary": synthesis.summary, "dimensions": final_dims})
    save_profile(final)

    if flagged:
        log.warning("Flagged %d items for human review", len(flagged))

    mtimes = get_source_mtimes(sources)
    save_state(mtimes, all_processed)
    await regenerate_operator(final)

    # Generate digest and index to Qdrant for context tools
    try:
        digest = await generate_digest(final)
        log.info("Generated digest: %d facts", digest["total_facts"])
    except Exception as e:
        log.warning("Digest generation failed: %s", e)

    try:
        from shared.profile_store import ProfileStore

        store = ProfileStore()
        store.ensure_collection()
        count = store.index_profile(final)
        log.info("Indexed %d facts to profile-facts collection", count)
    except Exception as e:
        log.warning("Profile indexing failed: %s", e)

    log.info("Auto-update complete")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="User profile extraction agent",
        prog="python -m agents.profiler",
    )
    parser.add_argument(
        "--source",
        choices=[
            "config",
            "transcript",
            "shell-history",
            "git",
            "memory",
            "llm-export",
            "takeout",
            "proton",
            "management",
            "drift",
            "conversation",
            "decisions",
            "langfuse",
        ],
        help="Only process this source type",
    )
    parser.add_argument(
        "--generate-prompts",
        action="store_true",
        help="Output extraction prompts for external platforms",
    )
    parser.add_argument("--ingest", metavar="FILE", help="Import external platform data from file")
    parser.add_argument("--show", action="store_true", help="Display current profile")
    parser.add_argument(
        "--full", action="store_true", help="Force complete re-extraction (ignore cached sources)"
    )
    parser.add_argument(
        "--auto", action="store_true", help="Unattended mode: detect changes, update if needed"
    )
    parser.add_argument(
        "--curate", action="store_true", help="Run quality curation on existing profile"
    )
    parser.add_argument(
        "--digest", action="store_true", help="Generate profile digest (per-dimension summaries)"
    )
    parser.add_argument(
        "--index-profile",
        action="store_true",
        help="Index profile facts into Qdrant profile-facts collection",
    )

    args = parser.parse_args()

    if args.digest:
        await run_digest()
    elif args.index_profile:
        await run_index_profile()
    elif args.curate:
        await run_curate()
    elif args.auto:
        await run_auto()
    elif args.show:
        run_show()
    elif args.generate_prompts:
        run_generate_prompts()
    elif args.ingest:
        await run_ingest(args.ingest)
    else:
        await run_extraction(source_filter=args.source, force_full=args.full)


if __name__ == "__main__":
    asyncio.run(main())
