"""Layout-integrity invariants across the full layout corpus.

Sister to ``test_layout_class_registration.py`` (#2629) and
``test_layout_assignment_references.py`` (#2630), which pin the same
two invariants but only against the canonical pair (``garage-door.json``
+ ``compositor-layouts/default.json``). This file widens coverage to
EVERY layout JSON in:

* ``config/layouts/`` — the operator-curated layouts (currently just
  ``garage-door.json``).
* ``config/compositor-layouts/`` — the canonical default + segment-*
  layouts + alternates (mobile, consent-safe).
* ``config/compositor-layouts/examples/`` — operator-declared
  alternative arrangements, if present.

A typo in any of these layouts surfaces only when the operator switches
to that layout — possibly after a livestream-segment transition, when
debugging is most expensive. Catching at CI cuts the loop closed.

Both invariants:

1. Every ``kind: "cairo"`` source's ``params.class_name`` resolves
   through ``_CAIRO_SOURCE_CLASSES``.
2. Every ``assignment.source`` / ``assignment.surface`` resolves to a
   declared entity in the same layout.

Pure layout-side regression pin — no source code touched, no behavior
change. Sources without ``params.class_name`` (those dispatched by
``backend`` instead, e.g. ``token_pole``, ``sierpinski_renderer``) are
skipped — they resolve through different registries and are out of
scope here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.studio_compositor.cairo_sources import _CAIRO_SOURCE_CLASSES

REPO_ROOT = Path(__file__).resolve().parents[2]


def _all_layout_paths() -> list[Path]:
    """Discover every layout JSON under config/.

    Sorted for deterministic test-id ordering. New layouts added under
    these roots get coverage automatically — no per-layout test
    maintenance.
    """
    roots = (
        REPO_ROOT / "config" / "layouts",
        REPO_ROOT / "config" / "compositor-layouts",
        REPO_ROOT / "config" / "compositor-layouts" / "examples",
    )
    paths: list[Path] = []
    for root in roots:
        if root.exists():
            paths.extend(sorted(root.glob("*.json")))
    return paths


ALL_LAYOUT_PATHS: list[Path] = _all_layout_paths()


@pytest.mark.parametrize(
    "layout_path",
    ALL_LAYOUT_PATHS,
    ids=lambda p: p.name,
)
def test_cairo_class_names_resolve(layout_path: Path) -> None:
    layout = json.loads(layout_path.read_text())
    unresolved: list[tuple[str, str]] = []
    for source in layout.get("sources", []):
        if source.get("kind") != "cairo":
            continue
        params = source.get("params") or {}
        class_name = params.get("class_name")
        if not class_name:
            # Sources dispatched by backend (e.g., token_pole,
            # sierpinski_renderer) resolve through different registries.
            continue
        if class_name not in _CAIRO_SOURCE_CLASSES:
            unresolved.append((source.get("id", "<no-id>"), class_name))

    assert not unresolved, (
        f"{layout_path.relative_to(REPO_ROOT)} declares cairo sources "
        f"whose class_name is not registered: {unresolved}. Register the "
        f"class in cairo_sources/__init__.py or fix the typo in the layout JSON."
    )


@pytest.mark.parametrize(
    "layout_path",
    ALL_LAYOUT_PATHS,
    ids=lambda p: p.name,
)
def test_assignment_references_resolve(layout_path: Path) -> None:
    layout = json.loads(layout_path.read_text())
    declared_source_ids = {s["id"] for s in layout.get("sources", []) if "id" in s}
    declared_surface_ids = {s["id"] for s in layout.get("surfaces", []) if "id" in s}

    errors: list[str] = []
    for index, assignment in enumerate(layout.get("assignments", [])):
        source_id = assignment.get("source")
        surface_id = assignment.get("surface")
        if source_id not in declared_source_ids:
            errors.append(f"assignment #{index}: source={source_id!r} not declared")
        if surface_id not in declared_surface_ids:
            errors.append(f"assignment #{index}: surface={surface_id!r} not declared")

    assert not errors, (
        f"{layout_path.relative_to(REPO_ROOT)} has unresolved assignment "
        f"references:\n  " + "\n  ".join(errors)
    )


def test_corpus_is_non_empty() -> None:
    """Defend against the test silently passing on a misconfigured glob."""
    assert ALL_LAYOUT_PATHS, (
        f"No layout JSONs discovered under {REPO_ROOT}/config/. "
        f"Expected garage-door.json + compositor-layouts/*.json at minimum."
    )
