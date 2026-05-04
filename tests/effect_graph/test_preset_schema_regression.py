"""Regression: every shipped graph preset in ``presets/`` must validate as ``EffectGraph``.

Backdrop: PR #2488 swapped the compositor's default startup preset from
``halftone_preset`` → ``sierpinski_line_overlay``. The new preset was missing
the required ``edges`` field, so Pydantic raised ``ValidationError`` at load
time and the compositor silently fell back to ``halftone_preset``. The
operator saw halftone dominating the broadcast even after the swap.

A 2026-05-04 audit then found 55 of 86 graph presets in ``presets/``
shipping without ``edges`` — i.e., 64% of the recruitable visual corpus
was unloadable, with ``state.py:362`` swallowing the ``ValidationError``
silently so recruitment fired but the chain held the previous plan.

Three complementary checks here:

1. ``test_every_graph_preset_validates_as_effect_graph`` parameterizes over
   EVERY graph-shaped preset in ``presets/`` (anything with a ``nodes`` map,
   excluding leading-underscore files and the ``shader_intensity_bounds``
   config file). This is the corpus-wide schema floor — any new preset that
   ships without ``edges`` regresses the recruitable corpus and fails here.
2. ``test_runtime_wired_presets_validate`` (legacy of PR #2491) parameterizes
   over presets that ALREADY declare both ``nodes`` and ``edges``. Subset of
   (1); kept as a focused check so failures still attribute clearly when the
   broader corpus check is parametrized away by future contributors.
3. ``test_default_startup_preset_is_runtime_loadable`` pins the specific
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

# Files in ``presets/`` that are not graph presets and are intentionally not
# subject to ``EffectGraph`` validation.
NON_GRAPH_PRESET_FILES = frozenset(
    {
        # Per-shader-family caps; ``_meta`` + ``node_caps`` shape, no ``nodes`` map.
        "shader_intensity_bounds.json",
    }
)


def _all_graph_presets() -> list[Path]:
    """Every preset in ``presets/`` that has the graph-preset shape.

    Graph-preset shape = a JSON object with a ``nodes`` map. This is the
    corpus the compositor's recruitment chain expects to be able to load
    without ``ValidationError``. Excludes leading-underscore files
    (``_default_modulations.json``) and the explicit non-graph allowlist.
    """
    out: list[Path] = []
    for p in sorted(PRESETS_DIR.glob("*.json")):
        if p.name.startswith("_") or p.name in NON_GRAPH_PRESET_FILES:
            continue
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(raw, dict) and isinstance(raw.get("nodes"), dict):
            out.append(p)
    return out


def _runtime_wired_presets() -> list[Path]:
    """Presets currently wired into the compositor runtime.

    "Runtime-wired" means the JSON file declares both ``nodes`` AND ``edges``
    — the same shape filter ``tests/effect_graph/test_smoke.py::_is_graph_preset``
    uses. Files in ``presets/`` that lack ``edges`` are satellite-only or
    template fragments and are intentionally not loaded by the compositor.
    """
    out: list[Path] = []
    for p in _all_graph_presets():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(raw, dict) and "nodes" in raw and "edges" in raw:
            out.append(p)
    return out


@pytest.mark.parametrize("preset_path", _all_graph_presets(), ids=lambda p: p.stem)
def test_every_graph_preset_validates_as_effect_graph(preset_path: Path) -> None:
    """EVERY graph-shaped preset must validate as ``EffectGraph``.

    Corpus-wide schema floor: any preset in ``presets/`` with a ``nodes``
    map must construct cleanly under ``EffectGraph(**raw)``. A failure here
    means the preset is missing ``edges``, has malformed ``edges``, or has
    a bad ``nodes`` entry — the runtime would either crash on load or
    (worse) silently swallow the ``ValidationError`` at
    ``agents/studio_compositor/state.py:362`` and hold the previous chain.
    """
    raw = json.loads(preset_path.read_text(encoding="utf-8"))
    try:
        EffectGraph(**raw)
    except ValidationError as exc:  # pragma: no cover — failure path
        pytest.fail(
            f"{preset_path.name} fails EffectGraph schema:\n{exc}\n"
            f"Add the missing field(s) so the compositor can load this preset."
        )


@pytest.mark.parametrize("preset_path", _runtime_wired_presets(), ids=lambda p: p.stem)
def test_runtime_wired_presets_validate(preset_path: Path) -> None:
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
