"""LayoutAutoSaver + LayoutFileWatcher tests — Phase 5 / parent task G22."""

from __future__ import annotations

import json
import time
from pathlib import Path

import agents.studio_compositor.layout_persistence as layout_persistence
from agents.studio_compositor.layout_persistence import (
    LayoutAutoSaver,
    LayoutFileWatcher,
)
from agents.studio_compositor.layout_state import LayoutState
from shared.compositor_model import (
    Assignment,
    Layout,
    SourceSchema,
    SurfaceGeometry,
    SurfaceSchema,
)


def _minimal_layout(name: str = "default") -> Layout:
    return Layout(
        name=name,
        sources=[
            SourceSchema(
                id="src1",
                kind="cairo",
                backend="cairo",
                params={"class_name": "Stub"},
            )
        ],
        surfaces=[
            SurfaceSchema(
                id="pip-ul",
                geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=100, h=100),
                z_order=1,
            ),
        ],
        assignments=[Assignment(source="src1", surface="pip-ul")],
    )


def _mutate_x(state: LayoutState, x_value: int) -> None:
    def mutator(layout: Layout) -> Layout:
        new_surfaces = [
            s.model_copy(update={"geometry": s.geometry.model_copy(update={"x": x_value})})
            for s in layout.surfaces
        ]
        return layout.model_copy(update={"surfaces": new_surfaces})

    state.mutate(mutator)


def test_autosave_debounces_rapid_mutations(tmp_path: Path) -> None:
    layout_file = tmp_path / "default.json"
    layout_file.write_text(json.dumps(_minimal_layout().model_dump()))
    state = LayoutState(_minimal_layout())
    saver = LayoutAutoSaver(state, layout_file, debounce_s=0.1)
    saver.start()
    try:
        for i in range(5):
            _mutate_x(state, i)
        time.sleep(0.4)
        on_disk = json.loads(layout_file.read_text())
        assert on_disk["surfaces"][0]["geometry"]["x"] == 4
    finally:
        saver.stop()


def test_autosave_flush_now_skips_debounce(tmp_path: Path) -> None:
    layout_file = tmp_path / "default.json"
    layout_file.write_text(json.dumps(_minimal_layout().model_dump()))
    state = LayoutState(_minimal_layout())
    saver = LayoutAutoSaver(state, layout_file, debounce_s=10.0)
    saver.start()
    try:
        _mutate_x(state, 42)
        saver.flush_now()
        on_disk = json.loads(layout_file.read_text())
        assert on_disk["surfaces"][0]["geometry"]["x"] == 42
    finally:
        saver.stop()


def test_autosave_writes_atomically(tmp_path: Path) -> None:
    """Temp files written during the atomic rename must not leak into the dir."""
    layout_file = tmp_path / "default.json"
    layout_file.write_text(json.dumps(_minimal_layout().model_dump()))
    state = LayoutState(_minimal_layout())
    saver = LayoutAutoSaver(state, layout_file, debounce_s=0.05)
    saver.start()
    try:
        _mutate_x(state, 7)
        time.sleep(0.3)
        residue = [p.name for p in tmp_path.iterdir() if p.name.startswith(".default.json.tmp-")]
        assert residue == []
    finally:
        saver.stop()


def test_autosave_refuses_to_poison_default_with_named_layout(tmp_path: Path, caplog) -> None:
    layout_file = tmp_path / "default.json"
    layout_file.write_text(json.dumps(_minimal_layout().model_dump()))
    state = LayoutState(_minimal_layout(name="segment-detail"))
    saver = LayoutAutoSaver(state, layout_file, debounce_s=0.05)
    with caplog.at_level("WARNING"):
        saver.flush_now()

    on_disk = json.loads(layout_file.read_text())
    assert on_disk["name"] == "default"
    assert "refusing to write layout" in caplog.text


