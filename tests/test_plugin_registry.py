"""Tests for the Phase 6 plugin system.

Covers:

- PluginRegistry discovery (loading manifests, skipping non-plugin dirs)
- PluginManifest validation (schema enforcement, error messages)
- Hot-reload (mtime-based, add/modify/delete detection)
- Reference clock plugin smoke tests
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agents.studio_compositor.plugin_registry import (
    FailedPlugin,
    LoadedPlugin,
    PluginRegistry,
    _default_plugins_dir,
)
from shared.plugin_manifest import PluginManifest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_manifest_dict(name: str = "test_plugin") -> dict:
    """Return a minimal valid manifest dict for ``name``."""
    return {
        "name": name,
        "version": "1.0.0",
        "kind": "text",
        "backend": "text",
        "description": "test plugin",
        "params": {},
    }


def _write_plugin(plugins_dir: Path, name: str, manifest: dict | None = None) -> Path:
    """Materialize a plugin directory under ``plugins_dir``."""
    plugin_dir = plugins_dir / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest_data = manifest if manifest is not None else _valid_manifest_dict(name)
    (plugin_dir / "manifest.json").write_text(json.dumps(manifest_data))
    return plugin_dir


# ---------------------------------------------------------------------------
# PluginManifest validation
# ---------------------------------------------------------------------------


def test_manifest_validates_minimal_valid_dict():
    manifest = PluginManifest.model_validate(_valid_manifest_dict("clock"))
    assert manifest.name == "clock"
    assert manifest.version == "1.0.0"
    assert manifest.kind == "text"
    assert manifest.backend == "text"


def test_manifest_extra_field_rejected():
    """extra='forbid' must catch typoed field names at validation time."""
    raw = _valid_manifest_dict("typo")
    raw["paramz"] = {}  # typo for "params"
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(raw)


def test_manifest_invalid_version_format_rejected():
    """Version must match semver MAJOR.MINOR.PATCH."""
    raw = _valid_manifest_dict("badver")
    raw["version"] = "v1"
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(raw)


def test_manifest_invalid_kind_rejected():
    """kind must be one of the canonical SourceKind literals."""
    raw = _valid_manifest_dict("badkind")
    raw["kind"] = "not-a-real-kind"
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(raw)


def test_manifest_param_extra_field_rejected():
    """PluginParam is also extra='forbid'."""
    raw = _valid_manifest_dict("badparam")
    raw["params"] = {
        "x": {
            "type": "float",
            "default": 1.0,
            "wrongkey": True,  # not a known field
        }
    }
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(raw)


def test_manifest_optional_fields_have_sensible_defaults():
    """description/author/license/params/tags all default to empty
    structures so a manifest with only required fields validates."""
    raw = {
        "name": "minimal",
        "version": "0.0.1",
        "kind": "text",
        "backend": "text",
    }
    manifest = PluginManifest.model_validate(raw)
    assert manifest.description == ""
    assert manifest.author == ""
    assert manifest.license == ""
    assert manifest.params == {}
    assert manifest.tags == []
    assert manifest.source_module is None
    assert manifest.shader is None


# ---------------------------------------------------------------------------
# PluginRegistry discovery
# ---------------------------------------------------------------------------


def test_registry_loads_plugin_with_valid_manifest(tmp_path: Path):
    plugin_dir = _write_plugin(tmp_path, "alpha")
    reg = PluginRegistry(plugins_dir=tmp_path)
    loaded, failed = reg.scan()
    assert loaded == 1
    assert failed == 0
    plugin = reg.get("alpha")
    assert isinstance(plugin, LoadedPlugin)
    assert plugin.name == "alpha"
    assert plugin.plugin_dir == plugin_dir
    assert plugin.manifest.kind == "text"


def test_registry_skips_directory_without_manifest(tmp_path: Path):
    """A directory under plugins/ without a manifest.json is silently
    ignored — this is how the existing Cargo plugins coexist."""
    cargo_like = tmp_path / "gst-fake"
    cargo_like.mkdir()
    (cargo_like / "Cargo.toml").write_text("[package]\nname = 'gst-fake'\n")
    reg = PluginRegistry(plugins_dir=tmp_path)
    loaded, failed = reg.scan()
    assert loaded == 0
    assert failed == 0


def test_registry_skips_invalid_json(tmp_path: Path):
    plugin_dir = tmp_path / "broken"
    plugin_dir.mkdir()
    (plugin_dir / "manifest.json").write_text("{not valid json")
    reg = PluginRegistry(plugins_dir=tmp_path)
    loaded, failed = reg.scan()
    assert loaded == 0
    assert failed == 1
    failed_list = reg.list_failed()
    assert len(failed_list) == 1
    assert isinstance(failed_list[0], FailedPlugin)
    assert failed_list[0].name == "broken"
    assert "json" in failed_list[0].error.lower()


def test_registry_skips_manifest_with_validation_error(tmp_path: Path):
    raw = _valid_manifest_dict("badkind")
    raw["kind"] = "totally-fake"
    _write_plugin(tmp_path, "badkind", manifest=raw)
    reg = PluginRegistry(plugins_dir=tmp_path)
    loaded, failed = reg.scan()
    assert loaded == 0
    assert failed == 1
    assert "validation" in reg.list_failed()[0].error


def test_registry_rejects_manifest_name_directory_mismatch(tmp_path: Path):
    """The manifest's name field must equal the directory name."""
    raw = _valid_manifest_dict("claimed_name")  # but directory is 'actual_name'
    _write_plugin(tmp_path, "actual_name", manifest=raw)
    reg = PluginRegistry(plugins_dir=tmp_path)
    loaded, failed = reg.scan()
    assert loaded == 0
    assert failed == 1
    assert "directory name" in reg.list_failed()[0].error


