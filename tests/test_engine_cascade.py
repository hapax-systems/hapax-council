"""Tests for reactive engine ↔ impingement cascade integration."""

from __future__ import annotations

import importlib
import sys
import time
from datetime import datetime
from pathlib import Path

# The logos.engine __init__.py triggers a circular import via
# shared.frontmatter ↔ shared.governance. Work around by importing
# submodules directly without triggering __init__.
# This is a pre-existing bug, not caused by the cascade work.


def _import_without_init(module_name: str):
    """Import a submodule without triggering the parent __init__."""
    parts = module_name.rsplit(".", 1)
    if len(parts) == 2:
        parent, child = parts
        if parent not in sys.modules:
            # Create a dummy parent module to avoid __init__
            import types

            sys.modules[parent] = types.ModuleType(parent)
            sys.modules[parent].__path__ = [
                str(Path(__file__).parent.parent / parent.replace(".", "/"))
            ]
    return importlib.import_module(module_name)


# Import the modules we need without circular import
_models = _import_without_init("logos.engine.models")
_rules = _import_without_init("logos.engine.rules")
_converter = _import_without_init("logos.engine.converter")
_rule_cap = _import_without_init("logos.engine.rule_capability")

ChangeEvent = _models.ChangeEvent
Action = _models.Action
Rule = _rules.Rule
convert = _converter.convert
RuleCapability = _rule_cap.RuleCapability

from shared.impingement import ImpingementType

# ── Converter Tests ──────────────────────────────────────────────────────────


def test_convert_basic_event():
    event = ChangeEvent(
        path=Path("/data/profiles/operator-profile.md"),
        event_type="modified",
        doc_type="profile",
        frontmatter=None,
        timestamp=datetime.now(),
    )
    imp = convert(event)
    assert imp.source.startswith("engine.")
    assert imp.content["path"] == str(event.path)
    assert imp.content["event_type"] == "modified"
    assert imp.content["doc_type"] == "profile"
    assert imp.strength == 0.70  # profile strength from map


def test_convert_axiom_event_gets_interrupt_token():
    event = ChangeEvent(
        path=Path("/data/axioms/registry.yaml"),
        event_type="modified",
        doc_type="axiom",
        frontmatter=None,
        timestamp=datetime.now(),
    )
    imp = convert(event)
    assert imp.interrupt_token == "axiom_config_changed"
    assert imp.type == ImpingementType.PATTERN_MATCH
    assert imp.strength == 0.95


def test_convert_health_event():
    event = ChangeEvent(
        path=Path("/data/profiles/health-history.jsonl"),
        event_type="modified",
        doc_type="health",
        frontmatter=None,
        timestamp=datetime.now(),
    )
    imp = convert(event)
    assert imp.interrupt_token == "health_status_changed"
    assert imp.strength == 0.85


def test_convert_unknown_event_gets_default_strength():
    event = ChangeEvent(
        path=Path("/data/some/random/file.txt"),
        event_type="created",
        doc_type=None,
        frontmatter=None,
        timestamp=datetime.now(),
    )
    imp = convert(event)
    assert imp.strength == 0.45  # default
    assert imp.interrupt_token is None
    assert imp.type == ImpingementType.STATISTICAL_DEVIATION


def test_convert_preserves_context():
    event = ChangeEvent(
        path=Path("/data/profiles/briefing.md"),
        event_type="modified",
        doc_type="briefing",
        frontmatter=None,
        timestamp=datetime.now(),
    )
    imp = convert(event)
    assert "stimmung_stance" in imp.context


# ── RuleCapability Tests ─────────────────────────────────────────────────────


def _make_rule(name: str = "test_rule", phase: int = 0) -> Rule:
    return Rule(
        name=name,
        description="Test rule",
        trigger_filter=lambda e: e.path.name == "test.md",
        produce=lambda e: [
            Action(
                name="test_action",
                handler=lambda: "done",
                args={},
                phase=phase,
            )
        ],
        phase=phase,
    )


def test_rule_capability_name():
    rule = _make_rule("my_rule")
    cap = RuleCapability(rule)
    assert cap.name == "my_rule"


def test_rule_capability_cost_from_phase():
    assert RuleCapability(_make_rule(phase=0)).activation_cost == 0.0
    assert RuleCapability(_make_rule(phase=1)).activation_cost == 0.5
    assert RuleCapability(_make_rule(phase=2)).activation_cost == 1.0


def test_rule_capability_can_resolve_matching():
    rule = _make_rule()
    cap = RuleCapability(rule)

    event = ChangeEvent(
        path=Path("/data/test.md"),
        event_type="modified",
        doc_type=None,
        frontmatter=None,
        timestamp=datetime.now(),
    )
    imp = convert(event)
    assert cap.can_resolve(imp) == 1.0


def test_rule_capability_can_resolve_non_matching():
    rule = _make_rule()
    cap = RuleCapability(rule)

    event = ChangeEvent(
        path=Path("/data/other.md"),
        event_type="modified",
        doc_type=None,
        frontmatter=None,
        timestamp=datetime.now(),
    )
    imp = convert(event)
    assert cap.can_resolve(imp) == 0.0


def test_rule_capability_activate_produces_actions():
    rule = _make_rule()
    cap = RuleCapability(rule)

    event = ChangeEvent(
        path=Path("/data/test.md"),
        event_type="modified",
        doc_type=None,
        frontmatter=None,
        timestamp=datetime.now(),
    )
    imp = convert(event)
    actions = cap.activate(imp, 0.8)
    assert len(actions) == 1
    assert actions[0].name == "test_action"


def test_rule_capability_rejects_non_engine_impingement():
    """Impingements from DMN/perception (no path) should return 0.0."""
    from shared.impingement import Impingement

    rule = _make_rule()
    cap = RuleCapability(rule)

    imp = Impingement(
        timestamp=time.time(),
        source="dmn.evaluative",
        type=ImpingementType.SALIENCE_INTEGRATION,
        strength=0.8,
        content={"metric": "operator_stress"},  # no "path" key
    )
    assert cap.can_resolve(imp) == 0.0
