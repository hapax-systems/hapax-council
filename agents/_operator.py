"""agents/_operator.py — Vendored operator profile integration.

Copied from shared/operator.py to dissolve the shared module dependency.
Each function that was imported by agents is preserved here.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

# PROFILES_DIR — previously from shared.config
PROFILES_DIR: Path = Path(__file__).resolve().parent.parent / "profiles"

log = logging.getLogger("agents._operator")

_operator_cache: dict | None = None


class OperatorSchema(BaseModel, extra="allow"):
    """Minimal validation for operator.json top-level structure."""

    version: int | str = 0
    operator: dict = Field(default_factory=dict)


# Core system context — lean identity only.
SYSTEM_CONTEXT = """\
System: Externalized executive function infrastructure for a single operator.

The operator has ADHD and autism — task initiation, sustained attention, and \
routine maintenance are genuine cognitive challenges. This system offloads \
cognitive overhead, maintains continuity, monitors health autonomously, and \
surfaces what needs attention. Behavioral variance is expected baseline.

You are a component of this system. Use your context tools to look up operator \
constraints, patterns, and profile facts when needed.\
"""


def _load_operator() -> dict:
    """Load and cache operator.json."""
    global _operator_cache
    if _operator_cache is not None:
        return _operator_cache

    path = PROFILES_DIR / "operator.json"
    if not path.exists():
        _operator_cache = {}
        return _operator_cache

    try:
        raw = json.loads(path.read_text())
        OperatorSchema.model_validate(raw)
        _operator_cache = raw
    except (json.JSONDecodeError, ValidationError) as e:
        log.warning("operator.json validation failed: %s — using defaults", e)
        _operator_cache = {}
    return _operator_cache


def get_operator() -> dict:
    """Return the full operator manifest."""
    return _load_operator()


def reload_operator() -> None:
    """Clear operator cache, forcing re-read from disk on next access."""
    global _operator_cache
    _operator_cache = None


def get_axioms() -> dict[str, str]:
    """Return the system axioms."""
    data = _load_operator()
    return data.get("axioms", {})


def get_constraints(*categories: str) -> list[str]:
    """Get constraint rules for given categories."""
    data = _load_operator()
    all_constraints = data.get("constraints", {})

    if not categories:
        categories = tuple(all_constraints.keys())

    rules: list[str] = []
    for cat in categories:
        rules.extend(all_constraints.get(cat, []))
    return rules


def get_patterns(*categories: str) -> list[str]:
    """Get behavioral patterns for given categories."""
    data = _load_operator()
    all_patterns = data.get("patterns", {})

    if not categories:
        categories = tuple(all_patterns.keys())

    items: list[str] = []
    for cat in categories:
        items.extend(all_patterns.get(cat, []))
    return items


def get_goals() -> list[dict]:
    """Get active goals (primary + secondary)."""
    data = _load_operator()
    goals = data.get("goals", {})
    return goals.get("primary", []) + goals.get("secondary", [])


def get_agent_context(agent_name: str) -> dict:
    """Get the context map entry for a specific agent."""
    data = _load_operator()
    return data.get("agent_context_map", {}).get(agent_name, {})


def get_neurocognitive_profile() -> dict[str, list[str]]:
    """Return the neurocognitive profile."""
    data = _load_operator()
    return data.get("neurocognitive", {})


def _read_stimmung_block() -> str:
    """Read current system Stimmung from /dev/shm and format for prompt injection."""
    stimmung_path = Path("/dev/shm/hapax-stimmung/state.json")
    try:
        import time

        raw = json.loads(stimmung_path.read_text(encoding="utf-8"))
        ts = raw.get("timestamp", 0)
        if ts > 0 and (time.monotonic() - ts) > 300:
            return ""
        stance = raw.get("overall_stance", "nominal")
        if stance == "nominal":
            return ""

        from agents._stimmung import SystemStimmung

        stimmung = SystemStimmung.model_validate(raw)
        return (
            "System self-state (adjust behavior accordingly — "
            "conserve resources when degraded/critical, "
            "reduce LLM calls when cost pressure is high):\n" + stimmung.format_for_prompt()
        )
    except Exception:
        return ""


from shared.apperception_shm import read_apperception_block as _read_apperception_block
from shared.temporal_shm import read_temporal_block as _read_temporal_block


def get_system_prompt_fragment(agent_name: str) -> str:
    """Build a system prompt fragment for a specific agent."""
    data = _load_operator()

    lines: list[str] = [SYSTEM_CONTEXT, ""]

    if not data:
        return "\n".join(lines)

    operator = data.get("operator", {})

    operator_name = operator.get("name", "Unknown")
    lines.append(f"Operator: {operator_name} — {operator.get('role', '')}")
    lines.append(operator.get("context", ""))

    axioms = data.get("axioms", {})
    try:
        from agents._axiom_registry import load_axioms as _load_axioms

        registry_axioms = _load_axioms()
        if registry_axioms:
            lines.append("")
            try:
                from agents._context_compression import to_toon

                axiom_data = {
                    "axioms": [
                        {"id": ax.id, "w": ax.weight, "rule": ax.text.strip()}
                        for ax in registry_axioms
                    ]
                }
                lines.append(
                    "System axioms (check_axiom_compliance tool available):\n" + to_toon(axiom_data)
                )
            except Exception:
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
        try:
            from agents._context_compression import to_toon
        except ImportError:
            to_toon = None  # type: ignore[assignment]
        lines.append(
            "Neurocognitive patterns (discovered through operator interview — "
            "accommodate these in all interactions):"
        )
        if to_toon is not None:
            lines.append(to_toon(neuro))
        else:
            for category, findings in neuro.items():
                cat_label = category.replace("_", " ").title()
                lines.append(f"  {cat_label}:")
                for finding in findings:
                    lines.append(f"    - {finding}")
    lines.append("")

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

    stimmung_block = _read_stimmung_block()
    if stimmung_block:
        lines.append(stimmung_block)
        lines.append("")

    temporal_block = _read_temporal_block()
    if temporal_block:
        lines.append(temporal_block)
        lines.append("")

    apperception_block = _read_apperception_block()
    if apperception_block:
        lines.append(apperception_block)
        lines.append("")

    return "\n".join(lines)
