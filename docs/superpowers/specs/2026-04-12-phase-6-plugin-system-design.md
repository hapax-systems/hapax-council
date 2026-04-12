# Phase 6: Plugin System — Design Spec

**Date:** 2026-04-12
**Status:** Approved (self-authored, alpha session)
**Epic:** `docs/superpowers/plans/2026-04-12-compositor-unification-epic.md`
**Phase:** 6 of 7
**Risk:** Low (purely additive; no rendering paths touched)
**Depends on:** Phase 3 complete (executor polymorphism — backends + cairo + text + image)

---

## Purpose

Formalize the plugin contract for compositor content sources so adding
a new content type is a one-directory drop instead of a Python class
edit in `agents/studio_compositor/`. Phase 3 lifted Cairo, text, and
image rendering into shared backends; Phase 6 lifts the *registration*
plane so new sources can be authored, validated, and discovered
without touching the compositor's internals.

After Phase 6:

- A plugin author creates `plugins/{name}/` with `manifest.json` +
  `source.py` (+ optional `shader.wgsl`, `README.md`).
- The compositor scans `plugins/` at startup, loads each
  `manifest.json`, validates it via Pydantic, and registers the
  plugin in a `PluginRegistry`.
- Layouts can reference plugin sources by name. The unified
  semantic recruitment system (`AffordancePipeline`) can recruit
  them.
- Malformed manifests are logged and skipped — they don't crash the
  compositor.
- A reference clock widget plugin demonstrates the contract end-to-end.

This phase is **purely additive**. The existing built-in sources
(camera, video, shader, image, text, cairo, external_rgba) continue
to work unchanged. Plugins are an *extension* mechanism, not a
replacement for the built-ins.

---

## Coexistence with the existing `plugins/` directory

The repo already has a `plugins/` directory at the root holding three
Rust GStreamer plugins (`gst-crossfade`, `gst-smooth-delay`,
`gst-temporalfx`), each with a `Cargo.toml`. These are an entirely
different runtime (Rust dynamic libraries loaded by GStreamer at
boot) and must not be touched by the compositor plugin scanner.

The discovery rule: **a directory under `plugins/` is a compositor
plugin iff it contains a top-level `manifest.json` file.** Cargo
plugins have `Cargo.toml` and no `manifest.json`, so they're
silently ignored. New compositor plugins must include `manifest.json`
to be discovered.

---

## Scope

Three sub-phases per the master plan, **shipped as one PR** in this
round because the pieces are tightly coupled:

1. **Phase 6a — Plugin directory + discovery.** `PluginRegistry`
   class scans `plugins/` for `manifest.json` files at startup.
   Each manifest is loaded, validated, and registered. mtime-based
   reload supported via a `reload_changed()` method analogous to
   `LayoutStore` (Phase 2c).

2. **Phase 6b — Manifest validation.** `PluginManifest` Pydantic
   model defines the canonical schema. Validation errors are caught,
   logged with context, and the offending plugin is skipped. The
   `loaded` count and `failed` list are exposed via the registry
   for observability.

3. **Phase 6c — Reference plugin.** `plugins/clock/` ships as the
   end-to-end example: a clock widget that renders the current time
   as text. Includes `manifest.json`, `source.py` (lifecycle stub),
   and `README.md` (plugin authoring guide).

The combined PR is small enough (~400 lines net) that splitting
would create artificial seams. Each piece is independently testable
within the single PR.

---

## File structure

| File | Purpose |
|---|---|
| `shared/plugin_manifest.py` | `PluginManifest` Pydantic model |
| `agents/studio_compositor/plugin_registry.py` | `PluginRegistry` + `LoadedPlugin` |
| `plugins/clock/manifest.json` | Reference plugin metadata |
| `plugins/clock/source.py` | Reference plugin lifecycle stub |
| `plugins/clock/README.md` | Plugin authoring guide |
| `tests/test_plugin_registry.py` | 12+ unit tests |

---

## PluginManifest schema

```python
"""Plugin manifest schema — the contract every compositor plugin honors.

Phase 6 of the compositor unification epic. Loaded by PluginRegistry
from plugins/{name}/manifest.json files. Validation is strict
(extra="forbid") so typos surface immediately instead of silently
becoming dead state.
"""

from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

# Same SourceKind as compositor_model.SourceSchema. The plugin's kind
# determines which built-in pipeline it slots into.
PluginKind = Literal[
    "camera", "video", "shader", "image", "text", "cairo",
    "external_rgba", "ndi", "generative",
]


class PluginParam(BaseModel):
    """One parameter the plugin exposes for layout/UI configuration."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["float", "int", "bool", "string", "enum"]
    default: Any
    min: float | None = None
    max: float | None = None
    enum_values: list[str] | None = None
    description: str = ""


class PluginManifest(BaseModel):
    """Top-level plugin manifest. Maps 1:1 onto plugins/{name}/manifest.json."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=64)
    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    kind: PluginKind
    backend: str
    description: str = ""
    author: str = ""
    license: str = ""
    params: dict[str, PluginParam] = Field(default_factory=dict)
    source_module: str | None = None  # dotted Python module to lazy-import
    shader: str | None = None  # WGSL file relative to plugin dir
    tags: list[str] = Field(default_factory=list)
```

