# Effect Node Graph — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed GStreamer shader chain and frontend canvas engine with a composable GPU node graph runtime — enough to run Ghost, Trails, and Clean presets end-to-end with three persistent layers, graph mutation, and the new API.

**Architecture:** The existing `_add_effects_branch()` (fixed 10-shader chain) is replaced by a graph compiler that builds GStreamer element chains from JSON graph definitions. Shader nodes are self-describing (`.frag` + `.json` manifest). Three persistent source layers (`@live`, `@smooth`, `@hls`) feed into the graph. The `_fx_tick_callback()` is replaced by a declarative `UniformModulator`. Frontend `CompositeCanvas.tsx` is deleted; the frontend becomes HLS player + snapshot display.

**Tech Stack:** Python 3.12, GStreamer (glshader, glupload, gldownload), GLSL ES 1.0, Pydantic models, FastAPI, React/TypeScript (frontend simplification)

**Spec:** `docs/superpowers/specs/2026-03-25-effect-node-graph-design.md`

**Phase scope:** Core infrastructure + 9 foundational nodes (colorgrade, trail, blend, stutter, bloom, scanlines, vignette, noise_overlay, output) + 3 migrated presets (Ghost, Trails, Clean). Later phases add remaining ~30 nodes and all presets.

---

## File Structure

### New files (backend)

| File | Responsibility |
|------|---------------|
| `agents/effect_graph/types.py` | Pydantic models: `ShaderDef`, `ParamDef`, `NodeInstance`, `EdgeDef`, `EffectGraph`, `GraphPatch`, `ModulationBinding` |
| `agents/effect_graph/registry.py` | `ShaderRegistry`: scans `shaders/nodes/` for `.json` manifests, loads `.frag` source, exposes node type schemas |
| `agents/effect_graph/compiler.py` | `GraphCompiler`: topological sort, validation, GStreamer element chain construction from graph JSON |
| `agents/effect_graph/runtime.py` | `GraphRuntime`: manages live graph, handles three mutation levels (param patch, topology diff, full replace), crossfade engine |
| `agents/effect_graph/modulator.py` | `UniformModulator`: declarative signal→uniform bindings, per-tick update loop |
| `agents/effect_graph/layers.py` | `LayerManager`: three persistent layers (@live, @smooth, @hls), per-layer palettes, smooth FBO ring |
| `agents/effect_graph/__init__.py` | Package init |
| `agents/shaders/nodes/colorgrade.frag` | Colorgrade shader (migrated from existing `color_grade.frag`) |
| `agents/shaders/nodes/colorgrade.json` | Colorgrade manifest |
| `agents/shaders/nodes/trail.frag` | Trail accumulator shader (new — replaces frontend ping-pong) |
| `agents/shaders/nodes/trail.json` | Trail manifest |
| `agents/shaders/nodes/blend.frag` | Blend compositor shader (new) |
| `agents/shaders/nodes/blend.json` | Blend manifest |
| `agents/shaders/nodes/stutter.json` | Stutter manifest (uses Python element, not GLSL) |
| `agents/shaders/nodes/bloom.frag` | Bloom shader (new — bright-pass + blur + add) |
| `agents/shaders/nodes/bloom.json` | Bloom manifest |
| `agents/shaders/nodes/scanlines.frag` | Scanlines shader (extracted from post_process.frag) |
| `agents/shaders/nodes/scanlines.json` | Scanlines manifest |
| `agents/shaders/nodes/vignette.frag` | Vignette shader (extracted from post_process.frag) |
| `agents/shaders/nodes/vignette.json` | Vignette manifest |
| `agents/shaders/nodes/noise_overlay.frag` | Grain overlay shader (new) |
| `agents/shaders/nodes/noise_overlay.json` | Noise overlay manifest |
| `agents/shaders/nodes/output.json` | Output sink manifest (no shader — identity passthrough) |
| `agents/shaders/nodes/palette.frag` | Layer palette shader (per-layer colorgrade) |
| `agents/shaders/nodes/palette.json` | Palette manifest |
| `presets/ghost.json` | Ghost preset graph |
| `presets/trails.json` | Trails preset graph |
| `presets/clean.json` | Clean preset graph |
| `tests/effect_graph/test_types.py` | Type model tests |
| `tests/effect_graph/test_registry.py` | Registry tests |
| `tests/effect_graph/test_compiler.py` | Compiler tests (validation, topo sort, FBO allocation) |
| `tests/effect_graph/test_runtime.py` | Runtime mutation tests |
| `tests/effect_graph/test_modulator.py` | Modulator tests |
| `tests/effect_graph/test_layers.py` | Layer manager tests |

### Modified files

| File | Changes |
|------|---------|
| `agents/studio_compositor.py` | Replace `_add_effects_branch()` with `GraphRuntime` integration; replace `_fx_tick_callback()` with `UniformModulator`; add smooth layer FBO ring; keep overlay/HLS/snapshot/recording branches intact |
| `agents/studio_effects.py` | Deprecate — keep for reference until all presets are migrated, add `to_graph_json()` converter |
| `logos/api/routes/studio.py` | Add graph CRUD routes, layer control routes, modulation routes, preset routes, node registry routes |
| `hapax-logos/src/components/terrain/ground/CameraHero.tsx` | Remove CompositeCanvas integration, simplify to HLS player + snapshot img |
| `hapax-logos/src/components/terrain/ground/StudioDetailPane.tsx` | Rewire preset selector to new API, rewire effect toggles to graph topology mutations |
| `hapax-logos/src/contexts/GroundStudioContext.tsx` | Remove compositeMode/smoothMode/presetIdx/liveFilterIdx/smoothFilterIdx, replace with graphState from API |

### Deleted files

| File | Reason |
|------|--------|
| `hapax-logos/src/components/studio/CompositeCanvas.tsx` | Entire canvas rendering engine replaced by backend |
| `hapax-logos/src/components/studio/compositePresets.ts` | Replaced by JSON preset files |
| `hapax-logos/src/components/studio/compositeFilters.ts` | Replaced by per-layer palette API |
| `hapax-logos/src/hooks/useImagePool.ts` | No longer needed (no ring buffer) |

---

## Task 1: Effect Graph Type Models

**Files:**
- Create: `agents/effect_graph/__init__.py`
- Create: `agents/effect_graph/types.py`
- Create: `tests/effect_graph/__init__.py`
- Create: `tests/effect_graph/test_types.py`

- [ ] **Step 1: Write failing tests for core types**

```python
# tests/effect_graph/__init__.py
# empty

# tests/effect_graph/test_types.py
"""Tests for effect graph type models."""

import pytest
from pydantic import ValidationError


def test_param_def_float():
    from agents.effect_graph.types import ParamDef

    p = ParamDef(type="float", default=0.5, min=0.0, max=1.0, description="opacity")
    assert p.type == "float"
    assert p.default == 0.5
    assert p.min == 0.0
    assert p.max == 1.0


def test_param_def_enum():
    from agents.effect_graph.types import ParamDef

    p = ParamDef(
        type="enum",
        default="lighter",
        enum_values=["lighter", "multiply", "difference", "screen", "overlay"],
        description="blend mode",
    )
    assert p.type == "enum"
    assert "lighter" in p.enum_values


def test_param_def_vec2():
    from agents.effect_graph.types import ParamDef

    p = ParamDef(type="vec2", default=[0.5, 0.5], description="center point")
    assert p.default == [0.5, 0.5]


def test_shader_def():
    from agents.effect_graph.types import ParamDef, PortType, ShaderDef

    s = ShaderDef(
        node_type="colorgrade",
        glsl_fragment="shaders/nodes/colorgrade.frag",
        inputs={"in": PortType.FRAME},
        outputs={"out": PortType.FRAME},
        params={
            "saturation": ParamDef(type="float", default=1.0, min=0.0, max=2.0),
            "brightness": ParamDef(type="float", default=1.0, min=0.0, max=2.0),
        },
        temporal=False,
    )
    assert s.node_type == "colorgrade"
    assert s.inputs["in"] == PortType.FRAME
    assert not s.temporal


def test_shader_def_temporal():
    from agents.effect_graph.types import ParamDef, PortType, ShaderDef

    s = ShaderDef(
        node_type="trail",
        glsl_fragment="shaders/nodes/trail.frag",
        inputs={"in": PortType.FRAME},
        outputs={"out": PortType.FRAME},
        params={
            "fade": ParamDef(type="float", default=0.04, min=0.001, max=0.2),
        },
        temporal=True,
        temporal_buffers=1,
    )
    assert s.temporal
    assert s.temporal_buffers == 1


def test_node_instance():
    from agents.effect_graph.types import NodeInstance

    n = NodeInstance(type="colorgrade", params={"saturation": 0.5, "brightness": 1.2})
    assert n.type == "colorgrade"
    assert n.params["saturation"] == 0.5


def test_edge_def_simple():
    from agents.effect_graph.types import EdgeDef

    e = EdgeDef.from_list(["color", "trail"])
    assert e.source_node == "color"
    assert e.source_port == "out"
    assert e.target_node == "trail"
    assert e.target_port == "in"


def test_edge_def_with_ports():
    from agents.effect_graph.types import EdgeDef

    e = EdgeDef.from_list(["@live", "blend:a"])
    assert e.source_node == "@live"
    assert e.source_port == "out"
    assert e.target_node == "blend"
    assert e.target_port == "a"


def test_edge_def_layer_source():
    from agents.effect_graph.types import EdgeDef

    e = EdgeDef.from_list(["@smooth", "color"])
    assert e.source_node == "@smooth"
    assert e.is_layer_source


def test_effect_graph_valid():
    from agents.effect_graph.types import EffectGraph, NodeInstance

    g = EffectGraph(
        name="test",
        nodes={
            "color": NodeInstance(type="colorgrade", params={"saturation": 1.0}),
            "out": NodeInstance(type="output", params={}),
        },
        edges=[["@live", "color"], ["color", "out"]],
    )
    assert len(g.nodes) == 2
    assert len(g.parsed_edges) == 2


def test_effect_graph_with_modulations():
    from agents.effect_graph.types import EffectGraph, ModulationBinding, NodeInstance

    g = EffectGraph(
        name="test",
        nodes={
            "color": NodeInstance(type="colorgrade", params={}),
            "out": NodeInstance(type="output", params={}),
        },
        edges=[["@live", "color"], ["color", "out"]],
        modulations=[
            ModulationBinding(
                node="color",
                param="saturation",
                source="audio_rms",
                scale=0.3,
                offset=0.5,
                smoothing=0.85,
            )
        ],
    )
    assert len(g.modulations) == 1
    assert g.modulations[0].source == "audio_rms"


def test_graph_patch_add_node():
    from agents.effect_graph.types import GraphPatch, NodeInstance

    p = GraphPatch(
        add_nodes={"bloom": NodeInstance(type="bloom", params={"threshold": 0.5})},
        add_edges=[["color", "bloom"], ["bloom", "out"]],
        remove_edges=[["color", "out"]],
    )
    assert "bloom" in p.add_nodes
    assert len(p.add_edges) == 2
    assert len(p.remove_edges) == 1


def test_layer_palette():
    from agents.effect_graph.types import LayerPalette

    lp = LayerPalette(
        saturation=0.4, sepia=0.55, hue_rotate=-10, contrast=1.25, brightness=1.1
    )
    assert lp.saturation == 0.4
    assert lp.hue_rotate == -10


def test_modulation_binding_validation():
    from agents.effect_graph.types import ModulationBinding

    m = ModulationBinding(
        node="bloom",
        param="alpha",
        source="audio_rms",
        scale=0.4,
        offset=0.2,
        smoothing=0.85,
    )
    assert 0.0 <= m.smoothing <= 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/effect_graph/test_types.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.effect_graph'`

- [ ] **Step 3: Implement type models**

