"""Tests for effect graph type models."""

import pytest
from pydantic import ValidationError

from agents.effect_graph.types import (
    EdgeDef,
    EffectGraph,
    GraphPatch,
    LayerPalette,
    ModulationBinding,
    NodeInstance,
    ParamDef,
    PortType,
    ShaderDef,
)


def test_param_def_float():
    p = ParamDef(type="float", default=0.5, min=0.0, max=1.0, description="opacity")
    assert p.type == "float"
    assert p.default == 0.5


def test_param_def_enum():
    p = ParamDef(type="enum", default="lighter", enum_values=["lighter", "multiply"])
    assert "lighter" in p.enum_values


def test_param_def_vec2():
    p = ParamDef(type="vec2", default=[0.5, 0.5])
    assert p.default == [0.5, 0.5]


def test_shader_def():
    s = ShaderDef(
        node_type="colorgrade",
        glsl_fragment="colorgrade.frag",
        inputs={"in": PortType.FRAME},
        outputs={"out": PortType.FRAME},
        params={"saturation": ParamDef(type="float", default=1.0)},
    )
    assert s.node_type == "colorgrade"
    assert not s.temporal


def test_shader_def_temporal():
    s = ShaderDef(
        node_type="trail",
        glsl_fragment="trail.frag",
        inputs={"in": PortType.FRAME},
        outputs={"out": PortType.FRAME},
        params={},
        temporal=True,
        temporal_buffers=1,
    )
    assert s.temporal


def test_node_instance():
    n = NodeInstance(type="colorgrade", params={"saturation": 0.5})
    assert n.params["saturation"] == 0.5


def test_edge_def_simple():
    e = EdgeDef.from_list(["color", "trail"])
    assert e.source_node == "color"
    assert e.target_node == "trail"
    assert e.target_port == "in"


def test_edge_def_with_ports():
    e = EdgeDef.from_list(["@live", "blend:a"])
    assert e.target_node == "blend"
    assert e.target_port == "a"


def test_edge_def_layer_source():
    e = EdgeDef.from_list(["@smooth", "color"])
    assert e.is_layer_source is True


def test_edge_def_not_layer():
    e = EdgeDef.from_list(["color", "trail"])
    assert e.is_layer_source is False


def test_edge_def_bad():
    with pytest.raises(ValueError):
        EdgeDef.from_list(["only_one"])


def test_effect_graph():
    g = EffectGraph(
        name="t",
        nodes={"c": NodeInstance(type="colorgrade"), "o": NodeInstance(type="output")},
        edges=[["@live", "c"], ["c", "o"]],
    )
    assert len(g.parsed_edges) == 2


def test_effect_graph_modulations():
    g = EffectGraph(
        name="t",
        nodes={"c": NodeInstance(type="colorgrade"), "o": NodeInstance(type="output")},
        edges=[["@live", "c"], ["c", "o"]],
        modulations=[ModulationBinding(node="c", param="saturation", source="audio_rms")],
    )
    assert len(g.modulations) == 1


def test_graph_patch():
    p = GraphPatch(
        add_nodes={"bloom": NodeInstance(type="bloom")},
        add_edges=[["c", "bloom"]],
        remove_edges=[["c", "o"]],
    )
    assert "bloom" in p.add_nodes


def test_layer_palette_defaults():
    lp = LayerPalette()
    assert lp.saturation == 1.0


def test_layer_palette_custom():
    lp = LayerPalette(saturation=0.4, hue_rotate=-10)
    assert lp.hue_rotate == -10


def test_layer_palette_validation():
    with pytest.raises(ValidationError):
        LayerPalette(saturation=5.0)


def test_modulation_smoothing_validation():
    with pytest.raises(ValidationError):
        ModulationBinding(node="x", param="y", source="z", smoothing=1.5)
