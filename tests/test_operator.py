"""Tests for the operator profile integration layer."""
import pytest

from shared.operator import (
    get_axioms,
    get_constraints,
    get_patterns,
    get_goals,
    get_agent_context,
    get_operator,
    get_system_prompt_fragment,
    reload_operator,
)


def test_operator_loads():
    data = get_operator()
    assert data.get("version") == 1
    assert data["operator"]["name"] == "Ryan Kleeberger"


def test_constraints_all():
    rules = get_constraints()
    assert len(rules) > 20  # Across all categories


def test_constraints_by_category():
    python_rules = get_constraints("python")
    assert any("uv" in r for r in python_rules)
    assert any("type hints" in r.lower() for r in python_rules)


def test_constraints_music():
    rules = get_constraints("music")
    assert any("DAW" in r for r in rules)
    assert any("44.1kHz" in r for r in rules)


def test_patterns_all():
    patterns = get_patterns()
    assert len(patterns) > 15


def test_patterns_by_category():
    dev = get_patterns("development")
    assert any("pipeline" in p.lower() for p in dev)


def test_goals():
    goals = get_goals()
    assert len(goals) >= 3
    ids = [g["id"] for g in goals]
    assert "llm-first-environment" in ids
    assert "agent-coverage" in ids


def test_agent_context_research():
    ctx = get_agent_context("research")
    assert "inject" in ctx
    assert "domain_knowledge" in ctx
    assert "knowledge base" in ctx["domain_knowledge"].lower()


def test_agent_context_code_review():
    ctx = get_agent_context("code-review")
    assert "constraints.python" in ctx["inject"]


def test_agent_context_missing():
    ctx = get_agent_context("nonexistent-agent")
    assert ctx == {}


def test_axioms():
    axioms = get_axioms()
    assert "single_user" in axioms
    assert "self_improving" in axioms
    assert "operator_authority" in axioms
    assert "Ryan" in axioms["single_user"]


def test_system_prompt_fragment_includes_single_user_axiom():
    fragment = get_system_prompt_fragment("research")
    # Registry text uses "single user" (no hyphen); fall back to "single-user system"
    assert "single user" in fragment.lower()
    assert "Ryan Kleeberger" in fragment


def test_system_prompt_fragment_includes_executive_function_axiom():
    fragment = get_system_prompt_fragment("research")
    assert "executive function" in fragment.lower()
    # Registry provides richer text — check for key concepts present in either path
    assert "adhd" in fragment.lower() or "friction" in fragment.lower()


def test_system_prompt_fragment_research():
    """Research agent gets identity + axioms but NOT constraints/patterns."""
    fragment = get_system_prompt_fragment("research")
    assert "Ryan Kleeberger" in fragment
    # Constraints/patterns no longer injected — available via context tools
    assert "Rules:" not in fragment
    assert len(fragment) > 100


def test_system_prompt_fragment_code_review():
    """Code review agent gets identity but NOT injected constraints."""
    fragment = get_system_prompt_fragment("code-review")
    assert "Ryan Kleeberger" in fragment
    # uv/type hints are constraints — no longer injected
    assert "Rules:" not in fragment


def test_system_prompt_fragment_missing():
    """Unknown agent still gets system context and operator identity."""
    fragment = get_system_prompt_fragment("nonexistent")
    assert "executive function" in fragment.lower()
    assert "Ryan" in fragment


def test_system_prompt_fragment_no_constraints_for_unmapped_agent():
    """Agents WITHOUT agent_context_map entries get no constraints injected."""
    fragment = get_system_prompt_fragment("nonexistent-agent-xyz")
    assert "Relevant constraints:" not in fragment
    assert "Relevant behavioral patterns:" not in fragment


def test_research_agent_has_operator_context():
    from agents.research import agent
    prompt = agent._system_prompts[0]
    assert "executive function" in prompt.lower()
    assert "lookup_constraints" in prompt


def test_code_review_agent_has_operator_context():
    from agents.code_review import SYSTEM_PROMPT
    assert "executive function" in SYSTEM_PROMPT.lower()
    assert "lookup_constraints" in SYSTEM_PROMPT


def test_neurocognitive_profile_empty():
    from shared.operator import get_neurocognitive_profile
    result = get_neurocognitive_profile()
    assert isinstance(result, dict)


def test_system_prompt_fragment_no_neurocognitive_when_empty(monkeypatch):
    """Empty neurocognitive dict means no 'Neurocognitive patterns' in fragment."""
    import shared.operator as op_mod
    import copy
    original = op_mod._load_operator()
    patched = copy.deepcopy(original)
    patched["neurocognitive"] = {}
    monkeypatch.setattr(op_mod, "_operator_cache", patched)
    fragment = get_system_prompt_fragment("research")
    assert "Neurocognitive patterns" not in fragment