```python
# agents/effect_graph/__init__.py
"""Effect node graph — composable GPU shader pipeline."""

# agents/effect_graph/types.py
"""Pydantic models for the effect node graph system."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PortType(str, Enum):
    """Port types for node connections."""

    FRAME = "frame"
    SCALAR = "scalar"
    COLOR = "color"


class ParamDef(BaseModel):
    """Definition of a shader uniform parameter."""

    type: str  # "float", "int", "vec2", "vec3", "vec4", "bool", "enum"
    default: Any
    min: float | None = None
    max: float | None = None
    enum_values: list[str] | None = None
    description: str = ""


class ShaderDef(BaseModel):
    """Definition of a shader node type loaded from manifest."""

    node_type: str
    glsl_fragment: str  # path to .frag file (relative to shaders/)
    inputs: dict[str, PortType]
    outputs: dict[str, PortType]
    params: dict[str, ParamDef]
    temporal: bool = False
    temporal_buffers: int = 0
    compute: bool = False


class NodeInstance(BaseModel):
    """An instance of a node in a graph with concrete parameter values."""

    type: str
    params: dict[str, Any] = Field(default_factory=dict)


class EdgeDef(BaseModel):
    """A connection between two nodes."""

    source_node: str
    source_port: str = "out"
    target_node: str
    target_port: str = "in"

    @property
    def is_layer_source(self) -> bool:
        return self.source_node.startswith("@")

    @classmethod
    def from_list(cls, edge: list[str]) -> EdgeDef:
        """Parse edge from ["source", "target"] or ["source", "target:port"] format."""
        if len(edge) != 2:
            msg = f"Edge must be [source, target], got {edge}"
            raise ValueError(msg)

        src_raw, tgt_raw = edge

        # Parse source — "node" or "node:port"
        if ":" in src_raw and not src_raw.startswith("@"):
            src_node, src_port = src_raw.split(":", 1)
        else:
            src_node = src_raw
            src_port = "out"

        # Parse target — "node" or "node:port"
        if ":" in tgt_raw:
            tgt_node, tgt_port = tgt_raw.split(":", 1)
        else:
            tgt_node = tgt_raw
            tgt_port = "in"

        return cls(
            source_node=src_node,
            source_port=src_port,
            target_node=tgt_node,
            target_port=tgt_port,
        )


class ModulationBinding(BaseModel):
    """Binds a node parameter to a perceptual signal source."""

    node: str
    param: str
    source: str  # audio_rms, audio_beat, stimmung_valence, etc.
    scale: float = 1.0
    offset: float = 0.0
    smoothing: float = Field(default=0.85, ge=0.0, le=1.0)


class LayerPalette(BaseModel):
    """Color grade applied to a persistent source layer."""

    saturation: float = Field(default=1.0, ge=0.0, le=2.0)
    brightness: float = Field(default=1.0, ge=0.0, le=2.0)
    contrast: float = Field(default=1.0, ge=0.0, le=2.0)
    sepia: float = Field(default=0.0, ge=0.0, le=1.0)
    hue_rotate: float = Field(default=0.0, ge=-180.0, le=180.0)


class EffectGraph(BaseModel):
    """Complete effect graph definition — the unit of preset storage and API exchange."""

    name: str = ""
    description: str = ""
    transition_ms: int = 500
    nodes: dict[str, NodeInstance]
    edges: list[list[str]]  # Raw edge lists — parsed on access
    modulations: list[ModulationBinding] = Field(default_factory=list)
    layer_palettes: dict[str, LayerPalette] = Field(default_factory=dict)

    @property
    def parsed_edges(self) -> list[EdgeDef]:
        return [EdgeDef.from_list(e) for e in self.edges]


class GraphPatch(BaseModel):
    """Topology mutation: add/remove nodes and edges."""

    add_nodes: dict[str, NodeInstance] = Field(default_factory=dict)
    remove_nodes: list[str] = Field(default_factory=list)
    add_edges: list[list[str]] = Field(default_factory=list)
    remove_edges: list[list[str]] = Field(default_factory=list)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/effect_graph/test_types.py -v`
Expected: All 14 tests PASS

- [ ] **Step 5: Lint and commit**

Run: `cd /home/hapax/projects/hapax-council && uv run ruff check agents/effect_graph/ tests/effect_graph/ --fix && uv run ruff format agents/effect_graph/ tests/effect_graph/`

```bash
git add agents/effect_graph/__init__.py agents/effect_graph/types.py tests/effect_graph/__init__.py tests/effect_graph/test_types.py
git commit -m "feat(effect-graph): add type models for node graph system"
```

---

## Task 2: Shader Registry

**Files:**
- Create: `agents/effect_graph/registry.py`
- Create: `tests/effect_graph/test_registry.py`
- Create: `agents/shaders/nodes/colorgrade.json`
- Migrate: `agents/shaders/nodes/colorgrade.frag` (copy and clean up from `agents/shaders/color_grade.frag`)

- [ ] **Step 1: Create the colorgrade manifest as reference**

```json
// agents/shaders/nodes/colorgrade.json
{
  "node_type": "colorgrade",
  "glsl_fragment": "colorgrade.frag",
  "inputs": { "in": "frame" },
  "outputs": { "out": "frame" },
  "params": {
    "saturation": { "type": "float", "default": 1.0, "min": 0.0, "max": 2.0, "description": "Color saturation" },
    "brightness": { "type": "float", "default": 1.0, "min": 0.0, "max": 2.0, "description": "Brightness multiplier" },
    "contrast": { "type": "float", "default": 1.0, "min": 0.0, "max": 2.0, "description": "Contrast multiplier" },
    "sepia": { "type": "float", "default": 0.0, "min": 0.0, "max": 1.0, "description": "Sepia tone strength" },
    "hue_rotate": { "type": "float", "default": 0.0, "min": -180.0, "max": 180.0, "description": "Hue rotation in degrees" }
  },
  "temporal": false
}
```

- [ ] **Step 2: Copy and clean up existing colorgrade shader**