def test_registry_loads_multiple_plugins(tmp_path: Path):
    _write_plugin(tmp_path, "alpha")
    _write_plugin(tmp_path, "beta")
    _write_plugin(tmp_path, "gamma")
    reg = PluginRegistry(plugins_dir=tmp_path)
    loaded, _ = reg.scan()
    assert loaded == 3
    assert reg.list_loaded() == ["alpha", "beta", "gamma"]


def test_registry_handles_missing_plugins_dir():
    """A nonexistent plugins/ directory is not an error — just zero loaded."""
    reg = PluginRegistry(plugins_dir=Path("/nonexistent/path/to/plugins"))
    loaded, failed = reg.scan()
    assert loaded == 0
    assert failed == 0


def test_default_plugins_dir_resolves_to_repo_root():
    """_default_plugins_dir() finds the in-tree plugins/ directory."""
    plugins_dir = _default_plugins_dir()
    # The repo's plugins/ exists (Cargo plugins live there even when no
    # compositor plugin is present). The default lookup must find it.
    assert plugins_dir.is_dir()
    assert plugins_dir.name == "plugins"


# ---------------------------------------------------------------------------
# Hot-reload
# ---------------------------------------------------------------------------


def test_reload_changed_returns_empty_when_nothing_changes(tmp_path: Path):
    _write_plugin(tmp_path, "stable")
    reg = PluginRegistry(plugins_dir=tmp_path)
    reg.scan()
    changed = reg.reload_changed()
    assert changed == []


def test_reload_detects_added_plugin(tmp_path: Path):
    _write_plugin(tmp_path, "first")
    reg = PluginRegistry(plugins_dir=tmp_path)
    reg.scan()
    _write_plugin(tmp_path, "second")
    changed = reg.reload_changed()
    assert "second" in changed
    assert "second" in reg.list_loaded()