The model uses `extra="forbid"` so a misspelled field (e.g.
`paramz` instead of `params`) raises a ValidationError on load,
caught by the registry and logged.

---

## PluginRegistry

```python
"""PluginRegistry — discovers, validates, and exposes compositor plugins.

Phase 6 of the compositor unification epic. Walks plugins/{name}/
at startup and on each reload tick, loads manifest.json files,
validates them via Pydantic, and stores LoadedPlugin instances
keyed by name.

A directory under plugins/ is a compositor plugin iff it contains
a top-level manifest.json file. Existing Rust/Cargo plugins
(gst-crossfade, gst-smooth-delay, gst-temporalfx) have no
manifest.json and are silently ignored.
"""

from __future__ import annotations
import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from shared.plugin_manifest import PluginManifest

log = logging.getLogger(__name__)


@dataclass
class LoadedPlugin:
    """A plugin that successfully loaded into the registry."""
    name: str
    manifest: PluginManifest
    plugin_dir: Path
    manifest_mtime: float


@dataclass
class FailedPlugin:
    """A plugin whose manifest failed to load. Kept for observability."""
    name: str
    plugin_dir: Path
    error: str


class PluginRegistry:
    def __init__(self, plugins_dir: Path | None = None) -> None: ...
    def scan(self) -> tuple[int, int]: ...  # (loaded, failed)
    def get(self, name: str) -> LoadedPlugin | None: ...
    def list_loaded(self) -> list[str]: ...
    def list_failed(self) -> list[FailedPlugin]: ...
    def reload_changed(self) -> list[str]: ...  # mtime-based
```

### Discovery rule

```python
def _is_plugin_dir(self, candidate: Path) -> bool:
    """A directory is a plugin iff it has a top-level manifest.json."""
    return candidate.is_dir() and (candidate / "manifest.json").is_file()
```

The scanner walks `plugins_dir.iterdir()` and applies this filter.
Anything else (Cargo.toml-only dirs, hidden files, READMEs at the
plugin root) is ignored.

### Validation flow

```python
def _load_one(self, plugin_dir: Path) -> LoadedPlugin | FailedPlugin:
    name = plugin_dir.name
    manifest_path = plugin_dir / "manifest.json"
    try:
        raw = json.loads(manifest_path.read_text())
        manifest = PluginManifest.model_validate(raw)
    except json.JSONDecodeError as exc:
        return FailedPlugin(name=name, plugin_dir=plugin_dir,
                            error=f"json: {exc}")
    except Exception as exc:
        return FailedPlugin(name=name, plugin_dir=plugin_dir,
                            error=f"validation: {exc}")
    if manifest.name != name:
        return FailedPlugin(name=name, plugin_dir=plugin_dir,
                            error=f"manifest.name {manifest.name!r} != "
                                  f"directory name {name!r}")
    return LoadedPlugin(name=name, manifest=manifest,
                        plugin_dir=plugin_dir,
                        manifest_mtime=manifest_path.stat().st_mtime)
```

Manifest name must match the directory name — this prevents
plugins from claiming each other's identifiers and gives the
operator a single, stable lookup key.

### Hot-reload

```python
def reload_changed(self) -> list[str]:
    """Re-scan the plugins directory; return names of changed plugins.

    Called from a periodic tick (1Hz) analogous to LayoutStore
    .reload_changed(). New plugins are added; deleted plugins are
    removed; modified manifests trigger a re-validation.
    """
```

### Default plugins directory

```python
def _default_plugins_dir() -> Path:
    """Resolve the plugins/ directory at the repo root.

    Walks up from this module until it finds a sibling 'plugins'
    directory. Returns ``$REPO/plugins`` for the in-tree case.
    """
```

Same lookup pattern as `LayoutStore._default_layout_dir()` from
Phase 2c.

---

## Reference plugin: `plugins/clock/`

### `plugins/clock/manifest.json`

```json
{
  "name": "clock",
  "version": "0.1.0",
  "kind": "text",
  "backend": "text",
  "description": "Renders the current time as a text overlay.",
  "author": "hapax-council",
  "license": "MIT",
  "params": {
    "format": {
      "type": "string",
      "default": "%H:%M:%S",
      "description": "strftime format string. Default 24h HH:MM:SS."
    },
    "font_family": {
      "type": "string",
      "default": "JetBrains Mono",
      "description": "Pango font family."
    },
    "font_size_pt": {
      "type": "float",
      "default": 24.0,
      "min": 6.0,
      "max": 144.0,
      "description": "Font size in points."
    }
  },
  "source_module": "plugins.clock.source",
  "tags": ["text", "widget", "time"]
}
```