Copy `agents/shaders/color_grade.frag` to `agents/shaders/nodes/colorgrade.frag`. The existing shader already uses `u_saturation`, `u_brightness`, `u_contrast`, `u_sepia`, `u_hue_rotate` uniforms. Verify it compiles (it's already proven in production).

- [ ] **Step 3: Write failing tests for registry**

```python
# tests/effect_graph/test_registry.py
"""Tests for shader registry."""

from pathlib import Path

import pytest


@pytest.fixture
def shader_dir(tmp_path: Path) -> Path:
    """Create a temporary shader node directory with one manifest."""
    nodes_dir = tmp_path / "nodes"
    nodes_dir.mkdir()

    # Write a minimal manifest
    manifest = nodes_dir / "colorgrade.json"
    manifest.write_text(
        """{
  "node_type": "colorgrade",
  "glsl_fragment": "colorgrade.frag",
  "inputs": {"in": "frame"},
  "outputs": {"out": "frame"},
  "params": {
    "saturation": {"type": "float", "default": 1.0, "min": 0.0, "max": 2.0, "description": "Color saturation"}
  },
  "temporal": false
}"""
    )

    # Write a minimal shader
    frag = nodes_dir / "colorgrade.frag"
    frag.write_text(
        """#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_saturation;
void main() {
    gl_FragColor = texture2D(tex, v_texcoord);
}
"""
    )

    return tmp_path


def test_registry_loads_manifests(shader_dir: Path):
    from agents.effect_graph.registry import ShaderRegistry

    reg = ShaderRegistry(shader_dir / "nodes")
    assert "colorgrade" in reg.node_types


def test_registry_get_shader_def(shader_dir: Path):
    from agents.effect_graph.registry import ShaderRegistry

    reg = ShaderRegistry(shader_dir / "nodes")
    sd = reg.get("colorgrade")
    assert sd is not None
    assert sd.node_type == "colorgrade"
    assert "saturation" in sd.params
    assert sd.glsl_source is not None
    assert "v_texcoord" in sd.glsl_source


def test_registry_unknown_type(shader_dir: Path):
    from agents.effect_graph.registry import ShaderRegistry

    reg = ShaderRegistry(shader_dir / "nodes")
    assert reg.get("nonexistent") is None


def test_registry_lists_all_types(shader_dir: Path):
    from agents.effect_graph.registry import ShaderRegistry

    reg = ShaderRegistry(shader_dir / "nodes")
    types = reg.node_types
    assert isinstance(types, list)
    assert "colorgrade" in types


def test_registry_schema_export(shader_dir: Path):
    from agents.effect_graph.registry import ShaderRegistry

    reg = ShaderRegistry(shader_dir / "nodes")
    schema = reg.schema("colorgrade")
    assert schema is not None
    assert schema["node_type"] == "colorgrade"
    assert "params" in schema
    assert "saturation" in schema["params"]


def test_registry_output_node(shader_dir: Path):
    """Output node has no shader — just a manifest."""
    nodes_dir = shader_dir / "nodes"
    out_manifest = nodes_dir / "output.json"
    out_manifest.write_text(
        """{
  "node_type": "output",
  "glsl_fragment": "",
  "inputs": {"in": "frame"},
  "outputs": {},
  "params": {},
  "temporal": false
}"""
    )

    from agents.effect_graph.registry import ShaderRegistry

    reg = ShaderRegistry(nodes_dir)
    sd = reg.get("output")
    assert sd is not None
    assert sd.glsl_source is None  # No shader for output sink
    assert len(sd.outputs) == 0


def test_registry_temporal_node(shader_dir: Path):
    """Temporal nodes declare buffer requirements."""
    nodes_dir = shader_dir / "nodes"
    trail_manifest = nodes_dir / "trail.json"
    trail_manifest.write_text(
        """{
  "node_type": "trail",
  "glsl_fragment": "trail.frag",
  "inputs": {"in": "frame"},
  "outputs": {"out": "frame"},
  "params": {
    "fade": {"type": "float", "default": 0.04, "min": 0.001, "max": 0.2}
  },
  "temporal": true,
  "temporal_buffers": 1
}"""
    )
    trail_frag = nodes_dir / "trail.frag"
    trail_frag.write_text("void main() { gl_FragColor = vec4(0.0); }")

    from agents.effect_graph.registry import ShaderRegistry

    reg = ShaderRegistry(nodes_dir)
    sd = reg.get("trail")
    assert sd is not None
    assert sd.temporal is True
    assert sd.temporal_buffers == 1
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/effect_graph/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agents.effect_graph.registry'`

- [ ] **Step 5: Implement the registry**

```python
# agents/effect_graph/registry.py
"""Shader registry — loads node type definitions from manifest files."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .types import ParamDef, PortType, ShaderDef

log = logging.getLogger(__name__)


@dataclass
class LoadedShaderDef:
    """ShaderDef with loaded GLSL source code."""

    node_type: str
    inputs: dict[str, PortType]
    outputs: dict[str, PortType]
    params: dict[str, ParamDef]
    temporal: bool
    temporal_buffers: int
    compute: bool
    glsl_source: str | None  # None for sink/passthrough nodes


class ShaderRegistry:
    """Scans a directory of .json manifests and .frag shaders, exposes node type schemas."""

    def __init__(self, nodes_dir: Path) -> None:
        self._nodes_dir = nodes_dir
        self._defs: dict[str, LoadedShaderDef] = {}
        self._load_all()

    def _load_all(self) -> None:
        if not self._nodes_dir.is_dir():
            log.warning("Shader nodes directory does not exist: %s", self._nodes_dir)
            return

        for manifest_path in sorted(self._nodes_dir.glob("*.json")):
            try:
                self._load_manifest(manifest_path)
            except Exception:
                log.exception("Failed to load shader manifest: %s", manifest_path)

    def _load_manifest(self, path: Path) -> None:
        raw = json.loads(path.read_text())
        node_type = raw["node_type"]

        # Parse params
        params: dict[str, ParamDef] = {}
        for name, pdef in raw.get("params", {}).items():
            params[name] = ParamDef(**pdef)

        # Parse ports
        inputs = {k: PortType(v) for k, v in raw.get("inputs", {}).items()}
        outputs = {k: PortType(v) for k, v in raw.get("outputs", {}).items()}

        # Load GLSL source if specified
        glsl_source: str | None = None
        frag_name = raw.get("glsl_fragment", "")
        if frag_name:
            frag_path = self._nodes_dir / frag_name
            if frag_path.is_file():
                glsl_source = frag_path.read_text()
            else:
                log.warning("Shader file not found: %s", frag_path)

        self._defs[node_type] = LoadedShaderDef(
            node_type=node_type,
            inputs=inputs,
            outputs=outputs,
            params=params,
            temporal=raw.get("temporal", False),
            temporal_buffers=raw.get("temporal_buffers", 0),
            compute=raw.get("compute", False),
            glsl_source=glsl_source,
        )

    @property
    def node_types(self) -> list[str]:
        return sorted(self._defs.keys())

    def get(self, node_type: str) -> LoadedShaderDef | None:
        return self._defs.get(node_type)

    def schema(self, node_type: str) -> dict[str, Any] | None:
        """Export node type as JSON-serializable dict for the API."""
        defn = self._defs.get(node_type)
        if defn is None:
            return None
        return {
            "node_type": defn.node_type,
            "inputs": {k: v.value for k, v in defn.inputs.items()},
            "outputs": {k: v.value for k, v in defn.outputs.items()},
            "params": {
                name: pdef.model_dump() for name, pdef in defn.params.items()
            },
            "temporal": defn.temporal,
            "temporal_buffers": defn.temporal_buffers,
            "compute": defn.compute,
        }

    def all_schemas(self) -> dict[str, Any]:
        """Export all node types for the registry API."""
        return {
            node_type: self.schema(node_type) for node_type in self._defs
        }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/effect_graph/test_registry.py -v`
Expected: All 7 tests PASS

- [ ] **Step 7: Lint and commit**

Run: `cd /home/hapax/projects/hapax-council && uv run ruff check agents/effect_graph/ tests/effect_graph/ --fix && uv run ruff format agents/effect_graph/ tests/effect_graph/`

```bash
git add agents/effect_graph/registry.py agents/shaders/nodes/colorgrade.json agents/shaders/nodes/colorgrade.frag tests/effect_graph/test_registry.py
git commit -m "feat(effect-graph): shader registry with manifest loading"
```

---

## Task 3: Graph Compiler (Validation + Topological Sort)

**Files:**
- Create: `agents/effect_graph/compiler.py`
- Create: `tests/effect_graph/test_compiler.py`

- [ ] **Step 1: Write failing tests for graph validation and compilation**

```python
# tests/effect_graph/test_compiler.py
"""Tests for graph compiler — validation, topological sort, FBO allocation."""

from pathlib import Path

import pytest

from agents.effect_graph.types import EffectGraph, NodeInstance


def _minimal_registry(tmp_path: Path):
    """Create a registry with colorgrade, trail, blend, scanlines, output nodes."""
    from agents.effect_graph.registry import ShaderRegistry

    nodes_dir = tmp_path / "nodes"
    nodes_dir.mkdir(exist_ok=True)

    # Minimal manifests
    for node_type, inputs, outputs, temporal in [
        ("colorgrade", {"in": "frame"}, {"out": "frame"}, False),
        ("trail", {"in": "frame"}, {"out": "frame"}, True),
        ("blend", {"a": "frame", "b": "frame"}, {"out": "frame"}, False),
        ("scanlines", {"in": "frame"}, {"out": "frame"}, False),
        ("bloom", {"in": "frame"}, {"out": "frame"}, False),
        ("vignette", {"in": "frame"}, {"out": "frame"}, False),
        ("output", {"in": "frame"}, {}, False),
    ]:
        import json

        manifest = {
            "node_type": node_type,
            "glsl_fragment": "",
            "inputs": inputs,
            "outputs": outputs,
            "params": {},
            "temporal": temporal,
            "temporal_buffers": 1 if temporal else 0,
        }
        (nodes_dir / f"{node_type}.json").write_text(json.dumps(manifest))

    return ShaderRegistry(nodes_dir)


def test_compile_linear_graph(tmp_path: Path):
    from agents.effect_graph.compiler import GraphCompiler

    reg = _minimal_registry(tmp_path)
    compiler = GraphCompiler(reg)

    graph = EffectGraph(
        name="test",
        nodes={
            "color": NodeInstance(type="colorgrade"),
            "scan": NodeInstance(type="scanlines"),
            "out": NodeInstance(type="output"),
        },
        edges=[["@live", "color"], ["color", "scan"], ["scan", "out"]],
    )

    plan = compiler.compile(graph)
    assert plan is not None
    # Execution order should be: color → scan → out
    node_order = [step.node_id for step in plan.steps]
    assert node_order.index("color") < node_order.index("scan")
    assert node_order.index("scan") < node_order.index("out")


def test_compile_branching_graph(tmp_path: Path):
    """Two sources → blend → output."""
    from agents.effect_graph.compiler import GraphCompiler

    reg = _minimal_registry(tmp_path)
    compiler = GraphCompiler(reg)

    graph = EffectGraph(
        name="test",
        nodes={
            "color_live": NodeInstance(type="colorgrade"),
            "color_smooth": NodeInstance(type="colorgrade"),
            "mix": NodeInstance(type="blend"),
            "out": NodeInstance(type="output"),
        },
        edges=[
            ["@live", "color_live"],
            ["@smooth", "color_smooth"],
            ["color_live", "mix:a"],
            ["color_smooth", "mix:b"],
            ["mix", "out"],
        ],
    )

    plan = compiler.compile(graph)
    node_order = [step.node_id for step in plan.steps]
    # Both color nodes before mix, mix before out
    assert node_order.index("color_live") < node_order.index("mix")
    assert node_order.index("color_smooth") < node_order.index("mix")
    assert node_order.index("mix") < node_order.index("out")


def test_reject_cycle(tmp_path: Path):
    from agents.effect_graph.compiler import GraphCompiler, GraphValidationError

    reg = _minimal_registry(tmp_path)
    compiler = GraphCompiler(reg)

    graph = EffectGraph(
        name="cycle",
        nodes={
            "a": NodeInstance(type="colorgrade"),
            "b": NodeInstance(type="colorgrade"),
            "out": NodeInstance(type="output"),
        },
        edges=[["@live", "a"], ["a", "b"], ["b", "a"], ["b", "out"]],
    )

    with pytest.raises(GraphValidationError, match="[Cc]ycle"):
        compiler.compile(graph)


def test_reject_missing_output(tmp_path: Path):
    from agents.effect_graph.compiler import GraphCompiler, GraphValidationError

    reg = _minimal_registry(tmp_path)
    compiler = GraphCompiler(reg)

    graph = EffectGraph(
        name="no-output",
        nodes={"color": NodeInstance(type="colorgrade")},
        edges=[["@live", "color"]],
    )

    with pytest.raises(GraphValidationError, match="[Oo]utput"):
        compiler.compile(graph)


def test_reject_unknown_node_type(tmp_path: Path):
    from agents.effect_graph.compiler import GraphCompiler, GraphValidationError

    reg = _minimal_registry(tmp_path)
    compiler = GraphCompiler(reg)

    graph = EffectGraph(
        name="unknown",
        nodes={
            "x": NodeInstance(type="nonexistent"),
            "out": NodeInstance(type="output"),
        },
        edges=[["@live", "x"], ["x", "out"]],
    )

    with pytest.raises(GraphValidationError, match="[Uu]nknown"):
        compiler.compile(graph)


def test_reject_disconnected_node(tmp_path: Path):
    from agents.effect_graph.compiler import GraphCompiler, GraphValidationError

    reg = _minimal_registry(tmp_path)
    compiler = GraphCompiler(reg)

    graph = EffectGraph(
        name="disconnected",
        nodes={
            "color": NodeInstance(type="colorgrade"),
            "orphan": NodeInstance(type="scanlines"),
            "out": NodeInstance(type="output"),
        },
        edges=[["@live", "color"], ["color", "out"]],
    )

    with pytest.raises(GraphValidationError, match="[Dd]isconnect|[Uu]nconnect"):
        compiler.compile(graph)


def test_temporal_nodes_flagged(tmp_path: Path):
    from agents.effect_graph.compiler import GraphCompiler

    reg = _minimal_registry(tmp_path)
    compiler = GraphCompiler(reg)

    graph = EffectGraph(
        name="temporal",
        nodes={
            "trail": NodeInstance(type="trail"),
            "out": NodeInstance(type="output"),
        },
        edges=[["@live", "trail"], ["trail", "out"]],
    )

    plan = compiler.compile(graph)
    trail_step = next(s for s in plan.steps if s.node_id == "trail")
    assert trail_step.temporal is True


def test_layer_sources_validated(tmp_path: Path):
    """Only @live, @smooth, @hls are valid layer sources."""
    from agents.effect_graph.compiler import GraphCompiler, GraphValidationError

    reg = _minimal_registry(tmp_path)
    compiler = GraphCompiler(reg)

    graph = EffectGraph(
        name="bad-layer",
        nodes={"out": NodeInstance(type="output")},
        edges=[["@invalid", "out"]],
    )

    with pytest.raises(GraphValidationError, match="[Ll]ayer|[Ss]ource"):
        compiler.compile(graph)


def test_fbo_allocation_multi_consumer(tmp_path: Path):
    """A node feeding two consumers needs a dedicated FBO."""
    from agents.effect_graph.compiler import GraphCompiler

    reg = _minimal_registry(tmp_path)
    compiler = GraphCompiler(reg)

    graph = EffectGraph(
        name="fan-out",
        nodes={
            "color": NodeInstance(type="colorgrade"),
            "scan": NodeInstance(type="scanlines"),
            "bloom": NodeInstance(type="bloom"),
            "mix": NodeInstance(type="blend"),
            "out": NodeInstance(type="output"),
        },
        edges=[
            ["@live", "color"],
            ["color", "scan"],
            ["color", "bloom"],
            ["scan", "mix:a"],
            ["bloom", "mix:b"],
            ["mix", "out"],
        ],
    )

    plan = compiler.compile(graph)
    color_step = next(s for s in plan.steps if s.node_id == "color")
    assert color_step.needs_dedicated_fbo is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/effect_graph/test_compiler.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the compiler**

```python
# agents/effect_graph/compiler.py
"""Graph compiler — validates and compiles effect graphs into execution plans."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .registry import ShaderRegistry
from .types import EdgeDef, EffectGraph

log = logging.getLogger(__name__)

VALID_LAYER_SOURCES = {"@live", "@smooth", "@hls"}


class GraphValidationError(Exception):
    """Raised when a graph fails validation."""


@dataclass
class ExecutionStep:
    """One node in the compiled execution plan."""

    node_id: str
    node_type: str
    params: dict[str, Any]
    shader_source: str | None  # GLSL fragment source
    input_edges: list[EdgeDef]
    output_edges: list[EdgeDef]
    temporal: bool = False
    temporal_buffers: int = 0
    needs_dedicated_fbo: bool = False


@dataclass
class ExecutionPlan:
    """Compiled graph ready for GStreamer element chain construction."""

    name: str
    steps: list[ExecutionStep]
    layer_sources: set[str]  # Which @layers are used
    transition_ms: int = 500


class GraphCompiler:
    """Validates and compiles EffectGraph into ExecutionPlan."""

    def __init__(self, registry: ShaderRegistry) -> None:
        self._registry = registry

    def compile(self, graph: EffectGraph) -> ExecutionPlan:
        """Validate and compile a graph into an execution plan."""
        edges = graph.parsed_edges
        self._validate(graph, edges)
        order = self._topological_sort(graph, edges)
        steps = self._build_steps(graph, edges, order)
        layer_sources = {e.source_node for e in edges if e.is_layer_source}
        return ExecutionPlan(
            name=graph.name,
            steps=steps,
            layer_sources=layer_sources,
            transition_ms=graph.transition_ms,
        )

    def _validate(self, graph: EffectGraph, edges: list[EdgeDef]) -> None:
        """Run all validation checks."""
        # Check for output node
        has_output = any(n.type == "output" for n in graph.nodes.values())
        if not has_output:
            raise GraphValidationError("Graph must have exactly one output node")

        # Check for unknown node types
        for node_id, node in graph.nodes.items():
            if node.type == "output":
                continue
            defn = self._registry.get(node.type)
            if defn is None:
                raise GraphValidationError(
                    f"Unknown node type '{node.type}' for node '{node_id}'"
                )

        # Check layer sources
        for edge in edges:
            if edge.source_node.startswith("@") and edge.source_node not in VALID_LAYER_SOURCES:
                raise GraphValidationError(
                    f"Invalid layer source '{edge.source_node}'. "
                    f"Valid sources: {VALID_LAYER_SOURCES}"
                )

        # Check for disconnected nodes (every non-layer node must have at least one edge)
        connected = set()
        for edge in edges:
            if not edge.is_layer_source:
                connected.add(edge.source_node)
            connected.add(edge.target_node)
        for node_id in graph.nodes:
            if node_id not in connected:
                raise GraphValidationError(
                    f"Disconnected node '{node_id}' — not connected to any edge"
                )

        # Check for cycles via topological sort (will raise if cycle found)
        self._topological_sort(graph, edges)

    def _topological_sort(self, graph: EffectGraph, edges: list[EdgeDef]) -> list[str]:
        """Kahn's algorithm for topological sort. Raises on cycle."""
        # Build adjacency and in-degree for graph nodes only (not layer sources)
        in_degree: dict[str, int] = {nid: 0 for nid in graph.nodes}
        successors: dict[str, list[str]] = defaultdict(list)

        for edge in edges:
            if edge.is_layer_source:
                # Layer sources have no in-degree to track
                continue
            if edge.source_node in graph.nodes and edge.target_node in graph.nodes:
                in_degree[edge.target_node] = in_degree.get(edge.target_node, 0) + 1
                successors[edge.source_node].append(edge.target_node)

        # Also count edges from layer sources
        for edge in edges:
            if edge.is_layer_source and edge.target_node in graph.nodes:
                # These don't add to in_degree for cycle detection purposes
                # but the target needs to be reachable
                pass

        # Find nodes with in_degree 0 (or only fed by layer sources)
        queue = []
        for nid in graph.nodes:
            # Count only non-layer input edges
            non_layer_inputs = sum(
                1 for e in edges if e.target_node == nid and not e.is_layer_source
                and e.source_node in graph.nodes
            )
            if non_layer_inputs == 0:
                queue.append(nid)

        order: list[str] = []
        while queue:
            node = queue.pop(0)
            order.append(node)
            for succ in successors.get(node, []):
                in_degree[succ] -= 1
                if in_degree[succ] == 0:
                    queue.append(succ)

        if len(order) != len(graph.nodes):
            raise GraphValidationError(
                "Cycle detected in graph — nodes not in topological order: "
                f"{set(graph.nodes) - set(order)}"
            )

        return order

    def _build_steps(
        self, graph: EffectGraph, edges: list[EdgeDef], order: list[str]
    ) -> list[ExecutionStep]:
        """Build execution steps from sorted node order."""
        # Count outgoing edges per node for FBO allocation
        out_count: dict[str, int] = defaultdict(int)
        for edge in edges:
            if not edge.is_layer_source:
                out_count[edge.source_node] += 1

        steps: list[ExecutionStep] = []
        for node_id in order:
            node = graph.nodes[node_id]
            defn = self._registry.get(node.type)

            input_edges = [e for e in edges if e.target_node == node_id]
            output_edges = [e for e in edges if e.source_node == node_id]

            steps.append(
                ExecutionStep(
                    node_id=node_id,
                    node_type=node.type,
                    params=dict(node.params),
                    shader_source=defn.glsl_source if defn else None,
                    input_edges=input_edges,
                    output_edges=output_edges,
                    temporal=defn.temporal if defn else False,
                    temporal_buffers=defn.temporal_buffers if defn else 0,
                    needs_dedicated_fbo=out_count.get(node_id, 0) > 1,
                )
            )

        return steps
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/effect_graph/test_compiler.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Lint and commit**

```bash
cd /home/hapax/projects/hapax-council
uv run ruff check agents/effect_graph/ tests/effect_graph/ --fix && uv run ruff format agents/effect_graph/ tests/effect_graph/
git add agents/effect_graph/compiler.py tests/effect_graph/test_compiler.py
git commit -m "feat(effect-graph): graph compiler with validation and topological sort"
```

---

## Task 4: Foundational Shader Nodes

**Files:**
- Create: `agents/shaders/nodes/scanlines.frag` + `.json`
- Create: `agents/shaders/nodes/vignette.frag` + `.json`
- Create: `agents/shaders/nodes/bloom.frag` + `.json`
- Create: `agents/shaders/nodes/noise_overlay.frag` + `.json`
- Create: `agents/shaders/nodes/blend.frag` + `.json`
- Create: `agents/shaders/nodes/trail.frag` + `.json`
- Create: `agents/shaders/nodes/stutter.json` (Python element, no GLSL)
- Create: `agents/shaders/nodes/output.json`
- Create: `agents/shaders/nodes/palette.frag` + `.json`

Each node needs a manifest and a shader. The existing `post_process.frag` contains scanlines + vignette + band_displacement + syrup — we extract them into individual shaders.

- [ ] **Step 1: Create output sink manifest**

```json
// agents/shaders/nodes/output.json
{
  "node_type": "output",
  "glsl_fragment": "",
  "inputs": { "in": "frame" },
  "outputs": {},
  "params": {},
  "temporal": false
}
```

- [ ] **Step 2: Create palette shader (per-layer colorgrade)**

The palette shader is identical to colorgrade — same uniforms, same logic. It's used for the persistent layer color grades.

```json
// agents/shaders/nodes/palette.json
{
  "node_type": "palette",
  "glsl_fragment": "colorgrade.frag",
  "inputs": { "in": "frame" },
  "outputs": { "out": "frame" },
  "params": {
    "saturation": { "type": "float", "default": 1.0, "min": 0.0, "max": 2.0 },
    "brightness": { "type": "float", "default": 1.0, "min": 0.0, "max": 2.0 },
    "contrast": { "type": "float", "default": 1.0, "min": 0.0, "max": 2.0 },
    "sepia": { "type": "float", "default": 0.0, "min": 0.0, "max": 1.0 },
    "hue_rotate": { "type": "float", "default": 0.0, "min": -180.0, "max": 180.0 }
  },
  "temporal": false
}
```

- [ ] **Step 3: Create scanlines shader (extracted from post_process.frag)**

```glsl
// agents/shaders/nodes/scanlines.frag
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_opacity;    // 0-0.5, default 0.12
uniform float u_spacing;    // 2-8, default 4.0
uniform float u_thickness;  // 0.5-3, default 1.5
uniform float u_height;     // canvas height in pixels

void main() {
    vec4 color = texture2D(tex, v_texcoord);
    float pixel_y = v_texcoord.y * u_height;
    float line = step(u_spacing - u_thickness, mod(pixel_y, u_spacing));
    color.rgb *= 1.0 - line * u_opacity;
    gl_FragColor = color;
}
```

```json
// agents/shaders/nodes/scanlines.json
{
  "node_type": "scanlines",
  "glsl_fragment": "scanlines.frag",
  "inputs": { "in": "frame" },
  "outputs": { "out": "frame" },
  "params": {
    "opacity": { "type": "float", "default": 0.12, "min": 0.0, "max": 0.5, "description": "Line darkness" },
    "spacing": { "type": "float", "default": 4.0, "min": 2.0, "max": 8.0, "description": "Pixels between lines" },
    "thickness": { "type": "float", "default": 1.5, "min": 0.5, "max": 3.0, "description": "Line thickness" }
  },
  "temporal": false
}
```

- [ ] **Step 4: Create vignette shader**

```glsl
// agents/shaders/nodes/vignette.frag
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_strength;   // 0-1, default 0.35
uniform float u_radius;     // 0.2-0.9, default 0.7
uniform float u_softness;   // 0.1-0.5, default 0.3

void main() {
    vec4 color = texture2D(tex, v_texcoord);
    vec2 center = v_texcoord - 0.5;
    float dist = length(center) * 2.0;  // 0 at center, ~1.41 at corners
    float vig = smoothstep(u_radius, u_radius + u_softness, dist);
    color.rgb *= 1.0 - vig * u_strength;
    gl_FragColor = color;
}
```

```json
// agents/shaders/nodes/vignette.json
{
  "node_type": "vignette",
  "glsl_fragment": "vignette.frag",
  "inputs": { "in": "frame" },
  "outputs": { "out": "frame" },
  "params": {
    "strength": { "type": "float", "default": 0.35, "min": 0.0, "max": 1.0, "description": "Darkening strength" },
    "radius": { "type": "float", "default": 0.7, "min": 0.2, "max": 0.9, "description": "Clear center radius" },
    "softness": { "type": "float", "default": 0.3, "min": 0.1, "max": 0.5, "description": "Falloff softness" }
  },
  "temporal": false
}
```

- [ ] **Step 5: Create bloom shader**

```glsl
// agents/shaders/nodes/bloom.frag
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_threshold;  // 0-1, default 0.5
uniform float u_radius;     // 1-20, default 8.0
uniform float u_alpha;      // 0-1, default 0.3
uniform float u_width;
uniform float u_height;

void main() {
    vec4 color = texture2D(tex, v_texcoord);

    // Bright-pass: extract pixels above threshold
    float luma = dot(color.rgb, vec3(0.299, 0.587, 0.114));
    float bright = smoothstep(u_threshold - 0.1, u_threshold + 0.1, luma);

    // Gaussian blur approximation (9-tap, at reduced effective resolution)
    vec2 texel = vec2(1.0 / u_width, 1.0 / u_height) * u_radius * 0.25;
    vec3 glow = vec3(0.0);
    float total = 0.0;
    for (float x = -2.0; x <= 2.0; x += 1.0) {
        for (float y = -2.0; y <= 2.0; y += 1.0) {
            vec2 offset = vec2(x, y) * texel;
            vec4 s = texture2D(tex, v_texcoord + offset);
            float sl = dot(s.rgb, vec3(0.299, 0.587, 0.114));
            float sb = smoothstep(u_threshold - 0.1, u_threshold + 0.1, sl);
            float w = exp(-(x * x + y * y) / 4.0);
            glow += s.rgb * sb * w;
            total += w;
        }
    }
    glow /= total;

    // Additive composite
    color.rgb += glow * u_alpha;
    gl_FragColor = color;
}
```

```json
// agents/shaders/nodes/bloom.json
{
  "node_type": "bloom",
  "glsl_fragment": "bloom.frag",
  "inputs": { "in": "frame" },
  "outputs": { "out": "frame" },
  "params": {
    "threshold": { "type": "float", "default": 0.5, "min": 0.0, "max": 1.0, "description": "Brightness cutoff for glow extraction" },
    "radius": { "type": "float", "default": 8.0, "min": 1.0, "max": 20.0, "description": "Blur radius in pixels" },
    "alpha": { "type": "float", "default": 0.3, "min": 0.0, "max": 1.0, "description": "Glow composite opacity" }
  },
  "temporal": false
}
```

- [ ] **Step 6: Create noise overlay shader**

```glsl
// agents/shaders/nodes/noise_overlay.frag
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_intensity;   // 0-0.3, default 0.06
uniform float u_animated;    // 0.0 or 1.0
uniform float u_time;
uniform float u_width;
uniform float u_height;

// Simple hash noise
float hash(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

void main() {
    vec4 color = texture2D(tex, v_texcoord);

    // Generate grain at 1/8 resolution for performance
    vec2 grain_uv = floor(v_texcoord * vec2(u_width, u_height) / 8.0);
    float seed = u_animated > 0.5 ? floor(u_time * 10.0) : 0.0;
    float noise = hash(grain_uv + seed);

    // Overlay blend: 2 * base * overlay where base < 0.5, else 1 - 2*(1-base)*(1-overlay)
    vec3 grain = vec3(noise);
    vec3 result = mix(
        2.0 * color.rgb * grain,
        1.0 - 2.0 * (1.0 - color.rgb) * (1.0 - grain),
        step(0.5, color.rgb)
    );
    color.rgb = mix(color.rgb, result, u_intensity);

    gl_FragColor = color;
}
```

```json
// agents/shaders/nodes/noise_overlay.json
{
  "node_type": "noise_overlay",
  "glsl_fragment": "noise_overlay.frag",
  "inputs": { "in": "frame" },
  "outputs": { "out": "frame" },
  "params": {
    "intensity": { "type": "float", "default": 0.06, "min": 0.0, "max": 0.3, "description": "Grain strength" },
    "animated": { "type": "bool", "default": false, "description": "Regenerate grain each frame" },
    "blend_mode": { "type": "enum", "default": "overlay", "enum_values": ["overlay", "additive", "multiply"], "description": "How grain blends with image" }
  },
  "temporal": false
}
```

- [ ] **Step 7: Create blend compositing shader**

```glsl
// agents/shaders/nodes/blend.frag
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_texcoord;
uniform sampler2D tex;     // input A
uniform sampler2D tex_b;   // input B (second source)
uniform float u_alpha;     // 0-1, default 0.5
uniform float u_mode;      // 0=screen, 1=lighter, 2=multiply, 3=difference, 4=overlay, 5=soft_light, 6=hard_light

vec3 blend_screen(vec3 a, vec3 b) { return 1.0 - (1.0 - a) * (1.0 - b); }
vec3 blend_lighter(vec3 a, vec3 b) { return a + b; }
vec3 blend_multiply(vec3 a, vec3 b) { return a * b; }
vec3 blend_difference(vec3 a, vec3 b) { return abs(a - b); }
vec3 blend_overlay(vec3 a, vec3 b) {
    return mix(
        2.0 * a * b,
        1.0 - 2.0 * (1.0 - a) * (1.0 - b),
        step(0.5, a)
    );
}
vec3 blend_soft_light(vec3 a, vec3 b) {
    return mix(
        2.0 * a * b + a * a * (1.0 - 2.0 * b),
        sqrt(a) * (2.0 * b - 1.0) + 2.0 * a * (1.0 - b),
        step(0.5, b)
    );
}
vec3 blend_hard_light(vec3 a, vec3 b) {
    return mix(
        2.0 * a * b,
        1.0 - 2.0 * (1.0 - a) * (1.0 - b),
        step(0.5, b)
    );
}

void main() {
    vec4 a = texture2D(tex, v_texcoord);
    vec4 b = texture2D(tex_b, v_texcoord);

    vec3 blended;
    if (u_mode < 0.5) blended = blend_screen(a.rgb, b.rgb);
    else if (u_mode < 1.5) blended = blend_lighter(a.rgb, b.rgb);
    else if (u_mode < 2.5) blended = blend_multiply(a.rgb, b.rgb);
    else if (u_mode < 3.5) blended = blend_difference(a.rgb, b.rgb);
    else if (u_mode < 4.5) blended = blend_overlay(a.rgb, b.rgb);
    else if (u_mode < 5.5) blended = blend_soft_light(a.rgb, b.rgb);
    else blended = blend_hard_light(a.rgb, b.rgb);

    gl_FragColor = vec4(mix(a.rgb, blended, u_alpha), 1.0);
}
```

```json
// agents/shaders/nodes/blend.json
{
  "node_type": "blend",
  "glsl_fragment": "blend.frag",
  "inputs": { "a": "frame", "b": "frame" },
  "outputs": { "out": "frame" },
  "params": {
    "mode": { "type": "enum", "default": "screen", "enum_values": ["screen", "lighter", "multiply", "difference", "overlay", "soft_light", "hard_light"], "description": "Blend mode" },
    "alpha": { "type": "float", "default": 0.5, "min": 0.0, "max": 1.0, "description": "Mix amount" }
  },
  "temporal": false
}
```

- [ ] **Step 8: Create trail accumulator shader**

The trail node is temporal — it maintains an FBO that accumulates frames. The shader itself does the fade + composite in a single pass. The runtime handles the FBO ping-pong.

```glsl
// agents/shaders/nodes/trail.frag
#ifdef GL_ES
precision mediump float;
#endif

varying vec2 v_texcoord;
uniform sampler2D tex;           // current frame
uniform sampler2D tex_accum;     // accumulator FBO (previous frame's result)
uniform float u_fade;            // 0.001-0.2, how much to fade per frame
uniform float u_opacity;         // 0-1, new frame composite strength
uniform float u_blend_mode;      // 0=lighter, 1=screen, 2=multiply, 3=difference, 4=overlay
uniform float u_drift_x;         // 0-10, horizontal drift per frame
uniform float u_drift_y;         // 0-10, vertical drift per frame
uniform float u_time;
uniform float u_width;
uniform float u_height;

vec3 blend_lighter(vec3 a, vec3 b) { return a + b; }
vec3 blend_screen(vec3 a, vec3 b) { return 1.0 - (1.0 - a) * (1.0 - b); }
vec3 blend_multiply(vec3 a, vec3 b) { return a * b; }
vec3 blend_difference(vec3 a, vec3 b) { return abs(a - b); }
vec3 blend_overlay(vec3 a, vec3 b) {
    return mix(2.0 * a * b, 1.0 - 2.0 * (1.0 - a) * (1.0 - b), step(0.5, a));
}

void main() {
    // Read accumulated trails with drift offset
    float t = u_time * 0.015;
    float dx = u_drift_x * sin(t) * 0.15 / u_width;
    float dy = u_drift_y * cos(t * 0.7) * 0.15 / u_height;
    vec4 accum = texture2D(tex_accum, v_texcoord + vec2(dx, dy));

    // Fade existing trails
    accum.rgb *= (1.0 - u_fade);

    // Read current frame
    vec4 current = texture2D(tex, v_texcoord);

    // Blend current frame onto faded accumulator
    vec3 blended;
    if (u_blend_mode < 0.5) blended = blend_lighter(accum.rgb, current.rgb * u_opacity);
    else if (u_blend_mode < 1.5) blended = blend_screen(accum.rgb, current.rgb * u_opacity);
    else if (u_blend_mode < 2.5) blended = blend_multiply(accum.rgb, current.rgb * u_opacity);
    else if (u_blend_mode < 3.5) blended = blend_difference(accum.rgb, current.rgb * u_opacity);
    else blended = blend_overlay(accum.rgb, current.rgb * u_opacity);

    gl_FragColor = vec4(blended, 1.0);
}
```

```json
// agents/shaders/nodes/trail.json
{
  "node_type": "trail",
  "glsl_fragment": "trail.frag",
  "inputs": { "in": "frame" },
  "outputs": { "out": "frame" },
  "params": {
    "fade": { "type": "float", "default": 0.04, "min": 0.001, "max": 0.2, "description": "Trail fade per frame" },
    "blend_mode": { "type": "enum", "default": "lighter", "enum_values": ["lighter", "screen", "multiply", "difference", "overlay"], "description": "How new frames blend onto trail" },
    "opacity": { "type": "float", "default": 0.5, "min": 0.0, "max": 1.0, "description": "New frame composite strength" },
    "drift_x": { "type": "float", "default": 0.0, "min": 0.0, "max": 10.0, "description": "Horizontal drift per frame" },
    "drift_y": { "type": "float", "default": 0.0, "min": 0.0, "max": 10.0, "description": "Vertical drift per frame" }
  },
  "temporal": true,
  "temporal_buffers": 1
}
```

- [ ] **Step 9: Create stutter manifest (Python element, no GLSL)**

Stutter uses the existing `StutterElement` pattern from the compositor — it's a frame hold/replay mechanism implemented in Python, not GLSL.

```json
// agents/shaders/nodes/stutter.json
{
  "node_type": "stutter",
  "glsl_fragment": "",
  "inputs": { "in": "frame" },
  "outputs": { "out": "frame" },
  "params": {
    "check_interval": { "type": "int", "default": 20, "min": 5, "max": 60, "description": "Frames between freeze checks" },
    "freeze_chance": { "type": "float", "default": 0.15, "min": 0.0, "max": 0.5, "description": "Probability of freeze per check" },
    "freeze_min": { "type": "int", "default": 2, "min": 1, "max": 10, "description": "Minimum freeze duration (frames)" },
    "freeze_max": { "type": "int", "default": 5, "min": 2, "max": 20, "description": "Maximum freeze duration (frames)" },
    "replay_frames": { "type": "int", "default": 2, "min": 1, "max": 8, "description": "Frames to replay after freeze" }
  },
  "temporal": true,
  "temporal_buffers": 8
}
```

- [ ] **Step 10: Verify registry loads all manifests**

```python
# Quick validation — run in REPL or as a one-off test
# cd /home/hapax/projects/hapax-council
# uv run python -c "
from agents.effect_graph.registry import ShaderRegistry
from pathlib import Path
reg = ShaderRegistry(Path('agents/shaders/nodes'))
print('Loaded node types:', reg.node_types)
assert len(reg.node_types) >= 9, f'Expected >=9 nodes, got {reg.node_types}'
print('All manifests loaded successfully')
# "
```

- [ ] **Step 11: Commit all shader nodes**

```bash
cd /home/hapax/projects/hapax-council
git add agents/shaders/nodes/
git commit -m "feat(effect-graph): foundational shader nodes — colorgrade, trail, blend, bloom, scanlines, vignette, noise, stutter, output, palette"
```

---

## Task 5: JSON Preset Files

**Files:**
- Create: `presets/ghost.json`
- Create: `presets/trails.json`
- Create: `presets/clean.json`

- [ ] **Step 1: Create Ghost preset**

```json
// presets/ghost.json
{
  "name": "Ghost",
  "description": "Transparent echo — gentle motion trails with soft glow",
  "transition_ms": 500,
  "nodes": {
    "trail": {
      "type": "trail",
      "params": {
        "fade": 0.015,
        "blend_mode": "lighter",
        "opacity": 0.3,
        "drift_x": 0,
        "drift_y": 0
      }
    },
    "bloom": {
      "type": "bloom",
      "params": {
        "threshold": 0.4,
        "radius": 10.0,
        "alpha": 0.25
      }
    },
    "out": { "type": "output", "params": {} }
  },
  "edges": [
    ["@live", "trail"],
    ["trail", "bloom"],
    ["bloom", "out"]
  ],
  "modulations": [],
  "layer_palettes": {}
}
```

- [ ] **Step 2: Create Trails preset**

```json
// presets/trails.json
{
  "name": "Trails",
  "description": "Bright additive motion — heavy trail persistence with bloom",
  "transition_ms": 500,
  "nodes": {
    "trail": {
      "type": "trail",
      "params": {
        "fade": 0.008,
        "blend_mode": "lighter",
        "opacity": 0.5,
        "drift_x": 2,
        "drift_y": 1
      }
    },
    "bloom": {
      "type": "bloom",
      "params": {
        "threshold": 0.35,
        "radius": 12.0,
        "alpha": 0.35
      }
    },
    "grain": {
      "type": "noise_overlay",
      "params": {
        "intensity": 0.04,
        "animated": false
      }
    },
    "out": { "type": "output", "params": {} }
  },
  "edges": [
    ["@live", "trail"],
    ["trail", "bloom"],
    ["bloom", "grain"],
    ["grain", "out"]
  ],
  "modulations": [
    { "node": "trail", "param": "opacity", "source": "audio_rms", "scale": 0.3, "offset": 0.3, "smoothing": 0.85 },
    { "node": "bloom", "param": "alpha", "source": "audio_beat", "scale": 0.2, "offset": 0.25, "smoothing": 0.7 }
  ],
  "layer_palettes": {}
}
```

- [ ] **Step 3: Create Clean preset**

```json
// presets/clean.json
{
  "name": "Clean",
  "description": "Minimal processing — light color correction with subtle vignette",
  "transition_ms": 300,
  "nodes": {
    "color": {
      "type": "colorgrade",
      "params": {
        "saturation": 1.05,
        "brightness": 1.02,
        "contrast": 1.05,
        "sepia": 0.0,
        "hue_rotate": 0
      }
    },
    "vig": {
      "type": "vignette",
      "params": {
        "strength": 0.15,
        "radius": 0.8,
        "softness": 0.3
      }
    },
    "out": { "type": "output", "params": {} }
  },
  "edges": [
    ["@live", "color"],
    ["color", "vig"],
    ["vig", "out"]
  ],
  "modulations": [],
  "layer_palettes": {}
}
```

- [ ] **Step 4: Write test that presets parse correctly**

```python
# tests/effect_graph/test_presets.py
"""Tests that preset JSON files parse into valid EffectGraph models."""

import json
from pathlib import Path

import pytest

from agents.effect_graph.types import EffectGraph

PRESETS_DIR = Path(__file__).parent.parent.parent / "presets"


def _load_preset(name: str) -> EffectGraph:
    path = PRESETS_DIR / f"{name}.json"
    raw = json.loads(path.read_text())
    return EffectGraph(**raw)


def test_ghost_preset():
    g = _load_preset("ghost")
    assert g.name == "Ghost"
    assert "trail" in g.nodes
    assert "bloom" in g.nodes
    assert "out" in g.nodes
    assert len(g.edges) == 3


def test_trails_preset():
    g = _load_preset("trails")
    assert g.name == "Trails"
    assert len(g.modulations) == 2
    assert g.modulations[0].source == "audio_rms"


def test_clean_preset():
    g = _load_preset("clean")
    assert g.name == "Clean"
    assert "color" in g.nodes
    assert g.nodes["color"].params["saturation"] == 1.05
```

- [ ] **Step 5: Run tests**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/effect_graph/test_presets.py -v`
Expected: All 3 tests PASS

- [ ] **Step 6: Commit**

```bash
cd /home/hapax/projects/hapax-council
git add presets/ tests/effect_graph/test_presets.py
git commit -m "feat(effect-graph): ghost, trails, clean preset JSON files"
```

---

## Task 6: Uniform Modulator

**Files:**
- Create: `agents/effect_graph/modulator.py`
- Create: `tests/effect_graph/test_modulator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/effect_graph/test_modulator.py
"""Tests for uniform modulation system."""

import pytest

from agents.effect_graph.modulator import UniformModulator
from agents.effect_graph.types import ModulationBinding


def test_modulator_register_binding():
    mod = UniformModulator()
    binding = ModulationBinding(
        node="bloom", param="alpha", source="audio_rms", scale=0.4, offset=0.2
    )
    mod.add_binding(binding)
    assert len(mod.bindings) == 1


def test_modulator_tick_with_signal():
    mod = UniformModulator()
    mod.add_binding(
        ModulationBinding(
            node="bloom",
            param="alpha",
            source="audio_rms",
            scale=1.0,
            offset=0.0,
            smoothing=0.0,  # No smoothing for test predictability
        )
    )

    signals = {"audio_rms": 0.8}
    updates = mod.tick(signals)

    assert ("bloom", "alpha") in updates
    assert updates[("bloom", "alpha")] == pytest.approx(0.8, abs=0.01)


def test_modulator_scale_and_offset():
    mod = UniformModulator()
    mod.add_binding(
        ModulationBinding(
            node="color",
            param="saturation",
            source="stimmung_arousal",
            scale=0.5,
            offset=0.7,
            smoothing=0.0,
        )
    )

    signals = {"stimmung_arousal": 0.6}
    updates = mod.tick(signals)

    # value = signal * scale + offset = 0.6 * 0.5 + 0.7 = 1.0
    assert updates[("color", "saturation")] == pytest.approx(1.0, abs=0.01)


def test_modulator_smoothing():
    mod = UniformModulator()
    mod.add_binding(
        ModulationBinding(
            node="bloom",
            param="alpha",
            source="audio_rms",
            scale=1.0,
            offset=0.0,
            smoothing=0.5,
        )
    )

    # First tick: no previous value, use raw
    updates1 = mod.tick({"audio_rms": 1.0})
    val1 = updates1[("bloom", "alpha")]

    # Second tick: smoothing pulls toward new value
    updates2 = mod.tick({"audio_rms": 0.0})
    val2 = updates2[("bloom", "alpha")]

    # With smoothing=0.5: new_val = 0.5 * prev + 0.5 * target
    # val2 should be ~0.5 * val1 + 0.5 * 0.0
    assert val2 < val1
    assert val2 > 0.0


def test_modulator_missing_signal():
    """Missing signals should not produce updates."""
    mod = UniformModulator()
    mod.add_binding(
        ModulationBinding(
            node="bloom", param="alpha", source="nonexistent", scale=1.0, offset=0.0
        )
    )

    updates = mod.tick({"audio_rms": 0.5})
    assert ("bloom", "alpha") not in updates


def test_modulator_remove_binding():
    mod = UniformModulator()
    mod.add_binding(
        ModulationBinding(
            node="bloom", param="alpha", source="audio_rms", scale=1.0, offset=0.0
        )
    )
    assert len(mod.bindings) == 1

    mod.remove_binding("bloom", "alpha")
    assert len(mod.bindings) == 0


def test_modulator_replace_all():
    mod = UniformModulator()
    mod.add_binding(
        ModulationBinding(
            node="bloom", param="alpha", source="audio_rms", scale=1.0, offset=0.0
        )
    )
    mod.replace_all(
        [
            ModulationBinding(
                node="color", param="saturation", source="audio_beat", scale=0.5, offset=0.5
            )
        ]
    )
    assert len(mod.bindings) == 1
    assert mod.bindings[0].node == "color"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/effect_graph/test_modulator.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the modulator**

```python
# agents/effect_graph/modulator.py
"""Uniform modulation — binds node parameters to perceptual signal sources."""

from __future__ import annotations

import logging
from typing import Any

from .types import ModulationBinding

log = logging.getLogger(__name__)


class UniformModulator:
    """Drives shader uniforms from perceptual signals (audio, stimmung, flow, biometrics)."""

    def __init__(self) -> None:
        self._bindings: list[ModulationBinding] = []
        self._smoothed: dict[tuple[str, str], float] = {}  # (node, param) → smoothed value

    @property
    def bindings(self) -> list[ModulationBinding]:
        return list(self._bindings)

    def add_binding(self, binding: ModulationBinding) -> None:
        # Replace if same (node, param) already bound
        self._bindings = [
            b for b in self._bindings
            if not (b.node == binding.node and b.param == binding.param)
        ]
        self._bindings.append(binding)

    def remove_binding(self, node: str, param: str) -> None:
        self._bindings = [
            b for b in self._bindings
            if not (b.node == node and b.param == param)
        ]
        self._smoothed.pop((node, param), None)

    def replace_all(self, bindings: list[ModulationBinding]) -> None:
        self._bindings = list(bindings)
        self._smoothed.clear()

    def tick(self, signals: dict[str, float]) -> dict[tuple[str, str], float]:
        """Process one frame tick. Returns {(node_id, param_name): value} for all active bindings."""
        updates: dict[tuple[str, str], float] = {}

        for binding in self._bindings:
            raw_signal = signals.get(binding.source)
            if raw_signal is None:
                continue

            target = raw_signal * binding.scale + binding.offset
            key = (binding.node, binding.param)

            prev = self._smoothed.get(key)
            if prev is None or binding.smoothing == 0.0:
                smoothed = target
            else:
                smoothed = binding.smoothing * prev + (1.0 - binding.smoothing) * target

            self._smoothed[key] = smoothed
            updates[key] = smoothed

        return updates
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/effect_graph/test_modulator.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Lint and commit**

```bash
cd /home/hapax/projects/hapax-council
uv run ruff check agents/effect_graph/ tests/effect_graph/ --fix && uv run ruff format agents/effect_graph/ tests/effect_graph/
git add agents/effect_graph/modulator.py tests/effect_graph/test_modulator.py
git commit -m "feat(effect-graph): uniform modulation system with signal bindings"
```

---

## Task 7: Graph Runtime (Mutation Levels + GStreamer Integration)

**Files:**
- Create: `agents/effect_graph/runtime.py`
- Create: `tests/effect_graph/test_runtime.py`

This is the core integration task. The runtime manages the live graph, handles the three mutation levels, and constructs GStreamer element chains.

- [ ] **Step 1: Write failing tests for runtime state management**

Note: GStreamer pipeline tests require `gi` and a display, so we test the state management and compilation logic, mocking GStreamer calls.

```python
# tests/effect_graph/test_runtime.py
"""Tests for graph runtime — state management and mutation levels."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agents.effect_graph.compiler import GraphCompiler
from agents.effect_graph.modulator import UniformModulator
from agents.effect_graph.registry import ShaderRegistry
from agents.effect_graph.runtime import GraphRuntime
from agents.effect_graph.types import EffectGraph, GraphPatch, LayerPalette, NodeInstance


@pytest.fixture
def registry(tmp_path: Path) -> ShaderRegistry:
    nodes_dir = tmp_path / "nodes"
    nodes_dir.mkdir()
    for node_type, inputs, outputs, temporal in [
        ("colorgrade", {"in": "frame"}, {"out": "frame"}, False),
        ("trail", {"in": "frame"}, {"out": "frame"}, True),
        ("bloom", {"in": "frame"}, {"out": "frame"}, False),
        ("scanlines", {"in": "frame"}, {"out": "frame"}, False),
        ("vignette", {"in": "frame"}, {"out": "frame"}, False),
        ("noise_overlay", {"in": "frame"}, {"out": "frame"}, False),
        ("output", {"in": "frame"}, {}, False),
    ]:
        manifest = {
            "node_type": node_type,
            "glsl_fragment": "",
            "inputs": inputs,
            "outputs": outputs,
            "params": {},
            "temporal": temporal,
            "temporal_buffers": 1 if temporal else 0,
        }
        (nodes_dir / f"{node_type}.json").write_text(json.dumps(manifest))
    return ShaderRegistry(nodes_dir)


@pytest.fixture
def runtime(registry: ShaderRegistry) -> GraphRuntime:
    compiler = GraphCompiler(registry)
    modulator = UniformModulator()
    return GraphRuntime(registry=registry, compiler=compiler, modulator=modulator)


def test_runtime_initial_state(runtime: GraphRuntime):
    assert runtime.current_graph is None
    assert runtime.current_plan is None


def test_runtime_load_graph(runtime: GraphRuntime):
    graph = EffectGraph(
        name="test",
        nodes={
            "color": NodeInstance(type="colorgrade"),
            "out": NodeInstance(type="output"),
        },
        edges=[["@live", "color"], ["color", "out"]],
    )
    runtime.load_graph(graph)
    assert runtime.current_graph is not None
    assert runtime.current_graph.name == "test"
    assert runtime.current_plan is not None


def test_runtime_patch_params(runtime: GraphRuntime):
    graph = EffectGraph(
        name="test",
        nodes={
            "color": NodeInstance(type="colorgrade", params={"saturation": 1.0}),
            "out": NodeInstance(type="output"),
        },
        edges=[["@live", "color"], ["color", "out"]],
    )
    runtime.load_graph(graph)
    runtime.patch_node_params("color", {"saturation": 0.5})
    assert runtime.current_graph.nodes["color"].params["saturation"] == 0.5


def test_runtime_topology_mutation(runtime: GraphRuntime):
    graph = EffectGraph(
        name="test",
        nodes={
            "color": NodeInstance(type="colorgrade"),
            "out": NodeInstance(type="output"),
        },
        edges=[["@live", "color"], ["color", "out"]],
    )
    runtime.load_graph(graph)

    patch = GraphPatch(
        add_nodes={"bloom": NodeInstance(type="bloom", params={"threshold": 0.5})},
        add_edges=[["color", "bloom"], ["bloom", "out"]],
        remove_edges=[["color", "out"]],
    )
    runtime.apply_patch(patch)

    assert "bloom" in runtime.current_graph.nodes
    # New edges should include color→bloom and bloom→out
    flat_edges = runtime.current_graph.edges
    assert ["color", "bloom"] in flat_edges
    assert ["bloom", "out"] in flat_edges
    # Old color→out edge should be gone
    assert ["color", "out"] not in flat_edges


def test_runtime_remove_node(runtime: GraphRuntime):
    graph = EffectGraph(
        name="test",
        nodes={
            "color": NodeInstance(type="colorgrade"),
            "scan": NodeInstance(type="scanlines"),
            "out": NodeInstance(type="output"),
        },
        edges=[["@live", "color"], ["color", "scan"], ["scan", "out"]],
    )
    runtime.load_graph(graph)

    patch = GraphPatch(
        remove_nodes=["scan"],
        add_edges=[["color", "out"]],
        remove_edges=[["color", "scan"], ["scan", "out"]],
    )
    runtime.apply_patch(patch)

    assert "scan" not in runtime.current_graph.nodes
    assert ["color", "out"] in runtime.current_graph.edges


def test_runtime_layer_palette(runtime: GraphRuntime):
    runtime.set_layer_palette("live", LayerPalette(saturation=0.5, hue_rotate=-10))
    palette = runtime.get_layer_palette("live")
    assert palette.saturation == 0.5
    assert palette.hue_rotate == -10


def test_runtime_modulations_from_graph(runtime: GraphRuntime):
    from agents.effect_graph.types import ModulationBinding

    graph = EffectGraph(
        name="test",
        nodes={
            "color": NodeInstance(type="colorgrade"),
            "out": NodeInstance(type="output"),
        },
        edges=[["@live", "color"], ["color", "out"]],
        modulations=[
            ModulationBinding(
                node="color", param="saturation", source="audio_rms", scale=0.3, offset=0.7
            )
        ],
    )
    runtime.load_graph(graph)
    assert len(runtime.modulator.bindings) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/effect_graph/test_runtime.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the runtime**

```python
# agents/effect_graph/runtime.py
"""Graph runtime — manages the live effect graph and its mutations."""

from __future__ import annotations

import copy
import logging
from typing import Any

from .compiler import ExecutionPlan, GraphCompiler
from .modulator import UniformModulator
from .registry import ShaderRegistry
from .types import EffectGraph, GraphPatch, LayerPalette, NodeInstance

log = logging.getLogger(__name__)


class GraphRuntime:
    """Manages the live effect graph. Handles param patches, topology diffs, and full replaces."""

    def __init__(
        self,
        registry: ShaderRegistry,
        compiler: GraphCompiler,
        modulator: UniformModulator,
    ) -> None:
        self._registry = registry
        self._compiler = compiler
        self._modulator = modulator
        self._current_graph: EffectGraph | None = None
        self._current_plan: ExecutionPlan | None = None
        self._layer_palettes: dict[str, LayerPalette] = {
            "live": LayerPalette(),
            "smooth": LayerPalette(),
            "hls": LayerPalette(),
        }
        # GStreamer integration hooks — set by compositor
        self._on_plan_changed: Any = None  # callback(old_plan, new_plan)
        self._on_params_changed: Any = None  # callback(node_id, params)

    @property
    def current_graph(self) -> EffectGraph | None:
        return self._current_graph

    @property
    def current_plan(self) -> ExecutionPlan | None:
        return self._current_plan

    @property
    def modulator(self) -> UniformModulator:
        return self._modulator

    def load_graph(self, graph: EffectGraph) -> None:
        """Full graph replace (Level 3 mutation)."""
        old_plan = self._current_plan
        plan = self._compiler.compile(graph)
        self._current_graph = copy.deepcopy(graph)
        self._current_plan = plan

        # Apply modulations from graph
        self._modulator.replace_all(list(graph.modulations))

        # Apply layer palettes from graph
        for layer_name, palette in graph.layer_palettes.items():
            if layer_name in self._layer_palettes:
                self._layer_palettes[layer_name] = palette

        if self._on_plan_changed:
            self._on_plan_changed(old_plan, plan)

        log.info("Loaded graph '%s' with %d nodes", graph.name, len(graph.nodes))

    def patch_node_params(self, node_id: str, params: dict[str, Any]) -> None:
        """Parameter patch (Level 1 mutation — zero-cost, no pipeline rebuild)."""
        if self._current_graph is None:
            log.warning("No graph loaded — ignoring param patch for %s", node_id)
            return

        node = self._current_graph.nodes.get(node_id)
        if node is None:
            log.warning("Node '%s' not found in graph", node_id)
            return

        node.params.update(params)

        if self._on_params_changed:
            self._on_params_changed(node_id, node.params)

    def apply_patch(self, patch: GraphPatch) -> None:
        """Topology mutation (Level 2 mutation — lightweight rebuild)."""
        if self._current_graph is None:
            log.warning("No graph loaded — ignoring topology patch")
            return

        graph = copy.deepcopy(self._current_graph)

        # Remove nodes
        for node_id in patch.remove_nodes:
            graph.nodes.pop(node_id, None)

        # Add nodes
        for node_id, node in patch.add_nodes.items():
            graph.nodes[node_id] = node

        # Remove edges
        for edge in patch.remove_edges:
            if edge in graph.edges:
                graph.edges.remove(edge)

        # Add edges
        for edge in patch.add_edges:
            graph.edges.append(edge)

        # Recompile and apply
        old_plan = self._current_plan
        plan = self._compiler.compile(graph)
        self._current_graph = graph
        self._current_plan = plan

        if self._on_plan_changed:
            self._on_plan_changed(old_plan, plan)

        log.info(
            "Applied topology patch: +%d/-%d nodes, +%d/-%d edges",
            len(patch.add_nodes),
            len(patch.remove_nodes),
            len(patch.add_edges),
            len(patch.remove_edges),
        )

    def remove_node(self, node_id: str) -> None:
        """Remove a node and all its edges."""
        if self._current_graph is None:
            return

        # Find and remove all edges involving this node
        edges_to_remove = [
            e for e in self._current_graph.edges
            if node_id in e
        ]
        patch = GraphPatch(
            remove_nodes=[node_id],
            remove_edges=edges_to_remove,
        )
        self.apply_patch(patch)

    def set_layer_palette(self, layer: str, palette: LayerPalette) -> None:
        if layer in self._layer_palettes:
            self._layer_palettes[layer] = palette

    def get_layer_palette(self, layer: str) -> LayerPalette:
        return self._layer_palettes.get(layer, LayerPalette())

    def get_graph_state(self) -> dict[str, Any]:
        """Export current state for the API."""
        if self._current_graph is None:
            return {"graph": None, "layer_palettes": {}, "modulations": []}
        return {
            "graph": self._current_graph.model_dump(),
            "layer_palettes": {
                k: v.model_dump() for k, v in self._layer_palettes.items()
            },
            "modulations": [b.model_dump() for b in self._modulator.bindings],
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/effect_graph/test_runtime.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Lint and commit**

```bash
cd /home/hapax/projects/hapax-council
uv run ruff check agents/effect_graph/ tests/effect_graph/ --fix && uv run ruff format agents/effect_graph/ tests/effect_graph/
git add agents/effect_graph/runtime.py tests/effect_graph/test_runtime.py
git commit -m "feat(effect-graph): graph runtime with three mutation levels"
```

---

## Task 8: API Routes

**Files:**
- Modify: `logos/api/routes/studio.py`

- [ ] **Step 1: Read the current studio routes file**

Read `logos/api/routes/studio.py` to understand the existing router structure, imports, and patterns.

- [ ] **Step 2: Add graph management routes**

Add these new routes to the existing `studio.py` router, following the existing patterns (FastAPI router, Pydantic models for request/response, error handling):

```python
# Add to logos/api/routes/studio.py — new imports at top
from agents.effect_graph.types import (
    EffectGraph,
    GraphPatch,
    LayerPalette,
    ModulationBinding,
    NodeInstance,
)

# --- Graph Management ---

@router.get("/studio/effect/graph")
async def get_effect_graph():
    """Current graph state (nodes, edges, params, modulations)."""
    runtime = _get_graph_runtime()
    if runtime is None:
        return {"graph": None}
    return runtime.get_graph_state()


@router.put("/studio/effect/graph")
async def replace_effect_graph(graph: EffectGraph):
    """Full graph replace (preset switch)."""
    runtime = _get_graph_runtime()
    if runtime is None:
        raise HTTPException(503, "Compositor not available")
    try:
        runtime.load_graph(graph)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"status": "ok", "name": graph.name}


@router.patch("/studio/effect/graph")
async def patch_effect_graph(patch: GraphPatch):
    """Topology mutation (add/remove nodes/edges)."""
    runtime = _get_graph_runtime()
    if runtime is None:
        raise HTTPException(503, "Compositor not available")
    try:
        runtime.apply_patch(patch)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"status": "ok"}


@router.patch("/studio/effect/graph/node/{node_id}/params")
async def patch_node_params(node_id: str, params: dict[str, Any]):
    """Parameter patch (zero-cost, no pipeline rebuild)."""
    runtime = _get_graph_runtime()
    if runtime is None:
        raise HTTPException(503, "Compositor not available")
    runtime.patch_node_params(node_id, params)
    return {"status": "ok"}


@router.delete("/studio/effect/graph/node/{node_id}")
async def remove_graph_node(node_id: str):
    """Remove node and its edges."""
    runtime = _get_graph_runtime()
    if runtime is None:
        raise HTTPException(503, "Compositor not available")
    runtime.remove_node(node_id)
    return {"status": "ok"}


# --- Layer Control ---

@router.patch("/studio/layer/{layer}/palette")
async def set_layer_palette(layer: str, palette: LayerPalette):
    """Per-layer color grade."""
    if layer not in ("live", "smooth", "hls"):
        raise HTTPException(400, f"Invalid layer: {layer}")
    runtime = _get_graph_runtime()
    if runtime is None:
        raise HTTPException(503, "Compositor not available")
    runtime.set_layer_palette(layer, palette)
    return {"status": "ok"}


@router.get("/studio/layer/status")
async def get_layer_status():
    """Layer status (fps, resolution, palette)."""
    runtime = _get_graph_runtime()
    palettes = {}
    if runtime:
        for layer in ("live", "smooth", "hls"):
            palettes[layer] = runtime.get_layer_palette(layer).model_dump()
    return {"layers": palettes}


# --- Modulation ---

@router.put("/studio/effect/graph/modulations")
async def replace_modulations(bindings: list[ModulationBinding]):
    """Replace all modulation bindings."""
    runtime = _get_graph_runtime()
    if runtime is None:
        raise HTTPException(503, "Compositor not available")
    runtime.modulator.replace_all(bindings)
    return {"status": "ok"}


@router.patch("/studio/effect/graph/modulations")
async def patch_modulations(
    add: list[ModulationBinding] | None = None,
    remove: list[dict[str, str]] | None = None,
):
    """Add/remove individual bindings."""
    runtime = _get_graph_runtime()
    if runtime is None:
        raise HTTPException(503, "Compositor not available")
    if remove:
        for r in remove:
            runtime.modulator.remove_binding(r["node"], r["param"])
    if add:
        for binding in add:
            runtime.modulator.add_binding(binding)
    return {"status": "ok"}


@router.get("/studio/effect/graph/modulations")
async def get_modulations():
    """Current bindings."""
    runtime = _get_graph_runtime()
    if runtime is None:
        return {"bindings": []}
    return {"bindings": [b.model_dump() for b in runtime.modulator.bindings]}


# --- Presets ---

_PRESETS_DIR = Path.home() / ".config" / "hapax" / "effect-presets"
_BUILTIN_PRESETS_DIR = Path(__file__).parent.parent.parent.parent / "presets"


def _load_preset(name: str) -> EffectGraph | None:
    """Load a preset from user dir, falling back to built-in."""
    for dir_ in (_PRESETS_DIR, _BUILTIN_PRESETS_DIR):
        path = dir_ / f"{name}.json"
        if path.is_file():
            import json
            raw = json.loads(path.read_text())
            return EffectGraph(**raw)
    return None


def _list_presets() -> list[dict[str, str]]:
    """List available presets (user + built-in, deduplicated)."""
    import json
    seen = set()
    result = []
    for dir_ in (_PRESETS_DIR, _BUILTIN_PRESETS_DIR):
        if not dir_.is_dir():
            continue
        for path in sorted(dir_.glob("*.json")):
            name = path.stem
            if name in seen:
                continue
            seen.add(name)
            try:
                raw = json.loads(path.read_text())
                result.append({
                    "name": name,
                    "display_name": raw.get("name", name),
                    "description": raw.get("description", ""),
                })
            except Exception:
                pass
    return result


@router.get("/studio/presets")
async def list_presets():
    return {"presets": _list_presets()}


@router.get("/studio/presets/{name}")
async def get_preset(name: str):
    preset = _load_preset(name)
    if preset is None:
        raise HTTPException(404, f"Preset not found: {name}")
    return preset.model_dump()


@router.put("/studio/presets/{name}")
async def save_preset(name: str, graph: EffectGraph):
    """Save current graph as preset."""
    import json
    _PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    path = _PRESETS_DIR / f"{name}.json"
    path.write_text(json.dumps(graph.model_dump(), indent=2))
    return {"status": "ok", "path": str(path)}


@router.delete("/studio/presets/{name}")
async def delete_preset(name: str):
    path = _PRESETS_DIR / f"{name}.json"
    if path.is_file():
        path.unlink()
        return {"status": "ok"}
    raise HTTPException(404, f"Preset not found: {name}")


@router.post("/studio/presets/{name}/activate")
async def activate_preset(name: str):
    """Load preset (full graph replace with crossfade)."""
    preset = _load_preset(name)
    if preset is None:
        raise HTTPException(404, f"Preset not found: {name}")
    runtime = _get_graph_runtime()
    if runtime is None:
        raise HTTPException(503, "Compositor not available")
    try:
        runtime.load_graph(preset)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"status": "ok", "name": preset.name}


# --- Node Registry ---

@router.get("/studio/effect/nodes")
async def list_node_types():
    """All registered node types with schemas."""
    registry = _get_shader_registry()
    if registry is None:
        return {"nodes": {}}
    return {"nodes": registry.all_schemas()}


@router.get("/studio/effect/nodes/{node_type}")
async def get_node_type(node_type: str):
    """Single node type schema."""
    registry = _get_shader_registry()
    if registry is None:
        raise HTTPException(503, "Registry not available")
    schema = registry.schema(node_type)
    if schema is None:
        raise HTTPException(404, f"Unknown node type: {node_type}")
    return schema
```

The `_get_graph_runtime()` and `_get_shader_registry()` helper functions access the runtime and registry instances from the compositor. These are set during compositor startup and stored as module-level references (same pattern as the existing `_compositor_status()` helper).

```python
# Module-level references set during compositor startup
_graph_runtime: GraphRuntime | None = None
_shader_registry: ShaderRegistry | None = None


def set_graph_runtime(runtime: GraphRuntime) -> None:
    global _graph_runtime
    _graph_runtime = runtime


def set_shader_registry(registry: ShaderRegistry) -> None:
    global _shader_registry
    _shader_registry = registry


def _get_graph_runtime() -> GraphRuntime | None:
    return _graph_runtime


def _get_shader_registry() -> ShaderRegistry | None:
    return _shader_registry
```

- [ ] **Step 3: Lint and commit**

```bash
cd /home/hapax/projects/hapax-council
uv run ruff check logos/api/routes/studio.py --fix && uv run ruff format logos/api/routes/studio.py
git add logos/api/routes/studio.py
git commit -m "feat(effect-graph): API routes for graph, layers, modulation, presets, node registry"
```

---

## Task 9: Compositor Integration

**Files:**
- Modify: `agents/studio_compositor.py`

This is the most delicate task — wiring the new runtime into the existing compositor without breaking HLS, snapshots, recording, or overlays.

- [ ] **Step 1: Read the compositor's `_add_effects_branch` and `_fx_tick_callback` methods**

Read `agents/studio_compositor.py` lines 679–1006 (`_add_effects_branch`) and lines 1799–1982 (`_fx_tick_callback`) to understand the exact integration points.

- [ ] **Step 2: Add graph runtime initialization to compositor startup**

In `StudioCompositor.__init__()`, after existing initialization:

```python
# Effect node graph system
from agents.effect_graph.registry import ShaderRegistry
from agents.effect_graph.compiler import GraphCompiler
from agents.effect_graph.runtime import GraphRuntime
from agents.effect_graph.modulator import UniformModulator

shader_nodes_dir = Path(__file__).parent / "shaders" / "nodes"
self._shader_registry = ShaderRegistry(shader_nodes_dir)
self._graph_compiler = GraphCompiler(self._shader_registry)
self._graph_modulator = UniformModulator()
self._graph_runtime = GraphRuntime(
    registry=self._shader_registry,
    compiler=self._graph_compiler,
    modulator=self._graph_modulator,
)

# Wire runtime callbacks for GStreamer integration
self._graph_runtime._on_plan_changed = self._on_graph_plan_changed
self._graph_runtime._on_params_changed = self._on_graph_params_changed

# Expose to API routes
from logos.api.routes.studio import set_graph_runtime, set_shader_registry
set_graph_runtime(self._graph_runtime)
set_shader_registry(self._shader_registry)
```

- [ ] **Step 3: Implement `_on_graph_plan_changed` callback**

This is called when the graph topology changes (Level 2 or 3 mutation). It rebuilds the GStreamer FX element chain.

```python
def _on_graph_plan_changed(self, old_plan, new_plan):
    """Rebuild the GStreamer FX element chain from the new execution plan.

    For Phase 1: simple rebuild — tear down old chain, build new one.
    Crossfade engine comes in a later phase.
    """
    if new_plan is None:
        return

    # For now: update all shader uniforms to match new plan
    # Full pipeline rebuild requires GStreamer pipeline manipulation
    # which will be implemented when we replace _add_effects_branch
    for step in new_plan.steps:
        if step.shader_source and step.node_id in self._fx_shader_elements:
            self._update_shader_uniforms(step.node_id, step.params)

    log.info("Graph plan changed: %d steps", len(new_plan.steps))
```

- [ ] **Step 4: Implement `_on_graph_params_changed` callback**

This is called for Level 1 mutations (param patches). It updates GStreamer shader uniforms directly.

```python
def _on_graph_params_changed(self, node_id: str, params: dict):
    """Update shader uniforms for a single node (Level 1 mutation)."""
    element = self._fx_shader_elements.get(node_id)
    if element is None:
        return

    # Build GstStructure from params
    parts = []
    for key, value in params.items():
        if isinstance(value, bool):
            parts.append(f"u_{key}=(float){1.0 if value else 0.0}")
        elif isinstance(value, (int, float)):
            parts.append(f"u_{key}=(float){float(value)}")

    if parts:
        uniforms_str = "uniforms, " + ", ".join(parts)
        uniforms = Gst.Structure.from_string(uniforms_str)
        if uniforms and uniforms[0]:
            element.set_property("uniforms", uniforms[0])
```

- [ ] **Step 5: Replace `_fx_tick_callback` with modulator-driven updates**

Replace the hardcoded beat-reactive code with the uniform modulator:

```python
def _fx_tick_callback(self) -> bool:
    """30 Hz tick — reads perceptual signals, drives modulator, updates shader uniforms."""
    if not self._running:
        return False

    self._fx_tick += 1
    t = self._fx_tick * 0.04

    # Read perceptual signals
    with self._overlay_state._lock:
        energy = self._overlay_state._data.audio_energy_rms

    beat = min(energy * 4.0, 1.0)
    self._fx_beat_smooth = max(beat, self._fx_beat_smooth * 0.85)

    # Build signal dict for modulator
    signals = {
        "audio_rms": energy,
        "audio_beat": self._fx_beat_smooth,
        "time": t,
    }

    # Add stimmung/flow if available
    data = self._overlay_state._data
    if data.flow_score > 0:
        signals["flow_score"] = data.flow_score
    if data.emotion_valence != 0:
        signals["stimmung_valence"] = data.emotion_valence
    if data.emotion_arousal != 0:
        signals["stimmung_arousal"] = data.emotion_arousal

    # Tick modulator — get uniform updates
    updates = self._graph_modulator.tick(signals)

    # Apply updates to GStreamer elements
    for (node_id, param), value in updates.items():
        self._on_graph_params_changed(node_id, {param: value})

    # Always update time uniform on all shaders
    for node_id, element in self._fx_shader_elements.items():
        try:
            current = element.get_property("uniforms")
            if current:
                current.set_value("u_time", float(t))
                element.set_property("uniforms", current)
        except Exception:
            pass

    return True  # Keep the timeout active
```

- [ ] **Step 6: Add preset activation via file-based IPC**

Modify the existing `fx-request.txt` watcher to also support graph-based presets:

```python
def _check_fx_request(self) -> None:
    """Check for preset change requests (file-based IPC from API)."""
    request_path = Path("/dev/shm/hapax-compositor/fx-request.txt")
    if not request_path.exists():
        return

    try:
        name = request_path.read_text().strip()
        request_path.unlink()
    except Exception:
        return

    if not name:
        return

    # Try graph-based preset first (check built-in presets dir)
    import json as _json
    presets_dir = Path(__file__).parent / ".." / "presets"
    user_presets_dir = Path.home() / ".config" / "hapax" / "effect-presets"
    preset = None
    for d in (user_presets_dir, presets_dir.resolve()):
        p = d / f"{name}.json"
        if p.is_file():
            raw = _json.loads(p.read_text())
            from agents.effect_graph.types import EffectGraph
            preset = EffectGraph(**raw)
            break
    if preset:
        self._graph_runtime.load_graph(preset)
        self._fx_active_preset = name
        log.info("Activated graph preset: %s", name)
        return

    # Fall back to legacy preset system
    if name in PRESETS:
        self._switch_fx_preset(name)
```

- [ ] **Step 7: Commit**

```bash
cd /home/hapax/projects/hapax-council
git add agents/studio_compositor.py
git commit -m "feat(effect-graph): wire graph runtime into compositor — modulator, param callbacks, preset activation"
```

---

## Task 10: Frontend Simplification

**Files:**
- Delete: `hapax-logos/src/components/studio/CompositeCanvas.tsx`
- Delete: `hapax-logos/src/components/studio/compositePresets.ts`
- Delete: `hapax-logos/src/components/studio/compositeFilters.ts`
- Delete: `hapax-logos/src/hooks/useImagePool.ts`
- Modify: `hapax-logos/src/components/terrain/ground/CameraHero.tsx`
- Modify: `hapax-logos/src/components/terrain/ground/StudioDetailPane.tsx`
- Modify: `hapax-logos/src/contexts/GroundStudioContext.tsx`

- [ ] **Step 1: Read the current CameraHero component**

Read `hapax-logos/src/components/terrain/ground/CameraHero.tsx` to understand how it orchestrates CompositeCanvas and HLS.

- [ ] **Step 2: Simplify CameraHero to HLS + snapshot display**

Replace the composite canvas integration with a simple image display. The HLS player remains. The snapshot `<img>` becomes the fallback.

The core change: remove all `CompositeCanvas` imports and usage. Remove `compositeMode` logic. The display is either HLS (primary) or a polling `<img>` (fallback).

```tsx
// Simplified CameraHero — delete CompositeCanvas references, keep HLS player
// Remove: import { CompositeCanvas } from "../../studio/CompositeCanvas"
// Remove: compositeMode state and logic
// Keep: HlsPlayer component
// Add: Simple snapshot <img> as fallback when HLS unavailable

function SnapshotFallback({ role }: { role: string }) {
  const [src, setSrc] = useState("");

  useEffect(() => {
    let running = true;
    const poll = () => {
      if (!running) return;
      setSrc(`/api/studio/stream/snapshot?_t=${Date.now()}`);
      setTimeout(poll, 100); // 10fps polling
    };
    poll();
    return () => { running = false; };
  }, [role]);

  return <img src={src} className="h-full w-full object-contain bg-black" alt="" />;
}
```

- [ ] **Step 3: Rewire StudioDetailPane preset selector to new API**

Replace the frontend preset index state with API calls:

```tsx
// Before: setPresetIdx(i) which updated GroundStudioContext
// After: fetch("/api/studio/presets/{name}/activate", { method: "POST" })

const activatePreset = async (name: string) => {
  await fetch(`/api/studio/presets/${name}/activate`, { method: "POST" });
};
```

- [ ] **Step 4: Delete obsolete files**

```bash
cd /home/hapax/projects/hapax-council
rm hapax-logos/src/components/studio/CompositeCanvas.tsx
rm hapax-logos/src/components/studio/compositePresets.ts
rm hapax-logos/src/components/studio/compositeFilters.ts
rm hapax-logos/src/hooks/useImagePool.ts
```

- [ ] **Step 5: Verify the frontend builds**

Run: `cd /home/hapax/projects/hapax-council/hapax-logos && npx tsc --noEmit`
Expected: No type errors. Fix any import references to deleted files.

- [ ] **Step 6: Commit**

```bash
cd /home/hapax/projects/hapax-council
git add -A hapax-logos/
git commit -m "feat(effect-graph): simplify frontend to HLS + snapshot display, delete CompositeCanvas"
```

---

## Task 11: Integration Test and Verification

- [ ] **Step 1: Run all unit tests**

Run: `cd /home/hapax/projects/hapax-council && uv run pytest tests/effect_graph/ -v`
Expected: All tests PASS

- [ ] **Step 2: Run ruff check across all changed files**

Run: `cd /home/hapax/projects/hapax-council && uv run ruff check agents/effect_graph/ --fix && uv run ruff format agents/effect_graph/`
Expected: Clean

- [ ] **Step 3: Verify the compositor starts with the graph system**

Run: `cd /home/hapax/projects/hapax-council && uv run python -c "
from agents.effect_graph.registry import ShaderRegistry
from agents.effect_graph.compiler import GraphCompiler
from agents.effect_graph.runtime import GraphRuntime
from agents.effect_graph.modulator import UniformModulator
from agents.effect_graph.types import EffectGraph
from pathlib import Path
import json

# Load registry
reg = ShaderRegistry(Path('agents/shaders/nodes'))
print(f'Registry loaded: {reg.node_types}')

# Load and compile Ghost preset
ghost = json.loads(Path('presets/ghost.json').read_text())
graph = EffectGraph(**ghost)
compiler = GraphCompiler(reg)
plan = compiler.compile(graph)
print(f'Ghost compiled: {len(plan.steps)} steps, layers: {plan.layer_sources}')

# Load runtime and activate
modulator = UniformModulator()
runtime = GraphRuntime(registry=reg, compiler=compiler, modulator=modulator)
runtime.load_graph(graph)
print(f'Runtime active: {runtime.current_graph.name}')
print('Integration test PASSED')
"`
Expected: "Integration test PASSED"

- [ ] **Step 4: Verify preset API works**

Run: `cd /home/hapax/projects/hapax-council && uv run python -c "
from agents.effect_graph.types import EffectGraph
from pathlib import Path
import json

for name in ['ghost', 'trails', 'clean']:
    raw = json.loads(Path(f'presets/{name}.json').read_text())
    g = EffectGraph(**raw)
    print(f'{g.name}: {len(g.nodes)} nodes, {len(g.edges)} edges, {len(g.modulations)} modulations')
print('All presets valid')
"`
Expected: All 3 presets parse and display correctly

- [ ] **Step 5: Final commit with all integration verified**

```bash
cd /home/hapax/projects/hapax-council
git add -A
git status  # Verify no untracked secrets or large files
git commit -m "feat(effect-graph): phase 1 complete — node graph infrastructure with 9 shader nodes"
```

---

## Phase 1 Deliverables Summary

| Component | Status |
|-----------|--------|
| Type models (Pydantic) | `agents/effect_graph/types.py` |
| Shader registry | `agents/effect_graph/registry.py` |
| Graph compiler (validation + topo sort) | `agents/effect_graph/compiler.py` |
| Graph runtime (3 mutation levels) | `agents/effect_graph/runtime.py` |
| Uniform modulator | `agents/effect_graph/modulator.py` |
| 9 shader nodes (manifests + GLSL) | `agents/shaders/nodes/` |
| 3 presets (Ghost, Trails, Clean) | `presets/` |
| API routes (graph, layers, modulation, presets, registry) | `logos/api/routes/studio.py` |
| Compositor integration | `agents/studio_compositor.py` |
| Frontend simplification | `hapax-logos/src/` (deleted CompositeCanvas + deps) |
| Test suite | `tests/effect_graph/` (38+ tests) |

## What Phase 2 Adds

- Remaining ~20 processing shaders (VHS, thermal, halftone, chromatic_aberration, displacement_map, etc.)
- Full GStreamer pipeline dynamic rebuild (replacing `_add_effects_branch` entirely)
- Smooth layer FBO ring (5-second delay buffer in GPU memory)
- Crossfade engine (dual-pipeline blend for transitions)
- All remaining presets (20 legacy + 8 new)

## What Phase 3 Adds

- ~15 temporal/generative/compositing nodes (datamosh, optical_flow, fluid_sim, reaction_diffusion, particle_system, etc.)
- Multi-camera compositing nodes (camera_select, split_screen, pip)
- Advanced modulation sources (heart_rate, optical_flow_magnitude)
- Frontend GraphInspector + NodeParamSlider components
