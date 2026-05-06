"""Deprecation gate for ``preset_family_selector``.

Per ``project_random_mode_dead_consumer_canonical`` (memory): ``random_mode``
is unwired per operator 2026-04-20 directive; ``preset_recruitment_consumer``
is the live chain mutation path. ``preset_family_selector`` still exists
(never-remove) but must not gain new callers.

This test pins the known import graph. If a new file starts importing from
``preset_family_selector``, the test fails and directs the author to
``preset_recruitment_consumer`` instead.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MODULE_NAME = "preset_family_selector"

# Known callers of preset_family_selector (grandfathered — do NOT add to this list).
KNOWN_IMPORTERS: frozenset[str] = frozenset(
    {
        "agents/studio_compositor/effects.py",
        "agents/studio_compositor/preset_recruitment_consumer.py",
        "agents/studio_compositor/random_mode.py",
        "tests/test_xerox_neon_paper_water_preset_pool.py",
        "tests/test_kaleido_pixsort_chromakey_sierpinski_preset_pool.py",
        "tests/test_drone_arcade_cellular_electromagnetic_preset_pool.py",
        "tests/test_monochrome_bloom_arcane_broadcast_preset_pool.py",
        "tests/test_chamber_chrome_diff_circular_preset_pool.py",
        "tests/studio_compositor/test_preset_family_selector.py",
        "tests/studio_compositor/test_scene_classifier.py",
    }
)


def _find_importers() -> set[str]:
    importers: set[str] = set()
    for py in sorted(REPO_ROOT.rglob("*.py")):
        if "__pycache__" in py.parts or ".venv" in py.parts:
            continue
        rel = str(py.relative_to(REPO_ROOT))
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=rel)
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and MODULE_NAME in node.module:
                importers.add(rel)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if MODULE_NAME in alias.name:
                        importers.add(rel)
    return importers


class TestPresetFamilySelectorDeprecation:
    def test_no_new_importers(self) -> None:
        actual = _find_importers()
        new = actual - KNOWN_IMPORTERS
        if new:
            lines = [
                "New imports of deprecated preset_family_selector detected:",
                *[f"  {f}" for f in sorted(new)],
                "",
                "preset_family_selector is deprecated per operator directive 2026-04-20.",
                "Use preset_recruitment_consumer instead (the canonical chain mutation path).",
                "If this import is genuinely needed, add the file to KNOWN_IMPORTERS",
                "with a comment explaining why.",
            ]
            import pytest

            pytest.fail("\n".join(lines))

    def test_known_importers_still_import(self) -> None:
        actual = _find_importers()
        stale = KNOWN_IMPORTERS - actual
        # This isn't a failure — files may legitimately stop importing.
        # Just advisory so the KNOWN_IMPORTERS list stays current.
        if stale:
            import warnings

            warnings.warn(
                f"KNOWN_IMPORTERS contains stale entries (no longer import "
                f"preset_family_selector): {sorted(stale)}. Consider removing "
                f"them from the grandfather list.",
                stacklevel=1,
            )
