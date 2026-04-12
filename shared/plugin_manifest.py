"""Plugin manifest schema — the contract every compositor plugin honors.

Phase 6 of the compositor unification epic. Loaded by
:class:`agents.studio_compositor.plugin_registry.PluginRegistry` from
``plugins/{name}/manifest.json`` files. Validation is strict
(``extra="forbid"``) so typos in field names surface immediately
instead of silently becoming dead state.

A new compositor plugin is a directory with three files:

* ``manifest.json`` — this schema, declaring metadata + params
* ``source.py`` — Python lifecycle (lazy-imported on instantiation)
* ``README.md`` — author docs

The Cargo plugins already living under ``plugins/`` (gst-crossfade,
gst-smooth-delay, gst-temporalfx) have ``Cargo.toml`` only — no
``manifest.json`` — so the registry's discovery rule silently skips
them.

See: docs/superpowers/specs/2026-04-12-phase-6-plugin-system-design.md
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Same SourceKind as :class:`shared.compositor_model.SourceSchema`. The
# plugin's kind determines which built-in pipeline it slots into. New
# kinds are added in lockstep here and in compositor_model so the
# Layout schema can reference plugin sources by kind without ambiguity.
PluginKind = Literal[
    "camera",
    "video",
    "shader",
    "image",
    "text",
    "cairo",
    "external_rgba",
    "ndi",
    "generative",
]

PluginParamType = Literal["float", "int", "bool", "string", "enum"]


class PluginParam(BaseModel):
    """One parameter the plugin exposes for layout/UI configuration.

    The schema is intentionally minimal — type, default, optional
    range/enum bounds, optional description. Phase 6 surfaces this
    via the registry; Phase 6's UI follow-up will turn the schema
    into typed form fields.
    """

    model_config = ConfigDict(extra="forbid")

    type: PluginParamType
    default: Any
    min: float | None = None
    max: float | None = None
    enum_values: list[str] | None = None
    description: str = ""


class PluginManifest(BaseModel):
    """Top-level plugin manifest. Maps 1:1 onto ``plugins/{name}/manifest.json``.

    Fields:
        name: Plugin name. MUST equal the parent directory name; the
            registry rejects manifests where these disagree.
        version: Semver string (``MAJOR.MINOR.PATCH``).
        kind: One of the canonical SourceKind values. Determines which
            built-in pipeline this plugin slots into.
        backend: Backend dispatcher key from Phase 3 (e.g. ``cairo``,
            ``text``, ``image_file``, ``wgsl_render``).
        description: Human-readable summary, surfaced in operator UIs.
        author: Plugin author identifier.
        license: SPDX license expression (e.g. ``MIT``, ``Apache-2.0``).
        params: Named parameter schemas for layout/UI configuration.
        source_module: Optional dotted Python module to import when
            the plugin is instantiated. Lazy — :meth:`PluginRegistry.scan`
            does NOT import this; the operator's compositor code does.
        shader: Optional WGSL file path relative to the plugin
            directory. Used when ``backend`` is a wgsl_* dispatcher.
        tags: Free-form labels for filtering / discovery.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=64)
    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    kind: PluginKind
    backend: str = Field(..., min_length=1, max_length=64)
    description: str = ""
    author: str = ""
    license: str = ""
    params: dict[str, PluginParam] = Field(default_factory=dict)
    source_module: str | None = None
    shader: str | None = None
    tags: list[str] = Field(default_factory=list)