def test_autosave_temp_file_failure_is_nonfatal(tmp_path: Path, monkeypatch, caplog) -> None:
    layout_file = tmp_path / "default.json"
    layout_file.write_text(json.dumps(_minimal_layout().model_dump()))
    state = LayoutState(_minimal_layout())
    saver = LayoutAutoSaver(state, layout_file, debounce_s=0.05)

    def fail_mkstemp(*_args, **_kwargs):
        raise PermissionError("read-only incident containment")

    monkeypatch.setattr(layout_persistence.tempfile, "mkstemp", fail_mkstemp)

    with caplog.at_level("ERROR"):
        saver.flush_now()

    on_disk = json.loads(layout_file.read_text())
    assert on_disk["name"] == "default"
    assert "temp file allocation failed" in caplog.text


def test_filewatcher_reloads_on_valid_edit(tmp_path: Path) -> None:
    layout_file = tmp_path / "default.json"
    layout_file.write_text(json.dumps(_minimal_layout().model_dump()))
    state = LayoutState(_minimal_layout())
    watcher = LayoutFileWatcher(state, layout_file)
    watcher.start()
    try:
        new_layout = _minimal_layout().model_copy(
            update={
                "surfaces": [
                    s.model_copy(update={"geometry": s.geometry.model_copy(update={"x": 999})})
                    for s in _minimal_layout().surfaces
                ]
            }
        )
        # Force a distinct mtime (>2s tolerance window for self-write detection).
        time.sleep(0.1)
        layout_file.write_text(json.dumps(new_layout.model_dump()))
        # Poll for up to 2s for the watcher to pick up the change.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if state.get().surfaces[0].geometry.x == 999:
                break
            time.sleep(0.05)
        assert state.get().surfaces[0].geometry.x == 999
    finally:
        watcher.stop()


def test_filewatcher_ignores_invalid_json(tmp_path: Path) -> None:
    layout_file = tmp_path / "default.json"
    layout_file.write_text(json.dumps(_minimal_layout().model_dump()))
    state = LayoutState(_minimal_layout())
    watcher = LayoutFileWatcher(state, layout_file)
    watcher.start()
    try:
        time.sleep(0.1)
        layout_file.write_text("{not valid json")
        time.sleep(0.3)
        # State unchanged — the invalid edit is ignored.
        assert state.get().surfaces[0].geometry.x == 0
    finally:
        watcher.stop()


def test_filewatcher_retries_transient_empty_write(tmp_path: Path) -> None:
    layout_file = tmp_path / "default.json"
    layout_file.write_text(json.dumps(_minimal_layout().model_dump()))
    state = LayoutState(_minimal_layout())
    watcher = LayoutFileWatcher(state, layout_file)
    watcher.start()
    try:
        layout_file.write_text("")
        time.sleep(0.3)
        assert state.get().surfaces[0].geometry.x == 0

        new_layout = _minimal_layout().model_copy(
            update={
                "surfaces": [
                    s.model_copy(update={"geometry": s.geometry.model_copy(update={"x": 321})})
                    for s in _minimal_layout().surfaces
                ]
            }
        )
        layout_file.write_text(json.dumps(new_layout.model_dump()))
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if state.get().surfaces[0].geometry.x == 321:
                break
            time.sleep(0.05)
        assert state.get().surfaces[0].geometry.x == 321
    finally:
        watcher.stop()


def test_filewatcher_skips_self_write(tmp_path: Path) -> None:
    layout_file = tmp_path / "default.json"
    layout_file.write_text(json.dumps(_minimal_layout().model_dump()))
    state = LayoutState(_minimal_layout())
    watcher = LayoutFileWatcher(state, layout_file)
    saver = LayoutAutoSaver(state, layout_file, debounce_s=0.05)
    mutation_count = {"n": 0}

    def observer(_layout: Layout) -> None:
        mutation_count["n"] += 1

    state.subscribe(observer)
    saver.start()
    watcher.start()
    try:
        # Baseline mtime so the watcher ignores the initial file.
        time.sleep(0.1)
        _mutate_x(state, 1)
        time.sleep(0.4)
        # Exactly one mutation — the autosaver wrote the file, and the
        # watcher interpreted the new mtime as a self-write.
        assert mutation_count["n"] == 1
    finally:
        watcher.stop()
        saver.stop()
