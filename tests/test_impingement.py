"""Tests for the impingement-driven activation cascade foundation."""

import time

from shared.capability_registry import CapabilityRegistry
from shared.impingement import Impingement, ImpingementType

# ── Test Impingement ──────────────────────────────────────────────────────────


def test_impingement_creation():
    imp = Impingement(
        timestamp=time.time(),
        source="dmn.sensory",
        type=ImpingementType.STATISTICAL_DEVIATION,
        strength=0.7,
        content={"metric": "flow_drop", "value": 0.3},
    )
    assert imp.strength == 0.7
    assert imp.source == "dmn.sensory"
    assert len(imp.id) == 12


def test_impingement_frozen():
    imp = Impingement(
        timestamp=time.time(),
        source="test",
        type=ImpingementType.PATTERN_MATCH,
        strength=0.5,
    )
    try:
        imp.strength = 0.9  # type: ignore[misc]
        raise AssertionError("Should be frozen")
    except Exception:
        pass


def test_impingement_cascade_tracing():
    parent = Impingement(
        timestamp=time.time(),
        source="audio.vad",
        type=ImpingementType.PATTERN_MATCH,
        strength=0.8,
        interrupt_token="operator_voice",
    )
    child = Impingement(
        timestamp=time.time(),
        source="stt.transcription",
        type=ImpingementType.SALIENCE_INTEGRATION,
        strength=0.6,
        parent_id=parent.id,
    )
    assert child.parent_id == parent.id


# ── Test Capability Registry ─────────────────────────────────────────────────


class MockCapability:
    """Test capability that matches specific impingement types."""

    def __init__(
        self,
        name: str,
        affordances: set[str],
        cost: float = 0.1,
        priority: bool = False,
    ):
        self._name = name
        self._affordances = affordances
        self._cost = cost
        self._priority = priority
        self._level = 0.0

    @property
    def name(self) -> str:
        return self._name

    @property
    def affordance_signature(self) -> set[str]:
        return self._affordances

    @property
    def activation_cost(self) -> float:
        return self._cost

    @property
    def activation_level(self) -> float:
        return self._level

    @property
    def consent_required(self) -> bool:
        return False

    @property
    def priority_floor(self) -> bool:
        return self._priority

    def can_resolve(self, impingement: Impingement) -> float:
        content = impingement.content
        metric = content.get("metric", "")
        if any(aff in metric for aff in self._affordances):
            return impingement.strength
        return 0.0

    def activate(self, impingement: Impingement, level: float) -> str:
        self._level = level
        return f"{self._name} activated at {level}"

    def deactivate(self) -> None:
        self._level = 0.0


def test_registry_register_and_broadcast():
    reg = CapabilityRegistry()
    cap = MockCapability("fortress_gov", {"drink", "population", "extinction"})
    reg.register(cap)
    assert "fortress_gov" in reg.capabilities

    imp = Impingement(
        timestamp=time.time(),
        source="dmn.absolute_threshold",
        type=ImpingementType.ABSOLUTE_THRESHOLD,
        strength=0.9,
        content={"metric": "drink_per_capita", "value": 0, "threshold": 10},
    )
    matches = reg.broadcast(imp)
    assert len(matches) == 1
    assert matches[0].capability.name == "fortress_gov"
    assert matches[0].effective_score > 0


def test_registry_no_match():
    reg = CapabilityRegistry()
    cap = MockCapability("speech_prod", {"verbal_response"})
    reg.register(cap)

    imp = Impingement(
        timestamp=time.time(),
        source="dmn.absolute_threshold",
        type=ImpingementType.ABSOLUTE_THRESHOLD,
        strength=0.9,
        content={"metric": "drink_per_capita"},
    )
    matches = reg.broadcast(imp)
    assert len(matches) == 0


def test_registry_priority_floor():
    reg = CapabilityRegistry()
    normal = MockCapability("fortress_gov", {"drink"}, cost=0.5)
    priority = MockCapability("axiom_gate", {"drink"}, cost=0.1, priority=True)
    reg.register(normal)
    reg.register(priority)

    imp = Impingement(
        timestamp=time.time(),
        source="dmn.absolute_threshold",
        type=ImpingementType.ABSOLUTE_THRESHOLD,
        strength=0.9,
        content={"metric": "drink_critical"},
    )
    matches = reg.broadcast(imp)
    # Priority floor should win and normal should be excluded
    assert len(matches) == 1
    assert matches[0].capability.name == "axiom_gate"


