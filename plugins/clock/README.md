# Clock Plugin

Reference compositor plugin for the hapax-council Phase 6 plugin
system. Renders the current time as a text overlay using strftime
formatting.

This is a **template** — copy this directory to `plugins/your_widget/`
and edit `manifest.json` + `source.py` to author your own plugin.

## Files

- `manifest.json` — declarative metadata + parameter schema. Loaded
  by `PluginRegistry` at startup. Required.
- `source.py` — Python lifecycle. Implements the `CairoSource`
  protocol. Lazy-imported via `manifest.source_module`.
- `README.md` — this file. Optional but recommended.

## Authoring a new plugin

1. Copy this directory:
   ```sh
   cp -r plugins/clock plugins/my_widget
   ```

2. Edit `plugins/my_widget/manifest.json`:
   - Set `name` to `my_widget` (must match the directory name).
   - Set `version` to `0.1.0` (semver).
   - Set `description`, `author`, and `params`.
   - Update `source_module` to `plugins.my_widget.source`.

3. Edit `plugins/my_widget/source.py`:
   - Rename `ClockSource` to your plugin's class.
   - Implement the `render(cr, w, h, t, state)` method per the
     `CairoSource` protocol.
   - Match the constructor's keyword arguments to your manifest's
     `params` keys.

4. Verify the plugin loads:
   ```python
   from agents.studio_compositor.plugin_registry import PluginRegistry
   reg = PluginRegistry()
   loaded, failed = reg.scan()
   assert "my_widget" in reg.list_loaded()
   ```

## Manifest schema

See `shared/plugin_manifest.py::PluginManifest` for the canonical
Pydantic schema. Strict validation (`extra="forbid"`) catches
typos in field names at load time. Failed validations are logged
and the plugin is skipped — the compositor never crashes on a
malformed manifest.

The clock plugin's manifest declares:

- `kind: text` — slots into the text source pipeline
- `backend: text` — uses the Phase 3c shared Pango render helper
- `params.format` — strftime string, defaults to `%H:%M:%S`
- `params.font_family` — Pango font name, defaults to `JetBrains Mono`
- `params.font_size_pt` — float in [6, 144], defaults to 24

## Lifecycle

`PluginRegistry.scan()` does NOT import `source.py` — that's lazy.
The operator's compositor code is responsible for instantiating
the source class when the plugin is actually used in a layout.

A `CairoSourceRunner` (from Phase 3b) typically wraps the source
to drive it on a background thread:

```python
from plugins.clock.source import ClockSource
from agents.studio_compositor.cairo_source import CairoSourceRunner

source = ClockSource(format="%H:%M", font_size_pt=48.0)
runner = CairoSourceRunner(
    source_id="clock-overlay",
    source=source,
    canvas_w=400,
    canvas_h=80,
    target_fps=2.0,  # clock ticks twice a second
)
runner.start()
```

## See also

- Spec: `docs/superpowers/specs/2026-04-12-phase-6-plugin-system-design.md`
- Manifest schema: `shared/plugin_manifest.py`
- Registry: `agents/studio_compositor/plugin_registry.py`
- CairoSource protocol: `agents/studio_compositor/cairo_source.py`
- Shared text helper: `agents/studio_compositor/text_render.py`