### `plugins/clock/source.py`

```python
"""Reference plugin: clock widget.

Renders the current time as text using the shared text_render helper.
This is a thin example showing the plugin lifecycle contract — a
plugin source provides:

  - render(cr, w, h, t, state): draw into a Cairo context per tick

Phase 6c of the compositor unification epic. Plugin authors copy
this directory as a starting template.
"""

from __future__ import annotations
import time
from typing import Any
import cairo

from agents.studio_compositor.cairo_source import CairoSource
from agents.studio_compositor.text_render import TextStyle, render_text


class ClockSource(CairoSource):
    """A CairoSource that renders the current time on every tick."""

    def __init__(
        self,
        format: str = "%H:%M:%S",
        font_family: str = "JetBrains Mono",
        font_size_pt: float = 24.0,
    ) -> None:
        self._format = format
        self._font = f"{font_family} {int(font_size_pt)}"

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        text = time.strftime(self._format)
        style = TextStyle(
            text=text,
            font_description=self._font,
            color_rgba=(1.0, 1.0, 1.0, 1.0),
            outline_color_rgba=(0.0, 0.0, 0.0, 0.85),
        )
        render_text(cr, style, x=8, y=8)
```

### `plugins/clock/README.md`

Short authoring guide: how to copy the directory as a template, what
to put in `manifest.json`, what `source.py` should implement, how to
test locally with `PluginRegistry().scan()`. Half a page.

---

## Tests

`tests/test_plugin_registry.py`:

### Discovery tests
- `test_registry_loads_plugin_with_valid_manifest`
- `test_registry_skips_directory_without_manifest` (Cargo plugins)
- `test_registry_skips_invalid_json`
- `test_registry_skips_manifest_with_validation_error`
- `test_registry_records_failed_plugins_for_observability`
- `test_registry_default_plugins_dir_resolves_repo_root`

### Validation tests
- `test_manifest_extra_field_rejected` (extra="forbid")
- `test_manifest_invalid_version_format_rejected`
- `test_manifest_invalid_kind_rejected`
- `test_manifest_name_must_match_directory_name`

### Hot-reload tests
- `test_reload_detects_modified_manifest`
- `test_reload_detects_added_plugin`
- `test_reload_detects_deleted_plugin`

### Reference plugin smoke tests
- `test_clock_plugin_loads_from_disk` — the actual `plugins/clock/`
  manifest validates against the registry
- `test_clock_source_renders_into_canvas` — instantiate ClockSource,
  call render() with a small surface, verify non-zero pixel output
  (skipped if Pango unavailable)

---

## Acceptance

- `shared/plugin_manifest.py::PluginManifest` exists with strict
  validation
- `agents/studio_compositor/plugin_registry.py::PluginRegistry`
  exists with scan/get/list/reload methods
- `plugins/clock/` ships as the reference plugin (manifest +
  source + README)
- The Cargo plugins (`gst-crossfade`, `gst-smooth-delay`,
  `gst-temporalfx`) are silently ignored by the scanner
- All Phase 6 tests pass (~14 new tests)
- `uv run ruff check` clean
- `uv run pyright` clean
- No rendering code is modified — this is purely additive

---

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Plugin discovery loads the existing GStreamer Cargo plugins | Low | Medium | Discovery rule requires manifest.json; Cargo plugins have only Cargo.toml |
| Plugin name collisions go unreported | Low | Low | Manifest name must match directory name; directory names are unique by filesystem |
| Hot-reload causes crashes when a plugin is half-edited | Low | Low | Validation errors are caught and logged; the previous LoadedPlugin stays in the registry until the new one validates |
| Lazy import of source_module raises at instantiation time | Medium | Low | source_module is documented as lazy; scan() doesn't import it; instantiation is the operator's responsibility |
| Manifest schema needs new fields later | High | Low | Pydantic models extend forward-compatibly; new optional fields don't break existing manifests |

---

## Not in scope

Phase 6 does not:

- Wire plugins into the unified semantic recruitment system
  (deferred to a follow-up — plugins are discoverable but not
  yet recruited)
- Auto-instantiate plugin source classes (lazy load only — the
  operator's compositor code is responsible for instantiation)
- Schema-driven UI form generation (Phase 6's manifest schema is
  the data source; the UI consumer is a follow-up)
- Plugin sandboxing or capability gating (single-operator system —
  no auth boundary needed)
- Plugin signing or trust verification (single-operator)
- Hot-reload of `source.py` Python files (only manifest changes;
  Python code reload requires importlib magic that's out of scope)

---

## Success metrics

Phase 6 is complete when:

- `PluginRegistry().scan()` discovers `plugins/clock/` and rejects
  malformed manifests
- The clock plugin's `ClockSource` instantiates and renders text
  into a Cairo surface
- The Cargo plugins are not picked up
- All 14 tests pass
- A new operator can copy `plugins/clock/` to `plugins/my_widget/`,
  edit the manifest, and have it appear in the next `scan()` call
