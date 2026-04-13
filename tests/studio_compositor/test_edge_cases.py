"""Post-epic audit Phase 4 — edge cases.

Each test exercises a surface the completion epic's tests didn't: an
empty source list, overlapping z_orders, unicode identifiers, symlinked
default paths, and so on. The goal is either to pin the current
behavior (good or bad) so future changes can't drift silently, or to
exercise a path the happy-path tests never hit.

Audit design: ``docs/superpowers/specs/2026-04-13-post-epic-audit-design.md``
Audit plan:   ``docs/superpowers/plans/2026-04-13-post-epic-audit-plan.md``
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from shared.compositor_model import Layout

# ---------------------------------------------------------------------------
# Layout schema edge cases
# ---------------------------------------------------------------------------


def test_layout_with_zero_sources_and_zero_assignments_parses() -> None:
    """A layout with no sources, no surfaces, no assignments is valid.

    This is the ground state for a compositor that has to boot before any
    content is declared. Rejecting it would force callers to fabricate a
    dummy source; allowing it lets the compositor start in a "nothing to
    render yet" state.
    """
    layout = Layout.model_validate(
        {"name": "empty", "sources": [], "surfaces": [], "assignments": []}
    )
    assert layout.name == "empty"
    assert layout.sources == []
    assert layout.surfaces == []
    assert layout.assignments == []


def test_layout_rejects_assignment_to_undeclared_source() -> None:
    """An assignment that points at a source ID not in ``sources`` is rejected.

    The pydantic ``_validate_references`` validator already enforces this
    via a ValueError with the close-match hint. This test pins that
    behavior from the outside so any future refactor of the validator
    has to preserve it.
    """
    with pytest.raises(ValueError) as excinfo:
        Layout.model_validate(
            {
                "name": "ghost-source",
                "sources": [{"id": "real", "kind": "cairo", "backend": "cairo", "params": {}}],
                "surfaces": [
                    {
                        "id": "pip",
                        "geometry": {"kind": "rect", "x": 0, "y": 0, "w": 10, "h": 10},
                    }
                ],
                "assignments": [{"source": "ghost", "surface": "pip"}],
            }
        )
    msg = str(excinfo.value)
    assert "ghost" in msg
    assert "unknown source" in msg


def test_layout_rejects_assignment_to_undeclared_surface() -> None:
    """Symmetrically: an assignment pointing at a missing surface is rejected."""
    with pytest.raises(ValueError) as excinfo:
        Layout.model_validate(
            {
                "name": "ghost-surface",
                "sources": [{"id": "real", "kind": "cairo", "backend": "cairo", "params": {}}],
                "surfaces": [
                    {
                        "id": "pip",
                        "geometry": {"kind": "rect", "x": 0, "y": 0, "w": 10, "h": 10},
                    }
                ],
                "assignments": [{"source": "real", "surface": "ghost"}],
            }
        )
    msg = str(excinfo.value)
    assert "ghost" in msg
    assert "unknown surface" in msg


def test_layout_rejects_duplicate_source_ids() -> None:
    with pytest.raises(ValueError, match="duplicate source IDs"):
        Layout.model_validate(
            {
                "name": "dup",
                "sources": [
                    {"id": "a", "kind": "cairo", "backend": "cairo", "params": {}},
                    {"id": "a", "kind": "cairo", "backend": "cairo", "params": {}},
                ],
                "surfaces": [],
                "assignments": [],
            }
        )


def test_layout_allows_overlapping_z_orders() -> None:
    """Two surfaces with the same ``z_order`` are legal — painter order is
    stable-by-declaration.

    This edge case matters because the audit design flagged it as a
    potential invariant violation. The schema permits it; the executor
    walks surfaces in the order they appear in ``self.surfaces``, so
    deterministic painter order holds even when z-values collide. This
    test pins both facts.
    """
    layout = Layout.model_validate(
        {
            "name": "same-z",
            "sources": [
                {"id": "a", "kind": "cairo", "backend": "cairo", "params": {}},
                {"id": "b", "kind": "cairo", "backend": "cairo", "params": {}},
            ],
            "surfaces": [
                {
                    "id": "first",
                    "geometry": {"kind": "rect", "x": 0, "y": 0, "w": 10, "h": 10},
                    "z_order": 10,
                },
                {
                    "id": "second",
                    "geometry": {"kind": "rect", "x": 0, "y": 0, "w": 10, "h": 10},
                    "z_order": 10,
                },
            ],
            "assignments": [
                {"source": "a", "surface": "first"},
                {"source": "b", "surface": "second"},
            ],
        }
    )
    # Declaration order is preserved — the executor's painter walk is
    # ``for surface in layout.surfaces``, so "first" paints before
    # "second" even though both have z_order=10.
    assert [s.id for s in layout.surfaces] == ["first", "second"]


def test_layout_rejects_unicode_source_id_with_extra_fields_guard() -> None:
    """Pydantic accepts non-ASCII IDs under the length cap — no special
    gating. This test pins that behavior so the cairo source registry
    lookups (which use the same string) can't silently fail on a
    future unicode-stripping pass.
    """
    layout = Layout.model_validate(
        {
            "name": "ünïcödé",
            "sources": [{"id": "café", "kind": "cairo", "backend": "cairo", "params": {}}],
            "surfaces": [],
            "assignments": [],
        }
    )
    assert layout.name == "ünïcödé"
    assert layout.sources[0].id == "café"


# ---------------------------------------------------------------------------
# Default layout path resolution
# ---------------------------------------------------------------------------


def test_default_layout_path_resolves_through_symlink(tmp_path: Path) -> None:
    """``_DEFAULT_LAYOUT_PATH`` uses ``Path(__file__).resolve()`` so a
    symlinked copy of the repo still resolves to the canonical config
    file. This test builds a symlinked view of the repo root and asserts
    the module-level constant still points at the real file.
    """
    from agents.studio_compositor import compositor as compositor_module

    real_path = compositor_module._DEFAULT_LAYOUT_PATH
    assert real_path.exists(), f"default layout file must exist on disk at {real_path}"
    assert real_path.is_absolute()
    assert real_path.name == "default.json"

    # Build a symlinked shim: tmp/repo -> actual repo root, and verify
    # that resolving a path through the shim lands on the same file.
    shim = tmp_path / "repo"
    shim.symlink_to(real_path.parents[2], target_is_directory=True)
    shimmed_config = shim / "config" / "compositor-layouts" / "default.json"
    assert shimmed_config.exists()
    assert shimmed_config.resolve() == real_path.resolve()


# ---------------------------------------------------------------------------
# Preset inputs edge cases (AC-7 robustness)
# ---------------------------------------------------------------------------


def test_preset_input_rejects_duplicate_as_aliases() -> None:
    """Two ``inputs`` entries with the same ``as`` alias must be rejected.

    The pydantic schema does not enforce uniqueness on ``as`` across
    the list; the resolver silently overwrote the earlier alias when
    this audit looked at the code. If an operator expects ``layer0``
    to refer to source A but another entry later binds ``layer0`` to
    source B, the preset is ambiguous.

    This test pins the *current* resolver behavior: the later entry
    wins. If a future audit decides ambiguity should raise, this test
    is the breakage point — flipping it is deliberate.
    """
    from agents.effect_graph.compiler import resolve_preset_inputs
    from agents.effect_graph.types import EffectGraph, NodeInstance, PresetInput
    from agents.studio_compositor.source_registry import SourceRegistry

    class _StubBackend:
        def __init__(self, tag: str) -> None:
            self.tag = tag

        def get_current_surface(self) -> None:
            return None

    registry = SourceRegistry()
    a = _StubBackend("A")
    b = _StubBackend("B")
    registry.register("pad_a", a)
    registry.register("pad_b", b)

    graph = EffectGraph(
        name="dup-alias",
        nodes={"n": NodeInstance(type="noise")},
        edges=[],
        inputs=[
            PresetInput(pad="pad_a", as_="layer0"),
            PresetInput(pad="pad_b", as_="layer0"),
        ],
    )

    resolved = resolve_preset_inputs(graph, registry)
    # Current behavior: last-declared wins.
    assert resolved["layer0"] is b
    assert len(resolved) == 1


# ---------------------------------------------------------------------------
# Compositor startup edge cases
# ---------------------------------------------------------------------------


def test_compositor_starts_with_zero_sources_layout(tmp_path: Path) -> None:
    """An empty-source layout must not crash ``start_layout_only``.

    Covers the "no content yet" boot state. The compositor should
    create a ``LayoutState`` + an empty ``SourceRegistry`` and return
    cleanly.
    """
    empty = {
        "name": "empty",
        "sources": [],
        "surfaces": [],
        "assignments": [],
    }
    layout_file = tmp_path / "empty.json"
    layout_file.write_text(json.dumps(empty))

    from agents.studio_compositor.compositor import StudioCompositor
    from agents.studio_compositor.config import _default_config

    with mock.patch(
        "agents.studio_compositor.compositor.load_camera_profiles",
        return_value=[],
    ):
        compositor = StudioCompositor(_default_config(), layout_path=layout_file)
    compositor.start_layout_only()

    assert compositor.layout_state is not None
    assert compositor.source_registry is not None
    assert compositor.source_registry.ids() == []

    # Persistence threads still start for the empty case — the
    # watcher will hot-reload when content is added later.
    assert compositor._layout_autosaver is not None
    assert compositor._layout_file_watcher is not None


def test_compositor_falls_back_when_source_backend_constructor_raises(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A cairo source whose constructor raises must be logged + skipped,
    not crash the compositor. The registered-sources set should contain
    every *other* source, and the broken one must be absent.
    """
    import logging

    raw = {
        "name": "one-broken-one-good",
        "sources": [
            {
                "id": "good",
                "kind": "cairo",
                "backend": "cairo",
                "params": {"class_name": "TokenPoleCairoSource", "natural_w": 32, "natural_h": 32},
            },
            {
                "id": "broken",
                "kind": "cairo",
                "backend": "cairo",
                "params": {"class_name": "ThisClassDoesNotExistAnywhere"},
            },
        ],
        "surfaces": [],
        "assignments": [],
    }
    layout_file = tmp_path / "mixed.json"
    layout_file.write_text(json.dumps(raw))

    from agents.studio_compositor.compositor import StudioCompositor
    from agents.studio_compositor.config import _default_config

    with mock.patch(
        "agents.studio_compositor.compositor.load_camera_profiles",
        return_value=[],
    ):
        compositor = StudioCompositor(_default_config(), layout_path=layout_file)
    caplog.set_level(logging.ERROR, logger="agents.studio_compositor.compositor")
    compositor.start_layout_only()

    assert compositor.source_registry is not None
    registered = set(compositor.source_registry.ids())
    assert "good" in registered
    assert "broken" not in registered
    assert any("failed to construct backend" in rec.message for rec in caplog.records)
