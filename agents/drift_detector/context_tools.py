"""Vendored from shared/context_tools.py — on-demand operator context tools."""

from __future__ import annotations

import logging

from pydantic_ai import RunContext  # noqa: TC002

log = logging.getLogger("drift_detector.context_tools")


async def lookup_constraints(ctx: RunContext[None], categories: str = "") -> str:
    """Look up operator constraints (rules) by category.

    Categories: communication, python, node, docker, llm, agents, secrets, git, music.

    Args:
        categories: Comma-separated constraint categories to look up.
    """
    log.info("context_tool_invoked tool=lookup_constraints categories=%s", categories)
    from .operator import get_constraints

    cats = tuple(c.strip() for c in categories.split(",") if c.strip()) if categories else ()
    try:
        rules = get_constraints(*cats)
    except Exception as e:
        return f"Error loading constraints: {e}"

    if not rules:
        return (
            f"No constraints found for categories: {categories}"
            if categories
            else "No constraints found."
        )

    lines = [f"Operator constraints ({len(rules)} rules):"]
    for rule in rules:
        lines.append(f"- {rule}")
    return "\n".join(lines)


async def lookup_patterns(ctx: RunContext[None], categories: str = "") -> str:
    """Look up operator behavioral patterns by category.

    Categories: decision_making, workflow, development, music_production, communication.

    Args:
        categories: Comma-separated pattern categories to look up.
    """
    log.info("context_tool_invoked tool=lookup_patterns categories=%s", categories)
    from .operator import get_patterns

    cats = tuple(c.strip() for c in categories.split(",") if c.strip()) if categories else ()
    try:
        patterns = get_patterns(*cats)
    except Exception as e:
        return f"Error loading patterns: {e}"

    if not patterns:
        return (
            f"No patterns found for categories: {categories}"
            if categories
            else "No patterns found."
        )

    lines = [f"Operator patterns ({len(patterns)} items):"]
    for pattern in patterns:
        lines.append(f"- {pattern}")
    return "\n".join(lines)


async def search_profile(ctx: RunContext[None], query: str, dimension: str = "") -> str:
    """Semantic search over operator profile facts via Qdrant.

    Args:
        query: Natural language search query.
        dimension: Optional dimension filter.
    """
    log.info("context_tool_invoked tool=search_profile query=%s dimension=%s", query, dimension)
    try:
        from shared.profile_store import ProfileStore

        store = ProfileStore()
        results = store.search(
            query,
            dimension=dimension or None,
            limit=5,
        )
    except Exception as e:
        return f"Profile search unavailable: {e}"

    if not results:
        return f"No profile facts found for: {query}"

    lines = [f"Profile facts matching '{query}':"]
    for r in results:
        lines.append(
            f"- [{r['dimension']}] {r['key']}: {r['value']} "
            f"(confidence: {r['confidence']:.1f}, relevance: {r['score']:.2f})"
        )
    return "\n".join(lines)


async def get_profile_summary(ctx: RunContext[None], dimension: str = "") -> str:
    """Get pre-computed profile summary, overall or for a specific dimension.

    Args:
        dimension: Profile dimension name. Empty for overall.
    """
    log.info("context_tool_invoked tool=get_profile_summary dimension=%s", dimension)
    try:
        from shared.profile_store import ProfileStore

        store = ProfileStore()
        digest = store.get_digest()
    except Exception as e:
        return f"Profile digest unavailable: {e}"

    if not digest:
        return "No profile digest available."

    if dimension:
        summary = digest.get("dimensions", {}).get(dimension, {}).get("summary")
        if summary:
            dim_info = digest["dimensions"][dimension]
            return (
                f"Profile dimension: {dimension}\n"
                f"Facts: {dim_info.get('fact_count', '?')}, "
                f"Avg confidence: {dim_info.get('avg_confidence', '?')}\n\n"
                f"{summary}"
            )
        available = ", ".join(digest.get("dimensions", {}).keys())
        return f"Dimension '{dimension}' not found. Available: {available}"

    lines = [f"Operator profile ({digest.get('total_facts', '?')} facts):"]
    if digest.get("overall_summary"):
        lines.append(digest["overall_summary"])
    lines.append("")
    for dim_name, dim_data in digest.get("dimensions", {}).items():
        count = dim_data.get("fact_count", 0)
        conf = dim_data.get("avg_confidence", 0)
        lines.append(f"  {dim_name}: {count} facts, avg confidence {conf:.2f}")
    return "\n".join(lines)


async def lookup_sufficiency_requirements(
    ctx: RunContext[None], axiom_id: str = "", level: str = "", domain: str = ""
) -> str:
    """Look up what the system must actively provide to satisfy axiom sufficiency requirements.

    Args:
        axiom_id: Specific axiom. Empty for all.
        level: Filter by level: "component", "subsystem", or "system". Empty for all.
        domain: Include domain axioms for this domain.
    """
    log.info(
        "context_tool_invoked tool=lookup_sufficiency_requirements axiom_id=%s level=%s domain=%s",
        axiom_id,
        level,
        domain,
    )
    try:
        from .axiom_registry import load_axioms, load_implications

        if domain:
            axioms = load_axioms(scope="constitutional") + load_axioms(domain=domain)
        else:
            axioms = load_axioms()

        if not axioms:
            return "No axioms defined in registry."

        if axiom_id:
            axioms = [a for a in axioms if a.id == axiom_id]
            if not axioms:
                return f"Axiom '{axiom_id}' not found or not active."

        sections: list[str] = []
        for axiom in axioms:
            impls = load_implications(axiom.id)
            suff = [i for i in impls if i.mode == "sufficiency"]
            if level:
                suff = [i for i in suff if i.level == level]
            if not suff:
                continue
            lines = [f"**{axiom.id}** -- {len(suff)} sufficiency requirement(s):"]
            for impl in suff:
                lines.append(f"  [{impl.tier}/{impl.level}] {impl.id}: {impl.text}")
            sections.append("\n".join(lines))

        if not sections:
            filters = []
            if axiom_id:
                filters.append(f"axiom={axiom_id}")
            if level:
                filters.append(f"level={level}")
            return f"No sufficiency requirements found ({', '.join(filters) or 'any'})."

        return "\n\n".join(sections)
    except Exception as e:
        return f"Error loading sufficiency requirements: {e}"


def get_context_tools() -> list:
    """Return the list of context tool functions for agent registration."""
    return [
        lookup_constraints,
        lookup_patterns,
        search_profile,
        get_profile_summary,
        lookup_sufficiency_requirements,
    ]
