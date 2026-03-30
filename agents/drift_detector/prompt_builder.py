"""Build LLM prompts for drift detection — goals and axiom sections."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def build_goals_section() -> str:
    """Build the operator goals section for the drift prompt."""
    from .operator import get_goals

    goals = get_goals()[:5]
    if not goals:
        return ""

    goal_lines = []
    for g in goals:
        status = g.get("status", "unknown")
        goal_lines.append(f"- [{status}] {g.get('name', '')}: {g.get('description', '')}")
    return f"\n\n## Operator Goals\n{chr(10).join(goal_lines)}"


def build_axiom_section() -> str:
    """Build the axiom compliance section for the drift prompt."""
    try:
        from .axiom_registry import load_axioms, load_implications

        active_axioms = load_axioms()
        if not active_axioms:
            return ""

        axiom_lines = ["\n\n## Active Axioms (check for compliance)"]
        for ax in active_axioms:
            scope_label = (
                f"[{ax.scope}]" if ax.scope == "constitutional" else f"[domain:{ax.domain}]"
            )
            axiom_lines.append(f"\n### {ax.id} {scope_label} (weight={ax.weight}, type={ax.type})")
            axiom_lines.append(ax.text.strip())
            impls = load_implications(ax.id)
            blocking = [i for i in impls if i.enforcement in ("block", "review")]
            if blocking:
                axiom_lines.append("Key implications to check:")
                for impl in blocking:
                    axiom_lines.append(f"  - [{impl.tier}/{impl.mode}/{impl.level}] {impl.text}")
            sufficiency = [i for i in impls if i.mode == "sufficiency"]
            if sufficiency:
                axiom_lines.append("Sufficiency requirements (check active support):")
                for impl in sufficiency:
                    axiom_lines.append(f"  - [{impl.tier}/{impl.level}] {impl.text}")
        return "\n".join(axiom_lines)
    except Exception as e:
        log.warning("Could not load axioms for drift check: %s", e)
        return ""
