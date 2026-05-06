"""Layout-JSON × cairo-source-registry integrity pin.

Cairo sources declared in ``config/layouts/*.json`` reference Python
classes by ``params.class_name`` strings. The compositor resolves these
strings to ``CairoSource`` subclasses via
``agents.studio_compositor.cairo_sources._CAIRO_SOURCE_CLASSES`` at
runtime — a typo or missing import in either the layout JSON or the
cairo-sources registrar surfaces only when the compositor tries to
construct the source on the live broadcast (post-deploy).

This module catches that drift at test time: every cairo-kind source
declared in ``garage-door.json`` MUST have a registered class. The same
guard applies to ``compositor-layouts/default.json``. Failures produce
the offending layout, source-id, and unresolved class_name so the
operator can fix the typo or add the missing registration before
shipping.

Pure layout-side regression pin — no source changes, no behavior
change. Future ward additions to either canonical layout get the same
guard automatically (no per-ward test maintenance).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import pytest

from agents.studio_compositor.cairo_sources import _CAIRO_SOURCE_CLASSES

REPO_ROOT = Path(__file__).resolve().parents[2]

CANONICAL_LAYOUT_PATHS: tuple[Path, ...] = (
    REPO_ROOT / "config" / "layouts" / "garage-door.json",
    REPO_ROOT / "config" / "compositor-layouts" / "default.json",
)


def _cairo_source_class_names(layout_path: Path) -> Iterable[tuple[str, str]]:
    """Yield (source_id, class_name) tuples for every cairo source.

    Sources without ``kind == "cairo"`` are skipped — non-Cairo backends
    (cameras, shaders, external_rgba, image_file, pango_*) resolve via
    different registries and are not in scope for this pin.
    """
    layout = json.loads(layout_path.read_text())
    for source in layout.get("sources", []):
        if source.get("kind") != "cairo":
            continue
        params = source.get("params") or {}
        class_name = params.get("class_name")
        if not class_name:
            # Some Cairo sources are dispatched by ``backend`` rather
            # than ``params.class_name`` (e.g., ``backend: "token_pole"``,
            # ``backend: "sierpinski_renderer"``). Those are resolved by
            # the source-registry's per-backend dispatchers, not this
            # class registry — skip them defensively.
            continue
        yield (source["id"], class_name)


@pytest.mark.parametrize(
    "layout_path",
    CANONICAL_LAYOUT_PATHS,
    ids=lambda p: p.name,
)
def test_cairo_class_names_resolve(layout_path: Path) -> None:
    unresolved: list[tuple[str, str]] = []
    for source_id, class_name in _cairo_source_class_names(layout_path):
        if class_name not in _CAIRO_SOURCE_CLASSES:
            unresolved.append((source_id, class_name))

    assert not unresolved, (
        f"{layout_path.name} declares cairo sources whose class_name "
        f"is not registered in agents.studio_compositor.cairo_sources: "
        f"{unresolved}. Either register the class in cairo_sources/__init__.py "
        f"or fix the typo in the layout JSON."
    )
