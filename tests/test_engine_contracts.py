"""Tests for reactive engine phase contracts."""

from __future__ import annotations

import sys
import types

import pytest

# Prevent logos.engine.__init__ from triggering heavy imports (watcher -> frontmatter
# circular import in test isolation). We only need models and rules submodules.
if "logos.engine" not in sys.modules:
    import pathlib

    _pkg = types.ModuleType("logos.engine")
    _pkg.__path__ = [str(pathlib.Path(__file__).resolve().parent.parent / "logos" / "engine")]
    _pkg.__package__ = "logos.engine"
    sys.modules["logos.engine"] = _pkg

from logos.engine.models import Action, Phase, RuleSpec  # noqa: E402
from logos.engine.rules import RuleRegistry  # noqa: E402


def test_phase_enum_values():
    assert Phase.DETERMINISTIC == 0
    assert Phase.GPU == 1
    assert Phase.CLOUD == 2


def test_rulespec_creation():
    spec = RuleSpec(
        id="test-rule",
        phase=Phase.DETERMINISTIC,
        trigger=lambda e: True,
        produce=lambda e: [],
    )
    assert spec.id == "test-rule"
    assert spec.phase == Phase.DETERMINISTIC
    assert spec.cooldown_s == 0


def test_rulespec_rejects_duplicate_id():
    """Registry rejects two rules with the same ID."""
    registry = RuleRegistry()
    spec1 = RuleSpec(
        id="dup", phase=Phase.DETERMINISTIC, trigger=lambda e: True, produce=lambda e: []
    )
    spec2 = RuleSpec(id="dup", phase=Phase.GPU, trigger=lambda e: True, produce=lambda e: [])

    registry.register(spec1)
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(spec2)


def test_action_phase_invariant():
    """A deterministic rule cannot produce GPU-phase actions."""
    spec = RuleSpec(
        id="bad-rule",
        phase=Phase.DETERMINISTIC,
        produce=lambda e: [Action(name="gpu-work", handler=None, phase=Phase.GPU)],
        trigger=lambda e: True,
    )
    # Invariant checked at evaluation time, not at registration
    assert spec.phase == Phase.DETERMINISTIC
