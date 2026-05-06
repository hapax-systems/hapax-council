"""Layout assignment-reference integrity pin.

Each entry in ``layout.assignments`` cites a ``source`` id and a
``surface`` id. If either id doesn't match a declaration in the layout's
``sources`` / ``surfaces`` arrays, the compositor either silently skips
the assignment (worse) or raises at construction (better, but still
post-deploy). A typo like ``"source": "m8_oscillocsope"`` is invisible
under normal review unless the broadcast happens to feature the
affected ward.

This test parameterizes over the canonical layouts and asserts every
``assignment.source`` and ``assignment.surface`` resolves to a declared
entity in the same layout. Failures report the offending assignment
position + unresolved id so the operator can fix the typo before
shipping.

Layout-side regression pin only — no source code touched, no behavior
change. Sister to ``test_layout_class_registration.py`` (different
invariant: cairo class_name registration vs assignment reference
resolution).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

CANONICAL_LAYOUT_PATHS: tuple[Path, ...] = (
    REPO_ROOT / "config" / "layouts" / "garage-door.json",
    REPO_ROOT / "config" / "compositor-layouts" / "default.json",
)


def _resolve_assignment_references(layout_path: Path) -> list[str]:
    """Return a list of human-readable error strings for unresolved refs.

    Empty list = clean. Each entry names the layout file, the assignment
    index, and the unresolved id with its referent slot, so a CI failure
    produces enough context to fix without re-reading the JSON.
    """
    layout = json.loads(layout_path.read_text())
    declared_source_ids = {s["id"] for s in layout.get("sources", []) if "id" in s}
    declared_surface_ids = {s["id"] for s in layout.get("surfaces", []) if "id" in s}

    errors: list[str] = []
    for index, assignment in enumerate(layout.get("assignments", [])):
        source_id = assignment.get("source")
        surface_id = assignment.get("surface")
        if source_id not in declared_source_ids:
            errors.append(
                f"{layout_path.name} assignment #{index}: "
                f"source={source_id!r} not declared in sources[]"
            )
        if surface_id not in declared_surface_ids:
            errors.append(
                f"{layout_path.name} assignment #{index}: "
                f"surface={surface_id!r} not declared in surfaces[]"
            )
    return errors


@pytest.mark.parametrize(
    "layout_path",
    CANONICAL_LAYOUT_PATHS,
    ids=lambda p: p.name,
)
def test_assignment_references_resolve(layout_path: Path) -> None:
    errors = _resolve_assignment_references(layout_path)
    assert not errors, "\n".join(errors)
