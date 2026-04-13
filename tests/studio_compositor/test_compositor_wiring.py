"""Phase D task 14 — StudioCompositor LayoutState + SourceRegistry wiring.

These tests exercise ``StudioCompositor.start_layout_only`` without
touching GStreamer so the Layout wiring can be validated on any
machine without a display, GPU, or v4l2 device nodes. The production
path runs this same helper from ``StudioCompositor.start`` before the
lifecycle pulls in the GStreamer bits, so whatever these tests lock in
also locks in the production wiring.

Source-registry epic Phase D task 14. See
``docs/superpowers/plans/2026-04-12-compositor-source-registry-foundation-plan.md``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

from agents.studio_compositor.compositor import StudioCompositor
from agents.studio_compositor.config import _default_config
from tests.studio_compositor.test_default_layout_loading import DEFAULT_JSON

if TYPE_CHECKING:
    import pytest


def _make_compositor(layout_path: Path | None = None) -> StudioCompositor:
    """Construct a compositor with a minimal config, patching load_camera_profiles.

    ``StudioCompositor.__init__`` calls ``load_camera_profiles`` eagerly, which
    opens ``~/.config/hapax-compositor/profiles.yaml`` if it exists. In CI and
    on fresh workstations, the file may be absent or carry an unrelated schema
    — neither is a bug in this test's scope. Patch the loader to a no-op so the
    test exercises the Layout wiring and nothing else.
    """
    with mock.patch(
        "agents.studio_compositor.compositor.load_camera_profiles",
        return_value=[],
    ):
        return StudioCompositor(_default_config(), layout_path=layout_path)


class TestStartLayoutOnly:
    """Happy-path, fallback, and idempotency coverage."""

    def test_reads_disk_layout_and_populates_state_and_registry(self, tmp_path: Path) -> None:
        layout_file = tmp_path / "default.json"
        layout_file.write_text(DEFAULT_JSON.read_text())

        compositor = _make_compositor(layout_path=layout_file)
        compositor.start_layout_only()

        assert compositor.layout_state is not None
        assert compositor.source_registry is not None

        layout = compositor.layout_state.get()
        assert layout.name == "default"
        assert {s.id for s in layout.sources} == {
            "token_pole",
            "album",
            "sierpinski",
            "reverie",
        }
        assert set(compositor.source_registry.ids()) == {
            "token_pole",
            "album",
            "sierpinski",
            "reverie",
        }

    def test_missing_layout_file_resolves_to_fallback(self, tmp_path: Path) -> None:
        """Missing on-disk layout must NOT stop the compositor from booting."""
        compositor = _make_compositor(layout_path=tmp_path / "does-not-exist.json")
        compositor.start_layout_only()

        assert compositor.layout_state is not None
        layout = compositor.layout_state.get()
        assert layout.name == "default"
        assert set(compositor.source_registry.ids()) == {
            "token_pole",
            "album",
            "sierpinski",
            "reverie",
        }

    def test_broken_json_resolves_to_fallback(self, tmp_path: Path) -> None:
        broken = tmp_path / "broken.json"
        broken.write_text("{not json")

        compositor = _make_compositor(layout_path=broken)
        compositor.start_layout_only()

        assert compositor.layout_state is not None
        assert compositor.layout_state.get().name == "default"

    def test_idempotent_when_called_twice(self, tmp_path: Path) -> None:
        """Calling start_layout_only twice must not re-register sources."""
        layout_file = tmp_path / "default.json"
        layout_file.write_text(DEFAULT_JSON.read_text())

        compositor = _make_compositor(layout_path=layout_file)
        compositor.start_layout_only()

        first_state = compositor.layout_state
        first_registry = compositor.source_registry

        compositor.start_layout_only()

        assert compositor.layout_state is first_state
        assert compositor.source_registry is first_registry

    def test_default_layout_path_is_repo_relative(self, tmp_path: Path) -> None:
        """Unconstructed compositor resolves ``config/compositor-layouts/default.json``."""
        compositor = _make_compositor()
        assert compositor._layout_path == Path("config/compositor-layouts/default.json")

    def test_continues_past_broken_source_backend(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A source with an unknown backend must log + skip, not crash."""
        import logging

        raw = json.loads(DEFAULT_JSON.read_text())
        raw["sources"].append(
            {
                "id": "broken",
                "kind": "cairo",
                "backend": "cairo",
                "params": {"class_name": "DoesNotExist"},
            }
        )
        layout_file = tmp_path / "default.json"
        layout_file.write_text(json.dumps(raw))

        compositor = _make_compositor(layout_path=layout_file)
        caplog.set_level(logging.ERROR, logger="agents.studio_compositor.compositor")
        compositor.start_layout_only()

        assert compositor.source_registry is not None
        assert "broken" not in compositor.source_registry.ids()
        assert {"token_pole", "album", "sierpinski", "reverie"}.issubset(
            set(compositor.source_registry.ids())
        )
        assert any("failed to construct backend" in rec.message for rec in caplog.records)


class TestStartDelegatesThroughStartLayoutOnly:
    """The full ``start()`` path must invoke ``start_layout_only()`` before GStreamer."""

    def test_start_invokes_layout_loader_before_lifecycle(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        layout_file = tmp_path / "default.json"
        layout_file.write_text(DEFAULT_JSON.read_text())

        compositor = _make_compositor(layout_path=layout_file)

        calls: list[str] = []
        original_layout_only = compositor.start_layout_only

        def _tracking_layout_only() -> None:
            calls.append("layout_only")
            original_layout_only()

        compositor.start_layout_only = _tracking_layout_only  # type: ignore[method-assign]

        fake_lifecycle = mock.Mock()

        def _track_lifecycle(c: StudioCompositor) -> None:
            calls.append("lifecycle")
            fake_lifecycle(c)

        monkeypatch.setattr(
            "agents.studio_compositor.lifecycle.start_compositor",
            _track_lifecycle,
        )

        compositor.start()

        assert calls == ["layout_only", "lifecycle"]
        assert compositor.layout_state is not None
        assert compositor.source_registry is not None
        fake_lifecycle.assert_called_once_with(compositor)
