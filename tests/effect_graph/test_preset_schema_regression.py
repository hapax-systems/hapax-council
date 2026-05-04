"""Regression: every shipped graph preset in ``presets/`` must validate as ``EffectGraph``.

Backdrop: PR #2488 swapped the compositor's default startup preset from
``halftone_preset`` → ``sierpinski_line_overlay``. The new preset was missing
the required ``edges`` field, so Pydantic raised ``ValidationError`` at load
time and the compositor silently fell back to ``halftone_preset``. The
operator saw halftone dominating the broadcast even after the swap.

Two complementary checks here:

1. ``test_preset_validates_as_effect_graph`` parameterizes over every preset
   that is wired into the compositor runtime today (i.e., declares both
   ``nodes`` and ``edges``). It guards against schema regressions on
   already-runtime-wired presets. A preset with only ``nodes`` is treated as
   a satellite-only / not-yet-wired graph and intentionally skipped here —
   ``test_default_startup_preset_is_runtime_loadable`` is the explicit guard
   that catches a default-startup preset slipping through schema-incomplete.
2. ``test_default_startup_preset_is_runtime_loadable`` pins the specific
   PR #2488 fallout: ``sierpinski_line_overlay.json`` (the compositor's
   default startup preset) must declare ``edges`` and ``modulations`` and
   must validate end-to-end. If this regresses, the compositor falls back
   to ``halftone_preset`` and broadcast aesthetics regress to
   halftone-dominant.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agents.effect_graph.types import EffectGraph

PRESETS_DIR = Path(__file__).parent.parent.parent / "presets"

# The compositor's default startup preset (see ``agents/studio_compositor/lifecycle.py``).
DEFAULT_STARTUP_PRESET = "sierpinski_line_overlay"


def _runtime_wired_presets() -> list[Path]:
    """Presets currently wired into the compositor runtime.

    "Runtime-wired" means the JSON file declares both ``nodes`` AND ``edges``
    — the same shape filter ``tests/effect_graph/test_smoke.py::_is_graph_preset``
    uses. Files in ``presets/`` that lack ``edges`` are satellite-only or
    template fragments and are intentionally not loaded by the compositor.
    """
    out: list[Path] = []
    for p in sorted(PRESETS_DIR.glob("*.json")):
        if p.name.startswith("_"):
            continue
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(raw, dict) and "nodes" in raw and "edges" in raw:
            out.append(p)
    return out


@pytest.mark.parametrize("preset_path", _runtime_wired_presets(), ids=lambda p: p.stem)
def test_preset_validates_as_effect_graph(preset_path: Path) -> None:
    """Every runtime-wired preset must validate as ``EffectGraph``.

    A ``ValidationError`` here means the preset declares ``nodes`` and
    ``edges`` but one of them is malformed (wrong types, missing required
    sub-fields, etc.). The compositor would crash trying to load this.
    """
    raw = json.loads(preset_path.read_text(encoding="utf-8"))
    try:
        EffectGraph(**raw)
    except ValidationError as exc:  # pragma: no cover — failure path
        pytest.fail(
            f"{preset_path.name} fails EffectGraph schema:\n{exc}\n"
            f"Add the missing field(s) so the compositor can load this preset."
        )


def test_default_startup_preset_is_runtime_loadable() -> None:
    """Pinned regression for the PR #2488 fallout.

    ``sierpinski_line_overlay.json`` is the compositor's default startup
    preset. It must declare ``edges`` (Pydantic-required) and ``modulations``
    (canonical preset shape), and must validate as ``EffectGraph`` with at
    least one edge, an ``output`` node, and a layer-source edge so live
    camera frames flow into the chain.
    """
    preset_path = PRESETS_DIR / f"{DEFAULT_STARTUP_PRESET}.json"
    raw = json.loads(preset_path.read_text(encoding="utf-8"))

    assert "edges" in raw, f"{DEFAULT_STARTUP_PRESET}.json must declare 'edges'"
    assert "modulations" in raw, f"{DEFAULT_STARTUP_PRESET}.json must declare 'modulations'"

    graph = EffectGraph(**raw)
    assert len(graph.edges) >= 1, f"{DEFAULT_STARTUP_PRESET} must have at least one edge"
    assert any(node.type == "output" for node in graph.nodes.values()), (
        f"{DEFAULT_STARTUP_PRESET} must have an 'output' node"
    )

    parsed = graph.parsed_edges
    assert any(edge.is_layer_source for edge in parsed), (
        f"{DEFAULT_STARTUP_PRESET} must have an '@'-prefixed layer-source edge"
    )
