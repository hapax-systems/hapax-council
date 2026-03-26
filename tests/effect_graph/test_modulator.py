"""Tests for uniform modulation system."""

import pytest

from agents.effect_graph.modulator import UniformModulator
from agents.effect_graph.types import ModulationBinding


def test_register_binding():
    mod = UniformModulator()
    mod.add_binding(ModulationBinding(node="bloom", param="alpha", source="audio_rms"))
    assert len(mod.bindings) == 1


def test_tick_with_signal():
    mod = UniformModulator()
    mod.add_binding(
        ModulationBinding(
            node="bloom", param="alpha", source="audio_rms", scale=1.0, offset=0.0, smoothing=0.0
        )
    )
    updates = mod.tick({"audio_rms": 0.8})
    assert updates[("bloom", "alpha")] == pytest.approx(0.8)


def test_scale_and_offset():
    mod = UniformModulator()
    mod.add_binding(
        ModulationBinding(
            node="c", param="sat", source="arousal", scale=0.5, offset=0.7, smoothing=0.0
        )
    )
    updates = mod.tick({"arousal": 0.6})
    assert updates[("c", "sat")] == pytest.approx(1.0)


def test_smoothing():
    mod = UniformModulator()
    mod.add_binding(
        ModulationBinding(node="b", param="a", source="rms", scale=1.0, offset=0.0, smoothing=0.5)
    )
    u1 = mod.tick({"rms": 1.0})
    u2 = mod.tick({"rms": 0.0})
    assert u2[("b", "a")] < u1[("b", "a")]
    assert u2[("b", "a")] > 0.0


def test_missing_signal():
    mod = UniformModulator()
    mod.add_binding(ModulationBinding(node="b", param="a", source="nope"))
    updates = mod.tick({"rms": 0.5})
    assert ("b", "a") not in updates


def test_remove_binding():
    mod = UniformModulator()
    mod.add_binding(ModulationBinding(node="b", param="a", source="rms"))
    mod.remove_binding("b", "a")
    assert len(mod.bindings) == 0


def test_replace_all():
    mod = UniformModulator()
    mod.add_binding(ModulationBinding(node="b", param="a", source="rms"))
    mod.replace_all([ModulationBinding(node="c", param="s", source="beat")])
    assert len(mod.bindings) == 1
    assert mod.bindings[0].node == "c"
