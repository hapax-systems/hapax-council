"""Default compositor layout validation tests.

Source-registry epic Phase D task 12. These tests assert that the
on-disk baseline layout at ``config/compositor-layouts/default.json``
parses as a valid ``shared.compositor_model.Layout`` and carries the
expected source/surface/assignment shape.

Task 13 will extend this file with end-to-end compositor loader tests
(``load_layout_or_fallback``) once that helper lands in ``compositor.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from shared.compositor_model import Layout

DEFAULT_JSON = Path(__file__).parents[2] / "config" / "compositor-layouts" / "default.json"


def test_default_json_exists_and_is_valid_layout() -> None:
    assert DEFAULT_JSON.exists(), f"missing {DEFAULT_JSON}"
    raw = json.loads(DEFAULT_JSON.read_text())
    layout = Layout.model_validate(raw)

    assert layout.name == "default"

    source_ids = {s.id for s in layout.sources}
    assert source_ids == {"token_pole", "album", "sierpinski", "reverie"}

    surface_ids = {s.id for s in layout.surfaces}
    assert surface_ids == {"pip-ul", "pip-ur", "pip-ll", "pip-lr"}

    assignment_pairs = {(a.source, a.surface) for a in layout.assignments}
    assert assignment_pairs == {
        ("token_pole", "pip-ul"),
        ("reverie", "pip-ur"),
        ("album", "pip-ll"),
    }


def test_default_json_source_backends_match_registry_dispatch() -> None:
    """Each source's backend matches the SourceRegistry dispatcher keys."""
    raw = json.loads(DEFAULT_JSON.read_text())
    layout = Layout.model_validate(raw)

    backend_by_id = {s.id: s.backend for s in layout.sources}
    assert backend_by_id == {
        "token_pole": "cairo",
        "album": "cairo",
        "sierpinski": "cairo",
        "reverie": "shm_rgba",
    }


def test_default_json_cairo_sources_name_registered_classes() -> None:
    """Cairo sources carry a ``class_name`` matching the cairo_sources registry."""
    from agents.studio_compositor.cairo_sources import get_cairo_source_class

    raw = json.loads(DEFAULT_JSON.read_text())
    layout = Layout.model_validate(raw)

    for source in layout.sources:
        if source.backend != "cairo":
            continue
        class_name = source.params.get("class_name")
        assert class_name, f"source {source.id}: cairo backend requires class_name"
        cls = get_cairo_source_class(class_name)
        assert cls is not None


def test_default_json_reverie_points_at_producer_shm_path() -> None:
    """The reverie source reads the exact shm path hapax-visual's write_side_output writes.

    Coupling regression pin: if either side of the producer/consumer
    pair moves, this test flags the drift. The producer path is
    ``SIDE_OUTPUT_FILE`` in ``hapax-logos/crates/hapax-visual/src/output.rs``.
    """
    raw = json.loads(DEFAULT_JSON.read_text())
    layout = Layout.model_validate(raw)

    reverie = next(s for s in layout.sources if s.id == "reverie")
    assert reverie.params.get("shm_path") == "/dev/shm/hapax-sources/reverie.rgba"


def test_default_json_pip_lr_surface_is_intentionally_unassigned() -> None:
    """pip-lr is defined but not bound so a recruited source can fill it at runtime."""
    raw = json.loads(DEFAULT_JSON.read_text())
    layout = Layout.model_validate(raw)

    surface_ids = {s.id for s in layout.surfaces}
    assigned_surface_ids = {a.surface for a in layout.assignments}
    unassigned = surface_ids - assigned_surface_ids
    assert unassigned == {"pip-lr"}
