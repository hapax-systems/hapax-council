"""Slot-family schema regression pins.

The yt-content-reverie-sierpinski-separation design (2026-04-21) tags each
``requires_content_slots`` node with a ``slot_family`` so the Rust runtime
can route ``content_slot_*`` bindings to family-matched sources only.
Pre-fix, both Reverie's ``content_layer`` and Sierpinski's
``sierpinski_content`` consumed from a single global pool — YouTube
frames bled into Reverie's generative substrate.

These tests pin the schema contract so future shader / compiler edits
can't reintroduce the cross-bleed silently.
"""

from __future__ import annotations

import json
from pathlib import Path

from agents.effect_graph.registry import LoadedShaderDef, ShaderRegistry

NODES_DIR = Path(__file__).parents[2] / "agents" / "shaders" / "nodes"


def test_loaded_shader_def_default_slot_family_is_narrative() -> None:
    """A node whose manifest omits ``slot_family`` defaults to ``narrative``.

    Backward compatibility: legacy node manifests (pre-2026-04-21) that
    don't carry the field must keep parsing as narrative-family so the
    Reverie substrate continues to receive narrative-content sources.
    """
    raw = {
        "node_type": "stub_node",
        "inputs": {},
        "outputs": {},
        "params": {},
        "temporal": False,
    }
    # Smallest-possible registry to exercise the parser path.
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        nodes_dir = Path(td)
        (nodes_dir / "stub.json").write_text(json.dumps(raw))
        reg = ShaderRegistry(nodes_dir)
        node = reg.get("stub_node")
        assert node is not None
        assert node.slot_family == "narrative"


def test_content_layer_manifest_declares_narrative_family() -> None:
    """Reverie's substrate node MUST tag itself ``narrative`` so the
    Rust runtime never binds YouTube frames into the generative graph."""
    manifest = json.loads((NODES_DIR / "content_layer.json").read_text())
    assert manifest.get("requires_content_slots") is True
    assert manifest.get("slot_family") == "narrative", (
        "content_layer must declare slot_family='narrative' so YT frames "
        "(which live in slot_family='youtube_pip') don't bleed into Reverie. "
        f"got: {manifest.get('slot_family')!r}"
    )


def test_sierpinski_content_manifest_declares_youtube_pip_family() -> None:
    """Sierpinski's content node tags itself ``youtube_pip`` so YouTube
    frames route here for foreground display, not into Reverie."""
    manifest = json.loads((NODES_DIR / "sierpinski_content.json").read_text())
    assert manifest.get("requires_content_slots") is True
    assert manifest.get("slot_family") == "youtube_pip", (
        "sierpinski_content must declare slot_family='youtube_pip' to claim "
        f"YT-slot sources. got: {manifest.get('slot_family')!r}"
    )


def test_registry_loads_node_slot_family_from_manifest() -> None:
    """End-to-end: ``ShaderRegistry`` reads the field through to
    ``LoadedShaderDef.slot_family`` (no field-mapping drift)."""
    reg = ShaderRegistry(NODES_DIR)
    content_layer = reg.get("content_layer")
    sierpinski = reg.get("sierpinski_content")
    assert content_layer is not None
    assert sierpinski is not None
    assert content_layer.slot_family == "narrative"
    assert sierpinski.slot_family == "youtube_pip"


def test_compiled_pass_descriptor_emits_slot_family() -> None:
    """The wgsl_compiler pass descriptor carries ``slot_family`` whenever
    ``requires_content_slots`` is True. The Rust deserializer relies on
    this invariant: a pass that needs slots ALWAYS has a family declared
    (no None / missing-field branch on the runtime side)."""
    from dataclasses import dataclass, field

    from agents.effect_graph.wgsl_compiler import _build_passes_for_target

    @dataclass
    class _Edge:
        source_node: str
        is_layer_source: bool = True

    @dataclass
    class _Step:
        node_id: str
        node_type: str
        params: dict[str, object] = field(default_factory=dict)
        input_edges: list[_Edge] = field(default_factory=list)
        temporal: bool = False

    reg = ShaderRegistry(NODES_DIR)

    steps = [
        _Step(node_id="content_a", node_type="content_layer"),
        _Step(node_id="sierp_a", node_type="sierpinski_content"),
        _Step(node_id="output", node_type="output"),  # filtered out by compiler
    ]
    passes = _build_passes_for_target(reg, steps)  # type: ignore[arg-type]

    by_id = {p["node_id"]: p for p in passes}
    assert "content_a" in by_id
    assert "sierp_a" in by_id

    content_pass = by_id["content_a"]
    assert content_pass.get("requires_content_slots") is True
    assert content_pass.get("slot_family") == "narrative", (
        "content_layer pass descriptor must carry slot_family='narrative' "
        f"alongside requires_content_slots=True. got: {content_pass.get('slot_family')!r}"
    )

    sierp_pass = by_id["sierp_a"]
    assert sierp_pass.get("requires_content_slots") is True
    assert sierp_pass.get("slot_family") == "youtube_pip"


def test_pass_descriptor_omits_slot_family_when_no_content_slots() -> None:
    """Nodes that don't need content slots also don't get a slot_family
    in the descriptor — keeps the JSON output minimal and avoids
    confusing the Rust runtime, which only reads slot_family on
    requires_content_slots passes."""
    from dataclasses import dataclass, field

    from agents.effect_graph.wgsl_compiler import _build_passes_for_target

    @dataclass
    class _Step:
        node_id: str
        node_type: str
        params: dict[str, object] = field(default_factory=dict)
        input_edges: list = field(default_factory=list)
        temporal: bool = False

    reg = ShaderRegistry(NODES_DIR)
    # Pick any non-content-slot node from the live registry.
    non_content_types = [
        nt
        for nt in reg.node_types
        if (d := reg.get(nt)) and not d.requires_content_slots and nt != "output"
    ]
    assert non_content_types, "no non-content-slot nodes in registry — test is meaningless"
    target_type = non_content_types[0]

    steps = [_Step(node_id="n0", node_type=target_type)]
    passes = _build_passes_for_target(reg, steps)  # type: ignore[arg-type]
    assert passes
    assert "slot_family" not in passes[0]
    assert "requires_content_slots" not in passes[0]


def test_loaded_shader_def_dataclass_field_present() -> None:
    """Type-level pin — ``LoadedShaderDef`` carries a ``slot_family``
    field with default ``narrative``. Catches silent removals via the
    dataclass field introspection rather than runtime behavior."""
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(LoadedShaderDef)}
    assert "slot_family" in field_names
    inst = LoadedShaderDef(
        node_type="x",
        inputs={},
        outputs={},
        params={},
        temporal=False,
        compute=False,
        glsl_source=None,
    )
    assert inst.slot_family == "narrative"