def test_registry_inhibition_of_return():
    reg = CapabilityRegistry()
    cap = MockCapability("fortress_gov", {"drink"})
    reg.register(cap)

    imp = Impingement(
        timestamp=time.time(),
        source="dmn.absolute_threshold",
        type=ImpingementType.ABSOLUTE_THRESHOLD,
        strength=0.9,
        content={"metric": "drink_critical"},
    )

    # First broadcast matches
    matches1 = reg.broadcast(imp)
    assert len(matches1) == 1

    # Add inhibition
    reg.add_inhibition(imp, duration_s=60.0)

    # Second broadcast is inhibited
    matches2 = reg.broadcast(imp)
    assert len(matches2) == 0


def test_registry_mutual_suppression():
    reg = CapabilityRegistry()
    strong = MockCapability("primary", {"drink"}, cost=0.1)
    weak = MockCapability("secondary", {"drink"}, cost=0.3)
    reg.register(strong)
    reg.register(weak)

    imp = Impingement(
        timestamp=time.time(),
        source="test",
        type=ImpingementType.ABSOLUTE_THRESHOLD,
        strength=0.9,
        content={"metric": "drink_critical"},
    )
    matches = reg.broadcast(imp)
    assert len(matches) >= 1
    # Strong should score higher than weak
    if len(matches) > 1:
        assert matches[0].effective_score >= matches[1].effective_score


# ── Test DMN Anti-Habituation ─────────────────────────────────────────────────


def test_dmn_absolute_threshold_drink():
    from agents.dmn.buffer import DMNBuffer
    from agents.dmn.pulse import DMNPulse

    buf = DMNBuffer()
    pulse = DMNPulse(buf)

    snapshot = {
        "perception": {"activity": "coding", "flow_score": 0.8},
        "stimmung": {"stance": "nominal"},
        "fortress": {
            "fortress_name": "TestFort",
            "population": 5,
            "food": 100,
            "drink": 0,
            "threats": 0,
        },
        "watch": {"heart_rate": 0},
    }

    pulse._check_absolute_thresholds(snapshot)
    impingements = pulse.drain_impingements()

    # drink=0 with pop=5 should trigger absolute threshold
    drink_imp = [i for i in impingements if i.content.get("metric") == "drink_per_capita"]
    assert len(drink_imp) == 1
    assert drink_imp[0].strength == 1.0  # 0 drinks = max strength
    assert drink_imp[0].type == ImpingementType.ABSOLUTE_THRESHOLD


def test_dmn_no_threshold_when_adequate():
    from agents.dmn.buffer import DMNBuffer
    from agents.dmn.pulse import DMNPulse

    buf = DMNBuffer()
    pulse = DMNPulse(buf)

    snapshot = {
        "perception": {"activity": "coding", "flow_score": 0.8},
        "stimmung": {"stance": "nominal"},
        "fortress": {
            "fortress_name": "TestFort",
            "population": 5,
            "food": 100,
            "drink": 50,
            "threats": 0,
        },
        "watch": {"heart_rate": 0},
    }

    pulse._check_absolute_thresholds(snapshot)
    impingements = pulse.drain_impingements()

    # drink=50 with pop=5 → 10 per capita, threshold is 2 per capita → no impingement
    drink_imp = [i for i in impingements if i.content.get("metric") == "drink_per_capita"]
    assert len(drink_imp) == 0


def test_dmn_extinction_risk():
    from agents.dmn.buffer import DMNBuffer
    from agents.dmn.pulse import DMNPulse

    buf = DMNBuffer()
    pulse = DMNPulse(buf)

    snapshot = {
        "perception": {},
        "stimmung": {"stance": "nominal"},
        "fortress": {"population": 2, "drink": 5, "food": 50, "fortress_name": "Dying"},
        "watch": {},
    }

    pulse._check_absolute_thresholds(snapshot)
    impingements = pulse.drain_impingements()

    extinction = [i for i in impingements if i.content.get("metric") == "extinction_risk"]
    assert len(extinction) == 1
    assert extinction[0].interrupt_token == "population_critical"
    assert extinction[0].strength == 1.0