def test_system_prompt_fragment_includes_neurocognitive_when_populated(monkeypatch):
    """Populated neurocognitive data appears in system prompt fragment."""
    import shared.operator as op_mod
    import copy
    original = op_mod._load_operator()
    patched = copy.deepcopy(original)
    patched["neurocognitive"] = {
        "task_initiation": ["Body doubling effective", "Timers help start"],
        "energy_cycles": ["Morning focus peak"],
    }
    monkeypatch.setattr(op_mod, "_operator_cache", patched)
    fragment = get_system_prompt_fragment("research")
    assert "Neurocognitive patterns" in fragment
    assert "Body doubling effective" in fragment
    assert "Task Initiation" in fragment
    assert "Energy Cycles" in fragment
    # Restore cache
    monkeypatch.setattr(op_mod, "_operator_cache", None)


# ── Agent context map injection tests ────────────────────────────────────────

def test_system_prompt_includes_constraints_for_mapped_agent():
    """Agents with agent_context_map entries get their mapped constraints."""
    fragment = get_system_prompt_fragment("code-review")
    # code-review maps to: constraints.python, constraints.docker, constraints.git
    assert "Relevant constraints:" in fragment
    # Python constraints include "uv" references
    assert "uv" in fragment.lower()


def test_system_prompt_includes_patterns_for_mapped_agent():
    """Agents with agent_context_map entries get their mapped patterns."""
    fragment = get_system_prompt_fragment("research")
    # research maps to: patterns.communication, patterns.decision_making
    assert "Relevant behavioral patterns:" in fragment


def test_system_prompt_includes_domain_knowledge():
    """Agents with domain_knowledge in their context map get it injected."""
    fragment = get_system_prompt_fragment("code-review")
    assert "Domain context:" in fragment
    assert "Pydantic AI" in fragment


def test_system_prompt_no_context_map_for_unknown():
    """Unknown agents don't get constraints/patterns but still get base context."""
    fragment = get_system_prompt_fragment("nonexistent-agent")
    assert "Relevant constraints:" not in fragment
    assert "Relevant behavioral patterns:" not in fragment
    assert "Domain context:" not in fragment
    # But still gets base context
    assert "executive function" in fragment.lower()


def test_system_prompt_still_has_neurocognitive():
    """Neurocognitive patterns are still injected alongside context map data."""
    fragment = get_system_prompt_fragment("code-review")
    # Should have both neurocognitive AND constraints
    assert "Neurocognitive patterns" in fragment or "ADHD" in fragment.lower()
    assert "Relevant constraints:" in fragment


# ── Schema validation tests ─────────────────────────────────────────────────

def test_operator_schema_valid():
    from shared.operator import OperatorSchema
    data = {"version": 1, "operator": {"name": "Test"}}
    schema = OperatorSchema.model_validate(data)
    assert schema.version == 1


def test_operator_schema_extra_fields_allowed():
    from shared.operator import OperatorSchema
    data = {"version": 1, "operator": {}, "custom_field": "allowed"}
    schema = OperatorSchema.model_validate(data)
    assert schema.version == 1


def test_operator_schema_wrong_type_rejects():
    from pydantic import ValidationError
    from shared.operator import OperatorSchema
    with pytest.raises(ValidationError):
        OperatorSchema.model_validate({"operator": "not-a-dict"})


def test_load_operator_corrupt_json(tmp_path, monkeypatch):
    import shared.operator as op_mod
    monkeypatch.setattr(op_mod, "_operator_cache", None)
    corrupt = tmp_path / "operator.json"
    corrupt.write_text("{invalid json!")
    monkeypatch.setattr(op_mod, "PROFILES_DIR", tmp_path)
    result = op_mod._load_operator()
    assert result == {}
    monkeypatch.setattr(op_mod, "_operator_cache", None)


def test_load_operator_invalid_schema(tmp_path, monkeypatch):
    import shared.operator as op_mod
    import json
    monkeypatch.setattr(op_mod, "_operator_cache", None)
    bad = tmp_path / "operator.json"
    bad.write_text(json.dumps({"operator": "not-a-dict"}))
    monkeypatch.setattr(op_mod, "PROFILES_DIR", tmp_path)
    result = op_mod._load_operator()
    assert result == {}
    monkeypatch.setattr(op_mod, "_operator_cache", None)


def test_reload_operator_clears_cache(monkeypatch):
    """reload_operator() clears cache so next access re-reads from disk."""
    import shared.operator as op_mod
    # Load once to populate cache
    get_operator()
    assert op_mod._operator_cache is not None
    # Inject fake data into cache
    monkeypatch.setattr(op_mod, "_operator_cache", {"fake": True})
    assert get_operator() == {"fake": True}
    # Reload clears cache
    reload_operator()
    assert op_mod._operator_cache is None
    # Next access re-reads real data
    data = get_operator()
    assert data.get("version") == 1
    assert "fake" not in data
