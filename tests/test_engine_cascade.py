"""Tests for reactive engine ↔ impingement cascade integration."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from logos.engine.converter import convert
from logos.engine.models import Action, ChangeEvent
from logos.engine.rule_capability import RuleCapability
from logos.engine.rules import Rule
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
    assert imp.strength == 0.70


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
    assert imp.strength == 0.45
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
    from shared.impingement import Impingement

    rule = _make_rule()
    cap = RuleCapability(rule)
    imp = Impingement(
        timestamp=time.time(),
        source="dmn.evaluative",
        type=ImpingementType.SALIENCE_INTEGRATION,
        strength=0.8,
        content={"metric": "operator_stress"},
    )
    assert cap.can_resolve(imp) == 0.0
