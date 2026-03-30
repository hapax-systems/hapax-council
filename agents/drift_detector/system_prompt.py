"""System prompt fragment builder for agents."""

from __future__ import annotations

from .operator import SYSTEM_CONTEXT, _load_operator, get_constraints, get_patterns
from .shm_readers import read_apperception_block, read_stimmung_block, read_temporal_block


def get_system_prompt_fragment(agent_name: str) -> str:
    """Build a system prompt fragment for a specific agent."""
    data = _load_operator()

    lines: list[str] = [SYSTEM_CONTEXT, ""]

    if not data:
        return "\n".join(lines)

    operator = data.get("operator", {})

    operator_name = operator.get("name", "Unknown")
    lines.append(f"Operator: {operator_name} -- {operator.get('role', '')}")
    lines.append(operator.get("context", ""))

    # Axiom injection
    axioms = data.get("axioms", {})
    try:
        from .axiom_registry import load_axioms as _load_axioms

        registry_axioms = _load_axioms()
        if registry_axioms:
            lines.append("")
            lines.append(
                "System axioms (check_axiom_compliance tool available for compliance checks):"
            )
            for ax in registry_axioms:
                lines.append(f"- [{ax.id}] {ax.text.strip()}")
        else:
            raise ImportError("No axioms in registry")
    except ImportError:
        if axioms.get("single_user"):
            lines.append(
                f"This is a single-user system. All data and preferences belong to {operator_name}."
            )
        if axioms.get("executive_function"):
            lines.append(
                "This system is externalized executive function infrastructure. "
                "Reduce friction and decision load in all recommendations. "
                "Surface stalled work as observation, never judgment."
            )

    neuro = data.get("neurocognitive", {})
    if neuro:
        lines.append(
            "Neurocognitive patterns (discovered through operator interview -- "
            "accommodate these in all interactions):"
        )
        for category, findings in neuro.items():
            cat_label = category.replace("_", " ").title()
            lines.append(f"  {cat_label}:")
            for finding in findings:
                lines.append(f"    - {finding}")
    lines.append("")

    # Agent-specific context injection
    context_map = data.get("agent_context_map", {}).get(agent_name, {})
    inject_paths = context_map.get("inject", [])

    if inject_paths:
        constraint_cats: list[str] = []
        pattern_cats: list[str] = []

        for dotpath in inject_paths:
            parts = dotpath.split(".", 1)
            if len(parts) != 2:
                continue
            section, key = parts
            if section == "constraints":
                constraint_cats.append(key)
            elif section == "patterns":
                pattern_cats.append(key)

        if constraint_cats:
            rules = get_constraints(*constraint_cats)
            if rules:
                lines.append("Relevant constraints:")
                for rule in rules:
                    lines.append(f"- {rule}")
                lines.append("")

        if pattern_cats:
            items = get_patterns(*pattern_cats)
            if items:
                lines.append("Relevant behavioral patterns:")
                for item in items:
                    lines.append(f"- {item}")
                lines.append("")

    domain_knowledge = context_map.get("domain_knowledge", "")
    if domain_knowledge:
        lines.append("Domain context:")
        lines.append(domain_knowledge)
        lines.append("")

    stimmung_block = read_stimmung_block()
    if stimmung_block:
        lines.append(stimmung_block)
        lines.append("")

    temporal_block = read_temporal_block()
    if temporal_block:
        lines.append(temporal_block)
        lines.append("")

    apperception_block = read_apperception_block()
    if apperception_block:
        lines.append(apperception_block)
        lines.append("")

    return "\n".join(lines)
