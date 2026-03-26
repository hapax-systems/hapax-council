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
    p = ParamDef(
        type="enum",
        default="lighter",
        enum_values=["lighter", "multiply", "difference"],
    )
    assert p.type == "enum"
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
        params={"saturation": ParamDef(type="float", default=1.0, min=0.0, max=2.0)},
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
    assert s.temporal_buffers == 1


def test_node_instance():
    n = NodeInstance(type="colorgrade", params={"saturation": 0.5})
    assert n.type == "colorgrade"
    assert n.params["saturation"] == 0.5


def test_edge_def_simple():
    e = EdgeDef.from_list(["color", "trail"])
    assert e.source_node == "color"
    assert e.source_port == "out"
    assert e.target_node == "trail"
    assert e.target_port == "in"


def test_edge_def_with_ports():
    e = EdgeDef.from_list(["@live", "blend:a"])
    assert e.source_node == "@live"
    assert e.target_node == "blend"
    assert e.target_port == "a"


def test_edge_def_layer_source():
    e = EdgeDef.from_list(["@smooth", "color"])
    assert e.source_node == "@smooth"
    assert e.is_layer_source is True


def test_edge_def_not_layer_source():
    e = EdgeDef.from_list(["color", "trail"])
    assert e.is_layer_source is False


def test_edge_def_bad_length():
    with pytest.raises(ValueError, match="Edge must be"):
        EdgeDef.from_list(["only_one"])


def test_effect_graph():
    g = EffectGraph(
        name="test",
        nodes={
            "color": NodeInstance(type="colorgrade"),
            "out": NodeInstance(type="output"),
        },
        edges=[["@live", "color"], ["color", "out"]],
    )
    assert len(g.nodes) == 2
    assert len(g.parsed_edges) == 2
    assert g.parsed_edges[0].source_node == "@live"


def test_effect_graph_with_modulations():
    g = EffectGraph(
        name="test",
        nodes={
            "color": NodeInstance(type="colorgrade"),
            "out": NodeInstance(type="output"),
        },
        edges=[["@live", "color"], ["color", "out"]],
        modulations=[ModulationBinding(node="color", param="saturation", source="audio_rms")],
    )
    assert len(g.modulations) == 1
    assert g.modulations[0].source == "audio_rms"


def test_graph_patch():
    p = GraphPatch(
        add_nodes={"bloom": NodeInstance(type="bloom", params={"threshold": 0.5})},
        add_edges=[["color", "bloom"], ["bloom", "out"]],
        remove_edges=[["color", "out"]],
    )
    assert "bloom" in p.add_nodes
    assert len(p.add_edges) == 2


def test_layer_palette_defaults():
    lp = LayerPalette()
    assert lp.saturation == 1.0
    assert lp.hue_rotate == 0.0


def test_layer_palette_custom():
    lp = LayerPalette(saturation=0.4, sepia=0.55, hue_rotate=-10)
    assert lp.saturation == 0.4
    assert lp.hue_rotate == -10


def test_layer_palette_range_validation():
    with pytest.raises(ValidationError):
        LayerPalette(saturation=5.0)  # max 2.0
    with pytest.raises(ValidationError):
        LayerPalette(sepia=-1.0)  # min 0.0


def test_modulation_binding_smoothing_validation():
    with pytest.raises(ValidationError):
        ModulationBinding(node="x", param="y", source="z", smoothing=1.5)
