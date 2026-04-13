"""Preset inputs schema + resolution tests — Phase 7 / parent I26+I27.

EffectGraph (the preset container) gains an optional ``inputs`` field.
Each ``PresetInput`` binds a SourceRegistry source pad to a named layer
slot. The compiler's ``resolve_preset_inputs`` helper dereferences the
pads against a live registry at preset-load time and raises
``PresetLoadError`` on any unknown pad — no silent fallthrough.
"""

from __future__ import annotations

import pytest

from agents.effect_graph.compiler import PresetLoadError, resolve_preset_inputs
from agents.effect_graph.types import EffectGraph, NodeInstance, PresetInput
from agents.studio_compositor.source_registry import SourceRegistry


def _minimal_graph(name: str = "t", inputs: list[PresetInput] | None = None) -> EffectGraph:
    return EffectGraph(
        name=name,
        nodes={"n": NodeInstance(type="noise")},
        edges=[],
        inputs=inputs,
    )


class _StubBackend:
    def get_current_surface(self) -> None:  # type: ignore[override]
        return None


# ── PresetInput schema ──────────────────────────────────────────────


def test_preset_input_accepts_pad_and_layer() -> None:
    entry = PresetInput(pad="reverie", **{"as": "layer0"})
    assert entry.pad == "reverie"
    assert entry.as_ == "layer0"


def test_preset_input_accepts_snake_case_attribute() -> None:
    entry = PresetInput(pad="reverie", as_="layer0")
    assert entry.as_ == "layer0"


def test_preset_input_rejects_empty_pad() -> None:
    with pytest.raises(ValueError):
        PresetInput(pad="", **{"as": "layer0"})


def test_preset_input_rejects_empty_as() -> None:
    with pytest.raises(ValueError):
        PresetInput(pad="reverie", **{"as": ""})


def test_preset_input_rejects_extra_fields() -> None:
    with pytest.raises(ValueError):
        PresetInput(pad="reverie", **{"as": "layer0", "nope": "x"})


def test_effect_graph_inputs_field_is_optional() -> None:
    graph = _minimal_graph()
    assert graph.inputs is None


def test_effect_graph_accepts_inputs_list() -> None:
    graph = _minimal_graph(
        inputs=[
            PresetInput(pad="reverie", **{"as": "layer0"}),
            PresetInput(pad="cam-vinyl", **{"as": "layer1"}),
        ],
    )
    assert graph.inputs is not None
    assert len(graph.inputs) == 2
    assert graph.inputs[0].pad == "reverie"
    assert graph.inputs[1].as_ == "layer1"


# ── resolve_preset_inputs ────────────────────────────────────────────


def test_resolve_returns_empty_dict_when_inputs_absent() -> None:
    registry = SourceRegistry()
    registry.register("reverie", _StubBackend())
    graph = _minimal_graph()
    assert resolve_preset_inputs(graph, registry) == {}


def test_resolve_returns_empty_dict_when_inputs_empty() -> None:
    registry = SourceRegistry()
    registry.register("reverie", _StubBackend())
    graph = _minimal_graph(inputs=[])
    assert resolve_preset_inputs(graph, registry) == {}


def test_resolve_maps_pads_to_backend_handles() -> None:
    registry = SourceRegistry()
    reverie_backend = _StubBackend()
    cam_backend = _StubBackend()
    registry.register("reverie", reverie_backend)
    registry.register("cam-vinyl", cam_backend)
    graph = _minimal_graph(
        inputs=[
            PresetInput(pad="reverie", **{"as": "layer0"}),
            PresetInput(pad="cam-vinyl", **{"as": "layer1"}),
        ],
    )
    resolved = resolve_preset_inputs(graph, registry)
    assert set(resolved.keys()) == {"layer0", "layer1"}
    assert resolved["layer0"] is reverie_backend
    assert resolved["layer1"] is cam_backend


def test_resolve_fails_loudly_on_unknown_pad() -> None:
    registry = SourceRegistry()
    registry.register("reverie", _StubBackend())
    graph = _minimal_graph(
        name="bad-preset",
        inputs=[PresetInput(pad="nonexistent", **{"as": "layer0"})],
    )
    with pytest.raises(PresetLoadError) as excinfo:
        resolve_preset_inputs(graph, registry)
    msg = str(excinfo.value)
    assert "bad-preset" in msg
    assert "nonexistent" in msg
    assert "reverie" in msg  # known pad list is included for debugging


def test_resolve_fails_loudly_on_second_unknown_after_known() -> None:
    """One known pad early in the list doesn't absolve a later unknown."""
    registry = SourceRegistry()
    registry.register("reverie", _StubBackend())
    graph = _minimal_graph(
        name="half-bad",
        inputs=[
            PresetInput(pad="reverie", **{"as": "layer0"}),
            PresetInput(pad="ghost", **{"as": "layer1"}),
        ],
    )
    with pytest.raises(PresetLoadError) as excinfo:
        resolve_preset_inputs(graph, registry)
    assert "ghost" in str(excinfo.value)