def test_reload_detects_modified_manifest(tmp_path: Path):
    plugin_dir = _write_plugin(tmp_path, "evolving")
    reg = PluginRegistry(plugins_dir=tmp_path)
    reg.scan()
    # Write a new manifest with a different description; bump mtime to
    # ensure the reload detects it (filesystem timestamp resolution
    # can be 1s on some platforms).
    import os
    import time

    new_raw = _valid_manifest_dict("evolving")
    new_raw["description"] = "updated"
    (plugin_dir / "manifest.json").write_text(json.dumps(new_raw))
    new_mtime = (plugin_dir / "manifest.json").stat().st_mtime + 5.0
    os.utime(plugin_dir / "manifest.json", (new_mtime, new_mtime))
    time.sleep(0)  # no-op; we use os.utime instead of relying on real time

    changed = reg.reload_changed()
    assert "evolving" in changed
    plugin = reg.get("evolving")
    assert plugin is not None
    assert plugin.manifest.description == "updated"


def test_reload_detects_deleted_plugin(tmp_path: Path):
    plugin_dir = _write_plugin(tmp_path, "deleteme")
    reg = PluginRegistry(plugins_dir=tmp_path)
    reg.scan()
    assert "deleteme" in reg.list_loaded()
    # Remove the plugin's manifest so the discovery rule no longer matches
    (plugin_dir / "manifest.json").unlink()
    changed = reg.reload_changed()
    assert "deleteme" in changed
    assert "deleteme" not in reg.list_loaded()


# ---------------------------------------------------------------------------
# Reference clock plugin smoke
# ---------------------------------------------------------------------------


def test_clock_plugin_loads_from_repo():
    """The shipped plugins/clock/ manifest validates against the registry."""
    reg = PluginRegistry()  # default = repo plugins/
    reg.scan()
    clock = reg.get("clock")
    assert isinstance(clock, LoadedPlugin)
    assert clock.manifest.kind == "text"
    assert clock.manifest.backend == "text"
    assert clock.manifest.source_module == "plugins.clock.source"
    # Default params are present and typed.
    assert "format" in clock.manifest.params
    assert clock.manifest.params["format"].type == "string"
    assert clock.manifest.params["font_size_pt"].type == "float"
    assert clock.manifest.params["font_size_pt"].min == 6.0
    assert clock.manifest.params["font_size_pt"].max == 144.0


def test_clock_source_can_be_constructed_with_defaults():
    """ClockSource instantiates with the manifest's default params.

    This proves the lazy import path works end-to-end: registry loads
    the manifest declaratively, the operator imports the source
    module separately, the class accepts the documented kwargs.
    """
    from plugins.clock.source import ClockSource

    source = ClockSource()
    # Constructor stored the default font/format.
    assert source._format == "%H:%M:%S"  # noqa: SLF001 — test boundary
    assert "JetBrains Mono" in source._font_description  # noqa: SLF001


def _has_pango() -> bool:
    """Match the gating used in test_text_render.py — Pango is only
    available on hosts with the GI typelibs installed (CI runs in a
    minimal container without GTK)."""
    try:
        import gi  # noqa: PLC0415

        gi.require_version("Pango", "1.0")
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import Pango, PangoCairo  # noqa: F401, PLC0415
    except (ImportError, ValueError):
        return False
    return True


@pytest.mark.skipif(not _has_pango(), reason="GI Pango/PangoCairo typelibs not installed")
def test_clock_source_renders_into_canvas():
    """Phase 6 audit fix: the spec required this test alongside the
    constructor smoke check. ClockSource.render() must produce non-zero
    pixel output for the documented default params.

    Verifies the lazy-import + render path end-to-end:
    - text_render.render_text imports Pango at draw time
    - ClockSource builds a TextStyle with the default font
    - time.strftime produces a renderable string
    - Cairo writes pixels into the supplied surface
    """
    import cairo  # noqa: PLC0415

    from plugins.clock.source import ClockSource

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 60)
    cr = cairo.Context(surface)
    source = ClockSource()
    source.render(cr, 200, 60, t=0.0, state={})
    surface.flush()
    data = bytes(surface.get_data())
    # At least one non-zero pixel was drawn — the text outline + body
    # should produce hundreds, but we only need a positive sanity check.
    assert any(b != 0 for b in data), "ClockSource.render() produced an empty surface"
