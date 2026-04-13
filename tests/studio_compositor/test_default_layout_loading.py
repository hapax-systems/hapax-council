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


# ---------------------------------------------------------------------------
# Phase D task 13 — load_layout_or_fallback
# ---------------------------------------------------------------------------


def test_load_layout_or_fallback_reads_valid_file(tmp_path: Path) -> None:
    """Reads a Layout JSON file from disk and returns the parsed model."""
    from agents.studio_compositor.compositor import load_layout_or_fallback

    src = DEFAULT_JSON.read_text()
    target = tmp_path / "default.json"
    target.write_text(src)

    layout = load_layout_or_fallback(target)

    assert layout.name == "default"
    source_ids = {s.id for s in layout.sources}
    assert source_ids == {"token_pole", "album", "sierpinski", "reverie"}


def test_load_layout_or_fallback_uses_fallback_when_file_missing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Missing file path resolves to the hardcoded fallback without raising."""
    import logging

    from agents.studio_compositor.compositor import load_layout_or_fallback

    caplog.set_level(logging.WARNING, logger="agents.studio_compositor.compositor")
    layout = load_layout_or_fallback(tmp_path / "does-not-exist.json")

    assert layout.name == "default"
    assert any("fallback" in rec.message.lower() for rec in caplog.records), (
        "missing-file path should log a fallback warning"
    )


def test_load_layout_or_fallback_uses_fallback_on_invalid_json(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Malformed JSON resolves to fallback without raising."""
    import logging

    from agents.studio_compositor.compositor import load_layout_or_fallback

    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    caplog.set_level(logging.WARNING, logger="agents.studio_compositor.compositor")

    layout = load_layout_or_fallback(broken)

    assert layout.name == "default"
    assert any("fallback" in rec.message.lower() for rec in caplog.records)


def test_load_layout_or_fallback_uses_fallback_on_schema_violation(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Valid JSON that fails pydantic validation also resolves to fallback."""
    import logging

    from agents.studio_compositor.compositor import load_layout_or_fallback

    bad_schema = tmp_path / "bad-schema.json"
    bad_schema.write_text(json.dumps({"not_a_layout": True}))
    caplog.set_level(logging.WARNING, logger="agents.studio_compositor.compositor")

    layout = load_layout_or_fallback(bad_schema)

    assert layout.name == "default"
    assert any("fallback" in rec.message.lower() for rec in caplog.records)


def test_fallback_layout_parses_to_same_shape_as_default_json() -> None:
    """The hardcoded _FALLBACK_LAYOUT is structurally identical to default.json.

    Regression pin: if someone edits one side without the other, this
    fires. The fallback is the rescue path when the JSON cannot be
    loaded — it should produce the same runtime layout.
    """
    from agents.studio_compositor.compositor import _FALLBACK_LAYOUT

    raw = json.loads(DEFAULT_JSON.read_text())
    disk = Layout.model_validate(raw)

    assert _FALLBACK_LAYOUT.name == disk.name
    assert {s.id for s in _FALLBACK_LAYOUT.sources} == {s.id for s in disk.sources}
    assert {s.id for s in _FALLBACK_LAYOUT.surfaces} == {s.id for s in disk.surfaces}
    assert {(a.source, a.surface) for a in _FALLBACK_LAYOUT.assignments} == {
        (a.source, a.surface) for a in disk.assignments
    }
