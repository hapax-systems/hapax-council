"""Tests for Phase R3 — perception impingement emission + shader capability."""

import time
from unittest.mock import MagicMock

from shared.impingement import Impingement, ImpingementType


def test_shader_capability_creation():
    from agents.effect_graph.capability import SHADER_DESCRIPTION, ShaderGraphCapability

    cap = ShaderGraphCapability()
    assert cap.name == "shader_graph"
    assert cap.activation_cost == 0.2
    assert not cap.has_pending()
    assert "visual" in SHADER_DESCRIPTION.lower()
    assert "GPU" in SHADER_DESCRIPTION


def test_shader_capability_activate_queues():
    from agents.effect_graph.capability import ShaderGraphCapability

    cap = ShaderGraphCapability()
    imp = Impingement(
        timestamp=time.time(),
        source="dmn.absolute_threshold",
        type=ImpingementType.ABSOLUTE_THRESHOLD,
        strength=0.8,
        content={"metric": "operator_stress", "value": 0.9},
    )
    cap.activate(imp, 0.8)
    assert cap.has_pending()
    consumed = cap.consume_pending()
    assert consumed is not None
    assert consumed.source == "dmn.absolute_threshold"
    assert not cap.has_pending()


def test_shader_capability_record():
    from agents.effect_graph.capability import SHADER_DESCRIPTION
    from shared.affordance import CapabilityRecord, OperationalProperties

    rec = CapabilityRecord(
        name="shader_graph",
        description=SHADER_DESCRIPTION,
        daemon="studio_compositor",
        operational=OperationalProperties(requires_gpu=True),
    )
    assert rec.operational.requires_gpu
    assert rec.daemon == "studio_compositor"


def _make_engine():
    """Create a PerceptionEngine with mock dependencies."""
    from agents.hapax_voice.perception import PerceptionEngine

    presence = MagicMock()
    presence.latest_vad_confidence = 0.0
    presence.face_detected = False
    presence.face_count = 0
    presence.operator_visible = False
    presence.guest_count = 0
    presence.score = "likely_absent"
    workspace_monitor = MagicMock()
    return PerceptionEngine(presence, workspace_monitor)


def test_perception_drain_impingements():
    """PerceptionEngine.drain_impingements() returns and clears pending."""
    engine = _make_engine()
    imp = Impingement(
        timestamp=time.time(),
        source="perception.flow_score",
        type=ImpingementType.STATISTICAL_DEVIATION,
        strength=0.5,
        content={"metric": "flow_score", "value": 0.8},
    )
    engine._pending_impingements.append(imp)
    drained = engine.drain_impingements()
    assert len(drained) == 1
    assert drained[0].source == "perception.flow_score"
    assert engine.drain_impingements() == []


def test_behavior_change_emits_impingement():
    """Significant behavior changes produce impingements."""
    from agents.hapax_voice.primitives import Behavior

    engine = _make_engine()
    behaviors: dict[str, Behavior] = {"flow_score": Behavior(0.0)}
    engine._prev_behavior_values["flow_score"] = 0.0

    # Small change — no impingement
    behaviors["flow_score"].update(0.05, time.monotonic())
    engine._check_behavior_changes(behaviors)
    assert len(engine._pending_impingements) == 0

    # Large change — impingement emitted
    behaviors["flow_score"].update(0.8, time.monotonic())
    engine._check_behavior_changes(behaviors)
    assert len(engine._pending_impingements) == 1
    assert engine._pending_impingements[0].content["metric"] == "flow_score"
    assert engine._pending_impingements[0].content["delta"] > 0.15


def test_behavior_change_caps_strength():
    """Impingement strength is capped at 1.0."""
    from agents.hapax_voice.primitives import Behavior

    engine = _make_engine()
    behaviors: dict[str, Behavior] = {"big_jump": Behavior(0.0)}
    engine._prev_behavior_values["big_jump"] = 0.0

    behaviors["big_jump"].update(5.0, time.monotonic())
    engine._check_behavior_changes(behaviors)
    assert engine._pending_impingements[0].strength == 1.0


def test_non_numeric_behaviors_ignored():
    """Non-numeric behavior values don't produce impingements."""
    from agents.hapax_voice.primitives import Behavior

    engine = _make_engine()
    behaviors: dict[str, Behavior] = {"window_class": Behavior("firefox")}
    engine._check_behavior_changes(behaviors)
    assert len(engine._pending_impingements) == 0


def test_shader_pipeline_interrupt_bypass():
    """ShaderGraph can be registered for interrupt tokens in the pipeline."""
    from shared.affordance_pipeline import AffordancePipeline

    pipeline = AffordancePipeline()
    pipeline.register_interrupt("stimmung_critical", "shader_graph", "compositor")

    imp = Impingement(
        timestamp=time.time(),
        source="dmn",
        type=ImpingementType.ABSOLUTE_THRESHOLD,
        strength=0.9,
        content={"metric": "stimmung_critical"},
        interrupt_token="stimmung_critical",
    )
    results = pipeline.select(imp)
    assert len(results) == 1
    assert results[0].capability_name == "shader_graph"
