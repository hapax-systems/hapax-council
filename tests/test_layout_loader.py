"""Tests for agents/studio_compositor/layout_loader.py — LayoutStore.

Phase 2c of the compositor unification epic.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from agents.studio_compositor.layout_loader import LayoutStore


def _write_minimal_layout(path: Path, name: str = "test") -> None:
    """Write a minimal valid Layout JSON file to disk."""
    content = (
        '{"name": "' + name + '", "sources": [{"id": "s1", "kind": "camera", "backend": "v4l2"}], '
        '"surfaces": [{"id": "f1", "geometry": {"kind": "tile"}}], '
        '"assignments": [{"source": "s1", "surface": "f1"}]}'
    )
    path.write_text(content)


# ---------------------------------------------------------------------------
# Construction and basic loading
# ---------------------------------------------------------------------------


class TestLayoutStoreInit:
    def test_loads_files_from_directory(self, tmp_path):
        _write_minimal_layout(tmp_path / "alpha.json", name="alpha")
        _write_minimal_layout(tmp_path / "beta.json", name="beta")
        store = LayoutStore(layout_dir=tmp_path)
        assert set(store.list_available()) == {"alpha", "beta"}

    def test_skips_non_json_files(self, tmp_path):
        _write_minimal_layout(tmp_path / "valid.json", name="valid")
        (tmp_path / "readme.md").write_text("# notes")
        (tmp_path / "garbage.txt").write_text("nope")
        store = LayoutStore(layout_dir=tmp_path)
        assert store.list_available() == ["valid"]

    def test_skips_invalid_json(self, tmp_path, caplog):
        _write_minimal_layout(tmp_path / "good.json", name="good")
        (tmp_path / "broken.json").write_text("{not valid json")
        with caplog.at_level("WARNING"):
            store = LayoutStore(layout_dir=tmp_path)
        assert store.list_available() == ["good"]
        assert any("Failed to load layout" in r.message for r in caplog.records)

    def test_skips_invalid_schema(self, tmp_path, caplog):
        _write_minimal_layout(tmp_path / "good.json", name="good")
        (tmp_path / "bad-schema.json").write_text(
            '{"name": "bad", "sources": [{"id": "x", "kind": "INVALID", "backend": "v4l2"}], '
            '"surfaces": [], "assignments": []}'
        )
        with caplog.at_level("WARNING"):
            store = LayoutStore(layout_dir=tmp_path)
        assert store.list_available() == ["good"]

    def test_empty_directory(self, tmp_path):
        store = LayoutStore(layout_dir=tmp_path)
        assert store.list_available() == []

    def test_nonexistent_directory(self, tmp_path):
        store = LayoutStore(layout_dir=tmp_path / "does-not-exist")
        assert store.list_available() == []


# ---------------------------------------------------------------------------
# Active layout
# ---------------------------------------------------------------------------


class TestActiveLayout:
    def test_get_active_returns_none_initially(self, tmp_path):
        _write_minimal_layout(tmp_path / "garage.json", name="garage")
        store = LayoutStore(layout_dir=tmp_path)
        assert store.get_active() is None
        assert store.active_name() is None

    def test_set_active_requires_existing_name(self, tmp_path):
        _write_minimal_layout(tmp_path / "garage.json", name="garage")
        store = LayoutStore(layout_dir=tmp_path)
        assert store.set_active("missing") is False
        assert store.active_name() is None

    def test_set_active_succeeds_for_loaded_layout(self, tmp_path):
        _write_minimal_layout(tmp_path / "garage.json", name="garage")
        store = LayoutStore(layout_dir=tmp_path)
        assert store.set_active("garage") is True
        assert store.active_name() == "garage"
        layout = store.get_active()
        assert layout is not None
        assert layout.name == "garage"

    def test_get_by_name(self, tmp_path):
        _write_minimal_layout(tmp_path / "alpha.json", name="alpha")
        _write_minimal_layout(tmp_path / "beta.json", name="beta")
        store = LayoutStore(layout_dir=tmp_path)
        alpha = store.get("alpha")
        beta = store.get("beta")
        assert alpha is not None and alpha.name == "alpha"
        assert beta is not None and beta.name == "beta"
        assert store.get("missing") is None


# ---------------------------------------------------------------------------
# Hot-reload
# ---------------------------------------------------------------------------


class TestReload:
    def test_reload_detects_added_files(self, tmp_path):
        store = LayoutStore(layout_dir=tmp_path)
        assert store.list_available() == []

        _write_minimal_layout(tmp_path / "new.json", name="new")
        changed = store.reload_changed()
        assert "new" in changed
        assert "new" in store.list_available()

    def test_reload_detects_modified_files(self, tmp_path):
        layout_path = tmp_path / "garage.json"
        _write_minimal_layout(layout_path, name="garage")
        store = LayoutStore(layout_dir=tmp_path)
        store.set_active("garage")

        # Modify the file with a new mtime
        time.sleep(0.01)  # ensure mtime changes
        modified_content = (
            '{"name": "garage", '
            '"description": "modified", '
            '"sources": [{"id": "s1", "kind": "camera", "backend": "v4l2"}], '
            '"surfaces": [{"id": "f1", "geometry": {"kind": "tile"}}], '
            '"assignments": [{"source": "s1", "surface": "f1"}]}'
        )
        layout_path.write_text(modified_content)
        # Force a different mtime via os.utime
        import os

        new_mtime = layout_path.stat().st_mtime + 10.0
        os.utime(layout_path, (new_mtime, new_mtime))

        changed = store.reload_changed()
        assert "garage" in changed
        layout = store.get_active()
        assert layout is not None
        assert layout.description == "modified"

    def test_reload_detects_deleted_files(self, tmp_path):
        _write_minimal_layout(tmp_path / "delete-me.json", name="delete-me")
        _write_minimal_layout(tmp_path / "keep-me.json", name="keep-me")
        store = LayoutStore(layout_dir=tmp_path)
        assert set(store.list_available()) == {"delete-me", "keep-me"}

        (tmp_path / "delete-me.json").unlink()
        store.reload_changed()
        assert store.list_available() == ["keep-me"]

    def test_reload_clears_active_when_active_deleted(self, tmp_path):
        _write_minimal_layout(tmp_path / "garage.json", name="garage")
        store = LayoutStore(layout_dir=tmp_path)
        store.set_active("garage")
        assert store.active_name() == "garage"

        (tmp_path / "garage.json").unlink()
        store.reload_changed()
        assert store.active_name() is None
        assert store.get_active() is None

    def test_reload_no_changes_returns_empty_list(self, tmp_path):
        _write_minimal_layout(tmp_path / "stable.json", name="stable")
        store = LayoutStore(layout_dir=tmp_path)
        # First reload after init: no changes (already loaded at construction)
        changed = store.reload_changed()
        assert changed == []


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_get_active_during_reload(self, tmp_path):
        _write_minimal_layout(tmp_path / "alpha.json", name="alpha")
        store = LayoutStore(layout_dir=tmp_path)
        store.set_active("alpha")

        results: list[bool] = []

        def reader():
            for _ in range(50):
                layout = store.get_active()
                results.append(layout is not None and layout.name == "alpha")

        def reloader():
            for _ in range(20):
                store.reload_changed()

        readers = [threading.Thread(target=reader) for _ in range(5)]
        reloaders = [threading.Thread(target=reloader) for _ in range(2)]
        for t in readers + reloaders:
            t.start()
        for t in readers + reloaders:
            t.join()

        assert all(results)
        assert len(results) == 250


# ---------------------------------------------------------------------------
# Garage-door integration
# ---------------------------------------------------------------------------


class TestGarageDoorIntegration:
    """The default LayoutStore should find the garage-door layout."""

    def test_default_dir_finds_garage_door(self):
        """When LayoutStore is constructed with no args, it should resolve
        the in-tree config/layouts/ directory and find garage-door."""
        store = LayoutStore()
        available = store.list_available()
        # garage-door must be present (it's the canonical fixture)
        assert "garage-door" in available, (
            f"Expected garage-door layout in {store.layout_dir}, got: {available}"
        )

    def test_garage_door_can_be_set_active(self):
        store = LayoutStore()
        assert store.set_active("garage-door") is True
        layout = store.get_active()
        assert layout is not None
        assert layout.name == "garage-door"
        # Has the expected counts from Phase 2a
        camera_sources = [s for s in layout.sources if s.kind == "camera"]
        assert len(camera_sources) == 6
